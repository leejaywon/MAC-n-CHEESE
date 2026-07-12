# Track 2 Review Agent — "No Free Lunch"

An evidence-bound, ICML-style reviewer for Ralphthon @ ICML 2026 (Track 2). It
reviews an arbitrary peer paper against its evidence bundle and emits a review
whose every score and claim is traceable to the paper text, its tables, or the
supplied results — no fabricated praise, no ungrounded accusations.

## Input

Each of the (up to 10) evaluation **sets** is:

- **A paper** — a Track 1 PDF (or a frozen Markdown manuscript). PDFs are
  converted to Markdown automatically.
- **An evidence bundle** — a directory of result files that verify the paper's
  numbers/tables/claims: `experiments.jsonl` ledgers, CSV/JSON results, logs,
  appendix, figure sources. May be empty for a pure manuscript.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# One set:
python run_review.py path/to/paper.pdf path/to/evidence_dir --out review.md

# Ten sets in parallel (papers/<name>.pdf, evidence/<name>/ → reviews/<name>.review.md):
python review_batch.py papers/ --out-dir reviews/ --evidence-root evidence/ --mode best
```

## Live submission (openagentreview.org)

On event day the ten peer papers are pulled from the platform API (see
`skill.md`) — title + abstract + PDF only, no evidence bundle — and structured
reviews are posted back. `submit.py` runs that whole flow:

```bash
# Dry run against an in-memory mock — no token, no network. Validates the flow
# and the exact review schema the server enforces:
python submit.py --dry-run

# Preview the live assignments without submitting anything:
python submit.py --no-post

# Download all ten original assigned papers without reviewing or posting:
python submit.py --download-only

# Live: paste the 15-minute setup token when prompted (input is hidden):
python submit.py --mode best
```

- **Secret hygiene** — the setup token is read from **stdin** (never argv, so it
  stays out of shell history) and exchanged once for a bearer held only in
  memory. Nothing prints the token, the bearer, or paper identity beyond the
  public ordinal/title. Each paper's fetch → review → POST runs in a worker
  *thread*, so the bearer is never copied into a subprocess.
- **Resumable** — assignments the platform already lists as `submitted` are
  skipped, so an interrupted review window resumes and posts only what's missing.
- **Stable local paper archive** — every fetched assignment is atomically saved
  under `submit_work/assigned_papers/ordinal-01/paper.pdf` through
  `ordinal-10/paper.pdf`, with a non-secret `manifest.json`.
- **Schema-safe** — the pipeline emits the platform's
  `soundness/presentation/significance/originality` (1–4),
  `overall` (1–6), `confidence` (1–5) + `comments`, and validates the body
  locally (int-only, in-range, no extra fields) before an identity-transform
  POST. The full frozen Evidence Trace remains local; live `comments` contain
  only the substantive review sections and omit local paths and hashes.
- **Guidance-driven** — the client fetches the canonical
  `/api/ralphthon/v1/skill.md` at credential startup and immediately before
  every state-changing POST, follows stable `reason_code`/`next_action` data,
  uses only returned scoped PDF URLs, and treats terminal `next_action:none` as
  a correct no-op.

Peer papers ship no evidence bundle, so the review is manuscript-only: the
deterministic mechanical checks that need no ledger (internal-consistency,
arithmetic, citation-existence, template, injection-scan, positioning) still run.

## Modes

- **`audit`** (default) — fully deterministic, offline, injection-resistant. The
  same inputs always produce the same verdict labels; hidden reviewer-directed
  instructions in the paper are sanitized and reported, never obeyed. PDF
  near-white, transparent, sub-pixel, and non-rendering text is quarantined
  before Markdown extraction. This is the guaranteed fallback contract.
- **`best`** — `audit` plus optional prior-art retrieval and a scientific
  committee. Three role-targeted specialists run concurrently, then a grounded
  area-chair call produces the final scientific review and six scores. Validated
  committee content is merged into the official review sections and may raise or
  lower scores; proven integrity breaches still cap Soundness and Overall at 2.
  The deterministic audit identity and verdict digest remain frozen. Enabled by
  `OPENAI_API_KEY` (see `.env.example`); retrieval alone can be enabled with
  `RALPH_BEST_RETRIEVAL=1`. Models receive only sanitized,
  section-prioritized paper spans up to `RALPH_BEST_MAX_CHARS` (default 60,000).
  Any committee failure falls back per paper to the deterministic review.

## Fresh random-PDF smoke and replay

Stress-test the complete PDF path on fresh public arXiv papers. The first
command generates and prints a random 64-bit seed, writes a manifest before
reviewing, and isolates failures per paper:

```bash
python eval/random_pdf_smoke.py --count 5 --mode audit
python eval/random_pdf_smoke.py --replay path/to/manifest.json --mode audit
```

Replay does not query arXiv discovery and rejects a PDF whose SHA-256 differs
from the manifest. Smoke downloads, manifests, derived Markdown, and reviews are
local artifacts and must not contain API credentials.

## How it works

An ordered six-stage pipeline (`reviewer/pipeline.py`): **S1** parse → **S2**
claim extraction → **S3** mechanical checks → **S4** evidence-bound verdicts →
**S5** compose → **S6** freeze (content-addressed identity + verdict digest).

- **Mechanical checks** (`reviewer/`): ledger-trace, internal-consistency,
  arithmetic, baseline-fairness, negative-evidence, citation-existence,
  template-compliance, injection-scan, self-review-audit.
- **Scientific positioning** (`positioning.py`) — deterministic related-work /
  novelty / SOTA-overclaim audit; false-positive-safe and self-suppressing.
- **Judgment layer** (`novelty_positioning.py`, `model_critique.py`) —
  `best`-mode retrieval plus three concurrent scientific specialists and one
  grounded area-chair meta-review, with isolated per-paper fallback.

## Testing

```bash
python -m unittest discover -s tests -q      # unit + regression suite
WANDB_MODE=offline python eval/eval.py       # detection / false-positive / injection-resistance score
```
