#!/usr/bin/env python3
"""Parallel batch reviewer — review many papers concurrently.

Each paper's review is fully independent, so N papers run in N parallel processes.
The per-paper work is the deterministic S1–S6 pipeline plus, in ``--best`` mode,
bounded arXiv retrieval, three concurrent specialist calls, and one area-chair
meta-review. Wall time is therefore bounded by the slowest paper-level committee,
not by the paper count. This is the right tool for reviewing ten papers under a
deadline; deterministic audit state and per-paper fallback remain isolated.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import tempfile
import time
from pathlib import Path

from reviewer import prepare_paper, run_pipeline

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _review_one(job: tuple[str, str, str, str]) -> dict[str, object]:
    paper, evidence_dir, out_path, mode = job
    started = time.time()
    try:
        # A .pdf set member is converted to Markdown first (next to its review).
        paper_path = Path(paper)
        prepared = prepare_paper(
            paper_path,
            Path(out_path).parent / f"{paper_path.stem}.source.md",
        )
        state = run_pipeline(
            paper_path,
            Path(evidence_dir),
            Path(out_path),
            mode=mode,
            prepared_paper=prepared,
        )
        scientific_status = (
            "committee"
            if getattr(state, "scientific_judgment", None) is not None
            else ("fallback" if mode == "best" else "not_requested")
        )
        return {
            "paper": Path(paper).name,
            "ok": True,
            "seconds": round(time.time() - started, 2),
            "scores": {name: score["value"] for name, score in state.scores.items()},
            "scientific_status": scientific_status,
        }
    except Exception as error:  # noqa: BLE001 — one bad paper must not sink the batch
        return {"paper": Path(paper).name, "ok": False, "seconds": round(time.time() - started, 2), "error": repr(error)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Review every *.md paper in a directory in parallel.")
    parser.add_argument("papers_dir", type=Path, help="directory of paper .pdf/.md files (one per set)")
    parser.add_argument("--out-dir", required=True, type=Path, help="where to write the review .md files")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=None,
        help="directory holding <paper-stem>/ evidence subdirs; papers without one get an empty bundle",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="skip the scientific committee (offline, reproducible, no API cost)",
    )
    parser.add_argument("--workers", type=int, default=min(8, (os.cpu_count() or 4)))
    args = parser.parse_args()

    if not args.deterministic:
        _load_dotenv(ROOT / ".env")

    # Prefer the PDF when a converted .md sidecar sits next to it, so a paper that
    # was already run through run_review.py is never reviewed twice in a batch.
    by_stem: dict[str, Path] = {}
    for path in sorted(args.papers_dir.iterdir()):
        if path.suffix.lower() not in {".pdf", ".md", ".markdown"}:
            continue
        if path.stem not in by_stem or path.suffix.lower() == ".pdf":
            by_stem[path.stem] = path
    papers = sorted(by_stem.values())
    if not papers:
        parser.error(f"no .pdf or .md papers in {args.papers_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="review-batch-empty-") as empty_evidence:
        jobs: list[tuple[str, str, str, str]] = []
        for paper in papers:
            sibling = args.evidence_root / paper.stem if args.evidence_root else None
            evidence = str(sibling) if sibling and sibling.is_dir() else empty_evidence
            jobs.append((str(paper), evidence, str(args.out_dir / f"{paper.stem}.review.md"), "audit" if args.deterministic else "best"))

        wall_start = time.time()
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(_review_one, jobs))
        wall = time.time() - wall_start

    ok = [result for result in results if result["ok"]]
    failed = [result for result in results if not result["ok"]]
    committee = sum(result.get("scientific_status") == "committee" for result in ok)
    fallback = sum(result.get("scientific_status") == "fallback" for result in ok)
    per_paper = [float(result["seconds"]) for result in results]
    print(f"batch: {len(ok)}/{len(results)} reviewed [workers={args.workers}]")
    if not args.deterministic:
        print(f"scientific: committee={committee} fallback={fallback}")
    print(f"wall={wall:.2f}s  slowest-paper={max(per_paper):.2f}s  sum-serial={sum(per_paper):.2f}s")
    for result in results:
        if result["ok"]:
            overall = result["scores"].get("Overall recommendation", "?")
            print(f"  ✓ {result['paper']:<44} {result['seconds']:>5.2f}s  overall={overall}/6")
        else:
            print(f"  ✗ {result['paper']:<44} {result['seconds']:>5.2f}s  {result['error']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
