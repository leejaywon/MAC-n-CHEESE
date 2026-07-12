"""Hermetic tests for the fresh-random arXiv PDF smoke harness."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from eval import random_pdf_smoke as smoke


REQUIRED_REVIEW = """# Track 2 — ICML-Style Review

## Paper and Evidence Identity

identity

## Summary

summary

## Strengths

- strength

## Weaknesses

- weakness

## Questions for the Authors

- question

## Scores

scores

## Ethics and Limitations

ethics

## Evidence Trace

- Frozen review identity: `sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`.
- Verdict labels digest: `sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`.

## Comment

comment
"""


def _atom_feed(arxiv_id: str, title: str, category: str, pdf_url: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/{arxiv_id}</id>
    <title>{title}</title>
    <updated>2026-07-12T00:00:00Z</updated>
    <category term="{category}" />
    <arxiv:primary_category term="{category}" />
    <link rel="related" type="application/pdf" href="{pdf_url}" title="pdf" />
  </entry>
</feed>
""".encode("utf-8")


def _prepared(pdf_path: Path, converted_path: Path | None = None) -> SimpleNamespace:
    payload = pdf_path.read_bytes()
    markdown = converted_path or pdf_path.with_suffix(".md")
    markdown.write_text("# Paper\n\n## Results\n\nAccuracy is 80%.", encoding="utf-8")
    original = SimpleNamespace(
        path=str(pdf_path.resolve()),
        media_type="application/pdf",
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        page_count=2,
    )
    derived_payload = markdown.read_bytes()
    derived = SimpleNamespace(
        path=str(markdown.resolve()),
        media_type="text/markdown",
        sha256=hashlib.sha256(derived_payload).hexdigest(),
        byte_length=len(derived_payload),
        page_count=None,
    )
    return SimpleNamespace(
        original=original,
        markdown=derived,
        raw_text=derived_payload.decode("utf-8"),
        analysis_text=derived_payload.decode("utf-8"),
        sanitation_traces=(),
        injection_findings=(),
        converter="fake-pdf-converter",
    )


def _review_state(
    prepared: SimpleNamespace,
    output_path: Path,
    *,
    mode: str = "audit",
) -> SimpleNamespace:
    output_path.write_text(REQUIRED_REVIEW, encoding="utf-8")
    return SimpleNamespace(
        original_identity=prepared.original,
        page_count=prepared.original.page_count,
        scores={
            "Soundness": {"value": 3, "scale": "1-4"},
            "Presentation": {"value": 3, "scale": "1-4"},
            "Significance": {"value": 3, "scale": "1-4"},
            "Originality": {"value": 3, "scale": "1-4"},
            "Overall recommendation": {"value": 4, "scale": "1-6"},
            "Confidence": {"value": 3, "scale": "1-5"},
        },
        review_markdown=REQUIRED_REVIEW,
        review_identity="sha256:" + ("a" * 64),
        verdict_digest="sha256:" + ("b" * 64),
        judgment={},
        mode=mode,
    )


