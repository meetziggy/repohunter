What This Is: Repohunter/ResearchHunter + BookHunter integration. Built research-hunter (deep/wide) with papers/books/web, CLI + MCP tools, skill added. Now also: standalone distributable book-fetch skill. Added trending search + report generation to repohunter core.

Last Session (2026-10-04, cleanup + Aruba check):
- repohunter_mcp.py: the appended research tools used `@mcp.tool()` decorators with no import (NameError on load) — rewritten into the file's own pattern: `skill_research_*` handlers registered in `SKILLS`, lazy import of research_hunter.py from skills/research-hunter/. All 68 tests pass, tools/list shows all 6 skills
- Removed session temp scripts from the root (_dbg.py, _dl_books.py, _dl_ia.py, _find_gritty.py, _ia_meta.py, _parse_dl.py, _zlib.py). Book downloads live in ~/dev/audits/groundtrace-books-20261004/
- Aruba Networks "get home": not found. `repohunter trending --topic aruba` (2026-10-04) = 27 repos, none matching. GitHub org:aruba has 53 repos, none "get home". gethome.arubanetworks.com and gethome.arubawebsites.com do not resolve. Best candidates if it was a product: Aruba Instant On (home/SMB WiFi) or the Aruba Central Python workflows repo used as a campaign signal in the groundtrace tenant (web/private/developer-campaign.json)
- Groundtrace book KB produced: docs/kb/BOOK-TO-FEATURES.md in the groundtrace-business repo (12 books → K1-K12 schema-anchored transformation entries, first five K1/K2/K5/K10/K7)
- Next planned: same artifact pattern for "AI fundamentals" reading list (Unix/macOS vs Windows operating perspective, account/device login, per-client chat+memory persistence) + micro tips bank

Earlier Session (2026-10-04):
- Added `repohunter trending` command: search GitHub by topic/language/time-period (daily/weekly/monthly/yearly), outputs markdown/json/html
- Added `repohunter report` command: generate reports from JSON (stdin or file) in markdown/json/html
- Both commands tested and working: trending finds real repos (e.g., machine-learning → transformers, pytorch, etc.)
- Book-fetch skill moved to skills/book-fetch/ (standalone deliverable), research-hunter to skills/research-hunter/
- Enhanced book-fetch with EPUB/PDF text extraction (ebooklib, pdfminer.six) + chunking for LLM ingestion
- New flags: --extract, --chunk-size, --chunk-overlap; outputs .chunks.json with overlapping chunks
- Replaced Standard Ebooks with Project Gutenberg (modern API, reliable)
- Legal-first book search: OpenLibrary/IA (ebook_access + LCP detection), Project Gutenberg. Gritty mirrors: Anna's Archive, LibGen, Z-Library (host rotation, fail-soft, silent failures)
- Flags: --author --isbn --lang --limit --no-gritty --download --out --json --extract. Verified: P&P 1.4MB EPUB downloaded + 696K chars extracted → 33 chunks; Pragmatic Programmer correctly borrow+mirrors
- IA access-restricted field unreliable; lending detected via *.lcp.* files or OL ebook_access != public
- Gritty sources now fail gracefully with short timeouts (8s) and silent failures (DNS issues, consent walls, JS-rendered SPAs)
- Existing repo code (bookhunter*, research_hunter.py, rh_cli.py) now in skills/research-hunter/
- repohunter_mcp.py: added ResearchHunter MCP tools (research_topic, research_papers, research_book)

Next Steps (priority):
1. Add more paper sources (CORE, Unpaywall) for better coverage
2. Improve OpenAlex query handling
3. Add citation export (BibTeX/JSON)
4. Wire research tools into repohunter's main CLI if desired

Open Questions: None blocking.

Key Files:
- skills/book-fetch/SKILL.md, skills/book-fetch/scripts/bookfetch.py (new deliverable with text extraction)
- skills/research-hunter/ (bookhunter*, research_hunter.py, rh_cli.py, SKILL.md)
- repohunter.py (trending, report commands added)
- repohunter_mcp.py (evaluate_repo, find_repos, portfolio_scan + research tools)

Blockers: None