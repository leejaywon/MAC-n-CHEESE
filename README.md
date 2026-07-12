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

## Modes

- **`audit`** (default) — fully deterministic, offline, injection-resistant. The
  same inputs always produce the same verdict labels; hidden reviewer-directed
  instructions in the paper are sanitized and reported, never obeyed. This is the
  primary submission.
- **`best`** — `audit` plus an optional scientific judgment layer that retrieves
  the real prior-art literature from arXiv and adds a grounded, calibration-only-
  lowers model critique. It runs **after** the audit is frozen, so it can never
  perturb the deterministic result. Enabled by `OPENAI_API_KEY` (see
  `.env.example`) or `RALPH_BEST_RETRIEVAL=1`; disabled → `best` equals `audit`.

## How it works

An ordered six-stage pipeline (`reviewer/pipeline.py`): **S1** parse → **S2**
claim extraction → **S3** mechanical checks → **S4** evidence-bound verdicts →
**S5** compose → **S6** freeze (content-addressed identity + verdict digest).

- **Mechanical checks** (`reviewer/`): ledger-trace, internal-consistency,
  arithmetic, baseline-fairness, negative-evidence, citation-existence,
  template-compliance, injection-scan, self-review-audit.
- **Scientific positioning** (`positioning.py`) — deterministic related-work /
  novelty / SOTA-overclaim audit; false-positive-safe and self-suppressing.
- **Judgment layer** (`novelty_positioning.py`, `model_critique.py`) — the
  `best`-mode retrieval + multi-persona model critique, grounded and
  calibration-only-lowers.

## Testing

```bash
python -m unittest discover -s tests -q      # unit + regression suite
python eval/eval.py                          # detection / false-positive / injection-resistance score
```