class RandomPDFSmokeTests(unittest.TestCase):
    def _network(self) -> tuple[object, object, dict[str, bytes], list[str]]:
        identifiers = {
            category: f"2607.{index:05d}v1"
            for index, category in enumerate(smoke.ARXIV_CATEGORIES, start=1)
        }
        pdfs = {
            f"https://arxiv.org/pdf/{arxiv_id}": f"%PDF-{category}".encode("ascii")
            for category, arxiv_id in identifiers.items()
        }
        feed_calls: list[str] = []

        def fetch_feed(url: str) -> bytes:
            feed_calls.append(url)
            query = parse_qs(urlsplit(url).query)["search_query"][0]
            category = query.removeprefix("cat:")
            arxiv_id = identifiers[category]
            return _atom_feed(
                arxiv_id,
                f"A recent {category} paper",
                category,
                f"https://arxiv.org/pdf/{arxiv_id}",
            )

        def fetch_pdf(url: str) -> bytes:
            return pdfs[url]

        return fetch_feed, fetch_pdf, pdfs, feed_calls

    def test_discovery_and_selection_cover_all_requested_categories(self) -> None:
        fetch_feed, _, _, feed_calls = self._network()

        discovered = smoke.discover_recent_papers(fetch_feed=fetch_feed)
        selected = smoke.select_diverse_papers(
            discovered,
            count=len(smoke.ARXIV_CATEGORIES),
            seed=17,
        )

        self.assertEqual(set(smoke.ARXIV_CATEGORIES), {paper["category"] for paper in selected})
        self.assertEqual(len(feed_calls), len(smoke.ARXIV_CATEGORIES))
        for category in smoke.ARXIV_CATEGORIES:
            self.assertTrue(any(f"cat%3A{category}" in url for url in feed_calls))

    def test_manifest_is_complete_and_persisted_before_review(self) -> None:
        fetch_feed, fetch_pdf, _, _ = self._network()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            review_calls: list[str] = []

            def run_pipeline(
                pdf_path: Path,
                evidence_dir: Path,
                output_path: Path,
                mode: str = "audit",
                *,
                prepared_paper: SimpleNamespace,
            ) -> SimpleNamespace:
                self.assertTrue(manifest_path.is_file())
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(len(manifest["papers"]), len(smoke.ARXIV_CATEGORIES))
                self.assertTrue(all(paper["sha256"] for paper in manifest["papers"]))
                review_calls.append(pdf_path.name)
                return _review_state(prepared_paper, output_path, mode=mode)

            report = smoke.run_smoke(
                count=len(smoke.ARXIV_CATEGORIES),
                seed=123,
                mode="audit",
                run_dir=root,
                fetch_feed=fetch_feed,
                fetch_pdf=fetch_pdf,
                prepare_paper_fn=_prepared,
                run_pipeline_fn=run_pipeline,
                now_fn=lambda: datetime(2026, 7, 12, 6, 0, tzinfo=timezone.utc),
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["seed"], 123)
            self.assertEqual(manifest["mode"], "audit")
            self.assertEqual(manifest["created_at"], "2026-07-12T15:00:00+09:00")
            self.assertEqual(len(review_calls), len(smoke.ARXIV_CATEGORIES))
            self.assertTrue(all(result["ok"] for result in report["results"]))
            for paper in manifest["papers"]:
                self.assertEqual(
                    set(paper),
                    {"arxiv_id", "title", "category", "pdf_url", "sha256"},
                )

    def test_replay_skips_discovery_and_reviews_the_frozen_papers(self) -> None:
        payload = b"%PDF-replay"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "frozen.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "seed": 991,
                        "created_at": "2026-07-12T15:00:00+09:00",
                        "mode": "audit",
                        "papers": [
                            {
                                "arxiv_id": "2607.00991v1",
                                "title": "Replay me",
                                "category": "cs.LG",
                                "pdf_url": "https://arxiv.org/pdf/2607.00991v1",
                                "sha256": digest,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            reviewed: list[Path] = []

            def no_discovery(_: str) -> bytes:
                self.fail("replay queried arXiv")

            def run_pipeline(
                pdf_path: Path,
                evidence_dir: Path,
                output_path: Path,
                mode: str = "audit",
                *,
                prepared_paper: SimpleNamespace,
            ) -> SimpleNamespace:
                reviewed.append(pdf_path)
                return _review_state(prepared_paper, output_path, mode=mode)

            report = smoke.run_smoke(
                replay=manifest_path,
                run_dir=root / "replay",
                fetch_feed=no_discovery,
                fetch_pdf=lambda _: payload,
                prepare_paper_fn=_prepared,
                run_pipeline_fn=run_pipeline,
            )

            self.assertEqual(report["seed"], 991)
            self.assertEqual(report["replay_manifest"], str(manifest_path.resolve()))
            self.assertEqual(len(reviewed), 1)
            self.assertTrue(report["results"][0]["ok"])

    def test_replay_hash_mismatch_blocks_only_that_paper(self) -> None:
        expected = hashlib.sha256(b"%PDF-expected").hexdigest()
        good_payload = b"%PDF-good"
        good_digest = hashlib.sha256(good_payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "frozen.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "seed": 4,
                        "created_at": "2026-07-12T15:00:00+09:00",
                        "mode": "audit",
                        "papers": [
                            {
                                "arxiv_id": "2607.00001v1",
                                "title": "Tampered",
                                "category": "cs.AI",
                                "pdf_url": "https://arxiv.org/pdf/bad",
                                "sha256": expected,
                            },
                            {
                                "arxiv_id": "2607.00002v1",
                                "title": "Intact",
                                "category": "cs.CL",
                                "pdf_url": "https://arxiv.org/pdf/good",
                                "sha256": good_digest,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            prepared_paths: list[Path] = []

            def prepare(path: Path, converted_path: Path | None = None) -> SimpleNamespace:
                prepared_paths.append(path)
                return _prepared(path, converted_path)

            report = smoke.run_smoke(
                replay=manifest_path,
                run_dir=root / "replay",
                fetch_feed=lambda _: self.fail("replay queried arXiv"),
                fetch_pdf=lambda url: b"%PDF-tampered" if url.endswith("/bad") else good_payload,
                prepare_paper_fn=prepare,
                run_pipeline_fn=lambda path, evidence, output, mode="audit", *, prepared_paper: _review_state(
                    prepared_paper, output, mode=mode
                ),
            )

            by_id = {result["arxiv_id"]: result for result in report["results"]}
            self.assertFalse(by_id["2607.00001v1"]["ok"])
            self.assertIn("sha256 mismatch", by_id["2607.00001v1"]["error"])
            self.assertTrue(by_id["2607.00002v1"]["ok"])
            self.assertEqual(len(prepared_paths), 1)

    def test_one_review_failure_does_not_block_other_papers(self) -> None:
        fetch_feed, fetch_pdf, pdfs, _ = self._network()
        bad_url = sorted(pdfs)[2]
        pdfs[bad_url] = b"%PDF-bad"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline_calls: list[str] = []

            def prepare(path: Path, converted_path: Path | None = None) -> SimpleNamespace:
                if path.read_bytes() == b"%PDF-bad":
                    raise ValueError("synthetic conversion failure")
                return _prepared(path, converted_path)

            def run_pipeline(
                pdf_path: Path,
                evidence_dir: Path,
                output_path: Path,
                mode: str = "audit",
                *,
                prepared_paper: SimpleNamespace,
            ) -> SimpleNamespace:
                pipeline_calls.append(pdf_path.name)
                return _review_state(prepared_paper, output_path, mode=mode)

            report = smoke.run_smoke(
                count=len(smoke.ARXIV_CATEGORIES),
                seed=8,
                run_dir=root,
                fetch_feed=fetch_feed,
                fetch_pdf=fetch_pdf,
                prepare_paper_fn=prepare,
                run_pipeline_fn=run_pipeline,
            )

            self.assertEqual(sum(result["ok"] for result in report["results"]), 4)
            failure = next(result for result in report["results"] if not result["ok"])
            self.assertIn("synthetic conversion failure", failure["error"])
            self.assertEqual(len(pipeline_calls), 4)

    def test_default_seed_uses_64_random_bits(self) -> None:
        with mock.patch.object(smoke.secrets, "randbits", return_value=0xC0FFEE) as randbits:
            self.assertEqual(smoke.resolve_seed(None), 0xC0FFEE)
        randbits.assert_called_once_with(64)


if __name__ == "__main__":
    unittest.main()
