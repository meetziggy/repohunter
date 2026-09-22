#!/usr/bin/env python3
"""repohunter_artifacts.py — artifact-level evaluation for agent-facing code.

RepoHunter scores repositories. This scores the things *inside* them that an
agent actually loads at runtime: skills, subagents, slash commands, hooks, MCP
servers, plugins and marketplaces.

The distinction matters. A repo verdict answers "is this project worth
adopting". An artifact verdict answers three different questions:

  1. What does it cost?   Every SKILL.md that triggers spends context forever.
  2. What can it reach?   allowed-tools is the blast radius. Omitted == all.
  3. Is it safe to read?  A skill body is an instruction stream aimed at the
                          agent that loads it. Prompt injection here is not
                          theoretical, it is the delivery mechanism.

Stdlib only, to match repohunter.py. Python 3.9 compatible.

  python3 repohunter_artifacts.py anthropics/skills
  python3 repohunter_artifacts.py mattpocock/skills --json
  python3 repohunter_artifacts.py obra/superpowers --store --max-artifacts 80
"""
import argparse, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import repohunter as RH  # noqa: E402  (config, gh(), scan_text() live there)

DATA = os.path.join(HERE, "data")
STORE = os.path.join(DATA, "artifactstore.json")
UA = getattr(RH, "UA", "repohunter-artifacts")
SCHEMA = 1

# ── what counts as an artifact ────────────────────────────────────────────────
# Ordered: first match wins, so the specific patterns precede the loose ones.
KIND_RULES = [
    ("skill",       re.compile(r"(?:^|/)SKILL\.md$", re.I)),
    ("agent",       re.compile(r"(?:^|/)(?:\.claude/)?agents/[^/]+\.md$", re.I)),
    ("command",     re.compile(r"(?:^|/)(?:\.claude/)?commands/.+\.md$", re.I)),
    ("hook",        re.compile(r"(?:^|/)(?:\.claude/)?hooks/[^/]+\.(?:json|sh|py|js|ts)$", re.I)),
    ("marketplace", re.compile(r"(?:^|/)\.claude-plugin/marketplace\.json$", re.I)),
    ("plugin",      re.compile(r"(?:^|/)\.claude-plugin/plugin\.json$", re.I)),
    ("mcp-config",  re.compile(r"(?:^|/)\.?mcp\.json$", re.I)),
    ("mcp-server",  re.compile(r"(?:^|/)(?:[a-z0-9_\-]*mcp[a-z0-9_\-]*_?server|server)\.(?:py|ts|js|mjs)$", re.I)),
]

# Files that are documentation about artifacts, not artifacts. Cheap noise filter.
SKIP_PATHS = re.compile(
    r"(?:^|/)(?:node_modules|\.git|dist|build|vendor|site-packages|__pycache__|"
    r"test|tests|fixtures|examples?/output)/", re.I)

MAX_FETCH_BYTES = 200_000

# ── tool-surface classification ───────────────────────────────────────────────
# An agent artifact's real privilege is the union of the tools it may call.
SURFACE = [
    ("shell",       re.compile(r"^(?:Bash|Shell|Execute|run_command|execute_command)", re.I)),
    ("write",       re.compile(r"^(?:Write|Edit|MultiEdit|NotebookEdit|create_file|write_file)", re.I)),
    ("network",     re.compile(r"^(?:WebFetch|WebSearch|fetch|curl|http)", re.I)),
    ("read",        re.compile(r"^(?:Read|Glob|Grep|Search|List|View)", re.I)),
    ("delegation",  re.compile(r"^(?:Task|Agent|Workflow|SendMessage)", re.I)),
    ("mcp",         re.compile(r"^mcp__", re.I)),
]
RISKY_SURFACE = {"shell", "write", "network", "delegation"}

