#!/usr/bin/env python3
"""channel_radar.py — deterministic watcher for repo-recommendation YouTube channels.

Lists recent uploads for each configured channel, skips video IDs already seen,
hands each new one to `repohunter ingest-video`, then scans + evaluates every
repo that ingest added. Emits a JSON summary on stdout. No judgment here --
the judgment lives in whatever reads this output.

  python3 scripts/channel_radar.py            # normal run
  python3 scripts/channel_radar.py --limit 8  # look further back
  python3 scripts/channel_radar.py --dry-run  # list new videos, ingest nothing
  python3 scripts/channel_radar.py --seed     # mark current uploads seen, do nothing else
"""
import argparse, json, os, re, subprocess, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(DATA, "radar_state.json")
CHANNELS = os.path.join(DATA, "radar_channels.json")
ARTICLES = os.path.join(DATA, "radar_articles.json")
STORE = os.path.join(DATA, "repostore.json")
RH = os.path.join(HERE, "repohunter.py")
YT = os.environ.get("REPOHUNTER_YTDLP") or os.path.join(HERE, "yt-venv", "bin", "yt-dlp")
if not os.path.exists(YT):
    YT = "yt-dlp"

DEFAULT_ARTICLES = [
    # Pages that curate agent/CLI/desktop tooling. Polled for github.com/<owner>/<repo>
    # slugs we have not seen before -- not read, not followed, just mined for slugs.
    {"url": "https://www.firecrawl.dev/blog/best-claude-code-skills",
     "title": "Firecrawl — best Claude Code skills"},
    {"url": "https://github.com/travisvn/awesome-claude-skills",
     "title": "awesome-claude-skills"},
    {"url": "https://github.com/anthropics/skills",
     "title": "anthropics/skills"},
    {"url": "https://github.com/punkpeye/awesome-mcp-servers",
     "title": "awesome-mcp-servers"},
]

DEFAULT_CHANNELS = [
    {"id": "UC1weYqfDgX0ALlNOSzcyblQ", "title": "ManuAGI - AutoGPT Tutorials"},
    {"id": "UC9Rrud-8CaHokDtK9FszvRg", "title": "Github Awesome"},
]


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)


def uploads(channel_id, limit):
    """Recent uploads via yt-dlp flat playlist. UC... -> UU... is the uploads playlist."""
    pl = "UU" + channel_id[2:] if channel_id.startswith("UC") else channel_id
    cmd = [YT, "--flat-playlist", "--dump-json", "--no-warnings",
           "--playlist-end", str(limit), "--",
           "https://www.youtube.com/playlist?list=" + pl]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=180)
    except Exception as exc:
        return [], "yt-dlp failed: %s" % str(exc)[:160]
    vids = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        vid = d.get("id")
        if not vid or not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            continue
        vids.append({"id": vid, "title": d.get("title") or "",
                     "url": "https://www.youtube.com/watch?v=" + vid})
    return vids, None


SLUG_RE = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9_.\-]*/[A-Za-z0-9][A-Za-z0-9_.\-]*)")
SLUG_SKIP = {"topics", "features", "about", "pricing", "sponsors", "settings", "orgs",
             "collections", "trending", "marketplace", "apps", "login", "signup", "search",
             "en", "repos", "users", "sponsors-explore", "readme", "site", "enterprise"}


