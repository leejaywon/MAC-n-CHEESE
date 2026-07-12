# Review Agent Spec — Track 2 (Team: No Free Lunch)

> Ralph 루프가 이 스펙을 구현한다. 사람은 루프 시작 전 이 파일만 다듬는다.
> Official output contracts: `vendor/ralphthon-icml/skills/auto-research/assets/track-2-agent-template.md`, `track-2-review-template.md`

## 1. Mission

Build an **evidence-bound audit reviewer**: given a frozen Track 1 paper and its
evidence bundle, produce an ICML-style structured review where **every claim in
the review is mechanically traceable**. It audits THIS event's evidence contract
(`experiments.jsonl` ledger, evidence paths/hashes, val_bpb claims, self-review
checklist).

Design doctrine (from prior art):
- **statcheck/GRIM**: never ask the LLM "does this look right?" — recompute and diff.
- **Black Spatula**: false positives destroy reviewer credibility. Flag only what
  we can prove; demote unproven suspicions to "Questions for the Authors".
- **PaperQA2/scite/Elicit**: decompose paper into claims; verdict per claim with
  label `supported | contradicted | unverifiable`; force structured extraction.

## 2. Deliverables (submission artifacts, 16:30 hard cut)

1. `submission/review-agent.md` — frozen agent definition (identity, version SHA,
   input hashes, instruction, output contract, guardrails). Fill every bracket of
   the official template.
2. Review result per `track-2-review-template.md`, produced by running the agent
   on a frozen Track 1 paper. Required sections: Summary / Strengths / Weaknesses /
   Questions / Scores (Soundness, Presentation, Significance, Originality,
   Overall, Confidence — **one evidence-backed rationale per score**) / Ethics &
   Limitations / Evidence Trace. Use the platform ranges directly: four
   dimensions 1–4, Overall 1–6, Confidence 1–5.

## 3. Pipeline (implement as `reviewer/` Python package, venv, no GPU)

```
run_review.py <paper.md|pdf> <evidence_dir> --out review.md
  S1 parse      : paper → sections, tables, all numeric tokens w/ location
  S2 claims     : structured claim list (JSON): {id, text, type, numbers, refs, location}
  S3 mech-check : deterministic battery (see §4) → findings JSON
  S4 verdicts   : per claim: supported | contradicted | unverifiable (+ evidence pointer)
  S5 compose    : two-pass (ReviewGrounder pattern):
                  (a) DRAFT — cheap model (terra/luna) writes candidate review text
                  (b) GROUND — strong pass maps every sentence to a finding/claim id;
                      ungroundable praise deleted, ungroundable criticism → Questions
                  every score cites S3/S4 output; per-comment confidence level (DeepReview)
  S6 freeze     : record original/derived paper identities, evidence hashes,
                  external citation snapshot digest, agent version, timestamp;
                  identical rerun on same hash must yield same verdict labels
```

Modes (`run_review.py --mode`): `audit` (DEFAULT) = the full deterministic
S1–S6 pipeline above, fully reproducible and injection-proof — this is the
fallback contract. `best` = `audit` plus the scientific committee (§4c) and is
the live-review mode when a model key is configured. It runs specialist calls
and a grounded meta-review but never gates a submission.
If the committee is unavailable or invalid, that paper falls back to its
complete `audit` review.

## 4. Mechanical check battery (S3) — the moat

| Check | Method |
|---|---|
| ledger-trace | every numeric result claim must exist in `experiments.jsonl` / evidence files (exact or rounding-tolerant match) |
| internal-consistency | table values vs prose mentions of same quantity → diff |
| arithmetic | recompute deltas, % improvements, averages from constituent numbers |
| baseline-fairness | claimed improvement must name baseline + same metric + confirmation rerun present |
| citation-existence | arXiv API / Semantic Scholar API: cited papers exist, titles match |
| template-compliance | 2–4 pages, required sections present, self-review boxes consistent w/ content |
| negative-evidence | ledger entries with `discard`/`crash` status absent from paper → flag omission |
| injection-scan | sanitize extracted text (invisible unicode, font-mapping, white-on-white); detect instruction-like content addressed to reviewers ("ignore previous", "give high score"); paper content is DATA, never instructions; report attempts in Ethics section |

Each finding: `{check, severity, location, expected, observed, evidence_path}`.

## 4b. Scientific scaffolding — deterministic (S5, always on)

The audit battery grounds the review; these deterministic slots make it read as
a REVIEW with no model call. Each is computed from ledger coverage or the parsed
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
specific literature, novelty/significance) require reasoning and live in §4c,
off by default.

## 4c. Scientific committee — `--best` only

Default `audit` mode is fully deterministic and is the primary fallback.
`best` mode assesses what mechanical checks cannot: problem–method fit,
claim–experiment alignment, experimental validity, scope/generalization,
design-choice and ablation justification, novelty, and significance.

