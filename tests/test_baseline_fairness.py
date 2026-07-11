"""Focused tests for the conservative baseline-fairness check."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer.baseline_fairness import check_baseline_fairness
from reviewer.parser import parse_markdown


def _check(paper_text: str, ledger_text: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paper = root / "paper.md"
        evidence = root / "evidence"
        evidence.mkdir()
        paper.write_text(paper_text, encoding="utf-8")
        (evidence / "experiments.jsonl").write_text(ledger_text, encoding="utf-8")
        return check_baseline_fairness(parse_markdown(paper), evidence)


COMPLETE_LEDGER = (
    '{"trial":"baseline","status":"keep","val_bpb":1.224}\n'
    '{"trial":"candidate-1","status":"keep","val_bpb":1.196}\n'
    '{"trial":"winner-confirmation","status":"keep","val_bpb":1.197}\n'
)


class BaselineFairnessTests(unittest.TestCase):
    def test_complete_comparison_has_one_matched_trace(self) -> None:
        result = _check(
            "# Results\n\nThe candidate improved `val_bpb` relative to the baseline.\n",
            COMPLETE_LEDGER,
        )

        self.assertEqual(result["check"], "baseline-fairness")
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["traces"]), 1)
        self.assertTrue(result["traces"][0]["matched"])
        self.assertEqual(result["traces"][0]["comparison_metrics"], ["val_bpb"])

    def test_missing_named_baseline_is_localized(self) -> None:
        result = _check("# Results\n\nThe candidate improved `val_bpb`.\n", COMPLETE_LEDGER)

        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["location"]["line"], 3)
        self.assertIn("does not name a baseline", result["findings"][0]["observed"])

    def test_mismatched_candidate_metric_is_reported(self) -> None:
        ledger = (
            '{"trial":"baseline","status":"keep","loss":2.0}\n'
            '{"trial":"candidate-1","status":"keep","accuracy":75.0}\n'
            '{"trial":"winner-confirmation","status":"keep","accuracy":74.8}\n'
        )
        result = _check(
            "# Results\n\nThe candidate outperformed the baseline.\n",
            ledger,
        )

        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("no common numeric metric", result["findings"][0]["observed"])

    def test_missing_confirmation_rerun_is_reported(self) -> None:
        result = _check(
            "# Results\n\nThe candidate improved accuracy over the baseline.\n",
            '{"trial":"baseline","accuracy":70.0}\n{"trial":"candidate-1","accuracy":75.0}\n',
        )

        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("confirmation rerun", result["findings"][0]["expected"])

    def test_confirmation_does_not_replace_primary_candidate_record(self) -> None:
        ledger = (
            '{"trial":"baseline","accuracy":70.0}\n'
            '{"trial":"winner-confirmation","accuracy":75.0}\n'
        )
        result = _check(
            "# Results\n\nThe candidate improved accuracy over the baseline.\n",
            ledger,
        )

        self.assertFalse(result["traces"][0]["same_metric"])
        self.assertIn("no common numeric metric", result["findings"][0]["observed"])

    def test_failed_confirmation_does_not_satisfy_rerun(self) -> None:
        ledger = COMPLETE_LEDGER.replace('"status":"keep","val_bpb":1.197', '"status":"crash","val_bpb":1.197')
        result = _check(
            "# Results\n\nThe candidate improved `val_bpb` over the baseline.\n",
            ledger,
        )

        self.assertFalse(result["traces"][0]["confirmation_rerun_present"])
        self.assertEqual(len(result["findings"]), 1)

    def test_confirmation_that_regresses_past_baseline_does_not_confirm_claim(self) -> None:
        ledger = (
            '{"trial":"baseline","status":"keep","accuracy":70.0}\n'
            '{"trial":"candidate-1","status":"keep","accuracy":75.0}\n'
            '{"trial":"winner-confirmation","status":"keep","accuracy":65.0}\n'
        )
        result = _check(
            "# Results\n\nThe candidate improved accuracy over the baseline.\n",
            ledger,
        )

        self.assertTrue(result["traces"][0]["confirmation_rerun_present"])
        self.assertFalse(result["traces"][0]["confirmation_supports_claim"])
        self.assertFalse(result["traces"][0]["matched"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("do not confirm", result["findings"][0]["observed"])

    def test_unknown_metric_direction_does_not_create_speculative_finding(self) -> None:
        ledger = (
            '{"trial":"baseline","status":"keep","custom_metric":10.0}\n'
            '{"trial":"candidate-1","status":"keep","custom_metric":12.0}\n'
            '{"trial":"winner-confirmation","status":"keep","custom_metric":8.0}\n'
        )
        result = _check(
            "# Results\n\nThe candidate improved custom_metric over the baseline.\n",
            ledger,
        )

        self.assertIsNone(result["traces"][0]["claimed_direction"])
        self.assertIsNone(result["traces"][0]["confirmation_supports_claim"])
        self.assertEqual(result["findings"], [])

    def test_planned_and_negated_language_is_not_flagged(self) -> None:
        paper = (
            "# Research Spec\n\nWe expect the candidate would improve over the baseline.\n"
            "# Results\n\nThe candidate did not improve over the baseline.\n"
        )
        result = _check(paper, "")

        self.assertEqual(result["traces"], [])
        self.assertEqual(result["findings"], [])

    def test_bounded_arithmetic_improvement_is_owned_by_arithmetic_check(self) -> None:
        paper = (
            "# Results\n\nThe absolute delta is -0.028 and the relative improvement is 2.29%.\n"
            "This report makes no claim beyond the displayed comparison.\n"
        )
        result = _check(paper, COMPLETE_LEDGER)

        self.assertEqual(result["traces"], [])
        self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()
