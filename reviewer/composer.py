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
) -> dict[str, dict[str, Any]]:
    """Apply the explicit §5 borderline-first scoring policy."""

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

    soundness = max(1, min(4, 2 + bool(headline_supported) - bool(contradicted)))
    if contradicted:
        soundness_reason = f"A deterministic contradiction lowers confidence in correctness [{contradicted_anchor}]."
    elif headline_supported:
        soundness_reason = f"At least one headline result has direct mechanical support [{supported_anchor}]."
    else:
        soundness_reason = f"No headline result has implemented mechanical support [{anchor}]."

    # Passing the structural audit alone does not establish clear writing, so
    # it cannot promote presentation above borderline. Proven violations do
    # demote it, while an unknown Markdown page count is kept unverifiable.
    presentation = 1 if template_findings else 2
    if template_findings:
        presentation_reason = (
            f"A deterministic template violation lowers presentation [{template_findings[0]['id']}]; "
            f"the claim inventory begins at [{anchor}]."
        )
    else:
        presentation_reason = (
            f"The structural template audit found no proven violation, but structure alone does not "
            f"establish clear presentation [{anchor}]."
        )
    contribution = 2
    contribution_reason = f"The evidence trace establishes result support, not novelty or broad significance [{anchor}]."

    overall = 3
    if headline_supported:
        overall += 1
    if contradicted:
        overall -= 1
    overall = max(1, min(5, overall))
    if contradicted:
        overall_reason = f"The borderline anchor is reduced by a contradicted claim [{contradicted_anchor}]."
    elif headline_supported:
        overall_reason = f"The borderline anchor is raised only because a headline claim is supported [{supported_anchor}]."
    else:
        overall_reason = f"The recommendation remains borderline without a supported headline claim [{anchor}]."

    fraction = len(verifiable) / len(claims) if claims else 0.0
    confidence = max(1, min(5, 1 + round(4 * fraction)))
    confidence_reason = (
        f"{len(verifiable)}/{len(claims)} extracted claims are mechanically verifiable; "
        f"the inventory begins at [{anchor}]."
    )

    return {
        "Soundness": {"value": soundness, "scale": SCORE_SCALES["Soundness"], "rationale": soundness_reason},
        "Presentation": {"value": presentation, "scale": SCORE_SCALES["Presentation"], "rationale": presentation_reason},
        "Contribution": {"value": contribution, "scale": SCORE_SCALES["Contribution"], "rationale": contribution_reason},
        "Overall recommendation": {"value": overall, "scale": SCORE_SCALES["Overall recommendation"], "rationale": overall_reason},
        "Confidence": {"value": confidence, "scale": SCORE_SCALES["Confidence"], "rationale": confidence_reason},
    }
