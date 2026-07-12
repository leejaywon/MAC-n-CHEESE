#!/usr/bin/env python3
"""Build the four-page Ralphthon Track 2 technical report with PyMuPDF."""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parent
OUTPUT = (
    Path(sys.argv[1]).expanduser().resolve()
    if len(sys.argv) > 1
    else ROOT / "ralphthon-track2-technical-report.pdf"
)

CSS = """
body { font-family: sans-serif; font-size: 9pt; line-height: 1.28; color: #172126; }
h1 { font-size: 23pt; line-height: 1.08; color: #174f5b; margin: 0 0 8pt 0; }
h2 { font-size: 14pt; color: #174f5b; margin: 9pt 0 4pt 0; border-bottom: 0.7pt solid #9bb7bd; }
h3 { font-size: 10.5pt; color: #253e45; margin: 7pt 0 2pt 0; }
p { margin: 0 0 5pt 0; text-align: justify; }
ul, ol { margin: 2pt 0 6pt 15pt; padding: 0; }
li { margin: 0 0 2.5pt 0; }
.kicker { color: #517078; font-size: 9pt; letter-spacing: 0.4pt; margin-bottom: 13pt; }
.lead { font-size: 10.3pt; line-height: 1.35; color: #253e45; }
.abstract { background-color: #eef4f5; border: 0.7pt solid #b9cdd1; padding: 8pt; }
.flow { width: 100%; border-collapse: collapse; margin: 8pt 0; }
.flow td { border: 0.7pt solid #86a8af; background-color: #f5f8f9; padding: 6pt; text-align: center; font-size: 8.2pt; }
.note { border-left: 3pt solid #2f7280; padding-left: 7pt; color: #29444b; }
.scores { width: 100%; border-collapse: collapse; margin: 5pt 0; }
.scores th { background-color: #dce9eb; color: #174f5b; padding: 4pt; border: 0.5pt solid #a9c0c5; }
.scores td { padding: 4pt; border: 0.5pt solid #b8c9cc; }
code { font-family: monospace; font-size: 8pt; color: #204d57; }
"""

