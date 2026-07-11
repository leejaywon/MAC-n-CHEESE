"""Deterministic scientific scaffolding — reviewer substance with no model call.

These emit Questions, never accusations. Per the false-positive rule an uncertain
critique becomes a question, and asking whether results are single-run or averaged
over seeds is always a fair ICML question. It self-suppresses when the paper
already discusses variance/seeds/multiple runs, so it never nags a rigorous paper.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# Any of these means the paper already addresses run-to-run variability.
VARIANCE_RE = re.compile(
    r"\b(?:variance|std(?:ev|\.)?|standard[- ]deviation|confidence[- ]interval|"
    r"error[- ]bars?|seeds?|stderr|averaged|deviation|±)\b"
    r"|\b\d+\s+(?:runs?|seeds?|trials?)\b"
    r"|\bmultiple\s+(?:runs?|seeds?|trials?)\b",
    re.I,
)


def rigor_questions(parsed_paper: dict[str, Any]) -> list[dict[str, Any]]:
    """One variance/seed question when a results table reports no variability."""

    tables = parsed_paper.get("tables") or []
    if not tables:
        return []
    source = Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8")
    if VARIANCE_RE.search(source):
        return []
    line = int(tables[0].get("line_start", 1))
    return [
        {
            "section": "Questions for the Authors",
            "stance": "question",
            "text": (
                "Are the reported results from a single run, or averaged over multiple seeds? "
                "No variance, standard deviation, confidence interval, or seed count is stated, "
                "so the reliability of the comparison cannot be assessed."
            ),
            "references": [f"paper:{line}"],
        }
    ]
