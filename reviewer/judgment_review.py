"""Judgment-first review: parsing, target-coherence gate, and integrity caps.

The review's spine is a strong model reading the FULL paper and writing an
ICML-shaped review in Markdown (see ``review_instructions.md``).
This module holds the thin mechanical frame around that spine:

- ``load_review_instructions`` — the packaged instructions handed to the model.
- ``parse_review`` — extract title, sections, and the six scores from the model's Markdown, reporting what is missing instead of guessing.
- ``check_review_target`` — the wrong-paper gate: a fluent review of the wrong paper is worthless, so the echoed title must match the input paper.
- ``apply_integrity_caps`` — the only score authority the mechanical layer keeps:
  a PROVEN integrity breach (contradicted claim / dishonest self-certification) caps Soundness and Overall at 2.
  Typographic findings and unverifiable-claim counts have no score authority here at all.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REVIEW_SECTIONS = (
    "Summary",
    "Strengths",
    "Weaknesses",
    "Questions for the Authors",
    "Scores",
    "Ethics and Limitations",
    "Comment",
)

SCORE_BOUNDS = {
    "Soundness": (1, 4),
    "Presentation": (1, 4),
    "Significance": (1, 4),
    "Originality": (1, 4),
    "Overall recommendation": (1, 6),
    "Confidence": (1, 5),
}

_TITLE_RE = re.compile(r"(?im)^#\s*Review(?:\s+of)?:?\s*(.+?)\s*$")
_WORD_RE = re.compile(r"[a-z0-9]+")
# Headings that are section labels by convention, never paper titles.
# When a paper's extraction yields one of these first, the title is UNKNOWN
# the gate must go indeterminate rather than compare against a non-title.
_NON_TITLE_RE = re.compile(
    r"(?i)^\s*(?:\d+[.)]|(?:abstract|introduction|references|bibliography|"
    r"appendix|related work|acknowledg|contents)\b)"
)


def extract_paper_title(paper_markdown: str) -> str:
    """The paper's title from its first heading, or "" when indeterminable."""

    for line in paper_markdown.splitlines():
        if not line.lstrip().startswith("#"):
            continue
        title = re.sub(r"[*_`#]", "", line).strip()
        if _NON_TITLE_RE.match(title) or len(title) < 8:
            return ""
        return title
    return ""


def load_review_instructions() -> str:
    return (Path(__file__).resolve().parent / "review_instructions.md").read_text(
        encoding="utf-8"
    )


def _section_body(markdown: str, name: str) -> str:
    match = re.search(
        rf"(?ims)^#{{2,3}}\s*{re.escape(name)}\s*$(.*?)(?=^#{{1,3}}\s|\Z)", markdown
    )
    return match.group(1).strip() if match else ""


def parse_review(markdown: str) -> dict[str, Any]:
    """Extract title, sections, scores; list gaps rather than papering over them."""

    title_match = _TITLE_RE.search(markdown)
    title = title_match.group(1).strip().strip('"').strip() if title_match else ""
    sections = {name: _section_body(markdown, name) for name in REVIEW_SECTIONS}
    scores: dict[str, int] = {}
    for dimension, (low, high) in SCORE_BOUNDS.items():
        match = re.search(
            rf"(?im)^[-*]?\s*\*{{0,2}}{re.escape(dimension)}\*{{0,2}}\s*:\s*(\d+)\s*/\s*\d+",
            markdown,
        )
        if match and low <= int(match.group(1)) <= high:
            scores[dimension] = int(match.group(1))
    missing = [name for name, body in sections.items() if not body]
    missing += [f"score:{name}" for name in SCORE_BOUNDS if name not in scores]
    if not title:
        missing.insert(0, "title")
    return {"title": title, "sections": sections, "scores": scores, "missing": missing}


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def check_review_target(review_title: str, paper_title: str) -> dict[str, Any]:
    """Wrong-paper gate. Conservative in BOTH directions by design.

    Fails only on positive evidence of a mismatch: both titles present and
    sharing too few content tokens. When the paper's own title could not be
    extracted (some PDFs yield no title heading), the gate reports
    ``indeterminate`` and passes — an unverifiable title is not evidence of a
    wrong target, and this gate must never manufacture a false alarm.
    """

    review_tokens, paper_tokens = _tokens(review_title), _tokens(paper_title)
    if not review_tokens or not paper_tokens:
        return {"ok": True, "status": "indeterminate", "overlap": 0.0}
    overlap = len(review_tokens & paper_tokens) / min(len(review_tokens), len(paper_tokens))
    return {"ok": overlap >= 0.5, "status": "checked", "overlap": round(overlap, 3)}


