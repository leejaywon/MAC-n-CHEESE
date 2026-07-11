#!/usr/bin/env python3
"""Run the Track 2 evidence-bound review pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from reviewer import run_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review a frozen Track 1 paper against its evidence bundle."
    )
    parser.add_argument("paper", type=Path, help="path to the frozen paper")
    parser.add_argument("evidence_dir", type=Path, help="path to its evidence bundle")
    parser.add_argument("--out", required=True, type=Path, help="review Markdown output path")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        state = run_pipeline(args.paper, args.evidence_dir, args.out)
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as error:
        _parser().error(str(error))
    print(f"wrote {state.output_path} ({', '.join(state.completed_stages)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
