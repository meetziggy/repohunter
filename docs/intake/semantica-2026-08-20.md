# Intake: semantica-agi/semantica — 2026-08-20

Worked example of the repo-intake pipeline. Full dickie party ran: scanner
(code) → auditor + scout (parallel agents) → fit-mapper.

## Verdict: CHERRY-PICK

Downgraded from the 2026-08-14 cached dossier's "MAYBE / integrate narrowly."
The deep audit killed the pip-adoption path; the logic value survives.

## Live facts (2026-08-20)

9.6k stars, 1k forks, 58 open issues, MIT (Hawksight AI), v0.6.5.
986 commits from 2026-04-08 to 2026-08-19 (last commit yesterday; ~4.5
months old). Author concentration: Mohd Kaif/KaifAhmad1 537 commits (one
person, two identities), Sameer 222, Zohaib 38 — effective bus factor ~2.
675 Python files, ~182k LOC under `semantica/`, 27 packages.

## Scan (full clone, 1,034 files)

13 raw findings → all benign on triage: 8× zero-width = UTF-8 BOMs at byte 0;
1× "AWS key" = `AKIAIOSFODNN7EXAMPLE` (AWS docs placeholder); 4× "exfiltration"
= the repo documenting its own `X-API-Key` auth. No agent-directed content
found anywhere in the tree. Side effect: two scanner FP classes fixed in
repohunter.py (BOM@0, example-key allowlist) + regression tests.

## Why not INTEGRATE

- `pip install semantica` forces **42 mandatory runtime deps** including
  torch, transformers, opencv, librosa, spacy, gensim — multi-GB for a use
  case (node-store + provenance) that needs none of them. No lite target.
  requirements-ci pins 392 transitive packages.
- **CI never runs its own Python test suite** (262 test files, ~5,135 test
  functions exist; ci.yml runs frontend tests + build checks only).
- 4.5 months old, one dominant maintainer, `evals/` is a stub, SECURITY.md
  and RELEASE_NOTES.md are stale (real record lives in CHANGELOG.md).
- Two divergent MCP servers (one not even packaged in the wheel); ghostlink
  is already the better MCP substrate.

## Why not SKIP — the lift list (all MIT, attribution required)

| Lift | Path | Size | Coupling | Serves |
|---|---|---|---|---|
| Provenance store | `semantica/provenance/` | ~3.8k LOC | `..utils` only, rdflib lazy | Hash-chained SQLite audit log + W3C PROV-O export → Dickie / agent-spend-guard audit trails. Strongest asset in the repo. |
| Conflict resolution | `semantica/conflicts/` | ~5k LOC | `..utils` only | 7 resolution strategies + source credibility → claims arbitration on the Dickie bus |
| Dedup/merge | `semantica/deduplication/` | ~4.6k LOC | `..utils` only | Weighted similarity + rule-based entity merge, no ML deps |
| Node-store pattern | `context/context_graph.py` + `agent_memory.py` | 4.3k + 2.3k | utils + entity_linker | node-ID-addressed, temporally-versioned graph + disk-persisted memory → P1 bounded context compaction skeleton |
| Fetch-by-id store | `vector_store/sqlite_vec_store.py` + `metadata_store.py` | ~1k | stdlib sqlite3 | zero-dep fetch-by-id |
| Temporal versioning | `change_management/` + `kg/temporal_query.py` | ~3.9k | utils only | checksummed snapshots + revision replay |
| Hardening references | `ingest/ssrf.py` (753), `triplet_store/sparql_escaping.py`, `graph_store/query_sanitize.py` | ~1k | — | DNS-pinned adapter (real TOCTOU closure) + injection sanitizers → ghostlink Phase 2 |

## Security posture note

The v0.6.5 fixes are real, not papered over: fail-closed auth (503 without
key, hmac.compare_digest), SSRF guard with resolved-IP pinning into the HTTP
adapter, centralized SPARQL/Cypher sanitizers at all call sites, SHA-pinned
Actions + Trusted Publishing + SLSA. Soft spots: WS accepts missing Origin,
unauthenticated `/build` stub, anonymous mode ships on in dev compose.

## Party stats

Scanner: inline code, 1,034 files. Auditor: 137k tokens, 58 tool uses.
Scout: 78k tokens, 33 tool uses (produced the helper bench in SKILL.md).
