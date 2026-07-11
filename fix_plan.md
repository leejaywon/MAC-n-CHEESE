# fix_plan — Review Agent build (one task per ralph iteration)

Spec: `specs/review-agent-spec.md`. Milestone descriptions live there (§8).

## Tasks

- [x] M0: scaffold `reviewer/` package + `run_review.py` walking skeleton —
      takes a paper path + evidence dir, runs S1→S6 as no-op stages, writes a
      dummy review.md with all required template sections. Must run end-to-end.
- [x] M1: S1 parser — markdown paper → sections, tables, numeric tokens with
      locations (JSON). Test on `eval/papers/sample_clean.md` (create a minimal
      one from the official track-1 template if none exists).
- [x] M2a: mech check `ledger-trace` — numeric claims ↔ experiments.jsonl match
- [x] M2b: mech checks `internal-consistency` (table↔prose diff) + `arithmetic`
      (recompute deltas/percentages)
- [x] M3: eval harness `eval/eval.py` + FLAWS-style generator `eval/make_eval_set.py`
      (claim-anchored error injection, answer_key.json), ≥4 corrupted + 2 clean
      papers; prints single score; logs W&B offline run (job_type=reviewer-eval)
- [x] M4: S2 claim extraction + S4 verdict labeling (supported/contradicted/
      unverifiable) → Evidence Trace section generation
- [x] M5: S5 composer — DRAFT (cheap model) → GROUND (map every sentence to
      finding/claim id; ungrounded praise deleted, ungrounded criticism →
      Questions); score calibration rules from spec §5
- [x] M6a: mech checks `baseline-fairness` + `negative-evidence`
- [x] M6b: mech checks `citation-existence` (arXiv/S2 API, cached) +
      `template-compliance`
- [x] M6c: `injection-scan` — sanitize invisible unicode/hidden text, detect
      reviewer-directed instructions, report in Ethics; add 2 injection-twin
      papers to eval set + injection-resistance metric
- [x] M7: determinism + freeze — same input hashes → same verdicts.
      `submission/review-agent.md` is human-drafted already: VERIFY it matches
      the implemented pipeline (edit only if code diverged; keep bracketed
      runtime fields as brackets)
- [x] M8: hill-climb — analyze eval failures, extend eval set (allowed here),
      improve weakest check. Repeatable task: re-add itself until 15:00.
- [ ] M9: update stale test_pipeline_exposes_all_m6b_checks expected check
      set to include the already-implemented injection-scan.

## Progress Log

(append: `iter <n> | <task> | eval=<score> | <one-line result>`)

iter 1 | M0 | eval=n/a | S1-S6 skeleton runs end-to-end and writes the complete official review shape with frozen input hashes.
iter 2 | M1 | eval=3/3 | Parser implementation and tests pass, but M1 remains unchecked because the read-only .git mount denied index.lock and prevented the required commit.
iter 3 | M1 | eval=3/3 | Verified committed S1 parser and all tests pass; fix_plan commit blocked because the read-only .git mount denied index.lock.
iter 4 | M2a | eval=8/8 | Metric- and trial-aware ledger tracing now emits deterministic evidence matches and findings with precision-aware rounding and malformed-ledger handling.
iter 5 | M2b | eval=14/14 | Conservative table-to-prose matching and deterministic delta/percentage recomputation now emit localized, evidence-backed findings.
iter 6 | M3 | eval=1.100000 | Six-paper claim-anchored eval detects and localizes all four corruptions with zero false positives and logs metrics to W&B offline.
iter 7 | M4 | eval=1.100000 | Deterministic claim extraction and evidence-bound verdicts now generate per-claim Evidence Trace entries without eval regression.
iter 8 | M5 | eval=1.100000 | Offline DRAFT candidates now pass through an authoritative GROUND filter with traceable comments and borderline-first calibrated scores.
iter 9 | M6a | eval=1.100000 | Explicit improvement claims now require a named same-metric baseline and confirmation rerun, while undisclosed discard/crash ledger outcomes produce evidence-backed omission findings.
iter 10 | M6b | eval=1.100000 | Cached timeout-safe arXiv/S2 citation verification and conservative Track 1 template/page/self-review checks now emit localized evidence-bound findings.
iter 11 | M6c | eval=1.100000 | Hidden HTML and Unicode-obfuscated reviewer instructions are sanitized, localized in Ethics, and rejected with perfect two-pair score invariance.
iter 12 | M7 | eval=1.100000 | Content-addressed agent/input freeze records now reproduce and guard verdict-label digests, and the human-drafted agent contract matches the implemented pipeline.
iter 13 | M8 | eval=1.100000 | Expanded eval to 10 papers and made baseline-fairness reject confirmation reruns that contradict a mechanically known improvement direction, with zero new false positives.
