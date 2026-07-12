"""PDF → Markdown ingestion.

The competition input for each set is a Track 1 paper PDF (or frozen manuscript)
plus an evidence bundle. The reviewer's S1 parser consumes Markdown, so a PDF is
converted to Markdown first (headings, tables, and prose preserved) and the rest
of the pipeline is unchanged. Markdown input passes through untouched.
"""

from __future__ import annotations

import importlib.metadata
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PDF_VISIBILITY_POLICY = "pdf-visibility-v1"


@dataclass(frozen=True)
class PdfMarkdownConversion:
    markdown: str
    visibility_traces: tuple[dict[str, Any], ...]
    visibility_findings: tuple[dict[str, Any], ...]


def converter_identity() -> str:
    """Return stable provenance for the installed PDF converter."""

    return (
        f"pymupdf4llm=={importlib.metadata.version('pymupdf4llm')};"
        f"{PDF_VISIBILITY_POLICY}"
    )


def _rgb(color: object) -> tuple[int, int, int]:
    value = color if type(color) is int else 0
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255.0
        return (
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(
    first: tuple[int, int, int], second: tuple[int, int, int]
) -> float:
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    light = max(first_luminance, second_luminance)
    dark = min(first_luminance, second_luminance)
    return (light + 0.05) / (dark + 0.05)


def _page_background(page: Any) -> tuple[int, int, int]:
    """Estimate the dominant page background without trusting PDF metadata."""

    import pymupdf

    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(0.25, 0.25),
        colorspace=pymupdf.csRGB,
        alpha=False,
    )
    width, height, channels = pixmap.width, pixmap.height, pixmap.n
    samples = pixmap.samples
    step_x = max(1, width // 32)
    step_y = max(1, height // 32)
    red: list[int] = []
    green: list[int] = []
    blue: list[int] = []
    for y in range(0, height, step_y):
        for x in range(0, width, step_x):
            offset = (y * width + x) * channels
            red.append(samples[offset])
            green.append(samples[offset + 1])
            blue.append(samples[offset + 2])
    return (
        int(statistics.median(red)) if red else 255,
        int(statistics.median(green)) if green else 255,
        int(statistics.median(blue)) if blue else 255,
    )


def _concealment_reasons(
    span: dict[str, Any],
    background: tuple[int, int, int],
) -> tuple[list[str], float]:
    foreground = _rgb(span.get("color"))
    contrast = _contrast_ratio(foreground, background)
    reasons: list[str] = []
    alpha = span.get("alpha", 255)
    if isinstance(alpha, (int, float)) and not isinstance(alpha, bool) and alpha <= 32:
        reasons.append("transparent")
    if contrast < 1.4:
        reasons.append("low-contrast")
    size = span.get("size")
    if isinstance(size, (int, float)) and not isinstance(size, bool) and size < 0.75:
        reasons.append("sub-pixel")
    char_flags = span.get("char_flags")
    if type(char_flags) is int and char_flags & 0b11000 == 0:
        reasons.append("non-rendering")
    return reasons, contrast


def pdf_to_markdown_with_visibility(pdf_path: Path) -> PdfMarkdownConversion:
    """Quarantine concealed PDF text before Markdown extraction.

    The converter otherwise flattens text color/alpha and makes near-white or
    non-rendering payloads indistinguishable from visible manuscript content.
    This pass estimates each page background, removes only text spans with
    inadequate visual contrast (or explicit non-rendering metadata), and records
    location-only findings. Concealed text itself never reaches Markdown,
    parsing, scoring, or model prompts.
    """

    import pymupdf
    import pymupdf4llm

    source = Path(pdf_path).expanduser().resolve()
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    temporary_path: Path | None = None
    with pymupdf.open(source) as document:
        for page_index, page in enumerate(document):
            background = _page_background(page)
            redactions: list[Any] = []
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if not isinstance(block, dict):
                    continue
                for line in block.get("lines", []):
                    if not isinstance(line, dict):
                        continue
                    for span in line.get("spans", []):
                        if not isinstance(span, dict):
                            continue
                        text = span.get("text")
                        bbox = span.get("bbox")
                        if (
                            not isinstance(text, str)
                            or not text.strip()
                            or not isinstance(bbox, (tuple, list))
                            or len(bbox) != 4
                        ):
                            continue
                        reasons, contrast = _concealment_reasons(span, background)
                        if not reasons:
                            continue
                        rect = pymupdf.Rect(*bbox) & page.rect
                        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                            continue
                        redactions.append(rect)
                        location = {
                            "page": page_index + 1,
                            "bbox": [round(value, 2) for value in rect],
                        }
                        trace = {
                            "location": location,
                            "policy": PDF_VISIBILITY_POLICY,
                            "reasons": reasons,
                            "character_count": len(text),
                            "contrast_ratio": round(contrast, 4),
                            "removed_content": "[concealed PDF text quarantined]",
                        }
                        traces.append(trace)
                        findings.append(
                            {
                                "check": "injection-scan",
                                "severity": "high",
                                "location": location,
                                "expected": (
                                    "scientific content rendered with sufficient "
                                    "visibility to a human reader"
                                ),
                                "observed": (
                                    "concealed PDF text was quarantined before "
                                    f"analysis ({', '.join(reasons)})"
                                ),
                                "evidence_path": source.name,
                            }
                        )
            for rect in redactions:
                page.add_redact_annot(rect, fill=None, cross_out=False)
            if redactions:
                page.apply_redactions(images=0, graphics=0, text=0)

        if traces:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                temporary_path = Path(handle.name)
            document.save(temporary_path, garbage=4, deflate=True)

    conversion_source = temporary_path or source
    try:
        markdown = pymupdf4llm.to_markdown(
            str(conversion_source),
            show_progress=False,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return PdfMarkdownConversion(
        markdown=markdown,
        visibility_traces=tuple(traces),
        visibility_findings=tuple(findings),
    )


def pdf_to_markdown(pdf_path: Path) -> str:
    """Convert visible PDF content to GitHub-flavored Markdown."""

    return pdf_to_markdown_with_visibility(pdf_path).markdown


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