def apply_integrity_caps(
    scores: dict[str, int], *, breach_count: int
) -> tuple[dict[str, int], list[str]]:
    """Cap Soundness/Overall at 2 on a PROVEN breach; otherwise change nothing."""

    if breach_count <= 0:
        return dict(scores), []
    capped = dict(scores)
    notes = []
    for dimension in ("Soundness", "Overall recommendation"):
        if capped.get(dimension, 0) > 2:
            capped[dimension] = 2
            notes.append(
                f"{dimension} capped at 2/{SCORE_BOUNDS[dimension][1]}: "
                f"{breach_count} proven integrity breach(es)."
            )
    return capped, notes


# --- Panel committee: the multi-agent form that keeps every member whole. ---
#
# The committee lineage (theorist / experimentalist / scope_ablation) survives as reviewer EMPHASES
# every panelist reads the FULL paper and writes a complete review with all six scores.
# Differentiation of attention, not fragmentation of coverage
PANEL_EMPHASES: dict[str, str] = {
    "theorist": (
        "Panel emphasis: you lean theorist. Give extra scrutiny to whether the "
        "method actually fits the problem, hidden assumptions, and whether "
        "claims follow from the arguments offered. Still review the whole "
        "paper and score every dimension."
    ),
    "experimentalist": (
        "Panel emphasis: you lean empiricist. Give extra scrutiny to baselines, "
        "ablations, statistical support, and whether experiments match the "
        "claims. Still review the whole paper and score every dimension."
    ),
    "scope_ablation": (
        "Panel emphasis: you lean scope-and-generalization. Give extra scrutiny "
        "to how far the claims travel beyond the tested setting and which "
        "design choices are load-bearing but unablated. Still review the whole "
        "paper and score every dimension."
    ),
}

_AREA_CHAIR_ADDENDUM = """
## Area-chair mode

You are the area chair. Below you receive the paper, guardrail annotations, and
the panel's reviews. Write the FINAL review in exactly the output format above,
as your own judgment informed by the panel:

- Where panelists agree, consolidate — do not repeat near-duplicates.
- Where they disagree or a criticism looks doubtful, check the quoted evidence
  against the paper itself and keep only what survives; a panelist's claim you
  cannot ground in the paper is dropped, not averaged.
- Scores are yours, coherent with your final narrative; the panel's scores are
  advisory anchors, not a formula.
- Never mention the panel, reviewers, or process in the review body — the
  output must read as one reviewer's review of the paper.
"""


