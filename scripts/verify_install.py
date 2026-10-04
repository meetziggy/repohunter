#!/usr/bin/env python3
"""Verify every published install method actually yields a working RepoHunter.

Each method runs in its own throwaway sandbox (temp config dirs for Claude Code, Codex,
VS Code and uv), so nothing touches the real setup on this machine. A method passes
only when the server it installs completes an MCP handshake and lists its tools, or
the CLI it installs produces a real scan.

    python3 scripts/verify_install.py                       # test what's on GitHub main
    python3 scripts/verify_install.py --source .            # test this checkout instead
    python3 scripts/verify_install.py --only cli,plugin     # a subset

Needs uv on PATH. Methods whose client CLI (claude, codex, code) is missing are skipped.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

GIT = "git+https://github.com/meetziggy/repohunter"
REPO = "meetziggy/repohunter"
SCAN_REPO = "camelot-dev/camelot"
TOOLS = {"evaluate_repo", "find_repos", "portfolio_scan"}


def run(cmd, env=None, timeout=300, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)


def env_with(**extra):
    e = dict(os.environ)
    e.update({k: str(v) for k, v in extra.items()})
    return e


def handshake(command, args, env=None):
    """Start a stdio MCP server, initialize it, list its tools. Returns (ok, detail)."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    try:
        r = subprocess.run([command] + list(args), input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, timeout=300, env=env)
    except Exception as e:
        return False, "could not start: %s" % e
    for line in r.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == 2:
            names = {t["name"] for t in (msg.get("result") or {}).get("tools", [])}
            missing = TOOLS - names
            return (not missing), ("tools: " + ", ".join(sorted(names)) if not missing
                                   else "missing tools: " + ", ".join(sorted(missing)))
    return False, "no tools/list reply; stderr: %s" % (r.stderr.strip().splitlines() or ["(none)"])[-1]


def server_args(src):
    return ["--from", src, "repohunter-mcp"]


# ── methods ─────────────────────────────────────────────────────────────────
def m_cli(src, tmp):
    r = run(["uvx", "--from", src, "repohunter", "scan", SCAN_REPO], cwd=tmp)
    line = (r.stdout.strip().splitlines() or [""])[0]
    ok = r.returncode == 0 and SCAN_REPO in line and "file(s) scanned" in line and "UNKNOWN" not in line
    return ok, line or r.stderr.strip()[-200:]


def m_uv_tool(src, tmp):
    e = env_with(UV_TOOL_DIR=os.path.join(tmp, "tools"), UV_TOOL_BIN_DIR=os.path.join(tmp, "bin"))
    r = run(["uv", "tool", "install", src], env=e)
    if r.returncode != 0:
        return False, "uv tool install failed: " + r.stderr.strip()[-200:]
    bin_dir = os.path.join(tmp, "bin")
    ok, detail = handshake(os.path.join(bin_dir, "repohunter-mcp"), [], env=e)
    s = run([os.path.join(bin_dir, "repohunter"), "scan", SCAN_REPO], env=e, cwd=tmp)
    scan_ok = "file(s) scanned" in s.stdout and "UNKNOWN" not in s.stdout
    return ok and scan_ok, detail + ("; scan ok" if scan_ok else "; scan failed: " + s.stdout[:120])


def m_mcp_json(src, tmp):
    """Claude Desktop, Windsurf, Zed, Cline and other JSON-config clients: the published block."""
    cfg = {"mcpServers": {"repohunter": {"command": "uvx", "args": server_args(src)}}}
    s = cfg["mcpServers"]["repohunter"]
    return handshake(s["command"], s["args"])


def m_claude_mcp_add(src, tmp):
    e = env_with(CLAUDE_CONFIG_DIR=os.path.join(tmp, "claude"))
    r = run(["claude", "mcp", "add", "-s", "user", "repohunter", "--", "uvx"] + server_args(src), env=e, cwd=tmp)
    if r.returncode != 0:
        return False, "add failed: " + (r.stderr or r.stdout).strip()[-200:]
    ls = run(["claude", "mcp", "list"], env=e, cwd=tmp)
    line = next((l for l in ls.stdout.splitlines() if l.startswith("repohunter")), ls.stdout.strip()[-200:])
    return ("Connected" in line), line


