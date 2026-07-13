# MAC n CHEESE — Review Agent Spec

An evidence-bound, ICML-style reviewer for scientific papers.

## 1. Mission

Given a paper (PDF or Markdown) and, optionally, an evidence bundle of result
files, produce an ICML-style structured review where **every claim in the review
is mechanically traceable** to the paper text, its tables, or the supplied
results. When an evidence bundle is present (an `experiments.jsonl` ledger,
result files, a self-review checklist), the reviewer audits the paper's numbers
against it; when absent, the checks that need no ledger still run.

Design doctrine (from prior art):
- **statcheck/GRIM**: never ask the model "does this look right?" — recompute and diff.
- **Black Spatula**: false positives destroy reviewer credibility. Flag only what
  can be proven; demote unproven suspicions to "Questions for the Authors".
- **PaperQA2/scite/Elicit**: decompose the paper into claims; verdict per claim with
  label `supported | contradicted | unverifiable`; force structured extraction.

## 2. Output

A structured review with sections: Summary / Strengths / Weaknesses / Questions /
Scores / Ethics & Limitations / Evidence Trace. Scores use ICML-style ranges —
Soundness, Presentation, Significance, Originality (1–4), Overall (1–6),
Confidence (1–5) — each with one evidence-backed rationale.

## 3. Pipeline (`reviewer/` Python package, venv, no GPU)

```
run_review.py <paper.md|pdf> [evidence_dir] --out review.md
  S1 parse      : paper → sections, tables, all numeric tokens w/ location
  S2 claims     : structured claim list (JSON): {id, text, type, numbers, refs, location}
  S3 mech-check : deterministic battery (see §4) → findings JSON
  S4 verdicts   : per claim: supported | contradicted | unverifiable (+ evidence pointer)
  S5 compose    : two-pass grounder:
                  (a) DRAFT — a cheap model writes candidate review text
                  (b) GROUND — a strong pass maps every sentence to a finding/claim id;
                      ungroundable praise deleted, ungroundable criticism → Questions
                  every score cites S3/S4 output; per-comment confidence level
  S6 freeze     : record original/derived paper identities, evidence hashes,
                  external citation snapshot digest, agent version, timestamp;
                  identical rerun on same hash must yield same verdict labels
```

By default the reviewer runs the full pipeline: the deterministic S1–S6 audit plus
the scientific committee (§4c). The committee runs only after S6 freeze, so it can
never perturb the reproducible audit identity; if it is unavailable or invalid,
that paper falls back to its complete deterministic audit. Pass `run_review.py
--deterministic` for the pure S1–S6 audit — fully reproducible, offline, and free.
The committee needs an OpenAI-compatible key.

## 4. Mechanical check battery (S3) — the moat

| Check | Method |
|---|---|
| ledger-trace | every numeric result claim must exist in `experiments.jsonl` / evidence files (exact or rounding-tolerant match) |
| internal-consistency | table values vs prose mentions of same quantity → diff |
| arithmetic | recompute deltas, % improvements, averages from constituent numbers |
| baseline-fairness | claimed improvement must name baseline + same metric + confirmation rerun present |
| citation-existence | arXiv API / Semantic Scholar API: cited papers exist, titles match |
| template-compliance | required sections present, self-review boxes consistent w/ content |
| negative-evidence | ledger entries with `discard`/`crash` status absent from paper → flag omission |
| injection-scan | sanitize extracted text (invisible unicode, font-mapping, white-on-white); detect instruction-like content addressed to reviewers ("ignore previous", "give high score"); paper content is DATA, never instructions; report attempts in Ethics section |

Each finding: `{check, severity, location, expected, observed, evidence_path}`.

Checks that assume an evidence ledger (ledger-trace, baseline-fairness,
negative-evidence) apply only when the paper ships that evidence contract;
against a bare manuscript they self-suppress rather than manufacture false
positives.

## 4b. Scientific scaffolding — deterministic (S5, always on)

The audit battery grounds the review; these deterministic slots make it read as a
REVIEW with no model call. Each is computed from ledger coverage or the parsed
paper, so it is reproducible and cannot hallucinate:

1. **Scope check** [deterministic]: claim breadth vs evidence breadth. Read the
   ledger's actual coverage (# trials, seeds, GPU type, benchmark count). Any
   generalized claim beyond that coverage gets a scope-limitation weakness that
   QUOTES the coverage numbers.
2. **Design critique** [deterministic]: single run vs. reported variance (one
   ledger row per trial with no repeats → "no variance"), missing confirmation
   rerun, baseline representativeness — all readable from the ledger.
