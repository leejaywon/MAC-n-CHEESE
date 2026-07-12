"""Strict value objects for the best-mode scientific review committee."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


SCIENTIFIC_AXES = (
    "problem_method_fit",
    "claim_experiment_alignment",
    "experimental_design",
    "scope_generalization",
    "design_choice_ablations",
)

SCIENTIFIC_RUBRIC_VERSION = "scientific-committee-v1"
COMMITTEE_ROLES = ("theorist", "experimentalist", "scope_ablation")
SPECIALIST_AXES = {
    "theorist": ("problem_method_fit",),
    "experimentalist": (
        "claim_experiment_alignment",
        "experimental_design",
    ),
    "scope_ablation": (
        "scope_generalization",
        "design_choice_ablations",
    ),
}

SCIENTIFIC_VERDICTS = frozenset(
    {
        "justified",
        "partially_justified",
        "not_justified",
        "unclear",
        "not_applicable",
    }
)

Grounding = str | tuple[str, ...]


def _has_grounding(grounding: Grounding) -> bool:
    if isinstance(grounding, str):
        return bool(grounding.strip())
    return (
        isinstance(grounding, tuple)
        and bool(grounding)
        and all(isinstance(item, str) and bool(item.strip()) for item in grounding)
    )


@dataclass(frozen=True)
class GroundedComment:
    text: str
    grounding: Grounding

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip() or not _has_grounding(self.grounding):
            raise ValueError("grounded comments require text and a grounding id")


@dataclass(frozen=True)
class GroundedQuestion(GroundedComment):
    assessment_if_resolved: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.assessment_if_resolved, str)
            or not self.assessment_if_resolved.strip()
        ):
            raise ValueError("questions require assessment_if_resolved")


@dataclass(frozen=True)
class ScoreAdjustment:
    value: int
    reason: str
    grounding: Grounding

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise ValueError("score adjustment value must be a plain int")
        if (
            not isinstance(self.reason, str)
            or not self.reason.strip()
            or not _has_grounding(self.grounding)
        ):
            raise ValueError("score adjustments require reason and grounding")


@dataclass(frozen=True)
class AxisAssessment:
    axis: str
    verdict: str
    text: str
    grounding: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.axis not in SCIENTIFIC_AXES:
            raise ValueError(f"unknown scientific axis: {self.axis!r}")
        if self.verdict not in SCIENTIFIC_VERDICTS:
            raise ValueError(f"unknown scientific verdict: {self.verdict!r}")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("axis assessment text must not be empty")
        if not _has_grounding(self.grounding):
            raise ValueError("axis assessments require grounding")


@dataclass(frozen=True)
class ScientificJudgment:
    summary: str
    axes: tuple[AxisAssessment, ...]
    strengths: tuple[GroundedComment, ...]
    weaknesses: tuple[GroundedComment, ...]
    questions: tuple[GroundedQuestion, ...]
    scores: Mapping[str, ScoreAdjustment]

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("scientific judgment summary must not be empty")


@dataclass(frozen=True)
class SpecialistReview:
    """One role's validated, evidence-grounded committee contribution."""

    role: str
    assessments: tuple[AxisAssessment, ...]
    strengths: tuple[GroundedComment, ...]
    weaknesses: tuple[GroundedComment, ...]
    questions: tuple[GroundedComment, ...]
    provisional_scores: Mapping[str, ScoreAdjustment]

    def __post_init__(self) -> None:
        if self.role not in COMMITTEE_ROLES:
            raise ValueError(f"unknown committee role: {self.role!r}")
        axes = tuple(item.axis for item in self.assessments)
        expected = SPECIALIST_AXES[self.role]
        if axes != expected:
            raise ValueError(
                f"{self.role} assessments must cover exactly: {', '.join(expected)}"
            )
        if (
            len(self.strengths) > 5
            or len(self.weaknesses) > 5
            or len(self.questions) > 5
        ):
            raise ValueError("specialist sections are limited to five items each")
        if not self.provisional_scores:
            raise ValueError("specialist review requires provisional score reasoning")


@dataclass(frozen=True)
class JudgmentDraft:
    summary: str
    strengths: tuple[GroundedComment, ...]
    weaknesses: tuple[GroundedComment, ...]
    questions: tuple[GroundedQuestion, ...]
    scores: Mapping[str, ScoreAdjustment]

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("judgment summary must not be empty")
        if len(self.questions) > 5:
            raise ValueError("at most five author questions are allowed")
