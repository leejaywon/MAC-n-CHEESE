"""M7 tests for content-addressed freeze records and verdict determinism."""

from __future__ import annotations

import tempfile
import unittest
import shutil
from pathlib import Path
from unittest import mock

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

    def test_citation_lookup_state_changes_review_identity(self) -> None:
        citation_line = "Our method follows the cited work arXiv:1901.99999."
        unavailable_check = {
            "check": "citation-existence",
            "traces": [
                {
                    "provider": "arxiv",
                    "identifier": "1901.99999",
                    "status": "unavailable",
                    "title": None,
                    "error": "TimeoutError",
                    "location": {"line": 3},
                }
            ],
            "findings": [],
        }
        not_found_finding = {
            "check": "citation-existence",
            "severity": "error",
            "location": {"line": 3, "column_start": 1, "column_end": len(citation_line)},
            "expected": "a published record for 1901.99999",
            "observed": "the arXiv API returned no record for this identifier",
            "evidence_path": "https://export.arxiv.org/api/query?id_list=1901.99999",
        }
        not_found_check = {
            "check": "citation-existence",
            "traces": [
                {
                    "provider": "arxiv",
                    "identifier": "1901.99999",
                    "status": "not-found",
                    "title": None,
                    "error": None,
                    "location": {"line": 3},
                }
            ],
            "findings": [not_found_finding],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.md"
            evidence = root / "evidence"
            paper.write_text(f"# Citation Snapshot\n\n{citation_line}\n", encoding="utf-8")
            evidence.mkdir()
            with mock.patch(
                "reviewer.pipeline.check_citation_existence",
                return_value=unavailable_check,
            ):
                unavailable = run_pipeline(paper, evidence, root / "unavailable.md")
            with mock.patch(
                "reviewer.pipeline.check_citation_existence",
                return_value=not_found_check,
            ):
                not_found = run_pipeline(paper, evidence, root / "not-found.md")

        self.assertEqual(
            unavailable.mechanical_checks["citation-existence"]["traces"][0]["status"],
            "unavailable",
        )
        self.assertEqual(
            not_found.mechanical_checks["citation-existence"]["traces"][0]["status"],
            "not-found",
        )
        self.assertNotEqual(unavailable.verdict_digest, not_found.verdict_digest)
        self.assertNotEqual(unavailable.review_identity, not_found.review_identity)

    def test_content_identity_is_independent_of_local_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identities = []
            for name in ("first", "second"):
                run_root = root / name
                evidence = run_root / "evidence"
                run_root.mkdir()
                evidence.mkdir()
                paper = run_root / "paper.md"
                shutil.copyfile(ROOT / "eval/papers/clean_val_bpb.md", paper)
                state = run_pipeline(paper, evidence, run_root / "review.md")
                identities.append((state.review_identity, state.verdict_digest, state.scores))

        self.assertEqual(identities[0], identities[1])


if __name__ == "__main__":
    unittest.main()
