# Ralphthon Track 2 Reviewer Hardening Design

## Goal

Make NFL-Auditor reliable and competitive for Ralphthon Track 2: fetch the ten
assigned PDFs through the evolving `openagentreview.org` agent API, produce
specific ICML-style reviews within the review window, and submit exactly the
server schema. The deterministic audit remains a safety and evidence layer; the
optional model layer supplies the scientific judgment needed for judge-review
similarity.

The design intentionally does not enforce ICML 2026's restrictions on LLM use.
It targets the Ralphthon competition, whose purpose is automated reviewing.

## Constraints

- Treat `https://openagentreview.org/skill.md` as the live API contract, but
  isolate it behind a small client because the organizers are still editing it.
- Never expose setup tokens, bearer tokens, private assignment identifiers, or
  Authorization headers.
- Finish up to ten reviews inside the 16:35–17:00 KST write window.
- Preserve a useful review when citation, retrieval, or model services fail.
- Keep unit tests hermetic. Network PDF tests are an explicit smoke command, not
  part of the default test suite.
- Sample fresh public arXiv PDFs for each smoke run. Persist that run's URLs,
  arXiv identifiers, retrieval timestamps, and SHA-256 hashes so the exact
  sample can be replayed afterward.

## Architecture

### 1. Input and canonical document

Introduce a canonical document representation with:

- original input path, media type, SHA-256, byte length, and PDF page count;
- converted Markdown path and SHA-256;
- visible sanitized text used by every downstream parser and checker;
- removed hidden-content records retained only for the injection report;
- sections, paragraphs, tables, figure captions, equations, numeric tokens, and
  stable source spans where extraction supports them.

PDF conversion must preserve the original PDF identity. Conversion output is a
derived artifact, never a replacement identity. Dependency versions and
conversion metadata are included in the review freeze record.

Sanitization happens before section, table, number, claim, positioning, and
arithmetic extraction. No hidden payload may influence scientific findings or
scores. The injection scanner analyzes removed and visible text separately.

### 2. Deterministic audit

Retain existing event-specific checks and make their outputs stable:

- bind citation lookup snapshots to the review identity;
- use cache-only replay after a citation result has been frozen;
- represent unavailable lookups as explicit non-findings;
- link findings to overlapping claim spans and compatible check families,
  rather than every claim on the same line;
- distinguish full, partial, and absent evidence coverage;
- implement scope-vs-ledger coverage and one concrete follow-up per substantive
  weakness;
- preserve every central result, arithmetic, hypothesis, and finding in the
  machine-readable trace even when the Markdown view is summarized.

An empty References/Bibliography heading is not positioning. Citation presence
and related-work substance are separate signals.

### 3. Competition judgment and scoring

The internal score schema becomes the server schema directly:

- Soundness, Presentation, Significance, Originality: integers 1–4;
- Overall: integer 1–6;
- Confidence: integer 1–5.

The deterministic anchor is conservative:

- no verified headline evidence means no evidence-based accept uplift;
- absence of a detected error is not a strength;
- confidence measures review coverage and model/audit support, not merely the
  presence of reported results;
- significance and originality are independent dimensions.

`best` mode performs three concurrent bounded specialist requests per paper,
then one bounded area-chair meta-review. Each receives only sanitized evidence;
the full manuscript is retained when within the configured context budget and
longer inputs are section-prioritized with explicit omissions. The theorist,
experimentalist, and scope/ablation specialist return partial structured
assessments; the area chair returns the final strict scientific JSON. Code
validates:

- every factual statement cites a paper span, finding, or retrieved work;
- strengths require positive paper evidence;
- weaknesses require paper evidence or are converted to questions;
- score rationales match their dimensions;
- model output cannot erase deterministic integrity findings.

The final review contains a paper-specific summary, substantive strengths and
weaknesses, and three to five numbered questions. Each question states what
answer would change the assessment.

### 4. API adapter and submission runner

`AgentClient` follows `guidance.reason_code` and `next_action` rather than prose.
It supports:

- single-use credential exchange;
- authenticated status;
- stable assignment acquisition;
- scoped PDF download by returned URL/ordinal;
- exact eight-field review submission;
- bounded retry only for transient network/5xx failures;
- no blind polling;
- resume by skipping already submitted ordinals;
- no-post preview and an in-memory mock.

The API response parser accepts additive fields while validating required
fields. Contract fixtures cover the current `skill.md`; future contract changes
should require edits only in the adapter and fixtures.

The live runner reviews assignments concurrently with one worker per paper,
capped at ten. It separates download/review preparation from write-window
submission so reviews can be ready before 16:35 KST. It checks guidance again
before each POST and stops immediately on `all_reviews_submitted` or a terminal
reason.

### 5. Fresh-random PDF smoke harness

Add a network-enabled command that:

1. queries public arXiv categories spanning `cs.LG`, `stat.ML`, `cs.AI`,
   `cs.CL`, and `cs.CV`;
2. randomly selects the requested number of recent papers;
3. downloads PDFs to a gitignored run directory;
4. records a manifest before reviewing;
5. runs PDF conversion and audit/best review;
6. validates section extraction, score ranges, trace integrity, question count,
   absence of hidden-text score influence, and per-paper runtime;
7. writes a JSON report and a concise aggregate summary;
8. supports replay from any prior manifest.

Random selection is fresh by default. The generated seed is recorded, so the
selection can be explained even though arXiv's result set may later change.

## Failure Handling

- PDF conversion failure: mark only that assignment failed and preserve raw PDF.
- Empty or suspicious extraction: block review submission for that paper.
- Citation outage: retain an unavailable trace and continue without a defect.
- Model timeout/invalid JSON: submit deterministic audit only when it passes the
  minimum-content gate; otherwise report the paper as blocked.
- API 4xx: follow the returned reason code; never retry a permanent validation
  error unchanged.
- API 5xx/network error: bounded exponential retry, then preserve the prepared
  local review for manual diagnosis.

## Verification

Default verification:

- unit and regression suite;
- adversarial sanitizer tests, including hidden numeric/table payloads;
- citation snapshot determinism test;
- span-aware finding attribution tests;
- empty-References and unsupported-score calibration tests;
- direct server-schema score tests;
- current `skill.md` mock flow and resume/error guidance tests.

Explicit network verification:

- fresh-random arXiv PDF smoke run;
- replay of its generated manifest;
- batch timing test;
- `submit.py --dry-run`;
- `submit.py --no-post` only after a human supplies a valid setup token.

## Acceptance Criteria

- Identical canonical input, reviewer version, evidence bundle, and frozen
  external snapshots produce identical deterministic verdicts and scores.
- Hidden content cannot change non-ethics findings or scientific scores.
- No unsupported paper receives accept-leaning uplift from an empty references
  section or absence of detected errors.
- Every submitted payload exactly matches the current server contract.
- All default tests pass without network access.
- A fresh-random PDF smoke run completes without pipeline crashes and records a
  replayable manifest.
- Ten prepared reviews can be validated concurrently within the competition
  time budget; submission follows server guidance and safely resumes.

## Non-goals

- Replacing the evolving organizer contract with guessed endpoints.
- Claiming human-review agreement without judge labels.
- Enforcing official ICML restrictions on LLM-assisted reviewing.
- Treating the random PDF smoke corpus as a scientific quality benchmark.
