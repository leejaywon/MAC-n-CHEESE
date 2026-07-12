"""Deterministic scientific scaffolding — reviewer substance with no model call.

The module keeps its original one-argument ``rigor_questions`` API, while optional
ledger and finding inputs add evidence-grounded scope comments and concrete
follow-ups. Uncertain design critiques remain Questions under the false-positive
rule; a scope criticism is emitted only for explicit generalized language whose
breadth is greater than the supplied ledger coverage.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .parser import paper_text


# Any of these means the paper already addresses run-to-run variability.
VARIANCE_RE = re.compile(
    r"\b(?:variance|std(?:ev|\.)?|standard[- ]deviation|confidence[- ]interval|"
    r"error[- ]bars?|seeds?|stderr|averaged|deviation|±)\b"
    r"|\b\d+\s+(?:runs?|seeds?|trials?)\b"
    r"|\bmultiple\s+(?:runs?|seeds?|trials?)\b",
    re.I,
)

GENERALIZED_CLAIM_RE = re.compile(
    r"\b(?:generaliz(?:e[sd]?|able|ation)|broadly\s+(?:applicable|effective)|"
    r"universal(?:ly)?|robust\s+across|consistently\s+(?:outperform|improv|perform)|"
    r"(?:across|on)\s+(?:all|every|multiple|several|diverse|a\s+wide\s+range\s+of)\s+"
    r"(?:benchmarks?|datasets?|tasks?|domains?|metrics?|seeds?|runs?|"
    r"gpus?|gpu\s+types?|hardware|accelerators?))\b",
    re.I,
)
NON_ASSERTION_RE = re.compile(
    r"\b(?:aim(?:s|ed)?\s+to|could|future|hope(?:s|d)?\s+to|hypothes(?:is|ize[ds]?)|"
    r"might|plan(?:s|ned)?\s+to|potentially|would)\b",
    re.I,
)
NEGATED_SCOPE_RE = re.compile(
    r"\b(?:does?|did|is|are|was|were|may|might|can|could|will|would)\s+not\b"
    r"[^.!?]{0,40}\b(?:generaliz|robust|consistent|universal)",
    re.I,
)
COUNTED_SCOPE_RE = re.compile(
    r"\b(?:across|on)\s+(?P<count>\d+)\s+"
    r"(?P<dimension>benchmarks?|datasets?|tasks?|domains?|metrics?|seeds?|runs?|trials?|"
    r"gpus?|gpu\s+types?|hardware|accelerators?)\b",
    re.I,
)
QUALIFIED_SCOPE_RE = re.compile(
    r"\b(?:across|on)\s+"
    r"(?P<quantifier>all|every|multiple|several|diverse|a\s+wide\s+range\s+of)\s+"
    r"(?P<dimension>benchmarks?|datasets?|tasks?|domains?|metrics?|seeds?|runs?|trials?|"
    r"gpus?|gpu\s+types?|hardware|accelerators?)\b",
    re.I,
)
BARE_SCOPE_RE = re.compile(
    r"\b(?:generaliz(?:e[sd]?|able|ation)|robust)\s+(?:well\s+)?across\s+"
    r"(?P<dimension>benchmarks?|datasets?|tasks?|domains?|metrics?|seeds?|runs?|trials?|"
    r"gpus?|gpu\s+types?|hardware|accelerators?)\b",
    re.I,
)

CONFIRMATION_RE = re.compile(r"\b(?:confirm(?:ation|atory|ed)?|re[-_ ]?run|repeat(?:ed)?)\b", re.I)
FAILED_STATUSES = frozenset({"cancel", "cancelled", "crash", "discard", "error", "fail", "failed"})
TRIAL_NAME_FIELDS = frozenset({"trial", "run", "run_id", "run_name", "run_tag", "role", "name"})
SEED_FIELDS = frozenset({"seed", "random_seed", "rng_seed"})
GPU_FIELDS = frozenset(
    {"gpu", "gpu_type", "gpu_model", "accelerator", "accelerator_type", "device", "device_type"}
)
BENCHMARK_FIELDS = frozenset(
    {"benchmark", "benchmark_name", "dataset", "dataset_name", "task", "task_name", "suite"}
)
METRIC_NAME_FIELDS = frozenset({"metric", "metric_name", "measure", "measure_name"})
METRIC_CONTAINER_FIELDS = frozenset({"metric", "metrics", "result", "results", "score", "scores"})
NON_METRIC_FIELDS = frozenset(
    {
        *TRIAL_NAME_FIELDS,
        *SEED_FIELDS,
        *GPU_FIELDS,
        *BENCHMARK_FIELDS,
        *METRIC_NAME_FIELDS,
        "batch_size",
        "duration",
        "elapsed_seconds",
        "epoch",
        "epochs",
        "gpu_count",
        "learning_rate",
        "lr",
        "num_steps",
        "status",
        "step",
        "steps",
        "timestamp",
        "tokens",
        "total_tokens",
    }
)

FOLLOW_UP_ACTIONS = {
    "variance": "Repeat the comparison with at least three independent seeds.",
    "baseline-fairness": "Run the named baseline under the same metric and budget.",
    "negative-evidence": "Report the omitted failed/discarded trial and its effect.",
    "citation-existence": "Correct or replace the unresolved citation identifier.",
}


def _normalize_field(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _leaf_values(value: object, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], object]]:
    leaves: list[tuple[tuple[str, ...], object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            leaves.extend(_leaf_values(child, (*path, str(key))))
    elif isinstance(value, list):
        for child in value:
            leaves.extend(_leaf_values(child, path))
    else:
        leaves.append((path, value))
    return leaves


def _scope_value(value: object) -> object | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if re.fullmatch(r"[+-]?\d+", stripped):
            return int(stripped)
        return stripped
    return None


def _sorted_values(values: set[object]) -> list[object]:
    return sorted(values, key=lambda value: (type(value).__name__, str(value).casefold()))


def _record_name(record: dict[str, Any]) -> str:
    values = [
        str(record[field]).strip()
        for field in TRIAL_NAME_FIELDS
        if field in record and record[field] is not None
    ]
    return " ".join(value for value in values if value)


def _is_successful_confirmation(record: dict[str, Any]) -> bool:
    status = str(record.get("status", "")).strip().casefold()
    failed = status in FAILED_STATUSES or any(
        status.startswith(f"{failure}ed") for failure in FAILED_STATUSES
    )
    if failed:
        return False
    if CONFIRMATION_RE.search(_record_name(record)):
        return True
    return any(
        _normalize_field(key) in {"confirmation", "confirmation_run", "rerun", "repeat"}
        and value is True
        for key, value in record.items()
    )


def _ledger_records(evidence_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    evidence_dir = Path(evidence_dir)
    if not evidence_dir.is_dir():
        return records, paths
    for path in sorted(evidence_dir.rglob("experiments.jsonl")):
        paths.append(path.relative_to(evidence_dir).as_posix())
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for raw_line in lines:
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records, paths


def compute_ledger_scope(evidence_dir: Path) -> dict[str, Any]:
    """Return deterministic experimental coverage from ``experiments.jsonl``.

    Malformed/non-object rows are ignored. Counts describe observed ledger data,
    not values inferred from prose.
    """

    records, ledger_paths = _ledger_records(Path(evidence_dir))
    seeds: set[object] = set()
    gpu_types: set[object] = set()
    benchmarks: set[object] = set()
    metrics: set[str] = set()

    for record in records:
        for path, raw_value in _leaf_values(record):
            if not path:
                continue
            field = _normalize_field(path[-1])
            parent = _normalize_field(path[-2]) if len(path) > 1 else ""
            value = _scope_value(raw_value)
            if value is None:
                continue
            if field in SEED_FIELDS:
                seeds.add(value)
                continue
            if field in GPU_FIELDS:
                gpu_types.add(value)
                continue
            if field in BENCHMARK_FIELDS:
                benchmarks.add(value)
                continue
            if field in METRIC_NAME_FIELDS and isinstance(value, str):
                metrics.add(_normalize_field(value))
                continue
            is_numeric = not isinstance(raw_value, bool) and isinstance(raw_value, (int, float))
            if (
                is_numeric
                and math.isfinite(float(raw_value))
                and field
                and field not in NON_METRIC_FIELDS
                and (len(path) == 1 or parent in METRIC_CONTAINER_FIELDS)
            ):
                metrics.add(field)

    distinct_seeds = _sorted_values(seeds)
    sorted_gpu_types = [str(value) for value in _sorted_values(gpu_types)]
    sorted_benchmarks = [str(value) for value in _sorted_values(benchmarks)]
    sorted_metrics = sorted(metric for metric in metrics if metric)
    return {
        "trial_count": len(records),
        "distinct_seeds": distinct_seeds,
        "seed_count": len(distinct_seeds),
        "gpu_types": sorted_gpu_types,
        "gpu_type_count": len(sorted_gpu_types),
        "benchmarks": sorted_benchmarks,
        "benchmark_count": len(sorted_benchmarks),
        "metrics": sorted_metrics,
        "metric_count": len(sorted_metrics),
        "confirmation_runs": sum(_is_successful_confirmation(record) for record in records),
        "ledger_paths": ledger_paths,
    }


def _dimension_key(raw_dimension: str) -> str:
    dimension = _normalize_field(raw_dimension)
    if dimension in {"benchmark", "benchmarks", "dataset", "datasets", "task", "tasks", "domain", "domains"}:
        return "benchmark_count"
    if dimension in {"metric", "metrics"}:
        return "metric_count"
    if dimension in {"seed", "seeds"}:
        return "seed_count"
    if dimension in {"run", "runs", "trial", "trials"}:
        return "trial_count"
    return "gpu_type_count"


def _scope_requirements(sentence: str) -> dict[str, float]:
    requirements: dict[str, float] = {}
    for match in COUNTED_SCOPE_RE.finditer(sentence):
        key = _dimension_key(match.group("dimension"))
        requirements[key] = max(requirements.get(key, 0), int(match.group("count")))
    for match in QUALIFIED_SCOPE_RE.finditer(sentence):
        key = _dimension_key(match.group("dimension"))
        quantifier = _normalize_field(match.group("quantifier"))
        required = math.inf if quantifier in {"all", "every"} else 2
        requirements[key] = max(requirements.get(key, 0), required)
    for match in BARE_SCOPE_RE.finditer(sentence):
        key = _dimension_key(match.group("dimension"))
        requirements[key] = max(requirements.get(key, 0), 2)

    if not requirements and re.search(
        r"\b(?:generaliz(?:e[sd]?|able|ation)|broadly\s+(?:applicable|effective)|universal(?:ly)?)\b",
        sentence,
        re.I,
    ):
        requirements["benchmark_count"] = 2
    if not requirements and re.search(r"\bconsistently\s+(?:outperform|improv|perform)", sentence, re.I):
        requirements["seed_count"] = 2
    return requirements


def _sentences(parsed_paper: dict[str, Any]) -> list[tuple[str, int]]:
    sentences: list[tuple[str, int]] = []
    for line_number, line in enumerate(paper_text(parsed_paper).splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "|" in stripped:
            continue
        sentences.extend(
            (match.group(0).strip(), line_number)
            for match in re.finditer(r"[^.!?]+[.!?]?", stripped)
            if match.group(0).strip()
        )
    return sentences


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


def _coverage_text(scope: dict[str, Any]) -> str:
    seeds = ", ".join(str(value) for value in scope["distinct_seeds"]) or "none stated"
    gpu_types = ", ".join(scope["gpu_types"]) or "none stated"
    benchmarks = ", ".join(scope["benchmarks"]) or "none stated"
    metrics = ", ".join(scope["metrics"]) or "none stated"
    return (
        f"{_plural(scope['trial_count'], 'trial')}; "
        f"{_plural(scope['seed_count'], 'distinct seed')} ({seeds}); "
        f"GPU types: {gpu_types}; "
        f"{_plural(scope['benchmark_count'], 'benchmark')} ({benchmarks}); "
        f"{_plural(scope['metric_count'], 'metric')} ({metrics}); "
        f"{_plural(scope['confirmation_runs'], 'confirmation run')}"
    )


def scope_weaknesses(
    parsed_paper: dict[str, Any], evidence_dir: Path
) -> list[dict[str, Any]]:
    """Return scope-limit Weaknesses for claims broader than ledger coverage."""

    scope = compute_ledger_scope(Path(evidence_dir))
    if scope["trial_count"] == 0:
        return []

    weaknesses: list[dict[str, Any]] = []
    for sentence, line_number in _sentences(parsed_paper):
        if (
            not GENERALIZED_CLAIM_RE.search(sentence)
            or NON_ASSERTION_RE.search(sentence)
            or NEGATED_SCOPE_RE.search(sentence)
        ):
            continue
        requirements = _scope_requirements(sentence)
        if not requirements or not any(
            required > int(scope.get(dimension, 0))
            for dimension, required in requirements.items()
        ):
            continue
        weaknesses.append(
            {
                "section": "Weaknesses",
                "stance": "criticism",
                "family": "scope",
                "text": (
                    f"Scope limitation — the generalized claim at paper line {line_number} "
                    f"exceeds the supplied ledger coverage: {_coverage_text(scope)}."
                ),
                "references": [f"paper:{line_number}"],
                "scope": scope,
            }
        )
    return weaknesses


def _finding_family(finding: dict[str, Any]) -> str | None:
    check = str(finding.get("check", "")).strip().casefold()
    subtype = str(finding.get("subtype", finding.get("family", ""))).strip().casefold()
    if check in FOLLOW_UP_ACTIONS:
        return check
    if subtype in FOLLOW_UP_ACTIONS:
        return subtype
    if check == "scientific-scaffolding" and "variance" in subtype:
        return "variance"
    return None


def _finding_references(finding: dict[str, Any]) -> list[str]:
    references: list[str] = []
    finding_id = finding.get("id")
    if isinstance(finding_id, str) and finding_id.strip():
        references.append(finding_id.strip())
    raw_references = finding.get("references")
    if isinstance(raw_references, (list, tuple)):
        references.extend(
            str(reference).strip()
            for reference in raw_references
            if str(reference).strip()
        )
    if references:
        return list(dict.fromkeys(references))
    location = finding.get("location")
    if isinstance(location, dict) and isinstance(location.get("line"), int):
        return [f"paper:{location['line']}"]
    if isinstance(location, str) and location.strip():
        return [location.strip()]
    return []


def follow_up_questions(findings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return one concrete, reference-preserving action per weakness family."""

    references_by_family: dict[str, list[str]] = {
        family: [] for family in FOLLOW_UP_ACTIONS
    }
    for finding in findings or []:
        family = _finding_family(finding)
        if family is None:
            continue
        references_by_family[family].extend(_finding_references(finding))

    questions: list[dict[str, Any]] = []
    for family, action in FOLLOW_UP_ACTIONS.items():
        references = list(dict.fromkeys(references_by_family[family]))
        if not references:
            continue
        rendered_references = ", ".join(references)
        questions.append(
            {
                "section": "Questions for the Authors",
                "stance": "question",
                "family": family,
                "text": f"Concrete follow-up — {action} [{rendered_references}]",
                "references": references,
            }
        )
    return questions


