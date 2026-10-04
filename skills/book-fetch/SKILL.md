---
name: book-fetch
description: >-
  Get any book, for free, from anywhere. One script, legal-first with gritty
  mirrors. Searches OpenLibrary, Internet Archive, Project Gutenberg, Anna's
  Archive, LibGen, and Z-Library. Finds public-domain direct downloads,
  14-day loan lending copies, and modern releases via the mirror network.
  Text extraction + chunking for LLM ingestion. Use whenever the user wants to find, borrow, or download a book.
---

# BookFetch

Get any book, for free, from anywhere.

## When to use
- User asks for a specific book ("get me Dune", "find a free copy of ...")
- User has an ISBN and wants the file
- User wants a book in a non-English language
- User says "download it", "where can I read this for free", "get me the epub"

## Run it

```bash
python3 scripts/bookfetch.py <title> [flags]
```

Flags:

| Flag | Purpose |
|---|---|
| `--author "Name"` | Disambiguate (e.g. "Traction" + "Gino Wickman") |
| `--isbn 9780...` | Exact match — use if the user gave an ISBN |
| `--lang en` | Preferred language, ISO 639-1 (default `en`; try the user's language) |
| `--limit 5` | Candidates per source |
| `--no-gritty` | Legal-only: OpenLibrary/IA/Gutenberg, no mirrors |
| `--download --out DIR` | Save the best direct-download file (default `./books`) |
| `--extract` | Extract text from downloaded EPUB/PDF (requires ebooklib/pdfminer) |
| `--chunk-size 4000` | Text chunk size for --extract (default 4000 words) |
| `--chunk-overlap 200` | Overlap between chunks (default 200) |
| `--json` | Machine-readable output |

If the user gave "Title, Author", run it as `--author`; that searches more
precisely than stuffing the name into the title.

## How results are ranked

1. `direct-download` — public domain / OA; grab the URL with `--download`
2. `borrow` — Internet Archive controlled-digital-lending (free 14-day loan,
   needs a free archive.org or OpenLib account); hand the user the
   `/details/` link and tell them how to borrow/read online
3. `annas-archive` — gritty mirror, universal, no login for most modern books
4. `scrape` (libgen/zlibrary) — last resort; open the link in a browser

Always prefer the first `direct-download` result. If only `borrow` exists, say
so plainly — it is still free, just a library loan. If only mirrors exist,
mention they are the gritty path.

## Text Extraction (for LLM ingestion)

```bash
python3 scripts/bookfetch.py "Pride and Prejudice" --download --extract --out ./books
```

- Downloads best EPUB/PDF, extracts full text using ebooklib (EPUB) or pdfminer (PDF)
- Splits into overlapping chunks (`--chunk-size`, `--chunk-overlap`)
- Outputs `.chunks.json` with `{source, chunks[], chunk_size, overlap}`
- Use chunks directly with LLM context windows or embedding pipelines

## Edge cases
- No results → retry with a shorter title, then with `--isbn` if the user can
  provide one, then drop `--no-gritty`.
- User wants a specific edition/format → check all candidate URLs, pick the
  `.epub`/`.pdf` that matches; `--json` shows every candidate.
- Non-English book → `--lang <code>` (de, fr, es, ja, ...).
- Download fails → the book is likely LCP-DRM; fall back to the borrow link or
  an annas-archive result.

## Output contract
Each candidate has: title, author, year, isbn, source, status, page count
(when known), `url` list, and a `download` object ({url, format, note}) when a
file can be fetched directly.

With `--json --download --extract`: also emits `text_length`, `chunk_count`,
`chunks[]`, and `chunks_file` path to stderr.