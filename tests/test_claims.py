"""M4 tests for claim extraction, verdict labels, and Evidence Trace output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import extract_claims, label_verdicts, parse_markdown, run_pipeline


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
        # Fresh TemporaryDirectory (not the shared gettempdir()) so a frozen
        # artifact from an earlier agent version cannot collide across reruns.
        with tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(
                ROOT / "eval/papers/clean_val_bpb.md",
                ROOT / "eval/evidence/clean_val_bpb",
                Path(directory) / "m4-clean-review.md",
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

    def test_citation_finding_on_shared_line_only_contradicts_citation_claim(self) -> None:
        line = (
            "Accuracy reached 90% on the benchmark. "
            "The cited comparison is arXiv:1901.99999."
        )
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "paper.md"
            paper.write_text(f"# Shared Line\n\n{line}\n", encoding="utf-8")
            claims = extract_claims(parse_markdown(paper))

        self.assertEqual(len(claims), 2)
        self.assertEqual({claim["location"]["line"] for claim in claims}, {3})
        result_claim = next(claim for claim in claims if claim["type"] == "result")
        citation_claim = next(claim for claim in claims if claim["refs"])
        finding = {
            "check": "citation-existence",
            "severity": "error",
            "location": {
                "line": 3,
                "column_start": citation_claim["location"]["column_start"],
                "column_end": citation_claim["location"]["column_end"],
            },
            "expected": "a published record for 1901.99999",
            "observed": "the arXiv API returned no record for this identifier",
            "evidence_path": "https://export.arxiv.org/api/query?id_list=1901.99999",
        }
        checks = {
            "ledger-trace": {
                "traces": [
                    {
                        "number_id": result_claim["numbers"][0],
                        "matched": True,
                        "evidence": [
                            {"path": "experiments.jsonl", "line": 1, "field": "accuracy"}
                        ],
                    }
                ]
            }
        }

        verdicts, _ = label_verdicts(claims, checks, [finding])
        verdict_by_claim = {verdict["claim_id"]: verdict for verdict in verdicts}

        self.assertEqual(verdict_by_claim[citation_claim["id"]]["label"], "contradicted")
        self.assertEqual(verdict_by_claim[result_claim["id"]]["label"], "supported")


if __name__ == "__main__":
    unittest.main()
