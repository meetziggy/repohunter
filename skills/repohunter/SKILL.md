---
name: repohunter
description: >-
  Reuse-first gate. BEFORE adopting, cloning, or installing any open-source repo or dependency,
  use this to decide should-I-reuse-this: real GitHub stats + a transparent GO/MAYBE/SKIP verdict,
  resource-fit for the current machine, and license/freshness signals. Also finds reuse candidates
  for a need, and summarizes a GitHub user/org's public work as facts. Use whenever the task is
  "find/evaluate/choose an open-source project", "should I add this dependency", or "build vs. reuse".
---

# RepoHunter — reuse before you reinvent

The reflex this skill installs: **don't add a dependency or clone a repo on vibes.** Check it first,
get one honest decision, then act. It stops slop and bloat from getting *into* the codebase.

## When to reach for it
- The user (or your own plan) is about to `pip install` / `npm install` / clone a repo → **evaluate it first.**
- The user asks "is there something that already does this?" → **find candidates, then evaluate the top one.**
- You're weighing **build-vs-reuse** → a MAYBE/SKIP with a thin repo is a signal to just write the few lines.
- Someone wants a factual read on a GitHub user/org's public work (due diligence) → **portfolio_scan.** Facts only.

## How to use it
RepoHunter ships as an **MCP server** (`repohunter-mcp`). If it's connected, call its tools directly:

- `evaluate_repo(repo, project?)` → real stars/license/last-push + RepoHunter's labeled scores
  (popularity/freshness/health/maturity), a **resource-fit** read (runs easily / needs RAM / wants a GPU),
  and a **GO / MAYBE / SKIP** verdict. Pass `project` (a one-line description of what you're building) to
  get a relevance read too.
- `find_repos(query)` → ranked reuse candidates from live GitHub search. Then `evaluate_repo` the best one.
- `portfolio_scan(user)` → a GitHub user/org's public work as **facts + patterns** (languages, focus,
  activity, top repos). This is a description of the *work*, never a judgment of the *person*.

If the MCP server isn't connected, the same logic runs from the CLI: `repohunter eval <owner/name>`
(see the project README), or tell the user how to add the server (below).

## Reading the verdict (don't treat it as gospel)
- **GO** — strong reuse candidate; still eyeball license + security before you commit.
- **MAYBE** — usable but has a gap (stale, small, niche). Weigh it against just building the piece yourself.
- **SKIP** — archived, abandoned, or a poor fit. Look elsewhere or build it.

The scores are a **transparent heuristic over public GitHub data — guidance, not a guarantee.** Always
verify license and security independently before adopting. Never present a verdict as objective truth.

## Integrity rules (non-negotiable)
- **Report real numbers only.** Everything comes from the live GitHub API — never invent stars, savings,
  or costs. If a value isn't in the data, say so.
- **Never judge a person.** `portfolio_scan` describes public work; it is not a competence, character, or
  hiring assessment. Say that plainly if asked to rank or rate someone.
- **Read-only on the world.** RepoHunter never opens issues/PRs or messages maintainers.

## Add the MCP server (if not already connected)
- **Claude Code:** `claude mcp add repohunter -- uvx repohunter-mcp`
- **Other clients + one-command install:** see `MCP-INSTALL.md` in the repo, or `repohunter.dev`.
