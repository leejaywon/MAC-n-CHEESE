"""Focused M6b tests for cached citations and template compliance."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import check_citation_existence, check_template_compliance, parse_markdown


ARXIV_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title>
</entry></feed>'''


def _parse(root: Path, text: str):
    paper = root / "paper.md"
    paper.write_text(text, encoding="utf-8")
    return parse_markdown(paper)


class CitationExistenceTests(unittest.TestCase):
    def test_arxiv_title_is_verified_and_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(
                root,
                "# References\n\n[Attention Is All You Need](https://arxiv.org/abs/1706.03762)\n",
            )
            calls: list[str] = []

            def fetch(url: str) -> bytes:
                calls.append(url)
                return ARXIV_XML

            first = check_citation_existence(parsed, root / "cache", fetch)
            second = check_citation_existence(
                parsed, root / "cache", lambda _: (_ for _ in ()).throw(AssertionError("network used"))
            )

        self.assertEqual(first["findings"], [])
        self.assertEqual(len(calls), 1)
        self.assertTrue(second["traces"][0]["cache_hit"])

    def test_s2_title_mismatch_and_not_found_are_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(
                root,
                "# References\n\n[Completely Different Claimed Title](https://doi.org/10.1000/example)\n",
            )
            mismatch = check_citation_existence(
                parsed,
                root / "cache-a",
                lambda _: json.dumps({"title": "Actual Research Paper Title"}).encode(),
            )

            def not_found(_: str) -> bytes:
                from urllib.error import HTTPError

                raise HTTPError("https://api.semanticscholar.org", 404, "missing", {}, None)

            absent = check_citation_existence(parsed, root / "cache-b", not_found)

        self.assertEqual(len(mismatch["findings"]), 1)
        self.assertIn("API title", mismatch["findings"][0]["observed"])
        # A Semantic Scholar 404 for a DOI is NOT proof of nonexistence (S2 does
        # not index every DOI), so it must not be a finding — only the trace records
        # it. Fabricated-arXiv detection (authoritative) is covered elsewhere.
        self.assertEqual(absent["findings"], [])
        self.assertEqual(absent["traces"][0]["status"], "not-found")

    def test_timeout_is_unavailable_trace_not_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(root, "# References\n\narXiv:1706.03762\n")
            result = check_citation_existence(
                parsed, root / "cache", lambda _: (_ for _ in ()).throw(TimeoutError())
            )

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["traces"][0]["status"], "unavailable")

    def test_truncated_read_does_not_crash_the_audit(self) -> None:
        # http.client.IncompleteRead (server closed the connection early) is NOT
        # an OSError. This lookup runs in the deterministic AUDIT path, so an
        # uncaught one would crash the primary submission on a flaky network.
        import http.client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parsed = _parse(root, "# References\n\narXiv:1706.03762\n")
            result = check_citation_existence(
                parsed, root / "cache", lambda _: (_ for _ in ()).throw(http.client.IncompleteRead(b""))
            )

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["traces"][0]["status"], "unavailable")


class TemplateComplianceTests(unittest.TestCase):
    def test_compact_paper_core_contract_passes_without_guessed_pages(self) -> None:
        text = """# Paper
## Research Spec
## Short Paper
### Abstract
### Results
### Limitations and Conclusion
## Self-Review
- [x] Claims match results.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_template_compliance(_parse(Path(directory), text))

        self.assertEqual(result["findings"], [])
        page_trace = next(trace for trace in result["traces"] if trace["kind"] == "page-count")
        self.assertIsNone(page_trace["matched"])

    def test_official_wrapper_requires_agent_workflow_and_two_to_four_pages(self) -> None:
        text = """# Track 1 — AI Scientist Submission
Page count: 5
## Research Spec
## Short Paper
### Abstract
### Experiments and Results
### Limitations and Conclusion
## Self-Review
- [?] Citations and page count are verified.
"""
        with tempfile.TemporaryDirectory() as directory:
            result = check_template_compliance(_parse(Path(directory), text))

        self.assertEqual(len(result["findings"]), 3)
        self.assertTrue(any("Agent Workflow" in finding["observed"] for finding in result["findings"]))
        self.assertTrue(any("5 page" in finding["observed"] for finding in result["findings"]))
        self.assertTrue(any("invalid checkbox" in finding["observed"] for finding in result["findings"]))


if __name__ == "__main__":
    unittest.main()
