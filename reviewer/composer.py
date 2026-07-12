"""Two-pass deterministic composition plus validated committee score merging.

The DRAFT pass is deliberately cheap and deterministic: it proposes short
comments from S4 verdicts.  The GROUND pass is the authority.  It retains a
statement only when its stance is licensed by the referenced claim verdict or
finding.  This keeps the event runtime offline while preserving the same
separation of responsibilities when best mode later adds a scientific
committee judgment.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .review_schema import ScientificJudgment


SCORE_SCALES = {
    "Soundness": "1-4",
    "Presentation": "1-4",
    "Significance": "1-4",
    "Originality": "1-4",
    "Overall recommendation": "1-6",
    "Confidence": "1-5",
}


def apply_scientific_scores(
    deterministic_scores: Mapping[str, Mapping[str, Any]],
    judgment: ScientificJudgment,
    *,
    integrity_breach: bool = False,
    integrity_grounding: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Copy all six validated direct scores, then enforce proven-integrity caps."""

    if not isinstance(judgment, ScientificJudgment):
        raise TypeError("judgment must be a validated ScientificJudgment")
    final = {
        dimension: dict(score)
        for dimension, score in deterministic_scores.items()
    }
    for dimension, scale in SCORE_SCALES.items():
        adjustment = judgment.scores[dimension]
        grounding = (
            (adjustment.grounding,)
            if isinstance(adjustment.grounding, str)
            else adjustment.grounding
        )
        citation = ", ".join(grounding)
        rationale = " ".join(adjustment.reason.split())
        if citation:
            rationale = f"{rationale} Grounding: [{citation}]."
        final[dimension] = {
            "value": adjustment.value,
            "scale": scale,
            "rationale": rationale,
        }

    if integrity_breach:
        anchors = tuple(
            grounding_id
            for grounding_id in integrity_grounding
            if isinstance(grounding_id, str) and grounding_id.strip()
        )
        anchor_text = f" [{', '.join(anchors)}]" if anchors else ""
        for dimension in ("Soundness", "Overall recommendation"):
            score = final[dimension]
            score["value"] = min(int(score["value"]), 2)
            score["rationale"] = (
                f"{score['rationale']} Deterministic integrity cap: a proven "
                f"contradiction or dishonest self-certification limits "
                f"{dimension} to at most 2{anchor_text}."
            )
    return final


def normalize_overall(
    soundness: int,
    presentation: int,
    significance: int,
    originality: int,
    headline_supported: int,
) -> int:
    """Return a conservative direct 1-6 recommendation.

    The deterministic layer never emits 6. Unsupported manuscripts are capped
    at 3, one supported headline result permits 4, and multiple supported
    headline results plus adequate presentation permit 5.
    """

    if headline_supported <= 0:
        mean = (soundness + presentation + significance + originality) / 4
        return min(3, max(1, int(mean + 0.5)))
    if headline_supported == 1:
        return 4 if soundness >= 3 else 3
    return 5 if presentation >= 3 and soundness >= 3 else 4


