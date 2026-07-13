"""Tests for the deterministic manuscript-integrity checks (S3)."""

from __future__ import annotations

import unittest
from pathlib import Path

from reviewer.manuscript_integrity import check_cross_references, check_manuscript_artifacts
from reviewer.parser import parse_markdown


def _paper(body: str) -> dict:
    return parse_markdown(Path("test.md"), text=f"# Title\n\n{body}\n")


class CrossReferenceTests(unittest.TestCase):
    def test_broken_float_reference(self) -> None:
        result = check_cross_references(_paper("See Figure ?? for the ablation."))
        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("float reference", result["findings"][0]["observed"])

    def test_unrendered_ref_and_failed_citation(self) -> None:
        self.assertEqual(
            len(check_cross_references(_paper(r"Results appear in \ref{tab:main}."))["findings"]),
            1,
        )
        self.assertEqual(
            len(check_cross_references(_paper("As shown in [?], accuracy improves."))["findings"]),
            1,
        )

    def test_clean_references_pass(self) -> None:
        result = check_cross_references(_paper("See Figure 3 and Table 1 for details."))
        self.assertEqual(result["findings"], [])


class ManuscriptArtifactTests(unittest.TestCase):
    def test_author_err(self) -> None:
        result = check_manuscript_artifacts(_paper("Authors: AUTHORERR"))
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["check"], "manuscript-artifacts")

    def test_placeholders(self) -> None:
        self.assertEqual(len(check_manuscript_artifacts(_paper("TODO: add the baseline."))["findings"]), 1)
        self.assertEqual(
            len(check_manuscript_artifacts(_paper("This is unproven [citation needed]."))["findings"]),
            1,
        )

    def test_clean_manuscript_passes(self) -> None:
        result = check_manuscript_artifacts(_paper("We evaluate on ImageNet with three seeds."))
        self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()
