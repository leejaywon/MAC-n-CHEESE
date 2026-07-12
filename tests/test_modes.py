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
from reviewer.review_schema import SCIENTIFIC_AXES


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

    def test_best_mode_committee_merges_grounded_review_and_direct_scores(self) -> None:
        # Drive the current four-call committee seam with a validated fake result,
        # without network access or API-key spend.
        original_retrieval = pipeline_module.check_novelty_positioning
        original_committee = pipeline_module._committee_review

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

        def fake_committee(*, packet, **kwargs):
            grounding = packet.spans[0].id
            score_values = {
                "Soundness": 2,
                "Presentation": 3,
                "Significance": 2,
                "Originality": 3,
                "Overall recommendation": 2,
                "Confidence": 4,
            }
            return {
                "ok": True,
                "judgment": {
                    "summary": "The method is clear, but the empirical scope is narrow.",
                    "axes": [
                        {
                            "axis": axis,
                            "verdict": "partially_justified",
                            "text": f"The evidence partially supports {axis}.",
                            "grounding": [grounding],
                        }
                        for axis in SCIENTIFIC_AXES
                    ],
                    "strengths": [
                        {
                            "text": "The method is stated clearly.",
                            "grounding": [grounding],
                        }
                    ],
                    "weaknesses": [
                        {
                            "text": "The evaluation is limited to one reported setting.",
                            "grounding": [grounding],
                        }
                    ],
                    "questions": [
                        {
                            "text": f"Can the authors clarify evaluation choice {index}?",
                            "grounding": [grounding],
                            "assessment_if_resolved": "This would improve confidence.",
                        }
                        for index in range(1, 4)
                    ],
                    "scores": {
                        dimension: {
                            "value": value,
                            "reason": f"The evidence supports {dimension}={value}.",
                            "grounding": [grounding],
                        }
                        for dimension, value in score_values.items()
                    },
                },
                "model": "gpt-test",
                "provenance": {
                    "rubric_version": "scientific-committee-v1",
                    "workers": 3,
                    "timeout_seconds": 60,
                    "specialists": [],
                    "meta": {},
                },
            }

        pipeline_module.check_novelty_positioning = fake_retrieval
        pipeline_module._committee_review = fake_committee
        try:
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False), \
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
        finally:
            pipeline_module.check_novelty_positioning = original_retrieval
            pipeline_module._committee_review = original_committee

        markdown = state.review_markdown
        self.assertIn("The method is clear, but the empirical scope is narrow.", markdown)
        self.assertIn("The evaluation is limited to one reported setting.", markdown)
        self.assertIn("Scientific committee configuration", markdown)
        self.assertNotIn("## Scientific Judgment (best mode)", markdown)
        self.assertEqual(state.scores["Overall recommendation"]["value"], 2)
        self.assertEqual(state.scores["Soundness"]["value"], 2)
        self.assertEqual(len(state.scientific_judgment.questions), 3)


if __name__ == "__main__":
    unittest.main()
