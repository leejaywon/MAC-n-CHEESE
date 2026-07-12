# fix_plan — Review Agent build (one task per ralph iteration)

Spec: `specs/review-agent-spec.md`. Milestone descriptions live there (§8).

## Tasks

- [x] M0: scaffold `reviewer/` package + `run_review.py` walking skeleton —
      takes a paper path + evidence dir, runs S1→S6 as no-op stages, writes a
      dummy review.md with all required template sections. Must run end-to-end.
- [ ] M1: S1 parser — markdown paper → sections, tables, numeric tokens with
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
- [x] M10a: deterministic-reach hardening (the primary hill-climb). Add ONE
      harder eval case whose planted flaw is still mechanically reachable by an
      EXISTING check family — e.g. multi-step arithmetic (mean-of-runs then
      delta), cross-section table↔abstract mismatch, a real-looking but
      nonexistent citation id, or a partially-disclosed discard/crash in the
      ledger. The score drops (bar rose — re-baseline, do NOT revert per
      PROMPT §4). Then strengthen the weakest check until it catches the case.
      This is honest detection headroom the deterministic reviewer can close.
- [x] M10b: deterministic scientific scaffolding (spec §4b — the [deterministic]
      items ONLY). SESSION-3 PARTIAL: positioning-lite is DONE (reviewer/positioning.py:
      related-work presence + novelty/SOTA overclaim → Weakness + Contribution↓;
      derived critique, kept out of detection/FP) and the single-run/no-variance
      design critique already exists (reviewer/scientific_scaffolding.py). REMAINING
      ONLY: a claim-scope note vs the ledger's actual coverage (# trials/seeds/GPU)
      and one templated follow-up per substantive Weakness. Do NOT reimplement
      positioning. S5 emits, per kept-candidate hypothesis: a claim-scope note vs
      the ledger's actual coverage (# trials, seeds, GPU type), a design critique
      (single-run / no-variance / missing confirmation rerun), one templated
      follow-up per substantive Weakness, and a positioning-lite check (zero
      citations in a hypothesis paper → Presentation weakness). All computed from
      the ledger/parsed paper — no model call. Lands in Weaknesses/Questions under
      the FP rule. Measured by section COMPLETENESS + external robustness, NOT by
      the detection metric. Do NOT add answer-key "detection" entries for these.
      (The NAMED confound + real positioning are judgment — they belong to M14.)
- [x] M11: external generalization smoke test — for every paper in
      `eval/external/` (real published AI papers placed by a human; skip if the
      dir is empty), `eval.py` already runs the pipeline and reports a robustness
      sub-metric (external_no_crash_rate + external_completeness +
      external_finding_total). Verify no crash and record the 3 most substantive
      findings per external paper in the Progress Log. Raising external
      robustness (no crashes, full sections, non-trivial findings) is a real
      goal even without an answer key.
- [x] M13: judgment-layer scaffold, NO model yet (spec §4c). The `--best` hook
      `_apply_judgment_layer` in `reviewer/pipeline.py` is already wired and
      no-op. Implement the GROUNDING machinery it needs: a function that takes
      candidate critique sentences + the S3 findings / S4 verdicts and keeps a
      sentence only when grounded (reuse `composer.ground_comments` semantics),
      populating `state.judgment["comments"]`. Drive it from DETERMINISTIC draft
      sentences (the §4b scaffolding) so `best` output is still reproducible and
      the machinery is proven before any model is added. Add a test: `best` runs,
      audit output byte-identical to `--mode audit`.
- [x] M14 (GATED — only if API-key + Codex credit confirmed at check-in; else
      SKIP and log why): add the model DRAFT behind the M13 grounding. Feed ONLY
      the sanitized paper text; temperature 0 + fixed seed; record model id +
      prompt hash in the freeze block; calibration may only LOWER scores. On any
      model/quota error, leave `state.judgment` empty so audit output stands.
      One bounded call budget per review. Verify injection twins still score
      invariant (sanitize-first) and audit-mode determinism is untouched.