def draft_comments(
    claims: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """DRAFT: propose concise candidate comments without deciding grounding."""

    verdict_by_claim = {item["claim_id"]: item for item in verdicts}
    comments: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = claim["id"]
        verdict = verdict_by_claim[claim_id]
        label = verdict["label"]
        if label == "supported":
            comments.append(
                {
                    "section": "Strengths",
                    "stance": "praise",
                    "text": f"The result claim is directly supported by the supplied evidence [{claim_id}].",
                    "claim_id": claim_id,
                    "references": [claim_id, *verdict["evidence"]],
                }
            )
        elif label == "contradicted":
            # A contradicted claim is contradicted BY a specific finding at its
            # line, and that finding is rendered below with its full expected/
            # observed detail. A separate opaque "conflicts with evidence" line
            # would just duplicate it, so skip it here (the claim->finding link
            # is preserved in the Evidence Trace).
            continue
        elif claim.get("type") in {"result", "arithmetic", "hypothesis"}:
            # Only substantive unverifiable claims (results, arithmetic,
            # hypotheses) warrant an evidence request. Demoting EVERY unverifiable
            # prose sentence to a question spams the review with dozens of
            # identical "provide auditable evidence" lines on any real paper —
            # unverifiable is the normal state of most prose, not a defect.
            comments.append(
                {
                    "section": "Weaknesses",
                    "stance": "criticism",
                    "text": f"The paper does not provide mechanically verifiable support for this claim [{claim_id}].",
                    "claim_id": claim_id,
                    "references": [claim_id],
                }
            )

    # Findings are also drafted independently so a contradiction remains
    # visible even when claim extraction changes around a malformed passage.
    for finding in findings:
        comments.append(
            {
                "section": "Weaknesses",
                "stance": "criticism",
                "text": (
                    f"The {finding['check']} check observed {finding['observed']}; "
                    f"expected {finding['expected']} [{finding['id']}]."
                ),
                "claim_id": None,
                "references": [finding["id"]],
            }
        )
    return comments


def ground_comments(
    draft: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """GROUND: delete unsupported praise and demote unproven criticism.

    A criticism may cite a claim but still be ungrounded as criticism when S4
    labels that claim unverifiable.  It then becomes a neutral author question,
    retaining its claim ID so the question itself remains traceable.
    """

    claim_ids = {item["id"] for item in claims}
    finding_ids = {item["id"] for item in findings}
    verdict_by_claim = {item["claim_id"]: item for item in verdicts}
    retained: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    reclassified: list[dict[str, Any]] = []

    for candidate in draft:
        claim_id = candidate.get("claim_id")
        references = list(dict.fromkeys(candidate.get("references", [])))
        known_references = [ref for ref in references if ref in claim_ids or ref in finding_ids]
        verdict = verdict_by_claim.get(claim_id)
        stance = candidate.get("stance")
        finding_grounded = any(ref in finding_ids for ref in known_references)

        if stance == "praise":
            licensed = verdict is not None and verdict["label"] == "supported"
            if not licensed or not known_references:
                deleted.append(candidate)
                continue
        elif stance == "criticism":
            licensed = finding_grounded or (verdict is not None and verdict["label"] == "contradicted")
            if not licensed:
                if claim_id in claim_ids:
                    converted = {
                        **candidate,
                        "section": "Questions for the Authors",
                        "stance": "question",
                        "text": f"Can the authors provide auditable evidence for this claim [{claim_id}]?",
                        "references": [claim_id],
                    }
                    retained.append(converted)
                    reclassified.append(converted)
                else:
                    # With no real claim/finding ID there is no safe target for
                    # even a question, so the sentence cannot enter the review.
                    deleted.append(candidate)
                continue
        elif stance == "question":
            if claim_id not in claim_ids:
                deleted.append(candidate)
                continue
        else:
            deleted.append(candidate)
            continue

        grounded = {**candidate, "references": known_references}
        retained.append(grounded)

    return {
        "comments": retained,
        "deleted": deleted,
        "reclassified": reclassified,
    }


def calibrate_scores(
    claims: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    self_review_dishonest: int = 0,
    positioning: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Score directly in the six-field openagentreview.org schema."""

    verdict_by_claim = {item["claim_id"]: item for item in verdicts}
    supported = [claim for claim in claims if verdict_by_claim[claim["id"]]["label"] == "supported"]
    contradicted = [claim for claim in claims if verdict_by_claim[claim["id"]]["label"] == "contradicted"]
    verifiable = [*supported, *contradicted]
    headline_supported = [
        claim for claim in supported if claim.get("type") in {"result", "arithmetic"}
    ]
    anchor = claims[0]["id"] if claims else "no-extracted-claim"
    supported_anchor = headline_supported[0]["id"] if headline_supported else anchor
    contradicted_anchor = contradicted[0]["id"] if contradicted else anchor
    template_findings = [
        finding for finding in (findings or []) if finding.get("check") == "template-compliance"
    ]

    signals = (positioning or {}).get("signals", {})
    positioned = bool(signals.get("positioned"))
    situated_novelty = positioned and signals.get("novelty_claim_count", 0) > 0
    scientific_findings = [
        finding for finding in (findings or []) if finding.get("check") != "injection-scan"
    ]
    clean_run = not scientific_findings  # zero proven scientific findings
    has_results = any(claim.get("type") in {"result", "arithmetic"} for claim in claims)

    # Concealed reviewer-directed text is quarantined before analysis and reported
    # in Ethics, but it is not scientific evidence about the visible manuscript.
    # Letting it alter scores would make an injected twin score differently from
    # the sanitized paper it actually presents to every scientific check/model.
    breach_count = len(contradicted) + self_review_dishonest
    integrity_breach = breach_count > 0
    integrity_anchor = contradicted_anchor if contradicted else anchor
    if integrity_breach:
        soundness = 1
        soundness_reason = (
            f"A proven integrity breach ({len(contradicted)} contradiction(s), "
            f"{self_review_dishonest} dishonest self-certification(s)) "
            f"undermines soundness [{integrity_anchor}]."
        )
    elif len(headline_supported) >= 2 and clean_run:
        soundness = 4
        soundness_reason = (
            f"Multiple headline results have direct mechanical support and no finding was proven "
            f"[{supported_anchor}]."
        )
    elif headline_supported:
        soundness = 3
        soundness_reason = f"At least one headline result has direct mechanical support [{supported_anchor}]."
    else:
        soundness = 2
        soundness_reason = f"No headline result has mechanical support, but none is contradicted [{anchor}]."

    # A proven template violation demotes presentation; a clean structural audit on
    # a paper that also situates itself against cited prior work reads as a
    # well-formed submission and earns above the borderline.
    if template_findings:
        presentation = 1
        presentation_reason = (
            f"A deterministic template violation lowers presentation [{template_findings[0]['id']}]; "
            f"the claim inventory begins at [{anchor}]."
        )
    elif positioned:
        presentation = 3
        presentation_reason = (
            f"The structural audit found no violation and the paper situates itself against cited "
            f"prior work [{anchor}]."
        )
    else:
        presentation = 2
        presentation_reason = (
            f"The structural template audit found no proven violation, but structure alone does not "
            f"establish clear presentation [{anchor}]."
        )
    positioning_findings = (positioning or {}).get("findings", [])
    overclaim = next(
        (finding for finding in positioning_findings if finding.get("subtype") == "novelty-overclaim"),
        None,
    )
    if overclaim:
        originality = 1
        originality_reason = (
            f"A novelty/SOTA claim at paper line {overclaim['location']['line']} is situated against "
            f"no cited prior work, so originality is not established [{anchor}]."
        )
    elif situated_novelty:
        originality = 3
        originality_reason = (
            f"The novelty claim is explicitly situated against prior work, while external novelty "
            f"remains a judgment-layer question [{anchor}]."
        )
    else:
        originality = 2
        originality_reason = (
            f"The deterministic trace neither establishes nor disproves novelty [{anchor}]."
        )

    if len(headline_supported) >= 2:
        significance = 3
        significance_reason = (
            f"Multiple reported outcomes are evidence-supported, establishing nontrivial empirical "
            f"scope without proving broad field impact [{supported_anchor}]."
        )
    else:
        significance = 2
        significance_reason = (
            f"Broad impact is not mechanically established"
            + (f"; one result is supported [{supported_anchor}]." if headline_supported else f" [{anchor}].")
        )

    if integrity_breach:
        overall = 1 if breach_count >= 2 else 2
        overall_reason = (
            f"A proven integrity breach ({breach_count} issue(s)) drives a reject recommendation; "
            f"supported results do not offset it [{integrity_anchor}]."
        )
    else:
        overall = normalize_overall(
            soundness,
            presentation,
            significance,
            originality,
            len(headline_supported),
        )
        overall_anchor = supported_anchor if headline_supported else anchor
        overall_reason = (
            f"Directly calibrated from Soundness {soundness}/4, Presentation {presentation}/4, "
            f"Significance {significance}/4, Originality {originality}/4"
            + (f" with {len(headline_supported)} evidence-supported headline result(s)" if headline_supported else "")
            + f" [{overall_anchor}]."
        )
    overall = max(1, min(5, overall))

    # Confidence is the reviewer's CERTAINTY in this review, driven by how much of
    # it rests on mechanically proven evidence (S3 findings + verified verdicts)
    # rather than unverifiable prose. A bare manuscript with nothing to check is
    # low confidence; a review anchored in proven findings/verdicts is high.
    # Confidence = the reviewer's CERTAINTY, from how much of the assessment rests
    # on signals the reviewer could actually check — verified/contradicted claims,
    # proven findings, a positioning judgment, and concrete reported results — not
    # result verification alone. So a well-analysed peer paper without an evidence
    # bundle is not stuck reporting 1/5, while an opaque paper stays low.
    evidence_claims = [
        claim for claim in claims if claim.get("type") in {"result", "arithmetic"}
    ]
    verified_evidence_claims = [
        claim for claim in evidence_claims if claim in verifiable
    ]
    coverage = (
        len(verified_evidence_claims) / len(evidence_claims)
        if evidence_claims
        else 0.0
    )
    extraction_quality = 1.0 if claims else 0.0
    positioning_coverage = 1.0 if positioned else 0.0
    confidence = 1
    if extraction_quality:
        confidence += 1
    if coverage > 0:
        confidence += 1
    if coverage >= 0.75 or scientific_findings:
        confidence += 1
    if positioning_coverage and coverage >= 0.5:
        confidence += 1
    confidence = max(1, min(5, confidence))
    confidence_reason = (
        f"Verified result coverage is {len(verified_evidence_claims)}/{len(evidence_claims)}; "
        f"claim extraction {'succeeded' if claims else 'failed'}, positioning is "
        f"{'covered' if positioned else 'not covered'}, and {len(scientific_findings)} finding(s) "
        f"are mechanically grounded [{anchor}]."
    )

    return {
        "Soundness": {"value": soundness, "scale": SCORE_SCALES["Soundness"], "rationale": soundness_reason},
        "Presentation": {"value": presentation, "scale": SCORE_SCALES["Presentation"], "rationale": presentation_reason},
        "Significance": {"value": significance, "scale": SCORE_SCALES["Significance"], "rationale": significance_reason},
        "Originality": {"value": originality, "scale": SCORE_SCALES["Originality"], "rationale": originality_reason},
        "Overall recommendation": {"value": overall, "scale": SCORE_SCALES["Overall recommendation"], "rationale": overall_reason},
        "Confidence": {"value": confidence, "scale": SCORE_SCALES["Confidence"], "rationale": confidence_reason},
    }
