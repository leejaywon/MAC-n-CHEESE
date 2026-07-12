#!/usr/bin/env python3
"""Evaluate mechanical flaw detection without modifying frozen answer data.

Stdout is deliberately one floating-point score for Ralph-loop consumption.
Diagnostics and W&B SDK output go to stderr.  A finding identifies a flaw only
when both its check family and paper line match the claim-anchored answer key.
Multiple findings at one injected passage count as one detection, not extra
false positives, because checks can independently prove the same corruption.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reviewer import run_pipeline  # noqa: E402


REQUIRED_REVIEW_MARKERS = (
    "## Scores",
    "## Summary",
    "## Strengths",
    "## Weaknesses",
    "## Questions for the Authors",
    "- Soundness:",
    "- Presentation:",
    "- Contribution:",
    "- Overall recommendation:",
    "- Confidence:",
    "## Ethics and Limitations",
    "## Evidence Trace",
    "## Comment",
)


def _line(location: object) -> int | None:
    if isinstance(location, dict) and isinstance(location.get("line"), int):
        return location["line"]
    if isinstance(location, str):
        suffix = location.rsplit(":", 1)[-1]
        return int(suffix) if suffix.isdigit() else None
    return None


def _load_key() -> dict[str, Any]:
    path = EVAL_DIR / "answer_key.json"
    if not path.is_file():
        raise FileNotFoundError("eval/answer_key.json is missing; run eval/make_eval_set.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = data.get("papers")
    if not isinstance(papers, dict) or not papers:
        raise ValueError("answer key must contain a non-empty papers object")
    return papers


def _evaluate_external() -> dict[str, float | int]:
    """Robustness smoke test on real papers in eval/external/ (no answer key).

    Purpose is a generalization + crash signal, never a detection score. Each
    paper runs through the full pipeline; a crash is RECORDED, not raised, so one
    malformed external paper can never abort the loop's backpressure run. Evidence
    is a sibling `eval/external/<stem>/` dir when present, else an empty dir —
    real published papers rarely ship this event's experiments.jsonl ledger.
    """

    external_dir = EVAL_DIR / "external"
    papers = sorted(external_dir.glob("*.md")) if external_dir.is_dir() else []
    if not papers:
        return {
            "external_paper_count": 0,
            "external_no_crash_rate": 1.0,
            "external_completeness": 1.0,
            "external_finding_total": 0,
        }
    no_crash = 0
    completeness_values: list[float] = []
    finding_total = 0
    with tempfile.TemporaryDirectory(prefix="ralphthon-external-") as out_dir, \
            tempfile.TemporaryDirectory(prefix="ralphthon-external-ev-") as empty_evidence:
        for paper in papers:
            sibling = external_dir / paper.stem
            evidence_dir = sibling if sibling.is_dir() else Path(empty_evidence)
            try:
                state = run_pipeline(paper, evidence_dir, Path(out_dir) / paper.name)
            except Exception as error:  # noqa: BLE001 — a crash is the signal, not a stop
                print(f"external: {paper.name} crashed: {error!r}", file=sys.stderr)
                completeness_values.append(0.0)
                continue
            no_crash += 1
            completeness_values.append(
                sum(marker in state.review_markdown for marker in REQUIRED_REVIEW_MARKERS)
                / len(REQUIRED_REVIEW_MARKERS)
            )
            finding_total += len(state.mechanical_findings)
    return {
        "external_paper_count": len(papers),
        "external_no_crash_rate": no_crash / len(papers),
        "external_completeness": sum(completeness_values) / len(completeness_values),
        "external_finding_total": finding_total,
    }


def _evaluate() -> dict[str, float | int]:
    papers = _load_key()
    expected_total = 0
    detected_total = 0
    identified_total = 0
    false_positives = 0
    completeness_values: list[float] = []
    states: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="ralphthon-eval-") as output_dir:
        for paper_name, case in sorted(papers.items()):
            paper_path = EVAL_DIR / "papers" / paper_name
            evidence_dir = EVAL_DIR / str(case["evidence_dir"])
            state = run_pipeline(paper_path, evidence_dir, Path(output_dir) / paper_name)
            states[paper_name] = state
            findings = list(state.mechanical_findings)
            flaws = list(case.get("flaws", []))
            expected_total += len(flaws)
            matched_finding_indexes: set[int] = set()

            for flaw in flaws:
                expected_checks = set(flaw.get("expected_checks", []))
                expected_line = _line(flaw.get("location"))
                check_matches = [
                    index
                    for index, finding in enumerate(findings)
                    if finding.get("check") in expected_checks
                ]
                if check_matches:
                    identified_total += 1
                localized = [
                    index
                    for index in check_matches
                    if _line(findings[index].get("location")) == expected_line
                ]
                if localized:
                    detected_total += 1
                    # All accepted check families at this injected line prove
                    # the same flaw and therefore are not duplicate FPs.
                    matched_finding_indexes.update(localized)

            false_positives += sum(
                1 for index in range(len(findings)) if index not in matched_finding_indexes
            )
            completeness_values.append(
                sum(marker in state.review_markdown for marker in REQUIRED_REVIEW_MARKERS)
                / len(REQUIRED_REVIEW_MARKERS)
            )

    denominator = expected_total or 1
    identification_rate = identified_total / denominator
    localization_rate = detected_total / denominator
    detection_rate = localization_rate
    false_positive_rate = false_positives / max(len(papers), 1)
    completeness = sum(completeness_values) / len(completeness_values)
    injection_pairs = [
        (paper_name, str(case["injection_twin_of"]))
        for paper_name, case in papers.items()
        if case.get("injection_twin_of")
    ]
    invariant_pairs = sum(
        states[attack].scores == states[clean].scores for attack, clean in injection_pairs
    )
    injection_resistance = invariant_pairs / len(injection_pairs) if injection_pairs else 1.0
    score = detection_rate - 0.5 * false_positive_rate + 0.1 * completeness
    external = _evaluate_external()
    return {
        "score": score,
        "detection_rate": detection_rate,
        "identification_rate": identification_rate,
        "localization_rate": localization_rate,
        "false_positive_count": false_positives,
        "false_positive_rate": false_positive_rate,
        "completeness": completeness,
        "paper_count": len(papers),
        "expected_flaw_count": expected_total,
        "injection_pair_count": len(injection_pairs),
        "injection_resistance": injection_resistance,
        **external,
    }


def _log_offline(metrics: dict[str, float | int]) -> None:
    # Force offline at the call site even if a user's shell has another W&B
    # default. The evaluation never syncs or asks for credentials.
    os.environ["WANDB_MODE"] = "offline"
    os.environ.setdefault("WANDB_SILENT", "true")
    # Keep every SDK path inside the writable workspace. Disabling machine
    # statistics avoids a wandb-core macOS netstat parser crash under the
    # sandbox; reviewer metrics are still persisted in the offline run.
    wandb_root = EVAL_DIR / "wandb"
    os.environ["WANDB_CACHE_DIR"] = str(wandb_root / "cache")
    os.environ["WANDB_CONFIG_DIR"] = str(wandb_root / "config")
    os.environ["WANDB_DATA_DIR"] = str(wandb_root / "data")
    import wandb

    log_dir = wandb_root / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run = wandb.init(
        project="ralphthon-reviewer-eval",
        job_type="reviewer-eval",
        mode="offline",
        dir=str(log_dir),
        settings=wandb.Settings(
            console="off",
            silent=True,
            x_disable_stats=True,
            x_disable_machine_info=True,
        ),
        config={"answer_key_version": 1, "score_formula": "detection-0.5*fp+0.1*completeness"},
    )
    if run is None:
        raise RuntimeError("W&B offline run did not initialize")
    run.log(metrics)
    run.finish()


def main() -> int:
    metrics = _evaluate()
    _log_offline(metrics)
    print(
        "eval details: "
        f"papers={metrics['paper_count']} flaws={metrics['expected_flaw_count']} "
        f"identification={metrics['identification_rate']:.3f} "
        f"localization={metrics['localization_rate']:.3f} "
        f"fp={metrics['false_positive_count']} completeness={metrics['completeness']:.3f}",
        f"injection_resistance={metrics['injection_resistance']:.3f}",
        f"external(papers={metrics['external_paper_count']} "
        f"no_crash={metrics['external_no_crash_rate']:.3f} "
        f"completeness={metrics['external_completeness']:.3f} "
        f"findings={metrics['external_finding_total']})",
        file=sys.stderr,
    )
    print(f"{metrics['score']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
