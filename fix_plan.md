# fix_plan — Review Agent build (one task per ralph iteration)

Spec: `specs/review-agent-spec.md`. Milestone descriptions live there (§8).

## Tasks

- [ ] M0: scaffold `reviewer/` package + `run_review.py` walking skeleton —
      takes a paper path + evidence dir, runs S1→S6 as no-op stages, writes a
      dummy review.md with all required template sections. Must run end-to-end.
- [ ] M1: S1 parser — markdown paper → sections, tables, numeric tokens with
      locations (JSON). Test on `eval/papers/sample_clean.md` (create a minimal
      one from the official track-1 template if none exists).
- [ ] M2a: mech check `ledger-trace` — numeric claims ↔ experiments.jsonl match
- [ ] M2b: mech checks `internal-consistency` (table↔prose diff) + `arithmetic`
      (recompute deltas/percentages)
- [ ] M3: eval harness `eval/eval.py` + FLAWS-style generator `eval/make_eval_set.py`
      (claim-anchored error injection, answer_key.json), ≥4 corrupted + 2 clean
      papers; prints single score; logs W&B offline run (job_type=reviewer-eval)
- [ ] M4: S2 claim extraction + S4 verdict labeling (supported/contradicted/
      unverifiable) → Evidence Trace section generation
- [ ] M5: S5 composer — DRAFT (cheap model) → GROUND (map every sentence to
      finding/claim id; ungrounded praise deleted, ungrounded criticism →
      Questions); score calibration rules from spec §5
- [ ] M6a: mech checks `baseline-fairness` + `negative-evidence`
- [ ] M6b: mech checks `citation-existence` (arXiv/S2 API, cached) +
      `template-compliance`
- [ ] M6c: `injection-scan` — sanitize invisible unicode/hidden text, detect
      reviewer-directed instructions, report in Ethics; add 2 injection-twin
      papers to eval set + injection-resistance metric
- [ ] M7: determinism + freeze — same input hashes → same verdicts; finalize
      `submission/review-agent.md` (fill official template brackets)
- [ ] M8: hill-climb — analyze eval failures, extend eval set (allowed here),
      improve weakest check. Repeatable task: re-add itself until 15:00.

## Progress Log

(append: `iter <n> | <task> | eval=<score> | <one-line result>`)
