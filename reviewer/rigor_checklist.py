"""Deterministic ICML / NeurIPS rigor & reproducibility checklist critic.

Mirrors the items a real ICML reviewer — and the NeurIPS/ICML reproducibility and
limitations checklist — expects but a paper may omit: released code/data,
hyperparameters, compute/hardware, an explicit limitations discussion, and a
broader-impact / ethics statement. It emits ONE consolidated Question naming only
the items the paper does not evidence — never a Weakness (their absence is a
disclosure gap, not a proven defect) — and self-suppresses entirely when the paper
already covers everything, so a thorough submission is not nagged. Model-free.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# (reviewer-facing label, a regex whose match means the paper DOES address it).
CHECKLIST: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "whether code or data will be released",
        re.compile(
            r"\b(?:code|implementation|dataset|data|weights?|checkpoints?)\s+(?:is|are|will\s+be)"
            r"\s+(?:made\s+)?(?:available|released|public|open)"
            r"|github\.com|hugging\s*face|zenodo|\bwe\s+(?:release|open[- ]?source|provide|share|make\s+available)\b"
            r"|supplementary\s+material|reproducib",
            re.I,
        ),
    ),
    (
        "the training hyperparameters",
        re.compile(
            r"\bhyper[- ]?parameters?\b|learning\s+rate|batch\s+size|\boptimizer\b|weight\s+decay"
            r"|(?:number\s+of\s+)?epochs?\b|warm[- ]?up|\bAdam\b|\bSGD\b",
            re.I,
        ),
    ),
    (
        "the compute / hardware used",
        re.compile(
            r"\bGPUs?\b|\bTPUs?\b|\bA100\b|\bV100\b|\bH100\b|GPU[- ]hours?|compute\s+(?:budget|cost|resources)"
            r"|\bhardware\b|\bFLOPs?\b|\bcores?\b",
            re.I,
        ),
    ),
    (
        "an explicit limitations discussion",
        re.compile(r"\blimitations?\b|\bshortcomings?\b|\bfailure\s+cases?\b", re.I),
    ),
    (
        "a broader-impact / ethics statement",
        re.compile(
            r"broader\s+impact|societal\s+impact|ethic|potential\s+(?:harm|misuse|negative\s+impact)"
            r"|responsible\s+(?:use|ai)",
            re.I,
        ),
    ),
)


def rigor_checklist_missing(parsed_paper: dict[str, Any]) -> list[str]:
    """Return the checklist labels the paper does not appear to address."""

    source = Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8")
    return [label for label, pattern in CHECKLIST if not pattern.search(source)]


def rigor_checklist_questions(parsed_paper: dict[str, Any]) -> list[dict[str, Any]]:
    """One consolidated reproducibility/limitations Question, or nothing."""

    missing = rigor_checklist_missing(parsed_paper)
    if not missing:
        return []
    items = "; ".join(missing)
    return [
        {
            "section": "Questions for the Authors",
            "stance": "question",
            "text": (
                "For reproducibility and completeness (standard ICML/NeurIPS checklist items), the "
                f"paper does not appear to report {items}. Could the authors clarify these?"
            ),
            "references": ["paper"],
        }
    ]
