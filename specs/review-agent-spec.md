# Review Agent Spec — Track 2 (Team: No Free Lunch)

> Ralph 루프가 이 스펙을 구현한다. 사람은 루프 시작 전 이 파일만 다듬는다.
> Official output contracts: `vendor/ralphthon-icml/skills/auto-research/assets/track-2-agent-template.md`, `track-2-review-template.md`

## 1. Mission

Build an **evidence-bound audit reviewer**: given a frozen Track 1 paper and its
evidence bundle, produce an ICML-style structured review where **every claim in
the review is mechanically traceable**. Not a generic paper reviewer — an
auditor specialized for THIS event's evidence contract (`experiments.jsonl`
ledger, evidence paths/hashes, val_bpb claims, self-review checklist).

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
   Questions / Scores (Soundness, Presentation, Contribution, Overall, Confidence —
   **one evidence-backed rationale per score**) / Ethics & Limitations / Evidence Trace.

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
  S6 freeze     : record paper hash, evidence hashes, agent version, timestamp;
                  identical rerun on same hash must yield same verdict labels
```

Modes (DeepReview pattern): `--fast` = S1–S3 only (mech report), `--best` = full
pipeline. Event fallback: if time is short, `--fast` output is still a valid
evidence-bound review skeleton.

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

## 5. Scoring calibration

- Known LLM-reviewer bias: too positive (OpenReviewer finding). Anchor rubric:
  Overall starts at borderline; move up only on `supported` headline claims,
  down on `contradicted` findings. Confidence tied to fraction of claims verifiable.
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
- **Loop rule**: a change is kept only if eval score does not regress. Log every
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
