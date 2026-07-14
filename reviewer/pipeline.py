"""Ordered six-stage scientific paper review pipeline."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .baseline_fairness import check_baseline_fairness
from .citation_existence import check_citation_existence
from .claims import extract_claims, label_verdicts
from .composer import (
    SCORE_SCALES,
    apply_scientific_scores,
    calibrate_scores,
    draft_comments,
    ground_comments,
)
from .document import PreparedPaper, SourceIdentity, prepare_paper
from .injection_scan import check_injection_scan, scan_and_sanitize
from .manuscript_integrity import check_cross_references, check_manuscript_artifacts
from .mechanical_checks import check_arithmetic, check_internal_consistency, check_ledger_trace
from .model_critique import (
    committee_review as _committee_review,
    compute_judgment_identity,
    generate_search_queries,
)
from .judgment_review import (
    apply_integrity_caps,
    extract_paper_title,
    run_panel_review,
)
from .negative_evidence import check_negative_evidence
from .parser import paper_text
from .promised_results import check_promised_results
from .novelty_positioning import check_novelty_positioning
from .parser import parse_markdown
from .positioning import check_positioning
from .prose_hygiene import sanitize as _sanitize_prose
from .review_schema import ScientificJudgment
from .rigor_checklist import rigor_checklist_questions
from .scientific_review import build_evidence_packet, validate_judgment
from .scientific_scaffolding import rigor_questions
from .self_review_audit import check_self_review_consistency
from .template_compliance import check_template_compliance
from .to_markdown import PDF_VISIBILITY_POLICY


STAGE_NAMES = (
    "S1 parse",
    "S2 claims",
    "S3 mech-check",
    "S4 verdicts",
    "S5 compose",
    "S6 freeze",
)

ROOT = Path(__file__).resolve().parents[1]
REVIEW_AGENT_PATH = ROOT / "specs" / "review-agent-spec.md"
FREEZE_ID_RE = re.compile(r"^- Frozen review identity: `(?P<value>sha256:[0-9a-f]{64})`\.$", re.M)
VERDICT_DIGEST_RE = re.compile(r"^- Verdict labels digest: `(?P<value>sha256:[0-9a-f]{64})`\.$", re.M)


@dataclass
class ReviewState:
    """Mutable state passed through the ordered pipeline stages."""

    paper_path: Path
    evidence_dir: Path
    output_path: Path
    agent_version: str = ""
    review_agent_path: Path = REVIEW_AGENT_PATH
    review_agent_hash: str = ""
    paper_hash: str = ""
    prepared_paper: PreparedPaper | None = None
    original_identity: SourceIdentity | None = None
    derived_identity: SourceIdentity | None = None
    page_count: int | None = None
    converter: str | None = None
    sanitation_traces: list[dict[str, object]] = field(default_factory=list)
    injection_findings: list[dict[str, object]] = field(default_factory=list)
    evidence_hashes: list[tuple[str, str]] = field(default_factory=list)
    frozen_at: str = ""
    review_identity: str = ""
    verdict_digest: str = ""
    external_snapshot_digest: str = ""
    completed_stages: list[str] = field(default_factory=list)
    parsed_paper: dict[str, object] = field(default_factory=dict)
    claims: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    finding_records: list[dict[str, Any]] = field(default_factory=list)
    mechanical_checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    mechanical_findings: list[dict[str, Any]] = field(default_factory=list)
    draft_comments: list[dict[str, Any]] = field(default_factory=list)
    grounded_comments: list[dict[str, Any]] = field(default_factory=list)
    grounding_audit: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    review_markdown: str = ""
    mode: str = "best"
    judgment: dict[str, Any] = field(default_factory=dict)
    scientific_judgment: ScientificJudgment | None = None
    judgment_identity: str = ""
    judgment_error: str = ""
    committee_provenance: dict[str, Any] = field(default_factory=dict)
    # Judgment-first review body (panel/area-chair markdown). When present it
    # becomes the review output and the deterministic audit ships as a sidecar.
    review_document: str = ""
    # Full panel member reviews, rendered only into the audit sidecar.
    panel_reviews: list[dict[str, Any]] = field(default_factory=list)
    event_format: bool = True


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


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _content_identity(identity: SourceIdentity) -> dict[str, object]:
    """Freeze source content/provenance without binding identity to a local path."""

    value = asdict(identity)
    value.pop("path", None)
    return value


def _agent_version() -> str:
    """Hash every executable reviewer source so the runtime identity is Git-independent."""

    source_paths = [ROOT / "run_review.py", ROOT / "requirements.txt", REVIEW_AGENT_PATH]
    source_paths.extend(sorted((ROOT / "reviewer").glob("*.py")))
    manifest = [
        (path.relative_to(ROOT).as_posix(), _sha256_file(path))
        for path in source_paths
    ]
    return _canonical_digest(manifest)


def _previous_freeze(path: Path) -> tuple[str, str] | None:
    """Read the machine-checkable freeze markers from an earlier review.

    An output without freeze markers may be replaced once; once a review with a
    frozen identity is written, the output path is bound to that identity.
    """

    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    identity = FREEZE_ID_RE.search(text)
    verdicts = VERDICT_DIGEST_RE.search(text)
    if identity is None and verdicts is None:
        return None
    if identity is None or verdicts is None:
        raise RuntimeError(f"incomplete freeze markers in existing output: {path}")
    return identity.group("value"), verdicts.group("value")


def _mark_stage(state: ReviewState, name: str) -> ReviewState:
    """Record a no-op stage so stage order is observable and testable."""

    state.completed_stages.append(name)
    return state


def _parse_paper(state: ReviewState) -> ReviewState:
    if state.prepared_paper is None:
        raise RuntimeError("paper was not prepared before S1")
    state.parsed_paper = parse_markdown(
        state.paper_path,
        text=state.prepared_paper.analysis_text,
    )
    return _mark_stage(state, "S1 parse")


def _detect_event_format(parsed_paper: dict[str, object], evidence_dir: Path) -> bool:
    """Is this an event-format submission with an evidence ledger, or an arbitrary peer paper?

    Event-specific checks (the Markdown template contract, baseline-fairness
    against a ledger) only make sense for THIS event's submission format.
    Applying them to an arbitrary peer paper manufactures false positives:
    wrong-template section penalties and demands for an experiments.jsonl ledger
    the peer never shipped. The strongest signal is the event's evidence
    contract — an experiments.jsonl ledger. A paper carrying both the Research
    Spec and Self-Review template sections also qualifies when evidence is absent.
    """

    if any(evidence_dir.rglob("experiments.jsonl")):
        return True
    titles = [str(section.get("title", "")).lower() for section in parsed_paper.get("sections", [])]
    has_spec = any("research spec" in title for title in titles)
    has_self_review = any("self-review" in title or "self review" in title for title in titles)
    return has_spec and has_self_review


def _run_mechanical_checks(state: ReviewState) -> ReviewState:
    state.event_format = _detect_event_format(state.parsed_paper, state.evidence_dir)
    injection_result = {
        "check": "injection-scan",
        "traces": state.sanitation_traces,
        "findings": state.injection_findings,
    }
    citation_check = check_citation_existence(state.parsed_paper)
    snapshot_fields = ("provider", "identifier", "status", "title", "url", "error")
    state.external_snapshot_digest = _canonical_digest(
        [
            {key: trace.get(key) for key in snapshot_fields if key in trace}
            for trace in citation_check.get("traces", [])
        ]
    )
    checks = (
        check_ledger_trace(state.parsed_paper, state.evidence_dir, state.event_format),
        check_internal_consistency(state.parsed_paper),
        check_arithmetic(state.parsed_paper),
        check_cross_references(state.parsed_paper),
        check_manuscript_artifacts(state.parsed_paper),
        # Annotation-only (zero findings ever): promissory statements whose
        # subject never reappears, for the judgment layer to weigh in context.
        check_promised_results(state.parsed_paper),
        check_baseline_fairness(state.parsed_paper, state.evidence_dir),
        check_negative_evidence(state.parsed_paper, state.evidence_dir),
        citation_check,
        check_template_compliance(state.parsed_paper, state.event_format),
        check_injection_scan(state.parsed_paper, precomputed=injection_result),
    )
    for result in checks:
        state.mechanical_checks[result["check"]] = result
        state.mechanical_findings.extend(result["findings"])
    # Derived integrity critique: does the authors' Self-Review checklist honestly
    # reflect the findings above? Stored for rendering and the trace, but
    # deliberately NOT added to mechanical_findings so it stays out of the
    # detection/false-positive eval accounting (it is a meta-critique, not a
    # primary flaw detection).
    self_review = check_self_review_consistency(state.parsed_paper, state.mechanical_findings)
    state.mechanical_checks[self_review["check"]] = self_review
    # Scientific positioning (related-work / novelty / SOTA) is likewise a derived
    # ICML-style critique, not a primary flaw detection: stored for rendering,
    # the Contribution score, and the trace, but kept OUT of mechanical_findings
    # so it never enters the detection/false-positive eval accounting.
    positioning = check_positioning(state.parsed_paper)
    state.mechanical_checks[positioning["check"]] = positioning
    return _mark_stage(state, "S3 mech-check")


def _extract_claims(state: ReviewState) -> ReviewState:
    state.claims = extract_claims(state.parsed_paper)
    return _mark_stage(state, "S2 claims")


def _label_verdicts(state: ReviewState) -> ReviewState:
    state.verdicts, state.finding_records = label_verdicts(
        state.claims, state.mechanical_checks, state.mechanical_findings
    )
    return _mark_stage(state, "S4 verdicts")


def _source_identity_matches(identity: SourceIdentity) -> bool:
    path = Path(identity.path)
    return (
        path.is_file()
        and path.stat().st_size == identity.byte_length
        and _sha256_file(path) == identity.sha256
    )


def _validate_prepared_paper(requested_path: Path, prepared: PreparedPaper) -> None:
    original_path = Path(prepared.original.path)
    markdown_path = Path(prepared.markdown.path)
    if requested_path not in {original_path, markdown_path}:
        raise ValueError("prepared paper does not describe the requested paper path")
    if prepared.markdown.media_type != "text/markdown":
        raise ValueError("prepared paper must expose a Markdown analysis identity")
    if markdown_path.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("prepared Markdown identity has an unsupported path suffix")
    if not _source_identity_matches(prepared.original):
        raise ValueError("prepared original identity does not match the source file")
    if not _source_identity_matches(prepared.markdown):
        raise ValueError("prepared Markdown identity does not match the derived file")
    try:
        markdown_text = markdown_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"paper is not valid UTF-8 Markdown: {markdown_path}") from error
    if markdown_text != prepared.raw_text:
        raise ValueError("prepared raw text does not match the Markdown source")

    if prepared.original.media_type == "text/markdown":
        if prepared.original != prepared.markdown or prepared.converter is not None:
            raise ValueError("Markdown preparation must use one source identity and no converter")
    elif prepared.original.media_type == "application/pdf":
        import pymupdf

        with pymupdf.open(original_path) as document:
            if document.page_count != prepared.original.page_count:
                raise ValueError("prepared PDF page count does not match the source")
        if prepared.converter is None:
            raise ValueError("prepared PDF is missing converter provenance")
    else:
        raise ValueError(f"unsupported original media type: {prepared.original.media_type!r}")

    analysis_text, traces, findings = scan_and_sanitize(
        prepared.raw_text,
        original_path.name,
    )
    trace_count = len(traces)
    finding_count = len(findings)
    text_traces = (
        prepared.sanitation_traces[-trace_count:] if trace_count else ()
    )
    text_findings = (
        prepared.injection_findings[-finding_count:] if finding_count else ()
    )
    visibility_traces = (
        prepared.sanitation_traces[:-trace_count]
        if trace_count
        else prepared.sanitation_traces
    )
    visibility_findings = (
        prepared.injection_findings[:-finding_count]
        if finding_count
        else prepared.injection_findings
    )
    if (
        analysis_text != prepared.analysis_text
        or traces != text_traces
        or findings != text_findings
    ):
        raise ValueError("prepared sanitation records do not match the Markdown source")
    if prepared.original.media_type == "text/markdown":
        if visibility_traces or visibility_findings:
            raise ValueError("Markdown preparation contains PDF visibility records")
    elif (
        len(visibility_traces) != len(visibility_findings)
        or any(
            trace.get("policy") != PDF_VISIBILITY_POLICY
            or "page" not in trace.get("location", {})
            for trace in visibility_traces
        )
        or any(
            finding.get("check") != "injection-scan"
            or finding.get("evidence_path") != original_path.name
            or "page" not in finding.get("location", {})
            for finding in visibility_findings
        )
    ):
        raise ValueError("prepared PDF visibility records are malformed")


def _freeze_inputs(state: ReviewState) -> ReviewState:
    # Hash once before S1 and verify again at S6 so a mid-run input mutation is
    # never silently accepted as part of the frozen review identity.
    prepared = state.prepared_paper
    if prepared is None:
        raise RuntimeError("paper preparation record is missing at freeze")
    if (
        state.original_identity != prepared.original
        or state.derived_identity != prepared.markdown
        or state.page_count != prepared.original.page_count
        or state.converter != prepared.converter
        or state.sanitation_traces != list(prepared.sanitation_traces)
        or state.injection_findings != list(prepared.injection_findings)
        or not _source_identity_matches(prepared.original)
        or not _source_identity_matches(prepared.markdown)
        or state.paper_hash != prepared.markdown.sha256
    ):
        raise RuntimeError("paper changed while the review pipeline was running")
    if state.evidence_hashes != _evidence_hashes(state.evidence_dir):
        raise RuntimeError("evidence bundle changed while the review pipeline was running")
    if state.review_agent_hash != _sha256_file(state.review_agent_path):
        raise RuntimeError("review-agent spec changed while the review pipeline was running")
    if state.agent_version != _agent_version():
        raise RuntimeError("reviewer source changed while the review pipeline was running")

    state.review_identity = _canonical_digest(
        {
            "schema_version": 2,
            "agent_version": state.agent_version,
            "review_agent_hash": state.review_agent_hash,
            "paper_hash": state.paper_hash,
            "original_identity": _content_identity(prepared.original),
            "derived_identity": _content_identity(prepared.markdown),
            "converter": prepared.converter,
            "evidence_hashes": state.evidence_hashes,
            "external_snapshot_digest": state.external_snapshot_digest,
        }
    )
    # The task's determinism contract is specifically about S4 labels. Keep a
    # narrow digest so prose/timestamp changes cannot masquerade as label drift.
    state.verdict_digest = _canonical_digest(
        [
            {"claim_id": verdict["claim_id"], "label": verdict["label"]}
            for verdict in state.verdicts
        ]
    )
    previous = _previous_freeze(state.output_path)
    if previous is not None:
        previous_identity, previous_verdicts = previous
        if previous_identity != state.review_identity:
            raise RuntimeError(
                "output path is already frozen to a different agent or input identity"
            )
        if previous_verdicts != state.verdict_digest:
            raise RuntimeError(
                "nondeterministic verdict labels detected for identical frozen inputs"
            )
    state.frozen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return _mark_stage(state, "S6 freeze")


def _scrub_path(path: object) -> str:
    """Basename only — never leak absolute paths or usernames into review output.

    A review may be sent to authors or posted double-blind; an absolute path like
    ``/Users/<name>/.../paper.pdf`` discloses the reviewer's identity and local
    environment. We keep the file's basename (enough to identify which artifact a
    hash refers to) and drop every parent directory. The ``sha256`` printed
    alongside remains the anonymized, machine-independent integrity anchor.
    """

    text = str(path or "").strip()
    if not text:
        return "(unnamed)"
    return Path(text.replace("\\", "/")).name or text


def _format_evidence_identity(state: ReviewState) -> str:
    if not state.evidence_hashes:
        return "none (no evidence bundle supplied)"
    entries = ", ".join(f"`{name}` (`sha256:{digest}`)" for name, digest in state.evidence_hashes)
    return f"`{_scrub_path(state.evidence_dir)}`: {entries}"


def _format_source_identity(label: str, identity: SourceIdentity) -> str:
    return (
        f"- {label}: `{_scrub_path(identity.path)}` / `{identity.media_type}` / "
        f"`sha256:{identity.sha256}` / `{identity.byte_length}` bytes"
    )


# Committee-authored weakness prose about typographic defects (broken \ref text
# etc.) — recognized so it can never be promoted to the closing "next step".
_TYPOGRAPHIC_REMARK_RE = re.compile(
    r"(?i)\bcross-refer|\bgarbled\b|\btypograph|minor presentation remark"
)

CONTRIBUTION_RE = re.compile(
    r"\b(?:our\s+(?:main\s+|key\s+|primary\s+)?contribution|we\s+(?:propose|present|introduce|develop|"
    r"show|demonstrate)|in\s+this\s+(?:paper|work)|this\s+(?:paper|work)\s+(?:proposes|presents|introduces))\b",
    re.I,
)


def _paper_title(parsed_paper: dict[str, object]) -> str:
    sections = parsed_paper.get("sections", [])
    headed = [section for section in sections if section.get("heading_line")]
    if not headed:
        return ""
    top_level = min(section["level"] for section in headed)
    for section in headed:
        if section["level"] == top_level:
            return re.sub(r"[*_`]", "", str(section.get("title", ""))).strip()
    return ""


def _contribution_sentence(claims: list[dict[str, Any]]) -> str:
    """The paper's own stated contribution, for a real (not audit-log) summary."""

    for claim in claims:
        text = re.sub(r"\s+", " ", str(claim.get("text", "")).strip())
        if CONTRIBUTION_RE.search(text) and 20 <= len(text) <= 400:
            return text if text.endswith((".", "!", "?")) else text + "."
    return ""


