"""Prose hygiene for committee (LLM-authored) review text.

The deterministic templates are already clean; the scientific committee, being a
language model, can leak reviewer self-identity ("Reviewer: MAC"), process
meta-commentary ("the batch", "this pipeline"), first-person voice, and evaluative
flourish ("exemplary", "genuinely useful") into the review. This pass makes
committee text read as an anonymous reviewer's grounded assessment.

It edits wording only — never facts, numbers, grounding ids, or citations. No rule
here touches bracketed ids (`[claim-001]`) or digits, and the caller appends
grounding *after* sanitation, so ids can never be altered. "genuine" meaning
real/actual is preserved; only the intensifier adverb "genuinely" is dropped.
"""

from __future__ import annotations

import re

# 1) Whole lines that only announce a reviewer identity or the review process.
_META_LINE = re.compile(
    r"(?im)^[ \t]*(?:reviewer|meta[- ]?review(?:er)?|area[- ]?chair)[ \t]*[:#\-][^\n]*(?:\n|$)"
)

# 2) Inline reviewer self-reference / process meta, removed wherever it appears.
_META_PHRASE = re.compile(
    r"(?i)\b(?:"
    r"as (?:an? )?(?:ai|language model|automated reviewer|reviewing agent|assistant|agent)"
    r"|in this (?:review|batch|pipeline|assessment)"
    r"|(?:this|the) (?:batch|pipeline|reviewing agent|automated (?:reviewer|system)|committee)"
    r")\b[,:]?"
)

# 3) First-person reviewer voice -> impersonal. Conservative: only clear
#    reviewer-stance forms, so a paper-quoted "we" ("we show that ...") is left.
_FIRST_PERSON = (
    re.compile(r"(?i)\bin (?:my|our) (?:view|opinion|assessment|judg(?:e)?ment)\b,?[ \t]*"),
    re.compile(
        r"(?i)\b(?:I|we) (?:believe|think|feel|find|note|observe|argue|would argue|"
        r"suspect|conclude|assess|recommend|suggest) that "
    ),
)

# 4) Evaluative intensifier adverbs -> dropped (the modified word stands alone).
_INTENSIFIER = re.compile(
    r"(?i)\b(?:unusually|remarkably|notably|exceptionally|extraordinarily|truly|genuinely|"
    r"particularly|highly|incredibly|impressively|strikingly|surprisingly|refreshingly|"
    r"exceedingly|immensely|tremendously|especially)[ \t]+"
)

# 5) Pure-flourish phrases/adjectives -> neutralized or dropped.
_FLOURISH = (
    (re.compile(r"(?i)\bthe strongest part\b"), "a strength"),
    (
        re.compile(
            r"(?i)\b(?:exemplary|impressive|compelling|elegant|masterful|stellar|superb|"
            r"outstanding|remarkable|striking)[ \t]+"
        ),
        "",
    ),
)

_ARTICLE = re.compile(r"\b([Aa]n?)[ \t]+([A-Za-z])")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:)])")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_SENTENCE_START = re.compile(r"(^|[.!?]\s+)([a-z])")


def _fix_articles(text: str) -> str:
    """Repair a/an after a following word was dropped (e.g. 'a impressive X')."""

    def repl(match: re.Match[str]) -> str:
        article, first = match.group(1), match.group(2)
        correct = "an" if first.lower() in "aeiou" else "a"
        if article[0].isupper():
            correct = correct.capitalize()
        return f"{correct} {first}"

    return _ARTICLE.sub(repl, text)


def sanitize(text: str) -> str:
    """Neutralize reviewer self-identity, process meta, first person, and flourish."""

    if not text or not text.strip():
        return text
    out = _META_LINE.sub("", text)
    out = _META_PHRASE.sub("", out)
    for pattern in _FIRST_PERSON:
        out = pattern.sub("", out)
    out = _INTENSIFIER.sub("", out)
    for pattern, replacement in _FLOURISH:
        out = pattern.sub(replacement, out)
    out = _fix_articles(out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = _MULTISPACE.sub(" ", out)
    # Recapitalize a sentence whose leading first-person subject was removed.
    out = _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    return out.strip()
