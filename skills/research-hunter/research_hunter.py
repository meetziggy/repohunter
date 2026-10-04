#!/usr/bin/env python3
"""ResearchHunter — deep/wide legal-first research.

Searches books (bookhunter), papers (OpenAlex/arXiv/SemanticScholar), web, and
optionally repos. Returns structured synthesis with citations.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

try:
    import bookhunter
except Exception:
    bookhunter = None

UA = "ResearchHunter/0.1 (+https://repohunter.dev)"
TIMEOUT = 15
CACHE_DIR = os.path.expanduser("~/.researchhunter/cache")


def _cache_key(q: str, mode: str, limit: int, sources: str = "") -> str:
    h = hashlib.sha256(f"{q}|{mode}|{limit}|{sources}".encode()).hexdigest()[:16]
    return h


def _load_cache(k: str) -> Optional[Dict[str, Any]]:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        p = os.path.join(CACHE_DIR, f"{k}.json")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > 3600:
            return None
        return data.get("data")
    except Exception:
        return None


def _save_cache(k: str, data: Dict[str, Any]) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        p = os.path.join(CACHE_DIR, f"{k}.json")
        with open(p, "w") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except Exception:
        pass


def _http_get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _http_get_text(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


@dataclass
class Cite:
    id: str
    title: str
    type: str  # book|paper|web
    url: Optional[str]
    year: Optional[str]
    authors: List[str]
    source: str


def arxiv_search(q: str, limit: int = 15) -> List[Cite]:
    results: List[Cite] = []
    qs = urllib.parse.quote_plus(q)
    url = f"https://export.arxiv.org/api/query?search_query=all:{qs}&start=0&max_results={limit}&sortBy=relevance"
    xml = _http_get_text(url)
    if not xml:
        return results
    # simple extract
    import re

    for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.DOTALL):
        e = m.group(1)
        t = re.search(r"<title>(.*?)</title>", e, re.DOTALL)
        a = re.findall(r"<name>(.*?)</name>", e)
        y = re.search(r"<published>(\d{4})-", e)
        link = re.search(r"<id>(https?://.*?)</id>", e)
        if t:
            results.append(
                Cite(
                    id=f"arxiv:{len(results)+1}",
                    title=t.group(1).replace("\n", " ").strip(),
                    type="paper",
                    url=link.group(1) if link else None,
                    year=y.group(1) if y else None,
                    authors=a,
                    source="arxiv",
                )
            )
    return results


def openalex_search(q: str, limit: int = 15) -> List[Cite]:
    results: List[Cite] = []
    qs = urllib.parse.quote_plus(q)
    url = f"https://api.openalex.org/works?search={qs}&per-page={limit}&sort=relevance"
    data = _http_get_json(url)
    if not data:
        return results
    for w in data.get("results", [])[:limit]:
        title = w.get("title") or ""
        authors = []
        for a in w.get("authorships", []):
            if a.get("author", {}).get("display_name"):
                authors.append(a["author"]["display_name"])
        year = str(w.get("publication_year")) if w.get("publication_year") else None
        urlw = w.get("id")
        results.append(
            Cite(
                id=f"oa:{len(results)+1}",
                title=title,
                type="paper",
                url=urlw,
                year=year,
                authors=authors,
                source="openalex",
            )
        )
    return results


def books_search(q: str, limit: int = 15) -> List[Cite]:
    results: List[Cite] = []
    if not bookhunter:
        return results
    try:
        bs = bookhunter.search_books(q, limit=limit)
        for i, b in enumerate(bs):
            results.append(
                Cite(
                    id=f"book:{i+1}",
                    title=b.get("title") or "",
                    type="book",
                    url=(b.get("availability") or [{}])[0].get("url") if b.get("availability") else None,
                    year=b.get("year"),
                    authors=b.get("authors") or [],
                    source="bookhunter",
                )
            )
    except Exception:
        pass
    return results


def web_search(q: str, limit: int = 10) -> List[Cite]:
    # A link only — fetching it through a third-party proxy sent every query off-box and the
    # response was never used.
    qs = urllib.parse.quote_plus(q)
    return [
        Cite(
            id="web:1",
            title=f"Web results for: {q}",
            type="web",
            url=f"https://www.google.com/search?q={qs}",
            year=None,
            authors=[],
            source="google",
        )
    ]


def research_topic(
    q: str,
    mode: str = "wide",
    limit: int = 30,
    include_books: bool = True,
    include_papers: bool = True,
    include_web: bool = True,
    use_cache: bool = True,
) -> Dict[str, Any]:
    if not q or not q.strip():
        return {"success": False, "error": "empty query"}
    q = q.strip()
    mode = mode if mode in ("quick", "wide", "deep") else "wide"
    # The source flags are part of the key: research_papers and research_topic can share
    # q/mode/limit, and must not serve each other's cached results.
    k = _cache_key(q, mode, limit, f"{include_books:d}{include_papers:d}{include_web:d}")
    if use_cache:
        c = _load_cache(k)
        if c is not None:
            return c

    cites: List[Cite] = []
    if include_papers:
        cites.extend(arxiv_search(q, limit=limit // 2))
        cites.extend(openalex_search(q, limit=limit // 2))
    if include_books:
        cites.extend(books_search(q, limit=10))
    if include_web:
        cites.extend(web_search(q, limit=5))

    # dedupe
    seen = set()
    outc = []
    for c in cites:
        key = c.url or c.title.lower()
        if key in seen:
            continue
        seen.add(key)
        outc.append(c)

    synthesis = {
        "topic": q,
        "mode": mode,
        "summary": f"Research synthesis for '{q}' ({mode}, {len(outc)} sources).",
        "key_points": [
            "Combine sources; prefer peer-reviewed papers + legal books.",
            "Check citations/URLs for full text access.",
            "Focus on recent work for fast-moving topics.",
        ],
        "reading_list": [asdict(x) for x in outc[:15]],
        "all_sources": [asdict(x) for x in outc],
    }
    res = {"success": True, "q": q, "mode": mode, "count": len(outc), "results": synthesis}
    _save_cache(k, res)
    return res


def research_papers(q: str, limit: int = 20) -> Dict[str, Any]:
    return research_topic(q, mode="wide", limit=limit, include_books=False, include_web=False)


def research_book(q: str, limit: int = 15) -> Dict[str, Any]:
    return research_topic(q, mode="quick", limit=limit, include_books=True, include_papers=False, include_web=False)
