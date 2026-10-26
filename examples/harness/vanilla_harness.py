#!/usr/bin/env python3
"""A plain-vanilla agent harness that checks a repo with RepoHunter before adopting it.

No framework, no SDK: it starts RepoHunter's MCP server over stdio, speaks MCP's JSON-RPC
directly (initialize, tools/list, tools/call), and gates on the verdict. It demonstrates the
protocol against RepoHunter's own server; Claude Code, Codex, Cursor and VS Code speak the same
protocol through their own clients.

    python3 vanilla_harness.py rtk-ai/rtk
    python3 vanilla_harness.py atlanhq/camelot --block-on MAYBE
    echo $?            # 0 = allowed, 2 = blocked, 1 = error

Exit codes: only 0 means approved. Treat any nonzero exit, including 1 (error), as not approved.
The gate uses the score verdict only: the license and security overlays that the CLI applies are
not applied by the MCP evaluate_repo tool, so a repo with no license can still be allowed.

Set REPOHUNTER_MCP to change the server command (default: the pinned v0.2.1 release via uvx).
"""
import argparse
import json
import os
import shlex
import subprocess
import sys

SERVER = os.environ.get(
    "REPOHUNTER_MCP",
    "uvx --from git+https://github.com/meetziggy/repohunter@v0.2.1 repohunter-mcp")
RANK = {"GO": 0, "MAYBE": 1, "SKIP": 2}


def mcp_session(messages):
    """Send JSON-RPC messages to the server over stdio; return (replies keyed by id, stderr)."""
    try:
        proc = subprocess.run(shlex.split(SERVER),
                              input="".join(json.dumps(m) + "\n" for m in messages),
                              capture_output=True, text=True, timeout=300)
    except FileNotFoundError as e:
        raise RuntimeError("cannot start server %r: %s" % (SERVER, e))
    except subprocess.TimeoutExpired:
        raise RuntimeError("server did not finish within 300s")
    replies = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        replies[msg.get("id")] = msg
    return replies, proc.stderr


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a repo with RepoHunter, then allow or block it.")
    ap.add_argument("repo", help="owner/name or a github.com URL")
    ap.add_argument("--block-on", choices=["MAYBE", "SKIP"], default="SKIP",
                    help="lowest verdict that blocks (default: SKIP)")
    a = ap.parse_args(argv)

    try:
        replies, stderr = mcp_session([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "vanilla_harness", "version": "0.1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "evaluate_repo", "arguments": {"repo": a.repo}}},
        ])
    except RuntimeError as e:
        print("error:", e, file=sys.stderr)
        return 1
    tools = [t["name"] for t in replies.get(2, {}).get("result", {}).get("tools", [])]
    print("server tools:", ", ".join(tools) or "none")

    reply = replies.get(3, {})
    if "error" in reply:
        print("error: server rejected the call:", reply["error"].get("message", reply["error"]),
              file=sys.stderr)
        return 1
    call = reply.get("result", {})
    try:
        text = call["content"][0]["text"]
    except (KeyError, IndexError):
        print("error: no usable reply from RepoHunter", file=sys.stderr)
        if stderr.strip():
            print("server stderr:", stderr.strip()[-500:], file=sys.stderr)
        return 1
    if call.get("isError"):
        print("error:", text, file=sys.stderr)
        return 1
    try:
        r = json.loads(text)
    except ValueError:
        print("error: reply was not JSON:", text[:200], file=sys.stderr)
        return 1
    if r.get("verdict") not in RANK:
        print("error:", r.get("error", "unexpected reply"), file=sys.stderr)
        return 1

    print("%s  %s  %s/100" % (r["repo"], r["verdict"], r["scores"]["overall"]))
    print("  status   %s" % ("ARCHIVED" if r["archived"] else "last push " + r["last_push"]))
    print("  license  %s" % (r["license"] or "none found"))
    print("  fit      %s" % r["resource_fit"]["verdict"])
    if RANK[r["verdict"]] >= RANK[a.block_on]:
        print("BLOCKED: verdict %s is at or worse than --block-on %s" % (r["verdict"], a.block_on))
        return 2
    print("ALLOWED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
