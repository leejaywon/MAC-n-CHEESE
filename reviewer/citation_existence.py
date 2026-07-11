"""Cached, conservative existence checks for explicitly identified citations.

Only citations carrying an arXiv, Semantic Scholar, or DOI identifier are
machine-checkable here.  Network failures become ``unavailable`` traces, never
findings: absence of a response is not evidence that a cited work is absent.
"""

from __future__ import annotations

import json
import re
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ARXIV_RE = re.compile(
    r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
    re.I,
)
# Peer papers routinely cite a bare arXiv id in brackets, e.g. "[2305.14567]",
# with no "arXiv:" prefix. The month digits (01-12) gate this so an arbitrary
# "[1234.5678]" is not misread as a citation. A not-found lookup on such an id
# (e.g. a fabricated "[1901.99999]") is a real, checkable defect on any paper.
BRACKET_ARXIV_RE = re.compile(
    r"\[(?:arxiv\s*:\s*)?(?P<id>\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?)\]",
    re.I,
)
S2_URL_RE = re.compile(
    r"semanticscholar\.org/paper/(?:[^\s/)]+/)?(?P<id>[0-9a-f]{40}|CorpusId:\d+)", re.I
)
CORPUS_RE = re.compile(r"\bCorpusId\s*:\s*(?P<id>\d+)\b", re.I)
DOI_RE = re.compile(
    r"(?:doi\s*:\s*|doi\.org/)(?P<id>10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
GENERIC_LINK_LABELS = {"arxiv", "doi", "link", "paper", "pdf", "semantic scholar", "source"}
Fetcher = Callable[[str], bytes]


def _paper_lines(parsed_paper: dict[str, Any]) -> list[str]:
    return Path(str(parsed_paper["source_path"])).read_text(encoding="utf-8").splitlines()


def _expected_title(line: str, identifier: str) -> str | None:
    for match in MARKDOWN_LINK_RE.finditer(line):
        if identifier.casefold() not in match.group(2).casefold():
            continue
        label = match.group(1).strip()
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", label)
        if label.casefold() not in GENERIC_LINK_LABELS and len(words) >= 3:
            return label
    return None


def _normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.findall(r"[\w]+", normalized))


def _titles_match(expected: str, observed: str) -> bool:
    expected_tokens = _normalize_title(expected).split()
    observed_tokens = _normalize_title(observed).split()
    if not expected_tokens or not observed_tokens:
        return False
    if expected_tokens == observed_tokens:
        return True
    overlap = len(set(expected_tokens) & set(observed_tokens))
    return overlap / max(len(set(expected_tokens)), len(set(observed_tokens))) >= 0.9


def _default_fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ralphthon-review-agent/1.0"})
    with urlopen(request, timeout=8) as response:
        return response.read()


def _arxiv_lookup(identifier: str, fetch: Fetcher) -> dict[str, Any]:
    bare_id = re.sub(r"v\d+$", "", identifier, flags=re.I)
    url = "https://export.arxiv.org/api/query?id_list=" + quote(bare_id, safe="./")
    payload = fetch(url)
    root = ElementTree.fromstring(payload)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", namespace)
    if not entries:
        return {"status": "not-found", "title": None, "url": url}
    title = entries[0].findtext("atom:title", default="", namespaces=namespace)
    return {"status": "verified", "title": " ".join(title.split()), "url": url}


def _s2_lookup(identifier: str, fetch: Fetcher) -> dict[str, Any]:
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/"
        + quote(identifier, safe="")
        + "?fields=title,externalIds,url"
    )
    try:
        data = json.loads(fetch(url).decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            error.close()
            return {"status": "not-found", "title": None, "url": url}
        raise
    title = data.get("title") if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip():
        return {"status": "not-found", "title": None, "url": url}
    return {"status": "verified", "title": " ".join(title.split()), "url": url}


def _cache_path(cache_dir: Path, provider: str, identifier: str) -> Path:
    key = sha256(f"{provider}:{identifier}".encode()).hexdigest()
    return cache_dir / f"{key}.json"


def _lookup(
    provider: str, identifier: str, cache_dir: Path, fetch: Fetcher
) -> tuple[dict[str, Any], bool]:
    path = _cache_path(cache_dir, provider, identifier)
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("schema_version") == 1 and cached.get("status") in {"verified", "not-found"}:
                return cached, True
        except (OSError, ValueError, TypeError):
            pass

    try:
        result = (
            _arxiv_lookup(identifier, fetch)
            if provider == "arxiv"
            else _s2_lookup(identifier, fetch)
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ElementTree.ParseError) as error:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "title": None,
            "error": type(error).__name__,
        }, False

    cached = {"schema_version": 1, "provider": provider, "identifier": identifier, **result}
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached, sort_keys=True) + "\n", encoding="utf-8")
    return cached, False


def _citations(parsed_paper: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(_paper_lines(parsed_paper), start=1):
        matches: list[tuple[str, str, str]] = []
        matches.extend(("arxiv", match.group("id"), match.group(0)) for match in ARXIV_RE.finditer(line))
        matches.extend(("arxiv", match.group("id"), match.group(0)) for match in BRACKET_ARXIV_RE.finditer(line))
        matches.extend(("s2", match.group("id"), match.group(0)) for match in S2_URL_RE.finditer(line))
        matches.extend(("s2", f"CorpusId:{match.group('id')}", match.group(0)) for match in CORPUS_RE.finditer(line))
        matches.extend(
            ("s2", f"DOI:{match.group('id').rstrip('.,;)')}", match.group(0).rstrip(")"))
            for match in DOI_RE.finditer(line)
        )
        for provider, identifier, source_token in matches:
            normalized_id = re.sub(r"v\d+$", "", identifier, flags=re.I) if provider == "arxiv" else identifier
            key = provider, normalized_id.casefold()
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                {
                    "provider": provider,
                    "identifier": normalized_id,
                    "expected_title": _expected_title(line, source_token),
                    "location": {"line": line_number},
                }
            )
    return citations


def check_citation_existence(
    parsed_paper: dict[str, Any],
    cache_dir: Path | None = None,
    fetch: Fetcher | None = None,
) -> dict[str, Any]:
    """Verify explicit persistent identifiers with timeout-safe cached APIs."""

    cache_dir = cache_dir or Path(__file__).resolve().parents[1] / ".cache" / "citations"
    fetch = fetch or _default_fetch
    traces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for citation in _citations(parsed_paper):
        result, cache_hit = _lookup(
            citation["provider"], citation["identifier"], cache_dir, fetch
        )
        trace = {**citation, **result, "cache_hit": cache_hit}
        traces.append(trace)
        evidence_path = result.get("url", f"{citation['provider']} API unavailable")
        if result["status"] == "not-found":
            findings.append(
                {
                    "check": "citation-existence",
                    "severity": "error",
                    "location": citation["location"],
                    "expected": f"a published record for {citation['identifier']}",
                    "observed": "the authoritative identifier lookup returned no record",
                    "evidence_path": evidence_path,
                }
            )
        elif (
            result["status"] == "verified"
            and citation["expected_title"]
            and not _titles_match(citation["expected_title"], result["title"])
        ):
            findings.append(
                {
                    "check": "citation-existence",
                    "severity": "error",
                    "location": citation["location"],
                    "expected": f"API title matching '{citation['expected_title']}'",
                    "observed": f"API title is '{result['title']}'",
                    "evidence_path": evidence_path,
                }
            )
    return {"check": "citation-existence", "traces": traces, "findings": findings}