# Capability signals inside the body text — what the artifact tells the agent to do.
CAPABILITY = [
    ("outbound-network", re.compile(r"\b(?:curl|wget|requests\.(?:get|post)|fetch\(|urllib\.request|axios)\b", re.I)),
    ("credential-read",  re.compile(r"\b(?:os\.environ|process\.env|\$\{?[A-Z_]*(?:TOKEN|KEY|SECRET|PASSWORD)|~/\.(?:aws|ssh|netrc|env))\b")),
    ("destructive-fs",   re.compile(r"\brm\s+-rf?\b|shutil\.rmtree|fs\.rm\b|git\s+push\s+--force|reset\s+--hard")),
    ("privilege",        re.compile(r"\bsudo\b|chmod\s+(?:\+x|777)|launchctl\s+load|crontab\s+-")),
    ("package-install",  re.compile(r"\b(?:npm\s+i(?:nstall)?\s+-g|pip\s+install|brew\s+install|npx\s+-y)\b", re.I)),
    ("self-modifying",   re.compile(r"(?:write|append).{0,40}(?:SKILL\.md|CLAUDE\.md|settings\.json|\.claude/)", re.I)),
]

# Description quality — a skill that never fires is dead context; one that always
# fires is a tax on every turn. Both are adoption risks and both are detectable.
TRIGGER_CUE = re.compile(r"\buse (?:this |the )?(?:skill )?when\b|\btrigger(?:s)? (?:on|with|when)\b|\buse for\b", re.I)
OVERBROAD_CUE = re.compile(r"\balways\b|\bevery (?:request|task|message|turn)\b|\bany (?:task|request)\b|\ball\b", re.I)


def _get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tok = getattr(RH, "GHTOK", "")
    if tok and "githubusercontent" not in url:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(MAX_FETCH_BYTES)
    return raw if binary else raw.decode("utf-8", "ignore")


# ── repo tree ─────────────────────────────────────────────────────────────────
def repo_tree(slug):
    """One recursive tree call. Returns (default_branch, [(path, size)])."""
    meta = RH.gh("/repos/" + slug)
    branch = meta.get("default_branch") or "main"
    tree = RH.gh("/repos/%s/git/trees/%s?recursive=1" % (slug, branch))
    out = []
    for node in tree.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if SKIP_PATHS.search("/" + path):
            continue
        out.append((path, node.get("size") or 0))
    return branch, out, tree.get("truncated", False), meta


def classify(paths):
    """Bucket every blob path into an artifact kind. Unmatched paths are dropped."""
    found = []
    for path, size in paths:
        if SKIP_PATHS.search("/" + path):   # also filtered in repo_tree; enforced here too
            continue                        # so classify() is honest called on its own
        for kind, rx in KIND_RULES:
            if rx.search("/" + path):
                found.append({"kind": kind, "path": path, "size": size})
                break
    return found


