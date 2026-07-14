"""Deterministic manuscript-integrity checks: broken cross-references and
compilation/template artifacts.

These are the paper-level defects a careful reviewer flags on sight — a dangling
``Figure ??``, an ``\\ref`` that never resolved, a failed ``[?]`` citation, an
unfilled ``TODO``, or a LaTeX ``AUTHORERR`` left in the PDF. They run on the
extracted Markdown as part of the S3 battery; like every S3 check they only add
findings and never touch the frozen audit identity.
"""

from __future__ import annotations

import re
from typing import Any

from .parser import paper_text

# Broken cross-references.
_BROKEN_FLOAT_REF = re.compile(
    r"(?i)\b(?:figure|fig|table|tbl|section|sec|equation|eq|algorithm|alg|appendix|listing)\.?\s*\?\?"
)
_UNRENDERED_REF = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref)\s*\{[^}]*\}")
_BROKEN_CITE = re.compile(r"\[\s*\?\s*\]")  # failed \cite renders as [?]
_UNDEFINED_REF = re.compile(r"(?i)\bundefined (?:reference|control sequence|citation)\b")
# Eaten leading backslash: pymupdf drops the "\r" of "\ref{tab:main}", leaving
# "eftab:main" — a cross-reference that never resolved to a numbered float and is
# invisible to the patterns above (no "??" or "\ref{").
_GARBLED_REF = re.compile(r"\bef[a-z]{2,}:[a-z]+\b")

# Compilation / template artifacts. Marker words match UPPERCASE only: leftover
# build markers are conventionally written TODO/FIXME/TBD/PLACEHOLDER, while the
# same words in lowercase running prose are ordinary content words — a paper
# about placeholders or todo-list agents must not be flagged as unfinished.
_ARTIFACT = re.compile(
    r"(?:"
    r"\bAUTHORERR\b"
    r"|\\author\s*\{\s*\}"
    r"|(?<![\w-])(?:TODO|FIXME|TBD|PLACEHOLDER)(?![\w-])"
    r"|(?i:\[citation needed\])"
    r"|(?i:\blorem ipsum\b)"
    r")",
)


def check_cross_references(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Flag broken cross-references: dangling ``??``, unrendered ``\\ref``, ``[?]``."""

    findings: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for line_number, line in enumerate(paper_text(parsed_paper).splitlines(), start=1):
        for pattern, kind in (
            (_BROKEN_FLOAT_REF, "float reference"),
            (_UNDEFINED_REF, "undefined reference"),
            (_UNRENDERED_REF, "unrendered LaTeX reference"),
            (_BROKEN_CITE, "failed citation"),
            (_GARBLED_REF, "garbled cross-reference"),
        ):
            match = pattern.search(line)
            if not match:
                continue
            snippet = " ".join(match.group(0).split())
            traces.append({"line": line_number, "kind": kind, "text": snippet})
            findings.append(
                {
                    "check": "cross-references",
                    "severity": "medium",
                    "location": {"line": line_number},
                    "expected": "every cross-reference resolves to a numbered float, section, or citation",
                    "observed": f"broken {kind}: {snippet!r}",
                    "evidence_path": f"paper line {line_number}",
                }
            )
            break  # one finding per line is enough
    return {"check": "cross-references", "traces": traces, "findings": findings}


def check_manuscript_artifacts(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Flag compilation/template artifacts: AUTHORERR, unfilled placeholders."""

    findings: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for line_number, line in enumerate(paper_text(parsed_paper).splitlines(), start=1):
        match = _ARTIFACT.search(line)
        if not match:
            continue
        snippet = " ".join(match.group(0).split())
        traces.append({"line": line_number, "text": snippet})
        findings.append(
            {
                "check": "manuscript-artifacts",
                "severity": "medium",
                "location": {"line": line_number},
                "expected": "a finished manuscript with no unfilled placeholders or build errors",
                "observed": f"leftover artifact: {snippet!r}",
                "evidence_path": f"paper line {line_number}",
            }
        )
    return {"check": "manuscript-artifacts", "traces": traces, "findings": findings}
