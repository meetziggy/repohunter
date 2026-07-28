# RepoHunter badge service (Cloudflare Worker)

A tiny, free edge worker that serves a **live, self-updating** RepoHunter badge + report card for any
**public** GitHub repo. No auth, no database. The owner embeds it but **cannot edit the verdict** —
that's exactly why it's trustworthy.

- `GET /badge/:owner/:name.svg` — shields-style badge: `repohunter | GO 82`
- `GET /card/:owner/:name.svg` — shareable report card (facts + scores + verdict)
- `GET /health` — `ok`

The score is a **transparent heuristic over live GitHub data — guidance, not a guarantee, and NOT a
safety/security rating** (that layer ships only after validation). Same math as `repohunter_mcp.py`.

## Deploy
```
cd worker
npx wrangler deploy            # provisions img.repohunter.dev (custom_domain in wrangler.toml)
# optional, higher GitHub rate limit (public badges work without it):
npx wrangler secret put GITHUB_TOKEN
```
Edge-caches each repo for 30 min, so a README badge won't hammer the GitHub API.

## Embed (README)
```md
[![RepoHunter](https://img.repohunter.dev/badge/OWNER/NAME.svg)](https://repohunter.dev)
```
