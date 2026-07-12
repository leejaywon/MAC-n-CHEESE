"""Two-pass, evidence-bound S5 review composition.

The DRAFT pass is deliberately cheap and deterministic: it proposes short
comments from S4 verdicts.  The GROUND pass is the authority.  It retains a
statement only when its stance is licensed by the referenced claim verdict or
finding.  This keeps the event runtime offline while preserving the same
separation of responsibilities as a cheap-model/strong-grounder design.
"""

from __future__ import annotations

from typing import Any


SCORE_SCALES = {
    "Soundness": "1-4",
    "Presentation": "1-4",
    "Contribution": "1-4",
    "Overall recommendation": "1-5",
    "Confidence": "1-5",
}


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
    """Apply the explicit §5 borderline-first scoring policy.

    An integrity breach — a proven contradiction OR a dishonest self-certification
    — is a serious soundness problem that a supported headline result must not
    offset. ``self_review_dishonest`` is the count of dishonest Self-Review boxes.
    ``positioning`` is the deterministic related-work / novelty audit; a proven
    novelty/SOTA overclaim (a superiority claim situated against no prior work)
    lowers Contribution below the borderline anchor. Absent a proven overclaim,
    Contribution stays at the borderline — verified novelty and broad significance
    are not machine-checkable here and are left to the ``--best`` judgment layer,
    so this deterministic pass never inflates Contribution.
    """

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

    # Grounded uplift signals: every score above the borderline must be EARNED by
    # evidence, never awarded by default. This keeps the "no fabricated praise"
    # property while letting a strong, clean, well-situated paper reach the top of
    # each scale (so scores correlate with human judges instead of hitting an
    # artificial ceiling).
    signals = (positioning or {}).get("signals", {})
    positioned = bool(signals.get("positioned"))
    situated_novelty = positioned and signals.get("novelty_claim_count", 0) > 0
    # Injection-scan findings are a security/ethics signal about hidden
    # reviewer-directed instructions, not a scientific defect, so they must not
    # move the scientific scores — otherwise an injection twin would score
    # differently from its sanitized-identical clean counterpart.
    scientific_findings = [
        finding for finding in (findings or []) if finding.get("check") != "injection-scan"
    ]
    clean_run = not scientific_findings  # zero proven scientific findings
    strong_support = len(headline_supported) >= 2
    has_results = any(claim.get("type") in {"result", "arithmetic"} for claim in claims)

    breach_count = len(contradicted) + self_review_dishonest
    integrity_breach = breach_count > 0
    if integrity_breach:
        soundness = 1
        soundness_reason = (
            f"A proven integrity breach ({len(contradicted)} contradiction(s), "
            f"{self_review_dishonest} dishonest self-certification(s)) undermines soundness "
            f"[{contradicted_anchor}]."
        )
    elif headline_supported and clean_run and strong_support:
        soundness = 4
        soundness_reason = (
            f"Multiple headline results have direct mechanical support and no finding was proven "
            f"[{supported_anchor}]."
        )
    elif headline_supported:
        soundness = 3
        soundness_reason = f"At least one headline result has direct mechanical support [{supported_anchor}]."
    elif positioned and has_results and clean_run:
        soundness = 3
        soundness_reason = (
            f"No contradiction or finding was proven and the reported results are situated against "
            f"cited prior work, though they could not be independently verified [{anchor}]."
        )
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
        contribution = 1
        contribution_reason = (
            f"A novelty/SOTA claim at paper line {overclaim['location']['line']} is situated against "
            f"no cited prior work, so the contribution is not established [{anchor}]."
        )
    elif situated_novelty:
        contribution = 3
        contribution_reason = (
            f"The paper makes a novelty claim situated against cited prior work — a contribution "
            f"beyond mere result support [{anchor}]."
        )
    else:
        contribution = 2
        contribution_reason = (
            f"The evidence trace establishes result support, not verified novelty or broad "
            f"significance [{anchor}]."
        )

    if integrity_breach:
        overall = 1 if breach_count >= 2 else 2
        overall_reason = (
            f"A proven integrity breach ({breach_count} issue(s)) drives a reject recommendation; "
            f"supported results do not offset it [{contradicted_anchor}]."
        )
    elif headline_supported and clean_run and situated_novelty and strong_support:
        overall = 5
        overall_reason = (
            f"Multiple supported headline results, a situated contribution, and no proven finding "
            f"support a strong accept [{supported_anchor}]."
        )
    elif headline_supported:
        overall = 4
        overall_reason = f"A supported headline result with no proven contradiction supports acceptance [{supported_anchor}]."
    else:
        overall = 3
        overall_reason = f"The recommendation remains borderline without a supported headline claim [{anchor}]."
    overall = max(1, min(5, overall))

    # Confidence is the reviewer's CERTAINTY in this review, driven by how much of
    # it rests on mechanically proven evidence (S3 findings + verified verdicts)
    # rather than unverifiable prose. A bare manuscript with nothing to check is
    # low confidence; a review anchored in proven findings/verdicts is high.
    proven = len(scientific_findings) + len(verifiable)
    coverage = min(1.0, proven / len(claims)) if claims else 0.0
    confidence = max(1, min(5, 1 + round(4 * coverage)))
    confidence_reason = (
        f"Review certainty reflects mechanical coverage: {len(scientific_findings)} proven finding(s) and "
        f"{len(verifiable)}/{len(claims)} verifiable claim(s) anchor the assessment [{anchor}]."
    )

    return {
        "Soundness": {"value": soundness, "scale": SCORE_SCALES["Soundness"], "rationale": soundness_reason},
        "Presentation": {"value": presentation, "scale": SCORE_SCALES["Presentation"], "rationale": presentation_reason},
        "Contribution": {"value": contribution, "scale": SCORE_SCALES["Contribution"], "rationale": contribution_reason},
        "Overall recommendation": {"value": overall, "scale": SCORE_SCALES["Overall recommendation"], "rationale": overall_reason},
        "Confidence": {"value": confidence, "scale": SCORE_SCALES["Confidence"], "rationale": confidence_reason},
    }
