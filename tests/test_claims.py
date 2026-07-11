"""M4 tests for claim extraction, verdict labels, and Evidence Trace output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import extract_claims, parse_markdown, run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class ClaimVerdictTests(unittest.TestCase):
    def test_extracts_stable_claim_schema_and_table_result_claims(self) -> None:
        claims = extract_claims(parse_markdown(ROOT / "eval/papers/clean_val_bpb.md"))

        self.assertEqual(claims[0]["id"], "claim-001")
        self.assertTrue(all(set(claim) == {"id", "text", "type", "numbers", "refs", "location"} for claim in claims))
        table_claims = [claim for claim in claims if claim["location"]["table_id"]]
        self.assertEqual([claim["text"] for claim in table_claims], ["baseline | keep | 1.224", "candidate-1 | keep | 1.196"])
        self.assertTrue(all(claim["type"] == "result" for claim in table_claims))
        self.assertFalse(any("Trial | Status" in claim["text"] for claim in claims))
        json.dumps(claims)

    def test_clean_results_supported_but_hypothesis_remains_unverifiable(self) -> None:
        state = run_pipeline(
            ROOT / "eval/papers/clean_val_bpb.md",
            ROOT / "eval/evidence/clean_val_bpb",
            Path(tempfile.gettempdir()) / "m4-clean-review.md",
        )
        labels = {claim["id"]: verdict["label"] for claim, verdict in zip(state.claims, state.verdicts)}
        hypothesis = next(claim for claim in state.claims if claim["type"] == "hypothesis")
        table_claims = [claim for claim in state.claims if claim["location"]["table_id"]]
        arithmetic = next(claim for claim in state.claims if claim["type"] == "arithmetic")

        self.assertEqual(labels[hypothesis["id"]], "unverifiable")
        self.assertTrue(all(labels[claim["id"]] == "supported" for claim in table_claims))
        self.assertEqual(labels[arithmetic["id"]], "supported")
        self.assertIn(f"[{arithmetic['id']}] **supported**", state.review_markdown)

    def test_corrupted_prose_claim_links_to_stable_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(
                ROOT / "eval/papers/corrupt_fabricated_result.md",
                ROOT / "eval/evidence/corrupt_fabricated_result",
                Path(directory) / "review.md",
            )

        claim = next(claim for claim in state.claims if "loss of 1.40" in claim["text"])
        verdict = next(item for item in state.verdicts if item["claim_id"] == claim["id"])
        self.assertEqual(verdict["label"], "contradicted")
        self.assertTrue(verdict["evidence"])
        self.assertTrue(all(pointer.startswith("finding-") for pointer in verdict["evidence"]))
        self.assertIn(f"[{claim['id']}] **contradicted**", state.review_markdown)


if __name__ == "__main__":
    unittest.main()
