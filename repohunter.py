#!/usr/bin/env python3
"""RepoHunter — reuse, don't reinvent.

The index + brain over open-source code: evaluate any repo for YOUR project and
YOUR hardware — relevance, how to integrate, the enhancement, build-vs-integrate,
rough cost, does-it-run-here — and a GO/MAYBE/SKIP verdict. Ingest candidates from
a seed list, live GitHub search, or a "top-N repos" YouTube video. RepoHunter hosts
nothing; it knows the code and makes it easy to adopt. Approve-first.

Config lives in ./config.json (see config.example.json). The LLM is pluggable and
OpenAI-compatible — local Ollama by default, or OpenAI/OpenRouter/Claude-CLI.

  python3 repohunter.py refresh                 # build the store from your seed
  python3 repohunter.py evaluate owner/repo     # deep-evaluate one repo
  python3 repohunter.py ingest-video <yt-url>   # mine a video for repos
  python3 repohunter.py serve                   # serve the UI + API locally

Stdlib only (plus optional yt-dlp for video ingest). MIT (c) 2026 Chris Gorzelic.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = int(time.time())
UA = "RepoHunter/0.1"


# ── Config ────────────────────────────────────────────────────────────────────
def _load_config():
    defaults = {
        "project": {"name": "My Project",
                    "profile": "A software project looking to reuse quality open-source components.",
                    "relevance_keywords": ["library", "cli", "api", "self-hosted", "local"]},
        "llm": {"backend": "ollama", "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:7b", "api_key_env": ""},
        "github_token_env": "GITHUB_TOKEN",
        "seed": [], "output": "data/repostore.json", "port": 8130,
    }
    path = "config.json" if os.path.exists("config.json") else os.path.join(HERE, "config.json")
    if os.path.exists(path):
        try:
            user = json.load(open(path))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(defaults.get(k), dict):
                    defaults[k].update(v)
                else:
                    defaults[k] = v
        except Exception as e:
            sys.stderr.write("config.json unreadable (%s); using defaults\n" % e)
    return defaults


CFG = _load_config()
# Data + cache live where the user runs (their project), not in the install dir — so the
# pip/pipx console-script works instead of trying to write into site-packages.
OUT = CFG["output"] if os.path.isabs(CFG["output"]) else os.path.join(os.getcwd(), CFG["output"])
CACHE = os.path.join(os.getcwd(), ".cache", "repohunter")
STORE_SCHEMA = 1
PROFILE = CFG["project"]["profile"]
GHTOK = os.environ.get(CFG.get("github_token_env") or "GITHUB_TOKEN", "")


# ── Machine specs (cross-platform: macOS + Linux) ─────────────────────────────
def machine_specs():
    def _out(*a):
        try:
            return subprocess.check_output(a, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""
    is_mac = sys.platform == "darwin"
    if is_mac:
        chip = _out("sysctl", "-n", "machdep.cpu.brand_string") or "Apple Silicon"
        cores = _out("sysctl", "-n", "hw.ncpu")
        try:
            ram = int(_out("sysctl", "-n", "hw.memsize")) // (1024 ** 3)
        except Exception:
            ram = 0
    else:
        chip, cores, ram = "CPU", str(os.cpu_count() or "?"), 0
        try:
            for ln in open("/proc/cpuinfo"):
                if ln.startswith("model name"):
                    chip = ln.split(":", 1)[1].strip(); break
        except Exception:
            pass
        try:
            for ln in open("/proc/meminfo"):
                if ln.startswith("MemTotal"):
                    ram = int(ln.split()[1]) // (1024 ** 2); break
        except Exception:
            pass
    disk = ""
    try:
        disk = subprocess.check_output("df -h . | awk 'NR==2{print $4}'", shell=True, text=True).strip()
    except Exception:
        pass
    return {"chip": chip, "cores": cores, "ram_gb": ram, "disk_free": disk,
            "os": "macOS" if is_mac else "Linux"}


# ── Pluggable LLM (OpenAI-compatible; local Ollama by default) ────────────────
def llm(system, prompt, timeout=180):
    """One chat completion → text (empty string on failure). Never raises."""
    b = CFG["llm"]
    backend = (b.get("backend") or "ollama").lower()
    if backend == "claude-cli":
        try:
            r = subprocess.run(["claude", "-p", "--append-system-prompt", system, prompt],
                               capture_output=True, text=True, timeout=timeout)
            return (r.stdout or "").strip()
        except Exception:
            return ""
    base = (b.get("base_url") or "http://localhost:11434/v1").rstrip("/")
    key = os.environ.get(b.get("api_key_env") or "", "")
    body = json.dumps({"model": b.get("model") or "qwen2.5:7b", "stream": False,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}],
                       "temperature": 0.3}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        return (d["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _json_from(text, opener="{", closer="}"):
    m = re.search(re.escape(opener) + r".*" + re.escape(closer), text or "", re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# ── GitHub ────────────────────────────────────────────────────────────────────
def gh(path, want_headers=False):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if GHTOK:
        req.add_header("Authorization", "Bearer " + GHTOK)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
        return (data, dict(r.headers)) if want_headers else data


def _count_via_link(path):
    """Contributor/other counts: read the Link rel=last page number (per_page=1)."""
    try:
        _, hdrs = gh(path, want_headers=True)
        m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', hdrs.get("Link", ""))
        return int(m.group(1)) if m else 1
    except Exception:
        return 0


def fetch_repo(slug):
    try:
        d = gh("/repos/" + slug)
    except Exception:
        return None
    lic = d.get("license") or {}
    meta = {
        "id": d.get("full_name", slug), "name": d.get("name", slug.split("/")[-1]),
        "owner": (d.get("owner") or {}).get("login", slug.split("/")[0]),
        "url": d.get("html_url", "https://github.com/" + slug),
        "desc": (d.get("description") or "").strip(), "language": d.get("language") or "",
        "license": lic.get("spdx_id") or lic.get("name") or "—",
        "stars": d.get("stargazers_count", 0), "forks": d.get("forks_count", 0),
        "issues": d.get("open_issues_count", 0), "topics": d.get("topics", []) or [],
        "pushed": d.get("pushed_at", ""), "created": d.get("created_at", ""),
        "archived": bool(d.get("archived")),
    }
    meta["contributors"] = _count_via_link("/repos/%s/contributors?per_page=1&anon=true" % slug)
    try:
        rel = gh("/repos/%s/releases/latest" % slug)
        meta["latest_release"] = rel.get("tag_name", "")
        meta["release_date"] = (rel.get("published_at") or "")[:10]
    except Exception:
        meta["latest_release"] = ""; meta["release_date"] = ""
    return meta


def _days_since(iso):
    try:
        t = time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
        return max(0, int((NOW - t) / 86400))
    except Exception:
        return 9999


def score(meta, why=""):
    kws = CFG["project"].get("relevance_keywords", [])
    text = " ".join([meta.get("desc", ""), why, " ".join(meta.get("topics", [])),
                     meta.get("name", ""), meta.get("language", "")]).lower()
    rel = min(100, 20 + sum(6 for k in kws if k.lower() in text))
    pop = min(100, int(math.log10(meta.get("stars", 0) + 1) * 22))
    d = _days_since(meta.get("pushed", ""))
    fresh = 100 if d < 30 else 80 if d < 90 else 55 if d < 365 else 25
    health = 70 + (15 if meta.get("license", "—") not in ("—", "NOASSERTION") else 0) \
        + (10 if meta.get("stars", 0) > 1000 else 0) - (40 if meta.get("archived") else 0)
    health = max(0, min(100, health))
    c = meta.get("contributors", 0)
    mat = min(100, (30 if meta.get("latest_release") else 0) + min(50, c * 2)
              + (20 if _days_since(meta.get("created", "")) > 365 else 5))
    overall = int(rel * 0.4 + pop * 0.18 + fresh * 0.17 + health * 0.13 + mat * 0.12)
    return {"relevance": rel, "popularity": pop, "freshness": fresh,
            "health": health, "maturity": mat, "overall": overall}


def resource_fit(meta, specs):
    """Estimate whether this repo runs on THIS machine — actually reads specs (RAM)."""
    text = " ".join([meta.get("desc", ""), " ".join(meta.get("topics", [])),
                     meta.get("language", "")]).lower()
    lang = meta.get("language", "").lower()
    try:
        ram = int((specs or {}).get("ram_gb") or 0)
    except Exception:
        ram = 0
    if any(k in text for k in ("cuda", "gpu-only", "a100", "h100", "training", "fine-tun",
                               "70b", "kubernetes", "cluster")):
        note = "Wants a GPU / lots of RAM — check the dossier."
        if ram and ram < 32:
            note = "Wants a GPU / lots of RAM — your %d GB is likely tight for this." % ram
        return {"verdict": "heavy", "ram_need": "high", "gpu": True, "note": note}
    if lang in ("c", "rust", "go", "zig", "c++"):
        return {"verdict": "runs easily", "ram_need": "low", "gpu": False,
                "note": "Compiled, small footprint."}
    if any(k in text for k in ("pytorch", "tensorflow", "model", "inference", "llm", "embedding")):
        note = "Local ML — fits given enough RAM."
        if ram and ram < 16:
            note = "Local ML — %d GB is on the low side; watch memory." % ram
        return {"verdict": "runs with headroom", "ram_need": "medium", "gpu": False, "note": note}
    return {"verdict": "runs easily", "ram_need": "low", "gpu": False, "note": "Ordinary app resources."}


# ── Dossier + plan (LLM) ──────────────────────────────────────────────────────
DOSSIER_SYSTEM = (
    "You are a software integration analyst. Given a GitHub repo and THIS project's "
    "profile, FIRST classify the repo's KIND, then decide how/whether to adopt it. "
    "Not every repo is installable code. Output ONLY a JSON object with string fields: "
    "kind (tool/library/mcp-server/app/framework/model/dataset/aggregate-list/reference/"
    "config-dotfiles/other), adopt_as (integrate/discovery-source/mine-for-candidates/"
    "reference-only/skip), what, relevance (to THIS project specifically), integration "
    "(how to adopt it the way adopt_as says), enhancement, feasibility (does it run on "
    "the given hardware; 'n/a — nothing to run' for non-code), improvements (how the "
    "adopter could make it better; 'n/a' if not code), build_vs_integrate (integrate vs "
    "build our own, with reasoning), cost (rough: output tokens, time, agents + upkeep), "
    "recommendation, verdict (GO/MAYBE/SKIP). Plain English, no markdown, no backticks."
)
PLAN_SYSTEM = (
    "You are a software integration engineer. Produce a concrete, SAFE plan to add this "
    "repo to the project. Output ONLY JSON with string fields: summary, install_method "
    "(prefer a pinned release with checksum verification; AVOID curl|bash and say why), "
    "steps (array), files_touched (array), gitignore (array), secrets_needed (array), "
    "smoke_test (array), rollback, risks (array), effort, verdict (GO/HOLD). Never commit "
    "to main — open a PR. No markdown, no backticks."
)


def _cache(slug, kind):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, "%s.%s.json" % (slug.replace("/", "_"), kind))


def make_dossier(meta, specs):
    cp = _cache(meta["id"], "dossier")
    if os.path.exists(cp) and os.path.getsize(cp) > 0:
        try:
            return json.load(open(cp))
        except Exception:
            pass
    q = ("PROJECT: %s\n\nHARDWARE: %s, %s cores, %s GB RAM, %s free, %s.\n\nREPO: %s\n%s\n"
         "License: %s · Language: %s · Stars: %s · Contributors: %s · Latest release: %s\n"
         "Topics: %s\n\nWrite the dossier as JSON." % (
             PROFILE, specs["chip"], specs["cores"], specs["ram_gb"], specs["disk_free"],
             specs["os"], meta["id"], meta.get("desc", ""), meta.get("license", ""),
             meta.get("language", ""), meta.get("stars", 0), meta.get("contributors", 0),
             meta.get("latest_release", "—"), ", ".join(meta.get("topics", [])[:10])))
    out = llm(DOSSIER_SYSTEM, q, timeout=180)
    d = _json_from(out) or {"verdict": "MAYBE", "what": meta.get("desc", ""),
                            "recommendation": out[:400] or "No LLM configured — scores only. "
                            "Set an LLM backend in config.json for the full dossier."}
    try:
        json.dump(d, open(cp, "w"), indent=2)
    except Exception:
        pass
    return d


def make_plan(meta, specs):
    q = ("PROJECT: %s\n\nHARDWARE: %s, %s GB RAM, %s.\n\nREPO: %s\n%s\nLicense: %s · Lang: %s\n\n"
         "Write the integration plan as JSON." % (
             PROFILE, specs["chip"], specs["ram_gb"], specs["os"], meta["id"],
             meta.get("desc", ""), meta.get("license", ""), meta.get("language", "")))
    plan = _json_from(llm(PLAN_SYSTEM, q, timeout=200)) or \
        {"summary": "No LLM configured — set one in config.json.", "verdict": "HOLD", "steps": []}
    # Honesty guard: "avoid curl|bash" is a request to the model, not a guarantee. Verify it and
    # downgrade to HOLD if a piped-shell install slipped through, so we never present it as safe.
    blob = " ".join(str(plan.get(k, "")) for k in ("install_method", "summary")) + " " \
        + " ".join(str(s) for s in (plan.get("steps") or []))
    if re.search(r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba)?sh", blob):
        plan.setdefault("risks", [])
        if isinstance(plan["risks"], list):
            plan["risks"].insert(0, "⚠ This plan contains a piped curl|bash install — do NOT run it "
                                    "unverified. Pin a release and verify a checksum instead.")
        plan["verdict"] = "HOLD"
    return plan


# ── Store I/O ─────────────────────────────────────────────────────────────────
def _load_store():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"repos": []}


def _save_store(store, specs=None):
    store["repos"].sort(key=lambda x: x["scores"]["overall"], reverse=True)
    store.update({"schema": STORE_SCHEMA, "generated": NOW, "count": len(store["repos"])})
    if specs:
        store["machine"] = specs
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(store, open(OUT, "w"), indent=2)


def build_one(entry, specs, deep=False):
    slug = entry["slug"] if isinstance(entry, dict) else entry
    meta = fetch_repo(slug)
    if not meta:
        return None
    why = entry.get("why", "") if isinstance(entry, dict) else ""
    meta["category"] = entry.get("category", "Candidate") if isinstance(entry, dict) else "Dropped-in"
    meta["why"] = why
    meta["scores"] = score(meta, why)
    meta["resource_fit"] = resource_fit(meta, specs)
    meta["status"] = "candidate"
    if deep or (isinstance(entry, dict) and entry.get("featured")):
        meta["dossier"] = make_dossier(meta, specs)
        meta["status"] = "evaluated"
    return meta


def refresh():
    specs = machine_specs()
    prior = {r["id"].lower(): r.get("integration")
             for r in _load_store().get("repos", []) if r.get("integration")}
    seen, repos = set(), []
    for e in list(CFG.get("seed", [])):
        slug = (e.get("slug") if isinstance(e, dict) else e) or ""
        if not slug or slug == "owner/repo" or slug.lower() in seen:
            continue
        seen.add(slug.lower())
        r = build_one(e, specs)
        if r:
            if prior.get(r["id"].lower()):
                r["integration"] = prior[r["id"].lower()]
            repos.append(r)
            print("  ✓ %-38s overall=%d %s" % (r["id"], r["scores"]["overall"],
                                               "· dossier" if "dossier" in r else ""))
    _save_store({"repos": repos}, specs)
    if not repos:
        print("\n⚠  Your store is EMPTY — config.json 'seed' is missing or still the placeholder.")
        print("   Add real repos and re-run, e.g.:  \"seed\": [{\"slug\": \"owner/name\"}]")
        print("   (config.example.json ships a few real ones to start from.)\n")
    print("→ wrote %s (%d repos)" % (OUT, len(repos)))


def evaluate(slug):
    slug = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    specs = machine_specs()
    r = build_one({"slug": slug, "featured": True}, specs, deep=True)
    if not r:
        print("could not resolve %s" % slug); return 1
    store = _load_store()
    store["repos"] = [x for x in store["repos"] if x.get("id") != r["id"]] + [r]
    _save_store(store, specs)
    print("→ evaluated %s (%s)" % (r["id"], r.get("dossier", {}).get("verdict", "?")))
    return 0


def plan_mode(slug):
    store = _load_store()
    rid = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    repo = next((x for x in store["repos"] if x["id"].lower() == rid.lower()), None)
    if not repo:
        print("not in store: %s" % rid); return 1
    specs = store.get("machine") or machine_specs()
    repo["integration"] = {"status": "planning", "updated": NOW}
    _save_store(store)
    repo["integration"] = {"status": "planned", "plan": make_plan(repo, specs), "updated": NOW}
    _save_store(store)
    print("planned %s" % rid); return 0


def decide_mode(slug, decision):
    store = _load_store()
    rid = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    repo = next((x for x in store["repos"] if x["id"].lower() == rid.lower()), None)
    if not repo:
        print("not in store: %s" % rid); return 1
    ig = repo.get("integration") or {}
    repo["integration"] = {"status": "approved" if decision == "approve" else "evaluated",
                           "plan": ig.get("plan"), "updated": NOW}
    _save_store(store)
    print("%s -> %s" % (rid, repo["integration"]["status"])); return 0


# ── YouTube ingest (optional; needs yt-dlp) ───────────────────────────────────
YT_BIN = os.environ.get("REPOHUNTER_YTDLP", os.path.join(HERE, "yt-venv", "bin", "yt-dlp"))
YT_EXTRACT = ("Extract the GitHub repositories a video recommends. Given the title, "
              "description and transcript, output ONLY a JSON array of 'owner/repo' "
              "strings actually referenced. No prose.")


def _strip_vtt(v):
    out = []
    for ln in v.splitlines():
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln or ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        if ln and (not out or out[-1] != ln):
            out.append(ln)
    return " ".join(out)[:6000]


def _is_youtube_url(url):
    """Real hostname check — a bare 'youtu' substring test lets a hostile URL through."""
    from urllib.parse import urlparse
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return False
    host = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and host in (
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be")


def ingest_video(url):
    import tempfile, glob
    if not _is_youtube_url(url):
        print("refusing non-YouTube URL: %r" % (url or "")[:80]); return 1
    ytbin = YT_BIN if os.path.exists(YT_BIN) else "yt-dlp"
    td = tempfile.mkdtemp()
    try:
        info = json.loads(subprocess.check_output(
            [ytbin, "--skip-download", "--dump-json", "--no-warnings", "--", url], text=True, timeout=120))
    except Exception as e:
        print("could not fetch video (%s) — is yt-dlp installed?" % str(e)[:60]); return 1
    title = info.get("title", "(video)")
    text = info.get("description", "") or ""
    try:
        subprocess.run([ytbin, "--skip-download", "--write-auto-subs", "--sub-lang", "en.*",
                        "--sub-format", "vtt", "-o", os.path.join(td, "v"), "--no-warnings", "--", url],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for f in glob.glob(os.path.join(td, "*.vtt")):
            text += "\n" + _strip_vtt(open(f, encoding="utf-8", errors="ignore").read()); break
    except Exception:
        pass
    slugs = set(re.sub(r"\.git$", "", m).rstrip("/.").lower()
                for m in re.findall(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", text))
    for s in (_json_from(llm(YT_EXTRACT, "Title: %s\n\n%s" % (title, text[:9000]), 120), "[", "]") or []):
        if isinstance(s, str) and s.count("/") == 1:
            slugs.add(s.strip().lower())
    specs = machine_specs(); store = _load_store()
    have = {x["id"].lower(): x for x in store["repos"]}
    src = {"type": "youtube", "title": title, "url": url, "id": info.get("id", "")}
    added = 0
    for slug in sorted(slugs):
        slug = re.sub(r"[^A-Za-z0-9_./\-]", "", slug)
        if slug.count("/") != 1 or slug.endswith("/"):
            continue
        if slug in have:
            have[slug].setdefault("sources", [])
            if not any(x.get("id") == src["id"] for x in have[slug]["sources"]):
                have[slug]["sources"].append(src)
            continue
        meta = fetch_repo(slug)
        if not meta:
            continue
        meta.update({"category": "From a video", "why": "Recommended in: %s" % title,
                     "scores": score(meta, title), "resource_fit": resource_fit(meta, specs),
                     "status": "candidate", "sources": [src]})
        store["repos"].append(meta); have[slug] = meta; added += 1
        print("  + %s" % slug)
    _save_store(store, specs)
    print("→ ingested %d repo(s) from: %s" % (added, title)); return 0


# ── Standalone server ─────────────────────────────────────────────────────────
def serve():
    import http.server
    from urllib.parse import urlparse
    port = int(CFG.get("port", 8130))
    me = os.path.abspath(__file__)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, ctype="application/json", raw=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            # No CORS: the UI is served from this same origin, so it needs no cross-origin grant.
            # A wildcard here would let ANY website drive your local API. Keep it same-origin only.
            body = raw if raw is not None else json.dumps(obj or {}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._send(204, raw=b"")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/store.html"):
                return self._send(200, raw=open(os.path.join(HERE, "store.html"), "rb").read(),
                                  ctype="text/html")
            if path == "/repostore.json":
                data = open(OUT, "rb").read() if os.path.exists(OUT) else b'{"repos":[]}'
                return self._send(200, raw=data)
            if path in ("/logo.svg", "/favicon.ico"):
                lp = os.path.join(HERE, "logo.svg")
                if os.path.exists(lp):
                    return self._send(200, raw=open(lp, "rb").read(), ctype="image/svg+xml")
            return self._send(404, {"error": "not found"})

        def _spawn(self, *args):
            subprocess.Popen([sys.executable, me, *args],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad json"})
            if path == "/api/repo/queue":
                u = (body.get("url") or "").strip()
                m = re.search(r"github\.com/([^/\s]+/[^/\s#?]+)", u) or re.match(r"^([\w.\-]+/[\w.\-]+)$", u)
                if not m:
                    return self._send(400, {"error": "owner/repo or github URL"})
                self._spawn("evaluate", m.group(1).replace(".git", ""))
                return self._send(200, {"queued": True})
            if path == "/api/repo/ingest-video":
                if not _is_youtube_url(body.get("url") or ""):
                    return self._send(400, {"error": "a valid youtube.com / youtu.be URL is required"})
                self._spawn("ingest-video", body["url"]); return self._send(200, {"queued": True})
            if path == "/api/repo/integrate":
                self._spawn("plan", body.get("id", "")); return self._send(200, {"queued": True})
            if path == "/api/repo/plan-decision":
                if body.get("decision") in ("approve", "reject"):
                    self._spawn("decide", body.get("id", ""), body["decision"])
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    print("RepoHunter → http://127.0.0.1:%d   (Ctrl-C to stop)" % port)
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()


USAGE = """RepoHunter — reuse, don't reinvent.

  repohunter refresh                     build the store from your config.json seed
  repohunter evaluate <owner/repo>       deep-evaluate one repo
  repohunter plan <owner/repo>           draft an integration plan
  repohunter decide <owner/repo> approve|reject
  repohunter ingest-video <youtube-url>  mine a video for the repos it recommends
  repohunter serve                       serve the UI + API on http://127.0.0.1:<port>
"""


def main(argv=None):
    """CLI entry point. Also the console_scripts target so `repohunter <cmd>` works."""
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "refresh"
    a = argv[1:]
    if cmd in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    needs = {"evaluate": 1, "plan": 1, "ingest-video": 1, "decide": 2}
    if cmd in needs and len(a) < needs[cmd]:
        sys.stderr.write("error: '%s' needs %d argument(s).\n\n%s" % (cmd, needs[cmd], USAGE))
        return 2
    fn = {"evaluate": lambda: evaluate(a[0]), "plan": lambda: plan_mode(a[0]),
          "decide": lambda: decide_mode(a[0], a[1]), "ingest-video": lambda: ingest_video(a[0]),
          "serve": serve, "refresh": refresh}.get(cmd)
    if fn is None:
        sys.stderr.write("error: unknown command '%s'.\n\n%s" % (cmd, USAGE))
        return 2
    return fn() or 0


if __name__ == "__main__":
    sys.exit(main())
