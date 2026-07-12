"""Deterministic S2 claim extraction and S4 evidence-bound verdicts.

Claim extraction is intentionally syntax-based: paper text is data, and no
paper-authored instruction is ever executed.  Verdicts only move to
``supported`` or ``contradicted`` when an S3 trace or finding proves that
label; everything else remains ``unverifiable``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .injection_scan import sanitize_for_analysis


ARITHMETIC_RE = re.compile(
    r"\b(?:delta|difference|relative|percentage|percent)\s+(?:improvement|change)|"
    r"\b(?:absolute\s+)?delta\b",
    re.I,
)
# A result verb in ANY tense — abstracts routinely use the present ("achieves",
# "obtains", "reports"), so a past-tense-only pattern mis-types headline numeric
# results (e.g. "achieves 80.5% GLUE") as generic prose and never questions them.
RESULT_RE = re.compile(
    r"\b(?:achiev(?:e|es|ed)|attain(?:s|ed)?|obtain(?:s|ed)?|reach(?:es|ed)?|"
    r"record(?:s|ed)?|report(?:s|ed)?|scor(?:e|es|ed)|result(?:s|ed)?|yield(?:s|ed)?|"
    r"establish(?:es|ed)?|improv(?:e|es|ed|ement)|reduc(?:e|es|ed|tion)|"
    r"outperform(?:s|ed)?|surpass(?:es|ed)?|measured|observed|mean|median|average|"
    r"comparison|experiment|run)\b",
    re.I,
)
# A numeric SOTA claim ("state-of-the-art FID of 3.17") is a result regardless of
# its verb; used only when the sentence also carries a number.
SOTA_RESULT_RE = re.compile(r"state[-\s]of[-\s]the[-\s]art|\bSOTA\b", re.I)
# Reference-list / bibliography sections hold citation entries, not research
# claims — extracting each "[arXiv:1234.5678](…)" line as a claim is boilerplate
# noise that also inflates the Confidence denominator.
REFERENCE_SECTION_RE = re.compile(r"\b(?:references|bibliography|works?\s+cited)\b", re.I)
# A sentence that is wholly a single citation link ("[arXiv:1312.3005](…)") is a
# reference entry, not a research claim, even when it leaks outside a References
# section.
CITATION_ONLY_RE = re.compile(r"^\[[^\]]+\]\([^)]+\)[.,;]?$")
CITATION_RE = re.compile(r"(?:\[[^\]]+\]|\b(?:arXiv:)?\d{4}\.\d{4,5}(?:v\d+)?\b)")
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s*\[[ xX]\]\s*")
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")


def _section_for_line(parsed_paper: dict[str, Any], line: int) -> dict[str, Any] | None:
    candidates = [
        section
        for section in parsed_paper.get("sections", [])
        if section.get("line_start", 0) <= line <= section.get("line_end", -1)
    ]
    return max(candidates, key=lambda section: section.get("level", 0), default=None)


def _numbers_on_line(parsed_paper: dict[str, Any], line: int) -> list[dict[str, Any]]:
    return [
        token
        for token in parsed_paper.get("numeric_tokens", [])
        if token.get("location", {}).get("line") == line
    ]


def _claim_type(
    text: str, section_title: str, *, table: bool, checkbox: bool, has_number: bool = False
) -> str:
    lowered = text.lower()
    title = section_title.lower()
    if table:
        return "result"
    if checkbox or "self-review" in title or "self review" in title:
        return "self_review"
    if "falsifiable hypothesis" in lowered or "hypothesis" in title:
        return "hypothesis"
    if ARITHMETIC_RE.search(text):
        return "arithmetic"
    if "limitation" in title or "limitation" in lowered:
        return "limitation"
    if "result" in title or RESULT_RE.search(text) or (has_number and SOTA_RESULT_RE.search(text)):
        return "result"
    if "baseline" in lowered or "method" in title or "experiment" in title:
        return "method"
    return "general"


def _sentence_spans(line: str) -> list[tuple[str, int, int]]:
    """Split prose conservatively while retaining one-based source columns."""

    content_start = len(line) - len(line.lstrip())
    content = line[content_start:]
    prefix = LIST_PREFIX_RE.match(content)
    if prefix:
        content_start += prefix.end()
        content = content[prefix.end():]
    spans: list[tuple[str, int, int]] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?:[.!?](?=\s|$)|$)", content):
        text = match.group(0).strip()
        if text:
            start = content_start + match.start() + 1
            spans.append((text, start, content_start + match.end()))
    return spans


def extract_claims(parsed_paper: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract declarative prose and result-table rows with stable locations."""

    source = Path(str(parsed_paper["source_path"]))
    # Hidden paper-authored instructions are DATA for the injection audit, not
    # claims for S2 or commands for any later stage.
    lines = sanitize_for_analysis(source.read_text(encoding="utf-8")).splitlines()
    table_by_line: dict[int, dict[str, Any]] = {}
    table_lines: set[int] = set()
    for table in parsed_paper.get("tables", []):
        table_lines.update(range(int(table["line_start"]), int(table["line_end"]) + 1))
        for row in table.get("rows", []):
            table_by_line[int(row["line"])] = {"table": table, "row": row}

    raw_claims: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or HEADING_RE.match(line) or TABLE_DELIMITER_RE.match(line):
            continue
        section = _section_for_line(parsed_paper, line_number)
        section_id = section.get("id") if section else None
        section_title = str(section.get("title", "")) if section else ""
        # Reference-list entries are citations, not claims.
        if REFERENCE_SECTION_RE.search(section_title):
            continue
        table_entry = table_by_line.get(line_number)
        if table_entry:
            row = table_entry["row"]
            cells = [str(cell).strip() for cell in row.get("cells", [])]
            text = " | ".join(cells)
            numbers = _numbers_on_line(parsed_paper, line_number)
            # Header-only or nonnumeric rows state schema, not research claims.
            if not numbers:
                continue
            raw_claims.append(
                {
                    "text": text,
                    "type": _claim_type(text, section_title, table=True, checkbox=False, has_number=True),
                    "numbers": [token["id"] for token in numbers],
                    "refs": CITATION_RE.findall(text),
                    "location": {
                        "line": line_number,
                        "column_start": 1,
                        "column_end": len(line),
                        "section_id": section_id,
                        "table_id": table_entry["table"]["id"],
                    },
                }
            )
            continue

        # The parser exposes table headers separately from result rows. They
        # define schema and must not become free-standing prose claims.
        if line_number in table_lines:
            continue

        checkbox = bool(CHECKBOX_RE.match(line))
        for text, column_start, column_end in _sentence_spans(line):
            if CITATION_ONLY_RE.match(text.strip()):
                continue  # a bare reference link is not a claim
            numbers = [
                token
                for token in _numbers_on_line(parsed_paper, line_number)
                if column_start <= token["location"]["column_start"] <= column_end
            ]
            raw_claims.append(
                {
                    "text": re.sub(r"^\[[ xX]\]\s*", "", text).strip(),
                    "type": _claim_type(text, section_title, table=False, checkbox=checkbox, has_number=bool(numbers)),
                    "numbers": [token["id"] for token in numbers],
                    "refs": CITATION_RE.findall(text),
                    "location": {
                        "line": line_number,
                        "column_start": column_start,
                        "column_end": column_end,
                        "section_id": section_id,
                        "table_id": None,
                    },
                }
            )

    for index, claim in enumerate(raw_claims, start=1):
        claim["id"] = f"claim-{index:03d}"
    return raw_claims


