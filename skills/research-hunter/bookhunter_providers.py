#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.parse, urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

UA = "BookHunter/0.1"
TIMEOUT = 15

def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace'))
    except Exception:
        return None

def _get_text(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception:
        return None

def _norm_isbn(s: str) -> Optional[str]:
    m = re.findall(r'(\d{9,13})', str(s))
    for c in m:
        if len(c) in (10,13): return c
    return None

@dataclass
class BookResult:
    title: str
    authors: List[str]
    isbn: Optional[str]
    year: Optional[str]
    language: Optional[str]
    cover_url: Optional[str]
    formats: List[str]
    availability: List[Dict[str,str]]
    sources: List[Dict[str,str]]
    score_legal: int = 90

class OpenLibraryProvider:
    name = 'openlibrary'
    def search(self, q: str, limit: int=20):
        res = []
        url = f'https://openlibrary.org/search.json?q={urllib.parse.quote_plus(q)}&limit={limit}'
        d = _get_json(url)
        if not d: return res
        for doc in d.get('docs', [])[:limit]:
            isbn = _norm_isbn((doc.get('isbn') or [None])[0]) if doc.get('isbn') else None
            authors = doc.get('author_name') or []
            year = str(doc.get('first_publish_year')) if doc.get('first_publish_year') else None
            cover = f'https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg' if isbn else None
            avail = []
            if isbn:
                avail.append({'type':'metadata','label':'Open Library (ISBN)','url':f'https://openlibrary.org/isbn/{isbn}'})
            wk = doc.get('key')
            if wk:
                avail.append({'type':'metadata','label':'Open Library (Work)','url':f'https://openlibrary.org{wk}'})
            res.append(BookResult(title=doc.get('title') or '', authors=authors if isinstance(authors,list) else [str(authors)], isbn=isbn, year=year, language=(doc.get('language') or [None])[0], cover_url=cover, formats=[], availability=avail, sources=[{'provider':self.name,'url':url}], score_legal=95))
        return res

class ProjectGutenbergProvider:
    name='gutenberg'
    def search(self, q:str, limit:int=20):
        res=[]
        url=f'https://www.gutenberg.org/ebooks/search/?query={urllib.parse.quote_plus(q)}'
        html=_get_text(url)
        if not html: return res
        for m in re.finditer(r'<li class="booklink">.*?</li>', html, re.DOTALL):
            b=m.group(0)
            tm=re.search(r'<span class="title">([^<]+)</span>', b)
            am=re.search(r'<span class="subtitle">([^<]+)</span>', b)
            lm=re.search(r'href="/ebooks/(\d+)"', b)
            if not tm or not lm: continue
            eid=lm.group(1)
            res.append(BookResult(title=tm.group(1).strip(), authors=[am.group(1).strip()] if am else [], isbn=None, year=None, language=None, cover_url=None, formats=['epub','html','txt'], availability=[{'type':'free_legal','label':'Project Gutenberg','url':f'https://www.gutenberg.org/ebooks/{eid}'}], sources=[{'provider':self.name,'url':url}], score_legal=100))
            if len(res)>=limit: break
        return res
