"""Audit a Self-Review checklist against the actual findings.

An event-format submission carries a Self-Review checklist whose author ticks
``[x]`` items such as "Every number traces to saved evidence". A checked box is a
claim by the authors about their own paper. When the deterministic checks already
found a contradicting issue in the mapped family, that self-certification is
demonstrably dishonest — a sharp, evidence-bound critique unique to this event.

This is a DERIVED integrity critique, not a primary flaw detection: the pipeline
renders it in Weaknesses but deliberately keeps it out of the detection/false-
positive eval accounting so the backpressure metric stays about primary flaws.
"""

from __future__ import annotations

import re
from typing import Any

from .parser import paper_text


# The event-format template uses a TRAILING checkbox ("- label: [ ]") while
# the event's example papers use a LEADING one ("- [x] label"). Support both so
# the audit works on real submissions, not only the local eval fixtures.
LEADING_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(?P<label>.+?)\s*$")
TRAILING_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+(?P<label>.+?)\s*:?\s*\[([ xX])\]\s*$")
SELF_REVIEW_TITLE_RE = re.compile(r"self[- ]review", re.I)


def _parse_checkbox(line: str) -> tuple[bool, str] | None:
    """Return (checked, label) for a leading- or trailing-checkbox list item."""

    match = LEADING_CHECKBOX_RE.match(line)
    if match:
        return match.group(1).lower() == "x", match.group("label").strip().rstrip(":").strip()
    match = TRAILING_CHECKBOX_RE.match(line)
    if match:
        return match.group(2).lower() == "x", match.group("label").strip().rstrip(":").strip()
    return None

# Map a checklist item (by keyword) to the deterministic check families that can
# contradict it. A checked item whose family already produced a finding is a
# dishonest self-certification.
ITEM_FAMILY_PATTERNS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\b(?:number|trace|traces|evidence|ledger)\b", re.I), frozenset({"ledger-trace"})),
    (re.compile(r"\bbaselines?\b|\bfair\b|\bmetric\b", re.I), frozenset({"baseline-fairness"})),
    (re.compile(r"\bclaims?\b.*\bresults?\b|\bresults?\b.*\bclaims?\b|\bmatch\b", re.I),
     frozenset({"internal-consistency", "arithmetic"})),
    (re.compile(r"\bnegative\b|\binconclusive\b", re.I), frozenset({"negative-evidence"})),
    (re.compile(r"\bcitations?\b", re.I), frozenset({"citation-existence"})),
    (re.compile(r"\bpage count\b|\bpages?\b", re.I), frozenset({"template-compliance"})),
)


def _self_review_items(parsed_paper: dict[str, Any]) -> list[tuple[int, str, bool]]:
    lines = paper_text(parsed_paper).splitlines()
    sections = [
        section
        for section in parsed_paper.get("sections", [])
        if SELF_REVIEW_TITLE_RE.search(str(section.get("title", "")))
    ]
    items: list[tuple[int, str, bool]] = []
    for line_number, line in enumerate(lines, start=1):
        if not any(
            section.get("line_start", 0) <= line_number <= section.get("line_end", -1)
            for section in sections
        ):
            continue
        parsed = _parse_checkbox(line)
        if parsed is not None:
            checked, label = parsed
            items.append((line_number, label, checked))
    return items


def check_self_review_consistency(
    parsed_paper: dict[str, Any], mechanical_findings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Flag checked self-review items contradicted by an existing S3 finding."""

    findings_by_family: dict[str, list[dict[str, Any]]] = {}
    for finding in mechanical_findings:
        findings_by_family.setdefault(str(finding.get("check")), []).append(finding)

    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for line_number, label, checked in _self_review_items(parsed_paper):
        families: set[str] = set()
        for pattern, mapped in ITEM_FAMILY_PATTERNS:
            if pattern.search(label):
                families |= mapped
        contradicting = {family for family in families if findings_by_family.get(family)}
        traces.append(
            {
                "line": line_number,
                "label": label,
                "checked": checked,
                "families": sorted(families),
                "contradicting_families": sorted(contradicting),
            }
        )
        if checked and contradicting:
            summary = ", ".join(
                f"{family} ({len(findings_by_family[family])})" for family in sorted(contradicting)
            )
            findings.append(
                {
                    "check": "self-review-audit",
                    "severity": "high",
                    "location": {"line": line_number},
                    "expected": f"the self-certified item to hold: '{label}'",
                    "observed": f"authors checked [x] '{label}', but {summary} already contradict it",
                    "evidence_path": "paper Self-Review checklist vs. S3 findings",
                }
            )
    return {"check": "self-review-audit", "traces": traces, "findings": findings}
