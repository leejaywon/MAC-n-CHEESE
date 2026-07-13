"""PDF → Markdown ingestion.

The input is a paper PDF (or a Markdown manuscript), optionally with an evidence
bundle. The reviewer's S1 parser consumes Markdown, so a PDF is
converted to Markdown first (headings, tables, and prose preserved) and the rest
of the pipeline is unchanged. Markdown input passes through untouched.
"""

from __future__ import annotations

import importlib.metadata
import re
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


_IMAGE_OCR_BLOCK = re.compile(
    r"[ \t]*<!-- Start of picture text -->.*?<!-- End of picture text -->[ \t]*(?:\n|$)",
    re.DOTALL,
)


def _strip_margin_line_numbers(markdown: str) -> str:
    """Remove ICML/NeurIPS margin line numbers that extraction inlines.

    Submission PDFs number every line; pymupdf emits them as a long, near-monotonic
    run of small integers ("000 001 002 ... 384") interleaved with the prose, which
    poisons numeric/claim extraction. This threads that increasing sequence through
    the integer-token stream and removes only its members — real numbers (e.g. 512
    units, 53%) fall outside the running line-number band and are kept. It is a no-op
    on any document that is not densely line-numbered.
    """

    tokens = list(re.finditer(r"(?<![\w.])\d{1,4}(?![\w.,])", markdown))
    flags = [False] * len(tokens)
    expected: int | None = None
    for index, token in enumerate(tokens):
        value = int(token.group())
        if expected is None:
            if value <= 3:  # line numbering starts at 000/001
                expected, flags[index] = value, True
        elif expected <= value <= expected + 8:
            expected, flags[index] = value, True
    if expected is None or expected < 50 or sum(flags) < 30:
        return markdown  # not a line-numbered document
    out: list[str] = []
    cursor = 0
    for index, token in enumerate(tokens):
        if flags[index]:
            out.append(markdown[cursor:token.start()])
            cursor = token.end()
    out.append(markdown[cursor:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out))


def _strip_image_ocr(markdown: str) -> str:
    """Drop pymupdf4llm image-OCR blocks (figure/chart text) from the Markdown.

    pymupdf4llm wraps text recovered from images between
    ``<!-- Start of picture text -->`` and ``<!-- End of picture text -->``. On
    born-digital papers these are garbled OCR of plots and diagrams that inject
    spurious numeric tokens and prose into claim extraction. They are removed only
    when substantial real text survives, so an image-only (scanned) PDF whose
    whole content is OCR is left untouched.
    """

    stripped = _IMAGE_OCR_BLOCK.sub("", markdown)
    if len(stripped.strip()) < 200:
        return markdown
    return re.sub(r"\n{3,}", "\n\n", stripped).strip() + "\n"


_LEADING_BOILERPLATE = re.compile(
    r"(?:grants permission to reproduce"
    r"|permission to make digital or hard copies"
    r"|^\s*copyright\b"
    r"|^\s*\(c\)\s*\d{4}"
    r"|^\s*©\s*\d{4})",
    re.IGNORECASE,
)


def _strip_leading_boilerplate(markdown: str) -> str:
    """Drop publisher copyright/permission notices from the document head.

    Notices like the NeurIPS "...grants permission to reproduce..." line are
    extracted as the first page text and otherwise become the review's Summary
    lead. Only the leading region — before the first heading or first substantial
    prose line — is filtered, and only specific boilerplate is dropped, so body
    text and reference arXiv IDs are never touched.
    """

    out: list[str] = []
    body_started = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not body_started and stripped and _LEADING_BOILERPLATE.search(line):
            continue
        if stripped.startswith("#") or len(stripped) > 40:
            body_started = True
        out.append(line)
    return re.sub(r"\A\n+", "", "\n".join(out))


_TABLE_ROW_BOLD = re.compile(r"\*\*")
_TABLE_ROW_ITALIC = re.compile(r"_([^_\n]+?)_")


def _normalize_table_cells(markdown: str) -> str:
    """Strip spurious bold/italic emphasis from Markdown table cells.

    pymupdf4llm styles table text from PDF font flags, wrapping digits and
    punctuation in stray ``**``/``_`` (e.g. ``**28.4**`` or ``9_._6``) that corrupt
    the numeric tokens the reviewer extracts. Emphasis carries no meaning in these
    result tables, so it is removed from table rows only; prose emphasis and
    literal underscores (e.g. ``val_bpb``) elsewhere are left untouched. Paired
    ``_x_`` italics are collapsed but lone underscores are kept, so ``val_bpb``
    survives even inside a table cell.
    """

    out: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            line = _TABLE_ROW_BOLD.sub("", line)
            previous = None
            while previous != line:
                previous = line
                line = _TABLE_ROW_ITALIC.sub(r"\1", line)
        out.append(line)
    return "\n".join(out)


_NUMERIC_PUNCT_EMPHASIS = re.compile(r"(?<=\d)\s*[_*]+\s*([.,/·])\s*[_*]+\s*(?=\d)")


def _fix_numeric_emphasis(markdown: str) -> str:
    """Repair decimals/fractions split by pymupdf4llm emphasis styling.

    A font-style change on the separator makes pymupdf4llm emit e.g. ``28 _._ 4``
    for 28.4 or ``1 _/_ 4`` for 1/4, in both tables and prose, which breaks the
    reviewer's numeric-token extraction and leaks into extracted claims. Emphasis
    wrapped around a single separator *between two digits* is always this artifact
    — never real italics, which wrap words — so it is collapsed everywhere.
    """

    return _NUMERIC_PUNCT_EMPHASIS.sub(r"\1", markdown)


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
    markdown = _strip_margin_line_numbers(markdown)
    markdown = _strip_image_ocr(markdown)
    markdown = _strip_leading_boilerplate(markdown)
    markdown = _fix_numeric_emphasis(markdown)
    markdown = _normalize_table_cells(markdown)
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
