"""M7 tests for content-addressed freeze records and verdict determinism."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reviewer import run_pipeline


ROOT = Path(__file__).resolve().parents[1]


class DeterminismFreezeTests(unittest.TestCase):
    def test_identical_hashes_produce_identical_verdict_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = run_pipeline(
                ROOT / "eval/papers/clean_val_bpb.md",
                ROOT / "eval/evidence/clean_val_bpb",
                Path(directory) / "first.md",
            )
            second = run_pipeline(
                ROOT / "eval/papers/clean_val_bpb.md",
                ROOT / "eval/evidence/clean_val_bpb",
                Path(directory) / "second.md",
            )

        first_labels = [(item["claim_id"], item["label"]) for item in first.verdicts]
        second_labels = [(item["claim_id"], item["label"]) for item in second.verdicts]
        self.assertEqual(first_labels, second_labels)
        self.assertEqual(first.review_identity, second.review_identity)
        self.assertEqual(first.verdict_digest, second.verdict_digest)
        self.assertRegex(first.agent_version, r"^sha256:[0-9a-f]{64}$")
        self.assertIn(f"Verdict labels digest: `{first.verdict_digest}`", first.review_markdown)

    def test_rerun_blocks_tampered_verdict_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review.md"
            first = run_pipeline(
                ROOT / "eval/papers/clean_val_bpb.md",
                ROOT / "eval/evidence/clean_val_bpb",
                output,
            )
            output.write_text(
                output.read_text(encoding="utf-8").replace(
                    first.verdict_digest, "sha256:" + "0" * 64
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "nondeterministic verdict labels"):
                run_pipeline(
                    ROOT / "eval/papers/clean_val_bpb.md",
                    ROOT / "eval/evidence/clean_val_bpb",
                    output,
                )


if __name__ == "__main__":
    unittest.main()
