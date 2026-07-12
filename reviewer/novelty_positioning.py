"""Retrieval-grounded novelty & positioning — the ``--best`` judgment layer's
model-free core: compare the paper against the ACTUAL literature.

Deterministic positioning (:mod:`reviewer.positioning`) only sees whether a paper
cites anyone. This module does what an ICML reviewer actually does when weighing
originality: it retrieves topically-close prior work from arXiv and checks whether
the submission engages with it. A closely-related paper the submission never
cites becomes a grounded Question — "how does the contribution differ from <real
paper>?" — anchored to a real arXiv id, never an accusation (false-positive rule).

Network use mirrors :mod:`reviewer.citation_existence`: an injectable ``fetch``,
an on-disk cache, and any failure degrades to "no retrieved work" rather than a
finding. It runs only in ``--best`` mode, AFTER the deterministic audit is frozen,
so it can never perturb the audit identity or the S4 verdict-label digest. An
optional model critique (multi-persona, grounded, calibration-only-lowers) layers
on top when an API key is present; without it these retrieval-grounded Questions
stand alone.
"""

from __future__ import annotations

import http.client
import json
import re
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .citation_existence import ARXIV_RE, BRACKET_ARXIV_RE


Fetcher = Callable[[str], bytes]

# Deliberately small, generic stop list: enough to keep query terms and
# similarity focused on content words without importing an NLP dependency.
STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in into is it its of on or that the
    their this to via we with our using use used based toward towards over under
    between across can could may might will would than then them they these those
    also more most much such other another paper method approach model results
    show shows shown propose proposed present presented new novel study work
    """.split()
)

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+/-]{1,}")
ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(?P<id>[^\s<]+)", re.I)
# The official arXiv DOI form, e.g. "doi:10.48550/arXiv.2004.05150" — a very
# common way to cite an arXiv work that the bare arXiv patterns miss, causing a
# false "not cited" accusation. It maps directly onto the arXiv id.
ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.(?P<id>\d{4}\.\d{4,5})", re.I)


def _default_fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ralphthon-review-agent/1.0"})
    with urlopen(request, timeout=8) as response:
        return response.read()


def _normalize_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [
        token
        for token in WORD_RE.findall(normalized)
        if token not in STOPWORDS and len(token) > 2
    ]


def _paper_text(parsed_paper: dict[str, Any]) -> str:
    return Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8")


def _title(parsed_paper: dict[str, Any]) -> str:
    sections = parsed_paper.get("sections", [])
    headed = [section for section in sections if section.get("heading_line")]
    if headed:
        top_level = min(section["level"] for section in headed)
        for section in headed:
            if section["level"] == top_level:
                return str(section.get("title", ""))
    return ""


def _abstract(parsed_paper: dict[str, Any]) -> str:
    for section in parsed_paper.get("sections", []):
        if "abstract" in str(section.get("title", "")).casefold():
            return str(section.get("content", ""))
    return ""


def _topic_terms(parsed_paper: dict[str, Any], limit: int = 8) -> list[str]:
    """Salient query terms: title tokens first, then the most frequent abstract
    content words. Order-preserving dedupe keeps the title's framing dominant."""

    title_tokens = _normalize_tokens(_title(parsed_paper))
    abstract_tokens = _normalize_tokens(_abstract(parsed_paper))
    frequency: dict[str, int] = {}
    for token in abstract_tokens:
        frequency[token] = frequency.get(token, 0) + 1
    ranked_abstract = sorted(frequency, key=lambda token: (-frequency[token], token))
    ordered: list[str] = []
    for token in [*title_tokens, *ranked_abstract]:
        if token not in ordered:
            ordered.append(token)
    return ordered[:limit]


def _cited_arxiv_ids(parsed_paper: dict[str, Any]) -> set[str]:
    text = _paper_text(parsed_paper)
    ids: set[str] = set()
    for pattern in (ARXIV_RE, BRACKET_ARXIV_RE, ARXIV_DOI_RE):
        for match in pattern.finditer(text):
            ids.add(re.sub(r"v\d+$", "", match.group("id"), flags=re.I).casefold())
    return ids


def _cache_path(cache_dir: Path, query: str, max_results: int) -> Path:
    key = sha256(f"arxiv-search:{max_results}:{query}".encode()).hexdigest()
    return cache_dir / f"{key}.json"


