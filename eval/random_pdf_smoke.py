#!/usr/bin/env python3
"""Fresh-random arXiv PDF smoke test with replayable, hash-pinned manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reviewer import prepare_paper, run_pipeline  # noqa: E402
from reviewer.review_schema import SCIENTIFIC_AXES  # noqa: E402


ARXIV_CATEGORIES: tuple[str, ...] = (
    "cs.LG",
    "stat.ML",
    "cs.AI",
    "cs.CL",
    "cs.CV",
)
ARXIV_API_URL = "https://export.arxiv.org/api/query"
DEFAULT_RUNS_DIR = ROOT / "eval" / "random_pdf_runs"
MANIFEST_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
DEFAULT_COUNT = 5
DEFAULT_PER_CATEGORY = 20
DEFAULT_MAX_RUNTIME_SECONDS = 300.0
KST = timezone(timedelta(hours=9), name="KST")

Fetch = Callable[[str], bytes]
PreparePaper = Callable[..., Any]
RunPipeline = Callable[..., Any]

_ATOM = {"atom": "http://www.w3.org/2005/Atom"}
_ARXIV = {"arxiv": "http://arxiv.org/schemas/atom"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRACE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REQUIRED_PAPER_FIELDS = ("arxiv_id", "title", "category", "pdf_url", "sha256")
_REQUIRED_REVIEW_SECTIONS = (
    "## Paper and Evidence Identity",
    "## Summary",
    "## Strengths",
    "## Weaknesses",
    "## Questions for the Authors",
    "## Scores",
    "## Ethics and Limitations",
    "## Evidence Trace",
    "## Comment",
)
_SCORE_RANGES: dict[str, tuple[int, int]] = {
    "Soundness": (1, 4),
    "Presentation": (1, 4),
    "Significance": (1, 4),
    "Originality": (1, 4),
    "Overall recommendation": (1, 6),
    "Confidence": (1, 5),
}


class SmokeValidationError(ValueError):
    """A downloaded paper or generated review failed the smoke contract."""


def resolve_seed(seed: int | None) -> int:
    """Return an explicit seed, or generate and expose a fresh 64-bit seed."""

    if seed is None:
        return secrets.randbits(64)
    if type(seed) is not int:
        raise TypeError(f"seed must be an integer, got {type(seed).__name__}")
    return seed


def _kst_timestamp(now_fn: Callable[[], datetime] | None = None) -> str:
    moment = now_fn() if now_fn is not None else datetime.now(KST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).isoformat(timespec="seconds")


def _fetch_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "paper-review-smoke/1.0 (random PDF smoke)",
            "Accept": "application/pdf, application/atom+xml;q=0.9, */*;q=0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def build_arxiv_query_url(category: str, max_results: int = DEFAULT_PER_CATEGORY) -> str:
    """Build a newest-first public Atom query for one requested category."""

    if category not in ARXIV_CATEGORIES:
        raise ValueError(f"unsupported arXiv category: {category!r}")
    if type(max_results) is not int or max_results < 1:
        raise ValueError("max_results must be a positive integer")
    query = urllib.parse.urlencode(
        {
            "search_query": f"cat:{category}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    return f"{ARXIV_API_URL}?{query}"


def _entry_arxiv_id(entry: ET.Element) -> str:
    raw_id = (entry.findtext("atom:id", default="", namespaces=_ATOM) or "").strip()
    if not raw_id:
        raise ValueError("arXiv entry is missing its id")
    marker = "/abs/"
    arxiv_id = raw_id.split(marker, 1)[1] if marker in raw_id else raw_id.rsplit("/", 1)[-1]
    arxiv_id = arxiv_id.strip().strip("/")
    if not arxiv_id:
        raise ValueError(f"could not parse arXiv id from {raw_id!r}")
    return arxiv_id


def _entry_category(entry: ET.Element, queried_category: str | None) -> str:
    terms = [
        str(element.attrib.get("term", "")).strip()
        for element in entry.findall("atom:category", _ATOM)
    ]
    primary = entry.find("arxiv:primary_category", _ARXIV)
    primary_term = str(primary.attrib.get("term", "")).strip() if primary is not None else ""
    if queried_category and queried_category in ARXIV_CATEGORIES:
        return queried_category
    if primary_term in ARXIV_CATEGORIES:
        return primary_term
    tracked = next((term for term in terms if term in ARXIV_CATEGORIES), "")
    if tracked:
        return tracked
    raise ValueError("arXiv entry has no tracked category")


def _entry_pdf_url(entry: ET.Element, arxiv_id: str) -> str:
    for link in entry.findall("atom:link", _ATOM):
        media_type = str(link.attrib.get("type", "")).lower()
        title = str(link.attrib.get("title", "")).lower()
        href = str(link.attrib.get("href", "")).strip()
        if href and (media_type == "application/pdf" or title == "pdf"):
            return href.replace("http://", "https://", 1)
    return f"https://arxiv.org/pdf/{arxiv_id}"


def parse_atom_feed(payload: bytes, category: str | None = None) -> list[dict[str, str]]:
    """Parse an arXiv Atom response into manifest-ready paper metadata."""

    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise ValueError("arXiv feed response is empty")
    root = ET.fromstring(bytes(payload))
    papers: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", _ATOM):
        arxiv_id = _entry_arxiv_id(entry)
        title = " ".join(
            (entry.findtext("atom:title", default="", namespaces=_ATOM) or "").split()
        )
        if not title:
            raise ValueError(f"arXiv entry {arxiv_id!r} is missing its title")
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "category": _entry_category(entry, category),
                "pdf_url": _entry_pdf_url(entry, arxiv_id),
            }
        )
    return papers


def discover_recent_papers(
    *,
    fetch_feed: Fetch | None = None,
    categories: Sequence[str] = ARXIV_CATEGORIES,
    per_category: int = DEFAULT_PER_CATEGORY,
) -> list[dict[str, str]]:
    """Query each requested category and de-duplicate recent Atom entries."""

    fetch = fetch_feed or _fetch_url
    discovered: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for category in categories:
        url = build_arxiv_query_url(category, per_category)
        for paper in parse_atom_feed(fetch(url), category):
            if paper["arxiv_id"] in seen_ids:
                continue
            seen_ids.add(paper["arxiv_id"])
            discovered.append(paper)
    return discovered


def select_diverse_papers(
    papers: Iterable[Mapping[str, str]],
    *,
    count: int,
    seed: int,
) -> list[dict[str, str]]:
    """Select deterministically from shuffled category buckets, round-robin."""

    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for item in papers:
        paper = {field: str(item.get(field, "")).strip() for field in _REQUIRED_PAPER_FIELDS[:-1]}
        if not all(paper.values()) or paper["arxiv_id"] in seen:
            continue
        seen.add(paper["arxiv_id"])
        buckets.setdefault(paper["category"], []).append(paper)

    available = sum(len(bucket) for bucket in buckets.values())
    if available < count:
        raise ValueError(f"requested {count} papers, but discovery returned only {available}")

    for bucket in buckets.values():
        rng.shuffle(bucket)
    category_order = [category for category in ARXIV_CATEGORIES if buckets.get(category)]
    category_order.extend(sorted(set(buckets) - set(category_order)))
    rng.shuffle(category_order)

    selected: list[dict[str, str]] = []
    while len(selected) < count:
        made_progress = False
        for category in category_order:
            bucket = buckets[category]
            if bucket:
                selected.append(bucket.pop())
                made_progress = True
                if len(selected) == count:
                    break
        if not made_progress:  # defensive: availability was checked above
            break
        rng.shuffle(category_order)
    return selected


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_stem(arxiv_id: str) -> str:
    stem = _SAFE_STEM_RE.sub("_", arxiv_id).strip("._")
    return stem or hashlib.sha256(arxiv_id.encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_manifest_timestamp(value: object) -> None:
    if not isinstance(value, str):
        raise SmokeValidationError("manifest created_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise SmokeValidationError("manifest created_at is not a valid ISO timestamp") from error
    if parsed.utcoffset() != timedelta(hours=9):
        raise SmokeValidationError("manifest created_at must use KST (+09:00)")


def validate_manifest(value: object) -> dict[str, Any]:
    """Validate and normalize a schema-v1 manifest before replay."""

    if not isinstance(value, dict):
        raise SmokeValidationError("manifest root must be a JSON object")
    if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SmokeValidationError(
            f"unsupported manifest schema_version: {value.get('schema_version')!r}"
        )
    if type(value.get("seed")) is not int:
        raise SmokeValidationError("manifest seed must be an integer")
    mode = value.get("mode")
    if mode not in {"audit", "best"}:
        raise SmokeValidationError("manifest mode must be 'audit' or 'best'")
    _validate_manifest_timestamp(value.get("created_at"))
    raw_papers = value.get("papers")
    if not isinstance(raw_papers, list):
        raise SmokeValidationError("manifest papers must be a list")

    normalized_papers: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw_paper in enumerate(raw_papers):
        if not isinstance(raw_paper, dict):
            raise SmokeValidationError(f"manifest paper {index} must be an object")
        missing = [field for field in _REQUIRED_PAPER_FIELDS if field not in raw_paper]
        if missing:
            raise SmokeValidationError(
                f"manifest paper {index} is missing fields: {', '.join(missing)}"
            )
        paper = {field: str(raw_paper[field]).strip() for field in _REQUIRED_PAPER_FIELDS}
        if not all(paper.values()):
            raise SmokeValidationError(f"manifest paper {index} has an empty required field")
        if paper["category"] not in ARXIV_CATEGORIES:
            raise SmokeValidationError(
                f"manifest paper {index} has unsupported category {paper['category']!r}"
            )
        paper["sha256"] = paper["sha256"].lower()
        if not _SHA256_RE.fullmatch(paper["sha256"]):
            raise SmokeValidationError(f"manifest paper {index} has an invalid sha256")
        if paper["arxiv_id"] in seen_ids:
            raise SmokeValidationError(
                f"manifest contains duplicate arXiv id {paper['arxiv_id']!r}"
            )
        seen_ids.add(paper["arxiv_id"])
        normalized_papers.append(paper)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "seed": value["seed"],
        "created_at": value["created_at"],
        "mode": mode,
        "papers": normalized_papers,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SmokeValidationError(f"manifest is not valid JSON: {manifest_path}") from error
    return validate_manifest(value)


def _attribute_or_key(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _best_question_count(state: object) -> int | None:
    scientific = getattr(state, "scientific_judgment", None)
    scientific_questions = _attribute_or_key(scientific, "questions", None)
    if isinstance(scientific_questions, (list, tuple)):
        return len(scientific_questions)

    judgment = getattr(state, "judgment", None)
    if not judgment:
        return None
    success = any(
        _attribute_or_key(judgment, key, False) is True
        for key in ("model_ok", "ok", "succeeded", "valid")
    )
    if not success:
        return None

    explicit = _attribute_or_key(judgment, "questions", None)
    if isinstance(explicit, (list, tuple)):
        return len(explicit)

    comments = _attribute_or_key(judgment, "comments", ())
    count = 0
    for comment in comments if isinstance(comments, (list, tuple)) else ():
        stance = str(_attribute_or_key(comment, "stance", "")).strip().lower()
        text = str(_attribute_or_key(comment, "text", comment)).strip()
        if stance == "question" or re.match(r"^(?:\d+[.)]\s*)?Question\b", text, re.I):
            count += 1
    return count


def _scientific_snapshot(state: object, mode: str) -> dict[str, Any]:
    """Return non-secret committee status for a smoke report."""

    if mode != "best":
        return {
            "scientific_status": "not_requested",
            "judgment_identity": None,
            "scientific_latency_seconds": None,
        }

    judgment = getattr(state, "scientific_judgment", None)
    identity = getattr(state, "judgment_identity", "")
    provenance = getattr(state, "committee_provenance", None)
    latency: float | None = None
    if isinstance(provenance, Mapping):
        candidate = provenance.get("runtime_seconds")
        if (
            type(candidate) in {int, float}
            and math.isfinite(float(candidate))
            and float(candidate) >= 0
        ):
            latency = float(candidate)
    if judgment is None:
        return {
            "scientific_status": "fallback",
            "judgment_identity": None,
            "scientific_latency_seconds": latency,
        }

    return {
        "scientific_status": "committee",
        "judgment_identity": identity,
        "scientific_latency_seconds": latency,
    }


def validate_review(
    *,
    pdf_path: Path,
    expected_sha256: str,
    prepared: object,
    state: object,
    review_path: Path,
    runtime_seconds: float,
    mode: str,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    """Validate the original PDF, extraction, review structure, scores, and trace."""

    errors: list[str] = []
    payload = pdf_path.read_bytes()
    actual_sha256 = _sha256(payload)
    if actual_sha256 != expected_sha256:
        errors.append(
            f"downloaded PDF sha256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    original = getattr(prepared, "original", None)
    prepared_hash = getattr(original, "sha256", None)
    if prepared_hash != expected_sha256:
        errors.append(
            f"prepared original sha256 mismatch: expected {expected_sha256}, got {prepared_hash}"
        )
    state_original = getattr(state, "original_identity", None)
    state_hash = getattr(state_original, "sha256", None)
    if state_hash != expected_sha256:
        errors.append(
            f"pipeline original sha256 mismatch: expected {expected_sha256}, got {state_hash}"
        )

    prepared_pages = getattr(original, "page_count", None)
    state_pages = getattr(state, "page_count", None)
    if (
        type(prepared_pages) is not int
        or prepared_pages < 1
        or type(state_pages) is not int
        or state_pages != prepared_pages
    ):
        errors.append(
            f"invalid PDF page count: prepared={prepared_pages!r}, pipeline={state_pages!r}"
        )

    extracted = getattr(prepared, "analysis_text", None)
    if not isinstance(extracted, str) or not extracted.strip():
        errors.append("PDF extraction is empty")

    scores = getattr(state, "scores", None)
    if not isinstance(scores, Mapping):
        errors.append("pipeline scores are missing")
        scores = {}
    flat_scores: dict[str, int] = {}
    for name, (low, high) in _SCORE_RANGES.items():
        score = scores.get(name) if isinstance(scores, Mapping) else None
        value = score.get("value") if isinstance(score, Mapping) else None
        if type(value) is not int or not low <= value <= high:
            errors.append(f"{name} score must be an integer in {low}..{high}, got {value!r}")
        else:
            flat_scores[name] = value

    review_text = getattr(state, "review_markdown", None)
    if not isinstance(review_text, str) or not review_text.strip():
        errors.append("pipeline review Markdown is empty")
        review_text = ""
    if not review_path.is_file() or not review_path.read_text(encoding="utf-8").strip():
        errors.append("pipeline did not persist a non-empty review file")
    for section in _REQUIRED_REVIEW_SECTIONS:
        if section not in review_text:
            errors.append(f"review is missing required section {section!r}")

    review_identity = getattr(state, "review_identity", "")
    verdict_digest = getattr(state, "verdict_digest", "")
    if not isinstance(review_identity, str) or not _TRACE_DIGEST_RE.fullmatch(review_identity):
        errors.append(f"invalid review identity digest: {review_identity!r}")
    elif review_identity not in review_text:
        errors.append("review identity digest is absent from the Evidence Trace")
    if not isinstance(verdict_digest, str) or not _TRACE_DIGEST_RE.fullmatch(verdict_digest):
        errors.append(f"invalid verdict digest: {verdict_digest!r}")
    elif verdict_digest not in review_text:
        errors.append("verdict digest is absent from the Evidence Trace")

    best_question_count = _best_question_count(state) if mode == "best" else None
    if best_question_count is not None and not 3 <= best_question_count <= 5:
        errors.append(
            "successful best judgment must contain three to five questions, "
            f"got {best_question_count}"
        )

    scientific = getattr(state, "scientific_judgment", None)
    scientific_snapshot = _scientific_snapshot(state, mode)
    if scientific is not None:
        axes = _attribute_or_key(scientific, "axes", ())
        axis_names = tuple(_attribute_or_key(axis, "axis", "") for axis in axes)
        if axis_names != SCIENTIFIC_AXES:
            errors.append(
                "successful best judgment must cover the five scientific axes "
                "in canonical order"
            )
        judgment_scores = _attribute_or_key(scientific, "scores", {})
        if not isinstance(judgment_scores, Mapping) or set(judgment_scores) != set(
            _SCORE_RANGES
        ):
            errors.append("successful best judgment must contain all six score dimensions")
        judgment_identity = scientific_snapshot["judgment_identity"]
        if (
            not isinstance(judgment_identity, str)
            or not _TRACE_DIGEST_RE.fullmatch(judgment_identity)
        ):
            errors.append(f"invalid scientific judgment identity: {judgment_identity!r}")
        elif judgment_identity not in review_text:
            errors.append("scientific judgment identity is absent from the Evidence Trace")

    if (
        isinstance(runtime_seconds, bool)
        or not isinstance(runtime_seconds, (int, float))
        or not math.isfinite(runtime_seconds)
        or runtime_seconds < 0
        or runtime_seconds > max_runtime_seconds
    ):
        errors.append(
            f"review runtime {runtime_seconds!r}s is outside 0..{max_runtime_seconds:g}s"
        )

    if errors:
        raise SmokeValidationError("; ".join(errors))
    return {
        "sha256": actual_sha256,
        "page_count": prepared_pages,
        "extracted_characters": len(extracted),
        "scores": flat_scores,
        "review_identity": review_identity,
        "verdict_digest": verdict_digest,
        "best_question_count": best_question_count,
        **scientific_snapshot,
    }


def _default_run_dir(seed: int, created_at: str) -> Path:
    compact_time = datetime.fromisoformat(created_at).strftime("%Y%m%dT%H%M%S%z")
    base = DEFAULT_RUNS_DIR / f"{compact_time}-seed-{seed}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{suffix:02d}")
        suffix += 1
    return candidate


def _paper_result(paper: Mapping[str, str]) -> dict[str, Any]:
    return {
        "arxiv_id": paper["arxiv_id"],
        "title": paper["title"],
        "category": paper["category"],
        "pdf_url": paper["pdf_url"],
        "sha256": paper.get("sha256"),
        "ok": False,
    }


def run_smoke(
    *,
    count: int = DEFAULT_COUNT,
    seed: int | None = None,
    mode: str | None = None,
    replay: Path | None = None,
    run_dir: Path | None = None,
    per_category: int = DEFAULT_PER_CATEGORY,
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
    fetch_feed: Fetch | None = None,
    fetch_pdf: Fetch | None = None,
    prepare_paper_fn: PreparePaper | None = None,
    run_pipeline_fn: RunPipeline | None = None,
    now_fn: Callable[[], datetime] | None = None,
    timer_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Download, review, validate, and report a fresh or replayed smoke corpus."""

    if mode is not None and mode not in {"audit", "best"}:
        raise ValueError("mode must be 'audit' or 'best'")
    if (
        isinstance(max_runtime_seconds, bool)
        or not isinstance(max_runtime_seconds, (int, float))
        or not math.isfinite(max_runtime_seconds)
        or max_runtime_seconds <= 0
    ):
        raise ValueError("max_runtime_seconds must be a positive finite number")

    created_at = _kst_timestamp(now_fn)
    replay_path = Path(replay).expanduser().resolve() if replay is not None else None
    if replay_path is not None:
        manifest = load_manifest(replay_path)
        resolved_seed = manifest["seed"]
        resolved_mode = mode or manifest["mode"]
        selected = [dict(paper) for paper in manifest["papers"]]
    else:
        resolved_seed = resolve_seed(seed)
        resolved_mode = mode or "audit"
        selected = select_diverse_papers(
            discover_recent_papers(
                fetch_feed=fetch_feed,
                per_category=per_category,
            ),
            count=count,
            seed=resolved_seed,
        )
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "seed": resolved_seed,
            "created_at": created_at,
            "mode": resolved_mode,
            "papers": [],
        }

    destination = (
        Path(run_dir).expanduser().resolve()
        if run_dir is not None
        else _default_run_dir(resolved_seed, created_at)
    )
    destination.mkdir(parents=True, exist_ok=True)
    pdf_dir = destination / "pdfs"
    source_dir = destination / "sources"
    evidence_root = destination / "evidence"
    review_dir = destination / "reviews"
    for directory in (pdf_dir, source_dir, evidence_root, review_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_path = replay_path or (destination / "manifest.json")
    report_path = destination / "report.json"
    pdf_fetcher = fetch_pdf or _fetch_url
    prepare = prepare_paper_fn or prepare_paper
    pipeline = run_pipeline_fn or run_pipeline
    timer = timer_fn or time.monotonic

    results_by_id: dict[str, dict[str, Any]] = {}
    downloaded: list[tuple[dict[str, str], Path]] = []
    fresh_manifest_papers: list[dict[str, str]] = []
    for paper in selected:
        record = _paper_result(paper)
        results_by_id[paper["arxiv_id"]] = record
        pdf_path = pdf_dir / f"{_safe_stem(paper['arxiv_id'])}.pdf"
        record["pdf_path"] = str(pdf_path)
        try:
            payload = pdf_fetcher(paper["pdf_url"])
            if not isinstance(payload, (bytes, bytearray)) or not payload:
                raise SmokeValidationError("PDF response is empty")
            payload = bytes(payload)
            pdf_path.write_bytes(payload)
            if b"%PDF-" not in payload[:1024]:
                raise SmokeValidationError("downloaded response does not contain a PDF header")
            digest = _sha256(payload)
            expected = paper.get("sha256")
            if expected is not None and digest != expected:
                raise SmokeValidationError(
                    f"sha256 mismatch: expected {expected}, got {digest}"
                )
            pinned = {
                "arxiv_id": paper["arxiv_id"],
                "title": paper["title"],
                "category": paper["category"],
                "pdf_url": paper["pdf_url"],
                "sha256": digest,
            }
            record["sha256"] = digest
            downloaded.append((pinned, pdf_path))
            fresh_manifest_papers.append(pinned)
        except Exception as error:  # per-paper network/hash isolation
            record["stage"] = "download"
            record["error"] = f"{type(error).__name__}: {error}"

    if replay_path is None:
        manifest["papers"] = fresh_manifest_papers
        manifest = validate_manifest(manifest)
        _write_json(manifest_path, manifest)

    # The manifest is guaranteed durable before the first prepare/review call.
    for paper, pdf_path in downloaded:
        record = results_by_id[paper["arxiv_id"]]
        started = timer()
        source_path = source_dir / f"{_safe_stem(paper['arxiv_id'])}.md"
        evidence_dir = evidence_root / _safe_stem(paper["arxiv_id"])
        review_path = review_dir / f"{_safe_stem(paper['arxiv_id'])}.review.md"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        record.update(
            {
                "source_path": str(source_path),
                "evidence_dir": str(evidence_dir),
                "review_path": str(review_path),
            }
        )
        try:
            prepared = prepare(pdf_path, converted_path=source_path)
            state = pipeline(
                pdf_path,
                evidence_dir,
                review_path,
                mode=resolved_mode,
                prepared_paper=prepared,
            )
            runtime_seconds = timer() - started
            validation = validate_review(
                pdf_path=pdf_path,
                expected_sha256=paper["sha256"],
                prepared=prepared,
                state=state,
                review_path=review_path,
                runtime_seconds=runtime_seconds,
                mode=resolved_mode,
                max_runtime_seconds=float(max_runtime_seconds),
            )
            record.update(validation)
            record["runtime_seconds"] = runtime_seconds
            record["stage"] = "complete"
            record["ok"] = True
        except Exception as error:  # per-paper conversion/pipeline/validation isolation
            runtime_seconds = timer() - started
            record["runtime_seconds"] = runtime_seconds
            record["stage"] = "review"
            record["error"] = f"{type(error).__name__}: {error}"

    ordered_results = [results_by_id[paper["arxiv_id"]] for paper in selected]
    passed = sum(result["ok"] for result in ordered_results)
    committee_successes = sum(
        result.get("scientific_status") == "committee" for result in ordered_results
    )
    committee_fallbacks = sum(
        result.get("scientific_status") == "fallback" for result in ordered_results
    )
    total_runtime = sum(
        float(result.get("runtime_seconds", 0.0)) for result in ordered_results
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "created_at": created_at,
        "seed": resolved_seed,
        "mode": resolved_mode,
        "manifest_path": str(manifest_path),
        "replay_manifest": str(replay_path) if replay_path is not None else None,
        "run_dir": str(destination),
        "report_path": str(report_path),
        "results": ordered_results,
        "summary": {
            "selected": len(selected),
            "downloaded": len(downloaded),
            "passed": passed,
            "failed": len(ordered_results) - passed,
            "committee_successes": committee_successes,
            "committee_fallbacks": committee_fallbacks,
            "total_runtime_seconds": total_runtime,
        },
    }
    _write_json(report_path, report)
    return report


def _parse_seed(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("seed must be an integer") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review fresh random arXiv PDFs, or replay a hash-pinned manifest."
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=_parse_seed)
    parser.add_argument("--mode", choices=("audit", "best"))
    parser.add_argument("--replay", type=Path, help="existing schema-v1 manifest to replay")
    parser.add_argument("--run-dir", type=Path, help="artifact directory for this run")
    parser.add_argument("--per-category", type=int, default=DEFAULT_PER_CATEGORY)
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=DEFAULT_MAX_RUNTIME_SECONDS,
        help="maximum accepted prepare+review time per paper",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_smoke(
            count=args.count,
            seed=args.seed,
            mode=args.mode,
            replay=args.replay,
            run_dir=args.run_dir,
            per_category=args.per_category,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    except (ET.ParseError, OSError, TypeError, ValueError) as error:
        print(f"random PDF smoke setup failed: {error}", file=sys.stderr)
        return 2

    summary = report["summary"]
    print(f"manifest: {report['manifest_path']}")
    print(f"report: {report['report_path']}")
    print(
        "summary: "
        f"{summary['passed']}/{summary['selected']} passed, "
        f"{summary['failed']} failed, "
        f"{summary['committee_successes']} committee / "
        f"{summary['committee_fallbacks']} fallback, "
        f"{summary['total_runtime_seconds']:.3f}s review runtime"
    )
    for result in report["results"]:
        if not result["ok"]:
            print(
                f"failed {result['arxiv_id']} ({result['category']}): "
                f"{result.get('error', 'unknown error')}"
            )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
