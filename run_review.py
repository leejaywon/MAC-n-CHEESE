#!/usr/bin/env python3
"""Run the Track 2 evidence-bound review pipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from reviewer import run_pipeline
from reviewer.to_markdown import convert_to_markdown


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a ``.env`` file for keys not already set.

    Dependency-free so the optional ``--best`` layer can read ``OPENAI_API_KEY`` /
    ``RALPH_BEST_RETRIEVAL`` from the gitignored ``.env`` a user copies from
    ``.env.example``. Exported shell variables always win; blank/comment/malformed
    lines are skipped. Audit mode never consults these, so this changes nothing
    for the deterministic default path.
    """

    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review a frozen Track 1 paper against its evidence bundle."
    )
    parser.add_argument("paper", type=Path, help="path to the frozen paper (.pdf or .md)")
    parser.add_argument("evidence_dir", type=Path, help="path to its evidence bundle")
    parser.add_argument("--out", required=True, type=Path, help="review Markdown output path")
    parser.add_argument(
        "--mode",
        choices=("audit", "best"),
        default="audit",
        help=(
            "audit (default): deterministic, reproducible, injection-proof evidence "
            "audit — the primary submission. best: audit plus the optional scientific "
            "judgment layer (may call a model; never blocks a submission)."
        ),
    )
    return parser


def main() -> int:
    _load_dotenv(Path(__file__).resolve().parent / ".env")
    args = _parser().parse_args()
    try:
        paper = convert_to_markdown(args.paper)
        if paper != args.paper:
            print(f"converted {args.paper} -> {paper}")
        state = run_pipeline(paper, args.evidence_dir, args.out, mode=args.mode)
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as error:
        _parser().error(str(error))
    print(f"wrote {state.output_path} [mode={state.mode}] ({', '.join(state.completed_stages)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
