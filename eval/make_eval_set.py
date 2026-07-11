#!/usr/bin/env python3
"""Build the deterministic M3 evaluation set from claim-anchored cases.

Each corrupted paper changes exactly one falsifiable result claim.  The answer
key records the changed source line, not just an error taxonomy, so eval.py can
require both identification and localization.  Evidence is generated from the
unchanged observations and is never rewritten to agree with a corruption.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PAPERS_DIR = ROOT / "papers"
EVIDENCE_DIR = ROOT / "evidence"
ANSWER_KEY = ROOT / "answer_key.json"


@dataclass(frozen=True)
class Case:
    name: str
    metric: str
    baseline: str
    candidate: str
    claim: str
    replacement: str | None = None
    expected_checks: tuple[str, ...] = ()
    description: str = ""


def _paper(case: Case) -> tuple[str, dict[str, object] | None]:
    lower_is_better = case.metric in {"val_bpb", "loss", "perplexity"}
    direction = "lowers" if lower_is_better else "raises"
    rows = (
        f"| baseline | keep | {case.baseline} |\n"
        f"| candidate-1 | keep | {case.candidate} |"
    )
    text = f"""# Frozen Track 1 Paper: {case.name}

## Research Spec

- Falsifiable hypothesis: the candidate {direction} `{case.metric}`.
- Baseline: unchanged recipe with the same metric and seed 42.

## Short Paper

### Abstract

We compare one candidate with the frozen baseline.

### Experiments and Results

| Trial | Status | {case.metric} |
|:------|:------:|--------------:|
{rows}

{case.claim}

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
"""
    if case.replacement is None:
        return text, None
    if text.count(case.claim) != 1:
        raise RuntimeError(f"claim anchor is not unique for {case.name}: {case.claim!r}")
    corrupted = text.replace(case.claim, case.replacement, 1)
    line = next(
        index
        for index, source_line in enumerate(corrupted.splitlines(), start=1)
        if case.replacement in source_line
    )
    return corrupted, {
        "claim": case.claim,
        "injected_text": case.replacement,
        "location": {"line": line},
        "expected_checks": list(case.expected_checks),
        "description": case.description,
    }


CASES = (
    Case(
        name="clean_val_bpb",
        metric="val_bpb",
        baseline="1.224",
        candidate="1.196",
        claim="The absolute delta is -0.028 and relative improvement is 2.29%.",
    ),
    Case(
        name="clean_accuracy",
        metric="accuracy",
        baseline="70.0",
        candidate="75.0",
        claim="The absolute delta is 5.0 and relative improvement is 7.14%.",
    ),
    Case(
        name="corrupt_wrong_delta",
        metric="val_bpb",
        baseline="1.224",
        candidate="1.196",
        claim="The absolute delta is -0.028.",
        replacement="The absolute delta is -0.018.",
        expected_checks=("arithmetic",),
        description="The reported absolute delta does not equal candidate minus baseline.",
    ),
    Case(
        name="corrupt_wrong_percent",
        metric="accuracy",
        baseline="70.0",
        candidate="75.0",
        claim="The relative improvement is 7.14%.",
        replacement="The relative improvement is 17.14%.",
        expected_checks=("arithmetic",),
        description="The reported percentage improvement is not recomputable from the table.",
    ),
    Case(
        name="corrupt_fabricated_result",
        metric="loss",
        baseline="2.00",
        candidate="1.50",
        claim="The candidate-1 achieved loss of 1.50.",
        replacement="The candidate-1 achieved loss of 1.40.",
        expected_checks=("ledger-trace", "internal-consistency"),
        description="The prose result is absent from the ledger and contradicts its table row.",
    ),
    Case(
        name="corrupt_table_text_mismatch",
        metric="accuracy",
        baseline="70.0",
        candidate="75.0",
        claim="The candidate-1 achieved accuracy of 75.0.",
        replacement="The candidate-1 achieved accuracy of 74.0.",
        expected_checks=("ledger-trace", "internal-consistency"),
        description="The prose claim conflicts with both the result table and frozen evidence.",
    ),
)


def _write_ledger(case: Case) -> None:
    case_dir = EVIDENCE_DIR / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    records = (
        {"trial": "baseline", "status": "keep", case.metric: float(case.baseline)},
        {"trial": "candidate-1", "status": "keep", case.metric: float(case.candidate)},
    )
    ledger = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    (case_dir / "experiments.jsonl").write_text(ledger, encoding="utf-8")


def main() -> int:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{case.name}.md" for case in CASES}
    for path in PAPERS_DIR.glob("*.md"):
        if path.name != "sample_clean.md" and path.name not in expected_names:
            path.unlink()

    answer_key: dict[str, dict[str, object]] = {}
    for case in CASES:
        paper, flaw = _paper(case)
        paper_name = f"{case.name}.md"
        (PAPERS_DIR / paper_name).write_text(paper, encoding="utf-8")
        _write_ledger(case)
        answer_key[paper_name] = {
            "evidence_dir": f"evidence/{case.name}",
            "flaws": [] if flaw is None else [flaw],
        }

    ANSWER_KEY.write_text(
        json.dumps({"version": 1, "papers": answer_key}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(CASES)} papers ({sum(bool(case.replacement) for case in CASES)} corrupted, 2 clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