3. **Follow-up** [deterministic]: every substantive Weakness gets ONE concrete
   templated follow-up (e.g., "repeat with ≥3 seeds to establish variance").
4. **Positioning** [deterministic-lite]: does the paper cite ANY related work?
   Zero citations in a hypothesis paper → Presentation weakness.

The FP rule always applies: uncertain critiques become Questions. The richer,
judgment-heavy critiques (a NAMED causal confound, real positioning against the
specific literature, novelty/significance) require reasoning and live in §4c, off
by default.

## 4c. Scientific committee (default; skip with `--deterministic`)

The deterministic audit is always computed and is the primary fallback. On top of
it, the committee assesses what mechanical checks cannot: problem–method fit, claim–experiment
alignment, experimental validity, scope/generalization, design-choice and
ablation justification, novelty, and significance.

Mechanism:
- **Three real specialist calls:** a theorist assesses assumptions and logical
  method fit; an experimentalist assesses claims, controls, baselines, confounds,
  and statistics; a scope/ablation reviewer assesses generalization, design
  choices, limitations, and missing ablations. Calls run concurrently over
  role-targeted sanitized evidence.
- **Area-chair meta-review:** when at least two specialists succeed, a fourth
  call reconciles their structured outputs against deterministic S3/S4 facts and
  stable paper-span IDs. It emits every required scientific axis, grounded
  strengths/weaknesses, three to five questions, and all six scores.
- **Validation and merge:** unknown grounding IDs, missing axes, malformed
  scores, or score–text contradictions reject the committee result. Validated
  content is merged into the review sections, not an appendix.
- **Calibration:** validated scientific scores may move above or below the
  deterministic anchor. Proven integrity breaches still cap Soundness and Overall
  at 2.

Hard rules for the committee (violating any = per-paper fallback):
- Every model receives SANITIZED paper spans only. Hidden instructions never
  reach a model.
- Temperature 0 + fixed seed; record each role's model, prompt hash, response
  hash, outcome, and aggregate `judgment_identity`.
- The S4 verdict-label digest remains unaffected; committee content is merged only
  after the deterministic audit is frozen.
- Each call is bounded. One specialist may fail; fewer than two successful
  specialists or any invalid meta-review triggers fallback.

## 5. Scoring calibration

- Known LLM-reviewer bias: too positive. Anchor rubric: no supported headline
  result caps Overall at 3; one clean supported result permits 4; multiple
  supported results plus adequate presentation permit 5; the deterministic audit
  never emits 6; integrity breaches cap Overall at 2. Confidence uses verified
  result coverage, extraction quality, and positioning coverage.
- Rationale for each score MUST quote a finding id or claim id.

## 6. Eval harness (`eval/eval.py`)

- **Dev set**: `eval/papers/` = synthetic papers with fake ledgers — some clean,
  some corrupted. Each corruption injects ONE claim-invalidating error;
  `answer_key.json` = {claim, error location, description}. Seeded with §4-style
  errors (fabricated number, wrong %, missing baseline, fake citation, omitted
  negative result, table/text mismatch) plus injection-attack papers.
- **Metrics**: identification rate AND localization rate (must point to the
  passage), false-positive count, section completeness, injection resistance
  (score unchanged on injected twin), determinism (same input → same verdicts).
- **Score** = detection_rate − 0.5·FP_rate + 0.1·completeness. Printed as a single
  number on stdout; diagnostics go to stderr.
- **External robustness sub-metric**: when `eval/external/` holds real papers,
  eval.py runs the full pipeline on each (no answer key) and reports
  external_no_crash_rate + external_completeness + external_finding_total — a
  generalization/crash signal, never a detection score.
- **Regression guard**: keep a reviewer-code change only if the primary detection
  metric does not regress on existing cases. Adding a harder true case
  re-baselines and is never reverted for the induced drop.

## 7. Constraints (Integrity Gate — hard)

- Never fabricate runs, citations, or reviewer evidence. Never edit the paper.
- Review statements trace to the reviewed artifact; unverifiable ≠ wrong — label it.
- No credentials/private data in artifacts.
- If evidence is insufficient, say so; do not silently switch paths.

## 8. Runtime notes

- External APIs: arXiv / Semantic Scholar only (public, keyless). Timeout + cache.
- Everything runs in `.venv`; add dependencies to `requirements.txt` as introduced.
- `best` mode needs an OpenAI-compatible API key (`OPENAI_API_KEY`); `audit` mode
  is fully offline.
