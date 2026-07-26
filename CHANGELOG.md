# Changelog

All notable changes to RepoHunter are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); pre-1.0 releases are date-based.

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
- **Visual store UI** — first-run walkthrough, plus **Grid** and **Map** (relevance × ready-to-use) views
- Brand identity — dragonfly logo, brand guide, OG link-preview + social assets