def build_reviewer_messages(
    paper_markdown: str,
    annotations: dict[str, Any] | None,
    *,
    emphasis: str | None = None,
) -> list[dict[str, str]]:
    """One panelist's call: full instructions + full paper + neutral annotations."""

    system = load_review_instructions()
    if emphasis:
        system += "\n\n" + PANEL_EMPHASES[emphasis]
    user = (
        "Review the following paper.\n\n"
        f"<guardrail-annotations>\n{_annotations_json(annotations)}\n</guardrail-annotations>\n\n"
        f"<paper>\n{paper_markdown}\n</paper>\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_area_chair_messages(
    paper_markdown: str,
    panel_reviews: list[str],
    annotations: dict[str, Any] | None,
) -> list[dict[str, str]]:
    system = load_review_instructions() + _AREA_CHAIR_ADDENDUM
    reviews_block = "\n\n".join(
        f"<panel-review index=\"{index}\">\n{review}\n</panel-review>"
        for index, review in enumerate(panel_reviews, 1)
    )
    user = (
        "Write the final review of the following paper.\n\n"
        f"<guardrail-annotations>\n{_annotations_json(annotations)}\n</guardrail-annotations>\n\n"
        f"<paper>\n{paper_markdown}\n</paper>\n\n"
        f"{reviews_block}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _annotations_json(annotations: dict[str, Any] | None) -> str:
    import json

    return json.dumps(annotations or {}, ensure_ascii=False, indent=1, sort_keys=True)


def median_scores(panel: list[dict[str, int]]) -> dict[str, int]:
    """Per-dimension median across gated panel reviews (AC-failure fallback)."""

    import statistics

    merged: dict[str, int] = {}
    for dimension in SCORE_BOUNDS:
        values = sorted(review[dimension] for review in panel if dimension in review)
        if values:
            merged[dimension] = int(statistics.median_low(values))
    return merged


def run_panel_review(
    paper_markdown: str,
    annotations: dict[str, Any] | None,
    *,
    paper_title: str = "",
    api_key: str = "",
    base_url: str | None = None,
    model: str | None = None,
    panel: int | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Run the review panel and (for N>=2) the area-chair synthesis.

    Failure-isolated like the committee it replaces:
    a panelist that errors, fails to parse, or fails the wrong-paper gate is dropped;
    zero survivors returns ``{"ok": False}`` so the caller can fall back to the deterministic audit.
    ``panel=1`` reproduces the validated single-reviewer configuration exactly
    """

    import os
    from concurrent.futures import ThreadPoolExecutor
    from hashlib import sha256 as _sha256

    from .model_critique import DEFAULT_BASE_URL, DEFAULT_MODEL, _default_client

    panel_size = panel if panel is not None else int(os.environ.get("REVIEWER_PANEL", "3") or 3)
    panel_size = max(1, panel_size)
    timeout = timeout if timeout is not None else int(os.environ.get("REVIEWER_COMMITTEE_TIMEOUT", "600") or 600)
    max_tokens = max_tokens if max_tokens is not None else int(os.environ.get("REVIEWER_MAX_TOKENS", "4096") or 4096)
    base_url = base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    call = client or _default_client(base_url, api_key, model, max_tokens, timeout, json_mode=False)

    roles: list[str | None]
    if panel_size == 1:
        roles = [None]
    else:
        cycle = list(PANEL_EMPHASES)
        roles = [cycle[index % len(cycle)] for index in range(panel_size)]

    def _one(role: str | None) -> dict[str, Any]:
        member: dict[str, Any] = {"role": role or "generalist", "ok": False}
        try:
            messages = build_reviewer_messages(paper_markdown, annotations, emphasis=role)
            raw = call(messages)
            member["prompt_sha256"] = _sha256(
                "".join(m["content"] for m in messages).encode("utf-8")
            ).hexdigest()
            member["response_sha256"] = _sha256(raw.encode("utf-8")).hexdigest()
            parsed = parse_review(raw)
            gate = check_review_target(parsed["title"], paper_title)
            member.update(
                markdown=raw,
                scores=parsed["scores"],
                missing=parsed["missing"],
                gate=gate,
            )
            score_gaps = [item for item in parsed["missing"] if item.startswith("score:")]
            member["ok"] = gate["ok"] and not score_gaps
        except Exception as error:  # noqa: BLE001 - per-member isolation
            member["error"] = f"{type(error).__name__}: {error}"
        return member

    with ThreadPoolExecutor(max_workers=min(panel_size, 4)) as pool:
        members = list(pool.map(_one, roles))
    survivors = [member for member in members if member["ok"]]
    if not survivors:
        return {"ok": False, "members": members, "model": model, "panel": panel_size}

    result: dict[str, Any] = {
        "ok": True,
        "members": members,
        "model": model,
        "panel": panel_size,
    }
    if len(survivors) == 1:
        chosen = survivors[0]
        result.update(
            review_markdown=chosen["markdown"], scores=chosen["scores"], synthesis="single"
        )
        return result

    try:
        ac_messages = build_area_chair_messages(
            paper_markdown, [member["markdown"] for member in survivors], annotations
        )
        ac_raw = call(ac_messages)
        ac_parsed = parse_review(ac_raw)
        ac_gate = check_review_target(ac_parsed["title"], paper_title)
        score_gaps = [item for item in ac_parsed["missing"] if item.startswith("score:")]
        if ac_gate["ok"] and not score_gaps:
            result.update(
                review_markdown=ac_raw,
                scores=ac_parsed["scores"],
                synthesis="area-chair",
                ac_gate=ac_gate,
            )
            return result
    except Exception as error:  # noqa: BLE001 - AC failure falls back to the panel
        result["ac_error"] = f"{type(error).__name__}: {error}"

    # Area chair unavailable: median scores; the body comes from the survivor whose Overall sits closest to the panel median (ties: first).
    merged = median_scores([member["scores"] for member in survivors])
    anchor = merged.get("Overall recommendation")
    chosen = min(
        survivors,
        key=lambda member: abs(member["scores"].get("Overall recommendation", 0) - anchor)
        if anchor is not None
        else 0,
    )
    result.update(
        review_markdown=chosen["markdown"], scores=merged, synthesis="panel-median"
    )
    return result
