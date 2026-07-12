# Track 2 Technical Report Design

## Deliverables

- English, four-page A4 technical report PDF for the Ralphthon Track 2 form.
- Reproducible Markdown source and PyMuPDF build script.
- Separate copy-ready Title and Abstract.

## Narrative

The report presents NFL-Auditor as a hybrid review system rather than as a
mechanical checker or an unconstrained LLM reviewer. It explains:

1. secure PDF ingestion and sanitize-before-analysis;
2. deterministic S1–S6 evidence auditing and frozen identities;
3. three concurrent scientific specialists plus a grounded area-chair
   meta-review;
4. strict schema, score calibration, integrity caps, and per-paper fallback;
5. guidance-driven acquisition and submission of exactly ten assignments.

## Page Plan

1. Motivation, abstract, contributions, and end-to-end architecture.
2. Canonical document pipeline, deterministic audit, grounding, and scoring.
3. Scientific committee, strict validation, merge policy, and failure handling.
4. Ten-paper deployment, reproducibility, current verification status,
   limitations, and conclusion.

## Claims Policy

The report distinguishes implemented mechanisms from completed validation. It
does not claim that the final committee/deployment delta has passed the deferred
test suite or that ten live Track 1 papers have already been reviewed. Organizer
availability and the live execution window are stated as external dependencies.

## Visual Style

Clean conference-report layout: restrained teal accent, compact architecture
diagram, readable two-column technical content where useful, page numbers, no
decorative graphics, and no screenshots of private credentials or assignments.
