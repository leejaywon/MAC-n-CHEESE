"""Deterministic scientific positioning — the machine-checkable half of an
ICML reviewer's Originality/Significance judgment, with no model call.

An ICML review weighs a contribution by how it situates itself against prior art.
This module audits only the part of that judgment provable from the paper text:

- Positioning coverage: does the paper cite ANY prior work or carry a
  Related-Work / Background section?
- Novelty / SOTA overclaim: does the paper assert novelty or state-of-the-art
  superiority while situating that claim against NO prior work at all? An
  unsupported superiority claim is a provable positioning defect, so it becomes a
  Weakness and lowers Contribution.

Per the false-positive rule the module is self-suppressing: it says nothing about
a paper that makes no novelty/superiority claim (a scoped replication is allowed
to cite little), and it emits a Weakness only for the provable case (a
novelty/SOTA claim with zero positioning). A softer gap — a superiority claim
that names no comparator on a paper that IS otherwise positioned — becomes a
Question. The judgment-heavy half (is the novelty REAL against the SPECIFIC
literature) is retrieval-grounded and lives in the ``--best`` judgment layer
(:mod:`reviewer.novelty_positioning`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .citation_existence import (
    ARXIV_RE,
    BRACKET_ARXIV_RE,
    CORPUS_RE,
    DOI_RE,
    S2_URL_RE,
)


# A section title that constitutes explicit positioning against prior art.
RELATED_WORK_TITLE_RE = re.compile(
    r"\b(?:related\s+work|prior\s+work|previous\s+work|background|"
    r"literature\s+review|references|bibliography)\b",
    re.I,
)
# Numeric citation markers: [12], [3, 4], [5-7]. A dot is excluded so a bracketed
# arXiv id ("[2305.14567]") is owned by the arXiv patterns, not miscounted here.
NUMERIC_CITE_RE = re.compile(r"\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]")
# Author-year citations: "(Vaswani et al., 2017)", "(Smith & Jones, 2020)", and
# the narrative form "Vaswani et al. (2017)".
AUTHOR_YEAR_RE = re.compile(
    r"\([A-Z][A-Za-z.'’-]+"
    r"(?:\s+(?:et\s+al\.?|and|&|[A-Z][A-Za-z.'’-]+))*,?\s+(?:18|19|20)\d{2}[a-z]?\)"
    r"|[A-Z][A-Za-z.'’-]+\s+et\s+al\.?\s*\((?:18|19|20)\d{2}[a-z]?\)"
)

NOVELTY_RE = re.compile(
    r"\b(?:novel(?:ty)?|for\s+the\s+first\s+time|we\s+are\s+the\s+first|first\s+to\s+\w+|"
    r"to\s+the\s+best\s+of\s+our\s+knowledge|state[- ]of[- ]the[- ]art|\bSOTA\b|"
    r"new(?:\s+\w+){0,2}\s+(?:method|approach|framework|architecture|algorithm|technique|model))\b",
    re.I,
)
SUPERIORITY_RE = re.compile(
    r"\b(?:outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|beat(?:s|en|ing)?|"
    r"exceed(?:s|ed|ing)?|superior\s+to|better\s+than|best[- ]performing|"
    r"advanc(?:e|es|ing)\s+the\s+state)\b",
    re.I,
)
# Hypotheticals / plans: "aims to outperform", "could surpass" are not live claims.
NON_CLAIM_RE = re.compile(
    r"\b(?:aim(?:s|ed)?\s+to|could|expect(?:s|ed)?|future|goal|hope(?:s|d)?\s+to|"
    r"hypothes(?:is|ize[ds]?)|might|plan(?:s|ned)?\s+to|potential(?:ly)?|would)\b",
    re.I,
)
# Negation immediately before a novelty/superiority keyword: "does not outperform".
NEGATED_RE = re.compile(
    r"\b(?:not|no|never|without|do(?:es)?\s+not|did\s+not)\b[^.!?]{0,20}?"
    r"\b(?:novel|outperform|surpass|beat|better|superior|exceed|"
    r"state[- ]of[- ]the[- ]art|sota|first)\b",
    re.I,
)
# Naming an external comparator: a baseline, or "compared to/with <Name>", etc.
COMPARATOR_RE = re.compile(
    r"\bbaselines?\b|\b(?:compared\s+(?:to|with)|relative\s+to|versus|vs\.?|against)\s+"
    r"(?:the\s+)?[A-Za-z][\w.-]*",
    re.I,
)


def _source_lines(parsed_paper: dict[str, Any]) -> list[str]:
    return Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8").splitlines()


def _has_related_work_section(parsed_paper: dict[str, Any]) -> bool:
    return any(
        RELATED_WORK_TITLE_RE.search(str(section.get("title", "")))
        for section in parsed_paper.get("sections", [])
    )


def _citation_count(lines: list[str]) -> int:
    """Count citation markers of any common style; over-counting only makes the
    overclaim gate MORE lenient, so ambiguity is resolved in the paper's favour."""

    total = 0
    for line in lines:
        for pattern in (
            NUMERIC_CITE_RE,
            AUTHOR_YEAR_RE,
            ARXIV_RE,
            BRACKET_ARXIV_RE,
            DOI_RE,
            S2_URL_RE,
            CORPUS_RE,
        ):
            total += sum(1 for _ in pattern.finditer(line))
    return total


