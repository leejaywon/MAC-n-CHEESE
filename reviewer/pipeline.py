"""Ordered six-stage Track 2 review pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .mechanical_checks import check_ledger_trace
from .parser import parse_markdown


STAGE_NAMES = (
    "S1 parse",
    "S2 claims",
    "S3 mech-check",
    "S4 verdicts",
    "S5 compose",
    "S6 freeze",
)


@dataclass
class ReviewState:
    """Mutable state passed through the ordered pipeline stages."""

    paper_path: Path
    evidence_dir: Path
    output_path: Path
    paper_hash: str = ""
    evidence_hashes: list[tuple[str, str]] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    parsed_paper: dict[str, object] = field(default_factory=dict)
    mechanical_checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    mechanical_findings: list[dict[str, Any]] = field(default_factory=list)
    review_markdown: str = ""


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_hashes(evidence_dir: Path) -> list[tuple[str, str]]:
    files = sorted(path for path in evidence_dir.rglob("*") if path.is_file())
    return [
        (path.relative_to(evidence_dir).as_posix(), _sha256_file(path))
        for path in files
    ]


def _mark_stage(state: ReviewState, name: str) -> ReviewState:
    """Record a no-op stage so stage order is observable and testable."""

    state.completed_stages.append(name)
    return state


def _parse_paper(state: ReviewState) -> ReviewState:
    state.parsed_paper = parse_markdown(state.paper_path)
    return _mark_stage(state, "S1 parse")


def _run_mechanical_checks(state: ReviewState) -> ReviewState:
    ledger_trace = check_ledger_trace(state.parsed_paper, state.evidence_dir)
    state.mechanical_checks["ledger-trace"] = ledger_trace
    state.mechanical_findings.extend(ledger_trace["findings"])
    return _mark_stage(state, "S3 mech-check")


def _freeze_inputs(state: ReviewState) -> ReviewState:
    # Hash once before S1 and verify again at S6 so a mid-run input mutation is
    # never silently accepted as part of the frozen review identity.
    if state.paper_hash != _sha256_file(state.paper_path):
        raise RuntimeError("paper changed while the review pipeline was running")
    if state.evidence_hashes != _evidence_hashes(state.evidence_dir):
        raise RuntimeError("evidence bundle changed while the review pipeline was running")
    return _mark_stage(state, "S6 freeze")


def _format_evidence_identity(state: ReviewState) -> str:
    if not state.evidence_hashes:
        return f"`{state.evidence_dir}` (empty directory)"
    entries = ", ".join(f"`{name}` (`sha256:{digest}`)" for name, digest in state.evidence_hashes)
    return f"`{state.evidence_dir}`: {entries}"


def _compose_scaffold_review(state: ReviewState) -> str:
    """Return the official review shape with honest milestone-limited content."""

    stage_trace = " -> ".join(STAGE_NAMES)
    section_count = len(state.parsed_paper.get("sections", []))
    table_count = len(state.parsed_paper.get("tables", []))
    number_count = len(state.parsed_paper.get("numeric_tokens", []))
    ledger_trace = state.mechanical_checks.get("ledger-trace", {})
    trace_count = len(ledger_trace.get("traces", []))
    matched_count = sum(1 for trace in ledger_trace.get("traces", []) if trace["matched"])
    finding_count = len(ledger_trace.get("findings", []))
    finding_lines = "\n".join(
        f"- ledger-trace at {finding['location']}: {finding['observed']}; expected {finding['expected']} "
        f"(evidence: `{finding['evidence_path']}`)."
        for finding in ledger_trace.get("findings", [])
    ) or "- No ledger-trace contradictions were proven."
    return f"""# Track 2 — ICML-Style Review

## Paper and Evidence Identity

- Review Agent name/version: No Free Lunch Review Agent / `m2a-ledger-trace`
- `review-agent.md` path/hash: Not frozen at M2a
- Paper version/hash: `{state.paper_path}` / `sha256:{state.paper_hash}`
- Evidence bundle reviewed: {_format_evidence_identity(state)}

## Summary

M2a ledger tracing completed. It found {section_count} sections, {table_count} tables, and {number_count} numeric tokens; {matched_count} of {trace_count} metric-labelled result values matched the experiment ledger, with {finding_count} ledger finding(s). Broader claim analysis is not performed at this milestone.

## Strengths

- {matched_count} metric-labelled result value(s) have direct experiment-ledger support.

## Weaknesses

{finding_lines}

## Questions for the Authors

- None generated at M2a; question generation is deferred to S4/S5.

## Scores

- Soundness: Not scored — M2a supplies ledger findings, but S4 claim verdicts are not implemented yet.
- Presentation: Not scored — S1 records structure but M2a does not yet evaluate template compliance.
- Contribution: Not scored — S2 does not yet extract claims, so contribution evidence is unavailable.
- Overall recommendation: Not scored — M2a findings are not yet grounded into claim verdicts.
- Confidence: Not scored — no complete claim set is evaluated for verifiability at M2a.

## Ethics and Limitations

This M2a output must not be treated as a complete substantive review. It checks direct numeric ledger traceability only and performs no citation, injection, ethics, arithmetic, or evidence-quality checks.

## Evidence Trace

- Pipeline execution: `{stage_trace}`.
- Frozen paper input: `{state.paper_path}` (`sha256:{state.paper_hash}`).
- S1 parse inventory: {section_count} sections, {table_count} tables, {number_count} numeric tokens with source locations.
- S3 ledger-trace: {matched_count}/{trace_count} metric-labelled values matched; {finding_count} finding(s), each with paper location and evidence path.
- No central paper claims were extracted or evaluated in M2a.
"""


class ReviewPipeline:
    """Execute the S1-S6 walking skeleton in the specified order."""

    def __init__(self) -> None:
        self._stages: tuple[Callable[[ReviewState], ReviewState], ...] = (
            _parse_paper,
            lambda state: _mark_stage(state, "S2 claims"),
            _run_mechanical_checks,
            lambda state: _mark_stage(state, "S4 verdicts"),
            self._compose,
            _freeze_inputs,
        )

    @staticmethod
    def _compose(state: ReviewState) -> ReviewState:
        state.review_markdown = _compose_scaffold_review(state)
        return _mark_stage(state, "S5 compose")

    def run(self, paper_path: Path, evidence_dir: Path, output_path: Path) -> ReviewState:
        paper_path = paper_path.expanduser().resolve()
        evidence_dir = evidence_dir.expanduser().resolve()
        output_path = output_path.expanduser().resolve()

        if not paper_path.is_file():
            raise FileNotFoundError(f"paper is not a file: {paper_path}")
        if not evidence_dir.is_dir():
            raise NotADirectoryError(f"evidence directory does not exist: {evidence_dir}")
        if output_path == paper_path:
            raise ValueError("output path must differ from the paper path")

        state = ReviewState(
            paper_path,
            evidence_dir,
            output_path,
            paper_hash=_sha256_file(paper_path),
            evidence_hashes=_evidence_hashes(evidence_dir),
        )
        for stage in self._stages:
            state = stage(state)

        if tuple(state.completed_stages) != STAGE_NAMES:
            raise RuntimeError(f"pipeline stage order mismatch: {state.completed_stages}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(state.review_markdown, encoding="utf-8")
        return state


def run_pipeline(paper_path: Path, evidence_dir: Path, output_path: Path) -> ReviewState:
    """Convenience entry point for callers embedding the reviewer package."""

    return ReviewPipeline().run(paper_path, evidence_dir, output_path)
