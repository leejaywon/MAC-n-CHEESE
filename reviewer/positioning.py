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
# Numeric citation markers: [12], [3, 4], [5-7], and 1000+ ref lists ([1024]). A
# dot is excluded so a bracketed arXiv id ("[2305.14567]") is owned by the arXiv
# patterns. Over-counting only makes a paper look MORE positioned, which is the
# safe direction, so recognition is deliberately generous.
NUMERIC_CITE_RE = re.compile(r"\[\d{1,4}(?:\s*[,–-]\s*\d{1,4})*\]")
# Author-year citations in parentheses OR square brackets (the ACL Anthology /
# ICLR / NeurIPS standard), the narrative form "Vaswani et al. (2017)", and
# natbib keys ("[Vaswani2017]", "[VaswaniEtAl2017]"). Recognizing more citation
# styles prevents a false "unpositioned" verdict on a paper that DOES cite work.
AUTHOR_YEAR_RE = re.compile(
    r"[\(\[][A-Z][A-Za-z.'’-]+"
    r"(?:\s+(?:et\s+al\.?|and|&|[A-Z][A-Za-z.'’-]+))*,?\s+(?:18|19|20)\d{2}[a-z]?[\)\]]"
    r"|[A-Z][A-Za-z.'’-]+\s+et\s+al\.?\s*\((?:18|19|20)\d{2}[a-z]?\)"
    r"|\[[A-Z][A-Za-z]+(?:etal)?\d{2,4}[a-z]?\]"
)

# A novelty / priority / state-of-the-art CLAIM must be an explicit claim about
# the work's OWN contribution — not an incidental "novel"/"new" as in the task
# names "novel view synthesis" or "novel class discovery". Requires a first-person
# or contribution frame.
NOVELTY_RE = re.compile(
    r"\b(?:"
    r"we\s+(?:are|were)\s+the\s+first\b"
    r"|(?:is|are)\s+the\s+first\s+(?:method|approach|work|paper|model|system|framework|algorithm|technique)\s+to\b"
    r"|for\s+the\s+first\s+time\b"
    r"|to\s+(?:the\s+)?best\s+of\s+our\s+knowledge\b"
    r"|(?:new\s+)?state[-\s]of[-\s]the[-\s]art\b|\bSOTA\b|best[-\s]performing\b|advanc(?:e|es|ing)\s+the\s+state\b"
    r"|(?:we\s+(?:propose|present|introduce|develop|design|devise|offer)|our)\s+(?:[a-z]+[\s,]+){0,4}?(?:novel|new)\s+(?:method|approach|framework|architecture|algorithm|technique|model|network|module|paradigm|formulation|objective|loss|scheme)"
    r"|(?:a|the|this)\s+(?:novel|new)\s+(?:method|approach|framework|architecture|algorithm|technique|model|network|module|paradigm|formulation)\s+(?:that|which|for|to|is|we|,)"
    r")",
    re.I,
)
# A superiority CLAIM: a superiority verb pointed at a comparison TARGET
# (baselines / prior / other methods), so ordinary uses of "beats" (music) or
# "exceeds the memory budget" do NOT register as claims.
SUPERIORITY_RE = re.compile(
    r"\b(?:outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|beat(?:s|en|ing)?|"
    r"exceed(?:s|ed|ing)?|superior|better)\b"
    r"[^.!?]{0,48}?\b(?:baselines?|state[-\s]of[-\s]the[-\s]art|sota|prior|previous|existing|"
    r"competing|other\s+(?:methods?|models?|systems?|approaches|networks?)|"
    r"all\s+(?:[a-z]+\s+){0,3}?(?:methods?|models?|systems?|approaches|baselines?|networks?))\b",
    re.I,
)
# A looser superiority claim with a first-person subject ("our approach
# outperforms significantly") — used only for the softer Question path, never to
# trigger a Weakness.
SUPERIORITY_LOOSE_RE = re.compile(
    r"\b(?:we|our\s+(?:method|approach|model|system|framework|technique|algorithm|results?|work))\b"
    r"[^.!?]{0,32}?\b(?:outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|"
    r"(?:is|are)\s+superior\s+to|(?:is|are|performs?|do(?:es)?)\s+better\s+than)\b",
    re.I,
)
# Negation directly on a claim word ("does not outperform", "not novel") within
# ~2 words, so "no fewer than three novel modules" is NOT read as a negation.
NEGATED_RE = re.compile(
    r"\b(?:not|never|n't|no\s+longer|do(?:es)?\s+not|did\s+not)\s+(?:[a-z]+\s+){0,2}?"
    r"\b(?:novel|state[-\s]of[-\s]the[-\s]art|sota|outperform\w*|surpass\w*|beat\w*|"
    r"exceed\w*|superior|better\s+than|first\s+to)\b",
    re.I,
)
# A future/hypothetical claim ("we plan to outperform", "aim to surpass"): the
# modal must directly govern a CLAIM verb. So "we hope to extend it further"
# (future work unrelated to the claim) and "we would like to note … SOTA" are NOT
# suppressed, while "we plan to outperform the baseline" is.
HYPOTHETICAL_RE = re.compile(
    r"\b(?:plan(?:s|ned)?|aim(?:s|ed)?|hope(?:s|d)?|intend(?:s|ed)?|expect(?:s|ed)?|"
    r"seek(?:s)?|going|will|would|could|might|may|shall)\s+to\s+(?:[a-z]+\s+){0,2}?"
    r"\b(?:outperform\w*|surpass\w*|beat\w*|exceed\w*|be\s+(?:novel|superior|the\s+first)|"
    r"achiev\w*\s+state|propose|present|introduce)\b",
    re.I,
)
# Naming an external comparator (used only for the softer Question path).
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

    weakness_claims: list[dict[str, Any]] = []  # novelty / SOTA / superiority-with-target
    question_claims: list[dict[str, Any]] = []  # looser first-person superiority, no comparator
    for sentence, line_number in _claim_sentences(lines):
        # A negated ("does not outperform") or hypothetical ("plan to outperform")
        # claim is not a live claim.
        if NEGATED_RE.search(sentence) or HYPOTHETICAL_RE.search(sentence):
            continue
        novelty = NOVELTY_RE.search(sentence)
        superiority = SUPERIORITY_RE.search(sentence)
        loose = SUPERIORITY_LOOSE_RE.search(sentence)
        if not (novelty or superiority or loose):
            continue
        entry = {"line": line_number, "kind": "novelty" if novelty else "superiority", "text": sentence}
        if novelty or superiority:
            weakness_claims.append(entry)
        elif not COMPARATOR_RE.search(sentence):
            question_claims.append(entry)
    all_claims = weakness_claims + question_claims

    findings: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    if weakness_claims and not positioned:
        # Provable positioning defect: the paper makes a novelty/superiority claim
        # but situates it against nothing a reader could check.
        first = weakness_claims[0]
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
    elif question_claims:
        # A superiority claim naming no comparator is a fair Question, never an
        # accusation — whether or not the paper is otherwise positioned.
        target = question_claims[0]
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
                "claims": all_claims,
            }
        ],
        "findings": findings,
        "questions": questions,
        "signals": {
            "has_related_work_section": has_related_work,
            "citation_count": citation_count,
            "positioned": positioned,
            "novelty_claim_count": len(all_claims),
        },
    }
