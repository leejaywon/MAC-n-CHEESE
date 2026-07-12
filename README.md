# Paper Review Agent

An evidence-bound, ICML-style reviewer for scientific papers. Give it a paper as
a **PDF or Markdown** file — optionally with an evidence bundle of result files —
and it emits a structured review whose every score and claim is traceable to the
paper text, its tables, or the supplied results. No fabricated praise, no
ungrounded accusations.

## Input

- **A paper** (required) — a `.pdf` or `.md` manuscript. PDFs are converted to
  Markdown automatically.
- **An evidence bundle** (optional) — a directory of result files that verify the
  paper's numbers/tables/claims: `experiments.jsonl` ledgers, CSV/JSON results,
  logs, appendix, figure sources. Omit it to review the manuscript on its own;
  the deterministic checks that need no ledger still run.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Review a paper on its own:
python run_review.py path/to/paper.pdf --out review.md

# Review a paper against an evidence bundle, best mode:
python run_review.py path/to/paper.pdf path/to/evidence_dir --out review.md --mode best

# Batch: papers/<name>.(pdf|md) [+ evidence/<name>/] -> reviews/<name>.review.md
python review_batch.py papers/ --out-dir reviews/ --evidence-root evidence/ --mode best
```

## Modes

- **`audit`** (default) — fully deterministic, offline, injection-resistant. The
  same inputs always produce the same verdict labels; hidden reviewer-directed
  instructions in the paper are sanitized and reported, never obeyed. PDF
  near-white, transparent, sub-pixel, and non-rendering text is quarantined
  before Markdown extraction. This is the guaranteed fallback contract.
- **`best`** — `audit` plus optional prior-art retrieval and a scientific
  committee. Three role-targeted specialists run concurrently, then a grounded
  area-chair call produces the final scientific review and six scores. Validated
  committee content is merged into the review sections and may raise or lower
  scores; proven integrity breaches still cap Soundness and Overall at 2. The
  deterministic audit identity and verdict digest remain frozen. Enabled by
  `OPENAI_API_KEY` (see `.env.example`); retrieval alone can be enabled with
  `REVIEWER_BEST_RETRIEVAL=1`. Models receive only sanitized, section-prioritized
  paper spans up to `REVIEWER_BEST_MAX_CHARS` (default 60,000). Any committee
  failure falls back per paper to the deterministic review.

## Fresh random-PDF smoke and replay

Stress-test the complete PDF path on fresh public arXiv papers. The first command
generates and prints a random 64-bit seed, writes a manifest before reviewing,
and isolates failures per paper:

```bash
python eval/random_pdf_smoke.py --count 5 --mode audit
python eval/random_pdf_smoke.py --replay path/to/manifest.json --mode audit
```

Replay does not query arXiv discovery and rejects a PDF whose SHA-256 differs from
the manifest. Smoke downloads, manifests, derived Markdown, and reviews are local
artifacts and must not contain API credentials.

## How it works

An ordered six-stage pipeline (`reviewer/pipeline.py`): **S1** parse → **S2** claim
extraction → **S3** mechanical checks → **S4** evidence-bound verdicts → **S5**
compose → **S6** freeze (content-addressed identity + verdict digest).

- **Mechanical checks** (`reviewer/`): ledger-trace, internal-consistency,
  arithmetic, baseline-fairness, negative-evidence, citation-existence,
  template-compliance, injection-scan, self-review-audit.
- **Scientific positioning** (`positioning.py`) — deterministic related-work /
  novelty / SOTA-overclaim audit; false-positive-safe and self-suppressing.
- **Judgment layer** (`novelty_positioning.py`, `model_critique.py`) — `best`-mode
  retrieval plus three concurrent scientific specialists and one grounded
  area-chair meta-review, with isolated per-paper fallback.

## Testing

```bash
python -m unittest discover -s tests -q   # unit + regression suite
python eval/eval.py                        # detection / false-positive / injection-resistance score
```

PDF ingestion requires the optional `pymupdf4llm` dependency (installed via
`requirements.txt`); Markdown input has no extra dependencies.
