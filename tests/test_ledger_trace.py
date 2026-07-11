"""M2a tests for conservative, location-preserving ledger traceability."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import check_ledger_trace, parse_markdown, run_pipeline


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "eval" / "papers" / "sample_clean.md"


def _write_ledger(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class LedgerTraceTests(unittest.TestCase):
    def test_matches_metric_values_and_ignores_non_result_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            _write_ledger(
                evidence / "experiments.jsonl",
                [
                    {"trial": "baseline", "val_bpb": 1.224, "status": "keep"},
                    {"trial": "candidate-1", "val_bpb": 1.1964, "status": "keep"},
                ],
            )
            result = check_ledger_trace(parse_markdown(SAMPLE), evidence)

        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["traces"]), 3)
        self.assertTrue(all(trace["matched"] for trace in result["traces"]))
        self.assertEqual(
            {trace["paper_value"] for trace in result["traces"]},
            {"1.224", "1.196"},
        )
        self.assertNotIn("42", {trace["paper_value"] for trace in result["traces"]})
        json.dumps(result)

    def test_trial_context_prevents_cross_run_value_match(self) -> None:
        paper_text = """# Results

| Trial | val_bpb |
|---|---:|
| baseline | 1.196 |
| candidate-1 | 1.224 |
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.md"
            paper.write_text(paper_text, encoding="utf-8")
            evidence = root / "evidence"
            evidence.mkdir()
            _write_ledger(
                evidence / "experiments.jsonl",
                [
                    {"trial": "baseline", "val_bpb": 1.224},
                    {"trial": "candidate-1", "val_bpb": 1.196},
                ],
            )
            result = check_ledger_trace(parse_markdown(paper), evidence)

        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all(finding["check"] == "ledger-trace" for finding in result["findings"]))
        self.assertEqual({finding["location"]["line"] for finding in result["findings"]}, {5, 6})

    def test_rounding_tolerance_is_inclusive_and_metric_specific(self) -> None:
        paper_text = """# Results

The baseline measured loss as 1.196 and accuracy as 1.196.
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.md"
            paper.write_text(paper_text, encoding="utf-8")
            evidence = root / "evidence"
            evidence.mkdir()
            _write_ledger(
                evidence / "experiments.jsonl",
                [{"trial": "baseline", "loss": 1.1965, "accuracy": 1.1966}],
            )
            result = check_ledger_trace(parse_markdown(paper), evidence)

        traces = {trace["metric"]: trace for trace in result["traces"]}
        self.assertTrue(traces["loss"]["matched"])
        self.assertFalse(traces["accuracy"]["matched"])
        self.assertEqual(len(result["findings"]), 1)

    def test_missing_and_malformed_ledgers_are_reported_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = check_ledger_trace(parse_markdown(SAMPLE), root)
            (root / "experiments.jsonl").write_text('{"trial": "baseline"}\nnot json\n', encoding="utf-8")
            malformed = check_ledger_trace(parse_markdown(SAMPLE), root)

        self.assertGreaterEqual(len(missing["findings"]), 1)
        self.assertTrue(
            all("not found" in finding["evidence_path"] for finding in missing["findings"])
        )
        self.assertTrue(any(finding["location"] == "experiments.jsonl:2" for finding in malformed["findings"]))

    def test_pipeline_exposes_s3_results_without_changing_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            _write_ledger(
                evidence / "experiments.jsonl",
                [
                    {"trial": "baseline", "val_bpb": 1.224},
                    {"trial": "candidate-1", "val_bpb": 1.196},
                ],
            )
            state = run_pipeline(SAMPLE, evidence, root / "review.md")

        self.assertIn("ledger-trace", state.mechanical_checks)
        self.assertEqual(state.completed_stages[2], "S3 mech-check")
        self.assertIn("S3 ledger-trace: 3/3", state.review_markdown)


if __name__ == "__main__":
    unittest.main()
