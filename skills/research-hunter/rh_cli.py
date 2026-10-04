#!/usr/bin/env python3
"""ResearchHunter CLI."""
from __future__ import annotations

import json
import sys

import research_hunter


def main():
    if len(sys.argv) < 2:
        print("usage: rh <research|papers|books> <query> [mode] [limit]")
        return
    cmd = sys.argv[1]
    if cmd in ("research", "r") and len(sys.argv) >= 3:
        parts = sys.argv[2:]
        limit = 30
        mode = "wide"
        qparts = []
        for p in parts:
            if p.isdigit():
                limit = int(p)
            elif p in ("quick", "wide", "deep"):
                mode = p
            else:
                qparts.append(p)
        q = " ".join(qparts) or " ".join(parts)
        res = research_hunter.research_topic(q, mode=mode, limit=limit)
        print(json.dumps(res, indent=2))
    elif cmd == "papers" and len(sys.argv) >= 3:
        q = " ".join(sys.argv[2:-1]) if len(sys.argv) > 3 and sys.argv[-1].isdigit() else " ".join(sys.argv[2:])
        limit = int(sys.argv[-1]) if len(sys.argv) > 3 and sys.argv[-1].isdigit() else 20
        res = research_hunter.research_papers(q, limit=limit)
        print(json.dumps(res, indent=2))
    elif cmd in ("books", "book") and len(sys.argv) >= 3:
        q = " ".join(sys.argv[2:-1]) if len(sys.argv) > 3 and sys.argv[-1].isdigit() else " ".join(sys.argv[2:])
        limit = int(sys.argv[-1]) if len(sys.argv) > 3 and sys.argv[-1].isdigit() else 15
        res = research_hunter.research_book(q, limit=limit)
        print(json.dumps(res, indent=2))
    else:
        print("usage: rh research 'wireless mesh routing' deep 40")


if __name__ == "__main__":
    main()
