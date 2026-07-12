"""Focused tests for deterministic scientific-scaffolding comments."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import run_pipeline
from reviewer.parser import parse_markdown
from reviewer.scientific_scaffolding import (
    compute_ledger_scope,
    follow_up_questions,
    rigor_questions,
)


def _write_ledger(evidence_dir: Path, records: list[object]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "experiments.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _parse(root: Path, text: str) -> dict:
    paper = root / "paper.md"
    paper.write_text(text, encoding="utf-8")
    return parse_markdown(paper)


class LedgerScopeTests(unittest.TestCase):
    def test_scope_counts_trials_seeds_gpu_benchmarks_metrics_and_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            _write_ledger(
                evidence,
                [
                    {
                        "trial": "baseline",
                        "status": "keep",
                        "seed": 11,
                        "gpu_type": "A100",
                        "benchmark": "CIFAR-10",
                        "metrics": {"accuracy": 70.0},
                    },
                    {
                        "trial": "candidate",
                        "status": "keep",
                        "seed": 12,
                        "gpu_type": "A100",
                        "benchmark": "ImageNet",
                        "metrics": {"accuracy": 75.0, "loss": 1.2},
                    },
                    {
                        "trial": "winner-confirmation",
                        "status": "keep",
                        "seed": 12,
                        "gpu_type": "H100",
                        "benchmark": "ImageNet",
                        "metrics": {"accuracy": 74.8},
                    },
                ],
            )

            scope = compute_ledger_scope(evidence)

        self.assertEqual(scope["trial_count"], 3)
        self.assertEqual(scope["distinct_seeds"], [11, 12])
        self.assertEqual(scope["gpu_types"], ["A100", "H100"])
        self.assertEqual(scope["benchmarks"], ["CIFAR-10", "ImageNet"])
        self.assertEqual(scope["metrics"], ["accuracy", "loss"])
        self.assertEqual(scope["confirmation_runs"], 1)

    def test_generalized_claim_emits_quoted_scope_weakness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(
                root,
                "# Results\n\nOur method generalizes across all benchmarks and hardware.\n",
            )
            evidence = root / "evidence"
            _write_ledger(
                evidence,
                [
                    {
                        "trial": "baseline",
                        "status": "keep",
                        "seed": 7,
                        "gpu_type": "A100",
                        "benchmark": "CIFAR-10",
                        "accuracy": 70.0,
                    },
                    {
                        "trial": "candidate",
                        "status": "keep",
                        "seed": 7,
                        "gpu_type": "A100",
                        "benchmark": "CIFAR-10",
                        "accuracy": 75.0,
                    },
                ],
            )

            comments = rigor_questions(parsed, evidence_dir=evidence)

        scope_comments = [item for item in comments if item.get("family") == "scope"]
        self.assertEqual(len(scope_comments), 1)
        weakness = scope_comments[0]
        self.assertEqual(weakness["section"], "Weaknesses")
        self.assertIn("2 trials", weakness["text"])
        self.assertIn("1 distinct seed", weakness["text"])
        self.assertIn("GPU types: A100", weakness["text"])
        self.assertIn("1 benchmark", weakness["text"])
        self.assertIn("1 metric", weakness["text"])
        self.assertIn("0 confirmation runs", weakness["text"])
        self.assertEqual(weakness["references"], ["paper:3"])

    def test_claim_with_observed_breadth_does_not_emit_scope_weakness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(
                root,
                "# Results\n\nOur method is robust across 2 benchmarks.\n",
            )
            evidence = root / "evidence"
            _write_ledger(
                evidence,
                [
                    {
                        "trial": "candidate-a",
                        "seed": 1,
                        "gpu": "A100",
                        "dataset": "CIFAR-10",
                        "accuracy": 75.0,
                    },
                    {
                        "trial": "candidate-b",
                        "seed": 2,
                        "gpu": "A100",
                        "dataset": "ImageNet",
                        "accuracy": 71.0,
                    },
                ],
            )

            comments = rigor_questions(parsed, evidence_dir=evidence)

        self.assertEqual([item for item in comments if item.get("family") == "scope"], [])

    def test_generalized_claim_without_ledger_does_not_invent_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(root, "# Results\n\nOur method generalizes broadly.\n")
            evidence = root / "empty-evidence"
            evidence.mkdir()

            comments = rigor_questions(parsed, evidence_dir=evidence)

        self.assertEqual([item for item in comments if item.get("family") == "scope"], [])


class FollowUpTests(unittest.TestCase):
    def test_one_concrete_follow_up_per_family_retains_all_finding_references(self) -> None:
        findings = [
            {"id": "finding-001", "check": "baseline-fairness"},
            {"id": "finding-002", "check": "negative-evidence"},
            {"id": "finding-003", "check": "baseline-fairness"},
            {"id": "finding-004", "check": "citation-existence"},
            {"id": "finding-005", "check": "variance"},
            {"id": "finding-006", "check": "arithmetic"},
        ]

        follow_ups = follow_up_questions(findings)

        self.assertEqual(
            [item["family"] for item in follow_ups],
            ["variance", "baseline-fairness", "negative-evidence", "citation-existence"],
        )
        self.assertEqual(
            follow_ups[1]["references"],
            ["finding-001", "finding-003"],
        )
        self.assertIn("finding-001", follow_ups[1]["text"])
        self.assertIn("finding-003", follow_ups[1]["text"])
        self.assertIn(
            "Repeat the comparison with at least three independent seeds.",
            follow_ups[0]["text"],
        )
        self.assertIn(
            "Run the named baseline under the same metric and budget.",
            follow_ups[1]["text"],
        )
        self.assertIn(
            "Report the omitted failed/discarded trial and its effect.",
            follow_ups[2]["text"],
        )
        self.assertIn(
            "Correct or replace the unresolved citation identifier.",
            follow_ups[3]["text"],
        )

    def test_existing_one_argument_call_includes_variance_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parsed = _parse(
                Path(directory),
                "# Results\n\n| condition | accuracy |\n|---|---:|\n| candidate | 75.0 |\n",
            )

            questions = rigor_questions(parsed)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["family"], "variance")
        self.assertIn("single run", questions[0]["text"])
        self.assertIn("at least three independent seeds", questions[0]["text"])

    def test_variance_follow_up_merges_finding_references_into_existing_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parsed = _parse(
                Path(directory),
                "# Results\n\n| condition | accuracy |\n|---|---:|\n| candidate | 75.0 |\n",
            )

            questions = rigor_questions(
                parsed,
                findings=[
                    {"id": "finding-007", "check": "variance"},
                    {"id": "finding-008", "check": "variance"},
                ],
            )

        self.assertEqual(len(questions), 1)
        self.assertEqual(
            questions[0]["references"],
            ["paper:3", "finding-007", "finding-008"],
        )
        self.assertIn("finding-007", questions[0]["text"])
        self.assertIn("finding-008", questions[0]["text"])

    def test_pipeline_routes_scope_critique_to_weaknesses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.md"
            paper.write_text(
                "# General Study\n\n## Results\n\n"
                "Our method generalizes across all benchmarks and hardware.\n",
                encoding="utf-8",
            )
            evidence = root / "evidence"
            _write_ledger(
                evidence,
                [
                    {
                        "trial": "candidate",
                        "seed": 1,
                        "gpu": "A100",
                        "dataset": "one-benchmark",
                        "accuracy": 75.0,
                    }
                ],
            )
            state = run_pipeline(paper, evidence, root / "review.md")

        weakness_block = state.review_markdown.split("## Weaknesses", 1)[1].split(
            "## Questions for the Authors", 1
        )[0]
        self.assertIn("Scope limitation", weakness_block)
        self.assertIn("1 trial", weakness_block)


if __name__ == "__main__":
    unittest.main()