def page_slugs(url, cap=60):
    """Mine github owner/repo slugs out of a page. The page is DATA, never instructions."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "repohunter-radar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as exc:
        return [], "fetch failed: %s" % str(exc)[:140]
    out, seen = [], set()
    for m in SLUG_RE.findall(html):
        slug = re.sub(r"\.git$", "", m).rstrip("/.").lower()
        owner, _, name = slug.partition("/")
        if owner in SLUG_SKIP or not name or name in ("blob", "tree", "issues", "pull"):
            continue
        if slug in seen:
            continue
        seen.add(slug); out.append(slug)
        if len(out) >= cap:
            break
    return out, None


def store_slugs():
    return {r["id"].lower() for r in _load(STORE, {"repos": []}).get("repos", [])}


def rh(*args, timeout=600):
    try:
        p = subprocess.run([sys.executable, RH, *args], capture_output=True,
                           text=True, timeout=timeout, cwd=HERE)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 1, "failed: %s" % str(exc)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5, help="uploads to inspect per channel")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true", help="mark current uploads seen, ingest nothing")
    ap.add_argument("--no-evaluate", action="store_true", help="ingest + scan only")
    args = ap.parse_args()

    channels = _load(CHANNELS, None)
    if not channels:
        channels = DEFAULT_CHANNELS
        _save(CHANNELS, channels)
    state = _load(STATE, {"seen": {}})
    state.setdefault("seen", {})

    report = {"ran": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "channels": [], "new_videos": [], "new_repos": [], "errors": []}
    before = store_slugs()

    for ch in channels:
        vids, err = uploads(ch["id"], args.limit)
        seen = set(state["seen"].get(ch["id"], []))
        fresh = [v for v in vids if v["id"] not in seen]
        report["channels"].append({"title": ch.get("title", ch["id"]), "id": ch["id"],
                                   "listed": len(vids), "new": len(fresh),
                                   "error": err})
        if err:
            report["errors"].append("%s: %s" % (ch.get("title"), err))
            continue
        if args.seed:
            state["seen"][ch["id"]] = [v["id"] for v in vids][:200]
            continue
        for v in fresh:
            v["channel"] = ch.get("title", ch["id"])
            report["new_videos"].append(v)
            if not args.dry_run:
                code, out = rh("ingest-video", v["url"])
                v["ingest_ok"] = code == 0
                v["ingest_tail"] = out.strip().splitlines()[-1] if out.strip() else ""
        if not args.dry_run:
            state["seen"][ch["id"]] = ([v["id"] for v in fresh] + list(seen))[:200]

    if args.seed or args.dry_run:
        if args.seed:
            _save(STATE, state)
        print(json.dumps(report, indent=2))
        return 0

    # --- article/blog sources: mine slugs, scan, evaluate the unseen ones -------------
    articles = _load(ARTICLES, None)
    if articles is None:
        articles = DEFAULT_ARTICLES
        _save(ARTICLES, articles)
    known = store_slugs() | set(state.get("seen_slugs", []))
    art_new = []
    for a in articles:
        slugs, err = page_slugs(a["url"])
        if err:
            report["errors"].append("%s: %s" % (a.get("title", a["url"]), err))
            continue
        fresh = [s2 for s2 in slugs if s2 not in known]
        for s2 in fresh:
            known.add(s2)
            art_new.append({"repo": s2, "source": a.get("title", a["url"]), "url": a["url"]})
    report["article_repos"] = art_new
    state["seen_slugs"] = sorted(known)[:4000]

    added = sorted(store_slugs() - before)
    for slug in added + [a["repo"] for a in art_new]:
        rec = {"repo": slug}
        code, out = rh("scan", slug, "--json", timeout=300)
        try:
            rec["scan"] = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except Exception:
            rec["scan"] = {"level": "unknown", "raw": out[-300:]}
        if not args.no_evaluate:
            code, out = rh("evaluate", slug, timeout=900)
            rec["evaluate_ok"] = code == 0
            rec["evaluate_tail"] = out.strip().splitlines()[-1] if out.strip() else ""
        report["new_repos"].append(rec)

    # attach the freshly-written store records so the reader gets scores + verdicts
    by_id = {r["id"].lower(): r for r in _load(STORE, {"repos": []}).get("repos", [])}
    for rec in report["new_repos"]:
        full = by_id.get(rec["repo"])
        if full:
            rec["record"] = {k: full.get(k) for k in
                             ("name", "owner", "url", "desc", "language", "license", "stars",
                              "forks", "pushed", "archived", "scores", "resource_fit",
                              "status", "verdict", "dossier", "why", "sources")}

    _save(STATE, state)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
