"""Tests for deterministic scientific positioning (related-work / novelty / SOTA).

These lock in the ICML-style Originality/Significance audit: a novelty or
state-of-the-art claim situated against no prior work is a proven Weakness that
lowers Contribution, while softer gaps stay Questions and a scoped paper making
no such claim is left alone (self-suppression, false-positive rule).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from reviewer import calibrate_scores, check_positioning, parse_markdown, run_pipeline
from reviewer.claims import extract_claims, label_verdicts


ROOT = Path(__file__).resolve().parents[1]


def _parse(text: str) -> dict:
    directory = Path(tempfile.mkdtemp(prefix="ralphthon-positioning-"))
    unittest.addModuleCleanup(shutil.rmtree, directory, ignore_errors=True)
    (directory / "paper.md").write_text(text, encoding="utf-8")
    return parse_markdown(directory / "paper.md")


class PositioningCheckTests(unittest.TestCase):
    # --- provable overclaim -> Weakness + Contribution demotion --------------

    def test_novelty_claim_without_any_prior_work_is_flagged(self) -> None:
        parsed = _parse(
            "# A New Method\n\n## Method\n\nWe propose a novel architecture for retrieval.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["subtype"], "novelty-overclaim")
        self.assertFalse(result["signals"]["positioned"])

    def test_sota_superiority_claim_without_prior_work_is_flagged(self) -> None:
        parsed = _parse(
            "# Results\n\nOur model achieves state-of-the-art and outperforms all systems.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["subtype"], "novelty-overclaim")

    # --- positioning present -> no overclaim finding -------------------------

    def test_novelty_claim_with_citations_is_not_flagged(self) -> None:
        parsed = _parse(
            "# A New Method\n\n## Related Work\n\nWe build on (Vaswani et al., 2017) and [12].\n\n"
            "## Method\n\nWe propose a novel architecture compared to the Transformer baseline.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["signals"]["positioned"])
        self.assertGreaterEqual(result["signals"]["citation_count"], 1)

    def test_related_work_section_alone_counts_as_positioning(self) -> None:
        parsed = _parse(
            "# Study\n\n## Prior Work\n\nMuch has been written.\n\n"
            "## Results\n\nWe present a novel finding.\n"
        )
        result = check_positioning(parsed)
        self.assertTrue(result["signals"]["has_related_work_section"])
        self.assertEqual(result["findings"], [])

    # --- softer gap -> Question, never accusation ----------------------------

    def test_comparatorless_superiority_on_positioned_paper_is_a_question(self) -> None:
        parsed = _parse(
            "# Study\n\n## Related Work\n\nWe cite [1] and [2].\n\n"
            "## Results\n\nOur approach outperforms significantly.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["questions"]), 1)
        self.assertIn("which specific prior method", result["questions"][0]["text"])

    # --- self-suppression: no novelty claim -> silent ------------------------

    def test_scoped_paper_with_no_novelty_claim_is_silent(self) -> None:
        parsed = _parse(
            "# Replication\n\n## Results\n\nAccuracy rose from 70.0 to 75.0 across three seeds.\n"
            "This minimal study makes no claim beyond the reported runs.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["questions"], [])

    def test_hypothetical_and_negated_claims_do_not_fire(self) -> None:
        parsed = _parse(
            "# Plan\n\nWe aim to outperform prior systems and hope to be novel.\n"
            "The method does not outperform the baseline yet.\n"
        )
        result = check_positioning(parsed)
        self.assertEqual(result["findings"], [])

    def test_incidental_claim_vocabulary_is_not_an_overclaim(self) -> None:
        # Task names and ordinary verbs contain "novel"/"beats"/"exceeds"/"first
        # to" — none is a novelty/superiority CLAIM, so no Weakness may fire.
        for sentence in (
            "We evaluate our system on novel view synthesis.",
            "The benchmark targets novel class discovery in images.",
            "The model predicts musical beats in each audio clip.",
            "When the batch is large the runtime exceeds the memory budget.",
            "We copy activations from the first to fourth layer of the network.",
            "We plan to outperform the baseline in future work.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(check_positioning(_parse(f"# R\n\n{sentence}\n"))["findings"], [])

    def test_hedged_real_overclaim_is_still_caught(self) -> None:
        # A stray hedge word ("would like", "potential", "hope to extend") must not
        # suppress a genuine unsituated SOTA/superiority claim.
        for sentence in (
            "We would like to note our method is state-of-the-art on every benchmark.",
            "Our approach outperforms all prior methods and has great potential.",
            "Our method is superior to all prior systems, and we hope to extend it further.",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(len(check_positioning(_parse(f"# R\n\n{sentence}\n"))["findings"]), 1)

    def test_square_bracket_author_year_counts_as_positioning(self) -> None:
        # The ACL Anthology / ICLR / NeurIPS "[Author, Year]" style must register,
        # so a well-cited paper is never falsely called unpositioned.
        parsed = _parse(
            "# A New Method\n\nWe cite [Vaswani et al., 2017] and [Devlin et al., 2019].\n"
            "We propose a novel architecture that improves retrieval.\n"
        )
        result = check_positioning(parsed)
        self.assertTrue(result["signals"]["positioned"])
        self.assertEqual(result["findings"], [])

    # --- scoring integration --------------------------------------------------

    def test_overclaim_lowers_contribution_score(self) -> None:
        parsed = _parse("# New\n\nWe present a novel state-of-the-art method.\n")
        positioning = check_positioning(parsed)
        claims = extract_claims(parsed)
        verdicts, _ = label_verdicts(claims, {}, [])
        scores = calibrate_scores(claims, verdicts, [], positioning=positioning)
        self.assertEqual(scores["Contribution"]["value"], 1)
        self.assertIn("no cited prior work", scores["Contribution"]["rationale"])

    def test_contribution_stays_borderline_without_overclaim(self) -> None:
        parsed = _parse("# Study\n\nAccuracy was 75.0 across three seeds.\n")
        positioning = check_positioning(parsed)
        claims = extract_claims(parsed)
        verdicts, _ = label_verdicts(claims, {}, [])
        scores = calibrate_scores(claims, verdicts, [], positioning=positioning)
        self.assertEqual(scores["Contribution"]["value"], 2)

    # --- end-to-end through the pipeline -------------------------------------

    def test_pipeline_renders_positioning_weakness_and_trace(self) -> None:
        paper = ROOT / "eval/papers/clean_val_bpb.md"
        # Craft an overclaiming peer paper and an empty evidence dir.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            peer = root / "peer.md"
            peer.write_text(
                "# Overclaimer\n\n## Method\n\n"
                "We introduce a novel method that outperforms every prior system.\n",
                encoding="utf-8",
            )
            evidence = root / "evidence"
            evidence.mkdir()
            state = run_pipeline(peer, evidence, root / "review.md")
        self.assertIn("Positioning —", state.review_markdown)
        self.assertIn("S3 positioning:", state.review_markdown)
        self.assertEqual(state.scores["Contribution"]["value"], 1)
        # A crafted overclaim must not leak into the mechanical-detection eval.
        self.assertNotIn("positioning", {finding.get("check") for finding in state.mechanical_findings})
        _ = paper  # anchor for readers: clean event papers self-suppress (see eval)


if __name__ == "__main__":
    unittest.main()
