"""Conservative baseline-fairness check for explicit improvement claims.

The check intentionally does not decide whether a metric value is better.  Its
job is narrower: an improvement claim must identify its baseline, compare
records on one common metric, and have a successful confirmation rerun that
supports the claimed direction. Ambiguous prose that merely discusses planned
or possible improvements is ignored to avoid reviewer false positives.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


IMPROVEMENT_RE = re.compile(
    r"\b(?:improv(?:e[ds]?|ing|ement)|outperform(?:s|ed|ing)?|surpass(?:es|ed|ing)?|"
    r"beat(?:s|en|ing)?|better\s+than|(?:lower|higher)\s+than)\b",
    re.I,
)
NON_CLAIM_RE = re.compile(
    r"\b(?:aim(?:s|ed)?\s+to|could|expected|future|goal|hope(?:s|d)?\s+to|"
    r"hypothes(?:is|ize[ds]?)|might|plan(?:s|ned)?\s+to|potential|would)\b",
    re.I,
)
NEGATED_RE = re.compile(
    r"\b(?:did\s+not|does\s+not|do\s+not|no|not|never|without)\b"
    r"[^.!?]{0,24}\b(?:improv|outperform|surpass|beat|better|lower|higher)",
    re.I,
)
# A recomputed, explicitly numeric improvement is arithmetic reporting rather
# than a general superiority claim.  The arithmetic check owns this case; the
# fairness gate applies when the prose says the candidate actually improved.
BOUNDED_ARITHMETIC_RE = re.compile(
    r"\b(?:relative\s+|percentage\s+|percent\s+)?improvement\s+"
    r"(?:is|was|of|=|:)\s*[+\-N{MINUS SIGN}]?(?:\d+(?:\.\d+)?|\.\d+)\s*%?",
    re.I,
)
BASELINE_REFERENCE_RE = re.compile(
    r"\bbaseline\b|\b(?:compared\s+(?:to|with)|relative\s+to|versus|vs\.?)\s+"
    r"(?:the\s+)?[A-Za-z][\w.-]*",
    re.I,
)
CONFIRMATION_RE = re.compile(r"\b(?:confirm(?:ation|atory|ed)?|re[-_ ]?run|repeat(?:ed)?)\b", re.I)
FAILED_STATUSES = frozenset({"cancel", "cancelled", "crash", "discard", "error", "fail", "failed"})
NON_METRIC_FIELDS = frozenset(
    {
        "gpu_count",
        "seed",
        "step",
        "steps",
        "num_steps",
        "run",
        "run_id",
        "trial",
        "status",
        "timestamp",
    }
)


@dataclass(frozen=True)
class LedgerRecord:
    path: str
    line: int
    trial: str
    status: str
    metrics: frozenset[str]
    values: tuple[tuple[str, float], ...]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _numeric_values(value: Any, prefix: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(value, dict):
        for key, child in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            yield from _numeric_values(child, field)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _numeric_values(child, f"{prefix}[{index}]")
    elif not isinstance(value, bool) and isinstance(value, (int, float)):
        numeric = float(value)
        leaf = _normalize(prefix.rsplit(".", 1)[-1].split("[", 1)[0])
        if math.isfinite(numeric) and leaf and leaf not in NON_METRIC_FIELDS:
            yield leaf, numeric


def _load_records(evidence_dir: Path) -> tuple[list[LedgerRecord], list[str]]:
    records: list[LedgerRecord] = []
    paths = sorted(evidence_dir.rglob("experiments.jsonl"))
    relative_paths = [path.relative_to(evidence_dir).as_posix() for path in paths]
    for path, relative in zip(paths, relative_paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, raw in enumerate(lines, start=1):
            try:
                value = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            trial = str(value.get("trial", value.get("run_type", value.get("role", "")))).strip()
            status = str(value.get("status", "")).strip().lower()
            values = tuple(_numeric_values(value))
            metrics = frozenset(field for field, _ in values)
            records.append(LedgerRecord(relative, line_number, trial, status, metrics, values))
    return records, relative_paths


def _sentences(parsed_paper: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    source = Path(str(parsed_paper["source_path"]))
    sections = parsed_paper.get("sections", [])
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or "|" in line:
            continue
        for match in re.finditer(r"[^.!?]+[.!?]?", line):
            sentence = match.group(0).strip()
            if not sentence:
                continue
            section_id = next(
                (
                    section.get("id")
                    for section in sections
                    if section.get("line_start", 0) <= line_number <= section.get("line_end", -1)
                ),
                None,
            )
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            yield sentence, {
                "line": line_number,
                "column_start": match.start() + leading + 1,
                "column_end": match.end(),
                "section_id": section_id,
                "table_id": None,
            }


def _metric_mentions(sentence: str, available: set[str]) -> set[str]:
    normalized_text = _normalize(sentence)
    padded = f"_{normalized_text}_"
    return {
        metric
        for metric in available
        if f"_{metric}_" in padded
        or f"_{metric.replace('_', '')}_" in padded
        or f"_{metric.replace('_', ' ')}_" in padded
    }


def _is_baseline(record: LedgerRecord) -> bool:
    return bool(re.search(r"\bbaseline\b", record.trial.replace("_", "-"), re.I))


def _is_confirmation(record: LedgerRecord) -> bool:
    failed = any(record.status == value or record.status.startswith(f"{value}ed") for value in FAILED_STATUSES)
    return bool(CONFIRMATION_RE.search(record.trial)) and not failed


def _is_candidate(record: LedgerRecord) -> bool:
    return not _is_baseline(record) and not _is_confirmation(record) and record.status not in FAILED_STATUSES


def _finding(location: dict[str, Any], expected: str, observed: str, evidence_path: str) -> dict[str, Any]:
    return {
        "check": "baseline-fairness",
        "severity": "high",
        "location": location,
        "expected": expected,
        "observed": observed,
        "evidence_path": evidence_path,
    }


LOWER_IS_BETTER = frozenset(
    {"val_bpb", "loss", "perplexity", "elapsed_seconds", "training_seconds", "total_seconds", "peak_vram_mb"}
)
HIGHER_IS_BETTER = frozenset({"score", "accuracy", "mfu_percent"})


def _claimed_direction(sentence: str, metric: str) -> str | None:
    if re.search(r"\blower\s+than\b", sentence, re.I):
        return "lower"
    if re.search(r"\bhigher\s+than\b", sentence, re.I):
        return "higher"
    if metric in LOWER_IS_BETTER:
        return "lower"
    if metric in HIGHER_IS_BETTER:
        return "higher"
    return None


def _metric_values(records: list[LedgerRecord], metric: str) -> list[float]:
    return [value for record in records for field, value in record.values if field == metric]


def check_baseline_fairness(parsed_paper: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    """Audit explicit improvement claims against baseline and rerun evidence."""

    records, ledger_paths = _load_records(evidence_dir)
    available_metrics = set().union(*(record.metrics for record in records)) if records else set()
    baselines = [record for record in records if _is_baseline(record)]
    candidates = [record for record in records if _is_candidate(record)]
    confirmations = [record for record in records if _is_confirmation(record)]
    evidence_path = ", ".join(ledger_paths) if ledger_paths else "experiments.jsonl (not found)"
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for sentence, location in _sentences(parsed_paper):
        if (
            not IMPROVEMENT_RE.search(sentence)
            or NON_CLAIM_RE.search(sentence)
            or NEGATED_RE.search(sentence)
            or BOUNDED_ARITHMETIC_RE.search(sentence)
        ):
            continue

        named_baseline = bool(BASELINE_REFERENCE_RE.search(sentence))
        mentioned = _metric_mentions(sentence, available_metrics)
        comparison_metrics = {
            metric
            for baseline in baselines
            for candidate in candidates
            for metric in baseline.metrics & candidate.metrics
        }
        eligible_metrics = comparison_metrics & mentioned if mentioned else comparison_metrics
        confirmation_metrics = {
            metric
            for metric in eligible_metrics
            if any(metric in record.metrics for record in confirmations)
        }
        same_metric = len(eligible_metrics) == 1
        confirmation_present = same_metric and eligible_metrics == confirmation_metrics
        direction: str | None = None
        confirmation_supports_claim: bool | None = None
        baseline_values: list[float] = []
        candidate_values: list[float] = []
        confirmation_values: list[float] = []
        if confirmation_present:
            metric = next(iter(eligible_metrics))
            direction = _claimed_direction(sentence, metric)
            baseline_values = _metric_values(baselines, metric)
            candidate_values = _metric_values(candidates, metric)
            confirmation_values = _metric_values(confirmations, metric)
            if direction is not None and baseline_values and candidate_values and confirmation_values:
                compare = (lambda value, baseline: value < baseline) if direction == "lower" else (lambda value, baseline: value > baseline)
                # Multiple records are accepted only when at least one
                # candidate and every purported confirmation support the same
                # side of every baseline.
                candidate_better = any(
                    compare(candidate, baseline)
                    for candidate in candidate_values
                    for baseline in baseline_values
                )
                confirmations_better = all(
                    compare(confirmation, baseline)
                    for confirmation in confirmation_values
                    for baseline in baseline_values
                )
                confirmation_supports_claim = candidate_better and confirmations_better

        trace = {
            "claim": sentence,
            "location": location,
            "named_baseline": named_baseline,
            "mentioned_metrics": sorted(mentioned),
            "comparison_metrics": sorted(eligible_metrics),
            "same_metric": same_metric,
            "confirmation_rerun_present": confirmation_present,
            "claimed_direction": direction,
            "confirmation_supports_claim": confirmation_supports_claim,
            "evidence": [
                {"path": record.path, "line": record.line, "trial": record.trial}
                for record in baselines + candidates + confirmations
            ],
            "matched": (
                named_baseline
                and same_metric
                and confirmation_present
                and confirmation_supports_claim is not False
            ),
        }
        traces.append(trace)

        if not named_baseline:
            findings.append(
                _finding(
                    location,
                    "the improvement claim to identify the compared baseline",
                    f"claim does not name a baseline: {sentence}",
                    "paper",
                )
            )
        if not same_metric:
            observed = (
                f"ambiguous common metrics {sorted(eligible_metrics)}"
                if eligible_metrics
                else "no common numeric metric across baseline and candidate evidence"
            )
            findings.append(
                _finding(
                    location,
                    "exactly one common metric for the baseline and candidate comparison",
                    observed,
                    evidence_path,
                )
            )
        elif not confirmation_present:
            metric = next(iter(eligible_metrics))
            findings.append(
                _finding(
                    location,
                    f"a successful confirmation rerun recording the same {metric} metric",
                    "no matching successful confirmation rerun record",
                    evidence_path,
                )
            )
        elif confirmation_supports_claim is False:
            metric = next(iter(eligible_metrics))
            findings.append(
                _finding(
                    location,
                    f"candidate and confirmation {metric} values both {direction} than the baseline",
                    (
                        f"baseline={baseline_values}, candidate={candidate_values}, "
                        f"confirmation={confirmation_values} do not confirm the claimed improvement"
                    ),
                    evidence_path,
                )
            )

    return {"check": "baseline-fairness", "traces": traces, "findings": findings}