def _location_line(value: object) -> int | None:
    if isinstance(value, dict) and isinstance(value.get("line"), int):
        return value["line"]
    if isinstance(value, str) and value.rsplit(":", 1)[-1].isdigit():
        return int(value.rsplit(":", 1)[-1])
    return None


def _finding_records(mechanical_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        mechanical_findings,
        key=lambda finding: (
            _location_line(finding.get("location")) or 10**9,
            str(finding.get("check", "")),
            str(finding.get("observed", "")),
        ),
    )
    return [{"id": f"finding-{index:03d}", **finding} for index, finding in enumerate(ordered, 1)]


def label_verdicts(
    claims: list[dict[str, Any]],
    mechanical_checks: dict[str, dict[str, Any]],
    mechanical_findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Label claims only from deterministic S3 support or contradiction."""

    findings = _finding_records(mechanical_findings)
    ledger_by_number = {
        trace["number_id"]: trace
        for trace in mechanical_checks.get("ledger-trace", {}).get("traces", [])
    }
    arithmetic_by_line: dict[int, list[dict[str, Any]]] = {}
    for trace in mechanical_checks.get("arithmetic", {}).get("traces", []):
        line = _location_line(trace.get("location"))
        if line is not None:
            arithmetic_by_line.setdefault(line, []).append(trace)

    verdicts: list[dict[str, Any]] = []
    for claim in claims:
        line = int(claim["location"]["line"])
        relevant_findings = [
            finding for finding in findings if _location_line(finding.get("location")) == line
        ]
        evidence: list[str] = []
        if relevant_findings:
            label = "contradicted"
            evidence = [finding["id"] for finding in relevant_findings]
            reason = "A deterministic mechanical finding contradicts this source passage."
        else:
            support: list[str] = []
            ledger_traces = [
                ledger_by_number[number_id]
                for number_id in claim.get("numbers", [])
                if number_id in ledger_by_number
            ]
            if ledger_traces and all(trace.get("matched") for trace in ledger_traces):
                for trace in ledger_traces:
                    for item in trace.get("evidence", []):
                        support.append(
                            f"{item['path']}:{item['line']}#{item['field']} ({trace['number_id']})"
                        )
            arithmetic_traces = arithmetic_by_line.get(line, [])
            if claim.get("type") == "arithmetic" and arithmetic_traces and all(
                trace.get("matched") for trace in arithmetic_traces
            ):
                support.extend(
                    f"S3 arithmetic {trace['formula']} at paper:{line}" for trace in arithmetic_traces
                )

            # Hypotheses, methods, limitations, and checklist assertions are
            # not converted into observed facts merely because they share a
            # line with a number. S3 support is reserved for result claims.
            evidence_bearing = claim.get("type") in {"result", "arithmetic"}
            if evidence_bearing and support:
                label = "supported"
                evidence = list(dict.fromkeys(support))
                reason = "Every S3 evidence-bearing value in this claim has a matching trace."
            else:
                label = "unverifiable"
                evidence = [f"paper:{line}"]
                reason = "No implemented mechanical check proves or disproves this claim."

        verdicts.append(
            {
                "claim_id": claim["id"],
                "label": label,
                "evidence": evidence,
                "reason": reason,
            }
        )
    return verdicts, findings