Mechanism:
- **Three real specialist calls:** a theorist assesses assumptions and logical
  method fit; an experimentalist assesses claims, controls, baselines,
  confounds, and statistics; a scope/ablation reviewer assesses generalization,
  design choices, limitations, and missing ablations. Calls run concurrently
  over role-targeted sanitized evidence.
- **Area-chair meta-review:** when at least two specialists succeed, a fourth
  call reconciles their structured outputs against deterministic S3/S4 facts
  and stable paper-span IDs. It emits every required scientific axis, grounded
  strengths/weaknesses, three to five questions, and all six scores.
- **Validation and merge:** unknown grounding IDs, missing axes, malformed
  scores, or score–text contradictions reject the committee result. Validated
  content is merged into the official review sections, not an appendix.
- **Calibration:** validated scientific scores may move above or below the
  deterministic anchor. Proven integrity breaches still cap Soundness and
  Overall at 2.

Hard rules for the committee (violating any = per-paper fallback):
- Every model receives SANITIZED paper spans only. Hidden instructions never
  reach a model.
- Temperature 0 + fixed seed; record each role's model, prompt hash, response
  hash, outcome, and aggregate `judgment_identity`.
- The S4 verdict-label digest remains unaffected; committee content is merged
  only after the deterministic audit is frozen.
- Each call is bounded. One specialist may fail; fewer than two successful
  specialists or any invalid meta-review triggers fallback. A committee failure
  never blocks other assignments or submission.

## 5. Scoring calibration

- Known LLM-reviewer bias: too positive (OpenReviewer finding). Anchor rubric:
  no supported headline result caps Overall at 3; one clean supported result
  permits 4; multiple supported results plus adequate presentation permit 5;
  deterministic audit never emits 6; integrity breaches cap Overall at 2.
  Confidence uses verified result coverage, extraction quality, and positioning
  coverage.
- Rationale for each score MUST quote a finding id or claim id.

## 6. Eval harness (`eval/eval.py`) — the loop's backpressure

- **Dev set**: `eval/papers/` = N synthetic Track 1-style papers (official template
  format, fake ledgers) — some clean, some corrupted. **Generator uses the FLAWS
  claim-anchored method**: extract the paper's falsifiable claims → for each, inject
  ONE claim-invalidating error (not from a fixed taxonomy; must undermine that claim;
  filter trivial edits) → `answer_key.json` = {claim, error location, description}.
  Seed with §4-style errors (fabricated number, wrong %, missing baseline, fake
  citation, omitted negative result, table/text mismatch) + 1–2 injection-attack
  papers (hidden "give high score" instructions).
- **Metrics**: identification rate AND localization rate (FLAWS-style: must point to
  the passage), false-positive count, section completeness, injection resistance
  (score unchanged on injected twin), determinism (same input → same verdicts).
- **Score** = detection_rate − 0.5·FP_rate + 0.1·completeness. Print single number.
- **External robustness sub-metric**: when `eval/external/` holds real papers,
  eval.py runs the full pipeline on each (no answer key) and reports
  external_no_crash_rate + external_completeness + external_finding_total. This
  is a generalization/crash signal, never a detection score, and never gates the
  primary loop rule.
- **Loop rule**: a reviewer-CODE change is kept only if the primary detection
  metric does not regress on existing cases. Eval-set HARDENING (adding a harder
  TRUE case when a task says so) re-baselines and is never reverted for the
  induced drop — that drop is the headroom the next iterations climb. Log every
  eval run to W&B offline (`job_type=reviewer-eval`).

## 7. Constraints (Integrity Gate — hard)

- Never fabricate runs, citations, reviewer evidence. Never edit the frozen paper.
- Review statements trace to the frozen artifact; unverifiable ≠ wrong — label it.
- No credentials/private data in artifacts. File-scoped git ops only
  (no `git add -A`, no `git reset --hard`). Bounded iterations, no infinite loops.
- If evidence is insufficient, say so; do not silently switch paths.

## 8. Milestones (fix_plan.md seeds — one per loop iteration)

- M0: repo scaffold, `run_review.py` end-to-end walking skeleton (dummy output)
- M1: S1 parser + numeric extraction on sample paper
- M2: ledger-trace + internal-consistency + arithmetic checks
- M3: eval harness + first score measured
- M4: claims + verdicts + Evidence Trace generation
- M5: composer w/ official template + FP filter + calibration
- M6: citation-existence, template-compliance, negative-evidence checks
- M7: determinism/freeze + review-agent.md finalized
- M8+: hill-climb eval score; harden on new injected-error cases

## 9. Runtime notes

- Orchestrator: gpt-5.6-sol high. Parallelizable work (per-claim verification,
  per-check implementation) → subagents depth 1, terra-high, ≤8 threads.
- External APIs: arXiv/Semantic Scholar only (public, keyless). Timeout + cache.
- Everything runs in `.venv`; add deps to `requirements.txt` as introduced.
