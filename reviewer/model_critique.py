"""OpenAI-compatible chat client and the prior-art query scout."""

from __future__ import annotations

import json
import os
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://api.openai.com/v1"

Client = Callable[[list[dict[str, str]]], str]


def _resolve_model(model: str | None) -> str:
    """Resolve the model name, or fail loudly — never silently downgrade.

    An explicit ``model`` wins; otherwise ``OPENAI_MODEL`` must be set. There is
    deliberately no built-in default: a missing model on a model-backed path is
    a configuration error.
    """

    resolved = (model or os.environ.get("OPENAI_MODEL") or "").strip()
    if not resolved:
        raise RuntimeError(
            "OPENAI_MODEL is not set; refusing to guess a model. Set OPENAI_MODEL "
            "(e.g. gpt-5.6-sol), or run with --deterministic to skip model calls."
        )
    return resolved


def _default_client(
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: int,
    *,
    json_mode: bool = True,
) -> Client:
    def call(messages: list[dict[str, str]]) -> str:
        params: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "seed": 7,
            "max_tokens": max_tokens,
        }
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        effort = os.environ.get("REVIEWER_COMMITTEE_EFFORT", "").strip().lower()
        if effort:
            # Reasoning models honor this; a model that rejects it returns 400
            # and the retry loop below drops it automatically.
            params["reasoning_effort"] = effort
        for _ in range(len(params)):
            request = Request(
                base_url.rstrip("/") + "/chat/completions",
                data=json.dumps(params).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except HTTPError as error:
                if error.code != 400:
                    raise
                try:
                    info = json.loads(error.read().decode("utf-8", "replace")).get("error", {})
                except ValueError:
                    raise error
                param = info.get("param")
                if info.get("code") not in ("unsupported_parameter", "unsupported_value") or param not in params:
                    raise
                if param == "max_tokens":
                    params["max_completion_tokens"] = params.pop("max_tokens")
                else:
                    params.pop(param)
        raise URLError("model rejected the request parameters")

    return call


_QUERY_SCOUT_SYSTEM = (
    "You are a literature scout for a paper reviewer. "
    "Read the submission's title and prioritized text, "
    "then output the arXiv searches a reviewer would run "
    "to check whether its core contribution already exists. "
    'Return STRICT JSON {"queries": ["...", ...]} with 3 to 5 queries, '
    "each 3-8 content words naming the specific idea, method, task, or setting — "
    "never title buzzwords, boolean operators, or quotes. No prose."
)


def generate_search_queries(
    *,
    title: str,
    abstract: str,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 30,
    client: Client | None = None,
    max_queries: int = 5,
) -> list[str]:
    """Ask the model for reviewer-style prior-art queries (by idea, not title tokens).

    A failure (no key, network, malformed JSON) returns an empty list
    so the caller degrades to the deterministic lexical fallback rather than blocking the review.
    """

    base_url = base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    model = model or os.environ.get("OPENAI_MODEL")
    if not model:
        return []  # no model configured: degrade to the deterministic lexical query
    call = client or _default_client(base_url, api_key, model, 512, timeout)
    payload = {"title": " ".join(title.split())[:300], "prioritized_text": abstract[:2500]}
    try:
        raw = call(
            [
                {"role": "system", "content": _QUERY_SCOUT_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        data = json.loads(raw)
        queries = [" ".join(str(item).split()) for item in data.get("queries", []) if str(item).strip()]
        return [query for query in queries if 2 <= len(query.split()) <= 12][:max_queries]
    except Exception:  # noqa: BLE001 - degrade to the lexical fallback
        return []
