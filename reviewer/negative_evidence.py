"""Conservative detection of omitted negative experiment outcomes.

This check intentionally needs two mechanically observable facts before it
raises a finding: a ledger record has an exact ``discard`` or ``crash`` status,
and the record has a stable string identity that can be searched for in the
paper.  Records without such an identity are not safe to localize and are
therefore left unflagged rather than guessed at.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


NEGATIVE_STATUSES = frozenset({"discard", "crash"})
IDENTITY_FIELDS = ("trial", "run_tag", "job_slug", "job_name", "name", "id")
NEGATIVE_LANGUAGE_RE = re.compile(
    r"\b(?:discard(?:ed)?|crash(?:ed)?|fail(?:ed|ure)?|abort(?:ed)?|"
    r"exclude(?:d)?|error|invalid|inconclusive|unsuccessful)\b",
    re.IGNORECASE,
)


def _paper_lines(parsed_paper: dict[str, Any]) -> list[str]:
    source_path = parsed_paper.get("source_path")
    if isinstance(source_path, str):
        try:
            return Path(source_path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            pass

    # The fallback keeps the check usable with serialized parser output.  Its
    # locations are section-relative, so callers should normally retain the
    # source_path when exact paper line numbers matter.
    lines: list[str] = []
    for section in parsed_paper.get("sections", []):
        title = section.get("title")
        if isinstance(title, str):
            lines.append(title)
        content = section.get("content")
        if isinstance(content, str):
            lines.extend(content.splitlines())
    return lines


def _identity(record: dict[str, Any]) -> tuple[str, str] | None:
    for field in IDENTITY_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return field, value.strip()
    return None


def _identity_pattern(identity: str) -> re.Pattern[str]:
    """Match an identifier literally while tolerating Markdown separators."""

    parts = [part for part in re.split(r"[_\W]+", identity.casefold()) if part]
    if not parts:
        return re.compile(r"(?!x)x")
    separator = r"[\W_]+"
    body = separator.join(re.escape(part) for part in parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _paper_mentions(lines: list[str], identity: str) -> tuple[list[int], list[int]]:
    pattern = _identity_pattern(identity)
    identity_lines: list[int] = []
    disclosure_lines: list[int] = []
    for line_number, line in enumerate(lines, start=1):
        if not pattern.search(line.casefold()):
            continue
        identity_lines.append(line_number)
        if NEGATIVE_LANGUAGE_RE.search(line):
            disclosure_lines.append(line_number)
    return identity_lines, disclosure_lines


def check_negative_evidence(
    parsed_paper: dict[str, Any], evidence_dir: Path
) -> dict[str, Any]:
    """Flag identifiable ``discard``/``crash`` ledger records not disclosed.

    Malformed and non-object JSONL lines are outside this check's narrow
    contract (ledger-trace reports those).  The output follows the established
    S3 ``{check, traces, findings}`` shape and is deterministically ordered by
    evidence path and ledger line.
    """

    evidence_dir = Path(evidence_dir)
    paper_lines = _paper_lines(parsed_paper)
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for ledger_path in sorted(evidence_dir.rglob("experiments.jsonl")):
        relative_path = ledger_path.relative_to(evidence_dir).as_posix()
        try:
            ledger_lines = ledger_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for line_number, raw_line in enumerate(ledger_lines, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue

            raw_status = record.get("status")
            if not isinstance(raw_status, str):
                continue
            status = raw_status.strip().casefold()
            if status not in NEGATIVE_STATUSES:
                continue

            identity = _identity(record)
            if identity is None:
                # An unidentifiable record cannot be proven absent from prose.
                continue
            identity_field, identity_value = identity
            mention_lines, disclosure_lines = _paper_mentions(paper_lines, identity_value)
            disclosed = bool(disclosure_lines)
            ledger_location = f"{relative_path}:{line_number}"
            trace = {
                "status": status,
                "identity_field": identity_field,
                "identity": identity_value,
                "location": ledger_location,
                "evidence_path": relative_path,
                "paper_mention_lines": mention_lines,
                "paper_disclosure_lines": disclosure_lines,
                "disclosed": disclosed,
            }
            traces.append(trace)

            if disclosed:
                continue
            observed = (
                f"paper mentions {identity_field}={identity_value!r} at line(s) "
                f"{mention_lines} without negative-outcome language"
                if mention_lines
                else f"paper does not mention {identity_field}={identity_value!r}"
            )
            findings.append(
                {
                    "check": "negative-evidence",
                    "severity": "high",
                    "location": ledger_location,
                    "expected": (
                        f"paper disclosure of ledger {status} outcome for "
                        f"{identity_field}={identity_value!r}"
                    ),
                    "observed": observed,
                    "evidence_path": relative_path,
                }
            )

    return {"check": "negative-evidence", "traces": traces, "findings": findings}
