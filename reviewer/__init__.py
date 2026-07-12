"""Evidence-bound audit pipeline with an optional scientific committee."""

from .baseline_fairness import check_baseline_fairness
from .citation_existence import check_citation_existence
from .document import PreparedPaper, SourceIdentity, prepare_paper
from .pipeline import ReviewPipeline, run_pipeline
from .claims import extract_claims, label_verdicts
from .composer import (
    apply_scientific_scores,
    calibrate_scores,
    draft_comments,
    ground_comments,
)
from .mechanical_checks import check_arithmetic, check_internal_consistency, check_ledger_trace
from .injection_scan import check_injection_scan, sanitize_for_analysis, scan_and_sanitize
from .model_critique import (
    committee_review,
    compute_judgment_identity,
    review_committee,
    run_committee,
)
from .negative_evidence import check_negative_evidence
from .parser import paper_text, parse_markdown
from .positioning import check_positioning
from .review_schema import (
    COMMITTEE_ROLES,
    SCIENTIFIC_AXES,
    SCIENTIFIC_RUBRIC_VERSION,
    ScientificJudgment,
    SpecialistReview,
)
from .scientific_review import (
    PaperSpan,
    ScientificEvidencePacket,
    build_evidence_packet,
    filter_evidence_packet,
    render_evidence_packet,
    validate_judgment,
    validate_specialist_review,
)
from .template_compliance import check_template_compliance

__all__ = [
    "ReviewPipeline",
    "PreparedPaper",
    "SourceIdentity",
    "extract_claims",
    "label_verdicts",
    "apply_scientific_scores",
    "calibrate_scores",
    "draft_comments",
    "ground_comments",
    "COMMITTEE_ROLES",
    "SCIENTIFIC_AXES",
    "SCIENTIFIC_RUBRIC_VERSION",
    "ScientificJudgment",
    "SpecialistReview",
    "PaperSpan",
    "ScientificEvidencePacket",
    "build_evidence_packet",
    "filter_evidence_packet",
    "render_evidence_packet",
    "validate_judgment",
    "validate_specialist_review",
    "committee_review",
    "review_committee",
    "run_committee",
    "compute_judgment_identity",
    "check_baseline_fairness",
    "check_citation_existence",
    "check_arithmetic",
    "check_internal_consistency",
    "check_injection_scan",
    "check_ledger_trace",
    "check_negative_evidence",
    "check_positioning",
    "check_template_compliance",
    "parse_markdown",
    "paper_text",
    "prepare_paper",
    "sanitize_for_analysis",
    "scan_and_sanitize",
    "run_pipeline",
]