def _grounding_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _scientific_comment_text(comment: object) -> str:
    text = _sanitize_prose(
        re.sub(r"\s+", " ", str(getattr(comment, "text", "")).strip())
    )
    grounding = ", ".join(_grounding_ids(getattr(comment, "grounding", ())))
    return f"{text} [{grounding}]" if grounding else text


def _scientific_question_text(question: object) -> str:
    text = _scientific_comment_text(question)
    assessment = _sanitize_prose(
        re.sub(r"\s+", " ", str(getattr(question, "assessment_if_resolved", "")).strip())
    )
    return (
        f"{text} Assessment if resolved: {assessment}"
        if assessment
        else text
    )


def _trace_scalar(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().replace("`", "'")


def _committee_trace(state: ReviewState) -> str:
    """Render compact four-call provenance only when best mode attempted it."""

    provenance = state.committee_provenance
    if not provenance and not state.judgment_error and not state.judgment_identity:
        return ""
    lines: list[str] = []
    if state.judgment_identity:
        lines.append(f"- Scientific judgment identity: `{state.judgment_identity}`.")
    committee_identity = provenance.get("committee_identity") if isinstance(provenance, dict) else None
    if committee_identity and committee_identity != state.judgment_identity:
        lines.append(f"- Scientific committee identity: `{committee_identity}`.")
    if isinstance(provenance, dict) and provenance:
        rubric = _trace_scalar(provenance.get("rubric_version")) or "unknown"
        workers = _trace_scalar(provenance.get("workers")) or "unknown"
        timeout = _trace_scalar(provenance.get("timeout_seconds")) or "unknown"
        lines.append(
            f"- Scientific committee configuration: rubric=`{rubric}`, "
            f"workers={workers}, timeout={timeout}s."
        )

    calls: list[dict[str, Any]] = []
    raw_specialists = provenance.get("specialists", []) if isinstance(provenance, dict) else []
    if isinstance(raw_specialists, list):
        calls.extend(call for call in raw_specialists if isinstance(call, dict))
    raw_meta = provenance.get("meta") if isinstance(provenance, dict) else None
    if isinstance(raw_meta, dict):
        calls.append(raw_meta)
    for call in calls:
        role = _trace_scalar(call.get("role")) or "unknown"
        model = _trace_scalar(call.get("model")) or "unknown"
        prompt_hash = _trace_scalar(call.get("prompt_sha256")) or "unavailable"
        response_hash = _trace_scalar(call.get("response_sha256")) or "unavailable"
        status = "ok" if call.get("ok") else "failed"
        error = _trace_scalar(call.get("error"))
        suffix = f", error={error}" if error else ""
        lines.append(
            f"- Scientific committee `{role}`: model=`{model}`, "
            f"prompt=`sha256:{prompt_hash}`, response=`sha256:{response_hash}`, "
            f"status={status}{suffix}."
        )
    if state.judgment_error:
        lines.append(
            "- Scientific committee fallback: deterministic review and scores "
            f"retained ({_trace_scalar(state.judgment_error)})."
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _review_method_line(state: ReviewState) -> str:
    """State plainly whether the scientific committee contributed to this review.

    When the committee did not run — ``--deterministic``, no API key, or a committee
    failure — the output must not read like a full committee review. This line makes
    the scope explicit so a reader knows every score and comment below then comes
    only from the deterministic mechanical audit.
    """

    if state.scientific_judgment is not None:
        return "- Review method: deterministic evidence audit + scientific committee."
    audit_note = (
        " Every score and comment below is from the deterministic mechanical checks; "
        "no scientific-committee judgment is included."
    )
    if state.mode != "best":
        return (
            "- Review method: deterministic evidence audit only (`--deterministic`)."
            + audit_note
        )
    if not os.environ.get("OPENAI_API_KEY"):
        detail = "no model API key configured"
    else:
        detail = state.judgment_error or "committee unavailable"
    return (
        "- Review method: deterministic evidence audit only — the scientific committee "
        f"did not run ({detail})." + audit_note
    )


def _compose_review(state: ReviewState) -> str:
    """Return the official review shape after DRAFT and authoritative GROUND."""

    if state.original_identity is None or state.derived_identity is None:
        raise RuntimeError("source identities are missing from review state")
    stage_trace = " -> ".join(STAGE_NAMES)
    section_count = len(state.parsed_paper.get("sections", []))
    table_count = len(state.parsed_paper.get("tables", []))
    number_count = len(state.parsed_paper.get("numeric_tokens", []))
    ledger_trace = state.mechanical_checks.get("ledger-trace", {})
    trace_count = len(ledger_trace.get("traces", []))
    matched_count = sum(1 for trace in ledger_trace.get("traces", []) if trace["matched"])
    finding_count = len(state.mechanical_findings)
    internal = state.mechanical_checks.get("internal-consistency", {})
    arithmetic = state.mechanical_checks.get("arithmetic", {})
    baseline_fairness = state.mechanical_checks.get("baseline-fairness", {})
    negative_evidence = state.mechanical_checks.get("negative-evidence", {})
    citations = state.mechanical_checks.get("citation-existence", {})
    template = state.mechanical_checks.get("template-compliance", {})
    injection = state.mechanical_checks.get("injection-scan", {})
    self_review_audit = state.mechanical_checks.get("self-review-audit", {})
    positioning = state.mechanical_checks.get("positioning", {})
    positioning_signals = positioning.get("signals", {})
    finding_lines = "\n".join(
        f"- [{finding['id']}] {finding['check']} at {finding['location']}: {finding['observed']}; expected {finding['expected']} "
        f"(evidence: `{finding['evidence_path']}`)."
        for finding in state.finding_records
    ) or "- No mechanical contradictions were proven."
    verdict_by_claim = {verdict["claim_id"]: verdict for verdict in state.verdicts}
    label_counts = {
        label: sum(verdict["label"] == label for verdict in state.verdicts)
        for label in ("supported", "contradicted", "unverifiable")
    }
    def _trace_line(claim: dict[str, Any]) -> str:
        verdict = verdict_by_claim[claim["id"]]
        pointers = ", ".join(f"`{pointer}`" for pointer in verdict["evidence"]) or "none"
        return (
            f"- [{claim['id']}] **{verdict['label']}** — paper:{claim['location']['line']} — "
            f"{claim['text']} — {verdict['reason']} Evidence: {pointers}."
        )

    # The trace prioritizes what a reader needs — every verified (supported /
    # contradicted) claim and every substantive unverifiable claim (result /
    # arithmetic / hypothesis) — capped, then summarizes the remaining generic
    # prose as a count instead of dumping hundreds of lines.
    TRACE_CAP = 30
    verified = [
        claim for claim in state.claims
        if verdict_by_claim[claim["id"]]["label"] in {"supported", "contradicted"}
    ]
    substantive_unverifiable = [
        claim for claim in state.claims
        if verdict_by_claim[claim["id"]]["label"] == "unverifiable"
        and claim.get("type") in {"result", "arithmetic", "hypothesis"}
    ]
    shown = (verified + substantive_unverifiable)[:TRACE_CAP]
    omitted = len(state.claims) - len(shown)
    trace_body = "\n".join(_trace_line(claim) for claim in shown)
    if omitted > 0:
        trace_body += (
            f"\n- (+{omitted} further extracted claim(s) — mostly unverifiable prose — omitted here for "
            f"brevity; all are labelled in S2/S4 with source lines.)"
        )
    evidence_trace_lines = trace_body or "- No declarative claims were extracted."
    comments_by_section: dict[str, list[dict[str, Any]]] = {
        "Strengths": [],
        "Weaknesses": [],
        "Questions for the Authors": [],
    }
    for comment in state.grounded_comments:
        comments_by_section[comment["section"]].append(comment)
    # The self-review audit is a derived integrity critique; surface each
    # dishonest self-certification as an explicit, evidence-bound Weakness.
    for finding in state.mechanical_checks.get("self-review-audit", {}).get("findings", []):
        comments_by_section["Weaknesses"].append(
            {"text": f"Self-review integrity — {finding['observed']} (self-review line {finding['location']['line']})."}
        )
    # Scientific positioning: an unsituated novelty/SOTA claim is a proven
    # Originality/Significance defect (Weakness); a comparator-less superiority
    # claim on an otherwise-positioned paper is a fair Question.
    positioning_check = state.mechanical_checks.get("positioning", {})
    for finding in positioning_check.get("findings", []):
        comments_by_section["Weaknesses"].append(
            {"text": f"Positioning — {finding['observed']} (paper line {finding['location']['line']})."}
        )
    for question in positioning_check.get("questions", []):
        comments_by_section["Questions for the Authors"].append(question)
    # Deterministic scientific scaffolding: fair, model-free Questions that add
    # review substance on evidence-poor papers (self-suppresses on rigorous ones).
    for scaffold in rigor_questions(
        state.parsed_paper,
        state.evidence_dir,
        state.finding_records,
    ):
        section = str(scaffold.get("section", "Questions for the Authors"))
        if section not in comments_by_section:
            section = "Questions for the Authors"
        comments_by_section[section].append(scaffold)
    # ICML/NeurIPS reproducibility & limitations checklist: one consolidated
    # Question about missing items (code/data, hyperparameters, compute,
    # limitations, broader impact), self-suppressing on a thorough paper.
    for question in rigor_checklist_questions(state.parsed_paper):
        comments_by_section["Questions for the Authors"].append(question)

    # --- Substance shaping so the review reads like a review, not an audit log ---
    pos_signals = positioning_check.get("signals", {})
    citation_count = pos_signals.get("citation_count", 0)
    result_claims = [claim for claim in state.claims if claim.get("type") in {"result", "arithmetic"}]

    # Grounded Strengths from what the audit actually established (never fabricated).
    if not comments_by_section["Strengths"]:
        if pos_signals.get("has_related_work_section") or citation_count > 0:
            comments_by_section["Strengths"].append(
                {"text": (
                    f"The paper situates its contribution against prior work "
                    f"({citation_count} citation(s); related-work section present)."
                )}
            )

    # Audit mode retains its established compact shaping. A successful committee
    # prepends exactly its three-to-five scientific questions while retaining
    # every deterministic comment; the latter remain separately traceable.
    raw_questions = comments_by_section["Questions for the Authors"]
    if state.scientific_judgment is None:
        evidence_requests = [
            item
            for item in raw_questions
            if "auditable evidence" in item.get("text", "")
        ]
        specific_questions = [
            item
            for item in raw_questions
            if "auditable evidence" not in item.get("text", "")
        ]
        shaped_questions = specific_questions[: (4 if evidence_requests else 5)]
        if evidence_requests:
            shaped_questions.append(
                {"text": (
                    f"{len(evidence_requests)} extracted result/arithmetic claim(s) could not be checked "
                    f"against the supplied evidence and are listed with their source lines in the Evidence "
                    f"Trace — could the authors provide the underlying results?"
                )}
            )
        comments_by_section["Questions for the Authors"] = shaped_questions
    else:
        scientific = state.scientific_judgment
        comments_by_section["Strengths"] = [
            {"text": _scientific_comment_text(comment)}
            for comment in scientific.strengths
        ] + comments_by_section["Strengths"]
        comments_by_section["Weaknesses"] = [
            {"text": _scientific_comment_text(comment)}
            for comment in scientific.weaknesses
        ] + comments_by_section["Weaknesses"]
        comments_by_section["Questions for the Authors"] = [
            {"text": _scientific_question_text(question)}
            for question in scientific.questions
        ]

    # Minor presentation remarks (typographic findings) always trail substantive
    # weaknesses — they are one-line notes, not the case against the paper.
    comments_by_section["Weaknesses"].sort(key=lambda item: bool(item.get("minor")))

    def render_comments(section: str, empty: str) -> str:
        comments = comments_by_section[section]
        if section == "Questions for the Authors" and comments:
            return "\n".join(
                f"{index}. {item['text']}" for index, item in enumerate(comments, 1)
            )
        return "\n".join(f"- {item['text']}" for item in comments) or f"- {empty}"

    strength_lines = render_comments(
        "Strengths", "No evidence-grounded strength could be established from the supplied material."
    )
    weakness_lines = render_comments(
        "Weaknesses",
        "The deterministic audit proved no contradiction, arithmetic error, or integrity breach; the "
        "remaining concern is limited to claims that could not be independently verified (see Questions).",
    )
    question_lines = render_comments("Questions for the Authors", "No open question was generated.")
    # Scores are the headline of the review, and the Overall recommendation leads.
    score_order = (
        "Overall recommendation",
        "Soundness",
        "Presentation",
        "Significance",
        "Originality",
        "Confidence",
    )
    ordered_scores = [(name, state.scores[name]) for name in score_order if name in state.scores]
    ordered_scores += [(name, score) for name, score in state.scores.items() if name not in score_order]
    score_lines = "\n".join(
        f"- {name}: {score['value']}/{score['scale'].split('-')[-1]} — {score['rationale']}"
        for name, score in ordered_scores
    )
    # A real review summarizes the PAPER first (its stated contribution and scope),
    # then a short audit line — not the audit process alone.
    overall_value = state.scores.get("Overall recommendation", {}).get("value", "?")
    sr_dishonest = len(self_review_audit.get("findings", []))
    proven_issues = len(state.finding_records)
    summary_anchor = state.claims[0]["id"] if state.claims else "no-extracted-claim"
    title = _paper_title(state.parsed_paper)
    contribution = _contribution_sentence(state.claims)
    if contribution:
        lead = contribution
    elif title:
        lead = f'The paper, "{title}", presents a method and supporting experiments.'
    else:
        lead = "The paper presents a method and supporting experiments."
    audit_stats = (
        f"{label_counts['contradicted']} contradiction(s), {sr_dishonest} dishonest "
        f"self-certification(s), {proven_issues} mechanical finding(s); "
        f"{label_counts['supported']} result claim(s) evidence-backed, "
        f"{label_counts['unverifiable']} unverifiable"
    )
    audit_summary = (
        f"Deterministic audit: {audit_stats}. "
        f"Overall recommendation: {overall_value}/6 [{summary_anchor}]."
    )
    if state.scientific_judgment is not None:
        # With a scientific judgment present the Summary reads as a review. The
        # audit tally is neutral process information — "no implemented check
        # covers this claim" is not a defect count — so it lives in the Evidence
        # Trace, not the Summary.
        scientific_summary = _sanitize_prose(
            re.sub(r"\s+", " ", state.scientific_judgment.summary.strip())
        )
        summary_text = f"{scientific_summary} Overall recommendation: {overall_value}/6."
    else:
        summary_text = (
            f"{lead} It reports {len(result_claims)} quantitative result claim(s) and cites "
            f"{citation_count} prior work(s). {audit_summary}"
        )

    # Legacy extension data can still render for embedders that directly assign
    # ``state.judgment``. Successful committees merge into the official sections
    # above and deliberately never create an isolated appendix.
    judgment_comments = state.judgment.get("comments") if isinstance(state.judgment, dict) else None
    if judgment_comments and state.scientific_judgment is None:
        rendered_judgment = "\n".join(f"- {str(item)}" for item in judgment_comments)
        provenance = ""
        if isinstance(state.judgment, dict) and state.judgment.get("model"):
            model_ok = state.judgment.get("model_ok")
            prompt_sha = str(state.judgment.get("prompt_sha256", ""))[:12]
            provenance = (
                f"\n\n_Legacy model critique: `{state.judgment.get('model')}` "
                f"(prompt `sha256:{prompt_sha}…`, temperature 0; "
                f"{'grounded + calibration-only-lowers' if model_ok else 'unavailable — retrieval-grounded questions only'})._"
            )
        judgment_block = f"\n## Scientific Judgment\n\n{rendered_judgment}{provenance}\n"
    else:
        judgment_block = ""

    # Closing reviewer comment (ICML-style), deterministic and always present.
    # The closing "most useful next step" must be a substantive scientific point:
    # skip minor typographic remarks (flagged or committee-authored) outright.
    first_weakness = next(
        (
            item["text"]
            for item in comments_by_section["Weaknesses"]
            if not item.get("minor") and not _TYPOGRAPHIC_REMARK_RE.search(item["text"])
        ),
        None,
    )
    first_question = next((item["text"] for item in comments_by_section["Questions for the Authors"]), None)
    if label_counts["contradicted"] or sr_dishonest:
        verdict_note = (
            "A proven integrity problem (a contradiction or dishonest self-certification) is the "
            "decisive factor and must be resolved before this paper can be accepted."
        )
    elif injection.get("findings"):
        verdict_note = (
            "Reviewer-directed concealed content was quarantined and reported "
            "in Ethics; it did not affect the scientific assessment."
        )
    elif state.scientific_judgment is not None:
        if isinstance(overall_value, int) and overall_value >= 5:
            verdict_note = (
                "The grounded scientific committee found the method, evidence, and "
                "scope sufficiently strong for an accept recommendation."
            )
        elif isinstance(overall_value, int) and overall_value >= 4:
            verdict_note = (
                "The grounded scientific committee found a positive case, with the "
                "listed weaknesses remaining material but not decisive."
            )
        else:
            verdict_note = (
                "The grounded scientific committee found that the listed scientific "
                "weaknesses currently outweigh the paper's strengths."
            )
    elif label_counts["supported"]:
        verdict_note = (
            "At least one headline result is mechanically supported; the open items concern "
            "positioning and rigor rather than any proven error."
        )
    else:
        verdict_note = (
            "No headline result is mechanically supported yet, so the recommendation stays "
            "borderline pending stronger evidence."
        )
    next_step = first_weakness or first_question
    comment_text = f"Recommendation: {overall_value}/6. {verdict_note}" + (
        f" Most useful next step for the authors — {next_step}" if next_step else ""
    )
    original_identity_line = _format_source_identity(
        "Original paper identity",
        state.original_identity,
    )
    derived_identity_line = _format_source_identity(
        "Derived Markdown identity",
        state.derived_identity,
    )
    page_count = str(state.page_count) if state.page_count is not None else "n/a"
    converter = state.converter or "none (Markdown source)"
    scientific_trace = _committee_trace(state)
    review_method = _review_method_line(state)
    audit_trace_line = (
        f"- Deterministic audit (neutral tally): {audit_stats}.\n"
        if state.scientific_judgment is not None
        else ""
    )
    return f"""# ICML-Style Paper Review

## Paper and Evidence Identity

{review_method}
- Review Agent name/version: paper-reviewer / `{state.agent_version}`
- Review-agent spec path/hash: `{_scrub_path(state.review_agent_path)}` / `sha256:{state.review_agent_hash}`
{original_identity_line}
{derived_identity_line}
- Original PDF page count: `{page_count}`
- Converter: `{converter}`
- Paper version/hash: `{_scrub_path(state.paper_path)}` / `sha256:{state.paper_hash}`
- Evidence bundle reviewed: {_format_evidence_identity(state)}
- Frozen at (UTC): `{state.frozen_at}`

## Summary

{summary_text}

## Strengths

{strength_lines}

## Weaknesses

{weakness_lines}

## Questions for the Authors

{question_lines}

## Scores

{score_lines}
{judgment_block}
## Ethics and Limitations

Paper text was treated only as data. The injection audit sanitized hidden HTML and Unicode format controls before claim analysis and found {len(injection.get('findings', []))} reviewer-directed instruction attempt(s). Broader ethics and evidence-quality claims outside S3 remain unverifiable [{state.claims[0]['id'] if state.claims else 'no-extracted-claim'}].

## Evidence Trace

- Pipeline execution: `{stage_trace}`.
{audit_trace_line}- Frozen review identity: `{state.review_identity}`.
- Verdict labels digest: `{state.verdict_digest}`.
- External citation snapshot digest: `{state.external_snapshot_digest}`.
{scientific_trace}- Output path: `{_scrub_path(state.output_path)}`.
- Frozen paper input: `{_scrub_path(state.paper_path)}` (`sha256:{state.paper_hash}`).
- Frozen original identity: `{_scrub_path(state.original_identity.path)}` (`{state.original_identity.media_type}`, `sha256:{state.original_identity.sha256}`, {state.original_identity.byte_length} bytes, page count={page_count}).
- Frozen derived identity: `{_scrub_path(state.derived_identity.path)}` (`{state.derived_identity.media_type}`, `sha256:{state.derived_identity.sha256}`, {state.derived_identity.byte_length} bytes).
- Frozen converter: `{converter}`.
- Pre-S1 sanitation: {len(state.sanitation_traces)} trace(s), {len(state.injection_findings)} injection finding(s).
- S1 parse inventory: {section_count} sections, {table_count} tables, {number_count} numeric tokens with source locations.
- S3 ledger-trace: {matched_count}/{trace_count} metric-labelled values matched; {len(ledger_trace.get('findings', []))} finding(s).
- S3 internal-consistency: {len(internal.get('traces', []))} comparison(s), {len(internal.get('findings', []))} finding(s).
- S3 arithmetic: {len(arithmetic.get('traces', []))} recomputation(s), {len(arithmetic.get('findings', []))} finding(s).
- S3 baseline-fairness: {len(baseline_fairness.get('traces', []))} explicit improvement claim(s), {len(baseline_fairness.get('findings', []))} finding(s).
- S3 negative-evidence: {len(negative_evidence.get('traces', []))} discard/crash outcome(s), {len(negative_evidence.get('findings', []))} omission finding(s).
- S3 citation-existence: {len(citations.get('traces', []))} explicit identifier(s), {len(citations.get('findings', []))} existence/title finding(s).
- S3 template-compliance: {len(template.get('traces', []))} contract trace(s), {len(template.get('findings', []))} finding(s).
- S3 injection-scan: {len(injection.get('traces', []))} sanitation trace(s), {len(injection.get('findings', []))} reviewer-directed instruction finding(s).
- S3 self-review-audit: {len(self_review_audit.get('traces', []))} checklist item(s), {len(self_review_audit.get('findings', []))} dishonest self-certification(s).
- S3 positioning: {positioning_signals.get('citation_count', 0)} cited reference(s), related-work section={positioning_signals.get('has_related_work_section', False)}, {positioning_signals.get('novelty_claim_count', 0)} novelty/superiority claim(s), {len(positioning.get('findings', []))} overclaim finding(s), {len(positioning.get('questions', []))} positioning question(s).
- S5 DRAFT/GROUND: {len(state.draft_comments)} candidate comment(s), {len(state.grounded_comments)} retained, {len(state.grounding_audit.get('deleted', []))} deleted, {len(state.grounding_audit.get('reclassified', []))} criticism comment(s) converted to questions.
- S2/S4 claim verdicts:
{evidence_trace_lines}

## Comment

{comment_text}
"""


def _judgment_enabled() -> bool:
    """Gate best-mode additions on a committee key or legacy retrieval opt-in.

    Audit mode never reaches this layer. Without either opt-in, best remains
    byte-compatible with audit apart from already-established volatile fields.
    """

    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("REVIEWER_BEST_RETRIEVAL"))


def _best_packet_chars() -> int:
    try:
        return max(8_000, int(os.environ.get("REVIEWER_BEST_MAX_CHARS", "60000")))
    except (TypeError, ValueError):
        return 60_000


def _compact_finding(record: dict[str, Any], *, finding_id: str) -> dict[str, Any]:
    location = record.get("location")
    compact_location = dict(location) if isinstance(location, dict) else str(location or "")
    return {
        "id": finding_id,
        "check": str(record.get("check", "")),
        "location": compact_location,
        "observed": str(record.get("observed", "")),
        "expected": str(record.get("expected", "")),
    }


def _committee_inputs(
    state: ReviewState,
    paper_span_ids: list[str],
    retrieval: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]], bool, tuple[str, ...]]:
    """Build compact deterministic data and stable non-paper grounding IDs."""

    verdicts = {item["claim_id"]: item for item in state.verdicts}
    all_contradicted_ids = [
        claim["id"]
        for claim in state.claims
        if verdicts[claim["id"]].get("label") == "contradicted"
    ]
    all_supported_ids = [
        claim["id"]
        for claim in state.claims
        if verdicts[claim["id"]].get("label") == "supported"
    ]
    ordered_claims = sorted(
        state.claims,
        key=lambda claim: (
            0
            if verdicts[claim["id"]].get("label") == "contradicted"
            else 1
            if verdicts[claim["id"]].get("label") == "supported"
            else 2
            if claim.get("type") in {"result", "arithmetic", "hypothesis"}
            else 3,
            str(claim["id"]),
        ),
    )
    selected_claims = ordered_claims[:60]
    claims: list[dict[str, Any]] = []
    for claim in selected_claims:
        verdict = verdicts[claim["id"]]
        location = claim.get("location", {})
        claims.append(
            {
                "id": claim["id"],
                "type": str(claim.get("type", "")),
                "text": str(claim.get("text", "")),
                "line": location.get("line") if isinstance(location, dict) else None,
                "verdict": verdict.get("label"),
                "verdict_reason": str(verdict.get("reason", "")),
                "evidence": list(verdict.get("evidence", [])),
            }
        )

    # Injection findings may contain a matched fragment from hidden source text.
    # They remain in the deterministic audit/review but never enter model prompts.
    redacted_injection_findings = sum(
        record.get("check") == "injection-scan"
        for record in state.finding_records
    )
    findings = [
        _compact_finding(record, finding_id=record["id"])
        for record in state.finding_records
        if record.get("check") != "injection-scan"
    ]
    self_review_ids: list[str] = []
    for index, record in enumerate(
        state.mechanical_checks.get("self-review-audit", {}).get("findings", []),
        1,
    ):
        finding_id = f"self-review-finding-{index:03d}"
        self_review_ids.append(finding_id)
        findings.append(_compact_finding(record, finding_id=finding_id))
    for index, record in enumerate(
        state.mechanical_checks.get("positioning", {}).get("findings", []),
        1,
    ):
        findings.append(
            _compact_finding(
                record,
                finding_id=f"positioning-finding-{index:03d}",
            )
        )

    selected_ids = {claim["id"] for claim in selected_claims}
    contradicted_ids = [
        claim_id for claim_id in all_contradicted_ids if claim_id in selected_ids
    ]
    supported_ids = [
        claim_id for claim_id in all_supported_ids if claim_id in selected_ids
    ]
    finding_ids = [finding["id"] for finding in findings]
    claim_ids = [claim["id"] for claim in claims]
    retrieved_prior_work: list[dict[str, Any]] = []
    arxiv_ids: list[str] = []
    for trace in (retrieval or {}).get("traces", []):
        if not isinstance(trace, dict):
            continue
        identifier = str(trace.get("id", "")).strip()
        if not identifier:
            continue
        grounding_id = f"arxiv:{identifier}"
        arxiv_ids.append(grounding_id)
        retrieved_prior_work.append(
            {
                "id": grounding_id,
                "title": str(trace.get("title", "")),
                # The abstract is the actual "scientific evidence": it lets the
                # committee compare the submission's method/claims against what this
                # related work really did, not just its title. Bounded to keep the
                # committee prompt within budget.
                "abstract": " ".join(str(trace.get("summary", "")).split())[:600],
                "published": str(trace.get("published", "")),
                "temporal_relation": str(trace.get("temporal_relation", "unknown")),
                "similarity": trace.get("similarity"),
                "already_cited": bool(trace.get("already_cited")),
                "mentioned_by_title": bool(trace.get("mentioned_by_title")),
            }
        )
    # Injection findings stay redacted from model prompts and remain visible in
    # the audit summary, but cannot cap scientific scores: all downstream analysis
    # sees the sanitized twin, so scoring the hidden payload would violate the
    # injection-invariance contract.
    integrity_ids = tuple([*all_contradicted_ids, *self_review_ids])
    audit = {
        "audit_identity": state.review_identity,
        "summary": {
            "claim_count": len(state.claims),
            "included_prioritized_claims": len(claims),
            "omitted_lower_priority_claims": len(state.claims) - len(claims),
            "supported_claims": len(all_supported_ids),
            "contradicted_claims": len(all_contradicted_ids),
            "deterministic_findings": len(findings),
            "redacted_injection_findings": redacted_injection_findings,
            "proven_integrity_breach": bool(integrity_ids),
        },
        "claims": claims,
        "findings": findings,
        "retrieved_prior_work": retrieved_prior_work,
        "deterministic_scores": {
            dimension: {
                "value": score.get("value"),
                "rationale": score.get("rationale"),
            }
            for dimension, score in state.scores.items()
        },
    }
    grounding = {
        "finding_ids": finding_ids,
        "contradicted_claim_ids": contradicted_ids,
        "supported_claim_ids": supported_ids,
        "claim_ids": claim_ids,
        "paper_span_ids": paper_span_ids,
        "arxiv_ids": arxiv_ids,
    }
    return audit, grounding, bool(integrity_ids), integrity_ids


