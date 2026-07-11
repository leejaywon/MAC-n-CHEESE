"""Deterministic mechanical checks for stage S3.

M2a implements only ledger tracing.  It deliberately traces metric-labelled
numbers rather than every number in a paper: years, seeds, section numbers,
and run counts are not experimental result claims merely because they are
numeric.  Later checks own derived arithmetic and broader claim extraction.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


DEFAULT_METRIC_FIELDS = (
    "val_bpb",
    "score",
    "accuracy",
    "loss",
    "perplexity",
    "mfu_percent",
    "peak_vram_mb",
    "elapsed_seconds",
    "training_seconds",
    "total_seconds",
    "num_params_M",
    "total_tokens_M",
)
DERIVED_LABELS = frozenset({"delta", "improvement", "change", "difference"})
NON_RESULT_FIELDS = frozenset({"gpu_count", "seed", "depth", "num_steps"})
NON_RESULT_CONTEXT_RE = re.compile(
    r"\b(?:hypothesis|threshold|target|budget|planned|expected|seed|at least|at most)\b",
    re.I,
)
RESULT_LANGUAGE_RE = re.compile(
    r"\b(?:achieved|attained|found|measured|observed|obtained|reached|recorded|reports?|"
    r"resulted|scored|was|were|mean|median|average[sd]?)\b",
    re.I,
)


@dataclass(frozen=True)
class LedgerValue:
    path: str
    line: int
    field: str
    value: float
    trial: str | None


def _finding(
    *,
    severity: str,
    location: dict[str, Any] | str,
    expected: str,
    observed: str,
    evidence_path: str,
) -> dict[str, Any]:
    return {
        "check": "ledger-trace",
        "severity": severity,
        "location": location,
        "expected": expected,
        "observed": observed,
        "evidence_path": evidence_path,
    }


def _normalized_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _metric_aliases(field: str) -> set[str]:
    normalized = _normalized_label(field)
    aliases = {normalized, normalized.replace("_", " "), normalized.replace("_", "-")}
    if normalized.endswith("_percent"):
        base = normalized.removesuffix("_percent")
        aliases.update({base, f"{base} percent", f"{base} percentage"})
    return aliases


def _numeric_leaves(value: Any, prefix: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(value, dict):
        for key, child in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            yield from _numeric_leaves(child, field)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _numeric_leaves(child, f"{prefix}[{index}]")
    elif not isinstance(value, bool) and isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            yield prefix, numeric


def _load_ledgers(
    evidence_dir: Path,
) -> tuple[list[LedgerValue], list[dict[str, Any]], list[str]]:
    values: list[LedgerValue] = []
    findings: list[dict[str, Any]] = []
    paths = sorted(evidence_dir.rglob("experiments.jsonl"))
    relative_paths = [path.relative_to(evidence_dir).as_posix() for path in paths]

    for path, relative_path in zip(paths, relative_paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            findings.append(
                _finding(
                    severity="high",
                    location=f"{relative_path}:1",
                    expected="a readable UTF-8 JSONL experiment ledger",
                    observed=f"ledger could not be read: {error}",
                    evidence_path=relative_path,
                )
            )
            continue

        for line_number, raw_line in enumerate(lines, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as error:
                findings.append(
                    _finding(
                        severity="high",
                        location=f"{relative_path}:{line_number}",
                        expected="one valid JSON object per nonblank ledger line",
                        observed=f"invalid JSON: {error.msg}",
                        evidence_path=relative_path,
                    )
                )
                continue
            if not isinstance(record, dict):
                findings.append(
                    _finding(
                        severity="high",
                        location=f"{relative_path}:{line_number}",
                        expected="a JSON object experiment record",
                        observed=f"JSON {type(record).__name__}",
                        evidence_path=relative_path,
                    )
                )
                continue
            trial = record.get("trial") if isinstance(record.get("trial"), str) else None
            for field, numeric in _numeric_leaves(record):
                values.append(LedgerValue(relative_path, line_number, field, numeric, trial))
    return values, findings, relative_paths


def _table_metric(
    parsed_paper: dict[str, Any], token: dict[str, Any], metric_fields: set[str]
) -> str | None:
    table_id = token["location"].get("table_id")
    if table_id is None:
        return None
    line = token["location"]["line"]
    normalized_token = token["normalized"]
    for table in parsed_paper.get("tables", []):
        if table.get("id") != table_id:
            continue
        row = next((item for item in table.get("rows", []) if item.get("line") == line), None)
        if row is None:
            return None
        for index, cell in enumerate(row.get("cells", [])):
            if any(
                match.group(0).strip().replace(",", "").rstrip("%").strip() == normalized_token
                for match in re.finditer(
                    r"[+\-\N{MINUS SIGN}]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?\s*%?",
                    cell,
                )
            ):
                headers = table.get("header", [])
                if index >= len(headers):
                    return None
                header = str(headers[index])
                # A numeric table cell is not automatically a result.  Require
                # its column to name a known/default numeric evidence field.
                return header if any(_field_matches(header, field) for field in metric_fields) else None
    return None


def _prose_metric(
    context: str, token: dict[str, Any], metric_fields: set[str]
) -> str | None:
    token_start = int(token["location"]["column_start"]) - 1
    token_end = int(token["location"]["column_end"])
    candidates: list[tuple[int, str]] = []
    for field in metric_fields:
        for alias in _metric_aliases(field.rsplit(".", 1)[-1]):
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", re.I)
            for match in pattern.finditer(context):
                gap = max(match.start() - token_end, token_start - match.end(), 0)
                if gap <= 32:
                    candidates.append((gap, field))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[1]


def _is_result_prose(parsed_paper: dict[str, Any], token: dict[str, Any]) -> bool:
    context = str(token.get("context", ""))
    if NON_RESULT_CONTEXT_RE.search(context):
        return False
    section_id = token["location"].get("section_id")
    section_title = next(
        (
            str(section.get("title", ""))
            for section in parsed_paper.get("sections", [])
            if section.get("id") == section_id
        ),
        "",
    )
    in_result_section = re.search(
        r"\b(?:experiment|evaluation|finding|result)s?\b", section_title, re.I
    )
    return bool(in_result_section or RESULT_LANGUAGE_RE.search(context))


def _field_matches(metric: str, ledger_field: str) -> bool:
    metric_name = _normalized_label(metric.rsplit(".", 1)[-1])
    ledger_name = _normalized_label(ledger_field.rsplit(".", 1)[-1])
    return metric_name == ledger_name or metric_name in _metric_aliases(ledger_name)


def _trial_context(context: str) -> str | None:
    lowered = context.lower().replace("_", "-")
    match = re.search(r"\bcandidate[- ]?(\d+)\b", lowered)
    if match:
        return f"candidate-{match.group(1)}"
    if re.search(r"\bwinner[- ]confirmation\b", lowered):
        return "winner-confirmation"
    if re.search(r"\bbaseline\b", lowered):
        return "baseline"
    if re.search(r"\bcandidate\b", lowered):
        return "candidate"
    if re.search(r"\bconfirmation\b", lowered):
        return "winner-confirmation"
    return None


def _trial_matches(context_trial: str | None, ledger_trial: str | None) -> bool:
    if context_trial is None:
        return True
    if ledger_trial is None:
        return False
    if context_trial == "candidate":
        return ledger_trial.startswith("candidate")
    return context_trial == ledger_trial


def _rounding_tolerance(normalized: str) -> Decimal:
    """Allow exactly half a unit in the paper's last displayed decimal place."""

    compact = normalized.lower()
    mantissa, _, exponent_text = compact.partition("e")
    decimals = len(mantissa.partition(".")[2]) if "." in mantissa else 0
    exponent = int(exponent_text) if exponent_text else 0
    return Decimal("0.5") * (Decimal(10) ** (exponent - decimals))


