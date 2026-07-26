# Contributing to RepoHunter

Thanks for being here. RepoHunter exists to help people **reuse instead of reinvent** — and to send
credit home to the maintainers whose work makes that possible. Contributions in that spirit are welcome.

> Heads up: RepoHunter is **owned and maintained autonomously by an AI agent (Ziggy)**, in the open,
> with a human (Chris) steering. That means fast, transparent iteration — and that issues/PRs may be
> triaged and answered by the agent. Be patient with the rough edges; it's early.

## Ways to help
- **Try it and file honest issues** — especially where a dossier, resource-fit check, or plan is *wrong*.
- **Suggest repos worth evaluating** — open an issue with the repo and why it's relevant.
- **Improve the docs** — if something was confusing on your first run, that's a bug worth fixing.
- **Code** — bug fixes, new ingest sources, better scoring signals, provider backends.

## Dev setup
```bash
git clone https://github.com/meetziggy/repohunter
cd repohunter
cp config.example.json config.json     # describe a project + pick your LLM backend
python3 repohunter.py refresh          # build the store
python3 repohunter.py serve            # → http://127.0.0.1:8130
```
It's **stdlib Python** — no build step. The LLM backend is pluggable (local Ollama by default, or your
OpenAI/OpenRouter key via `config.json`). Keep it dependency-light unless there's a strong reason not to.

## Ground rules
- **Promote authors, never strip them.** Anything that surfaces a repo must link back to it. No
  rehosting, no credit-erasing.
- **Approve-first, always.** RepoHunter *plans*; it never installs or runs things behind a user's back.
  Integration is two-gate: plan → human approval → build in isolation → human approval. Keep it that way.
- **Local-first & honest.** No telemetry that phones home without consent. Verdicts should be truthful,
  including "SKIP" and "build it yourself."
- **Be kind.** Critique code, respect people — the maintainers whose repos we evaluate included.

## Pull requests
1. Open (or comment on) an issue first for anything non-trivial, so we agree on direction.
2. Keep PRs focused and small; explain the *why*.
3. Match the existing style. No new heavy dependencies without discussion.
4. By contributing, you agree your work is licensed under the repo's **MIT License**.

## Reporting security issues
Please **don't** open a public issue for a vulnerability. Use GitHub's private security advisory on the
repo, or the contact in the repo profile.

Thank you for helping keep the commons alive. 🪲
