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

By default the reviewer produces the **full review**: a multi-agent review
committee whose judgment is the review, framed by a deterministic guardrail
layer. The committee runs only after the audit is frozen, so model output can
never perturb the reproducible audit identity or verdict digest; any committee
failure falls back per paper to the deterministic audit document.

- **Review committee** (`REVIEWER_PANEL`, default 3) — every panelist reads the
  **full sanitized paper** (text, tables, figures) and writes a complete
  ICML-shaped review; the panel differs only in emphasis (theorist /
  empiricist / scope-and-ablation). An **area chair** then synthesizes the final
  review, cross-checking each panel criticism against the paper and dropping
  anything it cannot ground. `REVIEWER_PANEL=1` runs a single reviewer and skips
  the area chair. Needs `OPENAI_API_KEY` and `OPENAI_MODEL` (see
  `.env.example`).
- **Deterministic guardrails** (always computed) — reproducible, offline,
  injection-resistant. Hidden reviewer-directed instructions in the paper are
  sanitized, reported, and never obeyed; PDF near-white, transparent, sub-pixel,
  and non-rendering text is quarantined before Markdown extraction. Mechanical
  findings (citations, arithmetic, consistency, promised-but-unreported items)
  reach the committee as **neutral annotations** — leads to weigh, never
  verdicts; a machine-checked title-echo gate rejects a review of the wrong
  paper; a **proven** integrity breach caps Soundness and Overall at 2.
- **Two outputs** — `review.md` is the committee's review, clean of pipeline
  mechanics and safe for double-blind use; `review.audit.md` is the sidecar
  with content-addressed identities, the evidence trace, and every panel
  member's full review, so each step stays traceable.
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
- **Judgment layer** (`judgment_review.py`, `model_critique.py`,
  `novelty_positioning.py`) — `best`-mode prior-art retrieval plus the review
  panel and area-chair synthesis over the full paper, with a title-echo
  target-coherence gate and isolated per-paper fallback.

## Testing

```bash
python -m unittest discover -s tests -q   # unit + regression suite
python eval/eval.py                        # detection / false-positive / injection-resistance score
```

PDF ingestion requires the optional `pymupdf4llm` dependency (installed via
`requirements.txt`); Markdown input has no extra dependencies.
