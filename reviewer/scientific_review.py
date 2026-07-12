"""Sanitized committee evidence and strict specialist/meta validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .parser import paper_text
from .review_schema import (
    COMMITTEE_ROLES,
    SCIENTIFIC_AXES,
    SCIENTIFIC_RUBRIC_VERSION,
    SCIENTIFIC_VERDICTS,
    SPECIALIST_AXES,
    AxisAssessment,
    GroundedComment,
    GroundedQuestion,
    ScientificJudgment,
    ScoreAdjustment,
    SpecialistReview,
)


ROLE_PRIORITY = (
    "abstract",
    "problem",
    "method",
    "experiments",
    "ablations",
    "limitations",
    "related_work",
    "references",
)

SCORE_RANGES = {
    "Soundness": (1, 4),
    "Presentation": (1, 4),
    "Significance": (1, 4),
    "Originality": (1, 4),
    "Overall recommendation": (1, 6),
    "Confidence": (1, 5),
}

_TOP_LEVEL_KEYS = frozenset(
    {"summary", "axes", "strengths", "weaknesses", "questions", "scores"}
)
_SPECIALIST_TOP_LEVEL_KEYS = frozenset(
    {
        "assessments",
        "strengths",
        "weaknesses",
        "questions",
        "provisional_scores",
    }
)
_AXIS_KEYS = frozenset({"axis", "verdict", "text", "grounding"})
_COMMENT_KEYS = frozenset({"text", "grounding"})
_SPECIALIST_QUESTION_KEYS = frozenset({"text", "grounding"})
_QUESTION_KEYS = frozenset({"text", "grounding", "assessment_if_resolved"})
_SCORE_KEYS = frozenset({"value", "reason", "grounding"})

_ABSTRACT_RE = re.compile(r"\b(?:abstract|executive\s+summary|synopsis)\b", re.I)
_PROBLEM_RE = re.compile(
    r"\b(?:introduction|motivation|problem|contributions?|overview|background)\b",
    re.I,
)
_METHOD_RE = re.compile(
    r"\b(?:methods?|methodology|approach|algorithm|architecture|framework|"
    r"proposed\s+(?:model|system)|technical\s+details?)\b",
    re.I,
)
_EXPERIMENTS_RE = re.compile(
    r"\b(?:experiments?|experimental|evaluation|results?|empirical|benchmarks?|"
    r"datasets?|implementation\s+details?|experimental\s+setup)\b",
    re.I,
)
_ABLATIONS_RE = re.compile(
    r"\b(?:ablations?|sensitivity|robustness|diagnostics?|error\s+analysis|"
    r"hyperparameter\s+analysis)\b",
    re.I,
)
_LIMITATIONS_RE = re.compile(
    r"\b(?:limitations?|ethics?|ethical\s+considerations?|broader\s+impacts?|"
    r"societal\s+impacts?|conclusions?)\b",
    re.I,
)
_RELATED_WORK_RE = re.compile(
    r"\b(?:(?:related|prior|previous)\s+work|literature\s+review)\b",
    re.I,
)
_REFERENCES_RE = re.compile(r"\b(?:references?|bibliograph(?:y|ies))\b", re.I)


@dataclass(frozen=True)
class PaperSpan:
    id: str
    role: str
    line_start: int
    line_end: int
    text: str

    def __post_init__(self) -> None:
        expected_id = f"paper:L{self.line_start}-L{self.line_end}"
        if (
            type(self.line_start) is not int
            or type(self.line_end) is not int
            or self.line_start < 1
            or self.line_end < self.line_start
            or self.id != expected_id
        ):
            raise ValueError("paper span id must exactly match its positive line range")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("paper span role must not be empty")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("paper span text must not be empty")


@dataclass(frozen=True)
class ScientificEvidencePacket:
    text: str
    spans: tuple[PaperSpan, ...]
    included_roles: tuple[str, ...]
    omitted_sections: tuple[str, ...]


@dataclass(frozen=True)
class _Section:
    index: int
    title: str
    role: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class _Candidate:
    section: _Section
    span: PaperSpan


def _heading_role(title: str) -> str:
    if _ABSTRACT_RE.search(title):
        return "abstract"
    if _REFERENCES_RE.search(title):
        return "references"
    if _RELATED_WORK_RE.search(title):
        return "related_work"
    if _ABLATIONS_RE.search(title):
        return "ablations"
    if _EXPERIMENTS_RE.search(title):
        return "experiments"
    if _METHOD_RE.search(title):
        return "method"
    if _LIMITATIONS_RE.search(title):
        return "limitations"
    if _PROBLEM_RE.search(title):
        return "problem"
    return "other"


def _paper_sections(parsed_paper: dict[str, object], line_count: int) -> tuple[_Section, ...]:
    raw_sections = parsed_paper.get("sections")
    sections: list[_Section] = []
    if isinstance(raw_sections, list):
        for index, raw_section in enumerate(raw_sections):
            if not isinstance(raw_section, dict):
                continue
            line_start = raw_section.get("line_start")
            line_end = raw_section.get("line_end")
            if (
                type(line_start) is not int
                or type(line_end) is not int
                or line_start < 1
                or line_end < line_start
                or line_start > line_count
            ):
                continue
            raw_title = raw_section.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) else f"Section {index + 1}"
            if not title:
                title = f"Section {index + 1}"
            sections.append(
                _Section(
                    index=index,
                    title=title,
                    role=_heading_role(title),
                    line_start=line_start,
                    line_end=min(line_end, line_count),
                )
            )
    if not sections and line_count:
        sections.append(
            _Section(
                index=0,
                title="Document",
                role="other",
                line_start=1,
                line_end=line_count,
            )
        )
    return tuple(sections)


def _table_ranges(parsed_paper: dict[str, object], line_count: int) -> dict[int, int]:
    ranges: dict[int, int] = {}
    raw_tables = parsed_paper.get("tables")
    if not isinstance(raw_tables, list):
        return ranges
    for raw_table in raw_tables:
        if not isinstance(raw_table, dict):
            continue
        line_start = raw_table.get("line_start")
        line_end = raw_table.get("line_end")
        if (
            type(line_start) is int
            and type(line_end) is int
            and 1 <= line_start <= line_end <= line_count
        ):
            ranges[line_start] = max(ranges.get(line_start, line_start), line_end)
    return ranges


def _span(lines: list[str], role: str, line_start: int, line_end: int) -> PaperSpan:
    text = "\n".join(lines[line_start - 1 : line_end]).rstrip()
    return PaperSpan(
        id=f"paper:L{line_start}-L{line_end}",
        role=role,
        line_start=line_start,
        line_end=line_end,
        text=text,
    )


def _bounded_spans(
    lines: list[str],
    role: str,
    line_start: int,
    line_end: int,
    *,
    max_lines: int = 12,
    max_chars: int = 2_800,
) -> list[PaperSpan]:
    """Keep grounding citations local enough to support a specific assessment."""

    spans: list[PaperSpan] = []
    cursor = line_start
    while cursor <= line_end:
        chunk_end = min(line_end, cursor + max_lines - 1)
        while (
            chunk_end > cursor
            and len("\n".join(lines[cursor - 1 : chunk_end])) > max_chars
        ):
            chunk_end -= 1
        spans.append(_span(lines, role, cursor, chunk_end))
        cursor = chunk_end + 1
    return spans


def _section_candidates(
    section: _Section,
    lines: list[str],
    table_ranges: dict[int, int],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    cursor = section.line_start
    while cursor <= section.line_end:
        if not lines[cursor - 1].strip():
            cursor += 1
            continue

        table_end = table_ranges.get(cursor)
        if table_end is not None:
            line_end = min(table_end, section.line_end)
            candidates.extend(
                _Candidate(section, span)
                for span in _bounded_spans(
                    lines,
                    section.role,
                    cursor,
                    line_end,
                    max_lines=20,
                )
            )
            cursor = line_end + 1
            continue

        line_start = cursor
        while (
            cursor <= section.line_end
            and lines[cursor - 1].strip()
            and cursor not in table_ranges
        ):
            cursor += 1
        candidates.extend(
            _Candidate(section, span)
            for span in _bounded_spans(
                lines,
                section.role,
                line_start,
                cursor - 1,
            )
        )
    return candidates


def _render_span(span: PaperSpan) -> str:
    return f"[{span.id} | role={span.role}]\n{span.text}"


def build_evidence_packet(
    parsed_paper: dict[str, object], *, max_chars: int = 60_000
) -> ScientificEvidencePacket:
    """Build a deterministic, section-prioritized packet from canonical text.

    The function deliberately reads paper content only through ``paper_text``.
    Parsed section and table coordinates supply structure, but their copied
    content fields and the source path are never consumed.
    """

    if type(max_chars) is not int or max_chars < 0:
        raise ValueError("max_chars must be a non-negative plain int")
    canonical_text = paper_text(parsed_paper)
    lines = canonical_text.splitlines()
    sections = _paper_sections(parsed_paper, len(lines))
    tables = _table_ranges(parsed_paper, len(lines))
    candidates = [
        candidate
        for section in sections
        for candidate in _section_candidates(section, lines, tables)
    ]

    priority = {role: index for index, role in enumerate(ROLE_PRIORITY)}
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            priority.get(candidate.span.role, len(ROLE_PRIORITY)),
            candidate.section.index,
            candidate.span.line_start,
            candidate.span.line_end,
        ),
    )

    retained: list[_Candidate] = []
    omitted_section_indexes: set[int] = set()
    rendered: list[str] = []
    used = 0
    for candidate in ordered:
        block = _render_span(candidate.span)
        cost = len(block) + (2 if rendered else 0)
        if used + cost <= max_chars:
            retained.append(candidate)
            rendered.append(block)
            used += cost
        else:
            omitted_section_indexes.add(candidate.section.index)

    included_roles = tuple(
        dict.fromkeys(candidate.span.role for candidate in retained)
    )
    omitted_sections = tuple(
        section.title
        for section in sections
        if section.index in omitted_section_indexes
    )
    return ScientificEvidencePacket(
        text="\n\n".join(rendered),
        spans=tuple(candidate.span for candidate in retained),
        included_roles=included_roles,
        omitted_sections=tuple(dict.fromkeys(omitted_sections)),
    )


def filter_evidence_packet(
    packet: ScientificEvidencePacket,
    roles: Iterable[str],
) -> ScientificEvidencePacket:
    """Return the stable spans relevant to a committee role.

    Filtering never re-reads or re-slices source text: the returned packet is
    rendered solely from already-sanitized spans in ``packet``.
    """

    if not isinstance(packet, ScientificEvidencePacket):
        raise TypeError("packet must be a ScientificEvidencePacket")
    if isinstance(roles, (str, bytes)):
        raise ValueError("roles must be an iterable of role names")
    requested: list[str] = []
    for role in roles:
        if not isinstance(role, str) or not role.strip() or role != role.strip():
            raise ValueError("evidence roles must be non-empty strings")
        if role not in ROLE_PRIORITY and role != "other":
            raise ValueError(f"unknown evidence role: {role}")
        if role not in requested:
            requested.append(role)
    selected = tuple(span for span in packet.spans if span.role in requested)
    included_roles = tuple(dict.fromkeys(span.role for span in selected))
    return ScientificEvidencePacket(
        text="\n\n".join(_render_span(span) for span in selected),
        spans=selected,
        included_roles=included_roles,
        omitted_sections=packet.omitted_sections,
    )


def render_evidence_packet(
    packet: ScientificEvidencePacket,
    roles: Iterable[str] | None = None,
) -> str:
    """Render sanitized packet spans, optionally restricted by section role."""

    selected = packet if roles is None else filter_evidence_packet(packet, roles)
    return "\n\n".join(_render_span(span) for span in selected.spans)


def _object(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], context: str) -> None:
    actual = set(value)
    unexpected = sorted(str(key) for key in actual - expected)
    missing = sorted(expected - actual)
    if unexpected:
        raise ValueError(f"{context} has unexpected keys: {', '.join(unexpected)}")
    if missing:
        raise ValueError(f"{context} is missing keys: {', '.join(missing)}")


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _grounding(
    value: object,
    *,
    allowed: frozenset[str],
    context: str,
) -> tuple[str, ...]:
    raw_ids = _array(value, f"{context} grounding")
    if not raw_ids:
        raise ValueError(f"{context} grounding must not be empty")
    ids: list[str] = []
    for raw_id in raw_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ValueError(f"{context} grounding ids must be non-empty strings")
        if raw_id != raw_id.strip():
            raise ValueError(f"{context} grounding ids must not contain outer whitespace")
        if raw_id in ids:
            raise ValueError(f"{context} has duplicate grounding id: {raw_id}")
        ids.append(raw_id)
    unknown = sorted(set(ids) - allowed)
    if unknown:
        raise ValueError(
            f"unknown grounding id for {context}: {', '.join(unknown)}"
        )
    return tuple(ids)


def _comments(
    value: object,
    *,
    allowed: frozenset[str],
    stance: str,
) -> tuple[GroundedComment, ...]:
    comments: list[GroundedComment] = []
    for index, raw_comment in enumerate(_array(value, stance)):
        context = f"{stance} item {index + 1}"
        comment = _object(raw_comment, context)
        _exact_keys(comment, _COMMENT_KEYS, context)
        comments.append(
            GroundedComment(
                text=_text(comment["text"], f"{context} text"),
                grounding=_grounding(
                    comment["grounding"],
                    allowed=allowed,
                    context=context,
                ),
            )
        )
    return tuple(comments)


def _axes(
    value: object,
    *,
    allowed: frozenset[str],
    expected_axes: tuple[str, ...] = SCIENTIFIC_AXES,
) -> tuple[AxisAssessment, ...]:
    assessments: dict[str, AxisAssessment] = {}
    for index, raw_axis in enumerate(_array(value, "axes")):
        context = f"axis assessment {index + 1}"
        axis_object = _object(raw_axis, context)
        _exact_keys(axis_object, _AXIS_KEYS, context)
        axis = _text(axis_object["axis"], f"{context} axis")
        if axis not in SCIENTIFIC_AXES:
            raise ValueError(f"unknown axis: {axis}")
        if axis not in expected_axes:
            raise ValueError(f"axis {axis} is outside this specialist's remit")
        if axis in assessments:
            raise ValueError(f"duplicate axis: {axis}")
        verdict = _text(axis_object["verdict"], f"{axis} verdict")
        if verdict not in SCIENTIFIC_VERDICTS:
            allowed_verdicts = ", ".join(sorted(SCIENTIFIC_VERDICTS))
            raise ValueError(
                f"unknown verdict for {axis}: {verdict}; expected one of {allowed_verdicts}"
            )
        assessments[axis] = AxisAssessment(
            axis=axis,
            verdict=verdict,
            text=_text(axis_object["text"], f"{axis} text"),
            grounding=_grounding(
                axis_object["grounding"],
                allowed=allowed,
                context=axis,
            ),
        )
    missing = [axis for axis in expected_axes if axis not in assessments]
    if missing:
        raise ValueError(f"missing axis assessments: {', '.join(missing)}")
    return tuple(assessments[axis] for axis in expected_axes)


def _questions(
    value: object,
    *,
    allowed: frozenset[str],
    minimum: int = 3,
    maximum: int = 5,
) -> tuple[GroundedQuestion, ...]:
    raw_questions = _array(value, "questions")
    if not minimum <= len(raw_questions) <= maximum:
        if minimum == 3 and maximum == 5:
            raise ValueError("scientific judgment requires three to five questions")
        raise ValueError(
            f"specialist review requires between {minimum} and {maximum} questions"
        )
    questions: list[GroundedQuestion] = []
    for index, raw_question in enumerate(raw_questions):
        context = f"question {index + 1}"
        question = _object(raw_question, context)
        _exact_keys(question, _QUESTION_KEYS, context)
        questions.append(
            GroundedQuestion(
                text=_text(question["text"], f"{context} text"),
                grounding=_grounding(
                    question["grounding"],
                    allowed=allowed,
                    context=context,
                ),
                assessment_if_resolved=_text(
                    question["assessment_if_resolved"],
                    f"{context} assessment_if_resolved",
                ),
            )
        )
    return tuple(questions)


def _specialist_questions(
    value: object,
    *,
    allowed: frozenset[str],
) -> tuple[GroundedComment, ...]:
    raw_questions = _array(value, "questions")
    if len(raw_questions) > 5:
        raise ValueError("specialist review allows at most five questions")
    questions: list[GroundedComment] = []
    for index, raw_question in enumerate(raw_questions):
        context = f"specialist question {index + 1}"
        question = _object(raw_question, context)
        _exact_keys(question, _SPECIALIST_QUESTION_KEYS, context)
        questions.append(
            GroundedComment(
                text=_text(question["text"], f"{context} text"),
                grounding=_grounding(
                    question["grounding"],
                    allowed=allowed,
                    context=context,
                ),
            )
        )
    return tuple(questions)


def _score_adjustment(
    value: object,
    *,
    dimension: str,
    allowed: frozenset[str],
) -> ScoreAdjustment:
    minimum, maximum = SCORE_RANGES[dimension]
    score = _object(value, f"{dimension} score")
    _exact_keys(score, _SCORE_KEYS, f"{dimension} score")
    raw_value = score["value"]
    if type(raw_value) is not int:
        raise ValueError(f"{dimension} score value must be a plain int")
    if not minimum <= raw_value <= maximum:
        raise ValueError(f"{dimension} score must be in range {minimum}-{maximum}")
    return ScoreAdjustment(
        value=raw_value,
        reason=_text(score["reason"], f"{dimension} score reason"),
        grounding=_grounding(
            score["grounding"],
            allowed=allowed,
            context=f"{dimension} score",
        ),
    )


def _scores(
    value: object,
    *,
    allowed: frozenset[str],
) -> dict[str, ScoreAdjustment]:
    raw_scores = _object(value, "scores")
    dimensions = set(raw_scores)
    expected = set(SCORE_RANGES)
    unknown = sorted(str(dimension) for dimension in dimensions - expected)
    missing = [dimension for dimension in SCORE_RANGES if dimension not in dimensions]
    if unknown:
        raise ValueError(f"scores have unknown dimensions: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"scores are missing dimensions: {', '.join(missing)}")

    scores: dict[str, ScoreAdjustment] = {}
    for dimension in SCORE_RANGES:
        scores[dimension] = _score_adjustment(
            raw_scores[dimension],
            dimension=dimension,
            allowed=allowed,
        )
    return scores


def _provisional_scores(
    value: object,
    *,
    allowed: frozenset[str],
) -> dict[str, ScoreAdjustment]:
    raw_scores = _object(value, "provisional_scores")
    if not raw_scores:
        raise ValueError("provisional_scores must not be empty")
    unknown = sorted(str(dimension) for dimension in set(raw_scores) - set(SCORE_RANGES))
    if unknown:
        raise ValueError(
            f"provisional_scores have unknown dimensions: {', '.join(unknown)}"
        )
    return {
        dimension: _score_adjustment(
            raw_scores[dimension],
            dimension=dimension,
            allowed=allowed,
        )
        for dimension in SCORE_RANGES
        if dimension in raw_scores
    }


def _grounding_allowlist(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("grounding allow-list must be an iterable of ids")
    ids: set[str] = set()
    for grounding_id in values:
        if (
            not isinstance(grounding_id, str)
            or not grounding_id.strip()
            or grounding_id != grounding_id.strip()
        ):
            raise ValueError("grounding ids must be non-empty strings")
        ids.add(grounding_id)
    return frozenset(ids)


def _allowed_grounding(
    packet: ScientificEvidencePacket,
    deterministic_grounding: Iterable[str],
) -> frozenset[str]:
    ids = {span.id for span in packet.spans}
    ids.update(_grounding_allowlist(deterministic_grounding))
    return frozenset(ids)


def validate_judgment(
    payload: object,
    packet: ScientificEvidencePacket,
    deterministic_grounding: Iterable[str] = (),
) -> ScientificJudgment:
    """Parse an untrusted JSON-compatible object into a strict judgment."""

    if not isinstance(packet, ScientificEvidencePacket):
        raise TypeError("packet must be a ScientificEvidencePacket")
    judgment = _object(payload, "scientific judgment")
    _exact_keys(judgment, _TOP_LEVEL_KEYS, "scientific judgment")
    allowed = _allowed_grounding(packet, deterministic_grounding)
    return ScientificJudgment(
        summary=_text(judgment["summary"], "scientific judgment summary"),
        axes=_axes(judgment["axes"], allowed=allowed),
        strengths=_comments(
            judgment["strengths"],
            allowed=allowed,
            stance="strengths",
        ),
        weaknesses=_comments(
            judgment["weaknesses"],
            allowed=allowed,
            stance="weaknesses",
        ),
        questions=_questions(judgment["questions"], allowed=allowed),
        scores=_scores(judgment["scores"], allowed=allowed),
    )


def validate_specialist_review(
    payload: object,
    *,
    role: str,
    allowed_grounding: Iterable[str],
) -> SpecialistReview:
    """Validate one untrusted specialist JSON response with an exact schema."""

    if role not in COMMITTEE_ROLES:
        raise ValueError(f"unknown committee role: {role!r}")
    specialist = _object(payload, f"{role} specialist review")
    _exact_keys(
        specialist,
        _SPECIALIST_TOP_LEVEL_KEYS,
        f"{role} specialist review",
    )
    allowed = _grounding_allowlist(allowed_grounding)
    return SpecialistReview(
        role=role,
        assessments=_axes(
            specialist["assessments"],
            allowed=allowed,
            expected_axes=SPECIALIST_AXES[role],
        ),
        strengths=_comments(
            specialist["strengths"],
            allowed=allowed,
            stance="strengths",
        ),
        weaknesses=_comments(
            specialist["weaknesses"],
            allowed=allowed,
            stance="weaknesses",
        ),
        questions=_specialist_questions(
            specialist["questions"],
            allowed=allowed,
        ),
        provisional_scores=_provisional_scores(
            specialist["provisional_scores"],
            allowed=allowed,
        ),
    )
