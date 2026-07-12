"""Deterministic mechanical checks for stage S3.

The checks deliberately require an explicit metric and comparison context.
Years, seeds, section numbers, and run counts are not experimental claims just
because they are numeric; ambiguous relationships are left for later claim
extraction instead of becoming false-positive findings.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .parser import paper_text


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
    check: str = "ledger-trace",
    severity: str,
    location: dict[str, Any] | str,
    expected: str,
    observed: str,
    evidence_path: str,
) -> dict[str, Any]:
    return {
        "check": check,
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
    # Require the canonical hyphen for numbered trials. A permissive
    # ``candidate 75`` match misreads the first numeric result cell as a trial
    # suffix when a table row is flattened into context.
    match = re.search(r"\bcandidate-(\d+)\b", lowered)
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


def _is_ordinal_suffix(token: dict[str, Any]) -> bool:
    """True when a number is an identifier's ordinal suffix ("candidate-1", "gpt-4").

    The parser's lookbehind already blocks a digit after a letter ("F1"), but not
    a digit after a hyphen, so "candidate-1" leaks a bare "1". That digit names a
    trial, not a measured value, and must never be traced as a metric.
    """

    context = str(token.get("context", ""))
    start = int(token.get("location", {}).get("column_start", 1)) - 1  # 0-based
    return start >= 2 and context[start - 1] in "-–—" and context[start - 2].isalnum()


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


def check_ledger_trace(
    parsed_paper: dict[str, Any], evidence_dir: Path, event_format: bool = True
) -> dict[str, Any]:
    """Trace metric-labelled paper values to ``experiments.jsonl`` records.

    The return value is JSON-serializable and separates successful/failed
    per-number traces from findings, which contain only proven evidence gaps.

    ``event_format`` distinguishes an event submission (expected to ship a ledger)
    from an arbitrary peer paper. When it is False and no ledger exists, an
    unmatched prose value proves nothing — there is no ledger to trace against —
    so only transparency traces are emitted, never findings. This mirrors
    baseline-fairness and prevents a false positive on any normal paper that
    reports a metric-labelled number (e.g. an Inception score in its abstract).
    """

    ledger_values, findings, ledger_paths = _load_ledgers(evidence_dir)
    # With a ledger present, an unmatched value is a real finding (fabricated-result
    # detection). With no ledger, findings are honest only for an event submission
    # that was expected to ship one; on a peer paper (event_format False) the
    # absence proves nothing and must not be flagged.
    has_ledger = bool(ledger_paths)
    suppress_missing_ledger_findings = not has_ledger and not event_format
    ledger_fields = {
        value.field
        for value in ledger_values
        if _normalized_label(value.field.rsplit(".", 1)[-1]) not in NON_RESULT_FIELDS
    }
    metric_fields = ledger_fields | set(DEFAULT_METRIC_FIELDS)
    traces: list[dict[str, Any]] = []

    for token in parsed_paper.get("numeric_tokens", []):
        if _is_ordinal_suffix(token):
            continue
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

        if matches or suppress_missing_ledger_findings:
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


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _result_values(parsed_paper: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only metric-labelled table/prose values with trial context."""

    metric_fields = set(DEFAULT_METRIC_FIELDS)
    values: list[dict[str, Any]] = []
    for token in parsed_paper.get("numeric_tokens", []):
        if _is_ordinal_suffix(token):
            continue
        table_metric = _table_metric(parsed_paper, token, metric_fields)
        source = "table" if table_metric else "prose"
        metric = table_metric
        if metric is None and _is_result_prose(parsed_paper, token):
            metric = _prose_metric(str(token.get("context", "")), token, metric_fields)
        if metric is None or token.get("kind") == "percentage":
            continue
        normalized_metric = _normalized_label(metric)
        if normalized_metric in DERIVED_LABELS:
            continue
        value = _decimal(str(token["normalized"]))
        if value is None:
            continue
        values.append(
            {
                "number_id": token["id"],
                "source": source,
                "metric": normalized_metric,
                "trial": _trial_context(_row_context(parsed_paper, token)),
                "value": value,
                "display": token["normalized"],
                "location": token["location"],
            }
        )
    return values


