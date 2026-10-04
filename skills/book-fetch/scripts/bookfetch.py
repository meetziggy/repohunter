#!/usr/bin/env python3
"""BookFetch — get any book, for free, from anywhere.

Legal-first, then 'gritty'. Stdlib only (Python 3.8+) + optional ebooklib/pdfminer for text extraction.

Sources, in order:
  1. OpenLibrary        — public-domain IA scans + lending links
  2. Standard Ebooks    — high-quality free editions
  3. Anna's Archive     — universal mirror, no login (gritty)
  4. LibGen / Z-Lib     — classic mirrors (gritty fallback)

Usage:
  python3 bookfetch.py "Pride and Prejudice"
  python3 bookfetch.py "The Pragmatic Programmer" --author Hunt
  python3 bookfetch.py "9780201633610" --isbn --download
  python3 bookfetch.py "Pride and Prejudice" --download --extract --out ./books
"""
from __future__ import annotations
import argparse
import json
import os
import re
import socket
import ssl
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# Optional dependencies for text extraction
try:
    from ebooklib import epub
    from ebooklib import ITEM_DOCUMENT, ITEM_NAVIGATION
    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

UA = "BookFetch/1.0"
TIMEOUT = 30
MAX_BYTES = 200 * 1024 * 1024


# ─── Text Extraction ────────────────────────────────────────────────────────────

def extract_epub_text(path: str) -> Optional[str]:
    """Extract text content from an EPUB file."""
    if not HAS_EPUB:
        return None
    try:
        book = epub.read_epub(path)
        parts = []
        for item in book.get_items():
            # Type 0 = content documents (xhtml/html pages)
            # ITEM_DOCUMENT = 9 = navigation document
            if item.get_type() in (0, ITEM_DOCUMENT):
                content = item.get_content()
                if content:
                    # Strip HTML tags
                    text = re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="ignore"))
                    text = re.sub(r"\s+", " ", text).strip()
                    if text and len(text) > 50:  # Skip tiny fragments
                        parts.append(text)
        return "\n\n".join(parts)
    except Exception as e:
        print(f"  EPUB extraction error: {e}", file=sys.stderr)
        return None


def extract_pdf_text(path: str) -> Optional[str]:
    """Extract text content from a PDF file."""
    if not HAS_PDF:
        return None
    try:
        return pdf_extract_text(path)
    except Exception as e:
        print(f"  PDF extraction error: {e}", file=sys.stderr)
        return None


def extract_book_text(path: str) -> Optional[str]:
    """Auto-detect format and extract text."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        return extract_epub_text(path)
    elif ext == ".pdf":
        return extract_pdf_text(path)
    elif ext in (".txt", ".md"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None
    return None


def chunk_text(text: str, chunk_size: int = 4000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks for LLM/embedding processing."""
    if not text:
        return []
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks

# Mirror networks. Order matters: first host that resolves wins.
AA_HOSTS = ["annas-archive.org", "a.a", "annas-archive.se"]
LG_HOSTS = ["libgen.rs", "libgen.lol", "mirror.libgen.dev", "libgen.rs.ingra.com", "libgen.is", "libgen.pw", "libgen.li"]
ZL_HOSTS = ["z-library.org", "zlibrary.to", "z-lib.org", "zlib.russia.sh", "z-lib.io", "zlibrary.ai", "zlibrary.ru"]

AA_API_HOSTS = ["api.annas-archive.se", "api.annas-archive.org", "annas-archive.org"]


# SSL context for problematic sites
SSL_NO_VERIFY = ssl.create_default_context()
SSL_NO_VERIFY.check_hostname = False
SSL_NO_VERIFY.verify_mode = ssl.CERT_NONE

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
}


def _resolve(hosts: List[str]) -> Optional[str]:
    for h in hosts:
        try:
            socket.gethostbyname(h)
            return h
        except Exception:
            continue
    return None


def _fetch(url: str, headers: Optional[Dict] = None, use_ssl_no_verify: bool = False, timeout: Optional[int] = None) -> Optional[bytes]:
    hdrs = dict(headers or {})
    if "User-Agent" not in hdrs:
        hdrs["User-Agent"] = UA
    if "Accept" not in hdrs:
        hdrs["Accept"] = "text/html,application/json;q=0.9,*/*;q=0.8"
    req = urllib.request.Request(url, headers=hdrs)
    try:
        context = SSL_NO_VERIFY if use_ssl_no_verify else None
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT, context=context) as r:
            data = r.read(MAX_BYTES)
        return data
    except Exception:
        return None