def m_claude_plugin(src, tmp):
    e = env_with(CLAUDE_CONFIG_DIR=os.path.join(tmp, "claude"))
    market = src if os.path.isdir(src) else REPO
    r = run(["claude", "plugin", "marketplace", "add", market], env=e, cwd=tmp)
    if r.returncode != 0:
        return False, "marketplace add failed: " + (r.stderr or r.stdout).strip()[-200:]
    r = run(["claude", "plugin", "install", "repohunter@repohunter"], env=e, cwd=tmp)
    if r.returncode != 0:
        return False, "plugin install failed: " + (r.stderr or r.stdout).strip()[-200:]
    ls = run(["claude", "mcp", "list"], env=e, cwd=tmp)
    line = next((l for l in ls.stdout.splitlines() if "repohunter" in l), ls.stdout.strip()[-200:])
    return ("Connected" in line), line


def m_codex(src, tmp):
    home = os.path.join(tmp, "codex")
    os.makedirs(home)
    e = env_with(CODEX_HOME=home)
    r = run(["codex", "mcp", "add", "repohunter", "--", "uvx"] + server_args(src), env=e)
    if r.returncode != 0:
        return False, "add failed: " + (r.stderr or r.stdout).strip()[-200:]
    import tomllib
    with open(os.path.join(home, "config.toml"), "rb") as f:
        s = tomllib.load(f)["mcp_servers"]["repohunter"]
    return handshake(s["command"], s.get("args", []))


def m_cursor(src, tmp):
    """Rebuild the homepage's Cursor install link, decode it as Cursor would, run the result."""
    server = {"command": "uvx", "args": server_args(src)}
    link = ("cursor://anysphere.cursor-deeplink/mcp/install?name=repohunter&config="
            + urllib.parse.quote(base64.b64encode(json.dumps(server).encode()).decode()))
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    s = json.loads(base64.b64decode(q["config"][0]))
    ok, detail = handshake(s["command"], s["args"])
    return ok, detail + " (link decoded; the Cursor app itself was not driven)"


def m_vscode(src, tmp):
    data = os.path.join(tmp, "vscode")
    spec = {"name": "repohunter", "command": "uvx", "args": server_args(src)}
    r = run(["code", "--user-data-dir", data, "--add-mcp", json.dumps(spec)], timeout=120)
    path = os.path.join(data, "User", "mcp.json")
    if not os.path.exists(path):
        return False, "VS Code did not write mcp.json: " + (r.stderr or r.stdout).strip()[-200:]
    with open(path) as f:
        s = json.load(f)["servers"]["repohunter"]
    return handshake(s["command"], s.get("args", []))


METHODS = [
    ("cli", "Terminal: uvx … repohunter scan", m_cli, None),
    ("uv-tool", "uv tool install (CLI + server)", m_uv_tool, None),
    ("json", "MCP JSON (Claude Desktop & others)", m_mcp_json, None),
    ("claude", "Claude Code: claude mcp add", m_claude_mcp_add, "claude"),
    ("plugin", "Claude Code plugin", m_claude_plugin, "claude"),
    ("codex", "Codex: codex mcp add", m_codex, "codex"),
    ("cursor", "Cursor install link", m_cursor, None),
    ("vscode", "VS Code: --add-mcp", m_vscode, "code"),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=GIT, help="uvx --from source: git URL (default) or a local path")
    ap.add_argument("--only", default="", help="comma-separated method keys: " + ",".join(k for k, *_ in METHODS))
    a = ap.parse_args(argv)
    src = os.path.abspath(a.source) if os.path.isdir(a.source) else a.source
    want = set(filter(None, a.only.split(",")))
    if not shutil.which("uv"):
        print("uv is required"); return 2
    results = []
    for key, label, fn, needs in METHODS:
        if want and key not in want:
            continue
        if needs and not shutil.which(needs):
            results.append((label, "SKIP", "%s not installed" % needs)); continue
        tmp = tempfile.mkdtemp(prefix="rh-verify-%s-" % key)
        try:
            ok, detail = fn(src, tmp)
        except Exception as e:
            ok, detail = False, "%s: %s" % (type(e).__name__, e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        results.append((label, "PASS" if ok else "FAIL", detail))
        print("%-4s  %-36s %s" % (results[-1][1], label, detail), flush=True)
    failed = [r for r in results if r[1] == "FAIL"]
    print("\n%d passed, %d failed, %d skipped (source: %s)" % (
        sum(r[1] == "PASS" for r in results), len(failed), sum(r[1] == "SKIP" for r in results), src))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
