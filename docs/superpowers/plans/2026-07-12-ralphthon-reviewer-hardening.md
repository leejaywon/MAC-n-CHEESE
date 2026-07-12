# Ralphthon Reviewer Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden NFL-Auditor's input pipeline, deterministic audit, ICML-style scoring, live submission adapter, and fresh-random PDF validation for Ralphthon Track 2.

**Architecture:** A sanitized canonical paper representation feeds every scientific check, while raw hidden content is isolated for the injection report. Deterministic findings and frozen external citation snapshots anchor a separate competition judgment layer that emits the exact openagentreview.org score schema. The network API and random-PDF harness remain adapters around the review core.

**Tech Stack:** Python 3.14, stdlib `unittest`, `pymupdf4llm`, PyMuPDF, urllib, public arXiv Atom/PDF endpoints, optional OpenAI-compatible chat API.

**Commit policy:** This plan intentionally omits commit steps because the user did not authorize commits.

---

### Task 1: Lock the known failures with regression tests

**Files:**
- Modify: `tests/test_injection_scan.py`
- Modify: `tests/test_determinism.py`
- Modify: `tests/test_positioning.py`
- Modify: `tests/test_composer.py`
- Modify: `tests/test_claims.py`

- [ ] **Step 1: Add a hidden-numeric score-invariance test**

Create clean and attacked papers where the attack is:

```python
'<span style="display:none">Accuracy rose from 1 to 2, a relative gain of 900%.</span>'
```

Run both through `run_pipeline`; assert identical non-injection findings and
identical scores.

- [ ] **Step 2: Add a citation-snapshot determinism test**

Patch citation lookup once to return `unavailable` and once to return
`not-found`. Assert the external snapshot participates in `review_identity`, so
the two states cannot claim the same frozen identity.

- [ ] **Step 3: Add empty-References and unsupported-score tests**

Use a paper with a `## References` heading and no entries. Assert:

```python
signals["positioned"] is False
scores["Soundness"]["value"] <= 2
scores["Overall recommendation"]["value"] <= 3
```

- [ ] **Step 4: Add span/check-aware attribution tests**

Put a valid result claim and a bad citation in separate sentences on one line.
Assert the citation finding does not mark the valid result claim contradicted.

- [ ] **Step 5: Run the focused tests and confirm they fail**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_injection_scan tests.test_determinism tests.test_positioning \
  tests.test_composer tests.test_claims -q
```

Expected: failures for hidden-numeric invariance, citation identity, empty
References, conservative scores, and claim attribution.

---

### Task 2: Sanitize before every scientific analysis and preserve PDF identity

**Files:**
- Create: `reviewer/document.py`
- Modify: `reviewer/parser.py`
- Modify: `reviewer/to_markdown.py`
- Modify: `reviewer/pipeline.py`
- Modify: `reviewer/claims.py`
- Modify: `reviewer/injection_scan.py`
- Modify: `reviewer/positioning.py`
- Modify: `reviewer/rigor_checklist.py`
- Modify: `reviewer/citation_existence.py`
- Modify: `run_review.py`
- Modify: `review_batch.py`
- Test: `tests/test_document.py`
- Test: `tests/test_pdf_ingestion.py`

- [ ] **Step 1: Define the canonical document types**

Implement:

```python
@dataclass(frozen=True)
class SourceIdentity:
    path: str
    media_type: str
    sha256: str
    byte_length: int
    page_count: int | None

@dataclass(frozen=True)
class PreparedPaper:
    original: SourceIdentity
    markdown: SourceIdentity
    raw_text: str
    analysis_text: str
    sanitation_traces: tuple[dict[str, object], ...]
    converter: str | None
