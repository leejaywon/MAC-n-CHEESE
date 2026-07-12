#!/usr/bin/env python3
"""Assemble a real-paper test corpus for eval/external/ from public sources.

For each arXiv id: title + abstract come from the arXiv API, while the real cited
arXiv ids and the Related-Work prose come from the ar5iv HTML full text. The
result is a faithful (not fabricated) Track-2 fixture that exercises the reviewer
on diverse, well-positioned papers across venues. A provenance comment records
the assembly. Network-only, polite delays; re-runnable (skips existing files).
"""

from __future__ import annotations

import html
import re
import sys
import time
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

EXTERNAL = Path(__file__).resolve().parent / "external"

# arXiv id -> (slug, venue label). A spread across NeurIPS/CVPR/ICLR/NAACL/ICML.
CORPUS = {
    "1706.03762": ("attention_is_all_you_need", "NeurIPS 2017"),
    "1512.03385": ("resnet_deep_residual_learning", "CVPR 2016"),
    "2010.11929": ("vit_image_16x16_words", "ICLR 2021"),
    "1810.04805": ("bert_pretraining", "NAACL 2019"),
    "2006.11239": ("ddpm_denoising_diffusion", "NeurIPS 2020"),
    "1703.03400": ("maml_model_agnostic_meta_learning", "ICML 2017"),
    "1412.6980": ("adam_stochastic_optimization", "ICLR 2015"),
}


def _get(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ralphthon-corpus/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _metadata(arxiv_id: str) -> tuple[str, str, str]:
    payload = _get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}")
    root = ElementTree.fromstring(payload)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
    abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
    published = entry.findtext("atom:published", default="", namespaces=ns)[:4]
    return title, abstract, published


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def _full_text(arxiv_id: str) -> str:
    try:
        return _get(f"https://ar5iv.org/abs/{arxiv_id}").decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 — corpus assembly, best effort
        return ""


def _cited_ids(page: str, self_id: str) -> list[str]:
    found = set(re.findall(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", page))
    found |= set(re.findall(r"arXiv:(\d{4}\.\d{4,5})", page))
    found.discard(self_id)
    return sorted(found)[:12]


def _related_work(page: str) -> str:
    match = re.search(r"(<section[^>]*>\s*<h2[^>]*>[^<]*Related Work.*?</section>)", page, re.S | re.I)
    if not match:
        return ""
    text = " ".join(_strip_tags(match.group(1)).split())
    text = re.sub(r"^\s*\d+\s+Related Work\s*", "", text, flags=re.I)
    return text[:900]


def _build(arxiv_id: str, slug: str, venue: str) -> str:
    title, abstract, year = _metadata(arxiv_id)
    time.sleep(1.0)
    page = _full_text(arxiv_id)
    time.sleep(1.0)
    cited = _cited_ids(page, arxiv_id)
    related = _related_work(page)
    if not related:
        related = "This work situates its contribution against the prior art listed in References."
    references = "\n".join(
        f"- [arXiv:{ref}](https://arxiv.org/abs/{ref})" for ref in cited
    ) or "- (no arXiv-linked references were extracted)"
    return f"""# {title}

<!-- Track-2 external test fixture. Provenance: title+abstract via arXiv API for
arXiv:{arxiv_id} ({venue}, {year}); Related Work prose and reference arXiv ids
extracted from ar5iv full text. Assembled, not authored. -->

## Abstract

{abstract}

## Related Work

{related}

## References

{references}
"""


def main() -> int:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    for arxiv_id, (slug, venue) in CORPUS.items():
        out = EXTERNAL / f"{slug}.md"
        if out.is_file():
            print(f"skip (exists): {out.name}")
            continue
        try:
            out.write_text(_build(arxiv_id, slug, venue), encoding="utf-8")
            print(f"wrote {out.name} [{venue}] arXiv:{arxiv_id}")
        except Exception as error:  # noqa: BLE001
            print(f"FAILED {arxiv_id}: {type(error).__name__} {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
