"""Tests for the review layers: the committee runs by default; --deterministic is audit-only."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer import run_pipeline
from reviewer import pipeline as pipeline_module


# Neutralize the judgment-layer opt-in so best==audit assertions never depend on the developer's shell having an API key or the retrieval flag exported.
_DISABLE_JUDGMENT = mock.patch.dict(
    os.environ, {"OPENAI_API_KEY": "", "REVIEWER_BEST_RETRIEVAL": ""}, clear=False
)


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "eval/papers/clean_val_bpb.md"
EVIDENCE = ROOT / "eval/evidence/clean_val_bpb"
# Lines that legitimately differ between two runs / two output files: 
# the UTC freeze stamp (per run) and the recorded output path (per file).
# Everything else is a pure function of the frozen inputs and the reviewer source.
VOLATILE_RE = re.compile(r"^- (?:Frozen at \(UTC\)|Output path|Review method):.*$", re.M)


def _review(mode: str, out_dir: str) -> str:
    state = run_pipeline(PAPER, EVIDENCE, Path(out_dir) / f"{mode}.md", mode=mode)
    return state.review_markdown


class ModeTests(unittest.TestCase):
    def test_full_review_is_default(self) -> None:
        with _DISABLE_JUDGMENT, tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(PAPER, EVIDENCE, Path(directory) / "d.md")
        self.assertEqual(state.mode, "best")

    def test_unknown_mode_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_pipeline(PAPER, EVIDENCE, Path(directory) / "x.md", mode="turbo")

    def test_deterministic_content_matches_committeeless_default(self) -> None:
        # With the committee unable to run, the default output must carry the same
        # deterministic content as --deterministic — only volatile lines and the
        # Review-method label differ. The label is asserted so a committee-less
        # review can never masquerade as a full committee review.
        with _DISABLE_JUDGMENT, tempfile.TemporaryDirectory() as directory:
            audit_raw = _review("audit", directory)
            best_raw = _review("best", directory)
        self.assertEqual(VOLATILE_RE.sub("", audit_raw), VOLATILE_RE.sub("", best_raw))
        self.assertNotIn("## Scientific Judgment", audit_raw)
        self.assertIn("`--deterministic`", audit_raw)
        self.assertIn("committee did not run", best_raw)

    def test_no_api_key_skips_model_layer_entirely(self) -> None:
        # The suite is hermetic (tests/__init__ scrubs the model env); without a
        # key the model layer must not run at all — no panel call, no provenance,
        # no sidecar — and the deterministic review is the whole output.
        calls: list[int] = []
        original_panel = pipeline_module.run_panel_review
        pipeline_module.run_panel_review = lambda *args, **kwargs: calls.append(1)
        try:
            with _DISABLE_JUDGMENT, tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = run_pipeline(PAPER, EVIDENCE, root / "r.md", mode="best")
                sidecar_exists = (root / "r.audit.md").exists()
        finally:
            pipeline_module.run_panel_review = original_panel
        self.assertEqual(calls, [])
        self.assertEqual(state.review_document, "")
        self.assertEqual(state.committee_provenance, {})
        self.assertFalse(sidecar_exists)

    def test_best_renders_grounded_judgment_when_layer_present(self) -> None:
        # Simulate the loop's future M13+ layer to prove the extension point and
        # the render path work end to end, without perturbing audit determinism.
        original = pipeline_module._apply_judgment_layer

        def _fake_layer(state: pipeline_module.ReviewState) -> pipeline_module.ReviewState:
            state.judgment = {
                "comments": ["Scope is limited to n=2 single-seed runs [claim-001]."]
            }
            return state

        pipeline_module._apply_judgment_layer = _fake_layer
        try:
            with tempfile.TemporaryDirectory() as directory:
                best = _review("best", directory)
        finally:
            pipeline_module._apply_judgment_layer = original
        self.assertIn("## Scientific Judgment", best)
        self.assertIn("Scope is limited to n=2", best)

    def test_best_mode_panel_review_becomes_body_with_audit_sidecar(self) -> None:
        # Drive the panel seam with a fake gated result, without network access
        # or API-key spend: the panel/area-chair markdown must become the review
        # body, its scores must stand, and the deterministic audit (plus panel
        # provenance) must ship as the .audit.md sidecar.
        panel_review = (
            "# Review: Novel Method\n\n"
            "## Summary\n\nThe method is clear, but the empirical scope is narrow.\n\n"
            "## Strengths\n\n- The method is stated clearly.\n\n"
            "## Weaknesses\n\n- The evaluation is limited to one reported setting.\n\n"
            "## Questions for the Authors\n\n1. Can the authors clarify the evaluation choice?\n\n"
            "## Scores\n\n"
            "- Soundness: 2/4 — thin evidence.\n"
            "- Presentation: 3/4 — clear.\n"
            "- Significance: 2/4 — narrow.\n"
            "- Originality: 3/4 — situated.\n"
            "- Overall recommendation: 2/6 — below the bar as presented.\n"
            "- Confidence: 4/5 — self-contained.\n\n"
            "## Ethics and Limitations\n\nNone.\n\n"
            "## Comment\n\nThe scope must widen before acceptance.\n"
        )
        captured: dict[str, object] = {}

        def fake_retrieval(parsed_paper, *args, **kwargs):
            return {
                "check": "novelty-positioning",
                "query": "attention",
                "retrieved": [],
                "traces": [],
                "questions": [
                    {
                        "section": "Questions for the Authors",
                        "stance": "question",
                        "text": "Related prior work arXiv:1706.03762 is not cited.",
                        "references": ["arxiv:1706.03762"],
                    }
                ],
            }

        def fake_panel(paper, annotations, **kwargs):
            captured["annotations"] = annotations
            captured["paper_title"] = kwargs.get("paper_title")
            member = {
                "role": "theorist",
                "ok": True,
                "markdown": panel_review,
                "scores": {
                    "Soundness": 2,
                    "Presentation": 3,
                    "Significance": 2,
                    "Originality": 3,
                    "Overall recommendation": 2,
                    "Confidence": 4,
                },
                "gate": {"ok": True, "status": "checked", "overlap": 1.0},
                "prompt_sha256": "0" * 64,
                "response_sha256": "1" * 64,
            }
            return {
                "ok": True,
                "review_markdown": panel_review,
                "scores": dict(member["scores"]),
                "members": [member],
                "panel": 3,
                "model": "gpt-test",
                "synthesis": "area-chair",
            }

        original_retrieval = pipeline_module.check_novelty_positioning
        original_panel = pipeline_module.run_panel_review
        original_scout = pipeline_module.generate_search_queries
        pipeline_module.check_novelty_positioning = fake_retrieval
        pipeline_module.run_panel_review = fake_panel
        pipeline_module.generate_search_queries = lambda **kwargs: []
        try:
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "gpt-test"}, clear=False), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paper = root / "peer.md"
                paper.write_text(
                    "# Novel Method\n\n## Related Work\n\nWe build on [1] and [2].\n\n## Method\n\n"
                    "We propose a novel architecture. It reports strong accuracy on the benchmarks.\n",
                    encoding="utf-8",
                )
                evidence = root / "ev"
                evidence.mkdir()
                state = run_pipeline(paper, evidence, root / "review.md", mode="best")
                body = (root / "review.md").read_text(encoding="utf-8")
                sidecar = (root / "review.audit.md").read_text(encoding="utf-8")
        finally:
            pipeline_module.check_novelty_positioning = original_retrieval
            pipeline_module.run_panel_review = original_panel
            pipeline_module.generate_search_queries = original_scout

        # The review body IS the panel review: human-shaped, no pipeline mechanics.
        self.assertTrue(body.startswith("# Review: Novel Method"))
        self.assertIn("The evaluation is limited to one reported setting.", body)
        self.assertNotIn("Evidence Trace", body)
        self.assertNotIn("unverifiable", body)
        # The sidecar carries the audit, the neutral tally, and panel provenance,
        # and states plainly that the panel ran and the review lives elsewhere.
        self.assertIn("Evidence Trace", sidecar)
        self.assertIn("Deterministic audit:", sidecar)
        self.assertIn("audit + review panel", sidecar)
        self.assertNotIn("committee did not run", sidecar)
        self.assertIn("Review panel configuration: panel=3", sidecar)
        self.assertIn("Panel Reviews (provenance)", sidecar)
        self.assertIn("theorist (accepted)", sidecar)
        # Panel scores stand (no integrity breach on this clean paper).
        self.assertEqual(state.scores["Overall recommendation"]["value"], 2)
        self.assertEqual(state.scores["Soundness"]["value"], 2)
        self.assertEqual(state.scores["Confidence"]["value"], 4)
        self.assertEqual(state.committee_provenance["layer"], "review-panel")
        self.assertEqual(state.committee_provenance["synthesis"], "area-chair")
        # The panel received the retrieval lead as a neutral annotation and the
        # extracted paper title for the wrong-paper gate.
        self.assertIn(
            "Related prior work arXiv:1706.03762 is not cited.",
            captured["annotations"]["prior_art_leads"],
        )
        self.assertEqual(captured["paper_title"], "Novel Method")

    def test_committee_enabled_without_model_fails_loud(self) -> None:
        # A committee-enabled run (API key present) with no OPENAI_MODEL must raise
        # a clear config error rather than silently downgrading to a weak default.
        with mock.patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": ""}, clear=False
        ), tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as caught:
                _review("best", directory)
        self.assertIn("OPENAI_MODEL", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