PAGES = [
    """
    <div class="kicker">RALPHTHON @ ICML 2026 · TRACK 2 TECHNICAL REPORT · TEAM NO FREE LUNCH</div>
    <h1>NFL-Auditor</h1>
    <p class="lead"><b>Evidence-Bound Scientific Reviewing with Deterministic Auditing and a Grounded Multi-Agent Committee</b></p>

    <h2>Abstract</h2>
    <div class="abstract"><p>
    Automated paper review must combine scientific judgment with resistance to
    fabricated evidence, prompt injection, and operational failure. NFL-Auditor
    is a hybrid Track 2 review system for evaluating Ralphthon Track 1 papers in
    the ICML review format. Its deterministic layer converts each PDF into a
    canonical, content-addressed document; quarantines concealed payloads before
    analysis; extracts claims, tables, citations, and numeric results; and runs
    reproducible consistency, arithmetic, evidence, positioning, and integrity
    checks. Scientific quality is assessed by three concurrent specialists: a
    theorist for problem-method fit, an experimentalist for claim-experiment
    alignment and validity, and a scope/ablation reviewer for generalization and
    design choices. A fourth area-chair stage reconciles their structured
    assessments into grounded strengths, weaknesses, author questions, and all
    six platform scores. Strict schema and evidence validation reject unsupported
    output, while deterministic findings and integrity caps remain authoritative.
    A guidance-driven API adapter validates the fixed ten-paper assignment set,
    preserves local artifacts, and separates review preparation from time-gated
    submission.
    </p></div>

    <h2>1. System Objective</h2>
    <p>
    A mechanical checker can prove an arithmetic error but cannot decide whether
    a method addresses its stated problem. A free-form model can discuss research
    quality but may invent evidence or follow instructions embedded in a paper.
    NFL-Auditor combines both capabilities while keeping their responsibilities
    separate: deterministic code establishes auditable facts, and a validated
    committee supplies scientific judgment.
    </p>

    <h2>2. End-to-End Architecture</h2>
    <table class="flow"><tr>
      <td>Secure PDF<br/>ingestion</td><td>Deterministic<br/>S1-S6 audit</td>
      <td>3 scientific<br/>specialists</td><td>Area-chair<br/>meta-review</td>
      <td>Validated review<br/>and API payload</td>
    </tr></table>
    <p>The architecture is governed by five implementation principles:</p>
    <ol>
      <li><b>Sanitize before interpretation:</b> hidden content is removed before parsing, retrieval, scoring, or model use.</li>
      <li><b>Evidence before verdict:</b> central comments and score rationales cite stable evidence identifiers.</li>
      <li><b>Separate identities:</b> deterministic audit and scientific judgment provenance are frozen independently.</li>
      <li><b>Specialize scientific review:</b> logical fit, experiments, and scope receive independent assessments.</li>
      <li><b>Isolate failures:</b> one paper or service failure cannot cancel the remaining review batch.</li>
    </ol>
    """,
    """
    <div class="kicker">NFL-AUDITOR · SECURE INGESTION AND DETERMINISTIC AUDIT</div>
    <h2>3. Canonical Document and Injection Resistance</h2>
    <p>
    The original PDF and derived Markdown are represented as distinct immutable
    sources. The canonical record captures media type, byte length, page count,
    converter version, and content digest. The local path is provenance only and
    is excluded from the content-addressed review identity.
    </p>
    <h3>3.1 Concealed PDF text quarantine</h3>
    <p>
    Ordinary PDF conversion can flatten white-on-white, transparent, or
    non-rendering text into normal extracted text. NFL-Auditor inspects PDF spans
    before conversion, estimates the page background, and quarantines
    low-contrast, transparent, sub-pixel, and non-rendering spans. Concealed text
    never reaches claim extraction, findings, scores, or scientific review.
    Location-only integrity records remain available for the audit.
    </p>
    <h3>3.2 Sanitize-first text pipeline</h3>
    <p>
    The Markdown sanitizer removes hidden HTML, comments, Unicode format
    controls, and reviewer-directed instructions while preserving line
    structure. The parser then inventories sections, paragraphs, tables,
    references, numeric tokens, and line/column locations. Scientific evidence
    is split into bounded stable spans such as <code>paper:L120-L131</code>.
    </p>

    <h2>4. Deterministic S1-S6 Audit</h2>
    <ol>
      <li><b>S1 Parse:</b> construct section, table, citation, and numeric-token inventories.</li>
      <li><b>S2 Claims:</b> extract falsifiable result, arithmetic, hypothesis, and declarative claims.</li>
      <li><b>S3 Checks:</b> execute evidence, consistency, formatting, positioning, and integrity checks.</li>
      <li><b>S4 Verdicts:</b> label claims supported, contradicted, or unverifiable with evidence pointers.</li>
      <li><b>S5 Compose:</b> draft comments and retain only comments licensed by their evidence.</li>
      <li><b>S6 Freeze:</b> bind source identities, evidence snapshots, agent version, and verdict labels.</li>
    </ol>
    <p>
    The check battery covers result-ledger traceability, table-to-prose
    consistency, arithmetic recomputation, baseline fairness, omitted negative
    outcomes, citation existence, template compliance, related-work positioning,
    self-review consistency, and injection scanning. Findings are matched to
    compatible claim types and overlapping spans rather than indiscriminately
    affecting every claim on a line.
    </p>

    <h2>5. Evidence-Grounded Composition</h2>
    <p>
    Composition uses a draft-and-ground pattern. Unsupported praise is removed;
    criticism without defect evidence becomes an author question. An empty
    References heading is not treated as positioning, and an unavailable
    external lookup is recorded as unavailable rather than as a paper defect.
    The audit therefore distinguishes “not verified” from “proven false.”
    </p>
    <p class="note">
    The deterministic review identity and ordered verdict digest are stable
    records of what the code established from the frozen input.
    </p>
    """,
    """
    <div class="kicker">NFL-AUDITOR · SCIENTIFIC COMMITTEE AND SCORING</div>
    <h2>6. Scientific Review Committee</h2>
    <p>
    The scientific layer is a real four-stage committee. Three specialist calls
    run concurrently over role-targeted packets assembled only from sanitized
    paper spans and deterministic findings.
    </p>
    <h3>Theorist</h3>
    <p>Assesses problem formulation, assumptions, logical validity, and whether the proposed method addresses the stated problem.</p>
    <h3>Experimentalist</h3>
    <p>Assesses claim-experiment alignment, controls, baselines, metrics, confounds, statistical support, and experimental validity.</p>
    <h3>Scope and ablation reviewer</h3>
    <p>Assesses generalization, experimental scope, design-choice justification, ablations, robustness, and stated limitations.</p>

    <h2>7. Area-Chair Synthesis</h2>
    <p>
    When at least two specialists produce valid assessments, an area-chair stage
    reconciles their outputs with the deterministic audit and retrieved
    prior-work records. The final structured judgment covers five scientific
    axes: problem-method fit, claim-experiment alignment, experimental-design
    validity, scope/generalization, and design-choice/ablation justification.
    </p>
    <p>
    The synthesis produces a paper-specific summary, grounded strengths and
    weaknesses, three to five numbered author questions, and an explanation of
    what each answer would change. Every assessment and score rationale must cite
    an allowed paper span, claim, finding, or literature record. Missing axes,
    unknown evidence IDs, duplicate IDs, empty text, extra fields, incorrect
    numeric types, and out-of-range scores are rejected.
    </p>

    <h2>8. Direct Platform Scoring</h2>
    <table class="scores">
      <tr><th>Dimension</th><th>Range</th><th>Primary basis</th></tr>
      <tr><td>Soundness</td><td>1-4</td><td>Logical and empirical validity</td></tr>
      <tr><td>Presentation</td><td>1-4</td><td>Clarity and completeness</td></tr>
      <tr><td>Significance</td><td>1-4</td><td>Importance of supported contribution</td></tr>
      <tr><td>Originality</td><td>1-4</td><td>Positioning and differentiated contribution</td></tr>
      <tr><td>Overall</td><td>1-6</td><td>Integrated recommendation</td></tr>
      <tr><td>Confidence</td><td>1-5</td><td>Coverage and evidential certainty</td></tr>
    </table>
    <p>
    Valid scientific scores may move above or below deterministic anchors.
    Mechanical contradictions remain visible, and proven contradictions,
    dishonest self-certification, or concealed-content findings cap Soundness
    and Overall at 2 after scientific scoring.
    </p>

    <h2>9. Failure-Isolated Review</h2>
    <p>
    One failed specialist does not cancel synthesis. If specialist quorum is
    unavailable or the area-chair result is invalid, the paper receives the
    complete deterministic review. Model, retrieval, or conversion failures are
    isolated to their assignment, allowing the remaining papers to proceed.
    </p>
    """,
    """
    <div class="kicker">NFL-AUDITOR · TEN-PAPER EXECUTION AND OUTPUT</div>
    <h2>10. Guidance-Driven Ten-Paper Workflow</h2>
    <p>
    The live adapter treats the organizer's canonical <code>skill.md</code> as
    the operational contract. It parses typed stage, reason, actor,
    prerequisite, next-action, and KST timing values and branches on stable
    reason codes rather than prose.
    </p>
    <ol>
      <li>Exchange a human-issued setup token once; retain the bearer only in memory.</li>
      <li>Read authenticated status without implicitly allocating work.</li>
      <li>Acquire assignments only when returned guidance permits it.</li>
      <li>Validate exactly ten unique ordinals, 1-10, before optional filtering.</li>
      <li>Download only returned scoped HTTPS PDF URLs on the canonical host.</li>
      <li>Store originals under <code>submit_work/assigned_papers/ordinal-XX/paper.pdf</code>.</li>
      <li>Prepare paper reviews concurrently before the write window.</li>
      <li>Refresh status and canonical guidance before each serialized review POST.</li>
      <li>Submit only in the half-open interval [16:35, 17:00) KST and stop on terminal guidance.</li>
    </ol>

    <h2>11. Output and Reproducibility</h2>
    <p>
    Each local review contains Summary, Strengths, Weaknesses, Questions for the
    Authors, Scores, Ethics and Limitations, Evidence Trace, and a closing
    recommendation. The local trace records original and derived identities,
    citation snapshots, deterministic verdicts, committee call provenance, and
    the independent scientific judgment identity.
    </p>
    <p>
    The live payload contains exactly the platform fields: ordinal, Soundness,
    Presentation, Significance, Originality, Overall, Confidence, and comments.
    Before transmission, NFL-Auditor extracts only substantive review sections;
    local paths, content hashes, prompt hashes, storage details, and private
    assignment metadata remain local.
    </p>

    <h2>12. Operational Safety</h2>
    <ul>
      <li>Credentials are not accepted through command-line arguments and are never written to disk.</li>
      <li>Redirects are rejected before authenticated downloads.</li>
      <li>Prepared reviews are reused only when source, agent, mode, schema, and artifact identities match.</li>
      <li>Already-submitted ordinals are skipped, enabling safe resume.</li>
      <li>Transient service errors use bounded retries; permanent validation errors are not repeated unchanged.</li>
    </ul>

    <h2>13. Conclusion</h2>
    <p>
    NFL-Auditor combines a reproducible evidence and integrity substrate with
    specialized scientific reasoning. The deterministic layer protects the
    review from concealed content, unsupported claims, arithmetic errors, and
    service failure. The committee supplies the problem-method, experimental,
    scope, and ablation judgments that a mechanical audit cannot provide.
    Strict validation, independent identities, hard integrity caps, local
    artifact preservation, and per-paper fallback support a time-bounded
    ten-paper Ralphthon workflow.
    </p>

    <h2>Implementation Map</h2>
    <p>
    Secure ingestion: <code>document.py</code>, <code>to_markdown.py</code>,
    <code>injection_scan.py</code>. Audit and composition:
    <code>pipeline.py</code>, <code>claims.py</code>, <code>composer.py</code>.
    Scientific committee: <code>scientific_review.py</code>,
    <code>model_critique.py</code>, <code>review_schema.py</code>. Deployment:
    <code>agent_api.py</code>, <code>api_scores.py</code>, and
    <code>submit.py</code>.
    </p>
    """,
]