```

Add `prepare_paper(path, converted_path=None) -> PreparedPaper`.

- [ ] **Step 2: Make parsing accept canonical analysis text**

Change the parser entry point to:

```python
def parse_markdown(path: Path, *, text: str | None = None) -> dict[str, Any]:
```

Include `analysis_text` in the parsed structure. Add a shared
`paper_text(parsed_paper)` helper. Refactor every checker to consume that helper
instead of reopening `source_path`.

- [ ] **Step 3: Separate raw injection analysis from visible text**

Implement `scan_and_sanitize(raw_text) -> (analysis_text, traces, findings)`.
Run it before `parse_markdown`. The injection check receives its precomputed raw
records; no scientific checker receives raw hidden content.

- [ ] **Step 4: Preserve original PDF metadata**

Use PyMuPDF to count pages and hash the original bytes. Record both original PDF
and derived Markdown hashes in `ReviewState`, freeze identity, and rendered
Evidence Trace. Record the installed converter version.

- [ ] **Step 5: Keep backward-compatible entry points**

`run_pipeline(Path, ...)` still accepts Markdown paths. Add optional
`prepared_paper`/`original_paper_path` arguments so `run_review.py`,
`review_batch.py`, and `submit.py` preserve PDF identity without breaking tests.

- [ ] **Step 6: Run document, PDF, and injection tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_document tests.test_pdf_ingestion tests.test_parser \
  tests.test_injection_scan -q
```

Expected: all pass; hidden numeric/table content is absent from parsed numbers
and findings, while the injection report retains it.

---

### Task 3: Freeze external citation state and correct verdict attribution

**Files:**
- Modify: `reviewer/citation_existence.py`
- Modify: `reviewer/claims.py`
- Modify: `reviewer/pipeline.py`
- Test: `tests/test_citation_template.py`
- Test: `tests/test_determinism.py`
- Test: `tests/test_claims.py`

- [ ] **Step 1: Return canonical citation snapshots**

For each identifier, produce:

```python
{
    "provider": "arxiv",
    "identifier": "2401.01234",
    "status": "verified|not-found|unavailable",
    "title": "...",
    "url": "...",
    "error": None,
}
```

Cache every status, including `unavailable`, without timestamps in the canonical
payload. Expose a digest of the ordered snapshots.

- [ ] **Step 2: Bind snapshots into review identity**

Add `external_snapshot_digest` to `ReviewState` and the `review_identity`
payload. Render the digest in Evidence Trace. A changed lookup state must create
a different identity instead of appearing as nondeterministic labels.

- [ ] **Step 3: Add compatibility-aware finding linkage**

Implement:

```python
def finding_applies_to_claim(finding: dict, claim: dict) -> bool:
```

Require line/span overlap and compatible pairs:

- arithmetic, ledger, internal consistency, baseline fairness → result/arithmetic;
- citation existence → a claim containing the cited identifier;
- injection/template/negative evidence → never directly contradict a claim.

- [ ] **Step 4: Run citation, determinism, and claim tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_citation_template tests.test_determinism tests.test_claims -q
```

Expected: all pass and the original citation/cache tests remain green.

---

### Task 4: Complete deterministic scientific scaffolding

**Files:**
- Modify: `reviewer/scientific_scaffolding.py`
- Modify: `reviewer/pipeline.py`
- Modify: `reviewer/positioning.py`
- Test: `tests/test_generality.py`
- Test: `tests/test_positioning.py`
- Create: `tests/test_scientific_scaffolding.py`

- [ ] **Step 1: Require substantive positioning**

Set `positioned=True` only when at least one actual citation marker exists or a
related-work section contains substantive non-heading prose. An empty
References/Bibliography heading is false.

- [ ] **Step 2: Compute ledger scope**

Extract trial count, distinct seeds, GPU types, benchmark/metric count, and
confirmation runs. Emit a scope weakness only when a generalized claim exceeds
the observed coverage; quote the coverage values.

- [ ] **Step 3: Generate one follow-up per weakness**

Map weakness families to concrete actions:

```python
{
    "variance": "Repeat the comparison with at least three independent seeds.",
    "baseline-fairness": "Run the named baseline under the same metric and budget.",
    "negative-evidence": "Report the omitted failed/discarded trial and its effect.",
    "citation-existence": "Correct or replace the unresolved citation identifier.",
}
```

Deduplicate follow-ups and retain their finding references.

- [ ] **Step 4: Run scaffolding and positioning tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_scientific_scaffolding tests.test_generality tests.test_positioning -q
```

Expected: all pass.

---

### Task 5: Replace score calibration with the exact competition schema

**Files:**
- Modify: `reviewer/composer.py`
- Modify: `reviewer/pipeline.py`
- Modify: `reviewer/api_scores.py`
- Modify: `reviewer/model_critique.py`
- Modify: `eval/eval.py`
- Modify: `tests/test_composer.py`
- Modify: `tests/test_modes.py`
- Modify: `tests/test_model_critique.py`
- Modify: `tests/test_api_scores.py`

