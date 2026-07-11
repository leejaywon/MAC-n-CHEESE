"""Tests for run modes: audit (default, deterministic) and best (judgment hook)."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from reviewer import run_pipeline
from reviewer import pipeline as pipeline_module


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "eval/papers/clean_val_bpb.md"
EVIDENCE = ROOT / "eval/evidence/clean_val_bpb"
# Lines that legitimately differ between two runs / two output files: the UTC
# freeze stamp (per run) and the recorded output path (per file). Everything else
# is a pure function of the frozen inputs and the reviewer source.
VOLATILE_RE = re.compile(r"^- (?:Frozen at \(UTC\)|Output path):.*$", re.M)


def _review(mode: str, out_dir: str) -> str:
    state = run_pipeline(PAPER, EVIDENCE, Path(out_dir) / f"{mode}.md", mode=mode)
    return state.review_markdown


class ModeTests(unittest.TestCase):
    def test_audit_is_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = run_pipeline(PAPER, EVIDENCE, Path(directory) / "d.md")
        self.assertEqual(state.mode, "audit")

    def test_unknown_mode_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_pipeline(PAPER, EVIDENCE, Path(directory) / "x.md", mode="turbo")

    def test_best_equals_audit_until_layer_built(self) -> None:
        # The judgment layer is a no-op today, so best output must equal audit
        # output except for the per-run UTC freeze timestamp.
        with tempfile.TemporaryDirectory() as directory:
            audit = VOLATILE_RE.sub("", _review("audit", directory))
            best = VOLATILE_RE.sub("", _review("best", directory))
        self.assertEqual(audit, best)
        self.assertNotIn("## Scientific Judgment", audit)

    def test_best_renders_grounded_judgment_when_layer_present(self) -> None:
        # Simulate the loop's future M13+ layer to prove the extension point and
        # the render path work end to end, without perturbing audit determinism.
        original = pipeline_module._apply_judgment_layer

        def _fake_layer(state: pipeline_module.ReviewState) -> pipeline_module.ReviewState:
            state.judgment = {
                "comments": ["Scope is limited to n=2 single-seed runs [claim-001]."]
            }
            return state

        pipeline_module._apply_judgment_layer = _fake_layer
        try:
            with tempfile.TemporaryDirectory() as directory:
                best = _review("best", directory)
        finally:
            pipeline_module._apply_judgment_layer = original
        self.assertIn("## Scientific Judgment (best mode)", best)
        self.assertIn("Scope is limited to n=2", best)


if __name__ == "__main__":
    unittest.main()
