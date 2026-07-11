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

    without_comments = HTML_COMMENT_RE.sub("", text)

    def remove_hidden(match: re.Match[str]) -> str:
        return "" if HIDDEN_STYLE_RE.search(match.group("attrs")) else match.group(0)

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


def _finding(line: int, observed: str, source: str) -> dict[str, Any]:
    return {
        "check": "injection-scan",
        "severity": "high",
        "location": {"line": line},
        "expected": "paper content that does not direct or manipulate the reviewer",
        "observed": observed,
        "evidence_path": source,
    }


def check_injection_scan(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Return localized injection findings and sanitation traces."""

    source = Path(str(parsed_paper["source_path"]))
    text = source.read_text(encoding="utf-8")
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        _, invisible_count = _strip_invisible(line)
        hidden_fragments = [match.group(0) for match in HTML_COMMENT_RE.finditer(line)]
        hidden_fragments.extend(
            match.group(0)
            for match in HIDDEN_ELEMENT_RE.finditer(line)
            if HIDDEN_STYLE_RE.search(match.group("attrs"))
        )
        matches = _instruction_matches(line)
        if invisible_count or hidden_fragments or matches:
            traces.append(
                {
                    "location": {"line": line_number},
                    "invisible_format_characters": invisible_count,
                    "hidden_fragment_count": len(hidden_fragments),
                    "instruction_matches": matches,
                    "sanitized": sanitize_for_analysis(line),
                }
            )
        if matches:
            concealment = []
            if invisible_count:
                concealment.append(f"{invisible_count} Unicode format control(s)")
            if hidden_fragments:
                concealment.append(f"{len(hidden_fragments)} hidden HTML fragment(s)")
            detail = f"; concealed with {', '.join(concealment)}" if concealment else ""
            findings.append(
                _finding(
                    line_number,
                    f"reviewer-directed instruction detected ({matches[0]!r}){detail}",
                    source.name,
                )
            )

    return {"check": "injection-scan", "traces": traces, "findings": findings}
