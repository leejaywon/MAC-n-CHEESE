"""Tests for the platform score mapping (reviewer/api_scores.py).

These pin the correctness-critical identity mapping from the pipeline's direct
six-score vocabulary to the openagentreview.org body and the server-mirroring
validation that rejects a body the platform would 4xx.
"""

from __future__ import annotations

import types
import unittest

from reviewer.api_scores import (
    API_FIELDS,
    ScoreMappingError,
    public_comments,
    to_api_review,
    validate_api_review,
)


def _state(
    soundness: int = 3,
    presentation: int = 3,
    significance: int = 3,
    originality: int = 3,
    overall: int = 3,
    confidence: int = 3,
    review_markdown: str = (
        "## Summary\n\nA grounded, evidence-bound review body.\n\n"
        "## Comment\n\nThe assessment follows the cited evidence."
    ),
) -> types.SimpleNamespace:
    """A minimal stand-in for ReviewState: only the fields the mapper reads."""

    return types.SimpleNamespace(
        scores={
            "Soundness": {"value": soundness},
            "Presentation": {"value": presentation},
            "Significance": {"value": significance},
            "Originality": {"value": originality},
            "Overall recommendation": {"value": overall},
            "Confidence": {"value": confidence},
        },
        review_markdown=review_markdown,
    )


class MappingTests(unittest.TestCase):
    def test_public_comments_keep_only_scientific_review_content(self) -> None:
        review = (
            "## Paper and Evidence Identity\n\n/private/path sha256:"
            + "a" * 64
            + "\n\n## Summary\n\nPaper-specific assessment. Deterministic audit: "
            "0 contradiction(s), 0 finding(s); 99 unverifiable. Overall recommendation: "
            "3/6 [claim-001].\n\n## Strengths\n\n"
            "- A specific scientific strength. [paper:L1-L2]\n"
            "- The paper situates its contribution against prior work (12 citation(s); "
            "related-work section present).\n\n"
            "## Ethics and Limitations\n\nInternal sanitation trace.\n\n"
            "## Evidence Trace\n\nS1 parse -> S6 freeze.\n\n"
            "## Comment\n\nDuplicate recommendation."
        )

        comments = public_comments(review)

        self.assertIn("Paper-specific assessment.", comments)
        self.assertIn("A specific scientific strength.", comments)
        for private_text in (
            "Deterministic audit:",
            "situates its contribution",
            "Ethics and Limitations",
            "Evidence Trace",
            "Comment",
            "/private/path",
            "sha256:",
        ):
            self.assertNotIn(private_text, comments)

    def test_happy_path_produces_only_plain_ints(self) -> None:
        review = to_api_review(_state(), ordinal=1)
        self.assertEqual(set(review), set(API_FIELDS))
        for field in ("ordinal", "soundness", "presentation", "significance", "originality", "overall", "confidence"):
            self.assertIs(type(review[field]), int)
        self.assertIsInstance(review["comments"], str)
        validate_api_review(review)  # must not raise

    def test_significance_and_originality_are_direct(self) -> None:
        review = to_api_review(_state(significance=4, originality=2), ordinal=2)
        self.assertEqual(review["significance"], 4)
        self.assertEqual(review["originality"], 2)

    def test_overall_is_direct_one_to_six(self) -> None:
        self.assertEqual(to_api_review(_state(overall=1), ordinal=1)["overall"], 1)
        self.assertEqual(to_api_review(_state(overall=6), ordinal=1)["overall"], 6)

    def test_empty_comments_are_rejected(self) -> None:
        with self.assertRaises(ScoreMappingError):
            to_api_review(_state(review_markdown="   \n  "), ordinal=1)

    def test_missing_score_is_rejected(self) -> None:
        state = _state()
        del state.scores["Soundness"]
        with self.assertRaises(ScoreMappingError):
            to_api_review(state, ordinal=1)

    def test_bool_ordinal_is_rejected(self) -> None:
        with self.assertRaises(ScoreMappingError):
            to_api_review(_state(), ordinal=True)  # bool is not a valid ordinal


class ValidateTests(unittest.TestCase):
    def _valid(self) -> dict:
        return {
            "ordinal": 1,
            "soundness": 3,
            "presentation": 3,
            "significance": 3,
            "originality": 3,
            "overall": 4,
            "confidence": 3,
            "comments": "ok",
        }

    def test_valid_body_passes(self) -> None:
        validate_api_review(self._valid())

    def test_float_is_rejected(self) -> None:
        bad = self._valid() | {"soundness": 3.0}
        with self.assertRaises(ScoreMappingError):
            validate_api_review(bad)

    def test_bool_is_rejected(self) -> None:
        bad = self._valid() | {"confidence": True}
        with self.assertRaises(ScoreMappingError):
            validate_api_review(bad)

    def test_stringified_int_is_rejected(self) -> None:
        bad = self._valid() | {"overall": "4"}
        with self.assertRaises(ScoreMappingError):
            validate_api_review(bad)

    def test_extra_field_is_rejected(self) -> None:
        bad = self._valid() | {"reviewer": "nfl"}
        with self.assertRaises(ScoreMappingError):
            validate_api_review(bad)

    def test_missing_field_is_rejected(self) -> None:
        bad = self._valid()
        del bad["comments"]
        with self.assertRaises(ScoreMappingError):
            validate_api_review(bad)

    def test_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(ScoreMappingError):
            validate_api_review(self._valid() | {"overall": 7})

    def test_ordinal_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(ScoreMappingError):
            validate_api_review(self._valid() | {"ordinal": 11})


if __name__ == "__main__":
    unittest.main()
