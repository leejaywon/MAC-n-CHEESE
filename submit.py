#!/usr/bin/env python3
"""Pull the assigned papers from openagentreview.org, review each with the
deterministic pipeline, and submit structured reviews — within the review window.
See ``skill.md`` for the API contract and its timing.

Secrets: the setup token is read from **stdin** (never argv, so it stays out of
shell history) and exchanged exactly once for a bearer that lives only in memory.
Nothing here prints the token, the bearer, or paper identity beyond the public
assignment ordinal. Fetch/review preparation runs in worker *threads* (not
subprocesses), then each POST is serialized behind a fresh status/guidance check,
so the in-memory bearer is never pickled or copied out.

    # Dry run against the in-memory mock — no token, no network. Validates the
    # whole flow and the exact review schema the server enforces:
    python submit.py --dry-run

    # Preview the live assignments without submitting anything:
    python submit.py --no-post

    # Download all ten PDFs to submit_work/assigned_papers and stop:
    python submit.py --download-only

    # Live: paste the 15-minute setup token when prompted (input hidden):
    python submit.py --mode best

Re-running is safe: assignments already marked ``submitted`` are skipped, so an
interrupted window resumes and only the missing ordinals are posted.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import getpass
import json
import os
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from reviewer import prepare_paper, run_pipeline
from reviewer.agent_api import (
    Actor,
    AgentAPIError,
    AgentClient,
    Guidance,
    MockTransport,
    NextAction,
    PrerequisiteCode,
    ReasonCode,
    parse_guidance,
)
from reviewer.api_scores import (
    API_FIELDS,
    public_comments,
    to_api_review,
    validate_api_review,
)
from reviewer.pipeline import REVIEW_AGENT_PATH, _agent_version

ROOT = Path(__file__).resolve().parent
_PREPARED_METADATA_SCHEMA = 1
_SCORE_FIELDS = (
    "soundness",
    "presentation",
    "significance",
    "originality",
    "overall",
    "confidence",
)
_ASSIGNMENT_RESUME_ACTIONS = {
    NextAction.GET_ASSIGNMENTS,
    NextAction.DOWNLOAD_AND_REVIEW_ASSIGNMENTS,
    NextAction.SUBMIT_REVIEW,
}
_ASSIGNMENT_RESUME_REASONS = {
    ReasonCode.ASSIGNMENTS_RETURNED,
    ReasonCode.REVIEWS_REMAINING,
    ReasonCode.REVIEW_WINDOW_OPEN,
    ReasonCode.REVIEW_WINDOW_NOT_OPEN,
}
_NON_AGENT_PREREQUISITE_ACTIONS = {
    NextAction.ASK_HUMAN_FOR_SETUP_TOKEN,
    NextAction.EXCHANGE_SETUP_TOKEN,
    NextAction.SUBMIT_TRACK2_REPORT,
    NextAction.REVOKE_OR_REPLACE_CREDENTIAL,
}
_NON_AGENT_PREREQUISITE_REASONS = {
    ReasonCode.INVALID_SETUP_TOKEN,
    ReasonCode.AUTHENTICATION_REQUIRED,
    ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED,
    ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS,
    ReasonCode.CLAIMABLE_PAPER_NOT_FOUND,
    ReasonCode.UNEXPECTED_AGENT_API_ERROR,
}


def _load_dotenv(path: Path, *, _seen: set[Path] | None = None) -> None:
    """Populate ``os.environ`` from ``.env`` for the optional best-mode keys, for
    keys not already exported. A local file may point at one shared worktree file
    with ``RALPHTHON_ENV_FILE`` so secrets need not be copied. Never consulted in
    --dry-run (kept hermetic)."""

    path = Path(path).expanduser().resolve()
    seen = _seen if _seen is not None else set()
    if path in seen:
        return
    seen.add(path)
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    shared_env = os.environ.get("RALPHTHON_ENV_FILE", "").strip()
    if shared_env:
        shared_path = Path(shared_env).expanduser()
        if not shared_path.is_absolute():
            shared_path = path.parent / shared_path
        _load_dotenv(shared_path, _seen=seen)


def _ordinal(paper: dict) -> int:
    return int(paper["ordinal"])


def _status(paper: dict) -> str:
    return str(paper.get("status") or "").strip().lower()


def _read_setup_token() -> str:
    token = getpass.getpass("Paste the 15-minute setup token (input hidden): ").strip()
    if not token:
        raise SystemExit("no setup token provided")
    return token


@dataclass
class _PreparedSubmission:
    record: dict[str, Any]
    payload: dict[str, Any] | None = None


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256_identity(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == len("sha256:") + 64
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _current_reviewer_identity() -> dict[str, str]:
    """Return the same executable/agent identities frozen by the pipeline."""

    return {
        "agent_version": _agent_version(),
        "review_agent_hash": _sha256_path(REVIEW_AGENT_PATH),
    }


def _assignment_workdir(workdir: Path, ordinal: int) -> Path:
    return workdir / f"paper_{ordinal:02d}"


def _saved_assignment_dir(workdir: Path, ordinal: int) -> Path:
    return workdir / "assigned_papers" / f"ordinal-{ordinal:02d}"


def _save_assigned_paper(raw: bytes, assignment: Mapping[str, Any], workdir: Path) -> Path:
    """Atomically persist one server-assigned paper at a stable local path."""

    ordinal = _ordinal(dict(assignment))
    paper = assignment.get("paper")
    if not isinstance(paper, Mapping):
        raise ValueError("assignment.paper must be an object")
    destination_dir = _saved_assignment_dir(workdir, ordinal)
    destination_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if raw[:5] == b"%PDF-" else ".md"
    destination = destination_dir / f"paper{suffix}"
    temporary = destination.with_name(f".{destination.name}.{time.time_ns()}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    for stale_suffix in ({".pdf", ".md"} - {suffix}):
        (destination_dir / f"paper{stale_suffix}").unlink(missing_ok=True)
    metadata = {
        "ordinal": ordinal,
        "status": _status(dict(assignment)),
        "title": str(paper.get("title", "")).strip(),
        "abstract": str(paper.get("abstract", "")).strip(),
        "file": destination.name,
    }
    metadata_path = destination_dir / "assignment.json"
    metadata_temporary = metadata_path.with_name(
        f".{metadata_path.name}.{time.time_ns()}.tmp"
    )
    metadata_temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata_temporary.replace(metadata_path)
    return destination


def _metadata_path(workdir: Path, ordinal: int) -> Path:
    return _assignment_workdir(workdir, ordinal) / "prepared_payload.json"


def _metadata_artifact(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _payload_scores(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in _SCORE_FIELDS}


def _cached_submission(
    *,
    raw: bytes,
    ordinal: int,
    mode: str,
    workdir: Path,
    reviewer_identity: Mapping[str, str],
    started: float,
) -> _PreparedSubmission | None:
    """Reuse only a fully matched, schema-valid local payload and its artifacts."""

    assignment_dir = _assignment_workdir(workdir, ordinal)
    path = _metadata_path(workdir, ordinal)
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return None
        if metadata.get("schema_version") != _PREPARED_METADATA_SCHEMA:
            return None
        if type(metadata.get("ordinal")) is not int or metadata["ordinal"] != ordinal:
            return None
        if metadata.get("pdf_sha256") != _sha256_bytes(raw):
            return None
        if metadata.get("mode") != mode:
            return None
        if metadata.get("agent_version") != reviewer_identity["agent_version"]:
            return None
        if metadata.get("review_agent_hash") != reviewer_identity["review_agent_hash"]:
            return None
        review_identity = metadata.get("review_identity")
        if not _is_sha256_identity(review_identity):
            return None
        judgment_identity = metadata.get("judgment_identity", "")
        if not isinstance(judgment_identity, str):
            return None
        if judgment_identity and not _is_sha256_identity(judgment_identity):
            return None
        if metadata.get("payload_fields") != list(API_FIELDS):
            return None
        payload = metadata.get("payload")
        if not isinstance(payload, dict) or set(payload) != set(API_FIELDS):
            return None
        validate_api_review(payload)
        if payload["ordinal"] != ordinal:
            return None
        fallback = metadata.get("fallback")
        if type(fallback) is not bool:
            return None
        if mode == "best" and fallback and os.environ.get("RALPH_REUSE_FALLBACK") != "1":
            # A transient committee outage during --no-post must not permanently
            # pin later live submission to the deterministic fallback.
            return None

        artifacts = metadata.get("artifacts")
        if not isinstance(artifacts, dict):
            return None
        paper_path = _metadata_artifact(assignment_dir, artifacts.get("paper"))
        source_path = _metadata_artifact(assignment_dir, artifacts.get("source"))
        review_path = _metadata_artifact(assignment_dir, artifacts.get("review"))
        if (
            paper_path is None
            or source_path is None
            or review_path is None
            or not paper_path.is_file()
            or not source_path.is_file()
            or not review_path.is_file()
        ):
            return None
        if _sha256_path(paper_path) != metadata["pdf_sha256"]:
            return None
        review_text = review_path.read_text(encoding="utf-8").strip()
        if public_comments(review_text) != payload["comments"].strip():
            return None
        if f"- Frozen review identity: `{review_identity}`." not in review_text:
            return None
        if judgment_identity and judgment_identity not in review_text:
            return None
        if reviewer_identity["agent_version"] not in review_text:
            return None
        if reviewer_identity["review_agent_hash"] not in review_text:
            return None
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

    return _PreparedSubmission(
        record={
            "ordinal": ordinal,
            "ok": True,
            "prepared": True,
            "posted": False,
            "fallback": fallback,
            "reused": True,
            "cache_saved": True,
            "submission_status": "prepared",
            "seconds": round(time.time() - started, 2),
            "scores": _payload_scores(payload),
            "review_path": str(review_path),
        },
        payload=payload,
    )


def _write_prepared_metadata(
    *,
    raw: bytes,
    ordinal: int,
    mode: str,
    workdir: Path,
    reviewer_identity: Mapping[str, str],
    paper_path: Path,
    state: Any,
    payload: dict[str, Any],
    fallback: bool,
) -> bool:
    """Atomically index a prepared payload without weakening pipeline freezes."""

    assignment_dir = _assignment_workdir(workdir, ordinal).resolve()
    try:
        validate_api_review(payload)
        if set(payload) != set(API_FIELDS) or payload["ordinal"] != ordinal:
            return False
        if getattr(state, "agent_version", None) != reviewer_identity["agent_version"]:
            return False
        if (
            getattr(state, "review_agent_hash", None)
            != reviewer_identity["review_agent_hash"]
        ):
            return False
        original_identity = getattr(state, "original_identity", None)
        if getattr(original_identity, "sha256", None) != _sha256_bytes(raw):
            return False
        review_identity = getattr(state, "review_identity", None)
        if not _is_sha256_identity(review_identity):
            return False
        judgment_identity = getattr(state, "judgment_identity", "") or ""
        if judgment_identity and not _is_sha256_identity(judgment_identity):
            return False

        source_path = Path(getattr(state, "paper_path")).resolve()
        review_path = Path(getattr(state, "output_path")).resolve()
        resolved_paper = paper_path.resolve()
        for artifact in (resolved_paper, source_path, review_path):
            artifact.relative_to(assignment_dir)
            if not artifact.is_file():
                return False
        if _sha256_path(resolved_paper) != _sha256_bytes(raw):
            return False
        review_text = review_path.read_text(encoding="utf-8").strip()
        if public_comments(review_text) != payload["comments"].strip():
            return False
        if f"- Frozen review identity: `{review_identity}`." not in review_text:
            return False
        if judgment_identity and judgment_identity not in review_text:
            return False

        metadata = {
            "schema_version": _PREPARED_METADATA_SCHEMA,
            "ordinal": ordinal,
            "pdf_sha256": _sha256_bytes(raw),
            "agent_version": reviewer_identity["agent_version"],
            "review_agent_hash": reviewer_identity["review_agent_hash"],
            "review_identity": review_identity,
            "judgment_identity": judgment_identity,
            "mode": mode,
            "payload_fields": list(API_FIELDS),
            "payload": payload,
            "fallback": fallback,
            "artifacts": {
                "paper": resolved_paper.relative_to(assignment_dir).as_posix(),
                "source": source_path.relative_to(assignment_dir).as_posix(),
                "review": review_path.relative_to(assignment_dir).as_posix(),
            },
        }
        destination = _metadata_path(workdir, ordinal)
        temporary = destination.with_name(
            f".{destination.name}.{time.time_ns()}.tmp"
        )
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return True
    except (
        AttributeError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
    ):
        return False


def _used_deterministic_fallback(
    state: Any, requested_mode: str, *, forced: bool = False
) -> bool:
    if requested_mode != "best":
        return False
    if forced or bool(getattr(state, "judgment_error", "")):
        return True
    if hasattr(state, "scientific_judgment"):
        return getattr(state, "scientific_judgment") is None
    return not bool(getattr(state, "judgment", None))


def _prepare_review(
    client: AgentClient,
    paper: dict,
    mode: str,
    workdir: Path,
    reviewer_identity: Mapping[str, str] | None = None,
) -> _PreparedSubmission:
    """Download and review one assignment without mutating server state."""

    ordinal = _ordinal(paper)
    started = time.time()
    try:
        raw = client.fetch_pdf(paper)
        saved_paper_path = _save_assigned_paper(raw, paper, workdir)
        identity = dict(reviewer_identity or _current_reviewer_identity())
        cached = _cached_submission(
            raw=raw,
            ordinal=ordinal,
            mode=mode,
            workdir=workdir,
            reviewer_identity=identity,
            started=started,
        )
        if cached is not None:
            cached.record["saved_paper_path"] = str(saved_paper_path)
            return cached

        assignment_dir = _assignment_workdir(workdir, ordinal)
        assignment_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = Path(
            tempfile.mkdtemp(prefix="build-", dir=assignment_dir)
        )
        # Name the file by its real content: peer inputs are PDFs, but a non-PDF
        # body (an error page, or the mock's Markdown) must not be parsed as a PDF.
        suffix = ".pdf" if raw[:5] == b"%PDF-" else ".md"
        paper_path = artifact_dir / f"paper{suffix}"
        paper_path.write_bytes(raw)

        prepared = prepare_paper(
            paper_path,
            artifact_dir / "source.md",
        )
        out_path = artifact_dir / "review.md"
        forced_fallback = False
        with tempfile.TemporaryDirectory(prefix=f"submit-empty-{ordinal}-") as empty_evidence:
            try:
                state = run_pipeline(
                    paper_path,
                    Path(empty_evidence),
                    out_path,
                    mode=mode,
                    prepared_paper=prepared,
                )
            except Exception:  # noqa: BLE001 — best mode must degrade per paper
                if mode != "best":
                    raise
                forced_fallback = True
                out_path = artifact_dir / "review.fallback.md"
                state = run_pipeline(
                    paper_path,
                    Path(empty_evidence),
                    out_path,
                    mode="audit",
                    prepared_paper=prepared,
                )

        review = to_api_review(state, ordinal)
        fallback = _used_deterministic_fallback(
            state, mode, forced=forced_fallback
        )
        cache_saved = _write_prepared_metadata(
            raw=raw,
            ordinal=ordinal,
            mode=mode,
            workdir=workdir,
            reviewer_identity=identity,
            paper_path=paper_path,
            state=state,
            payload=review,
            fallback=fallback,
        )
        return _PreparedSubmission(
            record={
                "ordinal": ordinal,
                "ok": True,
                "prepared": True,
                "posted": False,
                "fallback": fallback,
                "reused": False,
                "cache_saved": cache_saved,
                "submission_status": "prepared",
                "seconds": round(time.time() - started, 2),
                "scores": _payload_scores(review),
                "review_path": str(out_path),
                "saved_paper_path": str(saved_paper_path),
            },
            payload=review,
        )
    except Exception as error:  # noqa: BLE001 — one bad paper must not sink the batch
        message = (
            _api_error_message(error)
            if isinstance(error, AgentAPIError)
            else f"{type(error).__name__}: review preparation failed"
        )
        return _PreparedSubmission(
            record={
                "ordinal": ordinal,
                "ok": False,
                "prepared": False,
                "posted": False,
                "fallback": False,
                "reused": False,
                "cache_saved": False,
                "submission_status": "not_prepared",
                "seconds": round(time.time() - started, 2),
                "error": message,
            }
        )


def _download_assignment(
    client: AgentClient,
    assignment: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    ordinal = _ordinal(assignment)
    started = time.time()
    try:
        raw = client.fetch_pdf(assignment)
        path = _save_assigned_paper(raw, assignment, workdir)
        return {
            "ordinal": ordinal,
            "ok": True,
            "downloaded": True,
            "seconds": round(time.time() - started, 2),
            "saved_paper_path": str(path),
        }
    except Exception as error:  # noqa: BLE001 — isolate one failed download
        message = (
            _api_error_message(error)
            if isinstance(error, AgentAPIError)
            else f"{type(error).__name__}: assignment download failed"
        )
        return {
            "ordinal": ordinal,
            "ok": False,
            "downloaded": False,
            "seconds": round(time.time() - started, 2),
            "error": message,
        }


def _reason_from_error(error: AgentAPIError) -> ReasonCode:
    if error.guidance is not None:
        reason = error.guidance.reason_code
        if reason in {
            ReasonCode.INVALID_SETUP_TOKEN,
            ReasonCode.AUTHENTICATION_REQUIRED,
            ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED,
            ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS,
            ReasonCode.REVIEW_WINDOW_NOT_OPEN,
            ReasonCode.REVIEW_WINDOW_CLOSED,
            ReasonCode.ACTIVE_ASSIGNMENT_REQUIRED,
            ReasonCode.ASSIGNMENT_NOT_FOUND,
            ReasonCode.CLAIMABLE_PAPER_NOT_FOUND,
            ReasonCode.INVALID_REVIEW_PAYLOAD,
            ReasonCode.REVIEW_SUBMITTED,
            ReasonCode.ALL_REVIEWS_SUBMITTED,
            ReasonCode.UNEXPECTED_AGENT_API_ERROR,
        }:
            return reason
    detail = (error.detail or str(error)).casefold()
    if "invalid setup token" in detail:
        return ReasonCode.INVALID_SETUP_TOKEN
    if "authentication required" in detail:
        return ReasonCode.AUTHENTICATION_REQUIRED
    if "active_track2_report_required" in detail:
        return ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED
    if "insufficient_eligible_papers" in detail:
        return ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS
    if "active assignment required" in detail:
        return ReasonCode.ACTIVE_ASSIGNMENT_REQUIRED
    if "assignment not found" in detail:
        return ReasonCode.ASSIGNMENT_NOT_FOUND
    if "claimable paper not found" in detail:
        return ReasonCode.CLAIMABLE_PAPER_NOT_FOUND
    if "invalid_review_payload" in detail:
        return ReasonCode.INVALID_REVIEW_PAYLOAD
    if "writable from 16:35 until 17:00" in detail:
        if (
            error.guidance is not None
            and (
                error.guidance.terminal
                or error.guidance.time.window_closed
            )
        ):
            return ReasonCode.REVIEW_WINDOW_CLOSED
        return ReasonCode.REVIEW_WINDOW_NOT_OPEN
    return ReasonCode.UNEXPECTED_AGENT_API_ERROR


def _api_error_message(error: AgentAPIError) -> str:
    if error.transient:
        return (
            "transient network/5xx failure remained after bounded retries; "
            "preserve the prepared review and stop automatic submission. "
            + _error_context(error)
        )
    reason = _reason_from_error(error)
    if reason is ReasonCode.INVALID_SETUP_TOKEN:
        return (
            "invalid setup token — ask the human for a newly issued setup token; "
            "do not infer whether it expired, was used, or was revoked."
        )
    if reason is ReasonCode.AUTHENTICATION_REQUIRED:
        return (
            "authentication required — ask the human to re-provision the agent "
            "credential; browser cookies are not valid agent authentication."
        )
    if reason is ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED:
        return (
            "active Track 2 report required — the human must submit it in the "
            "browser before the cutoff; the agent has no API action."
        )
    if reason is ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS:
        return (
            "insufficient eligible papers — unmet server prerequisite; stopping "
            "without polling."
        )
    if reason in {
        ReasonCode.REVIEW_WINDOW_NOT_OPEN,
        ReasonCode.REVIEW_WINDOW_CLOSED,
    }:
        return (
            "review write window is unavailable — follow the returned KST "
            "boundary; do not retry this request unchanged."
        )
    if reason in {
        ReasonCode.ACTIVE_ASSIGNMENT_REQUIRED,
        ReasonCode.ASSIGNMENT_NOT_FOUND,
    }:
        return (
            "assignment state must be refreshed; the rejected POST will not be "
            "retried unchanged."
        )
    if reason is ReasonCode.CLAIMABLE_PAPER_NOT_FOUND:
        return "claimable paper not found — stop without guessing eligibility."
    if reason is ReasonCode.INVALID_REVIEW_PAYLOAD:
        return (
            "invalid review payload — preserve the prepared review and correct it "
            "before any write-window resubmission."
        )
    if reason is ReasonCode.ALL_REVIEWS_SUBMITTED:
        return "all reviews are already submitted — stop successfully."
    return (
        "unexpected agent API error — stop and inspect the returned status, "
        "reason, and KST timing. "
        + _error_context(error)
    )


def _error_context(error: AgentAPIError) -> str:
    guidance = error.guidance
    detail = " ".join((error.detail or "<unknown>").split())[:300]
    reason = (
        guidance.reason_code.value
        if guidance is not None
        else ReasonCode.UNEXPECTED_AGENT_API_ERROR.value
    )
    if guidance is None:
        return (
            f"status={error.status_code} detail={detail} reason={reason} "
            "now=<unknown> window_opens_at=<unknown> "
            "window_closes_at=<unknown>"
        )
    return (
        f"status={error.status_code} detail={detail} reason={reason} "
        f"now={guidance.time.now.isoformat()} "
        "window_opens_at="
        f"{guidance.time.window_opens_at.isoformat() if guidance.time.window_opens_at else None} "
        "window_closes_at="
        f"{guidance.time.window_closes_at.isoformat() if guidance.time.window_closes_at else None}"
    )


def _guidance_stop_message(guidance: Guidance) -> str:
    reason = guidance.reason_code
    if reason is ReasonCode.ALL_REVIEWS_SUBMITTED:
        return "all reviews submitted — no further action."
    if reason is ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS:
        return "insufficient eligible papers — server prerequisite unmet; no polling."
    if reason is ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED:
        return "active Track 2 report required from the human browser; no agent action."
    if reason is ReasonCode.REVIEW_WINDOW_CLOSED or guidance.time.window_closed:
        return "review window closed at the returned KST boundary; no further writes."
    if reason is ReasonCode.UNEXPECTED_AGENT_API_ERROR:
        return (
            "unexpected agent API state; stopping without guessing. "
            f"reason={reason.value} now={guidance.time.now.isoformat()} "
            "window_opens_at="
            f"{guidance.time.window_opens_at.isoformat() if guidance.time.window_opens_at else None} "
            "window_closes_at="
            f"{guidance.time.window_closes_at.isoformat() if guidance.time.window_closes_at else None}"
        )
    return (
        f"guidance is terminal ({reason.value}, next_action=none); "
        "nothing to do."
    )


def _submission_guidance(client: AgentClient) -> Guidance:
    """Refresh status and perform at most one matrix-directed status refresh."""

    guidance = parse_guidance(client.status())
    if guidance.can_submit_review or guidance.terminal:
        return guidance
    if guidance.next_action is NextAction.CHECK_STATUS:
        wait_seconds = guidance.time.seconds_until_window
        if wait_seconds is not None:
            print(
                "review window not open; waiting once until returned KST boundary "
                f"({wait_seconds:.0f}s)."
            )
            time.sleep(wait_seconds)
        return parse_guidance(client.status())
    return guidance


def _refresh_assignments_after_error(
    client: AgentClient, error: AgentAPIError
) -> bool:
    """Perform the matrix-directed GET refresh, never a retry of the rejected POST."""

    reason = _reason_from_error(error)
    if reason not in {
        ReasonCode.ACTIVE_ASSIGNMENT_REQUIRED,
        ReasonCode.ASSIGNMENT_NOT_FOUND,
    }:
        return False
    guidance = error.guidance
    if guidance is not None and (
        guidance.terminal or guidance.time.window_closed
    ):
        return False
    client.assignments()
    return True


def _plain_count(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if type(value) is int and value >= 0 else None


def _non_agent_prerequisite_failure(guidance: Guidance) -> bool:
    return (
        guidance.reason_code in _NON_AGENT_PREREQUISITE_REASONS
        or guidance.next_action in _NON_AGENT_PREREQUISITE_ACTIONS
        or guidance.next_action_actor is Actor.HUMAN
    )


def _status_indicates_allocated(
    status: Mapping[str, Any], guidance: Guidance
) -> bool:
    fixed = guidance.prerequisite(PrerequisiteCode.FIXED_TEN_ALLOCATED)
    if fixed is not None and fixed.satisfied:
        return True
    assigned = _plain_count(status, "assigned")
    submitted = _plain_count(status, "submitted")
    remaining = _plain_count(status, "remaining")
    if assigned == 10:
        return True
    return (
        submitted is not None
        and remaining is not None
        and submitted + remaining == 10
        and (submitted > 0 or remaining > 0)
    )


def _should_fetch_current_assignments(
    status: Mapping[str, Any], guidance: Guidance
) -> bool:
    """Return whether startup state safely directs a current fixed-set read."""

    if guidance.terminal or _non_agent_prerequisite_failure(guidance):
        return False
    allocated = _status_indicates_allocated(status, guidance)
    if guidance.next_action_actor is Actor.SERVER and not allocated:
        return False
    return (
        guidance.next_action in _ASSIGNMENT_RESUME_ACTIONS
        or guidance.reason_code in _ASSIGNMENT_RESUME_REASONS
        or allocated
    )


def _can_prepare_current_assignments(guidance: Guidance) -> bool:
    """Accept initial and resume guidance once a valid fixed set was fetched."""

    if guidance.terminal or _non_agent_prerequisite_failure(guidance):
        return False
    fixed = guidance.prerequisite(PrerequisiteCode.FIXED_TEN_ALLOCATED)
    return (
        guidance.can_prepare_assignments
        or guidance.next_action in _ASSIGNMENT_RESUME_ACTIONS
        or guidance.reason_code in _ASSIGNMENT_RESUME_REASONS
        or (
            fixed is not None
            and fixed.satisfied
            and guidance.next_action is NextAction.CHECK_STATUS
        )
    )


def _startup_status(client: AgentClient) -> tuple[dict[str, Any], Guidance]:
    """Read status once, with one additional refresh for ``check_status``."""

    status = client.status()
    guidance = parse_guidance(status)
    if (
        not guidance.terminal
        and not _non_agent_prerequisite_failure(guidance)
        and guidance.next_action is NextAction.CHECK_STATUS
    ):
        status = client.status()
        guidance = parse_guidance(status)
    return status, guidance


def _run_counts(
    *,
    assigned: int,
    selected: int,
    skipped: int,
    results: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "assigned": assigned,
        "selected": selected,
        "prepared": sum(bool(record.get("prepared")) for record in results),
        "posted": sum(bool(record.get("posted")) for record in results),
        "fallback": sum(
            bool(record.get("prepared")) and bool(record.get("fallback"))
            for record in results
        ),
        "failed": sum(not bool(record.get("ok")) for record in results),
        "skipped": skipped,
    }


def _write_run_report(
    *,
    workdir: Path,
    mode: str,
    post_requested: bool,
    submission_blocked: bool,
    counts: Mapping[str, int],
    results: list[dict[str, Any]],
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    report_path = workdir / "run_report.json"
    report_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "posted": post_requested,
                "post_requested": post_requested,
                "submission_blocked": submission_blocked,
                "counts": dict(counts),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_path


def _print_counts(counts: Mapping[str, int]) -> None:
    print(
        "counts: "
        f"assigned={counts['assigned']} selected={counts['selected']} "
        f"prepared={counts['prepared']} posted={counts['posted']} "
        f"fallback={counts['fallback']} failed={counts['failed']} "
        f"skipped={counts['skipped']}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("audit", "best"), default="best",
                        help="review mode for the live POST (default: best; --dry-run always uses audit)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the full flow against the in-memory mock (no token, no network)")
    parser.add_argument("--no-post", action="store_true",
                        help="build and validate reviews but do NOT submit them")
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="download the fixed assignments to <workdir>/assigned_papers and stop",
    )
    parser.add_argument("--only", type=int, default=None, metavar="ORD",
                        help="review/submit a single assignment ordinal (1..10)")
    parser.add_argument("--resubmit", action="store_true",
                        help="also re-post ordinals the platform already lists as submitted")
    parser.add_argument("--workdir", type=Path, default=ROOT / "submit_work",
                        help="where downloaded papers and reviews are written")
    parser.add_argument("--workers", type=int, default=None,
                        help="parallel paper workers (default: 3 in best mode, otherwise up to 10)")
    parser.add_argument("--base-url", default=None, help="override the API base URL (testing only)")
    return parser


def main() -> int:
    args = _parser().parse_args()
    default_workdir = ROOT / "submit_work"
    if args.dry_run and args.workdir == default_workdir:
        args.workdir = default_workdir / f"dry-run-{time.time_ns()}"
    mode = (
        "audit"
        if args.dry_run or args.download_only
        else args.mode
    )  # download-only and dry-run never need model credentials
    if args.workers is not None and args.workers < 1:
        print("--workers must be at least 1.")
        return 2
    if args.base_url and not args.dry_run:
        print("--base-url is restricted to --dry-run with the injected mock transport.")
        return 2
    if mode == "best" and not args.dry_run:
        _load_dotenv(ROOT / ".env")

    if args.dry_run:
        client = AgentClient(
            transport=MockTransport(),
            base_url=args.base_url or "https://openagentreview.org",
        )
        print("DRY RUN — in-memory mock, no token, no network. Mode forced to audit.")
    else:
        client = AgentClient(base_url=args.base_url or "https://openagentreview.org")

    try:
        client.fetch_skill()
    except AgentAPIError as error:
        print(f"startup contract fetch stopped: {_api_error_message(error)}")
        return 1

    setup_token = "dry-run" if args.dry_run else _read_setup_token()

    try:
        client.exchange_setup_token(setup_token)
    except AgentAPIError as error:
        print(f"credential exchange stopped: {_api_error_message(error)}")
        return 1
    del setup_token  # not needed past the one exchange

    try:
        status, guidance = _startup_status(client)
    except AgentAPIError as error:
        print(f"status stopped: {_api_error_message(error)}")
        return 0 if error.guidance is not None and error.guidance.terminal else 1
    status_assigned = _plain_count(status, "assigned")
    status_submitted = _plain_count(status, "submitted")
    status_remaining = _plain_count(status, "remaining")
    print(
        "status: "
        f"assigned={status_assigned if status_assigned is not None else '?'} "
        f"submitted={status_submitted if status_submitted is not None else '?'} "
        f"remaining={status_remaining if status_remaining is not None else '?'}"
    )
    if guidance.terminal:
        print(_guidance_stop_message(guidance))
        return 0
    if not _should_fetch_current_assignments(status, guidance):
        if _non_agent_prerequisite_failure(guidance):
            print(
                "cannot acquire assignments: the returned human/server "
                f"prerequisite is unmet (reason={guidance.reason_code.value})."
            )
            return 0
        print(
            "unexpected status guidance — current assignments were not fetched "
            f"(reason={guidance.reason_code.value}, "
            f"next_action={guidance.next_action.value})."
        )
        return 1

    try:
        full_assignment_set = client.assignments()
        assignment_guidance = client.guidance
    except AgentAPIError as error:
        print(f"assignment acquisition stopped: {_api_error_message(error)}")
        return 0 if error.guidance is not None and error.guidance.terminal else 1
    if assignment_guidance.terminal:
        print(_guidance_stop_message(assignment_guidance))
        return 0
    if not _can_prepare_current_assignments(assignment_guidance):
        print(
            "assignment guidance does not permit preparation "
            f"(reason={assignment_guidance.reason_code.value}, "
            f"next_action={assignment_guidance.next_action.value})."
        )
        return 1
    assigned_count = len(full_assignment_set)
    papers = list(full_assignment_set)
    if args.only is not None:
        papers = [paper for paper in papers if _ordinal(paper) == args.only]
        if not papers:
            print(f"ordinal {args.only} is not in the current assignment set.")
            counts = _run_counts(
                assigned=assigned_count,
                selected=0,
                skipped=0,
                results=[],
            )
            _print_counts(counts)
            report_path = _write_run_report(
                workdir=args.workdir,
                mode=mode,
                post_requested=not args.no_post,
                submission_blocked=False,
                counts=counts,
                results=[],
            )
            print(f"report: {report_path}")
            return 1
    selected_count = len(papers)

    if args.download_only:
        args.workdir.mkdir(parents=True, exist_ok=True)
        workers = args.workers or min(10, selected_count)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            downloads = list(
                executor.map(
                    lambda assignment: _download_assignment(
                        client,
                        assignment,
                        args.workdir,
                    ),
                    sorted(papers, key=_ordinal),
                )
            )
        downloads.sort(key=lambda record: record["ordinal"])
        downloaded = sum(bool(record.get("downloaded")) for record in downloads)
        manifest_path = args.workdir / "assigned_papers" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "assigned": assigned_count,
                    "selected": selected_count,
                    "downloaded": downloaded,
                    "failed": selected_count - downloaded,
                    "results": downloads,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"downloaded {downloaded}/{selected_count} assignment(s) to "
            f"{manifest_path.parent}"
        )
        for record in downloads:
            if record["ok"]:
                print(f"  ✓ #{record['ordinal']:<2} {record['saved_paper_path']}")
            else:
                print(f"  ✗ #{record['ordinal']:<2} {record['error']}")
        print(f"manifest: {manifest_path}")
        return 1 if downloaded != selected_count else 0

    todo, skipped = [], []
    for paper in sorted(papers, key=_ordinal):
        if _status(paper) == "submitted" and not args.resubmit:
            skipped.append(paper)
        else:
            todo.append(paper)
    for paper in skipped:
        print(f"  · skip  #{_ordinal(paper):<2} already submitted")
    args.workdir.mkdir(parents=True, exist_ok=True)
    if not todo:
        print("all selected assignments are already submitted.")
        counts = _run_counts(
            assigned=assigned_count,
            selected=selected_count,
            skipped=len(skipped),
            results=[],
        )
        _print_counts(counts)
        report_path = _write_run_report(
            workdir=args.workdir,
            mode=mode,
            post_requested=not args.no_post,
            submission_blocked=False,
            counts=counts,
            results=[],
        )
        print(f"report: {report_path}")
        return 0

    workers = args.workers or min(3 if mode == "best" else 10, len(todo))
    print(
        f"prepare {len(todo)} paper(s) "
        f"[mode={mode}, workers={workers}, post={not args.no_post}]"
    )

    wall_start = time.time()
    try:
        reviewer_identity = _current_reviewer_identity()
    except Exception as error:  # noqa: BLE001 — preserve one record per assignment
        results = [
            {
                "ordinal": _ordinal(paper),
                "ok": False,
                "prepared": False,
                "posted": False,
                "fallback": False,
                "reused": False,
                "cache_saved": False,
                "submission_status": "not_prepared",
                "seconds": 0.0,
                "error": f"{type(error).__name__}: reviewer identity unavailable",
            }
            for paper in todo
        ]
        counts = _run_counts(
            assigned=assigned_count,
            selected=selected_count,
            skipped=len(skipped),
            results=results,
        )
        _print_counts(counts)
        report_path = _write_run_report(
            workdir=args.workdir,
            mode=mode,
            post_requested=not args.no_post,
            submission_blocked=False,
            counts=counts,
            results=results,
        )
        print(f"report: {report_path}")
        return 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _prepare_review,
                client,
                paper,
                mode,
                args.workdir,
                reviewer_identity,
            ): paper
            for paper in todo
        }
        prepared = [
            future.result()
            for future in concurrent.futures.as_completed(futures)
        ]
    prepared.sort(key=lambda item: item.record["ordinal"])

    for item in prepared:
        if item.record.get("prepared"):
            item.record["submission_status"] = (
                "not_requested" if args.no_post else "pending"
            )

    submission_blocked = False
    stop_status: str | None = None
    if not args.no_post:
        for item in prepared:
            record = item.record
            if not record["ok"] or item.payload is None:
                continue
            try:
                post_guidance = _submission_guidance(client)
            except AgentAPIError as error:
                record["ok"] = False
                record["error"] = _api_error_message(error)
                record["submission_status"] = "failed"
                submission_blocked = True
                stop_status = "blocked"
                break
            if post_guidance.terminal:
                print(_guidance_stop_message(post_guidance))
                record["submission_status"] = "not_needed"
                stop_status = "not_needed"
                break
            if not post_guidance.can_submit_review:
                print(
                    "submission blocked by refreshed guidance "
                    f"(reason={post_guidance.reason_code.value}, "
                    f"next_action={post_guidance.next_action.value}, "
                    f"action_available={post_guidance.action_available})."
                )
                record["submission_status"] = "blocked"
                submission_blocked = True
                stop_status = "blocked"
                break
            try:
                client.post_review(item.payload)
                record["posted"] = True
                record["submission_status"] = "posted"
            except AgentAPIError as error:
                if error.guidance is not None and error.guidance.terminal:
                    print(_guidance_stop_message(error.guidance))
                    if error.guidance.reason_code is ReasonCode.ALL_REVIEWS_SUBMITTED:
                        record["submission_status"] = "not_needed"
                        stop_status = "not_needed"
                    else:
                        record["ok"] = False
                        record["error"] = _api_error_message(error)
                        record["submission_status"] = "failed"
                        submission_blocked = True
                        stop_status = "blocked"
                    break
                refreshed = False
                try:
                    refreshed = _refresh_assignments_after_error(client, error)
                except AgentAPIError as refresh_error:
                    record["ok"] = False
                    record["error"] = (
                        f"{_api_error_message(error)} Assignment refresh also "
                        f"failed: {_api_error_message(refresh_error)}"
                    )
                    record["submission_status"] = "failed"
                    submission_blocked = True
                    stop_status = "blocked"
                    break
                record["ok"] = False
                record["error"] = _api_error_message(error)
                record["submission_status"] = "failed"
                if refreshed:
                    record["error"] += " Current assignments were refreshed."
                reason = _reason_from_error(error)
                if reason is ReasonCode.INVALID_REVIEW_PAYLOAD:
                    continue
                submission_blocked = True
                stop_status = "blocked"
                break

            response_guidance = client.guidance
            if response_guidance.reason_code is ReasonCode.ALL_REVIEWS_SUBMITTED:
                print(_guidance_stop_message(response_guidance))
                stop_status = "not_needed"
                break
            if response_guidance.terminal:
                print(_guidance_stop_message(response_guidance))
                stop_status = "not_needed"
                break

    if stop_status is not None:
        for item in prepared:
            if item.record.get("submission_status") == "pending":
                item.record["submission_status"] = stop_status

    results = [item.record for item in prepared]
    wall = time.time() - wall_start
    counts = _run_counts(
        assigned=assigned_count,
        selected=selected_count,
        skipped=len(skipped),
        results=results,
    )

    print(f"\ndone in {wall:.1f}s")
    _print_counts(counts)
    for record in results:
        if record["ok"]:
            scores = record["scores"]
            flag = (
                "posted"
                if record["posted"]
                else "reused"
                if record.get("reused")
                else "built"
            )
            fallback = " fallback" if record.get("fallback") else ""
            print(
                f"  ✓ #{record['ordinal']:<2} {flag}{fallback} "
                f"{record['seconds']:>5.1f}s  "
                f"overall={scores['overall']}/6 sound={scores['soundness']} "
                f"pres={scores['presentation']} signif={scores['significance']} "
                f"orig={scores['originality']} conf={scores['confidence']}"
            )
        else:
            print(f"  ✗ #{record['ordinal']:<2} {record['seconds']:>5.1f}s  {record['error']}")

    report_path = _write_run_report(
        workdir=args.workdir,
        mode=mode,
        post_requested=not args.no_post,
        submission_blocked=submission_blocked,
        counts=counts,
        results=results,
    )
    print(f"report: {report_path}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