def _numbers_match(normalized: str, ledger_value: float) -> bool:
    try:
        paper_value = Decimal(normalized)
        evidence_value = Decimal(str(ledger_value))
    except (InvalidOperation, ValueError):
        return False
    return abs(paper_value - evidence_value) <= _rounding_tolerance(normalized)


def _row_context(parsed_paper: dict[str, Any], token: dict[str, Any]) -> str:
    table_id = token["location"].get("table_id")
    line = token["location"]["line"]
    if table_id is not None:
        for table in parsed_paper.get("tables", []):
            if table.get("id") == table_id:
                row = next((item for item in table.get("rows", []) if item.get("line") == line), None)
                if row:
                    return " ".join(str(cell) for cell in row.get("cells", []))
    return str(token.get("context", ""))


def check_ledger_trace(parsed_paper: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    """Trace metric-labelled paper values to ``experiments.jsonl`` records.

    The return value is JSON-serializable and separates successful/failed
    per-number traces from findings, which contain only proven evidence gaps.
    """

    ledger_values, findings, ledger_paths = _load_ledgers(evidence_dir)
    ledger_fields = {
        value.field
        for value in ledger_values
        if _normalized_label(value.field.rsplit(".", 1)[-1]) not in NON_RESULT_FIELDS
    }
    metric_fields = ledger_fields | set(DEFAULT_METRIC_FIELDS)
    traces: list[dict[str, Any]] = []

    for token in parsed_paper.get("numeric_tokens", []):
        table_metric = _table_metric(parsed_paper, token, metric_fields)
        metric = table_metric
        if metric is None and _is_result_prose(parsed_paper, token):
            metric = _prose_metric(str(token.get("context", "")), token, metric_fields)
        if metric is None or _normalized_label(metric) in DERIVED_LABELS:
            continue

        context = _row_context(parsed_paper, token)
        context_trial = _trial_context(context)
        candidates = [
            value
            for value in ledger_values
            if _field_matches(metric, value.field) and _trial_matches(context_trial, value.trial)
        ]
        matches = [value for value in candidates if _numbers_match(token["normalized"], value.value)]
        trace = {
            "number_id": token["id"],
            "metric": _normalized_label(metric),
            "paper_value": token["normalized"],
            "location": token["location"],
            "trial_context": context_trial,
            "matched": bool(matches),
            "evidence": [
                {
                    "path": value.path,
                    "line": value.line,
                    "field": value.field,
                    "value": value.value,
                    "trial": value.trial,
                }
                for value in matches
            ],
        }
        traces.append(trace)

        if matches:
            continue
        evidence_path = ", ".join(ledger_paths) if ledger_paths else "experiments.jsonl (not found)"
        expected_values = sorted({value.value for value in candidates})
        expected = (
            f"a rounding-compatible {_normalized_label(metric)} value in {evidence_path}"
            if not expected_values
            else f"one of the traceable {_normalized_label(metric)} values {expected_values}"
        )
        findings.append(
            _finding(
                severity="high",
                location=token["location"],
                expected=expected,
                observed=(
                    f"paper reports {_normalized_label(metric)}={token['normalized']}"
                    + (f" for {context_trial}" if context_trial else "")
                ),
                evidence_path=evidence_path,
            )
        )

    return {
        "check": "ledger-trace",
        "ledger_paths": ledger_paths,
        "traces": traces,
        "findings": findings,
    }
