"""Tests for committee prose hygiene (reviewer anonymity + de-puffing)."""

from __future__ import annotations

import unittest

from reviewer.prose_hygiene import sanitize


class ProseHygieneTests(unittest.TestCase):
    def test_reviewer_identity_line_removed(self) -> None:
        self.assertEqual(
            sanitize("Reviewer: MAC\nThe method is fine."), "The method is fine."
        )

    def test_process_meta_removed(self) -> None:
        out = sanitize("The batch was reviewed in this pipeline as an AI.").lower()
        for leaked in ("the batch", "in this pipeline", "as an ai"):
            self.assertNotIn(leaked, out)

    def test_first_person_stance_removed(self) -> None:
        self.assertEqual(
            sanitize("We believe that the method is sound."), "The method is sound."
        )
        self.assertEqual(
            sanitize("In our opinion, the design is weak."), "The design is weak."
        )

    def test_paper_voice_we_preserved(self) -> None:
        # "we show" reads as the paper's voice, not the reviewer's -> left alone.
        self.assertIn("we show", sanitize("The authors note that we show gains.").lower())

    def test_intensifier_adverbs_dropped(self) -> None:
        self.assertEqual(sanitize("This is genuinely useful."), "This is useful.")
        self.assertEqual(sanitize("The proof is remarkably clear."), "The proof is clear.")

    def test_genuine_adjective_preserved(self) -> None:
        self.assertEqual(
            sanitize("This is a genuine limitation."), "This is a genuine limitation."
        )

    def test_flourish_phrase_and_adjective(self) -> None:
        self.assertEqual(
            sanitize("The strongest part is the ablation."), "A strength is the ablation."
        )
        self.assertEqual(sanitize("It is a compelling argument."), "It is an argument.")
        self.assertEqual(sanitize("an exemplary evaluation of X"), "An evaluation of X")

    def test_grounding_ids_and_numbers_preserved(self) -> None:
        text = "The 28.4 BLEU result is genuine [claim-001]."
        self.assertEqual(sanitize(text), text)

    def test_empty_and_idempotent(self) -> None:
        self.assertEqual(sanitize(""), "")
        clean = "The method is clear and the evaluation is adequate."
        self.assertEqual(sanitize(clean), clean)
        self.assertEqual(sanitize(sanitize(clean)), clean)


if __name__ == "__main__":
    unittest.main()
