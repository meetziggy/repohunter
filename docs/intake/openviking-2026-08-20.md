# Intake: volcengine/OpenViking — 2026-08-20

Full dickie party ran: scanner (code, 3,619 files) → auditor + scout (parallel) → fit-mapper.

## Verdict: LOGIC-GATHER (blocked from adoption by license)

The code is excellent and lands directly on P1 and ghostlink Phase 2. The license
makes adoption impossible. Read it, reimplement clean-room, never link it.

## The decisive fact

**AGPL-3.0.** Verified three ways: `LICENSE` is stock AGPL-3.0 text, `pyproject.toml`
declares `license = "AGPL-3.0"`, 1,077 source files carry `SPDX-License-Identifier: AGPL-3.0`.
No CLA exists, so no realistic relicensing path — ByteDance can't relicense either
without re-collecting permission from 61 contributors.

§13 network-source obligation triggers the moment a tenant hits a modified instance.
That breaks the resale constraint outright.

Worse for diligence: the license map is internally inconsistent. `sdk/python/pyproject.toml`
declares **no license at all** → defaults to repo AGPL — and `openviking` core hard-depends
on `openviking-sdk`. So even a thin client is encumbered until a maintainer clarifies.
Clean exceptions: `examples/openclaw-plugin` (MIT) and `sdk/typescript` (Apache-2.0).

## What it is

A "context database": the agent's entire context — memories, resources, skills, session
archives — exposed as a virtual filesystem under `viking://`, addressable with
`ls`/`tree`/`find`/`grep`/`glob`, served over HTTP + MCP. Every entry materialized at three
tiers: `.abstract.md` (L0), `.overview.md` (L1), full body (L2). Retrieval walks directories
top-down instead of flat vector kNN.

Python is the real core (171,712 LOC). Rust `ragfs` (45.7k) is the storage substrate loaded
in-process via PyO3 — **mandatory, no pure-Python fallback**. C++ vector engine vendored.
Rust `ov_cli` (44.4k) and React `web-studio` (52.3k) are clients. `bot/vikingbot` (54.8k) is
a second product bundled in-repo.

## Live facts

26.9k stars, 2.1k forks (scout, verified on page). 300 commits in the depth-300 window,
2026-07-16 → 2026-08-19 (32 active days, 9.4 commits/day), **61 distinct authors**, no author
above 10%, top-5 = 37%. Healthy bus factor, real team, squash-merge-only, GPG-signed.
v0.4.x / "Development Status :: 3 - Alpha" — API surface will move under you.
One author is literally named `agent <heaoxiang@bytedance.com>` (16 commits); they run
agent-authored PRs in production.

## Scan (full clone, 3,619 files)

47 raw findings, all benign on triage: `curl|sh` install docs for uv/ollama/nodesource,
`[system]` health-check strings, self-documenting auth docs, synthetic Slack fixture, and
a *defensive* test neutralizing forged `<memory>` tags. One real behavioral note, not a
vulnerability: `openviking_cli/utils/ollama.py:146` genuinely executes
`bash -c "curl -fsSL https://ollama.com/install.sh | sh"` at runtime on macOS/Linux when
installing Ollama. Know that before running the setup wizard.

Security defaults worth flagging: `cors_origins: ["*"]`, `encryption_enabled: False`,
`api_key_hashing_enabled: False` (keys stored unhashed by default). Mitigating: dev auth
mode refuses non-loopback hosts.

## Self-host reality: genuinely real

`backend: "local"` is the default (vendored C++ engine on local disk). One container +
optional Caddy — no Postgres, Redis, Kafka, or external vector DB. Setup wizard is
explicitly Ollama-first and targets macOS/Apple Silicon with RAM-tiered model defaults.
Telemetry off by default, no phone-home. **No volces.com endpoint in any required library
path** — the TOS bucket appears only in `.github/workflows/api_test.yml` (CI convenience);
`setup.py` makes zero network calls.

Cost: 58 direct Python deps / 310 resolved, including `scrapy` and — non-optionally —
`volcengine` and `volcengine-python-sdk`. 639 Rust crates. Local GGUF default is a
**Chinese** embedding model (bge-small-zh); use the Ollama path for English.

Without an LLM: VFS, grep/glob, snapshots, tool-result externalization, dense retrieval,
MCP and OAuth all still work. Session→memory extraction hard-fails; L0/L1 tier generation
is VLM-produced, so the headline token-saving degrades to L2-only.

