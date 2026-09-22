# RepoHunter skills (the reuse reflex for your agent)

The [MCP server](../MCP-INSTALL.md) gives your agent the **tools**. A **skill** gives it the
**instinct** — it teaches the agent to reach for RepoHunter on its own, *before* it installs a
dependency or clones a repo, instead of only when you ask.

Two skills ship here, both plain Markdown with frontmatter, portable across agents:

| Skill | What it does |
|---|---|
| `repohunter/` | The reflex. Check a repo before adopting it — real stats, resource fit, GO/MAYBE/SKIP. |
| `repo-intake/` | The full gate. Scan → triage → evaluate → fit-map → INTEGRATE / CHERRY-PICK / LOGIC-GATHER / SKIP, run by a party of specialist agents. Includes the party spec. |

## The one-command install (Claude Code)

This repo is its own plugin marketplace, so both skills **and** the MCP server install together:

```
/plugin marketplace add meetziggy/repohunter
/plugin install repohunter
```

That is the whole setup. Skills arrive namespaced as `/repohunter:repohunter` and
`/repohunter:repo-intake`; the MCP server is wired from the bundled `.mcp.json`.

## Or install the skills alone

From a clone or an sdist:

```
repohunter install-skill            # -> ~/.claude/skills/
repohunter install-skill ./somewhere-else
```

> Two skill stores exist and they do **not** sync. `~/.claude/skills/` serves Claude Code;
> a chat profile store is separate. Installing to one does not make the skill appear in the
> other — upload the `.skill` bundle from the release page for that.

## Claude Code / Claude Desktop (Agent Skills)
Prefer the plugin install above. To do it by hand:
```
mkdir -p ~/.claude/skills && cp -r skills/repohunter skills/repo-intake ~/.claude/skills/
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