def _claim_sentences(lines: list[str]) -> Iterable[tuple[str, int]]:
    for line_number, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        # Skip blank lines, table rows, and headings: a claim should anchor to a
        # prose sentence, not a title that merely contains the word "novel".
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        for match in re.finditer(r"[^.!?]+[.!?]?", line):
            sentence = match.group(0).strip()
            if sentence:
                yield sentence, line_number


def check_positioning(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Audit related-work positioning and novelty/SOTA overclaims deterministically."""

    lines = _source_lines(parsed_paper)
    has_related_work = _has_related_work_section(parsed_paper)
    citation_count = _citation_count(lines)
    positioned = has_related_work or citation_count > 0

    claims: list[dict[str, Any]] = []
    for sentence, line_number in _claim_sentences(lines):
        if NON_CLAIM_RE.search(sentence) or NEGATED_RE.search(sentence):
            continue
        if NOVELTY_RE.search(sentence):
            kind = "novelty"
        elif SUPERIORITY_RE.search(sentence):
            kind = "superiority"
        else:
            continue
        claims.append(
            {"line": line_number, "kind": kind, "text": sentence, "comparator": bool(COMPARATOR_RE.search(sentence))}
        )

    findings: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    if claims and not positioned:
        # Provable positioning defect: the paper claims to advance the field but
        # situates that claim against nothing a reader could check.
        first = claims[0]
        findings.append(
            {
                "check": "positioning",
                "subtype": "novelty-overclaim",
                "severity": "high",
                "location": {"line": first["line"]},
                "expected": (
                    "the paper to situate its novelty/superiority claim against cited prior "
                    "work or a related-work section"
                ),
                "observed": (
                    f"a {first['kind']} claim is made with zero cited prior work and no "
                    f"related-work section: {first['text']}"
                ),
                "evidence_path": "paper",
            }
        )
    elif claims and positioned:
        # Positioned overall, but a specific superiority claim naming no comparator
        # is a fair Question, never an accusation.
        uncompared = [claim for claim in claims if claim["kind"] == "superiority" and not claim["comparator"]]
        if uncompared:
            target = uncompared[0]
            questions.append(
                {
                    "section": "Questions for the Authors",
                    "stance": "question",
                    "text": (
                        "Against which specific prior method is the superiority claim measured? "
                        "The claim names no external baseline at this location, so the strength of "
                        "the comparison cannot be assessed."
                    ),
                    "references": [f"paper:{target['line']}"],
                }
            )

    return {
        "check": "positioning",
        "traces": [
            {
                "has_related_work_section": has_related_work,
                "citation_count": citation_count,
                "positioned": positioned,
                "claims": claims,
            }
        ],
        "findings": findings,
        "questions": questions,
        "signals": {
            "has_related_work_section": has_related_work,
            "citation_count": citation_count,
            "positioned": positioned,
            "novelty_claim_count": len(claims),
        },
    }
