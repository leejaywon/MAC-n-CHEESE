"""Promised-but-unreported detection: papers that announce a held-out item and
never report it.

This is the one defect class that mechanical comparison catches more reliably
than a human skim — a paper says "a seventh event is held out as an unseen
transfer scenario" and the results section never mentions it again. It is also a
class where pattern matching against prose is inherently noisy, so this check is
**annotation-only by design**: it emits neutral traces for the judgment layer to
weigh with full context, and NEVER findings. It must not touch scores, weakness
lists, or verdicts on its own (the anti-overfit rule: class/convention signals,
never per-paper cleverness promoted to judgment).
"""

from __future__ import annotations

import re
from typing import Any

from .parser import paper_text

# Explicit promissory markers only. Deliberately narrow: "left to future work"
# and friends are announced NON-promises, and related-work mentions of other
# benchmarks' held-out splits are about someone else's paper — noise we accept
# rather than over-filter, because the output is a neutral note either way.
_PROMISE_RE = re.compile(
    r"(?i)\b(?:held[- ]?out|hold[- ]?out)\b"
    r"|\bunseen\s+(?:transfer|test|evaluation|scenario)\b"
    r"|\bwe\s+(?:additionally|also|further)\s+(?:report|evaluate|measure|collect)\b"
    r"|\breported?\s+(?:below|in\s+section|in\s+appendix)\b"
)
_REFERENCES_RE = re.compile(r"(?im)^#{1,6}\s*(?:references|bibliography)\b")
_STOPWORDS = frozenset(
    "about above after again their there these those which while whose being "
    "under between through during against without within because should would "
    "could where every other another paper section appendix figure table "
    "results result experiment experiments evaluation scenario transfer "
    "unseen held holdout".split()
)
_MAX_NOTES = 3


def _distinctive_tokens(sentence: str) -> list[str]:
    """Content words specific enough to track downstream (≥5 chars, non-stopword)."""

    tokens = re.findall(r"[a-z][a-z-]{4,}", sentence.lower())
    seen: list[str] = []
    for token in tokens:
        if token not in _STOPWORDS and token not in seen:
            seen.append(token)
    return seen


def check_promised_results(parsed_paper: dict[str, Any]) -> dict[str, Any]:
    """Neutral notes for promissory statements whose subject never reappears.

    A note fires only when (a) an explicit promissory marker is present before
    the references section, (b) the sentence yields at least two distinctive
    content tokens, and (c) NONE of those tokens occurs anywhere later in the
    body. Zero findings, ever — the traces ride to the judgment layer and the
    audit sidecar as "worth checking", not as defects.
    """

    text = paper_text(parsed_paper)
    references = _REFERENCES_RE.search(text)
    body = text[: references.start()] if references else text
    lines = body.splitlines()
    traces: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        marker = _PROMISE_RE.search(line)
        if not marker:
            continue
        tokens = _distinctive_tokens(line)
        if len(tokens) < 2:
            continue
        rest = "\n".join(lines[index:]).lower()
        if any(token in rest for token in tokens):
            continue
        traces.append(
            {
                "line": index,
                "marker": " ".join(marker.group(0).split()),
                "subject_tokens": tokens[:8],
                "note": (
                    "the paper announces a held-out/additional item here whose "
                    "distinctive terms never reappear afterwards; check whether "
                    "its results are actually reported"
                ),
            }
        )
        if len(traces) >= _MAX_NOTES:
            break
    return {"check": "promised-results", "traces": traces, "findings": []}
