"""Deterministic Markdown parsing for stage S1.

The parser deliberately keeps a small, explicit output schema.  Later
mechanical checks need stable source locations more than a rendered Markdown
AST, and using line/column/offset coordinates makes every extracted item
traceable to the frozen paper text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .injection_scan import sanitize_for_analysis


ATX_HEADING_RE = re.compile(r"^( {0,3})(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
SETEXT_HEADING_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
NUMBER_RE = re.compile(
    r"(?<![\w.])"
    r"[+\-\N{MINUS SIGN}]?"
    r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:[eE][+\-]?\d+)?"
    # If a percent sign follows, it is part of the token rather than optional;
    # otherwise the regex engine can accept the shorter bare-number match.
    r"(?:\s*%|(?!\s*%))"
    r"(?!\w)"
)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    return offsets


def _fenced_lines(lines: list[str]) -> set[int]:
    """Return one-based line numbers inside or delimiting fenced code blocks."""

    fenced: set[int] = set()
    marker: str | None = None
    marker_length = 0
    for line_number, line in enumerate(lines, start=1):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker is None:
            if match:
                marker = match.group(1)[0]
                marker_length = len(match.group(1))
                fenced.add(line_number)
        else:
            fenced.add(line_number)
            if match and match.group(1)[0] == marker and len(match.group(1)) >= marker_length:
                marker = None
                marker_length = 0
    return fenced


def _heading_title(raw_title: str) -> str:
    return raw_title.strip()


def _extract_headings(lines: list[str], fenced: set[int]) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index].rstrip("\r\n")
        if line_number in fenced:
            index += 1
            continue

        match = ATX_HEADING_RE.match(line)
        if match:
            headings.append(
                {
                    "level": len(match.group(2)),
                    "title": _heading_title(match.group(3)),
                    "heading_line": line_number,
                    "content_line_start": line_number + 1,
                }
            )
            index += 1
            continue

        if index + 1 < len(lines) and index + 2 not in fenced and line.strip():
            underline = lines[index + 1].rstrip("\r\n")
            setext = SETEXT_HEADING_RE.match(underline)
            if setext:
                headings.append(
                    {
                        "level": 1 if setext.group(1).startswith("=") else 2,
                        "title": _heading_title(line),
                        "heading_line": line_number,
                        "content_line_start": line_number + 2,
                    }
                )
                index += 2
                continue
        index += 1
    return headings


def _extract_sections(lines: list[str], headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    first_heading_line = headings[0]["heading_line"] if headings else len(lines) + 1
    if any(line.strip() for line in lines[: first_heading_line - 1]):
        sections.append(
            {
                "id": "section-000",
                "parent_id": None,
                "level": 0,
                "title": "Preamble",
                "heading_line": None,
                "line_start": 1,
                "line_end": first_heading_line - 1,
                "content": "".join(lines[: first_heading_line - 1]).rstrip("\r\n"),
            }
        )

    stack: list[tuple[int, str]] = []
    id_offset = len(sections)
    for index, heading in enumerate(headings):
        section_id = f"section-{index + id_offset:03d}"
        while stack and stack[-1][0] >= heading["level"]:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        next_heading_line = (
            headings[index + 1]["heading_line"] if index + 1 < len(headings) else len(lines) + 1
        )
        line_start = heading["content_line_start"]
        line_end = next_heading_line - 1
        content = "".join(lines[line_start - 1 : line_end]).rstrip("\r\n")
        sections.append(
            {
                "id": section_id,
                "parent_id": parent_id,
                "level": heading["level"],
                "title": heading["title"],
                "heading_line": heading["heading_line"],
                "line_start": line_start,
                "line_end": line_end,
                "content": content,
            }
        )
        stack.append((heading["level"], section_id))

    if not sections and lines:
        sections.append(
            {
                "id": "section-000",
                "parent_id": None,
                "level": 0,
                "title": "Document",
                "heading_line": None,
                "line_start": 1,
                "line_end": len(lines),
                "content": "".join(lines).rstrip("\r\n"),
            }
        )
    return sections


def _section_for_line(sections: list[dict[str, Any]], line_number: int) -> str | None:
    heading_matches = [section for section in sections if section["heading_line"] == line_number]
    if heading_matches:
        return heading_matches[-1]["id"]
    matches = [
        section
        for section in sections
        if section["line_start"] <= line_number <= section["line_end"]
    ]
    return matches[-1]["id"] if matches else None


def _split_table_row(line: str) -> list[str]:
    """Split a GFM table row while preserving escaped pipe characters."""

    text = line.rstrip("\r\n").strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith(r"\|"):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    code_delimiter: str | None = None
    for character in text:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "`":
            code_delimiter = None if code_delimiter else "`"
            current.append(character)
        elif character == "|" and code_delimiter is None:
            cells.append("".join(current).strip().replace(r"\|", "|"))
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip().replace(r"\|", "|"))
    return cells


def _is_table_delimiter(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(TABLE_DELIMITER_CELL_RE.fullmatch(cell) for cell in cells)


def _extract_tables(
    lines: list[str], fenced: set[int], sections: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    index = 0
    while index + 1 < len(lines):
        header_line_number = index + 1
        delimiter_line_number = index + 2
        if (
            header_line_number in fenced
            or delimiter_line_number in fenced
            or "|" not in lines[index]
            or not _is_table_delimiter(lines[index + 1])
        ):
            index += 1
            continue

        header = _split_table_row(lines[index])
        alignments: list[str] = []
        for cell in _split_table_row(lines[index + 1]):
            left, right = cell.startswith(":"), cell.endswith(":")
            alignments.append("center" if left and right else "left" if left else "right" if right else "default")
        if len(header) != len(alignments):
            index += 1
            continue

        row_index = index + 2
        rows: list[dict[str, Any]] = []
        while row_index < len(lines):
            row_line_number = row_index + 1
            if row_line_number in fenced or "|" not in lines[row_index] or not lines[row_index].strip():
                break
            cells = _split_table_row(lines[row_index])
            if len(cells) != len(header):
                break
            rows.append({"line": row_line_number, "cells": cells})
            row_index += 1

        table_id = f"table-{len(tables):03d}"
        tables.append(
            {
                "id": table_id,
                "section_id": _section_for_line(sections, header_line_number),
                "line_start": header_line_number,
                "line_end": max(delimiter_line_number, row_index),
                "header": header,
                "alignments": alignments,
                "rows": rows,
            }
        )
        index = row_index
    return tables


def _normalize_number(token: str) -> tuple[str, str]:
    compact = token.strip().replace("\N{MINUS SIGN}", "-")
    kind = "percentage" if compact.endswith("%") else "number"
    if kind == "percentage":
        compact = compact[:-1].rstrip()
    return compact.replace(",", ""), kind


def _extract_numbers(
    lines: list[str], offsets: list[int], sections: list[dict[str, Any]], tables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    table_by_line: dict[int, str] = {}
    for table in tables:
        for line_number in range(table["line_start"], table["line_end"] + 1):
            table_by_line[line_number] = table["id"]

    numbers: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        source_line = line.rstrip("\r\n")
        for match in NUMBER_RE.finditer(source_line):
            normalized, kind = _normalize_number(match.group(0))
            numbers.append(
                {
                    "id": f"number-{len(numbers):04d}",
                    "token": match.group(0),
                    "normalized": normalized,
                    "kind": kind,
                    "location": {
                        "line": line_number,
                        "column_start": match.start() + 1,
                        "column_end": match.end(),
                        "offset_start": offsets[line_number - 1] + match.start(),
                        "offset_end": offsets[line_number - 1] + match.end(),
                        "section_id": _section_for_line(sections, line_number),
                        "table_id": table_by_line.get(line_number),
                    },
                    "context": source_line,
                }
            )
    return numbers


def parse_markdown(path: Path, *, text: str | None = None) -> dict[str, Any]:
    """Parse a UTF-8 Markdown paper into a JSON-serializable S1 document."""

    path = path.expanduser().resolve()
    if path.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError(f"S1 Markdown parser does not support: {path.suffix or '<no suffix>'}")
    if text is None:
        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"paper is not valid UTF-8 Markdown: {path}") from error
        text = sanitize_for_analysis(raw_text)
    elif not isinstance(text, str):
        raise TypeError("analysis text must be a string")

    lines = text.splitlines(keepends=True)
    fenced = _fenced_lines(lines)
    headings = _extract_headings(lines, fenced)
    sections = _extract_sections(lines, headings)
    tables = _extract_tables(lines, fenced, sections)
    numbers = _extract_numbers(lines, _line_offsets(lines), sections, tables)
    return {
        "schema_version": 1,
        "source_path": str(path),
        "analysis_text": text,
        "line_count": len(lines),
        "sections": sections,
        "tables": tables,
        "numeric_tokens": numbers,
    }


def paper_text(parsed_paper: dict[str, Any]) -> str:
    """Return the canonical sanitized text carried by parser output."""

    text = parsed_paper.get("analysis_text")
    if not isinstance(text, str):
        raise ValueError("parsed paper does not contain canonical analysis_text")
    return text
