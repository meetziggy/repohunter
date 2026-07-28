#!/usr/bin/env python3
"""RepoHunter MCP server — the reuse-decision skill layer for AI agents.

Speaks MCP over stdio (newline-delimited JSON-RPC 2.0). Stdlib only — no dependencies.
Every result is REAL GitHub data + RepoHunter's transparent, labeled scores. No fabricated
numbers. No verdicts on people. Set GITHUB_TOKEN in the env to raise the rate limit / read private.

Skills:
  evaluate_repo   — should I reuse this repo? real stats + score + resource-fit + GO/MAYBE/SKIP
  find_repos      — find reuse candidates for a need (live GitHub search, ranked)
  portfolio_scan  — a GitHub user/org's public work as FACTS + patterns (never a judgment of the person)

MIT (c) 2026 Chris Gorzelic.
"""
import json
import math
import os
import re
import sys
import time
import urllib.request
import urllib.parse

UA = "RepoHunter-MCP/0.1"
GHTOK = os.environ.get("GITHUB_TOKEN", "")
NOW = int(time.time())
NOTE_SCORE = ("Scores are RepoHunter's transparent heuristic over public GitHub data — guidance, not a "
              "guarantee. Verify (especially security + license) before adopting.")


def gh(path):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if GHTOK:
        req.add_header("Authorization", "Bearer " + GHTOK)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _days(iso):
    try:
        return max(0, int((NOW - time.mktime(time.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S"))) / 86400))
    except Exception:
        return 9999


def score(m, keywords=None):
    kws = keywords or []
    text = " ".join([m.get("description") or "", " ".join(m.get("topics") or []),
                     m.get("name") or "", m.get("language") or ""]).lower()
    rel = min(100, 20 + sum(6 for k in kws if k.lower() in text))
    stars = m.get("stargazers_count", 0)
    pop = min(100, int(math.log10(stars + 1) * 22))
    fd = _days(m.get("pushed_at"))
    fresh = 100 if fd < 30 else 80 if fd < 90 else 55 if fd < 365 else 25
    spdx = (m.get("license") or {}).get("spdx_id") or ""
    health = 70 + (15 if spdx and spdx != "NOASSERTION" else 0) + (10 if stars > 1000 else 0) - (40 if m.get("archived") else 0)
    health = max(0, min(100, health))
    age = _days(m.get("created_at"))
    mat = min(100, (20 if age > 365 else 5) + min(50, int(math.log10(stars + 1) * 12)))
    overall = int(rel * 0.4 + pop * 0.18 + fresh * 0.17 + health * 0.13 + mat * 0.12) if kws \
        else int(pop * 0.3 + fresh * 0.25 + health * 0.25 + mat * 0.2)
    verdict = "SKIP" if m.get("archived") else "GO" if overall >= 68 else "MAYBE" if overall >= 45 else "SKIP"
    out = {"popularity": pop, "freshness": fresh, "health": health, "maturity": mat, "overall": overall, "verdict": verdict}
    if kws:
        out["relevance"] = rel
    return out


def resource_fit(m):
    text = " ".join([m.get("description") or "", " ".join(m.get("topics") or []), m.get("language") or ""]).lower()
    lang = (m.get("language") or "").lower()
    if re.search(r"cuda|gpu-only|a100|h100|training|fine-tun|70b|kubernetes|cluster", text):
        return {"verdict": "heavy", "note": "wants a GPU / lots of RAM"}
    if lang in ("c", "rust", "go", "zig", "c++"):
        return {"verdict": "runs easily", "note": "compiled, small footprint"}
    if re.search(r"pytorch|tensorflow|\bmodel\b|inference|\bllm\b|embedding", text):
        return {"verdict": "runs with headroom", "note": "local ML — needs RAM"}
    return {"verdict": "runs easily", "note": "ordinary app resources"}


def _kws_from(project):
    return [w for w in re.findall(r"[a-z]+", (project or "").lower()) if len(w) > 3][:12] if project else None


# ── skills ─────────────────────────────────────────────────────────────────────
def skill_evaluate_repo(args):
    slug = re.sub(r".*github\.com/", "", args.get("repo", "")).replace(".git", "").strip("/")
    m = re.match(r"^([\w.\-]+/[\w.\-]+)", slug)
    if not m:
        return {"error": "pass owner/name or a github.com URL"}
    d = gh("/repos/" + m.group(1))
    s = score(d, _kws_from(args.get("project")))
    return {"repo": d.get("full_name"), "url": d.get("html_url"), "description": d.get("description"),
            "stars": d.get("stargazers_count"), "language": d.get("language"),
            "license": (d.get("license") or {}).get("spdx_id"), "last_push": (d.get("pushed_at") or "")[:10],
            "archived": bool(d.get("archived")), "verdict": s["verdict"], "scores": s,
            "resource_fit": resource_fit(d), "_note": NOTE_SCORE}


def skill_find_repos(args):
    q = (args.get("query") or args.get("need") or "").strip()
    if not q:
        return {"error": "pass a 'query' describing what you need"}
    res = gh("/search/repositories?sort=stars&per_page=8&q=" + urllib.parse.quote(q))
    kws = _kws_from(q)
    out = []
    for d in res.get("items", []):
        s = score(d, kws)
        out.append({"repo": d.get("full_name"), "url": d.get("html_url"),
                    "description": (d.get("description") or "")[:140], "stars": d.get("stargazers_count"),
                    "language": d.get("language"), "verdict": s["verdict"], "overall": s["overall"]})
    return {"query": q, "candidates": out,
            "_note": "Ranked by RepoHunter's heuristic over live GitHub search — evaluate_repo the strongest before adopting."}


def skill_portfolio_scan(args):
    user = (args.get("user") or "").strip().strip("/")
    if not user:
        return {"error": "pass a GitHub 'user' or org"}
    repos = gh("/users/%s/repos?per_page=100&sort=updated&type=owner" % urllib.parse.quote(user))
    if not isinstance(repos, list):
        return {"error": "could not read that user's public repos"}
    own = [r for r in repos if not r.get("fork")]
    langs, topics, total_stars, recent = {}, {}, 0, 0
    for r in own:
        lang = r.get("language")
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
        for t in (r.get("topics") or []):
            topics[t] = topics.get(t, 0) + 1
        total_stars += r.get("stargazers_count", 0)
        if _days(r.get("pushed_at")) < 180:
            recent += 1
    top = sorted(own, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:5]
    return {"user": user, "public_repos": len(own), "total_stars": total_stars,
            "primary_languages": sorted(langs, key=langs.get, reverse=True)[:5],
            "focus_topics": sorted(topics, key=topics.get, reverse=True)[:8],
            "active_repos_last_6mo": recent,
            "top_work": [{"repo": r.get("full_name"), "stars": r.get("stargazers_count"),
                          "description": (r.get("description") or "")[:80]} for r in top],
            "_note": ("FACTS + patterns from public repos only — a description of the WORK, NOT an "
                      "assessment of the person, and NOT a competence or hiring judgment.")}


SKILLS = {
    "evaluate_repo": (skill_evaluate_repo,
        "Should I reuse this repo? Real GitHub stats + RepoHunter's score, resource-fit, and GO/MAYBE/SKIP "
        "verdict. Optionally pass your project context for a relevance read.",
        {"type": "object", "properties": {
            "repo": {"type": "string", "description": "owner/name or a github.com URL"},
            "project": {"type": "string", "description": "optional: describe your project for a relevance read"}},
         "required": ["repo"]}),
    "find_repos": (skill_find_repos,
        "Find reuse candidates for a need via live GitHub search, ranked by RepoHunter's heuristic.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "what you need, e.g. 'python pdf table extraction'"}},
         "required": ["query"]}),
    "portfolio_scan": (skill_portfolio_scan,
        "Summarize a GitHub user/org's public work as FACTS + patterns (languages, focus, activity, top "
        "repos). Facts only — never a judgment of the person.",
        {"type": "object", "properties": {
            "user": {"type": "string", "description": "a GitHub username or org"}},
         "required": ["user"]}),
}


# ── MCP stdio transport (newline-delimited JSON-RPC 2.0) ───────────────────────
def _send(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            _send(mid, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "repohunter", "version": "0.1.0"},
                        "capabilities": {"tools": {}}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send(mid, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (f, d, s) in SKILLS.items()]})
        elif method == "tools/call":
            p = msg.get("params", {}) or {}
            sk = SKILLS.get(p.get("name"))
            if not sk:
                _send(mid, error={"code": -32602, "message": "unknown tool: %s" % p.get("name")})
                continue
            try:
                out = sk[0](p.get("arguments", {}) or {})
                _send(mid, {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]})
            except Exception as e:
                _send(mid, {"content": [{"type": "text", "text": "error: %s" % str(e)[:200]}], "isError": True})
        elif mid is not None:
            _send(mid, error={"code": -32601, "message": "method not found"})


if __name__ == "__main__":
    main()
