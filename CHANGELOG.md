# Changelog

All notable changes to RepoHunter are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); pre-1.0 releases are date-based.

## [Unreleased]
- Soak-week hardening + full docs (see `SOAK_WEEK.md`)
- Landing-page guided walkthrough + larger hero logo
- Green **"compute saved ≈ energy ≈ CO₂ avoided"** estimate on adoptions _(planned)_
- Port the visual store (walkthrough + Map) fully into the standalone build

## [0.2.0] — 2026-09-22
### Added
- **License/resale-risk gate** — every dossier and `evaluate` now carries a license read
  (permissive / weak or strong copyleft / source-available), so a GPL or BUSL dependency doesn't
  quietly end up inside something you sell
- **Named project profiles** — `config.json` can define several projects; `--profile <name>` (or
  `REPOHUNTER_PROFILE`) switches between them, `repohunter profiles` lists what's configured. One
  install, several lenses.
- **Agent-config path walking** — `scan` now reads `.claude/`, `.agents/`, `skills/`, and similar
  nested agent-instruction directories, not just top-level files; a skill pack shipping 40 command
  files used to report "2 files scanned"
- **`repohunter-agent`** — authenticated, read-only A2A-style peer adapter exposing RepoHunter's
  skills to other agents
- **`repohunter-artifacts`** — artifact-level (not repo-level) evaluation: cost/blast-radius/safety
  of a skill, command, hook, or MCP server an agent actually loads
- Two discovery radars: YouTube channel polling, skillselion.com structured-data polling
- **Claude Code plugin** — this repo is its own marketplace (`/plugin install repohunter`); ships
  the MCP server and a new `repo-intake` skill (scan → triage → evaluate → fit-map) together
- **MCP evidence provenance** — every MCP skill result now carries a machine-readable block
  (endpoint, timestamp, derivation, limits) — see [`MCP-INSTALL.md`](MCP-INSTALL.md)
- Cloudflare Pages deploy is now codified (`wrangler.toml`, a deploy workflow, a post-deploy smoke
  check against the live site) instead of dashboard-only configuration
- Install via `uvx`/`uv tool install`/`pipx`, no clone required — see the Quickstart

### Fixed
- **Silent LLM failures** — a bad key, dead model ID, network failure, and rate limit used to all
  return `""` indistinguishably; failures are now logged with backend + reason. Added an optional
  app-level backend fallback (`llm.fallback` in `config.json`)
- **Concurrency-safe store I/O** — two `evaluate`/`plan`/`decide`/`ingest-video` runs at once could
  silently overwrite each other's store writes; now advisory-locked with atomic write-then-rename
- **Scan false positives** — API-documentation tables and policy/disclosure prose (e.g. a
  `SECURITY.md` describing an attack rather than instructing one) no longer trip the
  exfiltration-instruction detector; canonical AWS example keys no longer flag as leaked secrets
- A failed scan (GitHub rate limit, missing repo) used to report `"level": "clean"` — now honestly
  reports `"unknown"`

## [0.1.0] — 2026-07-26 — soft launch
### Added
- Public soft launch: repository + site at **repohunter.dev**
- **Integration dossier** per repo — relevance to your project, how to integrate, the enhancement,
  build-vs-integrate, rough cost (tokens/time/agents), does-it-run-on-your-hardware, kind classification,
  and a **GO / MAYBE / SKIP** verdict
- **All-inclusive ingest** — drop a repo, live GitHub search, YouTube "top repos" video ingest,
  and aggregate-list detection (awesome-lists treated as sources to mine)
- **Approve-first, two-gate integration planning** — concrete checksum-pinned plan → your approval
  (automated builder stage in progress); never a `curl | bash`
- **Pluggable LLM backend** — local Ollama by default (no API bill), OpenAI/OpenRouter via `config.json`
- **Store UI** — a sortable/filterable browser (best-fit / relevance / stars / maturity), dossier drawers,
  live GitHub search, and YouTube ingest. _(The guided walkthrough + Map view are tracked under Unreleased.)_
- Brand identity — dragonfly logo, brand guide, OG link-preview + social assets
