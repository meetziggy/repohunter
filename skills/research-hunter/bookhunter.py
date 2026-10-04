#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

try:
    from bookhunter_providers import OpenLibraryProvider, ProjectGutenbergProvider
except Exception:
    OpenLibraryProvider=ProjectGutenbergProvider=None

CACHE_DIR=os.path.expanduser('~/.bookhunter/cache')
PROVIDERS=[]
try:
    if OpenLibraryProvider: PROVIDERS.append(OpenLibraryProvider())
    if ProjectGutenbergProvider: PROVIDERS.append(ProjectGutenbergProvider())
except Exception:
    pass

DENY=['z-lib.org','zlibrary','annas-archive','libgen','sci-hub']

def _k(q:str,limit:int): return hashlib.sha256(f'{q}|{limit}'.encode()).hexdigest()[:16]
def _ld(k:str):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        p=os.path.join(CACHE_DIR,f'{k}.json')
        if not os.path.exists(p): return None
        with open(p) as f: d=json.load(f)
        if time.time()-d.get('ts',0)>3600: return None
        return d.get('r')
    except Exception: return None
def _sv(k:str,r): 
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR,f'{k}.json'),'w') as f: json.dump({'ts':time.time(),'r':r},f)
    except Exception: pass

def _deny(u:str):
    if not u: return False
    ul=u.lower()
    return any(x in ul for x in DENY)

def search_books(q:str,limit:int=25,use_cache:bool=True):
    if not q.strip(): return []
    k=_k(q,limit)
    if use_cache:
        c=_ld(k); 
        if c is not None: return c
    merged=[]
    for p in PROVIDERS:
        try: merged.extend(p.search(q,limit=limit))
        except Exception: pass
    # dedup
    seen=set(); out=[]
    for r in merged:
        key=(r.title.lower().strip(), tuple(sorted(a.lower() for a in r.authors)), r.isbn or '')
        if key in seen: continue
        seen.add(key)
        r.availability=[a for a in r.availability if not _deny(a.get('url') or '')]
        out.append(r)
    out.sort(key=lambda x:x.score_legal, reverse=True)
    res=[asdict(x) for x in out[:limit]]
    _sv(k,res)
    return res

def find_by_isbn(i:str): 
    if not i: return []
    return search_books(f'isbn:{i}', limit=5)
