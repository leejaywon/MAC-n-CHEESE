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
- [x] M9: update stale test_pipeline_exposes_all_m6b_checks expected check
      set to include the already-implemented injection-scan.
- [ ] M10a: deterministic-reach hardening (the primary hill-climb). Add ONE
      harder eval case whose planted flaw is still mechanically reachable by an
      EXISTING check family — e.g. multi-step arithmetic (mean-of-runs then
      delta), cross-section table↔abstract mismatch, a real-looking but
      nonexistent citation id, or a partially-disclosed discard/crash in the
      ledger. The score drops (bar rose — re-baseline, do NOT revert per
      PROMPT §4). Then strengthen the weakest check until it catches the case.
      This is honest detection headroom the deterministic reviewer can close.
- [ ] M10b: deterministic scientific scaffolding (spec §4b — the [deterministic]
      items ONLY). S5 emits, per kept-candidate hypothesis: a claim-scope note vs
      the ledger's actual coverage (# trials, seeds, GPU type), a design critique
      (single-run / no-variance / missing confirmation rerun), one templated
      follow-up per substantive Weakness, and a positioning-lite check (zero
      citations in a hypothesis paper → Presentation weakness). All computed from
      the ledger/parsed paper — no model call. Lands in Weaknesses/Questions under
      the FP rule. Measured by section COMPLETENESS + external robustness, NOT by
      the detection metric. Do NOT add answer-key "detection" entries for these.
      (The NAMED confound + real positioning are judgment — they belong to M14.)
- [ ] M11: external generalization smoke test — for every paper in
      `eval/external/` (real published AI papers placed by a human; skip if the
      dir is empty), `eval.py` already runs the pipeline and reports a robustness
      sub-metric (external_no_crash_rate + external_completeness +
      external_finding_total). Verify no crash and record the 3 most substantive
      findings per external paper in the Progress Log. Raising external
      robustness (no crashes, full sections, non-trivial findings) is a real
      goal even without an answer key.
- [ ] M13: judgment-layer scaffold, NO model yet (spec §4c). The `--best` hook
      `_apply_judgment_layer` in `reviewer/pipeline.py` is already wired and
      no-op. Implement the GROUNDING machinery it needs: a function that takes
      candidate critique sentences + the S3 findings / S4 verdicts and keeps a
      sentence only when grounded (reuse `composer.ground_comments` semantics),
      populating `state.judgment["comments"]`. Drive it from DETERMINISTIC draft
      sentences (the §4b scaffolding) so `best` output is still reproducible and
      the machinery is proven before any model is added. Add a test: `best` runs,
      audit output byte-identical to `--mode audit`.
- [ ] M14 (GATED — only if API-key + Codex credit confirmed at check-in; else
      SKIP and log why): add the model DRAFT behind the M13 grounding. Feed ONLY
      the sanitized paper text; temperature 0 + fixed seed; record model id +
      prompt hash in the freeze block; calibration may only LOWER scores. On any
      model/quota error, leave `state.judgment` empty so audit output stands.
      One bounded call budget per review. Verify injection twins still score
      invariant (sanitize-first) and audit-mode determinism is untouched.
- [ ] M15 (optional, after M14): multi-persona drafts (harsh-theorist /
      empiricist / reproducibility-cop) merged by an AC meta-review, all still
      gated by M13 grounding. Personas add coverage, never authority.
- [ ] M12 (terminal filler, repeatable until 15:00): hill-climb round — read the
      eval diagnostic line, pick the weakest DETERMINISTIC area, add one harder
      mechanically-reachable case (M10a style) and close it. Only pick this when
      every M10–M15 above is checked or explicitly skipped. Re-add after
      completing. Never add a case a deterministic check cannot reach.

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
iter 14 | M9 | eval=1.100000 | Updated the pipeline regression contract to require injection-scan in both the mechanical check set and rendered S3 summary.

## Generality hardening (session 2, human — Track 2 reframed as a STANDALONE reviewer of arbitrary official-template peer papers, not a closed self-review loop)

Verified against the official Track 1 template (Research Spec / Agent Workflow /
Short Paper[Abstract/Intro/Method/Experiments/Limitations] / Self-Review). All
event eval stays 1.10; 57 tests green.

- Format-aware gating: `_detect_event_format` (signal = experiments.jsonl ledger,
  or Research-Spec + Self-Review markers). `template-compliance` and
  `baseline-fairness` no-op on foreign papers → eliminated 8 false positives +
  2 fabricated "contradictions" that the reviewer produced on a normal ML paper.
- General checks now fire without the event table format: bracket arXiv citation
  extraction (`[NNNN.NNNNN]`, month-validated) catches fabricated citations via
  live arXiv; prose-ratio arithmetic ("from A to B … Z%") with paragraph/cross-
  line matching catches ratio errors anywhere.
- Self-Review checklist audit (`reviewer/self_review_audit.py`): flags dishonest
  `[x]` self-certifications against actual S3 findings; handles BOTH the official
  trailing `label: [x]` and the eval leading `[x] label` formats. Rendered as
  Weaknesses but kept OUT of the detection/FP eval accounting (derived critique).
- Question spam removed (only result/arithmetic/hypothesis unverifiable claims
  generate an evidence-request question).
- Ordinal-suffix FP fix: the "1" in "candidate-1" is no longer traced as metric=1.

Remaining (forward):
- [ ] G1: dedup the opaque "conflicts with deterministic evidence [claim]"
      weakness when a specific finding already covers the same line.
- [ ] G2: add 2 generality eval cases (official-template General-path paper with
      a planted arithmetic/citation error + a dishonest Self-Review) so the
      backpressure rewards generality, not only event-format detection.
- [ ] G3: judgment layer (M13–M15) is now the main substance lever for
      evidence-poor peer papers; PDF input (M-PDF) only if peer papers are not
      Markdown (they use the Markdown official template, so likely unneeded).
