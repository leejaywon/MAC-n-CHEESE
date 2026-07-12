"""Tests for run modes: audit (default, deterministic) and best (judgment hook)."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reviewer import run_pipeline
from reviewer import pipeline as pipeline_module


# Neutralize the judgment-layer opt-in so best==audit assertions never depend on
# the developer's shell having an API key or the retrieval flag exported.
_DISABLE_JUDGMENT = mock.patch.dict(
    os.environ, {"OPENAI_API_KEY": "", "RALPH_BEST_RETRIEVAL": ""}, clear=False
)


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "eval/papers/clean_val_bpb.md"
EVIDENCE = ROOT / "eval/evidence/clean_val_bpb"
# Lines that legitimately differ between two runs / two output files: the UTC
# freeze stamp (per run) and the recorded output path (per file). Everything else
# is a pure function of the frozen inputs and the reviewer source.
VOLATILE_RE = re.compile(r"^- (?:Frozen at \(UTC\)|Output path):.*$", re.M)


def _review(mode: str, out_dir: str) -> str:
    state = run_pipeline(PAPER, EVIDENCE, Path(out_dir) / f"{mode}.md", mode=mode)
    return state.review_markdown


class ModeTests(unittest.TestCase):
    def test_audit_is_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(PAPER, EVIDENCE, Path(directory) / "d.md")
        self.assertEqual(state.mode, "audit")

    def test_unknown_mode_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_pipeline(PAPER, EVIDENCE, Path(directory) / "x.md", mode="turbo")

    def test_best_equals_audit_when_judgment_disabled(self) -> None:
        # With the judgment layer's opt-in unset, best output must equal audit
        # output except for the per-run UTC freeze timestamp.
        with _DISABLE_JUDGMENT, tempfile.TemporaryDirectory() as directory:
            audit = VOLATILE_RE.sub("", _review("audit", directory))
            best = VOLATILE_RE.sub("", _review("best", directory))
        self.assertEqual(audit, best)
        self.assertNotIn("## Scientific Judgment", audit)

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
        self.assertIn("## Scientific Judgment (best mode)", best)
        self.assertIn("Scope is limited to n=2", best)

    def test_best_mode_model_critique_renders_and_calibrates(self) -> None:
        # Drive the full best path with retrieval and the model call faked, so the
        # grounded judgment, the model provenance, and calibration-only-lowers are
        # verified end to end without any network or API key spend.
        original_retrieval = pipeline_module.check_novelty_positioning
        original_model = pipeline_module._model_critique

        def fake_retrieval(parsed_paper, *args, **kwargs):
            return {
                "check": "novelty-positioning",
                "query": "attention",
                "retrieved": [],
                "traces": [
                    {
                        "id": "1706.03762",
                        "title": "Attention Is All You Need",
                        "similarity": 0.2,
                        "already_cited": False,
                        "mentioned_by_title": False,
                    }
                ],
                "questions": [
                    {
                        "section": "Questions for the Authors",
                        "stance": "question",
                        "text": "Related prior work arXiv:1706.03762 is not cited.",
                        "references": ["arxiv:1706.03762"],
                    }
                ],
            }

        def fake_model(*, sanitized_paper, grounding, anchor_scores, api_key, **kwargs):
            return {
                "comments": [{"stance": "weakness", "text": "Weakness — Single-seed results lack variance. [claim-001]"}],
                # Overall 3->2 is a permitted lowering; Soundness 2->1 must be
                # clamped to the floor (2) because no defect was proven.
                "calibration": {
                    "Overall recommendation": {"value": 2, "reason": "insufficient empirical rigor"},
                    "Soundness": {"value": 1, "reason": "attempted floor with no proven defect"},
                },
                "model": "gpt-test",
                "prompt_sha256": "deadbeef" * 8,
                "ok": True,
            }

        pipeline_module.check_novelty_positioning = fake_retrieval
        pipeline_module._model_critique = fake_model
        try:
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paper = root / "peer.md"
                paper.write_text(
                    "# Novel Method\n\n## Method\n\nWe propose a novel method that outperforms all baselines.\n",
                    encoding="utf-8",
                )
                evidence = root / "ev"
                evidence.mkdir()
                state = run_pipeline(paper, evidence, root / "review.md", mode="best")
        finally:
            pipeline_module.check_novelty_positioning = original_retrieval
            pipeline_module._model_critique = original_model

        markdown = state.review_markdown
        self.assertIn("## Scientific Judgment (best mode)", markdown)
        self.assertIn("Single-seed results lack variance", markdown)      # model comment
        self.assertIn("arXiv:1706.03762", markdown)                        # retrieval comment
        self.assertIn("Model critique: `gpt-test`", markdown)              # provenance
        self.assertEqual(state.scores["Overall recommendation"]["value"], 2)  # 3 -> 2 within the floor
        self.assertEqual(state.scores["Soundness"]["value"], 2)            # 1 clamped to floor 2 (no proven defect)
        self.assertIn("calibration lowered", markdown.lower())


if __name__ == "__main__":
    unittest.main()
