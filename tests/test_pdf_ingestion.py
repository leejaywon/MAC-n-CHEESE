"""PDF ingestion tests using generated, temporary PyMuPDF documents."""

from __future__ import annotations

import hashlib
import importlib.metadata
import tempfile
import unittest
from pathlib import Path

import pymupdf

from reviewer import run_pipeline
from reviewer.document import prepare_paper


def _write_two_page_pdf(path: Path) -> None:
    document = pymupdf.open()
    try:
        first = document.new_page()
        first.insert_text((72, 72), "Canonical PDF Paper", fontsize=18)
        first.insert_text((72, 110), "The visible result reaches 80 percent.")
        second = document.new_page()
        second.insert_text((72, 72), "Limitations", fontsize=18)
        second.insert_text((72, 110), "This evaluation uses one benchmark.")
        document.save(path)
    finally:
        document.close()


class PDFIngestionTests(unittest.TestCase):
    def test_pdf_preparation_preserves_original_and_derived_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            markdown = root / "derived.md"
            _write_two_page_pdf(pdf)
            pdf_bytes = pdf.read_bytes()

            prepared = prepare_paper(pdf, converted_path=markdown)
            markdown_bytes = markdown.read_bytes()

        self.assertEqual(prepared.original.path, str(pdf.resolve()))
        self.assertEqual(prepared.original.media_type, "application/pdf")
        self.assertEqual(prepared.original.sha256, hashlib.sha256(pdf_bytes).hexdigest())
        self.assertEqual(prepared.original.byte_length, len(pdf_bytes))
        self.assertEqual(prepared.original.page_count, 2)

        self.assertEqual(prepared.markdown.path, str(markdown.resolve()))
        self.assertEqual(prepared.markdown.media_type, "text/markdown")
        self.assertEqual(
            prepared.markdown.sha256,
            hashlib.sha256(markdown_bytes).hexdigest(),
        )
        self.assertEqual(prepared.markdown.byte_length, len(markdown_bytes))
        self.assertIsNone(prepared.markdown.page_count)
        self.assertNotEqual(prepared.original.sha256, prepared.markdown.sha256)
        self.assertEqual(prepared.raw_text, markdown_bytes.decode("utf-8"))
        self.assertTrue(prepared.analysis_text.strip())
        self.assertEqual(
            prepared.converter,
            f"pymupdf4llm=={importlib.metadata.version('pymupdf4llm')}",
        )

    def test_pipeline_freezes_and_renders_both_pdf_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            markdown = root / "derived.md"
            evidence = root / "evidence"
            review = root / "review.md"
            evidence.mkdir()
            _write_two_page_pdf(pdf)

            prepared = prepare_paper(pdf, converted_path=markdown)
            state = run_pipeline(
                pdf,
                evidence,
                review,
                prepared_paper=prepared,
            )

            self.assertEqual(state.prepared_paper, prepared)
            self.assertEqual(state.original_identity, prepared.original)
            self.assertEqual(state.derived_identity, prepared.markdown)
            self.assertEqual(state.page_count, 2)
            self.assertEqual(state.converter, prepared.converter)
            self.assertEqual(state.sanitation_traces, list(prepared.sanitation_traces))
            self.assertEqual(state.injection_findings, list(prepared.injection_findings))
            self.assertEqual(state.paper_hash, prepared.markdown.sha256)
            self.assertRegex(state.review_identity, r"^sha256:[0-9a-f]{64}$")

            rendered = review.read_text(encoding="utf-8")
            self.assertIn(
                f"Original paper identity: `{prepared.original.path}` / "
                f"`application/pdf` / `sha256:{prepared.original.sha256}`",
                rendered,
            )
            self.assertIn(
                f"Derived Markdown identity: `{prepared.markdown.path}` / "
                f"`text/markdown` / `sha256:{prepared.markdown.sha256}`",
                rendered,
            )
            self.assertIn("Original PDF page count: `2`", rendered)
            self.assertIn(f"Converter: `{prepared.converter}`", rendered)


if __name__ == "__main__":
    unittest.main()