def build() -> None:
    page_rect = pymupdf.paper_rect("a4")
    content_rect = pymupdf.Rect(42, 38, page_rect.width - 42, page_rect.height - 38)
    writer = pymupdf.DocumentWriter(str(OUTPUT))
    for index, html in enumerate(PAGES, 1):
        story = pymupdf.Story(html=html, user_css=CSS)
        device = writer.begin_page(page_rect)
        more, _ = story.place(content_rect)
        story.draw(device)
        writer.end_page()
        if more:
            writer.close()
            OUTPUT.unlink(missing_ok=True)
            raise RuntimeError(f"page {index} content overflowed its fixed page")
    writer.close()

    document = pymupdf.open(OUTPUT)
    for index, page in enumerate(document, 1):
        page.insert_text(
            (42, page_rect.height - 19),
            "NFL-Auditor · Track 2 Technical Report",
            fontname="helv",
            fontsize=7,
            color=(0.25, 0.38, 0.41),
        )
        footer = f"{index} / {len(document)}"
        width = pymupdf.get_text_length(footer, fontname="helv", fontsize=7)
        page.insert_text(
            (page_rect.width - 42 - width, page_rect.height - 19),
            footer,
            fontname="helv",
            fontsize=7,
            color=(0.25, 0.38, 0.41),
        )
    temporary = OUTPUT.with_suffix(".tmp.pdf")
    document.save(temporary, garbage=4, deflate=True)
    document.close()
    temporary.replace(OUTPUT)

    check = pymupdf.open(OUTPUT)
    if len(check) != 4:
        raise RuntimeError(f"expected 4 pages, generated {len(check)}")
    text = "\n".join(page.get_text() for page in check)
    check.close()
    for required in (
        "NFL-Auditor",
        "S1-S6",
        "Area-Chair",
        "Ten-Paper",
        "Conclusion",
    ):
        if required not in text:
            raise RuntimeError(f"generated PDF is missing {required!r}")
    print(f"wrote {OUTPUT} (4 pages)")


if __name__ == "__main__":
    build()
