"""Tests for the source-location contract consumed by later S3 checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reviewer import parse_markdown, run_pipeline


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "eval" / "papers" / "sample_clean.md"


class MarkdownParserTests(unittest.TestCase):
    def test_sample_extracts_sections_table_and_numeric_locations(self) -> None:
        parsed = parse_markdown(SAMPLE)

        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["line_count"], 25)
        self.assertEqual(
            [section["title"] for section in parsed["sections"]],
            [
                "Frozen Track 1 Paper",
                "Research Spec",
                "Short Paper",
                "Abstract",
                "3. Experiments and Results",
                "4. Limitations and Conclusion",
            ],
        )
        self.assertEqual(parsed["sections"][3]["parent_id"], "section-002")

        self.assertEqual(len(parsed["tables"]), 1)
        table = parsed["tables"][0]
        self.assertEqual(table["header"], ["Trial", "Status", "val_bpb"])
        self.assertEqual(table["alignments"], ["left", "center", "right"])
        self.assertEqual(table["rows"][1]["cells"], ["candidate", "keep", "1.196"])

        percentage = next(token for token in parsed["numeric_tokens"] if token["token"] == "2.29%")
        self.assertEqual(percentage["normalized"], "2.29")
        self.assertEqual(percentage["kind"], "percentage")
        self.assertEqual(percentage["location"]["line"], 21)
        self.assertIsNone(percentage["location"]["table_id"])

        seed = next(token for token in parsed["numeric_tokens"] if token["token"] == "42")
        self.assertEqual(seed["context"], "- Baseline: unchanged recipe, seed 42.")

        table_number = next(
            token
            for token in parsed["numeric_tokens"]
            if token["token"] == "1.224" and token["location"]["table_id"]
        )
        self.assertEqual(table_number["location"]["table_id"], "table-000")
        self.assertEqual(
            SAMPLE.read_text(encoding="utf-8")[
                table_number["location"]["offset_start"] : table_number["location"]["offset_end"]
            ],
            "1.224",
        )
        json.dumps(parsed)

    def test_pipeline_retains_s1_json_without_changing_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            output = root / "review.md"
            state = run_pipeline(SAMPLE, evidence, output)

        self.assertEqual(state.completed_stages[0], "S1 parse")
        self.assertEqual(state.parsed_paper["tables"][0]["id"], "table-000")
        self.assertIn("S1 parse inventory", state.review_markdown)

    def test_setext_headings_and_fenced_pipes_are_not_tables(self) -> None:
        markdown = """Title 2026
==========

```text
fake | table
--- | ---
```

Metric
------
Value is −1,234.5e-2%.
"""
        with tempfile.TemporaryDirectory() as directory:
            paper = Path(directory) / "paper.md"
            paper.write_text(markdown, encoding="utf-8")
            parsed = parse_markdown(paper)

        self.assertEqual([section["level"] for section in parsed["sections"]], [1, 2])
        self.assertEqual(parsed["tables"], [])
        token = next(item for item in parsed["numeric_tokens"] if "%" in item["token"])
        self.assertEqual(token["normalized"], "-1234.5e-2")


if __name__ == "__main__":
    unittest.main()