def _apply_legacy_retrieval_layer(state: ReviewState) -> ReviewState:
    """Preserve the no-model retrieval opt-in for existing embedders."""

    try:
        signals = state.mechanical_checks.get("positioning", {}).get("signals", {})
        retrieval = (
            check_novelty_positioning(state.parsed_paper)
            if signals.get("novelty_claim_count")
            else {"questions": [], "query": ""}
        )
        comments = [
            question["text"]
            for question in retrieval.get("questions", [])
            if isinstance(question, dict) and question.get("text")
        ]
        state.judgment = (
            {
                "comments": comments,
                "source": "novelty-positioning",
                "query": retrieval.get("query", ""),
            }
            if comments
            else {}
        )
    except Exception:  # noqa: BLE001 - optional retrieval never blocks a review
        state.judgment = {}
    return state


def _guardrail_annotations(state: ReviewState, retrieval: dict[str, Any]) -> dict[str, Any]:
    """Neutral leads for the review panel: scans annotate, they never conclude."""

    def _findings(check: str) -> list[dict[str, Any]]:
        items = state.mechanical_checks.get(check, {}).get("findings", [])
        return [
            {"location": item.get("location"), "observed": item.get("observed")}
            for item in items
        ][:8]

    return {
        "hidden_instruction_attempts": [
            {"kind": item.get("kind"), "match": str(item.get("match", ""))[:200]}
            for item in state.mechanical_checks.get("injection-scan", {}).get("findings", [])
        ],
        "citation_findings": _findings("citation-existence"),
        "arithmetic_findings": _findings("arithmetic"),
        "consistency_findings": _findings("internal-consistency"),
        "typographic_minor_remarks": (
            _findings("cross-references") + _findings("manuscript-artifacts")
        ),
        "promised_but_possibly_unreported": list(
            state.mechanical_checks.get("promised-results", {}).get("traces", [])
        ),
        "prior_art_leads": [
            question.get("text")
            for question in retrieval.get("questions", [])
            if isinstance(question, dict) and question.get("text")
        ][:5],
        "note": (
            "Automated leads, not conclusions; verify against the paper and "
            "weigh in context."
        ),
    }