def _parse_search_feed(payload: bytes) -> list[dict[str, str]]:
    root = ElementTree.fromstring(payload)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    entries: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", namespace):
        raw_id = entry.findtext("atom:id", default="", namespaces=namespace)
        match = ARXIV_ABS_RE.search(raw_id)
        identifier = re.sub(r"v\d+$", "", match.group("id"), flags=re.I) if match else ""
        title = " ".join(entry.findtext("atom:title", default="", namespaces=namespace).split())
        summary = " ".join(entry.findtext("atom:summary", default="", namespaces=namespace).split())
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        if identifier and title:
            entries.append(
                {"id": identifier, "title": title, "summary": summary, "published": published}
            )
    return entries


def _retrieve_arxiv(
    query: str, cache_dir: Path, fetch: Fetcher, max_results: int
) -> list[dict[str, str]]:
    path = _cache_path(cache_dir, query, max_results)
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("schema_version") == 1 and isinstance(cached.get("entries"), list):
                return cached["entries"]
        except (OSError, ValueError, TypeError):
            pass
    # OR-group the terms: an AND of many salient terms is too restrictive and
    # often returns nothing, so retrieve a broad relevance-ranked pool and let the
    # Jaccard threshold below do the precision filtering.
    url = "https://export.arxiv.org/api/query?" + urlencode(
        {"search_query": f"all:({query})", "start": 0, "max_results": max_results, "sortBy": "relevance"}
    )
    try:
        entries = _parse_search_feed(fetch(url))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
        ValueError,
        TypeError,
        ElementTree.ParseError,
    ):
        # Any retrieval failure (including a truncated read, which is an
        # http.client.HTTPException and not an OSError) degrades to no prior work.
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "query": query, "entries": entries}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return entries


def _similarity(topic_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not topic_tokens or not candidate_tokens:
        return 0.0
    intersection = topic_tokens & candidate_tokens
    union = topic_tokens | candidate_tokens
    return len(intersection) / len(union)


def check_novelty_positioning(
    parsed_paper: dict[str, Any],
    cache_dir: Path | None = None,
    fetch: Fetcher | None = None,
    max_results: int = 10,
    min_similarity: float = 0.10,
    max_questions: int = 3,
) -> dict[str, Any]:
    """Retrieve real prior work and surface closely-related papers left uncited.

    Returns retrieval traces plus grounded Questions. Every Question names a real
    arXiv id and title, so it is checkable; ambiguity is resolved toward silence.
    """

    cache_dir = cache_dir or Path(__file__).resolve().parents[1] / ".cache" / "novelty"
    fetch = fetch or _default_fetch

    topic_terms = _topic_terms(parsed_paper)
    query = " OR ".join(topic_terms)
    if not query:
        return {"check": "novelty-positioning", "query": "", "retrieved": [], "traces": [], "questions": []}

    entries = _retrieve_arxiv(query, cache_dir, fetch, max_results)
    cited_ids = _cited_arxiv_ids(parsed_paper)
    paper_tokens = set(_normalize_tokens(_paper_text(parsed_paper)))
    topic_token_set = set(topic_terms) | set(_normalize_tokens(_abstract(parsed_paper)))

    traces: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        candidate_tokens = set(_normalize_tokens(f"{entry['title']} {entry['summary']}"))
        similarity = _similarity(topic_token_set, candidate_tokens)
        already_cited = entry["id"].casefold() in cited_ids
        title_tokens = set(_normalize_tokens(entry["title"]))
        # "Already discussed by title": the paper names this work even without a
        # machine-readable id, so it is engaged with — do not ask about it.
        mentioned = bool(title_tokens) and len(title_tokens & paper_tokens) / len(title_tokens) >= 0.8
        trace = {
            "id": entry["id"],
            "title": entry["title"],
            "similarity": round(similarity, 4),
            "already_cited": already_cited,
            "mentioned_by_title": mentioned,
        }
        traces.append(trace)
        if similarity >= min_similarity and not already_cited and not mentioned:
            candidates.append({**trace, "published": entry.get("published", "")})

    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    questions: list[dict[str, Any]] = []
    for candidate in candidates[:max_questions]:
        questions.append(
            {
                "section": "Questions for the Authors",
                "stance": "question",
                "text": (
                    f"Closely related prior work \"{candidate['title']}\" "
                    f"(arXiv:{candidate['id']}) is not cited or discussed. How does the "
                    f"contribution differ from it, and does the positioning still hold?"
                ),
                "references": [f"arxiv:{candidate['id']}"],
                "similarity": candidate["similarity"],
            }
        )

    return {
        "check": "novelty-positioning",
        "query": query,
        "retrieved": entries,
        "traces": traces,
        "questions": questions,
    }
