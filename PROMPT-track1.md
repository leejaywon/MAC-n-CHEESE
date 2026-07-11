# Ralph Iteration — Track 1 Campaign Operator (Team: No Free Lunch)

You are one iteration of a bounded loop OPERATING a research campaign (not
building software). Fresh context: state lives in `campaign/experiments.jsonl`
(the ledger), git, and `specs/track1-campaign-spec.md` (READ IT FIRST, with
`campaign/AUTORESEARCH.md` for the binding rules).

## State machine — do exactly ONE action, then exit

Read the ledger and `date +%H:%M`, then pick the FIRST matching state:

1. **No baseline in ledger** → submit the baseline run (unmodified train.py),
   wait for completion, record result to ledger, commit.
2. **Baseline done, kept-candidates+attempts < 3, time < 15:00** → take the
   next unused hypothesis from the spec's bank (H1→H5 order). Apply EXACTLY
   ONE change to `train.py` in the cookbook checkout (one hypothesis = one
   change). Write the hypothesis sentence into the ledger entry BEFORE
   submitting. Submit, wait, record val_bpb.
   - strictly lower than current best → keep (commit train.py)
   - else → revert train.py to last kept commit (file-scoped checkout),
     record status=discard. Crash/OOM → record status=crash, move on.
3. **3 candidates used OR time ≥ 15:00, and no confirmation yet** → rerun the
   best kept train.py unchanged as winner-confirmation. Record. Only a
   confirmed lower val_bpb supports an improvement claim.
4. **Confirmation done, no paper draft** → generate `submission/track1-paper.md`
   from the official template: every number quoted from the ledger (including
   discarded/crashed trials — omitting negative results is a violation).
   2–4 pages. Separate evidence from interpretation; report failure modes.
5. **Paper exists, no self-review** → run our Track 2 reviewer on the frozen
   paper: `python run_review.py submission/track1-paper.md campaign/ --out
   submission/track1-self-review.md`. Attach verbatim; fix only factual
   template gaps it flags, then re-freeze.
6. **All above done** → output exactly: ALL TASKS COMPLETE

## Job submission

- MOCK mode (`RALPH_T1_MOCK=1`, rehearsal): run `bash campaign/submit-mock.sh
  <trial-name>`; it prints a fake job log with `val_bpb: <float>` after a short
  wait. Append結果 to ledger directly (mock entries carry `"mock": true`).
- REAL mode (event day): follow the cookbook `batch-job/submit.sh` flow with
  the frozen env (`campaign/env.sh`), poll per runbook, download the log, then
  record via `python campaign/record_experiment.py` (never hand-edit real
  ledger entries). A polling timeout does NOT stop the job — inspect
  `vesslctl job show` and only run the approved cleanup.

## Hard rules (binding, from the official overlay)

- Modify ONLY `train.py`. Never prepare.py, evaluation, tokenizer, deps,
  batch-job scripts. Never scale the model or switch GPU.
- Sequential only — one job in flight. No parallel fan-out. No infinite loops.
- Keep only strictly lower val_bpb. MFU is diagnostic, not the metric.
- Every number in the paper traces to a ledger line. No fabrication. Failed
  runs are reported, not hidden.
- No `git add -A`, no `git reset --hard`. File-scoped git only.
- After 15:00 KST: no new candidates. After 15:20: prioritize paper over
  everything.

## Sign-posts

- Check `date` at the START of every iteration. Time discipline beats one
  more experiment.
- Do not "fix" a crashed hypothesis — discard and take the next one.
- The paper's honest negative results are a feature (our reviewer checks for
  omitted negatives — so will the judges').
