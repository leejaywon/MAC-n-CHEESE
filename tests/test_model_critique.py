"""Tests for the optional model critique (the --best judgment layer's model call).

A canned client stands in for the network so grounding enforcement and
calibration-only-lowers are verified deterministically: ungrounded praise is
dropped, an ungrounded criticism becomes a question, a lowering is applied and a
raise is refused, and malformed output degrades to empty.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from reviewer.model_critique import critique


GROUNDING = {
    "finding_ids": ["finding-001"],
    "claim_ids": ["claim-001"],
    "arxiv_ids": ["arxiv:1706.03762"],
}
ANCHORS = {
    "Soundness": 3,
    "Presentation": 2,
    "Significance": 2,
    "Originality": 2,
    "Overall recommendation": 4,
    "Confidence": 3,
}


def _client(response: dict):
    def call(messages):
        call.messages = messages
        return json.dumps(response)

    return call


class ModelCritiqueTests(unittest.TestCase):
    def _run(self, response: dict):
        return critique(
            sanitized_paper="A short sanitized paper about attention.",
            grounding=GROUNDING,
            anchor_scores=ANCHORS,
            api_key="sk-test",
            model="stub-model",
            client=_client(response),
        )

    def test_grounding_is_enforced_regardless_of_model_output(self) -> None:
        result = self._run(
            {
                "items": [
                    {"stance": "weakness", "text": "Variance is unreported.", "grounding": "finding-001"},
                    {"stance": "strength", "text": "Great idea.", "grounding": "not-an-id"},
                    {"stance": "weakness", "text": "Vague worry.", "grounding": "not-an-id"},
                    {"stance": "question", "text": "How does it differ?", "grounding": "arxiv:1706.03762"},
                ],
                "calibration": {},
            }
        )
        texts = [comment["text"] for comment in result["comments"]]
        # grounded weakness kept and cited
        self.assertTrue(any("Weakness — Variance is unreported. [finding-001]" == text for text in texts))
        # ungrounded praise dropped entirely
        self.assertFalse(any("Great idea" in text for text in texts))
        # ungrounded criticism demoted to a question, uncited
        self.assertTrue(any(text == "Question — Vague worry." for text in texts))
        # grounded question kept and cited
        self.assertTrue(any("Question — How does it differ? [arxiv:1706.03762]" == text for text in texts))

    def test_weakness_citing_a_plain_claim_is_demoted_to_question(self) -> None:
        # The core fairness fix: a generic criticism stapled to an ordinary
        # (unverifiable) claim id must NOT become a grounded Weakness. Only a
        # finding / contradicted-claim / arXiv id is defect-evidence; a plain
        # claim id demotes the criticism to a Question.
        result = self._run(
            {
                "items": [{"stance": "weakness", "text": "Missing baselines.", "grounding": "claim-001"}],
                "calibration": {},
            }
        )
        texts = [comment["text"] for comment in result["comments"]]
        self.assertEqual(texts, ["Question — Missing baselines. [claim-001]"])
        self.assertFalse(any(text.startswith("Weakness") for text in texts))

    def test_weakness_grounded_in_a_finding_stays_a_weakness(self) -> None:
        result = self._run(
            {
                "items": [{"stance": "weakness", "text": "Result contradicts the ledger.", "grounding": "finding-001"}],
                "calibration": {},
            }
        )
        self.assertEqual(
            [comment["text"] for comment in result["comments"]],
            ["Weakness — Result contradicts the ledger. [finding-001]"],
        )

    def test_calibration_only_lowers(self) -> None:
        result = self._run(
            {
                "items": [],
                "calibration": {
                    "Soundness": {
                        "value": 1,
                        "reason": "unproven headline",
                        "grounding": "finding-001",
                    },
                    "Originality": {
                        "value": 4,
                        "reason": "over-generous",
                        "grounding": "finding-001",
                    },
                    "Overall recommendation": {
                        "value": 4,
                        "reason": "unchanged",
                        "grounding": "finding-001",
                    },
                },
            }
        )
        # lowering applied
        self.assertEqual(result["calibration"]["Soundness"]["value"], 1)
        # a raise (4 > anchor 2) is refused
        self.assertNotIn("Originality", result["calibration"])
        # an equal value (4 == anchor 4) is not a lowering
        self.assertNotIn("Overall recommendation", result["calibration"])

    def test_malformed_output_degrades_to_empty(self) -> None:
        def bad_client(messages):
            return "this is not json"

        result = critique(
            sanitized_paper="paper",
            grounding=GROUNDING,
            anchor_scores=ANCHORS,
            api_key="sk-test",
            model="stub-model",
            client=bad_client,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["comments"], [])
        self.assertEqual(result["calibration"], {})
        self.assertTrue(result["prompt_sha256"])  # still auditable

    def test_prompt_records_model_and_hash(self) -> None:
        result = self._run({"items": [], "calibration": {}})
        self.assertTrue(result["ok"])
        self.assertTrue(result["model"])
        self.assertEqual(len(result["prompt_sha256"]), 64)

    def test_prompt_keeps_late_high_priority_sections_beyond_old_prefix(self) -> None:
        client = _client({"summary": "Summary", "items": [], "calibration": {}})
        paper = "# Title\n\n" + ("ordinary body text " * 900) + "\n\n## References\n\nTAIL-MARKER-REF\n"
        with mock.patch.dict(os.environ, {"REVIEWER_BEST_MAX_CHARS": "8000"}, clear=False):
            result = critique(
                sanitized_paper=paper,
                grounding=GROUNDING,
                anchor_scores=ANCHORS,
                api_key="sk-test",
                model="stub-model",
                client=client,
            )
        self.assertTrue(result["ok"])
        self.assertIn("TAIL-MARKER-REF", client.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
