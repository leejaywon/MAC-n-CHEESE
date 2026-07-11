# AGENTS.md — build/run notes (keep brief; agents update with discoveries)

## Environment
- Python: `source .venv/bin/activate` (ALWAYS — never system python)
- Deps: `pip install -r requirements.txt`; add new deps there
- W&B: offline only (`WANDB_MODE=offline`); never sync without human approval
- macOS, zsh; `vesslctl` at ~/.local/bin (PATH required)

## Commands
- Eval (single score, higher better): `python eval/eval.py`
- Review one paper: `python run_review.py <paper.md> <evidence_dir> --out <review.md>`
- Regenerate eval set: `python eval/make_eval_set.py` (only when task allows)

## Layout
- `specs/review-agent-spec.md` — product spec (source of truth)
- `fix_plan.md` — task queue + progress log
- `reviewer/` — pipeline package (S1–S6)
- `eval/` — papers, answer keys (READ-ONLY except M3/M8), eval.py
- `submission/` — final artifacts (review-agent.md, review results)
- Track 1 lives in sibling repo `../2026_07_Ralphthon-track1` (NEVER write there)
- `vendor/ralphthon-icml` — official rulebook (read-only)

## Discovered optimizations
(agents: append one-liners here)
- Sandboxed W&B evals need workspace-local cache/config/data paths plus `x_disable_stats=True` to avoid macOS `netstat` monitor crashes.