def _apply_judgment_layer(state: ReviewState) -> ReviewState:
    """Run the review panel after S6 without changing audit identities.

    Every panelist reads the FULL sanitized paper and writes a complete
    ICML-shaped review; with panel size >= 2 an area chair synthesizes the
    final review, cross-checking each criticism against the paper. The gated
    result becomes the review body; the deterministic audit remains the
    sidecar and the per-paper fallback. Proven integrity findings cap
    Soundness and Overall at 2. Any failure leaves the deterministic review
    untouched and records fallback provenance.
    """

    if not _judgment_enabled():
        return state
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _apply_legacy_retrieval_layer(state)
    # Committee enabled (key present) but no model: a config error affecting every
    # paper identically, so fail loud rather than silently downgrade. Raised before
    # the isolation try so it surfaces instead of collapsing to a per-paper fallback.
    if not os.environ.get("OPENAI_MODEL"):
        raise RuntimeError(
            "OPENAI_MODEL is not set but the scientific committee is enabled "
            "(OPENAI_API_KEY present). Set OPENAI_MODEL (e.g. gpt-5.6-sol) in your "
            ".env or environment, or run with --deterministic to skip the committee."
        )

    try:
        panel_started = time.monotonic()
        full_paper = paper_text(state.parsed_paper)
        # Reviewer-style prior-art queries (by idea, not title tokens) so retrieval
        # finds the real related work; degrades to the lexical query on failure.
        scout_queries = generate_search_queries(
            title=_paper_title(state.parsed_paper),
            abstract=full_paper[:2500],
            api_key=api_key,
        )
        retrieval = check_novelty_positioning(
            state.parsed_paper, queries=scout_queries or None
        )
        annotations = _guardrail_annotations(state, retrieval)
        contradicted_count = sum(
            1 for verdict in state.verdicts if verdict.get("label") == "contradicted"
        )
        dishonest_count = len(
            state.mechanical_checks.get("self-review-audit", {}).get("findings", [])
        )
        breach_count = contradicted_count + dishonest_count

        result = run_panel_review(
            full_paper,
            annotations,
            paper_title=extract_paper_title(full_paper),
            api_key=api_key,
        )
        members = result.get("members", [])
        state.panel_reviews = [dict(member) for member in members]
        state.committee_provenance = {
            "layer": "review-panel",
            "panel": result.get("panel"),
            "model": result.get("model"),
            "synthesis": result.get("synthesis", ""),
            "members": [
                {
                    key: member.get(key)
                    for key in ("role", "ok", "gate", "prompt_sha256", "response_sha256", "error")
                    if key in member
                }
                for member in members
            ],
            "runtime_seconds": round(time.monotonic() - panel_started, 6),
        }
        if not result.get("ok"):
            state.judgment_error = "review panel returned no valid review"
            retrieval_comments = [
                question["text"]
                for question in retrieval.get("questions", [])
                if isinstance(question, dict) and question.get("text")
            ]
            state.judgment = (
                {
                    "comments": retrieval_comments,
                    "source": "novelty-positioning",
                    "query": retrieval.get("query", ""),
                }
                if retrieval_comments
                else {}
            )
            return state

        # The panel's scores stand; the mechanical layer's only score authority
        # here is the proven-integrity cap.
        capped_scores, cap_notes = apply_integrity_caps(
            result["scores"], breach_count=breach_count
        )
        for dimension, value in capped_scores.items():
            state.scores[dimension] = {
                "value": value,
                "scale": SCORE_SCALES[dimension],
                "rationale": (
                    "Judgment-first panel review; rationale in the review body's "
                    "Scores section."
                ),
            }
        body = str(result["review_markdown"]).strip() + "\n"
        if cap_notes:
            body += "\n> " + " ".join(cap_notes) + "\n"
        model = str(result.get("model") or os.environ.get("OPENAI_MODEL") or "unknown")
        state.review_document = body
        state.judgment_identity = "sha256:" + sha256(
            f"{state.review_identity}|{model}|{body}".encode("utf-8")
        ).hexdigest()
        state.judgment_error = ""
        state.judgment = {}
    except Exception as error:  # noqa: BLE001 - one paper failure cannot escape
        state.scientific_judgment = None
        state.judgment_identity = ""
        detail = re.sub(r"\s+", " ", str(error)).strip()
        state.judgment_error = (
            f"{type(error).__name__}: {detail[:300]}"
            if detail
            else type(error).__name__
        )
        state.judgment = {}
    return state


