"""Tests for retrieval-grounded novelty & positioning (the --best layer core).

A fake arXiv search feed is injected exactly as the citation tests inject a
fetcher, so retrieval logic is exercised offline and deterministically: a
closely-related uncited paper becomes a grounded Question, while an already-cited
paper, a paper named by title, and a low-similarity hit stay silent. A network
failure degrades to no retrieval, never a crash.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from reviewer.novelty_positioning import check_novelty_positioning
from reviewer.parser import parse_markdown


PAPER = """# Sparse Attention for Efficient Language Modeling

## Abstract

We study sparse attention in transformer models for language modeling. Our novel
method improves the efficiency of attention over long input sequences. We build
on [2004.05150] for the long-context baseline.

## Method

The approach outperforms dense attention on long sequences.
"""

# Four retrieved hits: a relevant uncited one, an already-cited one, one the
# paper already names by title, and an unrelated one.
SEARCH_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models use recurrent networks.
    We propose the Transformer based solely on attention mechanisms for language
    modeling and sequence tasks.</summary>
    <published>2017-06-12T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2004.05150v2</id>
    <title>Longformer: The Long-Document Transformer</title>
    <summary>We introduce the Longformer with sparse attention for long language
    sequences and efficient transformer modeling.</summary>
    <published>2020-04-10T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Sparse Attention Language Modeling</title>
    <summary>Sparse attention for language modeling with efficient transformers.</summary>
    <published>2021-01-01T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1904.00002v1</id>
    <title>Protein Folding Structure Prediction with Graph Networks</title>
    <summary>We predict protein tertiary structure from amino acid graphs.</summary>
    <published>2019-04-02T00:00:00Z</published>
  </entry>
</feed>
"""


class NoveltyPositioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="ralphthon-novelty-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        (self.directory / "paper.md").write_text(PAPER, encoding="utf-8")
        self.parsed = parse_markdown(self.directory / "paper.md")
        self.cache = self.directory / "cache"

    def _run(self, feed: bytes = SEARCH_FEED):
        self.calls: list[str] = []

        def fetch(url: str) -> bytes:
            self.calls.append(url)
            return feed

        return check_novelty_positioning(self.parsed, cache_dir=self.cache, fetch=fetch)

    def test_query_is_built_from_title_and_abstract(self) -> None:
        result = self._run()
        self.assertIn("attention", result["query"])
        self.assertIn("sparse", result["query"])

    def test_related_uncited_paper_becomes_a_grounded_question(self) -> None:
        result = self._run()
        texts = [question["text"] for question in result["questions"]]
        self.assertTrue(any("Attention Is All You Need" in text for text in texts))
        self.assertTrue(any("arXiv:1706.03762" in text for text in texts))

    def test_already_cited_paper_is_not_questioned(self) -> None:
        result = self._run()
        self.assertFalse(any("2004.05150" in question["text"] for question in result["questions"]))
        longformer = next(trace for trace in result["traces"] if trace["id"] == "2004.05150")
        self.assertTrue(longformer["already_cited"])

    def test_paper_named_by_title_is_not_questioned(self) -> None:
        result = self._run()
        self.assertFalse(any("2101.00001" in question["text"] for question in result["questions"]))
        named = next(trace for trace in result["traces"] if trace["id"] == "2101.00001")
        self.assertTrue(named["mentioned_by_title"])

    def test_unrelated_paper_is_below_similarity_threshold(self) -> None:
        result = self._run()
        protein = next(trace for trace in result["traces"] if trace["id"] == "1904.00002")
        self.assertLess(protein["similarity"], 0.10)
        self.assertFalse(any("1904.00002" in question["text"] for question in result["questions"]))

    def test_cache_prevents_a_second_fetch(self) -> None:
        self._run()
        first_calls = len(self.calls)
        result = self._run()
        self.assertEqual(len(self.calls), 0)  # served from cache; fetch not called
        self.assertGreaterEqual(first_calls, 1)
        self.assertTrue(result["questions"])

    def test_network_failure_degrades_to_no_retrieval(self) -> None:
        def failing_fetch(url: str) -> bytes:
            raise TimeoutError("network down")

        result = check_novelty_positioning(self.parsed, cache_dir=self.cache, fetch=failing_fetch)
        self.assertEqual(result["retrieved"], [])
        self.assertEqual(result["questions"], [])


if __name__ == "__main__":
    unittest.main()