def rigor_questions(
    parsed_paper: dict[str, Any],
    evidence_dir: Path | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic design, scope, and weakness-follow-up comments.

    ``evidence_dir`` and ``findings`` are optional so the pipeline's established
    ``rigor_questions(parsed_paper)`` call remains valid.
    """

    comments: list[dict[str, Any]] = []
    tables = parsed_paper.get("tables") or []
    variance_added = bool(tables) and not VARIANCE_RE.search(paper_text(parsed_paper))
    if variance_added:
        line = int(tables[0].get("line_start", 1))
        comments.append(
            {
                "section": "Questions for the Authors",
                "stance": "question",
                "family": "variance",
                "text": (
                    "Are the reported results from a single run, or averaged over multiple seeds? "
                    "No variance, standard deviation, confidence interval, or seed count is stated, "
                    "so the reliability of the comparison cannot be assessed. "
                    f"{FOLLOW_UP_ACTIONS['variance']}"
                ),
                "references": [f"paper:{line}"],
            }
        )

    if evidence_dir is not None:
        comments.extend(scope_weaknesses(parsed_paper, Path(evidence_dir)))

    for follow_up in follow_up_questions(findings):
        if variance_added and follow_up["family"] == "variance":
            variance_comment = next(
                comment for comment in comments if comment.get("family") == "variance"
            )
            additional_references = [
                reference
                for reference in follow_up["references"]
                if reference not in variance_comment["references"]
            ]
            variance_comment["references"].extend(additional_references)
            if additional_references:
                variance_comment["text"] += f" [{', '.join(additional_references)}]"
            continue
        comments.append(follow_up)
    return comments
