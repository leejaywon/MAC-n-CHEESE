#!/usr/bin/env python3
"""Run the scientific paper review pipeline on a PDF or Markdown paper."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from reviewer import prepare_paper, run_pipeline


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a ``.env`` file for keys not already set.

    Dependency-free so the scientific committee can read ``OPENAI_API_KEY`` /
    ``REVIEWER_BEST_RETRIEVAL`` from the gitignored ``.env`` a user copies from
    ``.env.example``. Exported shell variables always win; blank/comment/malformed
    lines are skipped. ``--deterministic`` never consults these, so it stays fully
    offline and reproducible.
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
        description="Review a scientific paper (PDF or Markdown), optionally against an evidence bundle."
    )
    parser.add_argument("paper", type=Path, help="path to the paper (.pdf or .md)")
    parser.add_argument(
        "evidence_dir",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "optional path to an evidence bundle (e.g. experiments.jsonl); "
            "omit to review the paper on its own"
        ),
    )
    parser.add_argument("--out", required=True, type=Path, help="review Markdown output path")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help=(
            "skip the scientific committee: a fully deterministic, reproducible, "
            "offline evidence audit with no model calls or API cost. The default "
            "adds three scientific specialists and a grounded area-chair "
            "meta-review on top, with per-paper deterministic fallback."
        ),
    )
    return parser


def main() -> int:
    _load_dotenv(Path(__file__).resolve().parent / ".env")
    args = _parser().parse_args()
    empty_evidence: tempfile.TemporaryDirectory[str] | None = None
    try:
        converted_path = (
            args.out.parent / ".reviewer_sources" / f"{args.paper.stem}.md"
            if args.paper.suffix.lower() == ".pdf"
            else None
        )
        prepared = prepare_paper(args.paper, converted_path=converted_path)
        markdown_path = Path(prepared.markdown.path)
        if Path(prepared.original.path) != markdown_path:
            print(f"converted {prepared.original.path} -> {markdown_path}")
        if args.evidence_dir is None:
            empty_evidence = tempfile.TemporaryDirectory(prefix="review-no-evidence-")
            evidence_dir = Path(empty_evidence.name)
        else:
            evidence_dir = args.evidence_dir
        state = run_pipeline(
            args.paper,
            evidence_dir,
            args.out,
            mode="audit" if args.deterministic else "best",
            prepared_paper=prepared,
        )
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as error:
        _parser().error(str(error))
    finally:
        if empty_evidence is not None:
            empty_evidence.cleanup()
    print(f"wrote {state.output_path} ({', '.join(state.completed_stages)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