- [ ] **Step 1: Define direct score dimensions**

Use:

```python
SCORE_SCALES = {
    "Soundness": (1, 4),
    "Presentation": (1, 4),
    "Significance": (1, 4),
    "Originality": (1, 4),
    "Overall recommendation": (1, 6),
    "Confidence": (1, 5),
}
```

Delete Contribution-to-two-dimensions projection and the Overall `+1` mapping.

- [ ] **Step 2: Implement conservative deterministic anchors**

Rules:

- contradiction/integrity breach caps Overall at 2;
- no supported headline result caps deterministic Overall at 3;
- one clean supported headline result permits Overall 4;
- multiple supported results plus adequate presentation can reach 5;
- deterministic audit never emits 6;
- empty references and absence of findings provide no uplift;
- Confidence uses verified coverage ratio, extraction quality, and positioning
  coverage, never raw result presence alone.

- [ ] **Step 3: Give Significance and Originality separate rationales**

Significance uses breadth, task relevance, and supported empirical/theoretical
scope. Originality uses novelty claims and positioning. Every rationale cites a
compatible claim/finding/paper span.

- [ ] **Step 4: Validate model calibration safely**

Allow `best` to propose all six dimensions within range. Enforce deterministic
caps for proven integrity defects and reject score changes with no grounding.
Keep score-text consistency after calibration.

- [ ] **Step 5: Make API mapping an identity transform**

`to_api_review` reads all six internal dimensions directly and validates the
exact eight-field payload.

- [ ] **Step 6: Run scoring and mode tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_composer tests.test_modes tests.test_model_critique \
  tests.test_api_scores -q
```

Expected: all pass; no unsupported paper receives Overall above 3.

---

### Task 6: Produce a substantive full-paper best-mode review

**Files:**
- Modify: `reviewer/model_critique.py`
- Modify: `reviewer/pipeline.py`
- Modify: `reviewer/novelty_positioning.py`
- Create: `reviewer/review_schema.py`
- Modify: `tests/test_model_critique.py`
- Modify: `tests/test_modes.py`
- Modify: `tests/test_novelty_positioning.py`

- [ ] **Step 1: Define strict judgment output**

Validate:

```python
@dataclass(frozen=True)
class JudgmentDraft:
    summary: str
    strengths: tuple[GroundedComment, ...]
    weaknesses: tuple[GroundedComment, ...]
    questions: tuple[GroundedQuestion, ...]
    scores: dict[str, ScoreAdjustment]
```

Questions must be numbered 1–5 and include `assessment_if_resolved`.

- [ ] **Step 2: Remove the 8,000-character prefix truncation**

Build a section-prioritized prompt up to `RALPH_BEST_MAX_CHARS` (default 60,000).
For overflow, retain Abstract, Method, Experiments, Limitations, and References
in that order and record omitted section names.

- [ ] **Step 3: Ground factual text**

Allow paper-span references (`paper:Lx-Ly`), finding IDs, supported/contradicted
claim IDs, and retrieved arXiv IDs. Drop unsupported strengths; convert
unsupported weaknesses to questions; reject ungrounded score adjustments.

- [ ] **Step 4: Apply a competition-specific literature cutoff**

Record retrieval dates and suppress novelty accusations. Retrieval only creates
questions, and related work published after the paper's declared/frozen date is
labelled concurrent/post-date rather than missing prior art.

- [ ] **Step 5: Merge judgment into the official review**

Prefer model summary/strengths/weaknesses/questions when valid, preserve all
deterministic findings, and render three to five numbered questions with impact
on assessment.

- [ ] **Step 6: Run best-mode tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_model_critique tests.test_modes tests.test_novelty_positioning -q
```

Expected: all pass; tests confirm full-tail content reaches the model prompt.

---

### Task 7: Align the API client with the live skill guidance contract

**Files:**
- Modify: `reviewer/agent_api.py`
- Modify: `submit.py`
- Modify: `tests/test_submit_dryrun.py`
- Create: `tests/test_agent_guidance.py`
- Modify: `README.md`

- [ ] **Step 1: Parse guidance as stable control data**

Implement typed helpers for `stage`, `reason_code`, `next_action`,
`action_available`, prerequisites, and KST boundaries. Unknown additive fields
are retained but do not break parsing.

- [ ] **Step 2: Use the returned scoped PDF URL**

