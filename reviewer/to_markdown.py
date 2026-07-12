"""PDF → Markdown ingestion.

The competition input for each set is a Track 1 paper PDF (or frozen manuscript)
plus an evidence bundle. The reviewer's S1 parser consumes Markdown, so a PDF is
converted to Markdown first (headings, tables, and prose preserved) and the rest
of the pipeline is unchanged. Markdown input passes through untouched.
"""

from __future__ import annotations

from pathlib import Path


def pdf_to_markdown(pdf_path: Path) -> str:
    """Convert a PDF to GitHub-flavored Markdown via PyMuPDF (headings + tables)."""

    import pymupdf4llm  # imported lazily so Markdown-only runs need no PDF dependency

    return pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)


def convert_to_markdown(paper_path: Path, out_md: Path | None = None) -> Path:
    """Return a Markdown path for ``paper_path``.

    A ``.md``/``.markdown`` paper is returned unchanged. A ``.pdf`` is converted and
    written to ``out_md`` (default: the PDF path with a ``.md`` suffix), and that
    path is returned. Any other suffix is rejected.
    """

    paper_path = Path(paper_path).expanduser().resolve()
    suffix = paper_path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return paper_path
    if suffix != ".pdf":
        raise ValueError(f"unsupported paper format: {suffix or '<no suffix>'} (expected .pdf or .md)")
    markdown = pdf_to_markdown(paper_path)
    out_md = Path(out_md).expanduser().resolve() if out_md else paper_path.with_suffix(".md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(markdown, encoding="utf-8")
    return out_md
