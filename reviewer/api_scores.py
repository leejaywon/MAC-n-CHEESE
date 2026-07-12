"""Map the deterministic reviewer's scores onto the openagentreview.org schema.

The live platform (see ``skill.md``) accepts one JSON review per assigned paper:

    {"ordinal": 1,                    # 1..10, the assignment ordinal
     "soundness": 1..4, "presentation": 1..4,
     "significance": 1..4, "originality": 1..4,
     "overall": 1..6, "confidence": 1..5,
     "comments": "<evidence-based comments>"}

and *rejects* booleans, floats, stringified integers, and any extra field. The
pipeline uses these dimensions and ranges directly; this module only validates
and renames keys for the JSON transport.
"""

from __future__ import annotations

import re
from typing import Any


_SOUNDNESS = "Soundness"
_PRESENTATION = "Presentation"
_SIGNIFICANCE = "Significance"
_ORIGINALITY = "Originality"
_OVERALL = "Overall recommendation"
_CONFIDENCE = "Confidence"

# The platform's review body: exactly these keys, nothing more.
API_FIELDS: tuple[str, ...] = (
    "ordinal",
    "soundness",
    "presentation",
    "significance",
    "originality",
    "overall",
    "confidence",
    "comments",
)

# Inclusive integer ranges the server enforces on every numeric field.
_RANGES: dict[str, tuple[int, int]] = {
    "soundness": (1, 4),
    "presentation": (1, 4),
    "significance": (1, 4),
    "originality": (1, 4),
    "overall": (1, 6),
    "confidence": (1, 5),
}

_PUBLIC_COMMENT_SECTIONS = frozenset(
    {
        "Summary",
        "Strengths",
        "Weaknesses",
        "Questions for the Authors",
        "Scores",
        "Scientific Judgment (best mode)",
    }
)
_HEADING_RE = re.compile(r"(?m)^## (?P<title>[^\n]+)\n")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}", re.I)
_AUDIT_SUMMARY_RE = re.compile(
    r"\s*Deterministic audit:[^\n]*?Overall recommendation:[^\n]*?(?:\.(?=\s|$)|$)"
)
_GENERIC_POSITIONING_RE = re.compile(
    r"(?m)^- The paper situates its contribution against prior work[^\n]*\n?"
)


class ScoreMappingError(ValueError):
    """A pipeline result cannot be turned into a valid platform review."""


def _score(scores: dict[str, Any], name: str) -> int:
    try:
        value = scores[name]["value"]
    except (KeyError, TypeError) as error:
        raise ScoreMappingError(f"pipeline result is missing the {name!r} score") from error
    if type(value) is not int:
        raise ScoreMappingError(f"{name} must be a plain int, got {value!r}")
    return value


def public_comments(review_markdown: str) -> str:
    """Remove local freeze/provenance sections from the live API comment.

    The complete review remains on disk. The platform receives only the
    scientific review sections, never local paths, paper/evidence hashes, prompt
    hashes, or output identities from Paper Identity / Evidence Trace.
    """

    if not isinstance(review_markdown, str):
        raise ScoreMappingError("pipeline review body must be a string")
    matches = list(_HEADING_RE.finditer(review_markdown))
    selected: list[str] = []
    for index, match in enumerate(matches):
        title = match.group("title").strip()
        if title not in _PUBLIC_COMMENT_SECTIONS:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            review_markdown
        )
        selected.append(review_markdown[match.start() : end].strip())
    comments = "\n\n".join(selected).strip()
    comments = _AUDIT_SUMMARY_RE.sub("", comments)
    comments = _GENERIC_POSITIONING_RE.sub("", comments)
    comments = re.sub(r"\n{3,}", "\n\n", comments).strip()
    return _DIGEST_RE.sub("[redacted-digest]", comments)


def to_api_review(state: Any, ordinal: int) -> dict[str, Any]:
    """Rename direct pipeline dimensions into the platform's 8-key body."""

    if not isinstance(ordinal, int) or isinstance(ordinal, bool):
        raise ScoreMappingError(f"ordinal must be an int, got {ordinal!r}")

    scores = getattr(state, "scores", None) or {}
    soundness = _score(scores, _SOUNDNESS)
    presentation = _score(scores, _PRESENTATION)
    significance = _score(scores, _SIGNIFICANCE)
    originality = _score(scores, _ORIGINALITY)
    overall = _score(scores, _OVERALL)
    confidence = _score(scores, _CONFIDENCE)

    comments = public_comments(getattr(state, "review_markdown", "") or "")
    if not comments:
        raise ScoreMappingError("pipeline produced an empty review body for comments")

    review = {
        "ordinal": ordinal,
        "soundness": soundness,
        "presentation": presentation,
        "significance": significance,
        "originality": originality,
        "overall": overall,
        "confidence": confidence,
        "comments": comments,
    }
    validate_api_review(review)
    return review


def validate_api_review(review: dict[str, Any]) -> None:
    """Enforce exactly what the server enforces, so a bad body fails locally
    (before a network round-trip near the deadline) instead of returning a 4xx.

    Rejects: missing/extra fields, non-int numerics (incl. ``bool`` and ``float``
    and stringified ints), out-of-range values, and an empty comments string.
    """

    keys = set(review)
    extra = keys - set(API_FIELDS)
    if extra:
        raise ScoreMappingError(f"review has fields the platform rejects: {sorted(extra)}")
    missing = set(API_FIELDS) - keys
    if missing:
        raise ScoreMappingError(f"review is missing required fields: {sorted(missing)}")

    for field in ("ordinal", *_RANGES):
        value = review[field]
        # ``bool`` is a subclass of ``int``; reject it explicitly, like the server.
        if type(value) is not int:
            raise ScoreMappingError(
                f"{field} must be a plain int, got {type(value).__name__} ({value!r})"
            )

    for field, (low, high) in _RANGES.items():
        if not low <= review[field] <= high:
            raise ScoreMappingError(f"{field}={review[field]} outside {low}..{high}")

    if not 1 <= review["ordinal"] <= 10:
        raise ScoreMappingError(f"ordinal={review['ordinal']} outside 1..10")

    if not isinstance(review["comments"], str) or not review["comments"].strip():
        raise ScoreMappingError("comments must be a non-empty string")