## The lift list (read-and-reimplement — AGPL, do not copy)

| Lift | Path | Size | Serves |
|---|---|---|---|
| **Tool-result synopsis** | `session/tool_result_synopsis.py` | 489 LOC, zero internal imports | **P1.** Deterministic, LLM-free typed synopsis (json/csv/yaml/xml/code/text) with structure outline + head/tail sample. Highest value-per-LOC in the repo. "Deterministic work is CODE not agents" made literal. |
| **Tool-result store** | `session/tool_result_store.py` | 323 LOC | **P1.** Content-addressed node IDs `tr_<tool>_<sha256[:16]>`, sidecar metadata, offset/limit paging with `has_more`, substring search with offsets. |
| **OAuth 2.1 on MCP** | `docs/design/mcp-oauth2-1.md` + `server/oauth/` | 1,744 LOC | **ghostlink Phase 2.** Three decisions worth taking wholesale: delegate the protocol to the official SDK's `mcp.server.auth`; opaque tokens + SQLite, zero crypto of your own; token prefixes (`ovat_`/`ovrt_`) as routing hints with the DB still authoritative. Plus RFC 9728 PRM, cross-device 6-char code flow, and `authorizing_key_fp` — rotating the API key invalidates the whole derived token chain. |
| **Context assembler** | `retrieve/context_assembler/` | ~1,800 LOC, 11 files | **P1.** Single round-trip assembly, token budget, tier degradation, per-purpose quotas. `ledger.py` (173 LOC) is a cross-turn dedup ledger with turn-distance cooldown — a pattern I haven't seen elsewhere. |
| **Envelope escape** | `retrieve/context_assembler/render.py` | **49 LOC** | Provenance-forgery defense for XML-envelope context injection. Copy the idea in 10 minutes; the test is the spec. |
| **MCP stdio→HTTP proxy** | `agent-plugins/servers/shared/mcp-proxy-core.mjs` | 504 LOC, node stdlib only | **ghostlink.** Session-id retry, SSE frame parsing, protocol-clean stdio, concurrency semaphore, credential hot-reload. |
| **Billing idempotency** | `usage_reporter/models.py` | 60 LOC | **P1 metering.** `event_id = "ue_" + sha256(identity_tuple)` — duplicate emission is safe. 20 lines of real idea. |
| **Tenant metric caps** | `metrics/account_dimension.py` | ~200 LOC | Per-tenant Prometheus labels with `__unknown__`/`__overflow__` buckets — protects the metrics backend from unbounded tenant cardinality. |

Cleanest to actually *use*: `examples/openclaw-plugin` (**MIT**, 40.6k TS, targets the same
OpenClaw runtime SpookyJuice builds on) and `sdk/typescript` (**Apache-2.0**).

## Memory poisoning: honest read

The defense in `render.py` is a correct, minimal, deterministic **provenance-forgery**
defense — it escapes `<memory>` tags so a body can't forge a sibling entry with its own
uri/type/score. Good engineering, properly tested.

It is **not** poisoning protection. `ignore previous instructions` passes through verbatim
as legitimate text. There is no semantic injection detection anywhere in `parse/`, `ingest/`,
or `session/memory/`. Blast-radius limiters are per-peer namespacing and PII placeholdering.
The design is honest about which guarantee it provides.

## Metering gap

`usage_reporter/` is a well-designed billing-event *emitter* with a pluggable sink protocol.
But `tenant_id` is shaped for a Volcengine marketplace pipeline (`OV_RESOURCE_ID` required at
construction), and there is **no rate limiting, no quota enforcement, no spend ceiling, no
plan/tier concept anywhere**. It does not serve P1-metering or P2-spend-ceilings.

## Test/CI: the weakest signal

622 test files, **6,734 test functions** — and **public CI does not gate on them**.
`_test_lite.yml` runs exactly 4 files. `_test_full.yml` never invokes pytest and is
**orphaned** (no workflow references it). `api_test.yml` is the real suite but needs
Volcengine secrets, so it cannot pass on a fork. Verify locally before trusting anything lifted.

## Party stats

Scanner: inline code, 3,619 files. Auditor: 182k tokens, 96 tool uses. Scout: 91k tokens, 41 tool uses.
