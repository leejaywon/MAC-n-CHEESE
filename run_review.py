#!/usr/bin/env python3
"""Run the scientific paper review pipeline on a PDF or Markdown paper."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import datetime
from pathlib import Path

from reviewer import prepare_paper, run_pipeline

DEFAULT_OUT_DIR = Path("reviews")


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


def _log(message: str) -> None:
    print(message, flush=True)


def _log_path_transfer(label: str, source: Path, destination: Path) -> None:
    _log(label)
    _log(f"  {source}")
    _log("  ->")
    _log(f"  {destination}")


def _default_out_path(paper: Path, *, out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    """``reviews/{stem}.review.{YYYY-MM-DD}.md``, with ``-2``, ``-3``, … on collision."""

    date = datetime.now().strftime("%Y-%m-%d")
    base = f"{paper.stem}.review.{date}"
    candidate = out_dir / f"{base}.md"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = out_dir / f"{base}-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


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
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "review Markdown output path (default: "
            f"{DEFAULT_OUT_DIR}/<paper-stem>.review.<YYYY-MM-DD>.md; "
            "adds -2, -3, … if that file already exists)"
        ),
    )
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
    os.environ.setdefault("REVIEWER_PROGRESS", "1")
    args = _parser().parse_args()
    out_path = args.out if args.out is not None else _default_out_path(args.paper)
    mode = "audit" if args.deterministic else "best"
    panel = os.environ.get("REVIEWER_PANEL", "3") or "3"
    model = (os.environ.get("OPENAI_MODEL") or "").strip() or "(unset)"
    empty_evidence: tempfile.TemporaryDirectory[str] | None = None
    try:
        _log("[start]")
        _log(f"  paper: {args.paper}")
        _log(f"  out: {out_path}")
        _log(f"  mode={mode} reviewers={panel} model={model}")

        converted_path = (
            out_path.parent / ".reviewer_sources" / f"{args.paper.stem}.md"
            if args.paper.suffix.lower() == ".pdf"
            else None
        )
        if converted_path is not None:
            _log("[convert] PDF→Markdown starting (OCR may take a while)...")
        prepared = prepare_paper(args.paper, converted_path=converted_path)
        markdown_path = Path(prepared.markdown.path)
        if Path(prepared.original.path) != markdown_path:
            _log_path_transfer("converted", Path(prepared.original.path), markdown_path)
        if args.evidence_dir is None:
            empty_evidence = tempfile.TemporaryDirectory(prefix="review-no-evidence-")
            evidence_dir = Path(empty_evidence.name)
        else:
            evidence_dir = args.evidence_dir
        state = run_pipeline(
            args.paper,
            evidence_dir,
            out_path,
            mode=mode,
            prepared_paper=prepared,
        )
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as error:
        _parser().error(str(error))
    finally:
        if empty_evidence is not None:
            empty_evidence.cleanup()
    _log("wrote")
    _log(f"  {state.output_path}")
    audit_path = state.output_path.with_suffix(".audit.md")
    if state.review_document and audit_path.is_file():
        _log("audit")
        _log(f"  {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
