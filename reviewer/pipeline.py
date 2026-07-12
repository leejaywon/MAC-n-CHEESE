"""Ordered six-stage Track 2 review pipeline."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .baseline_fairness import check_baseline_fairness
from .citation_existence import check_citation_existence
from .claims import extract_claims, label_verdicts
from .composer import calibrate_scores, draft_comments, ground_comments
from .injection_scan import check_injection_scan, sanitize_for_analysis
from .mechanical_checks import check_arithmetic, check_internal_consistency, check_ledger_trace
from .model_critique import critique as _model_critique
from .negative_evidence import check_negative_evidence
from .novelty_positioning import check_novelty_positioning
from .parser import parse_markdown
from .positioning import check_positioning
from .rigor_checklist import rigor_checklist_questions
from .scientific_scaffolding import rigor_questions
from .self_review_audit import check_self_review_consistency
from .template_compliance import check_template_compliance


STAGE_NAMES = (
    "S1 parse",
    "S2 claims",
    "S3 mech-check",
    "S4 verdicts",
    "S5 compose",
    "S6 freeze",
)

ROOT = Path(__file__).resolve().parents[1]
REVIEW_AGENT_PATH = ROOT / "submission" / "review-agent.md"
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
    evidence_hashes: list[tuple[str, str]] = field(default_factory=list)
    frozen_at: str = ""
    review_identity: str = ""
    verdict_digest: str = ""
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
    mode: str = "audit"
    judgment: dict[str, Any] = field(default_factory=dict)
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

    Legacy M0-M6 outputs have no markers and may be replaced once. Once an M7
    result is written, however, the output path is bound to one frozen identity.
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
    state.parsed_paper = parse_markdown(state.paper_path)
    return _mark_stage(state, "S1 parse")


def _detect_event_format(parsed_paper: dict[str, object], evidence_dir: Path) -> bool:
    """Is this an event-format Track 1 submission, or an arbitrary peer paper?

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
    checks = (
        check_ledger_trace(state.parsed_paper, state.evidence_dir, state.event_format),
        check_internal_consistency(state.parsed_paper),
        check_arithmetic(state.parsed_paper),
        check_baseline_fairness(state.parsed_paper, state.evidence_dir),
        check_negative_evidence(state.parsed_paper, state.evidence_dir),
        check_citation_existence(state.parsed_paper),
        check_template_compliance(state.parsed_paper, state.event_format),
        check_injection_scan(state.parsed_paper),
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


def _freeze_inputs(state: ReviewState) -> ReviewState:
    # Hash once before S1 and verify again at S6 so a mid-run input mutation is
    # never silently accepted as part of the frozen review identity.
    if state.paper_hash != _sha256_file(state.paper_path):
        raise RuntimeError("paper changed while the review pipeline was running")
    if state.evidence_hashes != _evidence_hashes(state.evidence_dir):
        raise RuntimeError("evidence bundle changed while the review pipeline was running")
    if state.review_agent_hash != _sha256_file(state.review_agent_path):
        raise RuntimeError("review-agent.md changed while the review pipeline was running")
    if state.agent_version != _agent_version():
        raise RuntimeError("reviewer source changed while the review pipeline was running")

    state.review_identity = _canonical_digest(
        {
            "schema_version": 1,
            "agent_version": state.agent_version,
            "review_agent_hash": state.review_agent_hash,
            "paper_hash": state.paper_hash,
            "evidence_hashes": state.evidence_hashes,
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


def _format_evidence_identity(state: ReviewState) -> str:
    if not state.evidence_hashes:
        return f"`{state.evidence_dir}` (empty directory)"
    entries = ", ".join(f"`{name}` (`sha256:{digest}`)" for name, digest in state.evidence_hashes)
    return f"`{state.evidence_dir}`: {entries}"


def _compose_review(state: ReviewState) -> str:
    """Return the official review shape after DRAFT and authoritative GROUND."""

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
    evidence_trace_lines = "\n".join(
        f"- [{claim['id']}] **{verdict_by_claim[claim['id']]['label']}** — "
        f"paper:{claim['location']['line']} — {claim['text']} — "
        f"{verdict_by_claim[claim['id']]['reason']} Evidence: "
        f"{', '.join(f'`{pointer}`' for pointer in verdict_by_claim[claim['id']]['evidence'])}."
        for claim in state.claims
    ) or "- No declarative claims were extracted."
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
    for question in rigor_questions(state.parsed_paper):
        comments_by_section["Questions for the Authors"].append(question)
    # ICML/NeurIPS reproducibility & limitations checklist: one consolidated
    # Question about missing items (code/data, hyperparameters, compute,
    # limitations, broader impact), self-suppressing on a thorough paper.
    for question in rigor_checklist_questions(state.parsed_paper):
        comments_by_section["Questions for the Authors"].append(question)

    def render_comments(section: str, empty: str) -> str:
        comments = comments_by_section[section]
        return "\n".join(f"- {item['text']}" for item in comments) or f"- {empty}"

    strength_lines = render_comments("Strengths", "No evidence-grounded strengths were established.")
    weakness_lines = render_comments("Weaknesses", "No deterministic contradictions were proven.")
    question_lines = render_comments(
        "Questions for the Authors", "No unverified claim generated an evidence request."
    )
    # Scores are the headline of the review, and the Overall recommendation leads.
    score_order = ("Overall recommendation", "Soundness", "Presentation", "Contribution", "Confidence")
    ordered_scores = [(name, state.scores[name]) for name in score_order if name in state.scores]
    ordered_scores += [(name, score) for name, score in state.scores.items() if name not in score_order]
    score_lines = "\n".join(
        f"- {name}: {score['value']}/{score['scale'].split('-')[-1]} — {score['rationale']}"
        for name, score in ordered_scores
    )
    # An assessment, not a claim count: the event flags "review-as-summary" as a
    # common mistake, so the Summary states the verdict the audit supports.
    overall_value = state.scores.get("Overall recommendation", {}).get("value", "?")
    sr_dishonest = len(self_review_audit.get("findings", []))
    proven_issues = len(state.finding_records)
    summary_anchor = state.claims[0]["id"] if state.claims else "no-extracted-claim"
    summary_text = (
        f"This review assesses the paper's claims against its supplied evidence. The "
        f"deterministic audit proved {label_counts['contradicted']} contradiction(s), "
        f"{sr_dishonest} dishonest self-certification(s), and {proven_issues} mechanical "
        f"finding(s) in total; {label_counts['supported']} result claim(s) are evidence-backed "
        f"and {label_counts['unverifiable']} remain unverifiable. Overall recommendation: "
        f"{overall_value}/5 [{summary_anchor}]."
    )
    # `best`-mode judgment layer (§4c) is additive prose. Empty in `audit` mode,
    # so this block renders nothing and audit output is byte-identical.
    judgment_comments = state.judgment.get("comments") if isinstance(state.judgment, dict) else None
    if judgment_comments:
        rendered_judgment = "\n".join(f"- {str(item)}" for item in judgment_comments)
        provenance = ""
        if isinstance(state.judgment, dict) and state.judgment.get("model"):
            model_ok = state.judgment.get("model_ok")
            prompt_sha = str(state.judgment.get("prompt_sha256", ""))[:12]
            provenance = (
                f"\n\n_Model critique: `{state.judgment.get('model')}` "
                f"(prompt `sha256:{prompt_sha}…`, temperature 0; "
                f"{'grounded + calibration-only-lowers' if model_ok else 'unavailable — retrieval-grounded questions only'})._"
            )
        judgment_block = f"\n## Scientific Judgment (best mode)\n\n{rendered_judgment}{provenance}\n"
    else:
        judgment_block = ""

    # Closing reviewer comment (ICML-style), deterministic and always present.
    first_weakness = next((item["text"] for item in comments_by_section["Weaknesses"]), None)
    first_question = next((item["text"] for item in comments_by_section["Questions for the Authors"]), None)
    if label_counts["contradicted"] or sr_dishonest:
        verdict_note = (
            "A proven integrity problem (a contradiction or a dishonest self-certification) is the "
            "decisive factor and must be resolved before this paper can be accepted."
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
    comment_text = f"Recommendation: {overall_value}/5. {verdict_note}" + (
        f" Most useful next step for the authors — {next_step}" if next_step else ""
    )
    return f"""# Track 2 — ICML-Style Review

## Paper and Evidence Identity

- Review Agent name/version: NFL-Auditor / `{state.agent_version}`
- `review-agent.md` path/hash: `{state.review_agent_path}` / `sha256:{state.review_agent_hash}`
- Paper version/hash: `{state.paper_path}` / `sha256:{state.paper_hash}`
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
- Frozen review identity: `{state.review_identity}`.
- Verdict labels digest: `{state.verdict_digest}`.
- Output path: `{state.output_path}`.
- Frozen paper input: `{state.paper_path}` (`sha256:{state.paper_hash}`).
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
    """Gate the `best` layer's network/model work on an explicit opt-in.

    A live ``OPENAI_API_KEY`` or the ``RALPH_BEST_RETRIEVAL`` flag enables it.
    Absent both, `best` equals `audit`, so the layer never adds nondeterministic
    retrieved content to a default run or a hermetic test.
    """

    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("RALPH_BEST_RETRIEVAL"))


def _apply_judgment_layer(state: ReviewState) -> ReviewState:
    """Optional `best`-mode scientific judgment layer (spec §4c).

    Runs ONLY in `best` mode, AFTER the S6 freeze, so it can never perturb the
    audit identity or the S4 verdict-label digest. Today it contributes the
    retrieval-grounded novelty/positioning core: real prior work is fetched from
    arXiv and a closely-related but uncited paper becomes a grounded Question.

    Invariants (violating any = revert):
    - Gated on ``_judgment_enabled()``; disabled → `best` == `audit`.
    - Self-suppressing: only positions a paper that makes a novelty/superiority
      claim (reuses the deterministic S3 positioning signal).
    - On ANY error, leaves ``state.judgment`` empty so `audit` output stands.

    The optional model critique (multi-persona, sanitize-first, grounded,
    calibration-only-lowers) appends to ``comments`` here when an API key is
    present; the retrieval-grounded Questions stand alone without it.
    """

    if not _judgment_enabled():
        return state
    try:
        signals = state.mechanical_checks.get("positioning", {}).get("signals", {})
        if not signals.get("novelty_claim_count"):
            return state
        retrieval = check_novelty_positioning(state.parsed_paper)
        comments = [question["text"] for question in retrieval.get("questions", [])]
        judgment: dict[str, Any] = {
            "comments": comments,
            "source": "novelty-positioning",
            "query": retrieval.get("query", ""),
        }
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            verdict_label = {verdict["claim_id"]: verdict["label"] for verdict in state.verdicts}
            finding_ids = [record["id"] for record in state.finding_records]
            contradicted_ids = [cid for cid, label in verdict_label.items() if label == "contradicted"]
            supported_ids = [cid for cid, label in verdict_label.items() if label == "supported"]
            grounding = {
                "finding_ids": finding_ids,
                "contradicted_claim_ids": contradicted_ids,
                "supported_claim_ids": supported_ids,
                "claim_ids": [claim["id"] for claim in state.claims],
                "arxiv_ids": [f"arxiv:{trace['id']}" for trace in retrieval.get("traces", [])],
            }
            anchor_scores = {name: score["value"] for name, score in state.scores.items()}
            sanitized = sanitize_for_analysis(state.paper_path.read_text(encoding="utf-8"))
            model_result = _model_critique(
                sanitized_paper=sanitized,
                grounding=grounding,
                anchor_scores=anchor_scores,
                api_key=api_key,
            )
            comments.extend(item["text"] for item in model_result.get("comments", []))
            # Without a proven defect (a finding or a contradiction), the model may
            # nudge a score down but never floor it: a paper with zero proven
            # problems must not be driven to the minimum on an ungrounded opinion.
            score_floor = 1 if (finding_ids or contradicted_ids) else 2
            _apply_calibration(state, model_result.get("calibration", {}), score_floor)
            judgment["model"] = model_result.get("model")
            judgment["prompt_sha256"] = model_result.get("prompt_sha256")
            judgment["model_ok"] = model_result.get("ok", False)
        judgment["comments"] = comments
        state.judgment = judgment if (comments or judgment.get("model")) else {}
    except Exception:  # noqa: BLE001 — a frozen audit must survive any layer failure
        state.judgment = {}
    return state


def _apply_calibration(state: ReviewState, calibration: dict[str, Any], floor: int = 1) -> None:
    """Lower deterministic scores per the model's calibration; never raise.

    Runs after the S6 freeze in `best` mode only. It touches ``state.scores``,
    which is not part of the frozen verdict-label digest, so the audit
    determinism contract is untouched. ``floor`` bounds how far a dimension may be
    lowered: it is 1 when a defect is actually proven, but 2 (borderline) when the
    critique rests on judgment alone, so an unproven opinion cannot floor a score.
    """

    for dimension, adjustment in (calibration.items() if isinstance(calibration, dict) else []):
        score = state.scores.get(dimension)
        if not score or not isinstance(adjustment, dict):
            continue
        new_value = adjustment.get("value")
        # bool is an int subclass; reject it so a stray True cannot become "1/4".
        if isinstance(new_value, bool) or not isinstance(new_value, int):
            continue
        new_value = max(new_value, floor)
        if new_value < score["value"]:
            reason = adjustment.get("reason") or "best-mode multi-persona calibration."
            score["value"] = new_value
            score["rationale"] = (
                f"{score['rationale']} Best-mode calibration lowered this to {new_value}: {reason}"
            )


class ReviewPipeline:
    """Execute the S1-S6 walking skeleton in the specified order."""

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
        state.draft_comments = draft_comments(state.claims, state.verdicts, state.finding_records)
        state.grounding_audit = ground_comments(
            state.draft_comments, state.claims, state.verdicts, state.finding_records
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
        mode: str = "audit",
    ) -> ReviewState:
        if mode not in ("audit", "best"):
            raise ValueError(f"unknown review mode: {mode!r} (expected 'audit' or 'best')")
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
            agent_version=_agent_version(),
            review_agent_hash=_sha256_file(REVIEW_AGENT_PATH),
            paper_hash=_sha256_file(paper_path),
            evidence_hashes=_evidence_hashes(evidence_dir),
            mode=mode,
        )
        for stage in self._stages:
            state = stage(state)

        if tuple(state.completed_stages) != STAGE_NAMES:
            raise RuntimeError(f"pipeline stage order mismatch: {state.completed_stages}")

        # `best` adds the optional judgment layer AFTER the deterministic audit
        # (including S6 freeze) so it can never perturb the audit identity or
        # verdict-label digest. It is a no-op until the loop builds it (§4c).
        if state.mode == "best":
            state = _apply_judgment_layer(state)

        # S5 decides all deterministic prose, comments, and scores. Rendering
        # after S6 lets the official output include the verified freeze record.
        state.review_markdown = _compose_review(state)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(state.review_markdown, encoding="utf-8")
        return state


def run_pipeline(
    paper_path: Path,
    evidence_dir: Path,
    output_path: Path,
    mode: str = "audit",
) -> ReviewState:
    """Convenience entry point for callers embedding the reviewer package."""

    return ReviewPipeline().run(paper_path, evidence_dir, output_path, mode=mode)
