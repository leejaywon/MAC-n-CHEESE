# Live Review Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hardening branch reliably acquire ten Track 1 PDFs, save originals locally, produce best-mode reviews with deterministic fallback, and emit valid submission outputs.

**Architecture:** Keep the guidance-driven ten-paper runner as the deployment entrypoint. Restore the invariant that concealed instructions are quarantined and reported without changing scientific scores, retain deterministic score caps only for scientific contradictions or dishonest self-review, and allow the worktree to load an explicitly referenced shared `.env` without copying secrets.

**Tech Stack:** Python 3.14, `unittest`, `pymupdf4llm`, W&B offline evaluation, stdlib HTTP client.

---

### Task 1: Restore injection score invariance

**Files:**
- Modify: `reviewer/composer.py`
- Modify: `reviewer/pipeline.py`
- Test: `tests/test_injection_scan.py`

- [x] Run the existing attack-twin tests and confirm they fail because injection findings are counted as scientific integrity breaches.
- [x] Remove injection findings from deterministic and committee score-cap inputs while preserving Ethics reporting and sanitation traces.
- [x] Re-run `python -m unittest tests.test_injection_scan -q`; expect all tests to pass.

### Task 2: Preserve actionable API error detail

**Files:**
- Modify: `submit.py`
- Test: `tests/test_submit_dryrun.py`

- [x] Run `ErrorActionTests.test_exhausted_transient_error_surfaces_returned_context` and confirm the returned `detail` is absent.
- [x] Add the already-redacted error detail to `_error_context`.
- [x] Re-run the focused test; expect it to pass without exposing credentials.

### Task 3: Align tests with the current ten-paper contract

**Files:**
- Modify: `tests/test_api_scores.py`
- Modify: `tests/test_modes.py`
- Modify: `tests/test_pdf_ingestion.py`
- Modify: `tests/test_submit_dryrun.py`

- [x] Update API-score fixtures to use an actual sectioned review body so public-comment extraction is exercised.
- [x] Patch the current scientific committee seam instead of the removed legacy `_model_critique` symbol.
- [x] Expect the visibility-aware converter identity.
- [x] Change two-paper mock expectations to exact ordinals 1–10, ten POSTs, and nine remaining records after ordinal 1 is already submitted.
- [x] Run the four affected test modules; expect all to pass.

### Task 4: Connect best-mode configuration without copying secrets

**Files:**
- Modify: `submit.py`
- Modify: `tests/test_submit_dryrun.py`
- Create locally (gitignored): `.env`

- [x] Add a failing test where `.env` contains `RALPHTHON_ENV_FILE=<shared-file>` and the shared file contains the best-mode keys.
- [x] Load the explicit shared env file once after the local file, rejecting self-reference and preserving already-exported environment variables.
- [x] Create the feature worktree `.env` with only `RALPHTHON_ENV_FILE=/Users/jerry/Documents/FolderInDocuments/Dev/2026_07_Ralphthon-track2/.env`; never copy or print the key.
- [x] Verify configuration flags report model and retrieval ready without printing values.

### Task 5: End-to-end verification

**Files:**
- Modify after real-PDF replay exposed a mismatch: `reviewer/pipeline.py`
- Test: `tests/test_pdf_ingestion.py`

- [x] Run `python -m unittest discover -s tests -q`; expect zero failures.
- [x] Run `WANDB_MODE=offline python eval/eval.py`; expect score `1.100000` and injection resistance `1.000`.
- [x] Run `python submit.py --dry-run`; expect 10/10 prepared and posted with valid local artifacts.
- [x] Replay the latest five-paper PDF manifest in audit mode; expect 5/5 complete with unchanged PDF hashes.
- [x] Fix and regression-test prepared PDF visibility records uncovered by the replay.
- [x] Fetch the live canonical `skill.md` through `AgentClient`; expect the Ralphthon runbook identity.
- [x] Inspect the final worktree diff and report any remaining human-only prerequisite, especially the setup token.
