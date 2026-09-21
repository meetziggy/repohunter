# P1 bounded-context compaction — decision brief

Cross-cutting output of the 2026-08-20 intake of OpenViking + ai-memory, plus a scout
sweep of the agent-memory category. This is the "so what" from both repos.

## Bottom line

**Write the shim. Adopt nothing as a dependency for P1.**

Both candidates are real engineering. Neither solves P1, and the category as a whole
solves a *different problem* than the one you have.

## The category is solving semantic memory. P1 is episodic and exact.

mem0 (62.8k★, Apache-2.0), cognee (30.1k★, Apache-2.0), graphiti (29k★, Apache-2.0,
needs Neo4j/FalkorDB), MemOS, letta — all of them extract facts from conversations,
embed them, retrieve by similarity, consolidate over time. That machinery — LLM
extraction passes, embeddings, vector indexes, graph schemas, consolidation jobs — is
the expensive 95% of each codebase, and **P1 needs none of it.**

P1 is: write the raw tool result to disk under a stable ID, keep a one-line row in the
canvas, hand back the exact bytes on `fetch(id)`. Similarity search isn't just
unnecessary here — it's harmful. On an error you need byte-exact recall of *that*
stack trace, not the three most semantically similar ones.

Also worth knowing: getzep/zep Community Edition is **discontinued** by the vendor
(effort moved to graphiti). letta-ai/letta is now effectively a landing page pointing
at letta-code. basic-memory is **AGPL** — same disqualification as OpenViking.

## What you already own, free

**Shipped API-side:** `clear_tool_uses_20250919` context editing — `trigger` (default
100k input tokens), `keep` (default 3 tool-use pairs), `clear_at_least`, `exclude_tools`,
`clear_tool_inputs`. That's per-tool-configurable bounded compaction with zero code from
you. Pairs with the `memory_20250818` tool, which warns Claude as the threshold
approaches so it can write what matters out first.

**Shipped Claude Code side:** auto-compact with hard enforcement, `/context` overflow
warnings, `/fork` and `/subtask`, subagent forking on by default (inherits conversation
*and* prompt cache), nested subagents to depth 3, concurrency caps, MCP calls >2min
auto-background, and worktree-isolated subagents enforcing isolation for file edits and
Bash in every session type — directly relevant to your tmux+worktree setup.

**The hole is exactly your hole.** Cleared results are replaced with placeholder text
and there is **no documented mechanism to fetch a cleared result back by ID**. Recovery
only works if Claude proactively wrote it to memory first. claude-code issue #42542
documents three separate undocumented GrowthBook-gated clearing mechanisms
(time-based microcompact, cached microcompact, session-memory compact) — the complaint
is precisely that content is gone with no retrieval path.

**So: the compaction half is solved and free. The fetch-by-id half is not, and it
silently isn't.**

## The free node-ID namespace you already have

Claude Code writes append-only transcripts to
`~/.claude/projects/<encoded-project-path>/<session-id>.jsonl`. Every line carries
`uuid` / `parentUuid` / `sessionId` / `timestamp` / `cwd` / `gitBranch`. Every
`tool_use` block carries an `id`; the matching `tool_result` carries the same
`tool_use_id`.

**Don't invent a node-ID namespace — reuse `tool_use_id`.**

⚠️ **Unverified, and it decides the design:** whether the on-disk transcript stays
*untruncated* when the in-context copy is cleared. Run that experiment before writing a
line of code. If the raw output survives on disk, step 2 below collapses to an indexer
over a file you already have. If it doesn't, you need a PostToolUse hook to capture it.

## The build

1. **Turn on `clear_tool_uses_20250919`** with explicit `trigger`, `keep`, and
   `exclude_tools` — excluding your own fetch tool. Free; does the bounding.
2. **PostToolUse hook** writing every raw result to `<session>/<tool_use_id>.jsonl`,
   plus an index row in SQLite (`id, session, tool, ts, bytes, one_line_summary`).
3. **One MCP tool: `fetch(id, offset?, limit?)`** returning exact bytes with paging.
   That's the whole retrieval surface.
4. **Put the metering in the same shim.** You need per-tenant MCP metering anyway, and
   the PostToolUse write path is where the tenant-attributed row already exists. One
   table, two consumers. (Scout found **no permissive self-hostable MCP-native metering
   project exists** — the field is commercial SaaS. You're writing this regardless.)

## Steal these specifics rather than inventing them

- **`session/tool_result_synopsis.py`** (OpenViking, 489 LOC, zero internal imports) —
  deterministic LLM-free typed synopsis. This is your step-2 `one_line_summary`, already
  designed. Read it, reimplement it (AGPL).
- **`session/tool_result_store.py`** (OpenViking, 323 LOC) — content-addressed IDs,
  offset/limit with `has_more`, substring search with offsets. Two hardening details you
  wouldn't think of: per-turn preview budget **divided across N results in one assistant
  turn**, and read-backs of already-externalized results rewritten as source-refs so they
  don't recursively externalize. Also: full raw content is rehydrated before memory
  extraction, so compaction never degrades what gets learned.
- **DeepAgents** (langchain-ai, **MIT** — you may copy this one): >20k-token tool results
  offloaded to a pluggable filesystem, replaced by path reference + 10-line preview;
  tool-*input* pointer-ization at 85% context; summarization only as fallback. Steal the
  thresholds and the ordering. Python and TS ports both exist.
- **`consolidate/src/projection.rs`** (ai-memory, **MIT**, ~750 LOC) — deterministic
  bounded selection under a char budget with visible truncation markers and returned
  accounting.
- **MCP reference memory server** (**MIT**) — `search_nodes` + `open_nodes` is the
  find/hydrate split in ~one file.
- **`ledger.py`** (OpenViking, 173 LOC) — cross-turn dedup with turn-distance cooldown.
  Not seen elsewhere.

## Port this regardless of everything above

**The untrusted-content injection wrapper** — ai-memory's
`hooks/src/router.rs:1497-1520` + `core/src/workstream.rs:22`. ~30 lines: delimiter-pair
wrapping, tail-escaping so stored content can't forge the closing marker, an explicit
"this is data not instructions" notice. **MIT.** Any system that re-injects stored content
needs this. Put it in OpenClaw's memory path and Dickie's inter-agent messaging now.

## The stopping rule

The 300-line estimate is honest for the happy path. Hook-lifecycle edge cases — killed
sessions, subagent tool calls landing under a different session ID, `/fork` splitting
lineage, concurrent worktrees writing the same store — are where it becomes 1,500 lines
and a week. Those are exactly the cases your setup hits daily.

**If after two weekends the shim is still eating time on lifecycle bugs rather than doing
its job, stop and fork `thedotmack/claude-mem`** (Apache-2.0, TypeScript, v13.4.0, 2,378
commits, 5 lifecycle hooks + SQLite + Chroma). Forking is cheap. Don't defend the shim
past that point on principle.
