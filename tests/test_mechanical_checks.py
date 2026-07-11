"""M2b tests for conservative table/prose and arithmetic checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer import check_arithmetic, check_internal_consistency, parse_markdown, run_pipeline


def _parse(text: str, root: Path):
    paper = root / "paper.md"
    paper.write_text(text, encoding="utf-8")
    return parse_markdown(paper)


class MechanicalCheckTests(unittest.TestCase):
    def test_clean_sample_recomputes_delta_and_improvement(self) -> None:
        sample = Path(__file__).resolve().parents[1] / "eval" / "papers" / "sample_clean.md"
        parsed = parse_markdown(sample)

        consistency = check_internal_consistency(parsed)
        arithmetic = check_arithmetic(parsed)

        self.assertEqual(consistency["findings"], [])
        self.assertEqual(arithmetic["findings"], [])
        self.assertEqual(len(arithmetic["traces"]), 2)
        self.assertTrue(all(trace["matched"] for trace in arithmetic["traces"]))

    def test_table_prose_mismatch_is_localized(self) -> None:
        text = """# Results

| Trial | accuracy |
|---|---:|
| baseline | 70.0 |
| candidate | 75.0 |

The candidate achieved accuracy of 74.0.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_internal_consistency(_parse(text, Path(directory)))

        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["check"], "internal-consistency")
        self.assertEqual(result["findings"][0]["location"]["line"], 8)

    def test_aggregate_or_unlabelled_prose_does_not_create_false_positive(self) -> None:
        text = """# Results

| Trial | accuracy |
|---|---:|
| baseline | 70.0 |
| candidate | 75.0 |

Across 3 runs, mean accuracy was 74.0. Seed 42 was used.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_internal_consistency(_parse(text, Path(directory)))

        self.assertEqual(result["traces"], [])
        self.assertEqual(result["findings"], [])

    def test_wrong_delta_and_percent_are_both_reported(self) -> None:
        text = """# Research Spec

The candidate should lower `loss`.

# Results

| Trial | loss |
|---|---:|
| baseline | 2.00 |
| candidate | 1.50 |

The absolute delta is -0.40 and relative improvement is 20.0%.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_arithmetic(_parse(text, Path(directory)))

        self.assertEqual(len(result["traces"]), 2)
        self.assertEqual(len(result["findings"]), 2)
        self.assertEqual({item["check"] for item in result["findings"]}, {"arithmetic"})
        self.assertEqual({item["location"]["line"] for item in result["findings"]}, {12})

    def test_ambiguous_multiple_metrics_are_not_guessed(self) -> None:
        text = """# Results

| Trial | accuracy | loss |
|---|---:|---:|
| baseline | 70 | 2.0 |
| candidate | 75 | 1.5 |

The relative improvement is 7.14%.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_arithmetic(_parse(text, Path(directory)))

        self.assertEqual(result["traces"], [])
        self.assertEqual(result["findings"], [])

    def test_pipeline_exposes_all_m6b_checks(self) -> None:
        sample = Path(__file__).resolve().parents[1] / "eval" / "papers" / "sample_clean.md"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "experiments.jsonl").write_text(
                '{"trial":"baseline","val_bpb":1.224}\n'
                '{"trial":"candidate-1","val_bpb":1.196}\n',
                encoding="utf-8",
            )
            state = run_pipeline(sample, evidence, root / "review.md")

        self.assertEqual(
            set(state.mechanical_checks),
            {
                "ledger-trace",
                "internal-consistency",
                "arithmetic",
                "baseline-fairness",
                "negative-evidence",
                "citation-existence",
                "template-compliance",
                "injection-scan",
                "self-review-audit",
            },
        )
        self.assertIn("S3 arithmetic: 2 recomputation(s), 0 finding(s)", state.review_markdown)
        self.assertIn("S3 baseline-fairness:", state.review_markdown)
        self.assertIn("S3 negative-evidence:", state.review_markdown)
        self.assertIn("S3 citation-existence:", state.review_markdown)
        self.assertIn("S3 template-compliance:", state.review_markdown)
        self.assertIn("S3 injection-scan:", state.review_markdown)
        self.assertIn("S3 self-review-audit:", state.review_markdown)


if __name__ == "__main__":
    unittest.main()
