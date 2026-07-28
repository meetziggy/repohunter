# Install the RepoHunter MCP server

RepoHunter is an **MCP server** — a set of skills your AI coding agent can call *before* it adopts a
repo. It runs **locally, on your machine** (free, private, your token never leaves your box). Stdlib
Python — no dependencies.

**Skills:** `evaluate_repo` (should I reuse this? real stats + score + resource-fit + GO/MAYBE/SKIP) ·
`find_repos` (reuse candidates for a need) · `portfolio_scan` (a user/org's public work as facts).

> There is **no `curl | bash`** here — that's an insecure pattern (and one RepoHunter itself flags).
> It's a normal MCP server: point your client at it with a small config block.

## The command

Once it's on PyPI (registry publish pending):
```
uvx repohunter-mcp
```

Or run it straight from a clone (works today):
```
python3 /path/to/repohunter/repohunter_mcp.py
```

Optional: set `GITHUB_TOKEN` in the `env` for higher rate limits / private-repo reads. It stays on your
machine and is passed straight to GitHub — RepoHunter never transmits or stores it.

## Add it to your agent (copy-paste)

The config block is the same everywhere — just the file it goes in differs.

```json
{
  "mcpServers": {
    "repohunter": {
      "command": "uvx",
      "args": ["repohunter-mcp"],
      "env": { "GITHUB_TOKEN": "" }
    }
  }
}
```

From a clone instead, swap the command:
```json
{ "command": "python3", "args": ["/absolute/path/to/repohunter_mcp.py"], "env": { "GITHUB_TOKEN": "" } }
```

Where that block goes, per client:
- **Claude Desktop** — Settings → Developer → Edit Config (`claude_desktop_config.json`).
- **Claude Code** — `claude mcp add repohunter -- uvx repohunter-mcp`, or a project `.mcp.json`.
- **Cursor** — Settings → MCP → Add, or `.cursor/mcp.json`.
- **Cline / Roo** — the MCP Servers panel → Configure.
- **Windsurf** — Settings → Cascade → MCP (`mcp_config.json`).
- **VS Code** — `.vscode/mcp.json`, or install natively from the **GitHub MCP Registry** (`@mcp` in Extensions).
- **Zed** — `settings.json` → `context_servers`.
- **Goose** — Settings → Extensions → Add (command-line extension).

## Find it in the directories

Once published, RepoHunter is listed on the **Official MCP Registry**, which feeds **Smithery,
PulseMCP, Docker Hub, and the GitHub MCP Registry**. The easiest cross-client install:
```
npx @smithery/cli install repohunter
```
Smithery can also host a **remote** version (their Gateway) if you'd rather not run it locally — that's
the "run it in the cloud" option, no local install.

## Verify it works
```
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | python3 repohunter_mcp.py
```
You should see the server info and the three skills.
