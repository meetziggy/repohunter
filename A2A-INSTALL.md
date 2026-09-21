# RepoHunter agent peer

RepoHunter can run as an authenticated, read-only peer for the SpookyJuice hub.
It reuses the same evidence functions as the MCP server and adds no LLM call.

## Protocol status

The adapter implements SpookyJuice's current `0.1-spooky` custom binding:

- authenticated `GET {base}/.well-known/agent-card.json`
- authenticated `POST {base}/tasks` with `{ "id", "skill", "input" }`

It intentionally does **not** claim Linux Foundation A2A 1.0 conformance. The
released protocol uses a different Agent Card and `SendMessage`/`message:send`
wire contract. The custom binding is labeled in the Agent Card so clients can
make an informed compatibility decision.

## Security model

- The service binds to `127.0.0.1` by default.
- Remote access goes through tailnet-only Tailscale Serve, never Funnel.
- Discovery and tasks require a dedicated bearer token of at least 32 characters.
- Only the three read-only RepoHunter skills are callable.
- Requests are capped at 64 KiB; provider failures return generic errors.
- Tokens are never included in Agent Cards, task results, or logs.

## Local runtime

Create a protected runtime file outside the repository:

```sh
runtime_dir="$HOME/Library/Application Support/RepoHunter"
mkdir -p "$runtime_dir"
chmod 700 "$runtime_dir"
umask 077
printf 'REPOHUNTER_AGENT_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$runtime_dir/agent.env"
```

Run directly:

```sh
./scripts/run-agent.sh
```

The macOS deployment uses `~/Library/LaunchAgents/dev.repohunter.agent.plist`
with `RunAtLoad` and `KeepAlive`. Logs are written under
`~/Library/Logs/RepoHunter/`.

Expose the loopback service privately:

```sh
tailscale serve --bg --https=8765 http://127.0.0.1:8765
```

Do not replace `serve` with `funnel`.

## SpookyJuice registration

Add a target to the protected `A2A_TARGETS` runtime value used by intelligence:

```json
{
  "name": "repohunter",
  "url": "https://dickie.taild93f81.ts.net:8765/a2a",
  "token": "stored out of band"
}
```

Recreate only the intelligence service so it reloads the environment. Then use
the hub's `peer_discover` before `peer_call`; do not guess skill names.

## Verification

The live acceptance sequence is:

1. `GET /health` succeeds locally.
2. Authenticated discovery succeeds from the SpookyJuice VPS.
3. Authenticated `evaluate_repo` succeeds from the VPS.
4. SpookyJuice `peer_discover(repohunter)` returns three OBSERVE skills.
5. SpookyJuice `peer_call(repohunter, evaluate_repo, …)` returns a real evidence result.
6. The hub audit log records `PEER_CALL_OUT` success without request content or tokens.

## Rollback

1. Remove the `repohunter` target from `A2A_TARGETS` and recreate intelligence.
2. Run `tailscale serve --https=8765 off`.
3. Run `launchctl bootout gui/$(id -u)/dev.repohunter.agent`.

No database migration or Home Base record mutation is involved.