# ── frontmatter ───────────────────────────────────────────────────────────────
def parse_frontmatter(text):
    """Minimal YAML frontmatter reader — scalars and inline/blocked lists only.

    Deliberately not a YAML parser. Agent frontmatter is a flat key/value block;
    pulling in a dependency to read six keys would fail the reuse test.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block, body = text[3:end], text[end + 4:]
    fm, key, folding = {}, None, False
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
        if m and not (folding and line.startswith((" ", "\t"))):
            key, val = m.group(1).lower(), m.group(2).strip()
            # Block scalars (| > |- >-) carry the value on the following indented
            # lines. Descriptions are routinely written this way; treating the
            # marker as the value is how a 900-char trigger reads as 2 chars.
            folding = val[:1] in ("|", ">")
            if folding:
                fm[key] = ""
                continue
            val = val.strip("'\"")
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val:
                fm[key] = val
            else:
                fm[key] = []
        elif key and re.match(r"^\s*-\s+", line):
            item = re.sub(r"^\s*-\s+", "", line).strip().strip("'\"")
            if isinstance(fm.get(key), list):
                fm[key].append(item)
            else:
                fm[key] = [item]
        elif key and line.startswith((" ", "\t")):
            # Folded block, or a plain scalar wrapped across lines.
            cont = line.strip().strip("'\"")
            if isinstance(fm.get(key), str):
                fm[key] = (fm[key] + " " + cont).strip()
    return fm, body


def tool_surface(fm):
    """Resolve declared tools into privilege categories.

    An omitted allowed-tools is not 'no tools' — it means the artifact inherits
    the full session toolset. That is the widest possible surface and it is the
    single most common thing a skill review misses.
    """
    raw = fm.get("allowed-tools") or fm.get("allowed_tools") or fm.get("tools")
    if raw is None:
        return {"declared": False, "tools": [], "categories": ["inherits-all"], "breadth": 99}
    if isinstance(raw, str):
        raw = [t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()]
    if not raw or (len(raw) == 1 and raw[0] in ("*", "all")):
        return {"declared": True, "tools": raw, "categories": ["inherits-all"], "breadth": 99}
    cats = set()
    for tool in raw:
        base = tool.split("(")[0].strip()
        for name, rx in SURFACE:
            if rx.match(base):
                cats.add(name)
                break
        else:
            cats.add("other")
    return {"declared": True, "tools": raw, "categories": sorted(cats), "breadth": len(raw)}


def describe_quality(fm, kind):
    """Score the trigger description. Returns (grade, notes)."""
    desc = fm.get("description") or ""
    if isinstance(desc, list):
        desc = " ".join(desc)
    notes = []
    if kind not in ("skill", "agent", "command"):
        return "n/a", notes
    if not desc:
        return "missing", ["no description — the model cannot know when to load this"]
    n = len(desc)
    if n < 40:
        notes.append("description under 40 chars — will misfire or never fire")
    if n > 1200:
        notes.append("description over 1200 chars — it is loaded on every turn, this is rent")
    if not TRIGGER_CUE.search(desc):
        notes.append("no explicit trigger clause ('use when…') — matching will be fuzzy")
    if OVERBROAD_CUE.search(desc):
        notes.append("over-broad trigger language — likely to fire on unrelated turns")
    grade = "good" if not notes else ("weak" if len(notes) == 1 else "poor")
    return grade, notes


def capability_findings(text):
    hits = []
    for label, rx in CAPABILITY:
        m = rx.search(text)
        if m:
            hits.append({"capability": label, "excerpt": " ".join(m.group(0).split())[:80]})
    return hits


def est_tokens(nchars):
    return int(nchars / 4)


def eval_artifact(slug, branch, art, bundle_bytes=0):
    """Fetch one artifact and produce its record. Never raises on a bad file."""
    path = art["path"]
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (slug, branch, path)
    rec = dict(art)
    rec["id"] = "%s#%s" % (slug, path)
    rec["repo"] = slug
    rec["url"] = "https://github.com/%s/blob/%s/%s" % (slug, branch, path)
    try:
        text = _get(url)
    except Exception as exc:
        rec["error"] = str(exc)[:120]
        rec["verdict"] = "UNKNOWN"
        rec["why"] = "could not fetch"
        return rec

    fm, body = parse_frontmatter(text)
    rec["name"] = (fm.get("name") or os.path.basename(os.path.dirname(path)) or
                   os.path.basename(path)).strip()
    if isinstance(rec["name"], list):
        rec["name"] = " ".join(rec["name"])
    rec["description"] = (fm.get("description") if isinstance(fm.get("description"), str) else "") or ""
    rec["model"] = fm.get("model") or ""
    rec["surface"] = tool_surface(fm) if art["kind"] in ("skill", "agent", "command") else {
        "declared": False, "tools": [], "categories": [], "breadth": 0}
    rec["context"] = {
        "file_bytes": len(text),
        "est_tokens_on_load": est_tokens(len(text)),
        "bundle_bytes": bundle_bytes or len(text),
        "est_tokens_if_bundle_read": est_tokens(bundle_bytes or len(text)),
    }
    grade, notes = describe_quality(fm, art["kind"])
    rec["trigger"] = {"grade": grade, "notes": notes}
    rec["capabilities"] = capability_findings(text)
    try:
        rec["safety"] = RH.scan_text(path, text)
    except Exception:
        rec["safety"] = []
    rec["max_severity"] = ("high" if any(f["severity"] == "high" for f in rec["safety"]) else
                           "medium" if any(f["severity"] == "medium" for f in rec["safety"]) else
                           "low" if rec["safety"] else "none")
    rec["verdict"], rec["why"] = verdict_for(rec)
    return rec


def verdict_for(rec):
    """GO / MAYBE / SKIP / QUARANTINE, with the reason that decided it.

    Safety dominates. Cost and surface can only downgrade GO to MAYBE — they are
    reasons to read it before adopting, not reasons to refuse it.
    """
    sev = rec.get("max_severity")
    if sev == "high":
        kinds = ", ".join(sorted({f["kind"] for f in rec["safety"] if f["severity"] == "high"}))
        return "QUARANTINE", "high-severity finding: " + kinds
    surface, ctx, trig = rec["surface"], rec["context"], rec["trigger"]
    reasons = []
    caps = {c["capability"] for c in rec.get("capabilities", [])}
    # Almost no published skill declares allowed-tools, so on its own that fact
    # separates nothing — a finding that fires on 100% of inputs is noise. It
    # only becomes a reason when the body actually exercises the privilege.
    if "inherits-all" in surface.get("categories", []) and caps:
        reasons.append("undeclared tool surface + body does " + "/".join(sorted(caps)))
    risky = RISKY_SURFACE.intersection(surface.get("categories", []))
    if risky:
        reasons.append("reaches " + "/".join(sorted(risky)))
    if ctx["est_tokens_on_load"] > 5000:
        reasons.append("~%dk tokens on load" % (ctx["est_tokens_on_load"] // 1000))
    if trig["grade"] in ("poor", "missing"):
        reasons.append("trigger description " + trig["grade"])
    if caps and "inherits-all" not in surface.get("categories", []):
        reasons.append("does " + "/".join(sorted(caps)[:3]))
    if sev == "medium":
        reasons.append("medium-severity scan finding")
    if trig["grade"] == "missing" and rec["kind"] in ("skill", "agent"):
        return "SKIP", "; ".join(reasons)
    return ("GO", "clean: tight surface, cheap to load") if not reasons else ("MAYBE", "; ".join(reasons))


# ── repo-level driver ─────────────────────────────────────────────────────────
def bundle_sizes(paths, artifacts):
    """A skill is a directory, not a file. Charge it for everything it ships."""
    dirs = {os.path.dirname(a["path"]): 0 for a in artifacts if a["kind"] == "skill"}
    for path, size in paths:
        d = os.path.dirname(path)
        while d:
            if d in dirs:
                dirs[d] += size
                break
            d = os.path.dirname(d)
    return dirs


def evaluate_repo(slug, max_artifacts=60, kinds=None, sleep=0.0):
    started = time.time()
    try:
        branch, paths, truncated, meta = repo_tree(slug)
    except Exception as exc:
        return {"repo": slug, "error": str(exc)[:160], "artifacts": [], "rollup": {}}

    found = classify(paths)
    if kinds:
        found = [a for a in found if a["kind"] in kinds]
    found.sort(key=lambda a: ({"skill": 0, "agent": 1, "command": 2, "plugin": 3,
                               "marketplace": 4, "mcp-config": 5, "mcp-server": 6,
                               "hook": 7}.get(a["kind"], 9), a["path"]))
    capped = found[:max_artifacts]
    bundles = bundle_sizes(paths, capped)

    records = []
    for art in capped:
        bb = bundles.get(os.path.dirname(art["path"]), 0) if art["kind"] == "skill" else 0
        records.append(eval_artifact(slug, branch, art, bb))
        if sleep:
            time.sleep(sleep)

    by_kind = {}
    for r in records:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    verdicts = {}
    for r in records:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    rollup = {
        "repo": slug,
        "default_branch": branch,
        "stars": meta.get("stargazers_count", 0),
        "license": ((meta.get("license") or {}).get("spdx_id") or "—"),
        "pushed": meta.get("pushed_at", ""),
        "archived": bool(meta.get("archived")),
        "tree_truncated": truncated,
        "artifacts_found": len(found),
        "artifacts_evaluated": len(records),
        "dropped_by_cap": max(0, len(found) - len(capped)),
        "by_kind": by_kind,
        "verdicts": verdicts,
        "context_cost_if_all_load": sum(r["context"]["est_tokens_on_load"] for r in records),
        "quarantined": [r["id"] for r in records if r["verdict"] == "QUARANTINE"],
        "inherits_all_tools": [r["id"] for r in records
                               if "inherits-all" in r["surface"].get("categories", [])],
        "elapsed_s": round(time.time() - started, 1),
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return {"repo": slug, "rollup": rollup, "artifacts": records}


# ── store ─────────────────────────────────────────────────────────────────────
def save(results):
    os.makedirs(DATA, exist_ok=True)
    try:
        with open(STORE, encoding="utf-8") as fh:
            store = json.load(fh)
    except Exception:
        store = {"schema": SCHEMA, "repos": {}, "artifacts": {}}
    store.setdefault("repos", {})
    store.setdefault("artifacts", {})
    for res in results:
        if res.get("rollup"):
            store["repos"][res["repo"]] = res["rollup"]
        for rec in res.get("artifacts", []):
            store["artifacts"][rec["id"]] = rec
    store["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    store["count"] = len(store["artifacts"])
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, STORE)
    return STORE


# ── human output ──────────────────────────────────────────────────────────────
BADGE = {"GO": "GO       ", "MAYBE": "MAYBE    ", "SKIP": "SKIP     ",
         "QUARANTINE": "QUARANTINE", "UNKNOWN": "UNKNOWN  "}


def render(res):
    r = res.get("rollup") or {}
    if res.get("error"):
        return "%s — ERROR: %s" % (res["repo"], res["error"])
    lines = ["", "=" * 78,
             "%s  ★%s  %s  pushed %s" % (res["repo"], r.get("stars", 0),
                                         r.get("license", "—"), (r.get("pushed") or "")[:10]),
             "%d artifacts found, %d evaluated%s — %s" % (
                 r.get("artifacts_found", 0), r.get("artifacts_evaluated", 0),
                 (" (%d over cap)" % r["dropped_by_cap"]) if r.get("dropped_by_cap") else "",
                 ", ".join("%s×%s" % (v, k) for k, v in sorted(r.get("by_kind", {}).items()))),
             "context if every artifact loads: ~%s tokens" % f"{r.get('context_cost_if_all_load', 0):,}",
             "=" * 78]
    for rec in res["artifacts"]:
        surf = rec["surface"]
        cats = ",".join(surf.get("categories") or ["—"])
        lines.append("%s %-11s %-34s ~%5dt  %s" % (
            BADGE.get(rec["verdict"], rec["verdict"]), rec["kind"],
            rec["name"][:34], rec["context"]["est_tokens_on_load"], cats))
        lines.append("    %s" % rec["path"])
        if rec.get("why"):
            lines.append("    → %s" % rec["why"])
        for f in rec.get("safety", [])[:3]:
            lines.append("    ! [%s] %s — %s" % (f["severity"], f["kind"], f["excerpt"][:70]))
        for n in rec["trigger"].get("notes", [])[:2]:
            lines.append("    · %s" % n)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the agent artifacts inside a repo.")
    ap.add_argument("slugs", nargs="+", help="owner/repo (or a skillselion URL)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--store", action="store_true", help="persist to data/artifactstore.json")
    ap.add_argument("--max-artifacts", type=int, default=60)
    ap.add_argument("--kind", default="", help="comma list: skill,agent,command,mcp-server,plugin,hook")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between artifact fetches")
    a = ap.parse_args(argv)

    kinds = [k.strip() for k in a.kind.split(",") if k.strip()] or None
    results = []
    for slug in a.slugs:
        m = re.search(r"skillselion\.com/skills/([^/]+)/([^/]+)", slug)
        if m:
            slug = "%s/%s" % (m.group(1), m.group(2))
        slug = slug.replace("https://github.com/", "").strip("/ ")
        results.append(evaluate_repo(slug, a.max_artifacts, kinds, a.sleep))

    if a.store:
        save(results)
    if a.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    else:
        for res in results:
            print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