def _get_json(url: str, timeout: Optional[int] = None) -> Optional[Any]:
    d = _fetch(url, headers=JSON_HEADERS, timeout=timeout)
    if not d:
        return None
    try:
        return json.loads(d.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _get_text(url: str, use_ssl_no_verify: bool = False, timeout: Optional[int] = None) -> Optional[str]:
    d = _fetch(url, headers=BROWSER_HEADERS, use_ssl_no_verify=use_ssl_no_verify, timeout=timeout)
    return d.decode("utf-8", errors="replace") if d else None


def _norm_isbn(s: str) -> Optional[str]:
    for m in re.findall(r"\d{9,13}", str(s).replace("-", "")):
        if len(m) in (10, 13):
            return m
    return None


# ---------------- OpenLibrary / Internet Archive ----------------

def ol_search(title: str, author: Optional[str], isbn: Optional[str], limit: int = 5) -> List[Dict]:
    q = f'title:"{title}"'
    if author:
        q += f' author:"{author}"'
    if isbn:
        q = f'isbn:{_norm_isbn(isbn)}'
    url = ("https://openlibrary.org/search.json?limit=%d"
           "&fields=key,title,author_name,ia,ebook_access,year,first_publish_year,edition_count"
           "&q=%s") % (limit, urllib.parse.quote_plus(q))
    d = _get_json(url)
    out = []
    if not d:
        return out
    for doc in d.get("docs", []):
        ia = doc.get("ia")
        if isinstance(ia, list):
            ia = ia[0]
        if ia:
            ia = ia.replace("ia:", "")
        year = doc.get("year") or doc.get("first_publish_year")
        isbn13 = None
        for i in doc.get("isbn", []) or []:
            n = _norm_isbn(i)
            if n:
                isbn13 = n
                break
        out.append({
            "title": doc.get("title"),
            "author": (doc.get("author_name") or [None])[0],
            "ia": ia,
            "ebook_access": doc.get("ebook_access"),
            "isbn": isbn13,
            "year": year,
            "url": "https://openlibrary.org" + (doc.get("key") or ""),
            "has_fulltext": doc.get("has_fulltext"),
        })
    return out


def ia_download_url(identifier: str) -> Optional[Dict]:
    d = _get_json(f"https://archive.org/metadata/{identifier}")
    if not d:
        return None
    files = d.get("files", [])
    if not files:
        return None
    title = (d.get("metadata") or {}).get("title", identifier)
    year = (d.get("metadata") or {}).get("year")
    # Lending/DRM items carry a paired .lcp.pdf or *_lcp.<fmt> file.
    lcp = any(
        (f.get("format") or "").lower() in ("pdf with drm", "lcpdf")
        or (f.get("name", "").lower().endswith(".lcp.pdf"))
        or "_lcp." in f.get("name", "").lower()
        for f in files
    )
    restricted = lcp or str(d.get("access-restricted", "false")).lower() == "true"
    # prefer ebook formats, then pdf. Skip DRM/LCP-wrapped files for public items.
    for ext in ("epub", "pdf", "mobi", "txt"):
        for f in files:
            name = f.get("name", "")
            fmt = (f.get("format") or "").lower()
            nlow = name.lower()
            if "encrypted" in nlow or nlow.endswith((".lcp.pdf", ".lcp.epub")):
                continue
            if fmt == ext or nlow.endswith("." + ext):
                return {
                    "url": f"https://archive.org/download/{identifier}/{urllib.parse.quote(name)}",
                    "format": ext,
                    "title": title,
                    "year": year,
                    "restricted": restricted,
                }
    for f in files:
        if f.get("format") in ("EPUB", "PDF", "Mobi", "Text", "HTML"):
            return {
                "url": f"https://archive.org/download/{identifier}/{urllib.parse.quote(f.get('name',''))}",
                "format": f["format"].lower(),
                "title": title,
                "year": year,
                "restricted": restricted,
            }
    return None


# ---------------- Project Gutenberg ----------------

def gutenberg_search(title: str, limit: int = 5) -> List[Dict]:
    """Search Project Gutenberg for books."""
    url = f"https://gutendex.com/books/?search={urllib.parse.quote_plus(title)}"
    d = _get_json(url)
    out = []
    if not d:
        return out
    for b in d.get("results", [])[:limit]:
        authors = ", ".join(a.get("name", "") for a in b.get("authors", []))
        formats = b.get("formats", {})
        epub_url = formats.get("application/epub+zip") or formats.get("text/html")
        out.append({
            "title": b.get("title"),
            "author": authors,
            "url": f"https://www.gutenberg.org/ebooks/{b.get('id')}",
            "download": epub_url,
            "source": "gutenberg",
            "languages": b.get("languages", []),
        })
    return out


# ---------------- Anna's Archive ----------------

def aa_api_host() -> Optional[str]:
    host = _resolve(AA_API_HOSTS)
    if host:
        return host
    # Try main site hosts as fallback
    return _resolve(AA_HOSTS)


def aa_search(title: str, author: Optional[str], isbn: Optional[str], limit: int = 8) -> List[Dict]:
    host = aa_api_host()
    if not host:
        return []
    q = _norm_isbn(isbn) if isbn and _norm_isbn(isbn) else title
    url = (f"https://{host}/search?v=2&lang=all&q={urllib.parse.quote_plus(q)}&limit={limit}")
    # Short timeout for gritty sources
    d = _get_json(url, timeout=8)
    items = []
    if d:
        raw = d.get("results") if isinstance(d, dict) else None
        if raw:
            items = [x[0] if isinstance(x, list) and x else x for x in raw]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        md5 = (it.get("md5") or "").lower()
        ext = it.get("ext") or it.get("extension") or "epub"
        if not md5:
            continue
        out.append({
            "md5": md5,
            "title": it.get("title"),
            "author": it.get("author"),
            "ext": ext,
            "lang": it.get("lang"),
            "pages": it.get("pages") or it.get("pages_count"),
            "year": it.get("year") or it.get("year_pub"),
        })
    return out


def aa_download_url(md5: str, ext: str) -> str:
    h = aa_api_host()
    base = f"https://{h}" if h and h != "annas-archive.org" else "https://annas-archive.org"
    dl = f"https://download.annas-archive.org" if h else base + "/download"
    return f"{dl}/md5/{md5[0]}/{md5[1]}/{md5}/{md5}.{ext}"


# ---------------- LibGen / Z-Library (parse HTML) ----------------

def libgen_search(title: str, author: Optional[str], limit: int = 5) -> List[Dict]:
    h = _resolve(LG_HOSTS)
    if not h:
        return []
    url = f"https://{h}/search?req={urllib.parse.quote_plus(title)}&s=1&d=0"
    if author:
        url += f"&req2={urllib.parse.quote_plus(author)}"
    # Short timeout for gritty sources
    html = _get_text(url, use_ssl_no_verify=True, timeout=8)
    if not html:
        html = _get_text(url, use_ssl_no_verify=False, timeout=8)
    if not html:
        return []
    # Detect consent wall / GDPR page
    if "gdprAppliesGlobally" in html or "cmp_host" in html or "consentmanager" in html.lower():
        return []
    out = []
    for m in re.finditer(r'href="/(result/|details/)?(\d+)"[^>]*><td[^>]*>(.*?)</td>', html, re.DOTALL):
        lid = m.group(2)
        t = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if t:
            out.append({"id": lid, "title": t, "source": "libgen"})
        if len(out) >= limit:
            break
    if not out:
        for m in re.finditer(r'/result/(\d+)', html):
            out.append({"id": m.group(1), "title": title, "source": "libgen"})
            if len(out) >= limit:
                break
    return out


def zl_search(title: str, author: Optional[str], limit: int = 5) -> List[Dict]:
    h = _resolve(ZL_HOSTS)
    if not h:
        return []
    url = f"https://{h}/index.php?story={urllib.parse.quote_plus(title)}"
    html = _get_text(url, use_ssl_no_verify=True, timeout=8)
    if not html:
        html = _get_text(url, use_ssl_no_verify=False, timeout=8)
    if not html:
        return []
    out = []
    for m in re.finditer(r'href="(/book/[0-9a-f]+_[^"]*"?|https?://\S+?\.pdf?)"', html):
        u = m.group(1)
        out.append({"url": u if u.startswith("http") else f"https://{h}{u}", "title": title, "source": "zlibrary"})
        if len(out) >= limit:
            break
    return out


# ---------------- pipeline ----------------

def find_book(title: str, author: Optional[str] = None, isbn: Optional[str] = None,
              lang: str = "en", limit: int = 5, gritty: bool = True) -> List[Dict]:
    results: List[Dict] = []
    title = (title or "").strip()
    if not title:
        return results

    # 1) OpenLibrary -> Internet Archive
    for doc in ol_search(title, author, isbn, limit=limit):
        entry = {
            "title": doc["title"],
            "author": doc["author"],
            "year": str(doc["year"]) if doc.get("year") else None,
            "isbn": doc["isbn"],
            "source": "openlibrary",
            "status": "metadata-only",
            "url": [doc["url"]],
            "download": None,
        }
        if doc.get("ia"):
            dl = ia_download_url(doc["ia"])
            if dl:
                if dl.get("restricted"):
                    entry["status"] = "borrow"
                    entry["source"] = "openlibrary+internet-archive (loan)"
                    entry["download"] = {"url": dl["url"], "format": dl["format"],
                                         "title": dl["title"],
                                         "note": "on loan — use /details/ page or borrow via account"}
                    entry["url"].append(f"https://archive.org/details/{doc.get('ia')}")
                    results.append(entry)
                    continue
                entry["download"] = dl
                entry["status"] = "direct-download"
                entry["source"] = "openlibrary+internet-archive"
        elif doc.get("ebook_access") == "borrow" and _norm_isbn(doc.get("isbn") or ""):
            n = _norm_isbn(doc.get("isbn") or "")
            entry["url"].append(f"https://archive.org/details/{doc.get('ia') or ('isbn:' + n)}")
            entry["status"] = "borrow"
        results.append(entry)

    # 2) Project Gutenberg (public domain)
    for se in gutenberg_search(title):
        dl = se.get("download")
        results.append({
            "title": se["title"], "author": se.get("author"), "year": None, "isbn": None,
            "source": se.get("source"), "status": "direct-download" if dl else "metadata-only",
            "url": [se["url"]], "download": {"url": dl, "format": "epub", "title": se["title"]} if dl else None,
        })

    # 3) Anna's Archive (gritty)
    if gritty:
        aa = aa_search(title, author, isbn, limit=max(limit, 6))
        if aa:
            # prefer requested language
            aa_sorted = sorted(aa, key=lambda x: (
                not (x.get("lang") or "").lower().startswith(lang.lower()), -int(x.get("pages") or 0)))
        else:
            aa_sorted = []
        for item in aa_sorted[:limit]:
            results.append({
                "title": item.get("title"), "author": item.get("author"),
                "year": str(item["year"]) if item.get("year") else None, "isbn": None,
                "source": "annas-archive", "status": "direct-download",
                "url": [f"https://annas-archive.org/md5/{item['md5']}"],
                "download": {
                    "url": aa_download_url(item["md5"], item["ext"]),
                    "format": item["ext"], "title": item.get("title"),
                },
                "pages": item.get("pages"),
            })
        # 4) LibGen / Z-Lib fallback if no usable file was found
        if not any(r.get("download") and r["status"] == "direct-download" for r in results):
            for lg in libgen_search(title, author, limit=limit):
                results.append({
                    "title": lg["title"], "author": author, "year": None, "isbn": None,
                    "source": lg["source"], "status": "scrape",
                    "url": [f"/result/{lg['id']}"], "download": None,
                })
            for zl in zl_search(title, author, limit=2):
                results.append({
                    "title": zl["title"], "author": author, "year": None, "isbn": None,
                    "source": zl["source"], "status": "scrape",
                    "url": [zl["url"]], "download": zl["url"] if zl["url"].endswith((".pdf", ".epub")) else None,
                })

    # rank: direct-download > borrow > metadata > scrape; prefer isbn match, pages
    order = {"direct-download": 0, "borrow": 1, "metadata-only": 2, "scrape": 3}
    results.sort(key=lambda r: (order.get(r["status"], 4), -int((r.get("pages") or 0))))
    return results[:max(limit * 2, 10)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Get any book, for free, from anywhere.",
        epilog='"Pride and Prejudice", "the great gatsby", or --isbn 9780743273565')
    ap.add_argument("query", nargs="*", help="title (and optional author words)")
    ap.add_argument("--author", help="author name (more precise)")
    ap.add_argument("--isbn", help="ISBN 10/13 (most precise)")
    ap.add_argument("--lang", default="en", help="preferred language, ISO-639-1 (default en)")
    ap.add_argument("--limit", type=int, default=5, help="candidates per source (default 5)")
    ap.add_argument("--no-gritty", action="store_true", help="legal-first only (skip AA/LibGen/ZLib)")
    ap.add_argument("--download", action="store_true", help="download best direct file to --out")
    ap.add_argument("--out", default="./books", help="output dir for --download (default ./books)")
    ap.add_argument("--extract", action="store_true", help="extract text from downloaded EPUB/PDF (requires ebooklib/pdfminer)")
    ap.add_argument("--chunk-size", type=int, default=4000, help="text chunk size for --extract (default 4000 words)")
    ap.add_argument("--chunk-overlap", type=int, default=200, help="overlap between chunks (default 200)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    title = " ".join(args.query).strip()
    if not title and not args.isbn:
        ap.error("provide a title or --isbn")

    res = find_book(title, args.author, args.isbn, lang=args.lang,
                    limit=args.limit, gritty=not args.no_gritty)

    if args.json:
        payload = json.dumps(res, indent=2, ensure_ascii=False)
        print(payload)
        if args.download:
            best = next((r for i, r in enumerate(res) if r.get("download")
                         and r["status"] == "direct-download"), None)
            if best:
                d = dict(best["download"])
                dest = download_file(d["url"], args.out)
                if dest:
                    result = {"downloaded": dest}
                    if args.extract:
                        text = extract_book_text(dest)
                        if text:
                            chunks = chunk_text(text, args.chunk_size, args.chunk_overlap)
                            result["text_length"] = len(text)
                            result["chunks"] = chunks
                            result["chunk_count"] = len(chunks)
                            # Save chunks to file
                            chunk_file = dest + ".chunks.json"
                            with open(chunk_file, "w", encoding="utf-8") as f:
                                json.dump({"source": dest, "chunks": chunks, "chunk_size": args.chunk_size, "overlap": args.chunk_overlap}, f, ensure_ascii=False, indent=2)
                            result["chunks_file"] = chunk_file
                        else:
                            result["extraction_error"] = "Failed to extract text (missing deps or unsupported format)"
                    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 0

    if not res:
        print("No results. Try --no-gritty off, or a more specific title/ISBN.", file=sys.stderr)
        return 1

    print(f"== {len(res)} candidate(s) for: {title or args.isbn}")
    for i, r in enumerate(res, 1):
        print(f"\n[{i}] {r['title']}")
        if r.get("author"):
            print(f"    by {r['author']}")
        meta = f"    {r['source']} | status: {r['status']}"
        if r.get("year"):
            meta += f" | {r['year']}"
        if r.get("isbn"):
            meta += f" | isbn {r['isbn']}"
        print(meta)
        for u in r["url"][:3]:
            print(f"    {u}")
        dl = r.get("download")
        if dl and isinstance(dl, dict):
            note = f"  ({dl['note']})" if dl.get("note") else ""
            print(f"    download: {dl['url']}  ({dl['format']}){note}")
        if r.get("pages"):
            print(f"    {r['pages']} pages")

    best_i = next((i for i, r in enumerate(res, 1)
                   if r.get("download") and r["status"] == "direct-download"), None)
    if best_i is not None:
        r = res[best_i - 1]
        print(f"\nBest: [{best_i}] {r['title']}")
        print(f"  open: {r['download']['url']}")
        if args.download:
            dest = download_file(r["download"]["url"], args.out)
            if dest:
                print(f"  saved: {dest}  ({os.path.getsize(dest):,} bytes)")
                if args.extract:
                    text = extract_book_text(dest)
                    if text:
                        chunks = chunk_text(text, args.chunk_size, args.chunk_overlap)
                        print(f"  extracted: {len(text):,} chars → {len(chunks)} chunks ({args.chunk_size}w/{args.chunk_overlap} overlap)")
                        # Save chunks to JSON
                        chunk_file = dest + ".chunks.json"
                        with open(chunk_file, "w", encoding="utf-8") as f:
                            json.dump({"source": dest, "chunks": chunks, "chunk_size": args.chunk_size, "overlap": args.chunk_overlap}, f, ensure_ascii=False, indent=2)
                        print(f"  chunks saved: {chunk_file}")
                    else:
                        print("  extraction failed — missing ebooklib/pdfminer or unsupported format")
            else:
                print("  download failed — open the URL manually.")

    return 0


def download_file(url: str, outdir: str) -> Optional[str]:
    import shutil
    os.makedirs(outdir, exist_ok=True)
    name = os.path.basename(urllib.parse.urlparse(url).path) or "book.bin"
    name = re.sub(r"[^\w.\-]", "_", name)[:150]
    dest = os.path.join(outdir, name)
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1 << 20)
        shutil.move(tmp, dest)
        return dest
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"  download error: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    sys.exit(main())
