What This Is: Repohunter/ResearchHunter + BookHunter integration. Built research-hunter (deep/wide) with papers/books/web, CLI + MCP tools, skill added.

Last Session (2026-10-03):
- Created bookhunter_providers.py + bookhunter.py (legal-first book search: OpenLibrary, Project Gutenberg). Added availability links.
- Built research_hunter.py: arXiv + OpenAlex papers, books via bookhunter, web; synthesis + citations.
- Added MCP tools (research_topic/papers/book), rh_cli.py, skills/research-hunter/SKILL.md. Tested queries; arXiv returns results, OpenAlex sparse depending on query.
- Book search works (OpenLibrary results). Avoided piracy sources by design.

Next Steps (priority):
1. Add more paper sources (CORE, Unpaywall) for better coverage
2. Improve OpenAlex query handling
3. Add citation export (BibTeX/JSON)
4. Extend bookhunter with Internet Archive/StandardEbooks/DOAB properly
5. Wire research tools into repohunter's main CLI if desired

Open Questions: None blocking.

Key Files:
- research_hunter.py, rh_cli.py, bookhunter*.py, repohunter_mcp.py, skills/research-hunter/SKILL.md

Blockers: None
