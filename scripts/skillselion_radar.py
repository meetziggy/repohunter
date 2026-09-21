#!/usr/bin/env python3
"""skillselion_radar.py — adoption-ranked agent tooling, turned into candidates.

Skillselion ranks Claude Code skills, MCP servers and marketplaces by real
install counts from the skills.sh registry, with GitHub stars as tiebreak.
There is no public API, but the pages ship schema.org ItemList JSON-LD, so the
ranking is structured data rather than a scrape that breaks on a CSS change.

Why this source earns its place next to the YouTube radar: a video tells you a
repo exists, installs tell you whether anyone kept it. And the URL shape
    /skills/<owner>/<repo>/<skill-name>
joins a ranked artifact directly onto a GitHub slug — which is exactly the
input repohunter_artifacts.py needs.

State lives in data/skillselion_state.json, so every run yields a delta:
what is new, what moved, and how fast installs are accruing. A snapshot says
what is popular; the delta says what is *becoming* popular, which is the only
part worth acting on.

  python3 scripts/skillselion_radar.py                 # delta report, JSON
  python3 scripts/skillselion_radar.py --evaluate      # + artifact eval on movers
  python3 scripts/skillselion_radar.py --seed          # record baseline, report nothing
"""
import argparse, html, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(DATA, "skillselion_state.json")
BASE = "https://skillselion.com"
UA = "repohunter-skillselion/1.0 (+https://github.com/bgorzelic)"
PAGES = [("leaderboard", "/leaderboard")]

NUM = re.compile(r"([\d,]+(?:\.\d+)?)\s*([KMB])?\s*(installs|stars)", re.I)
MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def flatten(page):
    txt = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return html.unescape(re.sub(r"\s+", " ", txt))


def item_lists(page):
    """Every schema.org ItemList on the page, in document order."""
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        for node in (obj if isinstance(obj, list) else [obj]):
            if isinstance(node, dict) and node.get("@type") == "ItemList":
                out.append(node)
    return out


def parse_metrics(flat, name):
    """installs/stars printed after an entry's name. Returns {} when absent."""
    i = flat.find(" " + name + " ")
    if i == -1:
        return {}
    window = flat[i:i + 500]
    vals = {}
    for m in NUM.finditer(window):
        raw, mult, kind = m.group(1).replace(",", ""), (m.group(2) or "").upper(), m.group(3).lower()
        try:
            vals.setdefault(kind, int(float(raw) * MULT.get(mult, 1)))
        except ValueError:
            continue
    return vals


def slug_from_url(url, kind):
    """Map a skillselion URL back to a GitHub owner/repo (+ artifact name)."""
    path = url.replace(BASE, "").strip("/")
    parts = path.split("/")
    if kind == "skill" and len(parts) >= 3 and parts[0] == "skills":
        rest = parts[1:]
        if len(rest) >= 3:                       # skills/<owner>/<repo>/<skill>
            return "%s/%s" % (rest[0], rest[1]), rest[-1]
        if len(rest) == 2:                       # skills/<owner>/<repo>
            return "%s/%s" % (rest[0], rest[1]), rest[1]
    if kind == "mcp" and "tool" in parts:        # mcp/tool/io.github.<owner>/<name>
        tail = parts[parts.index("tool") + 1:]
        if len(tail) >= 2 and tail[0].startswith("io.github."):
            return "%s/%s" % (tail[0].split("io.github.", 1)[1], tail[1]), tail[1]
    if kind == "marketplace" and len(parts) >= 3:
        return "%s/%s" % (parts[1], parts[2]), parts[-1]
    return None, parts[-1] if parts else ""


def kind_of(list_name, url):
    n = (list_name or "").lower()
    if "/mcp/" in url or "mcp" in n:
        return "mcp"
    if "/marketplace" in url or "marketplace" in n:
        return "marketplace"
    return "skill"


def collect():
    rows, seen_urls = [], set()
    for page_name, path in PAGES:
        page = fetch(path)
        flat = flatten(page)
        for lst in item_lists(page):
            list_name = lst.get("name", "")
            for el in lst.get("itemListElement", []):
                url = el.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                name = el.get("name") or ""
                kind = kind_of(list_name, url)
                slug, artifact = slug_from_url(url, kind)
                metrics = parse_metrics(flat, name)
                rows.append({
                    "key": url,
                    "kind": kind,
                    "name": name,
                    "artifact": artifact,
                    "repo": slug,
                    "url": url,
                    "list": list_name,
                    "page": page_name,
                    "rank": el.get("position"),
                    "installs": metrics.get("installs"),
                    "stars": metrics.get("stars"),
                })
    return rows


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


