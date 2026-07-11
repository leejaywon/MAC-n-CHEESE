"""Generality tests: the reviewer must be fair and substantive on arbitrary
(non-event-format) peer papers, not only this event's Track 1 submissions.

These lock in the fixes for the failure modes observed when reviewing a normal
ML paper: event-specific checks manufacturing false positives, and the general
checks (arithmetic, citation) failing to fire without the event's table format.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from reviewer.baseline_fairness import check_baseline_fairness
from reviewer.citation_existence import check_citation_existence
from reviewer.mechanical_checks import check_arithmetic, check_ledger_trace
from reviewer.parser import parse_markdown
from reviewer.pipeline import _detect_event_format
from reviewer.scientific_scaffolding import rigor_questions
from reviewer.self_review_audit import check_self_review_consistency
from reviewer.template_compliance import check_template_compliance


PEER_PAPER = """# Instruction Position Bias in Few-Shot Prompting

## Abstract

Moving the instruction after the examples improved accuracy from 62.0% to 68.0%,
a relative gain of 10.7%. We build on [2305.14567] and extend [1901.99999].

## Method

We compare two templates and outperform the baseline on every benchmark.
"""

# arXiv Atom feed with no <entry> → the id lookup returns "not-found".
EMPTY_ARXIV_FEED = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


class GeneralityTests(unittest.TestCase):
    def _parse(self, text: str, ledger: str | None = None) -> tuple[dict, Path]:
        directory = Path(tempfile.mkdtemp(prefix="ralphthon-generality-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / "paper.md").write_text(text, encoding="utf-8")
        if ledger is not None:
            (directory / "experiments.jsonl").write_text(ledger, encoding="utf-8")
        return parse_markdown(directory / "paper.md"), directory

    # --- P0: event-specific checks must not misfire on a peer paper ----------

    def test_peer_paper_is_not_event_format(self) -> None:
        parsed, directory = self._parse(PEER_PAPER)  # no experiments.jsonl
        self.assertFalse(_detect_event_format(parsed, directory))

    def test_template_check_no_ops_on_peer_paper(self) -> None:
        parsed, _ = self._parse(PEER_PAPER)
        self.assertEqual(check_template_compliance(parsed, event_format=False)["findings"], [])

    def test_baseline_fairness_no_ops_without_a_ledger(self) -> None:
        parsed, directory = self._parse(PEER_PAPER)
        self.assertEqual(check_baseline_fairness(parsed, directory)["findings"], [])

    # --- P1: general checks must fire without the event's table format -------

    def test_prose_ratio_error_is_caught(self) -> None:
        parsed, _ = self._parse(PEER_PAPER)
        ratio = [f for f in check_arithmetic(parsed)["findings"] if "abs(to-from)" in f["expected"]]
        self.assertEqual(len(ratio), 1)
        self.assertIn("9.68%", ratio[0]["expected"])

    def test_correct_prose_ratio_is_not_flagged(self) -> None:
        parsed, _ = self._parse("# Results\n\nAccuracy rose from 50.0 to 75.0, a relative gain of 50.0%.\n")
        ratio = [f for f in check_arithmetic(parsed)["findings"] if "abs(to-from)" in f["expected"]]
        self.assertEqual(ratio, [])

    def test_bracket_arxiv_ids_are_extracted_and_missing_ones_flagged(self) -> None:
        parsed, _ = self._parse(PEER_PAPER)
        with tempfile.TemporaryDirectory() as cache:
            result = check_citation_existence(
                parsed, cache_dir=Path(cache), fetch=lambda url: EMPTY_ARXIV_FEED
            )
        identifiers = {trace["identifier"] for trace in result["traces"]}
        self.assertIn("2305.14567", identifiers)
        self.assertIn("1901.99999", identifiers)
        # With a not-found feed both are flagged; live arXiv verifies the real one.
        self.assertEqual(len(result["findings"]), 2)

    # --- event template: audit the Self-Review checklist and trial names -----

    def test_identifier_ordinal_is_not_traced_as_a_metric(self) -> None:
        # The "1" in "candidate-1" must not be read as accuracy=1; only 67.0 traces.
        parsed, directory = self._parse(
            "# Results\n\nThe candidate-1 achieved accuracy of 67.0.\n",
            ledger='{"trial":"candidate-1","status":"keep","accuracy":67.0}\n',
        )
        self.assertEqual(check_ledger_trace(parsed, directory)["findings"], [])

    def test_dishonest_trailing_self_review_is_flagged(self) -> None:
        # Official template uses a TRAILING checkbox; a checked item contradicted
        # by an existing finding is a dishonest self-certification.
        parsed, _ = self._parse(
            "## Self-Review\n\n- Claims match results: [x]\n- Negative results are included: [ ]\n"
        )
        findings = [{"check": "internal-consistency", "location": {"line": 3}}]
        result = check_self_review_consistency(parsed, findings)
        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("Claims match results", result["findings"][0]["observed"])

    def test_honest_self_review_is_not_flagged(self) -> None:
        parsed, _ = self._parse("## Self-Review\n\n- Claims match results: [x]\n")
        # No findings at all → the checked item is honest → no self-review finding.
        self.assertEqual(check_self_review_consistency(parsed, [])["findings"], [])

    # --- deterministic scientific substance (false-positive-safe Questions) ---

    def test_rigor_question_added_when_no_variance_reported(self) -> None:
        parsed, _ = self._parse("# Results\n\n| cond | acc |\n|---|---:|\n| a | 1.0 |\n\nResults shown.\n")
        questions = rigor_questions(parsed)
        self.assertEqual(len(questions), 1)
        self.assertIn("single run", questions[0]["text"])

    def test_rigor_question_suppressed_when_seeds_mentioned(self) -> None:
        parsed, _ = self._parse("# Results\n\n| cond | acc |\n|---|---:|\n| a | 1.0 |\n\nWe report over 5 seeds.\n")
        self.assertEqual(rigor_questions(parsed), [])


if __name__ == "__main__":
    unittest.main()