Change download to `fetch_pdf(assignment)`. Validate that `paper.pdf_url` is an
HTTPS URL on `openagentreview.org` under the agent API prefix before attaching
the bearer.

- [ ] **Step 3: Split prepare and submit phases**

Download and review assignments whenever guidance permits preparation. Before
each POST, refresh status and require `review_window_open`/`submit_review`.
Terminal `next_action:none` stops without polling.

- [ ] **Step 4: Implement exact error actions**

Cover invalid setup token, active report required, insufficient papers, window
not open/closed, assignment refresh, invalid payload, submitted, complete, and
unexpected API errors. Retry only network/5xx failures.

- [ ] **Step 5: Expand the in-memory mock**

Mock guidance and state transitions: credential setup → assignments → review
window → partial submissions → complete. Add resume and terminal-no-op tests.

- [ ] **Step 6: Run API tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_api_scores tests.test_agent_guidance tests.test_submit_dryrun -q
python submit.py --dry-run
```

Expected: tests pass and dry run reports every mock assignment submitted.

---

### Task 8: Add fresh-random arXiv PDF smoke and replay

**Files:**
- Create: `eval/random_pdf_smoke.py`
- Create: `tests/test_random_pdf_smoke.py`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Implement arXiv discovery and random selection**

Query recent entries across `cs.LG`, `stat.ML`, `cs.AI`, `cs.CL`, and `cs.CV`.
Generate a seed with `secrets.randbits(64)` unless `--seed` is supplied.

- [ ] **Step 2: Persist the manifest before review**

Manifest fields:

```json
{
  "schema_version": 1,
  "seed": 123,
  "created_at": "KST ISO timestamp",
  "mode": "audit",
  "papers": [
    {"arxiv_id": "2401.01234", "title": "...", "pdf_url": "...", "sha256": "..."}
  ]
}
```

Support `--replay manifest.json` without querying arXiv.

- [ ] **Step 3: Validate each PDF review**

Check original hash/page count, non-empty extraction, score ranges, required
sections, three-to-five questions when best judgment succeeds, trace digest,
runtime, and exception isolation.

- [ ] **Step 4: Add hermetic fake-network tests**

Inject Atom feed/PDF fetchers. Assert category diversity, manifest writing,
hash verification, replay behavior, and one-paper failure isolation.

- [ ] **Step 5: Run smoke-harness tests**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_random_pdf_smoke -q
```

Expected: all pass without external network.

---

### Task 9: Finalize artifacts, documentation, and full verification

**Files:**
- Modify: `submission/review-agent.md`
- Modify: `submission/track-2-review-template.md`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `fix_plan.md`

- [ ] **Step 1: Remove bracket placeholders**

Describe the runtime content-addressed version and per-review frozen identity
without unresolved brackets. Update the contract to the six server dimensions
and original-PDF/derived-Markdown hashes.

- [ ] **Step 2: Update operator documentation**

Document audit/best behavior, privacy and secret handling, random-PDF smoke,
manifest replay, dry run, no-post preparation, live write-window submission,
failure recovery, and exact environment variables.

- [ ] **Step 3: Run the full hermetic suite**

Run:

```bash
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -q
```

Expected: zero failures.

- [ ] **Step 4: Run the deterministic evaluation**

Run:

```bash
source .venv/bin/activate
WANDB_MODE=offline python eval/eval.py
```

Expected: no detection regression, zero current false positives, and complete
review sections. Record the new baseline if the direct score schema changes
score equality details without changing flaw detection.

- [ ] **Step 5: Run a fresh network PDF smoke**

Run:

```bash
source .venv/bin/activate
python eval/random_pdf_smoke.py --count 5 --mode audit
```

Expected: five random public PDFs downloaded, reviewed or individually reported
as failed, with manifest and report paths printed.

- [ ] **Step 6: Replay the exact smoke manifest**

Run:

```bash
source .venv/bin/activate
python eval/random_pdf_smoke.py --replay <manifest-path> --mode audit
```

Expected: downloaded hashes match and deterministic review digests/scores match
the first run.

- [ ] **Step 7: Run submission dry-run and inspect status**

Run:

```bash
source .venv/bin/activate
python submit.py --dry-run
git status --short
```

Expected: dry run succeeds, no credentials are printed, and only intended
source/docs plus gitignored smoke/run artifacts exist.
