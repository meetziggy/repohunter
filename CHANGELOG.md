# Changelog

All notable changes to RepoHunter are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); pre-1.0 releases are date-based.

## [0.2.0] — 2026-08-20 — ship the reflex with the tools
### Added
- **Claude Code plugin** — the repo is now its own single-plugin marketplace.
  `/plugin marketplace add meetziggy/repohunter` then `/plugin install repohunter`
  installs the skills *and* wires the MCP server in one step
  (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`).
- **`repo-intake` skill** — the full gate: scan → triage → evaluate → fit-map →
  INTEGRATE / CHERRY-PICK / LOGIC-GATHER / SKIP, run by a party of specialist agents.
  Includes the party spec in `references/`.
- **Named project profiles.** `config.json` may now carry a `profiles` map; select with
  `--profile <name>` / `REPOHUNTER_PROFILE`, list with `repohunter profiles`. The same
  repo is often a GO for one project and a SKIP for another — the lens decides as much
  as the repo does. An unknown profile is a hard error rather than a silent fallback.
- **`repohunter install-skill [dir]`** — copy the bundled skills into an agent's skills
  directory for agents without plugin support.
- **`.skill` bundles** built per release for skill stores that take an upload.
- Release workflow: manifest validation, tests, wheel + sdist, an sdist-contents check
  that fails if the skills went missing, and PyPI publish via Trusted Publishing.

### Fixed
- `repohunter_artifacts` was never listed in `py-modules`, so it did not exist in an
  installed copy despite shipping its own tests. Now packaged, with a
  `repohunter-artifacts` console script.
- `MANIFEST.in` added so the sdist carries the skills and plugin manifests.
- Safety scan: a UTF-8 BOM at byte 0 no longer counts as hidden text, and AWS's
  canonical documentation keys (`AKIAIOSFODNN7EXAMPLE`) no longer count as leaked
  secrets. Both were burying real findings in noise.

## [Unreleased]
- Soak-week hardening + full docs (see `SOAK_WEEK.md`)
- Landing-page guided walkthrough + larger hero logo
- Green **"compute saved ≈ energy ≈ CO₂ avoided"** estimate on adoptions _(planned)_
- Port the visual store (walkthrough + Map) fully into the standalone build

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
