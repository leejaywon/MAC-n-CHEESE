"""M5 tests for the DRAFT/GROUND policy and score calibration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer import calibrate_scores, ground_comments, run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class ComposerTests(unittest.TestCase):
    def test_grounder_deletes_praise_and_demotes_unproven_criticism(self) -> None:
        claims = [{"id": "claim-001"}, {"id": "claim-002"}]
        verdicts = [
            {"claim_id": "claim-001", "label": "unverifiable", "evidence": []},
            {"claim_id": "claim-002", "label": "supported", "evidence": ["ledger:1"]},
        ]
        draft = [
            {"section": "Strengths", "stance": "praise", "text": "Novel.", "claim_id": "claim-001", "references": ["claim-001"]},
            {"section": "Weaknesses", "stance": "criticism", "text": "Unsupported.", "claim_id": "claim-001", "references": ["claim-001"]},
        ]

        result = ground_comments(draft, claims, verdicts, [])

        self.assertEqual(len(result["deleted"]), 1)
        self.assertEqual(len(result["reclassified"]), 1)
        self.assertEqual(result["comments"][0]["section"], "Questions for the Authors")
        self.assertIn("[claim-001]", result["comments"][0]["text"])

    def test_scores_start_borderline_and_use_only_verdict_evidence(self) -> None:
        claims = [
            {"id": "claim-001", "type": "result"},
            {"id": "claim-002", "type": "general"},
        ]
        supported = [
            {"claim_id": "claim-001", "label": "supported", "evidence": []},
            {"claim_id": "claim-002", "label": "unverifiable", "evidence": []},
        ]
        contradicted = [
            {"claim_id": "claim-001", "label": "contradicted", "evidence": ["finding-001"]},
            {"claim_id": "claim-002", "label": "unverifiable", "evidence": []},
        ]

        promoted = calibrate_scores(claims, supported)
        demoted = calibrate_scores(claims, contradicted)

        self.assertEqual(promoted["Overall recommendation"]["value"], 4)
        self.assertEqual(demoted["Overall recommendation"]["value"], 2)
        self.assertIn("[claim-001]", promoted["Overall recommendation"]["rationale"])
        self.assertIn("[claim-001]", demoted["Soundness"]["rationale"])

    def test_pipeline_outputs_grounded_sections_and_all_score_rationales(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(
                ROOT / "eval/papers/clean_val_bpb.md",
                ROOT / "eval/evidence/clean_val_bpb",
                Path(directory) / "review.md",
            )

        self.assertTrue(state.draft_comments)
        self.assertTrue(state.grounded_comments)
        self.assertEqual(set(state.scores), {
            "Soundness", "Presentation", "Contribution", "Overall recommendation", "Confidence"
        })
        self.assertIn("S5 DRAFT/GROUND:", state.review_markdown)
        self.assertNotIn("Not scored", state.review_markdown)
        for name, score in state.scores.items():
            self.assertIn(f"- {name}: {score['value']}/", state.review_markdown)
            self.assertRegex(score["rationale"], r"\[claim-\d{3}\]")


if __name__ == "__main__":
    unittest.main()