def _panel_appendix(state: ReviewState) -> str:
    """Full panel member reviews for the audit sidecar (never the review body)."""

    if not state.panel_reviews:
        return ""
    blocks = []
    for index, member in enumerate(state.panel_reviews, 1):
        status = "accepted" if member.get("ok") else "dropped"
        header = f"### Panel review {index} — {member.get('role', 'generalist')} ({status})"
        body = str(member.get("markdown", "")).strip() or (
            f"_no review produced: {member.get('error', 'unknown error')}_"
        )
        blocks.append(f"{header}\n\n{body}\n")
    return "\n## Panel Reviews (provenance)\n\n" + "\n".join(blocks)


class ReviewPipeline:
    """Execute the ordered S1-S6 pipeline stages."""

    def __init__(self) -> None:
        self._stages: tuple[Callable[[ReviewState], ReviewState], ...] = (
            _parse_paper,
            _extract_claims,
            _run_mechanical_checks,
            _label_verdicts,
            self._compose,
            _freeze_inputs,
        )

    @staticmethod
    def _compose(state: ReviewState) -> ReviewState:
        scientific_findings = [
            finding
            for finding in state.finding_records
            if finding.get("check") != "injection-scan"
        ]
        state.draft_comments = draft_comments(
            state.claims,
            state.verdicts,
            scientific_findings,
        )
        state.grounding_audit = ground_comments(
            state.draft_comments,
            state.claims,
            state.verdicts,
            scientific_findings,
        )
        state.grounded_comments = state.grounding_audit["comments"]
        sr_dishonest = len(state.mechanical_checks.get("self-review-audit", {}).get("findings", []))
        state.scores = calibrate_scores(
            state.claims,
            state.verdicts,
            state.finding_records,
            self_review_dishonest=sr_dishonest,
            positioning=state.mechanical_checks.get("positioning"),
        )
        return _mark_stage(state, "S5 compose")

    def run(
        self,
        paper_path: Path,
        evidence_dir: Path,
        output_path: Path,
        mode: str = "best",
        *,
        prepared_paper: PreparedPaper | None = None,
    ) -> ReviewState:
        if mode not in ("audit", "best"):
            raise ValueError(f"unknown review mode: {mode!r} (expected 'audit' or 'best')")
        requested_path = paper_path.expanduser().resolve()
        evidence_dir = evidence_dir.expanduser().resolve()
        output_path = output_path.expanduser().resolve()

        if not requested_path.is_file():
            raise FileNotFoundError(f"paper is not a file: {requested_path}")
        if not evidence_dir.is_dir():
            raise NotADirectoryError(f"evidence directory does not exist: {evidence_dir}")
        prepared = prepared_paper or prepare_paper(requested_path)
        _validate_prepared_paper(requested_path, prepared)
        paper_path = Path(prepared.markdown.path)
        if output_path in {requested_path, paper_path}:
            raise ValueError("output path must differ from the paper path")

        state = ReviewState(
            paper_path,
            evidence_dir,
            output_path,
            agent_version=_agent_version(),
            review_agent_hash=_sha256_file(REVIEW_AGENT_PATH),
            paper_hash=prepared.markdown.sha256,
            prepared_paper=prepared,
            original_identity=prepared.original,
            derived_identity=prepared.markdown,
            page_count=prepared.original.page_count,
            converter=prepared.converter,
            sanitation_traces=list(prepared.sanitation_traces),
            injection_findings=list(prepared.injection_findings),
            evidence_hashes=_evidence_hashes(evidence_dir),
            mode=mode,
        )
        for stage in self._stages:
            state = stage(state)

        if tuple(state.completed_stages) != STAGE_NAMES:
            raise RuntimeError(f"pipeline stage order mismatch: {state.completed_stages}")

        # `best` runs the failure-isolated committee AFTER the deterministic
        # audit (including S6 freeze), so model output can never perturb the
        # audit identity or verdict-label digest.
        if state.mode == "best":
            state = _apply_judgment_layer(state)

        # S5 decides all deterministic prose, comments, and scores. Rendering
        # after S6 lets the official output include the verified freeze record.
        audit_document = _compose_review(state)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if state.review_document:
            # Judgment-first inversion: the review body is the panel/area-chair
            # review (double-blind clean, no pipeline mechanics); the full
            # deterministic audit plus panel provenance ships as a sidecar so
            # every step stays traceable.
            state.review_markdown = state.review_document
            output_path.with_suffix(".audit.md").write_text(
                audit_document + _panel_appendix(state), encoding="utf-8"
            )
        else:
            state.review_markdown = audit_document
        output_path.write_text(state.review_markdown, encoding="utf-8")
        return state


def run_pipeline(
    paper_path: Path,
    evidence_dir: Path,
    output_path: Path,
    mode: str = "best",
    *,
    prepared_paper: PreparedPaper | None = None,
) -> ReviewState:
    """Convenience entry point for callers embedding the reviewer package."""

    return ReviewPipeline().run(
        paper_path,
        evidence_dir,
        output_path,
        mode=mode,
        prepared_paper=prepared_paper,
    )