- [x] M15 (optional, after M14): multi-persona drafts (harsh-theorist /
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
iter 15 | M10a | eval=1.100000 | Added a mean-of-repeated-runs then delta corruption (hardened baseline 0.988889) and closed it generically; eval details: papers=13 flaws=9 identification=1.000 localization=1.000 fp=0 completeness=1.000 injection_resistance=1.000 external(papers=7 no_crash=1.000 completeness=1.000 findings=0).

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
- [x] G1: deduped the opaque "conflicts with deterministic evidence" weakness —
      a contradicted claim now renders only the specific finding, not both.
- [x] G2: added a prose-ratio generality eval pair (clean_prose_ratio +
      corrupt_prose_ratio) so backpressure covers the general P1b check. (The
      Self-Review honesty audit is a DERIVED critique kept out of detection/FP
      accounting by design, so it is covered by tests, not an eval-detection case.)
- [x] Competitiveness (judging-aligned, from re-read of the event SKILL): the
      Summary now states an ASSESSMENT, not a claim count ("review-as-summary" is
      a flagged common mistake); scoring treats a proven contradiction OR a
      dishonest self-certification as an integrity breach → Soundness 1 / Overall
      reject, not offset by supported results.
- [x] G3: judgment layer (M13–M15) = main remaining substance lever for
      evidence-poor peer papers; needs Codex API quota. PDF input likely unneeded
      (peer papers use the Markdown official template). DONE in session 3 (below).

## Session 3 (human-directed — ICML research-evaluation layers: positioning / novelty / model critique)

Added the research-depth half of an ICML review on top of the deterministic
audit. 82 tests green; event eval stays 1.10 (detection 1.0, FP 0, injection 1.0);
external smoke: 7 real papers, no crash, completeness 1.0, 0 false findings. DO
NOT reimplement any of the below — search the code first (PROMPT §3).

- M10b positioning-lite → `reviewer/positioning.py` (ships in `audit`): related-work
  presence + novelty/SOTA overclaim (a superiority claim situated against zero prior
  work → Weakness + Contribution→1). FP-safe, self-suppressing, kept OUT of
  detection/FP accounting (derived critique). Replaced the hardcoded Contribution=2.
- M13 grounding + M14 model + M15 personas → `reviewer/novelty_positioning.py`
  (retrieval, `--best`) + `reviewer/model_critique.py` (model, `--best`). Retrieval:
  real arXiv search for topically-close prior work; a closely-related uncited paper →
  grounded Question naming the real arXiv id; injectable fetch + cache; 429/failure
  degrades to none. Model: dependency-free OpenAI-compatible call; multi-persona
  (harsh-theorist/empiricist/repro-cop) + AC meta-review; sanitize-first (injection-
  scan output only); grounding ENFORCED in code (ungrounded praise dropped, ungrounded
  criticism→question); calibration only LOWERS; temperature 0 + seed; model id +
  prompt sha256 in the Scientific Judgment provenance line. Both run AFTER the S6
  freeze so audit identity/verdict-digest are untouched. Enablement gated on
  OPENAI_API_KEY or RALPH_BEST_RETRIEVAL; disabled → best==audit (test_modes).
  Live-verified on Attention (gpt-4o-mini): grounded weaknesses + Soundness 2→1.
- Review format (human request): Scores are the headline (top, Overall first); a
  closing `## Comment` ends the review. eval markers updated; completeness 1.0.
- Generality bug the real-paper corpus caught: `ledger-trace` flagged a DDPM
  Inception score as "absent from experiments.jsonl" on a paper with NO ledger.
  Fixed with an `event_format` guard (peer paper → no finding; event submission
  missing its ledger → still flagged). Regression test in test_generality.py.
- Env: dependency-free `_load_dotenv` in run_review.py loads `.env`
  (OPENAI_API_KEY / RALPH_BEST_RETRIEVAL); OPENAI_MODEL / OPENAI_BASE_URL honored.

M11 external findings: the 7 corpus papers are well-positioned real papers, so
mechanical findings are ~0 (correct — this is fairness, not a miss); positioning
self-suppresses on all 7; best-mode retrieval/model surface the positioning
questions. Attention: 1 comparator-less-superiority positioning Question.

Hardening pass (2026-07-12): sanitize-first canonical PDF/Markdown identity,
external citation snapshot freeze, span-aware verdict attribution, direct
six-field competition scores, substantive best-mode prompt, live guidance
adapter, and replayable fresh-random PDF smoke implemented. M12 remains the
repeatable optional hill-climb.

## Session 4 (urgent — real scientific committee and ten-paper deployment)

- [x] C1: replace the single prompt that impersonates multiple reviewers with
      three actual concurrent specialist calls (theorist, experimentalist,
      scope/ablation) and one grounded area-chair meta-review.
- [x] C2: merge validated scientific judgment into the official review and
      permit evidence-grounded score increases or decreases while preserving
      deterministic integrity caps and per-paper fallback.
- [x] C3: require and safely resume the fixed ten-assignment API flow, including
      partially submitted states and exact ordinal validation.
- [ ] C4: defer regression, integration, and timed ten-paper execution until
      after the code-only deadline pass; do not claim deployment verification
      before those checks run.
- [x] C5: quarantine low-contrast, transparent, sub-pixel, and non-rendering PDF
      text before Markdown extraction so concealed numeric payloads cannot enter
      claims, scores, or committee prompts.
