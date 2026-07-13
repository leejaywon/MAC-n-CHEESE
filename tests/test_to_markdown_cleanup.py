"""Tests for PDF-extraction cleanup passes that need no pymupdf."""

from __future__ import annotations

import unittest

from reviewer.to_markdown import _strip_margin_line_numbers


class MarginLineNumberTests(unittest.TestCase):
    def _line_numbered(self) -> str:
        parts = []
        for i in range(60):  # a densely line-numbered submission
            parts.append(f"{i:03d}")
            if i == 10:
                parts.append("we use 512 hidden units")
            if i == 20:
                parts.append("reaching 53% accuracy")
        return " ".join(parts)

    def test_line_numbers_removed_real_numbers_kept(self) -> None:
        out = _strip_margin_line_numbers(self._line_numbered())
        tokens = out.split()
        self.assertNotIn("005", tokens)      # a line number is gone
        self.assertNotIn("045", tokens)
        self.assertIn("512", tokens)         # real hyperparameter kept
        self.assertIn("53%", out)            # real percentage kept

    def test_noop_on_unnumbered_document(self) -> None:
        clean = "# Title\n\nWe evaluate on ImageNet with 512 hidden units and 3 seeds.\n"
        self.assertEqual(_strip_margin_line_numbers(clean), clean)

    def test_noop_when_below_guard(self) -> None:
        # Too few / too-low integers to be a line-numbered doc — leave untouched.
        short = "Results: 001 baseline, 002 candidate, 003 oracle."
        self.assertEqual(_strip_margin_line_numbers(short), short)


if __name__ == "__main__":
    unittest.main()
