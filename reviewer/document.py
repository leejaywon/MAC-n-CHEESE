"""Canonical paper preparation with original and derived source identities."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .injection_scan import scan_and_sanitize
from .to_markdown import converter_identity, pdf_to_markdown_with_visibility


@dataclass(frozen=True)
class SourceIdentity:
    path: str
    media_type: str
    sha256: str
    byte_length: int
    page_count: int | None


@dataclass(frozen=True)
class PreparedPaper:
    original: SourceIdentity
    markdown: SourceIdentity
    raw_text: str
    analysis_text: str
    sanitation_traces: tuple[dict[str, object], ...]
    injection_findings: tuple[dict[str, object], ...]
    converter: str | None


def _identity(path: Path, media_type: str, page_count: int | None) -> SourceIdentity:
    payload = path.read_bytes()
    return SourceIdentity(
        path=str(path),
        media_type=media_type,
        sha256=sha256(payload).hexdigest(),
        byte_length=len(payload),
        page_count=page_count,
    )


def _decode_markdown(payload: bytes, path: Path) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"paper is not valid UTF-8 Markdown: {path}") from error


def _pdf_page_count(path: Path) -> int:
    import pymupdf

    with pymupdf.open(path) as document:
        return document.page_count


def prepare_paper(path: Path, converted_path: Path | None = None) -> PreparedPaper:
    """Prepare Markdown or PDF once before any scientific analysis."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"paper is not a file: {source}")

    suffix = source.suffix.lower()
    converter: str | None = None
    visibility_traces: tuple[dict[str, object], ...] = ()
    visibility_findings: tuple[dict[str, object], ...] = ()
    if suffix in {".md", ".markdown"}:
        payload = source.read_bytes()
        raw_text = _decode_markdown(payload, source)
        original = _identity(source, "text/markdown", None)
        markdown = original
    elif suffix == ".pdf":
        page_count = _pdf_page_count(source)
        original = _identity(source, "application/pdf", page_count)
        target = (
            Path(converted_path).expanduser().resolve()
            if converted_path is not None
            else source.parent / ".reviewer_sources" / f"{source.stem}.md"
        )
        if target == source:
            raise ValueError("converted Markdown path must differ from the PDF path")
        target.parent.mkdir(parents=True, exist_ok=True)
        conversion = pdf_to_markdown_with_visibility(source)
        raw_text = conversion.markdown
        visibility_traces = conversion.visibility_traces
        visibility_findings = conversion.visibility_findings
        target.write_text(raw_text, encoding="utf-8")
        markdown = _identity(target, "text/markdown", None)
        converter = converter_identity()
    else:
        raise ValueError(
            f"unsupported paper format: {suffix or '<no suffix>'} (expected .pdf or .md)"
        )

    analysis_text, text_traces, text_findings = scan_and_sanitize(
        raw_text,
        source.name,
    )
    sanitation_traces = (*visibility_traces, *text_traces)
    injection_findings = (*visibility_findings, *text_findings)
    return PreparedPaper(
        original=original,
        markdown=markdown,
        raw_text=raw_text,
        analysis_text=analysis_text,
        sanitation_traces=sanitation_traces,
        injection_findings=injection_findings,
        converter=converter,
    )
