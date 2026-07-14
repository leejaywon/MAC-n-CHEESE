"""Judgment-first review: parsing, target-coherence gate, and integrity caps.

The review's spine is a strong model reading the FULL paper and writing an
ICML-shaped review in Markdown (see ``review_instructions.md``). This module
holds the thin mechanical frame around that spine:

- ``load_review_instructions`` — the packaged instructions handed to the model.
- ``parse_review`` — extract title, sections, and the six scores from the
  model's Markdown, reporting what is missing instead of guessing.
- ``check_review_target`` — the wrong-paper gate: a fluent review of the wrong
  paper is worthless, so the echoed title must match the input paper.
- ``apply_integrity_caps`` — the only score authority the mechanical layer
  keeps: a PROVEN integrity breach (contradicted claim / dishonest
  self-certification) caps Soundness and Overall at 2. Typographic findings and
  unverifiable-claim counts have no score authority here at all.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REVIEW_SECTIONS = (
    "Summary",
    "Strengths",
    "Weaknesses",
    "Questions for the Authors",
    "Scores",
    "Ethics and Limitations",
    "Comment",
)

SCORE_BOUNDS = {
    "Soundness": (1, 4),
    "Presentation": (1, 4),
    "Significance": (1, 4),
    "Originality": (1, 4),
    "Overall recommendation": (1, 6),
    "Confidence": (1, 5),
}

_TITLE_RE = re.compile(r"(?im)^#\s*Review(?:\s+of)?:?\s*(.+?)\s*$")
_WORD_RE = re.compile(r"[a-z0-9]+")
# Headings that are section labels by convention, never paper titles. When a
# paper's extraction yields one of these first, the title is UNKNOWN — the gate
# must go indeterminate rather than compare against a non-title.
_NON_TITLE_RE = re.compile(
    r"(?i)^\s*(?:\d+[.)]|(?:abstract|introduction|references|bibliography|"
    r"appendix|related work|acknowledg|contents)\b)"
)


def extract_paper_title(paper_markdown: str) -> str:
    """The paper's title from its first heading, or "" when indeterminable."""

    for line in paper_markdown.splitlines():
        if not line.lstrip().startswith("#"):
            continue
        title = re.sub(r"[*_`#]", "", line).strip()
        if _NON_TITLE_RE.match(title) or len(title) < 8:
            return ""
        return title
    return ""


def load_review_instructions() -> str:
    return (Path(__file__).resolve().parent / "review_instructions.md").read_text(
        encoding="utf-8"
    )


def _section_body(markdown: str, name: str) -> str:
    match = re.search(
        rf"(?ims)^#{{2,3}}\s*{re.escape(name)}\s*$(.*?)(?=^#{{1,3}}\s|\Z)", markdown
    )
    return match.group(1).strip() if match else ""


def parse_review(markdown: str) -> dict[str, Any]:
    """Extract title, sections, scores; list gaps rather than papering over them."""

    title_match = _TITLE_RE.search(markdown)
    title = title_match.group(1).strip().strip('"').strip() if title_match else ""
    sections = {name: _section_body(markdown, name) for name in REVIEW_SECTIONS}
    scores: dict[str, int] = {}
    for dimension, (low, high) in SCORE_BOUNDS.items():
        match = re.search(
            rf"(?im)^[-*]?\s*\*{{0,2}}{re.escape(dimension)}\*{{0,2}}\s*:\s*(\d+)\s*/\s*\d+",
            markdown,
        )
        if match and low <= int(match.group(1)) <= high:
            scores[dimension] = int(match.group(1))
    missing = [name for name, body in sections.items() if not body]
    missing += [f"score:{name}" for name in SCORE_BOUNDS if name not in scores]
    if not title:
        missing.insert(0, "title")
    return {"title": title, "sections": sections, "scores": scores, "missing": missing}


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def check_review_target(review_title: str, paper_title: str) -> dict[str, Any]:
    """Wrong-paper gate. Conservative in BOTH directions by design.

    Fails only on positive evidence of a mismatch: both titles present and
    sharing too few content tokens. When the paper's own title could not be
    extracted (some PDFs yield no title heading), the gate reports
    ``indeterminate`` and passes — an unverifiable title is not evidence of a
    wrong target, and this gate must never manufacture a false alarm.
    """

    review_tokens, paper_tokens = _tokens(review_title), _tokens(paper_title)
    if not review_tokens or not paper_tokens:
        return {"ok": True, "status": "indeterminate", "overlap": 0.0}
    overlap = len(review_tokens & paper_tokens) / min(len(review_tokens), len(paper_tokens))
    return {"ok": overlap >= 0.5, "status": "checked", "overlap": round(overlap, 3)}


def apply_integrity_caps(
    scores: dict[str, int], *, breach_count: int
) -> tuple[dict[str, int], list[str]]:
    """Cap Soundness/Overall at 2 on a PROVEN breach; otherwise change nothing."""

    if breach_count <= 0:
        return dict(scores), []
    capped = dict(scores)
    notes = []
    for dimension in ("Soundness", "Overall recommendation"):
        if capped.get(dimension, 0) > 2:
            capped[dimension] = 2
            notes.append(
                f"{dimension} capped at 2/{SCORE_BOUNDS[dimension][1]}: "
                f"{breach_count} proven integrity breach(es)."
            )
    return capped, notes
