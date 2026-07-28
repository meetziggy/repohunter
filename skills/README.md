# RepoHunter as a Skill (the reuse reflex for your agent)

The [MCP server](../MCP-INSTALL.md) gives your agent the **tools**. A **Skill** gives it the
**instinct** — it teaches the agent to reach for RepoHunter on its own, *before* it installs a
dependency or clones a repo, instead of only when you ask.

`repohunter/SKILL.md` is the skill. It's plain Markdown with frontmatter — portable across agents.

## Claude Code / Claude Desktop (Agent Skills)
Copy the folder into your skills directory:
```
mkdir -p ~/.claude/skills && cp -r skills/repohunter ~/.claude/skills/
```
Then add the tools once: `claude mcp add repohunter -- uvx repohunter-mcp`. The agent now checks a
repo before adopting it, without being told to.

## Codex CLI
Codex reads project guidance from `AGENTS.md` and connects MCP servers via `~/.codex/config.toml`:
```toml
[mcp_servers.repohunter]
command = "uvx"
args = ["repohunter-mcp"]
```
Paste the "When to reach for it" section of `repohunter/SKILL.md` into your `AGENTS.md` so Codex
knows to use it before adopting dependencies.

## Gemini CLI
Gemini reads context from `GEMINI.md` and supports MCP servers in `~/.gemini/settings.json`:
```json
{ "mcpServers": { "repohunter": { "command": "uvx", "args": ["repohunter-mcp"] } } }
```
Add the skill's guidance to your `GEMINI.md`.

## Any other agent
The skill is just Markdown — drop its guidance into whatever "system prompt / context / rules" file
your agent uses, and connect the MCP server per [MCP-INSTALL.md](../MCP-INSTALL.md). One server, one
skill, every agent.

> There is deliberately **no `curl | bash` universal installer** — that's the insecure pattern
> RepoHunter itself flags. The closest to one-click is `npx @smithery/cli install repohunter`.
