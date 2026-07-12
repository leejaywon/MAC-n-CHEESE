"""Tests for the ICML/NeurIPS rigor & reproducibility checklist critic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer.parser import parse_markdown
from reviewer.rigor_checklist import rigor_checklist_missing, rigor_checklist_questions


def _parse(text: str) -> dict:
    directory = Path(tempfile.mkdtemp(prefix="ralphthon-rigor-"))
    (directory / "paper.md").write_text(text, encoding="utf-8")
    return parse_markdown(directory / "paper.md")


class RigorChecklistTests(unittest.TestCase):
    def test_bare_paper_gets_one_consolidated_question(self) -> None:
        parsed = _parse("# Study\n\nWe report an accuracy of 90.0 on the benchmark.\n")
        questions = rigor_checklist_questions(parsed)
        self.assertEqual(len(questions), 1)
        self.assertIn("reproducibility", questions[0]["text"].lower())
        self.assertIn("code or data", questions[0]["text"])

    def test_thorough_paper_self_suppresses(self) -> None:
        parsed = _parse(
            "# Study\n\n"
            "We release our code at github.com/x/y. We train with the Adam optimizer, a\n"
            "learning rate of 1e-4 and batch size 64 on 8 A100 GPUs.\n\n"
            "## Limitations\n\nOur method has limitations on long sequences.\n\n"
            "## Broader Impact\n\nWe discuss the societal impact of this work.\n"
        )
        self.assertEqual(rigor_checklist_missing(parsed), [])
        self.assertEqual(rigor_checklist_questions(parsed), [])

    def test_partial_paper_names_only_missing_items(self) -> None:
        # Has code + hyperparameters + compute; lacks limitations + broader impact.
        parsed = _parse(
            "# Study\n\nWe release code on github.com/x/y; trained with learning rate 1e-4 on V100 GPUs.\n"
        )
        missing = rigor_checklist_missing(parsed)
        self.assertIn("an explicit limitations discussion", missing)
        self.assertIn("a broader-impact / ethics statement", missing)
        self.assertNotIn("the training hyperparameters", missing)
        text = rigor_checklist_questions(parsed)[0]["text"]
        self.assertIn("limitations", text)
        self.assertNotIn("hyperparameters", text)


if __name__ == "__main__":
    unittest.main()