def diff(rows, state):
    """New entries, rank moves, install velocity. The point of keeping state."""
    prev = state.get("entries", {})
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new, movers, unchanged = [], [], 0
    for row in rows:
        old = prev.get(row["key"])
        if not old:
            row["first_seen"] = now
            row["status"] = "new"
            new.append(row)
            continue
        row["first_seen"] = old.get("first_seen", now)
        row["prev_rank"] = old.get("rank")
        row["prev_installs"] = old.get("installs")
        row["rank_delta"] = ((old.get("rank") or 0) - (row.get("rank") or 0)) or 0
        if row.get("installs") is not None and old.get("installs") is not None:
            row["installs_delta"] = row["installs"] - old["installs"]
            days = _age_days(old.get("observed_at"), now)
            row["installs_per_day"] = round(row["installs_delta"] / days, 1) if days else None
        else:
            row["installs_delta"] = None
            row["installs_per_day"] = None
        if row["rank_delta"] or (row.get("installs_delta") or 0):
            row["status"] = "moved"
            movers.append(row)
        else:
            row["status"] = "flat"
            unchanged += 1
    # Entries that fell off the board entirely are their own signal.
    live = {r["key"] for r in rows}
    dropped = [{"key": k, "name": v.get("name"), "repo": v.get("repo"),
                "last_rank": v.get("rank"), "last_seen": v.get("observed_at")}
               for k, v in prev.items() if k not in live]
    return new, movers, dropped, unchanged


def _age_days(then, now):
    try:
        a = time.mktime(time.strptime(then[:19], "%Y-%m-%dT%H:%M:%S"))
        b = time.mktime(time.strptime(now[:19], "%Y-%m-%dT%H:%M:%S"))
        return max((b - a) / 86400.0, 0.04)
    except Exception:
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Skillselion leaderboard → radar candidates.")
    ap.add_argument("--seed", action="store_true", help="record the baseline, report nothing new")
    ap.add_argument("--evaluate", action="store_true", help="artifact-eval new + moving entries")
    ap.add_argument("--eval-limit", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true", help="do not write state")
    a = ap.parse_args(argv)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state = _load(STATE, {"entries": {}})
    try:
        rows = collect()
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:200], "generated": now}, indent=2))
        return 1
    if not rows:
        print(json.dumps({"error": "no ItemList found — page structure changed",
                          "generated": now}, indent=2))
        return 1

    new, movers, dropped, flat = diff(rows, state)

    report = {
        "generated": now,
        "source": BASE + "/leaderboard",
        "totals": {"tracked": len(rows), "new": len(new), "moved": len(movers),
                   "flat": flat, "dropped": len(dropped),
                   "by_kind": _by_kind(rows)},
        "new": [] if a.seed else new,
        "movers": [] if a.seed else sorted(
            movers, key=lambda r: -(r.get("installs_per_day") or 0))[:20],
        "dropped": [] if a.seed else dropped,
        "baseline_seeded": bool(a.seed),
        "evaluations": [],
    }

    if a.evaluate and not a.seed:
        sys.path.insert(0, HERE)
        import repohunter_artifacts as RA
        targets, seen = [], set()
        for row in (new + report["movers"]):
            if row.get("repo") and row["repo"] not in seen:
                seen.add(row["repo"])
                targets.append(row["repo"])
            if len(targets) >= a.eval_limit:
                break
        for slug in targets:
            res = RA.evaluate_repo(slug, max_artifacts=25)
            report["evaluations"].append({
                "repo": slug,
                "rollup": res.get("rollup", {}),
                "flagged": [r for r in res.get("artifacts", [])
                            if r["verdict"] in ("QUARANTINE", "MAYBE")][:8],
            })

    if not a.dry_run:
        entries = dict(state.get("entries", {}))
        for row in rows:
            entries[row["key"]] = {
                "name": row["name"], "kind": row["kind"], "repo": row["repo"],
                "rank": row["rank"], "installs": row["installs"], "stars": row["stars"],
                "first_seen": row.get("first_seen", now), "observed_at": now,
            }
        _save(STATE, {"schema": 1, "updated": now, "entries": entries})

    print(json.dumps(report, indent=2))
    return 0


def _by_kind(rows):
    out = {}
    for r in rows:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
