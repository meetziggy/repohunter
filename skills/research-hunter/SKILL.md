---
name: research-hunter
description: >-
  Deep/wide research for any topic, author, or book. Searches legal books, academic
  papers (arXiv/OpenAlex), and web. Returns structured synthesis with citations and
  reading list. Modes: quick/wide/deep. Legal-first (uses BookHunter). Use when you
  need to research an ambiguous topic, find papers, or locate books.
---

# ResearchHunter

Research any topic deeply/widely with citations.

## When to use
- Ambiguous topic research ("wireless mesh routing" broadly/deeply)
- Find papers on a topic/author
- Find legal books (title/author/ISBN)
- Need reading list + synthesis

## Tools (MCP)
- `research_topic(query, mode="wide", limit=30, include_books=True, include_papers=True, include_web=True)` — full
- `research_papers(query, limit=20)` — papers only
- `research_book(query, limit=15)` — legal books only

Modes: quick (focused), wide (balanced), deep (broader).

## CLI
```bash
cd /Users/bgorzelic/dev/projects/repohunter
python3 rh_cli.py research "topic" wide 30
python3 rh_cli.py papers "topic" 20
python3 rh_cli.py books "Traction Gino Wickman" 10
```

Returns synthesis (summary, key points, reading list, all sources) with URLs/citations.
