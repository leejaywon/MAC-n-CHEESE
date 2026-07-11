"""Deterministic checks for the Track 1 Markdown submission contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CORE_SECTION_GROUPS = {
    "Research Spec": (r"\bresearch spec\b",),
    "Short Paper": (r"\bshort paper\b",),
    "Abstract": (r"\babstract\b",),
    "Experiments and Results": (r"\bexperiment(?:s)?\b.*\bresult(?:s)?\b", r"\bresults?\b"),
    "Limitations and Conclusion": (r"\blimitations?\b", r"\bconclusion\b"),
    "Self-Review": (r"\bself[- ]review\b",),
}
WRAPPER_SECTION_GROUPS = {
    "Agent Workflow": (r"\bagent workflow\b",),
}
OFFICIAL_MARKER_RE = re.compile(r"Track\s*1\s*[—:-]\s*AI Scientist Submission", re.I)
PAGE_COUNT_RE = re.compile(r"(?:page count|pages?)\s*[:=]\s*(\d+)\b", re.I)
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([^\]])\]\s+(.+)$")


def _source(parsed_paper: dict[str, Any]) -> tuple[str, list[str]]:
    text = Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8")
    return text, text.splitlines()


def _has_heading(titles: list[str], patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, title, re.I) for title in titles for pattern in patterns)


def _finding(location: dict[str, int], expected: str, observed: str, source: str) -> dict[str, Any]:
    return {
        "check": "template-compliance",
        "severity": "error",
        "location": location,
        "expected": expected,
        "observed": observed,
        "evidence_path": source,
    }


def check_template_compliance(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Check required headings, explicit page count, and checkbox syntax.

    Markdown has no intrinsic rendered page count.  We therefore enforce the
    2--4 page rule only from an explicit declaration or form-feed boundaries;
    otherwise the trace records ``unknown`` instead of inventing a layout.
    """

    text, lines = _source(parsed_paper)
    source_path = str(parsed_paper["source_path"])
    titles = [str(section.get("title", "")) for section in parsed_paper.get("sections", [])]
    official_wrapper = bool(OFFICIAL_MARKER_RE.search(text))
    groups = {**CORE_SECTION_GROUPS, **(WRAPPER_SECTION_GROUPS if official_wrapper else {})}
    sections = {name: _has_heading(titles, patterns) for name, patterns in groups.items()}
    findings: list[dict[str, Any]] = []
    first_line = {"line": 1}
    for name, present in sections.items():
        if not present:
            findings.append(
                _finding(first_line, f"a '{name}' section", f"required section '{name}' is absent", source_path)
            )

    declarations = [
        (line_number, int(match.group(1)))
        for line_number, line in enumerate(lines, start=1)
        if (match := PAGE_COUNT_RE.search(line))
    ]
    page_count: int | None = declarations[0][1] if declarations else None
    page_location = declarations[0][0] if declarations else 1
    page_source = "explicit declaration" if declarations else "unknown"
    if page_count is None and "\f" in text:
        page_count = text.count("\f") + 1
        page_source = "form-feed boundaries"
    if len({count for _, count in declarations}) > 1:
        findings.append(
            _finding(
                {"line": declarations[1][0]},
                "one consistent explicit page count",
                f"conflicting page counts were declared: {[count for _, count in declarations]}",
                source_path,
            )
        )
    elif page_count is not None and not 2 <= page_count <= 4:
        findings.append(
            _finding(
                {"line": page_location},
                "a 2-4 page short paper",
                f"the declared/delimited paper length is {page_count} page(s)",
                source_path,
            )
        )

    self_review_sections = {
        section["id"]
        for section in parsed_paper.get("sections", [])
        if re.search(r"\bself[- ]review\b", str(section.get("title", "")), re.I)
    }
    checkboxes: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        section_ids = {
            token.get("location", {}).get("section_id")
            for token in parsed_paper.get("numeric_tokens", [])
            if token.get("location", {}).get("line") == line_number
        }
        in_self_review = bool(section_ids & self_review_sections) or any(
            section["id"] in self_review_sections
            and section["line_start"] <= line_number <= section["line_end"]
            for section in parsed_paper.get("sections", [])
        )
        if not in_self_review:
            continue
        match = CHECKBOX_RE.match(line)
        if not match:
            continue
        marker, label = match.groups()
        valid = marker in {" ", "x", "X"}
        checkboxes.append({"line": line_number, "marker": marker, "label": label, "valid": valid})
        if not valid:
            findings.append(
                _finding(
                    {"line": line_number},
                    "a self-review checkbox marker of space or x",
                    f"invalid checkbox marker '[{marker}]'",
                    source_path,
                )
            )

    traces = [
        {
            "kind": "required-sections",
            "official_wrapper": official_wrapper,
            "sections": sections,
            "matched": all(sections.values()),
        },
        {
            "kind": "page-count",
            "page_count": page_count,
            "source": page_source,
            "matched": None if page_count is None else 2 <= page_count <= 4,
        },
        {"kind": "self-review", "checkboxes": checkboxes, "matched": all(item["valid"] for item in checkboxes)},
    ]
    return {"check": "template-compliance", "traces": traces, "findings": findings}
