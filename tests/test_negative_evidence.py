"""Focused tests for the M6a negative-evidence mechanical check."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer.negative_evidence import check_negative_evidence
from reviewer.parser import parse_markdown


def _write_paper(root: Path, text: str) -> dict[str, object]:
    path = root / "paper.md"
    path.write_text(text, encoding="utf-8")
    return parse_markdown(path)


def _write_ledger(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class NegativeEvidenceTests(unittest.TestCase):
    def test_disclosed_discard_and_crash_are_traced_without_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _write_paper(
                root,
                "# Results\n\nCandidate 2 was discarded after divergence.\n"
                "The WINNER-CONFIRMATION run crashed with an error.\n",
            )
            evidence = root / "evidence"
            _write_ledger(
                evidence / "experiments.jsonl",
                [
                    {"trial": "candidate-2", "status": "discard"},
                    {"trial": "winner_confirmation", "status": "CRASH"},
                    {"trial": "baseline", "status": "keep"},
                ],
            )

            result = check_negative_evidence(parsed, evidence)

        self.assertEqual(result["check"], "negative-evidence")
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["traces"]), 2)
        self.assertTrue(all(trace["disclosed"] for trace in result["traces"]))
        json.dumps(result)

    def test_absent_entry_and_status_omission_are_flagged_at_ledger_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _write_paper(root, "# Results\n\nCandidate-1 achieved the best score.\n")
            evidence = root / "evidence"
            _write_ledger(
                evidence / "experiments.jsonl",
                [
                    {"trial": "candidate-1", "status": "discard"},
                    {"trial": "candidate-2", "status": "crash"},
                ],
            )

            result = check_negative_evidence(parsed, evidence)

        self.assertEqual(len(result["findings"]), 2)
        self.assertEqual(
            [finding["location"] for finding in result["findings"]],
            ["experiments.jsonl:1", "experiments.jsonl:2"],
        )
        self.assertIn("without negative-outcome language", result["findings"][0]["observed"])
        self.assertIn("does not mention", result["findings"][1]["observed"])
        self.assertTrue(all(finding["evidence_path"] == "experiments.jsonl" for finding in result["findings"]))

    def test_nested_ledgers_are_sorted_and_use_relative_evidence_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _write_paper(root, "# Results\n\nNo failed trials are described.\n")
            evidence = root / "evidence"
            _write_ledger(evidence / "z" / "experiments.jsonl", [{"run_tag": "z-run", "status": "crash"}])
            _write_ledger(evidence / "a" / "experiments.jsonl", [{"job_slug": "a-job", "status": "discard"}])

            result = check_negative_evidence(parsed, evidence)

        self.assertEqual(
            [trace["evidence_path"] for trace in result["traces"]],
            ["a/experiments.jsonl", "z/experiments.jsonl"],
        )
        self.assertEqual(result["findings"][0]["location"], "a/experiments.jsonl:1")

    def test_unidentifiable_and_malformed_records_do_not_create_speculation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _write_paper(root, "# Results\n\nThe baseline completed.\n")
            evidence = root / "evidence"
            ledger = evidence / "experiments.jsonl"
            evidence.mkdir()
            ledger.write_text(
                '{"status":"crash","val_bpb":2.0}\n'
                'not json\n'
                '["discard"]\n'
                '{"trial":"baseline","status":"keep"}\n',
                encoding="utf-8",
            )

            result = check_negative_evidence(parsed, evidence)

        self.assertEqual(result, {"check": "negative-evidence", "traces": [], "findings": []})


if __name__ == "__main__":
    unittest.main()