def check_internal_consistency(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Compare table and prose values only when metric and trial both agree.

    Requiring an explicit trial prevents unrelated rows or aggregate prose from
    being compared. Repeated mentions are retained as traces, while only
    rounding-incompatible pairs become findings.
    """

    values = _result_values(parsed_paper)
    table_values = [value for value in values if value["source"] == "table"]
    prose_values = [value for value in values if value["source"] == "prose"]
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for prose in prose_values:
        if prose["trial"] is None:
            continue
        candidates = [
            table
            for table in table_values
            if table["metric"] == prose["metric"] and table["trial"] == prose["trial"]
        ]
        if not candidates:
            continue
        matched = any(_numbers_match(prose["display"], float(table["value"])) for table in candidates)
        trace = {
            "prose_number_id": prose["number_id"],
            "metric": prose["metric"],
            "trial": prose["trial"],
            "prose_value": prose["display"],
            "prose_location": prose["location"],
            "table_values": [str(table["value"]) for table in candidates],
            "table_locations": [table["location"] for table in candidates],
            "matched": matched,
        }
        traces.append(trace)
        if not matched:
            findings.append(
                _finding(
                    check="internal-consistency",
                    severity="high",
                    location=prose["location"],
                    expected=(
                        f"{prose['metric']} for {prose['trial']} to equal table value(s) "
                        f"{trace['table_values']}"
                    ),
                    observed=f"prose reports {prose['display']}",
                    evidence_path=f"paper table at {trace['table_locations']}",
                )
            )

    return {"check": "internal-consistency", "traces": traces, "findings": findings}


ARITHMETIC_CLAIM_RE = re.compile(
    r"\b(?P<label>absolute\s+delta|delta|difference|relative\s+improvement|"
    r"percentage\s+improvement|percent\s+improvement|improvement|relative\s+change|"
    r"percentage\s+change|percent\s+change)\b"
    r"[^\n.!?;]{0,48}?"
    r"(?:is|was|of|=|:)\s*"
    r"(?P<value>[+\-\N{MINUS SIGN}]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?\s*%?)",
    re.I,
)
# Self-contained prose ratio: "from A to B, a (relative) gain of Z%". The
# operands live in the sentence, so this generalizes beyond the event's
# baseline/candidate table format and fires on arbitrary peer papers.
FROM_TO_RATIO_RE = re.compile(
    r"\bfrom\s+(?P<a>\d[\d,]*(?:\.\d+)?)\s*%?\s+to\s+(?P<b>\d[\d,]*(?:\.\d+)?)\s*%?"
    r"[^.!?\n]{0,80}?"
    r"\b(?:relative\s+|percentage\s+|percent\s+)?"
    r"(?P<kind>gain|improvement|increase|reduction|decrease|drop|change)\s+of\s+"
    r"(?P<z>\d[\d,]*(?:\.\d+)?)\s*%",
    re.I,
)


def _table_comparison_pairs(parsed_paper: dict[str, Any]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    values = [value for value in _result_values(parsed_paper) if value["source"] == "table"]
    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for metric in sorted({value["metric"] for value in values}):
        baseline = [value for value in values if value["metric"] == metric and value["trial"] == "baseline"]
        candidates = [
            value
            for value in values
            if value["metric"] == metric
            and (
                value["trial"] == "winner-confirmation"
                or str(value["trial"] or "").startswith("candidate")
            )
        ]
        # Multiple eligible rows make the operands ambiguous. Do not guess.
        if len(baseline) == 1 and len(candidates) == 1:
            pairs[metric] = (baseline[0], candidates[0])
    return pairs


def _table_mean_comparison_pairs(
    parsed_paper: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Aggregate repeated baseline/candidate rows for explicit mean claims.

    Repeated rows make a direct baseline/candidate pairing ambiguous, but an
    explicit prose cue such as "averaging the runs" supplies a deterministic
    operation: compute each group mean and then compare those means. Requiring
    at least two observations in both groups prevents this path from silently
    changing the semantics of ordinary one-row result tables.
    """

    values = [value for value in _result_values(parsed_paper) if value["source"] == "table"]
    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for metric in sorted({value["metric"] for value in values}):
        baseline = [
            value
            for value in values
            if value["metric"] == metric and value["trial"] == "baseline"
        ]
        candidates = [
            value
            for value in values
            if value["metric"] == metric
            and str(value["trial"] or "").startswith("candidate")
        ]
        if len(baseline) < 2 or len(candidates) < 2:
            continue

        def aggregate(group: list[dict[str, Any]], trial: str) -> dict[str, Any]:
            mean = sum((value["value"] for value in group), Decimal(0)) / len(group)
            return {
                "metric": metric,
                "trial": trial,
                "value": mean,
                "display": str(mean),
                "location": group[0]["location"],
                "locations": [value["location"] for value in group],
                "count": len(group),
            }

        pairs[metric] = (aggregate(baseline, "baseline"), aggregate(candidates, "candidate"))
    return pairs


def _lower_is_better(parsed_paper: dict[str, Any], metric: str) -> bool | None:
    metric_alias = re.escape(metric).replace("_", r"[ _-]")
    text = "\n".join(str(section.get("content", "")) for section in parsed_paper.get("sections", []))
    if re.search(rf"(?:lower(?:s|ed|ing)?|reduce[sd]?|decrease[sd]?)\s+`?{metric_alias}`?", text, re.I):
        return True
    if re.search(rf"(?:higher|increase[sd]?|raise[sd]?)\s+`?{metric_alias}`?", text, re.I):
        return False
    if metric in {"val_bpb", "loss", "perplexity", "elapsed_seconds", "training_seconds", "total_seconds", "peak_vram_mb"}:
        return True
    if metric in {"score", "accuracy", "mfu_percent"}:
        return False
    return None


def _prose_paragraphs(lines: list[str]) -> list[tuple[str, list[int]]]:
    """Join consecutive prose lines into paragraphs with a per-character line map.

    Claims wrap across physical lines in real papers (and in PDF-extracted text),
    so matching per physical line misses them. Blank lines and table lines break
    paragraphs; the char->line map recovers the true source line of any match.
    """

    paragraphs: list[tuple[str, list[int]]] = []
    parts: list[str] = []
    char_lines: list[int] = []

    def flush() -> None:
        if parts:
            paragraphs.append(("".join(parts), list(char_lines)))
            parts.clear()
            char_lines.clear()

    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or "|" in line:
            flush()
            continue
        if parts:
            parts.append(" ")
            char_lines.append(line_number)
        parts.append(line)
        char_lines.extend([line_number] * len(line))
    flush()
    return paragraphs


def check_arithmetic(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Recompute explicit delta/change claims from unambiguous table operands."""

    pairs = _table_comparison_pairs(parsed_paper)
    mean_pairs = _table_mean_comparison_pairs(parsed_paper)
    lines = paper_text(parsed_paper).splitlines()
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, start=1):
        if "|" in line:  # arithmetic claims are prose, not table labels/cells
            continue
        for match in ARITHMETIC_CLAIM_RE.finditer(line):
            raw_value = match.group("value").replace("−", "-").replace(",", "").strip()
            is_percent = raw_value.endswith("%")
            display = raw_value.rstrip("%").strip()
            reported = _decimal(display)
            if reported is None:
                continue
            label = _normalized_label(match.group("label"))
            is_relative = is_percent or any(word in label for word in ("relative", "percent", "percentage", "improvement"))

            # A single metric pair is safe. With multiple pairs, require the
            # metric name in the same sentence instead of silently choosing.
            eligible = list(pairs.items())
            uses_group_means = False
            if not eligible and re.search(r"\b(?:averag(?:e|ed|es|ing)|mean)\b", line, re.I):
                eligible = list(mean_pairs.items())
                uses_group_means = True
            if len(eligible) > 1:
                eligible = [item for item in eligible if any(alias in line.lower() for alias in _metric_aliases(item[0]))]
            if len(eligible) != 1:
                continue
            metric, (baseline, candidate) = eligible[0]
            baseline_value = baseline["value"]
            candidate_value = candidate["value"]
            expected = candidate_value - baseline_value
            formula = (
                "mean(candidate runs) - mean(baseline runs)"
                if uses_group_means
                else "candidate - baseline"
            )
            if is_relative:
                if baseline_value == 0:
                    continue
                lower = _lower_is_better(parsed_paper, metric)
                if "improvement" in label and lower is not None:
                    expected = (baseline_value - candidate_value) / abs(baseline_value) if lower else (candidate_value - baseline_value) / abs(baseline_value)
                    formula = "improvement / abs(baseline)"
                else:
                    expected = (candidate_value - baseline_value) / abs(baseline_value)
                    formula = "(candidate - baseline) / abs(baseline)"
                if is_percent:
                    expected *= Decimal(100)

            matched = _numbers_match(display, float(expected))
            location = {
                "line": line_number,
                "column_start": match.start("value") + 1,
                "column_end": match.end("value"),
                "section_id": next(
                    (section["id"] for section in parsed_paper.get("sections", []) if section["line_start"] <= line_number <= section["line_end"]),
                    None,
                ),
                "table_id": None,
            }
            trace = {
                "metric": metric,
                "label": label,
                "reported": display,
                "expected": str(expected),
                "formula": formula,
                "operands": {"baseline": str(baseline_value), "candidate": str(candidate_value)},
                "location": location,
                "matched": matched,
            }
            traces.append(trace)
            if not matched:
                findings.append(
                    _finding(
                        check="arithmetic",
                        severity="high",
                        location=location,
                        expected=f"{expected} from {formula} using baseline={baseline_value}, candidate={candidate_value}",
                        observed=f"paper reports {match.group('value').strip()}",
                        evidence_path=(
                            "paper table locations "
                            f"{baseline.get('locations', [baseline['location']])} and "
                            f"{candidate.get('locations', [candidate['location']])}"
                        ),
                    )
                )

    for paragraph, char_lines in _prose_paragraphs(lines):
        for match in FROM_TO_RATIO_RE.finditer(paragraph):
            operand_a = _decimal(match.group("a").replace(",", ""))
            operand_b = _decimal(match.group("b").replace(",", ""))
            reported_display = match.group("z").replace(",", "")
            reported = _decimal(reported_display)
            if operand_a is None or operand_b is None or reported is None or operand_a == 0:
                continue
            expected = (abs(operand_b - operand_a) / abs(operand_a)) * Decimal(100)
            expected_display = expected.quantize(Decimal("0.01"))
            matched = _numbers_match(reported_display, float(expected))
            z_index = match.start("z")
            line_number = char_lines[z_index]
            line_start = char_lines.index(line_number)
            location = {
                "line": line_number,
                "column_start": z_index - line_start + 1,
                "column_end": max(z_index - line_start + 1, match.end("z") - line_start),
                "section_id": next(
                    (section["id"] for section in parsed_paper.get("sections", []) if section["line_start"] <= line_number <= section["line_end"]),
                    None,
                ),
                "table_id": None,
            }
            traces.append(
                {
                    "metric": "prose-ratio",
                    "label": _normalized_label(match.group("kind")),
                    "reported": reported_display,
                    "expected": str(expected),
                    "formula": "100 * abs(to - from) / abs(from)",
                    "operands": {"from": str(operand_a), "to": str(operand_b)},
                    "location": location,
                    "matched": matched,
                }
            )
            if not matched:
                findings.append(
                    _finding(
                        check="arithmetic",
                        severity="high",
                        location=location,
                        expected=f"{expected_display}% from 100*abs(to-from)/abs(from) using from={operand_a}, to={operand_b}",
                        observed=f"paper reports a {match.group('kind').lower()} of {match.group('z').strip()}%",
                        evidence_path=f"paper prose at line {line_number}",
                    )
                )

    return {"check": "arithmetic", "traces": traces, "findings": findings}
