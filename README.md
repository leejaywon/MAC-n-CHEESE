<p align="center">
  <img src="docs/banner.png" alt="A committee of decapod-crowned academic reviewers auditing a manuscript" width="820">
</p>

<h1 align="center">MAC n CHEESE</h1>

<p align="center">
  <em>Multi-Agent Committee 'n Checking &amp; Evaluating with Scientific Evidence</em>
</p>

<p align="center">
  🏆 <strong>Winner · Track 2 (Review Agent)</strong> — Ralphthon @ ICML 2026 Auto-Research
</p>

<p align="center">
  An evidence-bound, ICML-style reviewer for scientific papers.
</p>

---

Give it a paper as a **PDF or Markdown** file — optionally with an evidence bundle
of result files — and it emits a structured review whose every score and claim is
traceable to the paper text, its tables, or the supplied results. No fabricated
praise, no ungrounded accusations.

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

# Review a paper (full review: deterministic audit + scientific committee):
python run_review.py path/to/paper.pdf --out review.md

# ...against an evidence bundle:
python run_review.py path/to/paper.pdf path/to/evidence_dir --out review.md

# Deterministic only — offline, reproducible, no API cost (skips the committee):
python run_review.py path/to/paper.pdf --out review.md --deterministic

# Batch: papers/<name>.(pdf|md) [+ evidence/<name>/] -> reviews/<name>.review.md
python review_batch.py papers/ --out-dir reviews/ --evidence-root evidence/
```

## What runs

By default the reviewer produces the **full review**: the deterministic evidence
audit **plus** a scientific committee. The committee runs only after the audit is
frozen, so model output can never perturb the reproducible audit identity or
verdict digest; any committee failure falls back per paper to the audit.

- **Deterministic audit** (always computed) — reproducible, offline,
  injection-resistant. The same inputs always produce the same verdict labels;
  hidden reviewer-directed instructions in the paper are sanitized and reported,
  never obeyed. PDF near-white, transparent, sub-pixel, and non-rendering text is
  quarantined before Markdown extraction.
- **Scientific committee** — three role-targeted specialists run concurrently,
  then a grounded area-chair call produces the final scientific review and six
  scores. Validated committee content is merged into the review sections and may
  raise or lower scores; proven integrity breaches still cap Soundness and Overall
  at 2. Needs `OPENAI_API_KEY` (see `.env.example`); models receive only sanitized,
  section-prioritized paper spans up to `REVIEWER_BEST_MAX_CHARS` (default 60,000).
  Retrieval alone can run without a key via `REVIEWER_BEST_RETRIEVAL=1`.
- **`--deterministic`** — skip the committee entirely: the pure evidence audit,
  offline and free.

## Fresh random-PDF smoke and replay

Stress-test the complete PDF path on fresh public arXiv papers. The first command
generates and prints a random 64-bit seed, writes a manifest before reviewing,
and isolates failures per paper:

```bash
python eval/random_pdf_smoke.py --count 5
python eval/random_pdf_smoke.py --replay path/to/manifest.json
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
