"""Sanitize paper text and detect reviewer-directed prompt injection.

Paper text is always data.  Hidden markup and Unicode format controls are
removed before S2 claim extraction, while S3 records only high-precision
reviewer-directed instructions as findings.  Suspicious formatting without an
instruction is retained as an audit trace rather than treated as wrongdoing.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HIDDEN_ELEMENT_RE = re.compile(
    r"<(?P<tag>[a-z][\w:-]*)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)\s*>",
    re.I | re.S,
)
HIDDEN_STYLE_RE = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\D|$)|"
    r"font-size\s*:\s*0(?:px|pt|em|rem|%)?|color\s*:\s*(?:white|#fff(?:fff)?|"
    r"rgba?\(\s*255\s*,\s*255\s*,\s*255))",
    re.I,
)
INSTRUCTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:give|assign|award)\s+(?:this\s+paper\s+)?(?:a\s+)?high\s+score\b", re.I),
    re.compile(r"\b(?:reviewer|reviewers|review\s+agent)\s*[:,]\s*(?:must\s+)?(?:accept|approve|recommend\s+acceptance)\b", re.I),
    re.compile(r"\b(?:you|reviewer|reviewers)\s+must\s+(?:accept|approve|give|assign|ignore)\b", re.I),
    re.compile(r"\b(?:do\s+not|never)\s+(?:report|mention|flag|disclose)\s+(?:this|the\s+instruction|the\s+attack)\b", re.I),
)


def _is_invisible(character: str) -> bool:
    # Preserve ordinary whitespace/newlines. Unicode format controls are not
    # semantically needed in the event's Markdown and can conceal instructions.
    return unicodedata.category(character) == "Cf"


def _strip_invisible(text: str) -> tuple[str, int]:
    count = sum(_is_invisible(character) for character in text)
    return "".join(character for character in text if not _is_invisible(character)), count


def _blank_fragment(text: str) -> str:
    """Remove hidden content without changing later line/column offsets."""

    return "".join(character if character in "\r\n" else " " for character in text)


def _hidden_fragments(text: str) -> tuple[tuple[int, int, str], ...]:
    """Locate hidden fragments using the same bounded rules as sanitation."""

    fragments: list[tuple[int, int, str]] = []

    def remove_comment(match: re.Match[str]) -> str:
        fragments.append((match.start(), match.end(), match.group(0)))
        return _blank_fragment(match.group(0))

    sanitized = HTML_COMMENT_RE.sub(remove_comment, text)
    previous = None
    for _ in range(4):
        if sanitized == previous:
            break
        previous = sanitized

        def remove_hidden(match: re.Match[str]) -> str:
            if not HIDDEN_STYLE_RE.search(match.group("attrs")):
                return match.group(0)
            fragments.append((match.start(), match.end(), match.group(0)))
            return _blank_fragment(match.group(0))

        sanitized = HIDDEN_ELEMENT_RE.sub(remove_hidden, sanitized)

    unique = {
        (start, end, fragment)
        for start, end, fragment in fragments
    }
    return tuple(sorted(unique, key=lambda item: (item[0], item[1], item[2])))


def _sanitize_hidden(text: str) -> str:
    without_comments = HTML_COMMENT_RE.sub(
        lambda match: _blank_fragment(match.group(0)),
        text,
    )

    def remove_hidden(match: re.Match[str]) -> str:
        return (
            _blank_fragment(match.group(0))
            if HIDDEN_STYLE_RE.search(match.group("attrs"))
            else match.group(0)
        )

    previous = None
    sanitized = without_comments
    # Bounded repetition handles a hidden element nested one level inside
    # another without turning this conservative sanitizer into an HTML parser.
    for _ in range(4):
        if sanitized == previous:
            break
        previous = sanitized
        sanitized = HIDDEN_ELEMENT_RE.sub(remove_hidden, sanitized)
    sanitized, _ = _strip_invisible(sanitized)
    return sanitized


def _plain_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _instruction_matches(text: str) -> list[str]:
    normalized, _ = _strip_invisible(unicodedata.normalize("NFKC", text))
    # Comments are hidden from rendering but their body must remain visible to
    # the detector; stripping generic HTML first would erase the whole attack.
    normalized = HTML_COMMENT_RE.sub(lambda match: match.group(0)[4:-3], normalized)
    plain = re.sub(r"\s+", " ", _plain_html(normalized)).strip()
    return [match.group(0) for pattern in INSTRUCTION_PATTERNS for match in pattern.finditer(plain)]


def sanitize_for_analysis(text: str) -> str:
    """Remove non-visible payloads and Unicode format controls deterministically."""

    return _sanitize_hidden(text)


def _finding(line: int, observed: str, source: str) -> dict[str, Any]:
    return {
        "check": "injection-scan",
        "severity": "high",
        "location": {"line": line},
        "expected": "paper content that does not direct or manipulate the reviewer",
        "observed": observed,
        "evidence_path": source,
    }


def scan_and_sanitize(
    raw_text: str,
    source_name: str,
) -> tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Sanitize once and report instructions found in the original raw text."""

    analysis_text = _sanitize_hidden(raw_text)
    raw_lines = raw_text.splitlines()
    analysis_lines = analysis_text.splitlines()
    fragments = _hidden_fragments(raw_text)
    fragments_by_line: dict[int, list[str]] = {}
    matches_by_line: dict[int, list[str]] = {}

    for start, _, fragment in fragments:
        line_number = raw_text.count("\n", 0, start) + 1
        fragments_by_line.setdefault(line_number, []).append(fragment)
        matches_by_line.setdefault(line_number, []).extend(_instruction_matches(fragment))

    for line_number, line in enumerate(raw_lines, start=1):
        matches_by_line.setdefault(line_number, []).extend(_instruction_matches(line))

    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    line_numbers = set(range(1, len(raw_lines) + 1)) | set(fragments_by_line) | set(matches_by_line)
    for line_number in sorted(line_numbers):
        raw_line = raw_lines[line_number - 1] if line_number <= len(raw_lines) else ""
        sanitized_line = analysis_lines[line_number - 1] if line_number <= len(analysis_lines) else ""
        _, invisible_count = _strip_invisible(raw_line)
        hidden = fragments_by_line.get(line_number, [])
        matches = list(dict.fromkeys(matches_by_line.get(line_number, [])))
        if invisible_count or hidden or matches:
            traces.append(
                {
                    "location": {"line": line_number},
                    "invisible_format_characters": invisible_count,
                    "hidden_fragment_count": len(hidden),
                    "instruction_matches": matches,
                    "removed_content": hidden,
                    "sanitized": sanitized_line,
                }
            )
        if matches:
            concealment = []
            if invisible_count:
                concealment.append(f"{invisible_count} Unicode format control(s)")
            if hidden:
                concealment.append(f"{len(hidden)} hidden HTML fragment(s)")
            detail = f"; concealed with {', '.join(concealment)}" if concealment else ""
            findings.append(
                _finding(
                    line_number,
                    f"reviewer-directed instruction detected ({matches[0]!r}){detail}",
                    source_name,
                )
            )

    return analysis_text, tuple(traces), tuple(findings)


def check_injection_scan(
    parsed_paper: dict[str, Any],
    *,
    precomputed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return localized findings, reusing canonical preparation when supplied."""

    if precomputed is not None:
        return {
            "check": "injection-scan",
            "traces": list(precomputed.get("traces", [])),
            "findings": list(precomputed.get("findings", [])),
        }

    # Compatibility path for callers that only have the historical parsed-paper
    # object. This scanner is the sole component allowed to reopen raw paper text.
    source = Path(str(parsed_paper["source_path"]))
    raw_text = source.read_text(encoding="utf-8")
    _, traces, findings = scan_and_sanitize(raw_text, source.name)
    return {
        "check": "injection-scan",
        "traces": list(traces),
        "findings": list(findings),
    }
