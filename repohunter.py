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

Stdlib only (plus optional yt-dlp for video ingest). MIT (c) 2026 Brian Gorzelic.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = int(time.time())
UA = "RepoHunter/0.1"


# ── Config ────────────────────────────────────────────────────────────────────
def resolve_profile(cfg, name=None):
    """Pick the active project lens. Pure — unit-testable.

    config.json carries either a single "project" object (the original shape) or a
    "profiles" map of named project objects. The named map is what lets one install
    evaluate a repo for Dickie, then for RepoHunter itself, without hand-editing
    config.json between runs — a repo that is a GO for one is often a SKIP for another,
    and the difference is the lens, not the repo.

    Returns (project_dict, active_name). Raises KeyError for an unknown name: silently
    scoring against the wrong lens produces a confidently wrong verdict, which is worse
    than no verdict at all.
    """
    profiles = cfg.get("profiles") or {}
    if not profiles:
        # An explicit request for a lens this config cannot provide must fail. Falling
        # through to the single "project" block would score the repo against the wrong
        # project while looking like it honoured the flag.
        if name:
            raise KeyError(name)
        return cfg.get("project") or {}, None
    chosen = name or cfg.get("default_profile") or next(iter(profiles))
    if chosen not in profiles:
        raise KeyError(chosen)
    merged = dict(cfg.get("project") or {})
    merged.update(profiles[chosen] or {})
    return merged, chosen


def profile_names(cfg):
    """Named profiles available in this config, in declaration order."""
    return list((cfg.get("profiles") or {}).keys())


def _argv_profile(argv=None):
    """Read --profile/-p out of argv without disturbing the positional grammar."""
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok in ("--profile", "-p") and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith("--profile="):
            return tok.split("=", 1)[1]
    return None


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
# Selection is lenient here so `import repohunter` never explodes on a bad env var;
# main() re-validates strictly before doing any work, so the CLI still fails loudly.
ACTIVE_PROFILE = None
_env_want = os.environ.get("REPOHUNTER_PROFILE")
_want = _env_want or _argv_profile()
try:
    CFG["project"], ACTIVE_PROFILE = resolve_profile(CFG, _want)
except KeyError:
    # Only warn for the env var. A bad --profile is about to get a better error from
    # main(), and two messages for one mistake is noise.
    if _env_want:
        sys.stderr.write("unknown profile %r from REPOHUNTER_PROFILE; using default\n" % _want)
    CFG["project"], ACTIVE_PROFILE = resolve_profile(CFG, None)
# Data + cache live where the user runs (their project), not in the install dir — so the
# pip/pipx console-script works instead of trying to write into site-packages.
OUT = CFG["output"] if os.path.isabs(CFG["output"]) else os.path.join(os.getcwd(), CFG["output"])
CACHE = os.path.join(os.getcwd(), ".cache", "repohunter")
STORE_SCHEMA = 1
PROFILE = CFG["project"]["profile"]
# Turn this off in config.json if nothing here is ever resold: "commercial": {"resale": false}
RESALE = bool((CFG.get("commercial") or {}).get("resale", True))
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


def _first_line(text, fallback):
    """First non-empty line of subprocess stderr, or a fallback. Pure — no I/O."""
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else fallback


def _llm_fail(backend, detail):
    """Stderr diagnostic for a failed LLM backend call. Never raises — callers still get ""
    on any failure, same contract as before; this only makes the reason visible instead of
    silently indistinguishable (bad key, dead model ID, network down, and a rate limit all
    used to look identical: nothing)."""
    sys.stderr.write("llm[%s] failed: %s\n" % (backend, detail))


# ── Pluggable LLM (OpenAI-compatible; local Ollama by default) ────────────────
def llm(system, prompt, timeout=180):
    """One chat completion → text. Tries llm.backend, then llm.fallback if configured and
    the first attempt came back empty. Never raises."""
    b = CFG["llm"]
    out = _llm_once((b.get("backend") or "ollama").lower(), b, system, prompt, timeout)
    fb = (b.get("fallback") or "").lower()
    if not out and fb:
        # A subscription-backed CLI can go quiet on a usage cap. Don't let that turn into a
        # silently empty dossier — fall through to the backup backend instead.
        out = _llm_once(fb, b, system, prompt, timeout)
    return out


def _llm_once(backend, b, system, prompt, timeout):
    if backend == "claude-cli":
        try:
            r = subprocess.run(["claude", "-p", "--append-system-prompt", system, prompt],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                _llm_fail(backend, "exit %d: %s" % (r.returncode, _first_line(r.stderr, "no stderr")))
            return (r.stdout or "").strip()
        except Exception as e:
            _llm_fail(backend, "%s: %s" % (type(e).__name__, e))
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
    except urllib.error.HTTPError as e:
        _llm_fail(backend, "HTTP %d: %s" % (e.code, e.reason))
        return ""
    except Exception as e:
        _llm_fail(backend, "%s: %s" % (type(e).__name__, e))
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


# ── Safety scan (heuristic, offline — no LLM required) ───────────────────────
# Scans a repo's README, docs and install scripts for prompt-injection attempts aimed
# at coding agents, hidden/obfuscated text, piped-shell installs and leaked secrets.
# Output is a RISK ASSESSMENT, not a certification: a clean scan means "these
# heuristics found nothing", never "this repo is safe".
ZERO_WIDTH = ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff")
BIDI_CTRL = tuple(chr(c) for c in list(range(0x202a, 0x202f)) + list(range(0x2066, 0x206a)))
# Requires a URL in the fetch so prose that merely *mentions* `curl | bash` doesn't flag.
PIPE_SH = r"(curl|wget)[^\n|]*https?://[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh"
INJECT_PATTERNS = (  # (regex, severity, label)
    (r"ignore (all |any )?(previous|prior|above|earlier) (instructions|prompts|rules|context)",
     "high", "prompt-injection phrase"),
    (r"disregard (your|all|the|any) (instructions|rules|guidelines|system prompt)",
     "high", "prompt-injection phrase"),
    (r"if you are an? (ai|llm|agent|assistant|language model)", "high", "agent-directed instruction"),
    (r"you are (now|actually) [^.\n]{0,60}(assistant|agent|mode)", "medium", "role-override attempt"),
    (r"do not (tell|inform|mention|reveal|alert)[^.\n]{0,40}(user|human|owner|developer)",
     "high", "concealment instruction"),
    # \b matters: without it `sendProgress(token: string)` reads as exfiltration.
    # Bare "token" matters too: `POST | /v2/* | Bearer Token` in an API doc is not an
    # attack. Require a real secret noun, then grade on whether a destination is named.
    # Not [^.\n]: a dot is normal inside `.env`, `config.json`, `~/.aws/credentials`,
    # and excluding it made the pattern miss the most common real phrasing.
    (r"\b(send|post|upload|forward|exfiltrate|transmit|leak)s?\b[^\n]{0,80}"
     r"(\.env\b|\b(?:api[ _-]?keys?|access[ _-]?tokens?|auth[ _-]?tokens?|"
     r"credentials?|secrets?|passwords?|private[ _-]keys?|ssh[ _-]keys?)\b)",
     "high", "exfiltration instruction"),
    (r"(?:^|[^`\w])(?:<system>|\[system\]|system prompt\s*:)", "medium", "system-prompt marker"),
)
SECRET_PATTERNS = (
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "GitHub fine-grained token"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
    (r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY", "private key"),
)
# AWS's canonical documentation keys appear verbatim in tests and docs across the
# ecosystem (e.g. semantica's Neptune tests); flagging them buries real leaks in noise.
# (Built by concatenation, not a literal: local secret-scan tooling pattern-matches
# AKIA[0-9A-Z]{16} regardless of context, and these are intentionally that shape.)
EXAMPLE_SECRETS = {"AKIA" + "IOSFODNN7EXAMPLE", "AKIA" + "I44QH8DHBEXAMPLE"}


# An external destination is what separates "send your API key to https://evil.tld"
# from "never send your API key anywhere".
DEST_CUE = re.compile(
    r"(https?://|\bwebhook\b|\battacker\b|\bmy (?:server|endpoint|bot|api)\b|"
    r"\bremote server\b|\bto me\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b)", re.I)
# Policy/disclosure prose DESCRIBES an attack rather than instructing one. SECURITY.md
# saying "anything that exfiltrates keys, .env, traces is in scope" is the repo defending
# itself, not attacking you.
POLICY_CUE = re.compile(
    r"(\bin scope\b|\bout of scope\b|\bnot in scope\b|\bvulnerabilit|\bdisclosur|"
    r"\breport (?:it|them|this|a|any)\b|\bplease report\b|\bthreat model\b|"
    r"\bmust not\b|\bshould not\b|\bdo not\b|\bdon't\b|\bnever\b|\bprohibited\b|"
    r"\bforbidden\b|\bwe do not\b|\banything that\b|\battempts? to\b|\bmalicious\b)", re.I)


# `| POST | /v2/* | ... Bearer Token |` is an endpoint table, not an instruction.
APIDOC_CUE = re.compile(r"(\|\s*(?:GET|POST|PUT|PATCH|DELETE)\s*\||\|[^\n]*\||^\s*(?:GET|POST|PUT|PATCH|DELETE)\s+/)", re.M)
HTTP_VERB = ("POST", "GET", "PUT", "PATCH", "DELETE")


def _window(text, start, end, before=160, after=160):
    return text[max(0, start - before):min(len(text), end + after)]


def _excerpt(text, start, end):
    snip = text[max(0, start - 30):min(len(text), end + 30)]
    for c in ZERO_WIDTH + BIDI_CTRL:
        snip = snip.replace(c, "·")
    return " ".join(snip.split())[:120]


def scan_text(name, text):
    """Heuristic findings for one file's text. Pure function — unit-testable."""
    findings, seen = [], set()

    def add(sev, kind, ex):
        key = (kind, sev)
        if key in seen:  # one finding per kind per file; repeats add noise, not signal
            return
        seen.add(key)
        findings.append({"file": name, "severity": sev, "kind": kind, "excerpt": ex})

    # Injection language — anywhere is bad; inside an HTML comment (invisible on GitHub) is worse.
    hidden = [(m.start(1), m.group(1)) for m in re.finditer(r"<!--(.*?)-->", text, re.S)]
    for rx, sev, label in INJECT_PATTERNS:
        for m in re.finditer(rx, text, re.I):
            in_comment = any(off <= m.start() < off + len(body) for off, body in hidden)
            sev_now, label_now = sev, label
            if label == "exfiltration instruction" and not in_comment:
                win = _window(text, m.start(), m.end())
                # An all-caps HTTP verb inside an endpoint table is documentation.
                if m.group(1).upper() in HTTP_VERB and m.group(1).isupper() \
                        and APIDOC_CUE.search(win):
                    continue
                if POLICY_CUE.search(win):
                    # Downgraded, not dropped — hiding a real instruction inside policy
                    # prose should still leave a trace for a human to look at.
                    sev_now, label_now = "low", label + " (described, not instructed)"
                elif not DEST_CUE.search(win):
                    sev_now, label_now = "medium", label + " (no destination named)"
            add("high" if in_comment else sev_now,
                ("hidden " if in_comment else "") + label_now,
                _excerpt(text, m.start(), m.end()))
    # ZWJ/ZWNJ are legitimate inside emoji sequences and joining scripts — only count them
    # when sandwiched between plain-ASCII text, where they can only be hiding something.
    zw = 0
    for m in re.finditer("[\u200b\u200c\u200d\u2060\ufeff]", text):
        c, i = m.group(0), m.start()
        if c == "\ufeff" and i == 0:
            continue  # UTF-8 BOM at byte 0 is an editor artifact, not hidden text
        if c in ("\u200c", "\u200d"):
            prev_c = text[i - 1] if i else " "
            next_c = text[i + 1] if i + 1 < len(text) else " "
            if ord(prev_c) > 127 or ord(next_c) > 127:
                continue
        zw += 1
    if zw:
        add("medium", "zero-width characters (%d) — possible hidden text" % zw, "")
    bd = sum(text.count(c) for c in BIDI_CTRL)
    if bd:
        add("medium", "bidi control characters (%d) — possible trojan-source text" % bd, "")
    for m in re.finditer(PIPE_SH, text):
        add("medium", "piped shell install (curl|bash)", _excerpt(text, m.start(), m.end()))
    if re.search(r"base64\s+(-d|--decode)[^\n]*\|\s*(ba|z)?sh", text):
        add("high", "base64-decoded shell execution", "")
    for rx, label in SECRET_PATTERNS:
        for m in re.finditer(rx, text):
            if m.group(0) in EXAMPLE_SECRETS:
                continue  # canonical docs placeholder, not a leak
            add("high", "leaked secret: " + label, m.group(0)[:12] + "…")
            break
    return findings


# Directories and filenames that carry instructions aimed at whatever agent
# reads the repo. These are the whole reason `scan` exists, and until 2026-09-21
# it never looked at them — it read the README and top-level files only, so a
# skill pack could ship 40 command files and still report "2 files scanned".
AGENT_CONFIG_PREFIXES = (
    ".claude/", ".agents/", ".cursor/", ".github/copilot", ".codex/", ".gemini/",
    "skills/", "agents/", "commands/", "prompts/", ".windsurf/", ".continue/",
)
AGENT_CONFIG_NAMES = (
    "agents.md", "claude.md", "cursor.md", ".cursorrules", "skill.md",
    "agent.md", "gemini.md", "copilot-instructions.md",
)
AGENT_CONFIG_EXTS = (".md", ".mdx", ".json", ".toml", ".yaml", ".yml", ".txt")


def _fetch_agent_config_files(slug, cap=40, max_bytes=300000):
    """Walk the repo tree for agent-directed instruction files.

    Separate from the top-level pass because these are the highest-risk text in
    any repo: a human may never read them, but an agent will.
    """
    files = []
    try:
        tree = gh("/repos/%s/git/trees/HEAD?recursive=1" % slug).get("tree") or []
    except Exception:
        return files
    picks = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        low = path.lower()
        base = low.rsplit("/", 1)[-1]
        in_dir = low.startswith(AGENT_CONFIG_PREFIXES) or any(
            ("/" + pre) in ("/" + low) for pre in AGENT_CONFIG_PREFIXES
        )
        if not (in_dir or base in AGENT_CONFIG_NAMES):
            continue
        if not low.endswith(AGENT_CONFIG_EXTS):
            continue
        if (node.get("size") or 0) > max_bytes:
            continue
        picks.append((node.get("size") or 0, path))
    # Biggest first: a 38KB command file is likelier to hide something than a stub.
    picks.sort(reverse=True)
    for _, path in picks[:cap]:
        try:
            url = "https://raw.githubusercontent.com/%s/HEAD/%s" % (slug, urllib.parse.quote(path))
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                files.append((path, r.read().decode("utf-8", "ignore")[:200000]))
        except Exception:
            pass
    return files


def _fetch_text_files(slug, cap=8):
    """README + top-level docs/scripts/manifests, size-capped. Best-effort."""
    import base64
    files = []
    try:
        rd = gh("/repos/%s/readme" % slug)
        files.append((rd.get("name", "README"),
                      base64.b64decode(rd.get("content") or b"").decode("utf-8", "ignore")[:200000]))
    except Exception:
        pass
    try:
        names = {n.lower() for n, _ in files}
        for it in gh("/repos/%s/contents/" % slug):
            n = it.get("name", "")
            if len(files) >= cap:
                break
            interesting = n.lower().endswith((".md", ".sh", ".bash", ".txt")) or n.lower() in (
                "makefile", "dockerfile", "server.json", ".mcp.json", "manifest.json", "setup.py")
            if it.get("type") != "file" or not interesting or n.lower() in names \
                    or (it.get("size") or 0) > 300000 or not it.get("download_url"):
                continue
            try:
                req = urllib.request.Request(it["download_url"], headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    files.append((n, r.read().decode("utf-8", "ignore")[:200000]))
            except Exception:
                pass
    except Exception:
        pass
    return files


def safety_scan(slug):
    files = _fetch_text_files(slug)
    seen = {n for n, _ in files}
    for name, text in _fetch_agent_config_files(slug):
        if name not in seen:
            files.append((name, text))
    findings = []
    for name, text in files:
        findings.extend(scan_text(name, text))
    sevs = [f["severity"] for f in findings]
    level = "high" if "high" in sevs else "medium" if "medium" in sevs else \
        "low" if findings else "clean"
    risk = min(100, sum({"high": 40, "medium": 15, "low": 5}[s] for s in sevs))
    if not files:
        # Nothing was fetched — almost always a GitHub 403/404 (unauthenticated rate limit),
        # not a repo with no text in it. Reporting "clean" here is a FALSE clean, so don't.
        return {"level": "unknown", "risk": 0, "findings": [], "files_scanned": 0,
                "note": "Scan could not read any files — likely a GitHub rate limit or a "
                        "missing/renamed repo. This is NOT a clean result. Set GITHUB_TOKEN "
                        "and re-run."}
    return {"level": level, "risk": risk, "findings": findings[:40], "files_scanned": len(files),
            "note": "Heuristic risk assessment, not a certification — a clean scan means these "
                    "checks found nothing, not that the repo is safe."}


# ── License / resale gate ────────────────────────────────────────────────────
# When the thing you are building gets SOLD, license is not a footnote — it decides
# whether a dependency is usable at all. GitHub reports an SPDX id, "NOASSERTION" for
# anything it cannot classify (which is where BUSL/PolyForm/Elastic/SSPL land), or
# nothing at all for a repo with no LICENSE file.
PERMISSIVE = {"MIT", "MIT-0", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "BSD-3-CLAUSE-CLEAR",
              "ISC", "UNLICENSE", "0BSD", "ZLIB", "PSF-2.0", "WTFPL", "BSL-1.0", "CC0-1.0"}
WEAK_COPYLEFT = {"MPL-2.0", "LGPL-2.1", "LGPL-3.0", "EPL-2.0", "CDDL-1.0"}
STRONG_COPYLEFT = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "SSPL-1.0", "OSL-3.0", "EUPL-1.2"}
SOURCE_AVAILABLE_HINT = re.compile(
    r"(business source|BUSL|polyform|elastic license|commons clause|SSPL|"
    r"server side public|fair source|functional source|non-?commercial|CC BY-NC)", re.I)


def license_risk(meta, for_resale=True):
    """Can this be shipped inside something we sell? Facts + a call, never a legal opinion."""
    raw = (meta.get("license") or "").strip()
    up = raw.upper()
    if not for_resale:
        return {"verdict": "n/a", "license": raw or "—",
                "reason": "Resale gate is off (config.commercial.resale = false)."}
    if up in PERMISSIVE:
        return {"verdict": "clear", "license": raw,
                "reason": "Permissive — attribution is normally the only obligation."}
    if up in WEAK_COPYLEFT:
        return {"verdict": "caution", "license": raw,
                "reason": "File-level / linking copyleft. Usually shippable if kept as an "
                          "unmodified dependency, but modifications to ITS files must be "
                          "published. Do not vendor-and-edit."}
    if up in STRONG_COPYLEFT:
        net = " AGPL extends this to users reached over a network, so a hosted service " \
              "counts as distribution." if up == "AGPL-3.0" else ""
        return {"verdict": "blocked", "license": raw,
                "reason": "Strong copyleft — linking it into a proprietary product obliges "
                          "you to release that product's source under the same terms.%s" % net}
    if up in ("NOASSERTION", "OTHER"):
        blob = " ".join(str(meta.get(k, "")) for k in ("desc", "why")) + " " + raw
        if SOURCE_AVAILABLE_HINT.search(blob):
            return {"verdict": "blocked", "license": raw,
                    "reason": "Reads as source-available (BUSL / PolyForm / Elastic / SSPL "
                              "family). These are written specifically to block resale."}
        return {"verdict": "caution", "license": raw,
                "reason": "GitHub could not classify the license — often a custom or "
                          "source-available term. Read LICENSE by hand before shipping it."}
    if not raw or raw == "—":
        return {"verdict": "blocked", "license": "none",
                "reason": "No LICENSE file. No license means no grant: default copyright "
                          "reserves all rights to the author. Not usable in a sold product."}
    return {"verdict": "caution", "license": raw,
            "reason": "Unrecognized license id — read it before shipping."}


def apply_license(meta):
    """Fold resale risk into the verdict. Like safety: it can downgrade, never upgrade."""
    d, lic = meta.get("dossier"), meta.get("commercial")
    if not d or not lic or lic["verdict"] in ("clear", "n/a"):
        return
    if lic["verdict"] == "blocked" and d.get("verdict") == "GO":
        d["verdict"] = "MAYBE"
        d["recommendation"] = ("⚠ LICENSE (%s): %s Fine to study or self-host; NOT shippable "
                               "inside something you sell. " % (lic["license"], lic["reason"])
                               ) + str(d.get("recommendation", ""))
    elif lic["verdict"] == "caution":
        d["recommendation"] = ("⚠ LICENSE (%s): %s " % (lic["license"], lic["reason"])
                               ) + str(d.get("recommendation", ""))


def apply_safety(meta):
    """Fuse the safety level into the dossier verdict — findings downgrade, never upgrade."""
    d, s = meta.get("dossier"), meta.get("safety")
    if not d or not s:
        return
    if s["level"] == "high" and d.get("verdict") != "SKIP":
        d["verdict"] = "SKIP"
        d["recommendation"] = ("⚠ SAFETY: high-risk findings (see safety scan) — verdict "
                               "downgraded to SKIP. ") + str(d.get("recommendation", ""))
    elif s["level"] == "unknown" and d.get("verdict") == "GO":
        d["verdict"] = "MAYBE"
        d["recommendation"] = ("⚠ SAFETY: scan read zero files (rate limit or missing repo) — "
                               "verdict capped at MAYBE until a real scan runs. ") + str(
            d.get("recommendation", ""))
    elif s["level"] == "medium" and d.get("verdict") == "GO":
        d["verdict"] = "MAYBE"
        d["recommendation"] = ("⚠ SAFETY: medium-risk findings (see safety scan) — verdict "
                               "capped at MAYBE. ") + str(d.get("recommendation", ""))


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
STORE_LOCK = OUT + ".lock"


@contextlib.contextmanager
def _flock(timeout=180):
    """Exclusive advisory lock on the store. Two concurrent `evaluate` runs used to
    read-modify-write the same file and the loser's records vanished."""
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    fh = open(STORE_LOCK, "a+")
    deadline = time.time() + timeout
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError("store lock still held after %ds — is another "
                                       "repohunter run stuck?" % timeout)
                time.sleep(0.25)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _load_store():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"repos": []}


def _write_store(store, specs=None):
    """Serialize the store atomically. Caller must already hold the lock."""
    store["repos"].sort(key=lambda x: (x.get("scores") or {}).get("overall", 0), reverse=True)
    store.update({"schema": STORE_SCHEMA, "generated": NOW, "count": len(store["repos"])})
    if specs:
        store["machine"] = specs
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    # Write-then-rename: a crash mid-write leaves the old store intact instead of a
    # half-written file that fails to parse on the next load.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(store, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, OUT)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _save_store(store, specs=None):
    with _flock():
        _write_store(store, specs)


@contextlib.contextmanager
def store_txn(specs=None):
    """Read-modify-write the store under one lock. Do NOT do network or LLM work
    inside this block — the lock is held for its whole duration."""
    with _flock():
        store = _load_store()
        yield store
        _write_store(store, specs)


def _find(store, rid):
    return next((x for x in store["repos"] if x["id"].lower() == rid.lower()), None)


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
    meta["commercial"] = license_risk(meta, RESALE)
    meta["status"] = "candidate"
    if deep or (isinstance(entry, dict) and entry.get("featured")):
        meta["safety"] = safety_scan(slug)
        meta["dossier"] = make_dossier(meta, specs)
        apply_safety(meta)
        apply_license(meta)
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
    with store_txn(specs) as store:
        store["repos"] = [x for x in store["repos"] if x.get("id") != r["id"]] + [r]
    lic = r.get("commercial") or {}
    tag = "" if lic.get("verdict") in ("clear", "n/a", None) else \
        "  [license: %s — %s]" % (lic.get("license"), lic.get("verdict").upper())
    print("→ evaluated %s (%s)%s" % (r["id"], r.get("dossier", {}).get("verdict", "?"), tag))
    return 0


def plan_mode(slug):
    rid = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    with store_txn() as store:
        repo = _find(store, rid)
        if not repo:
            print("not in store: %s" % rid); return 1
        specs = store.get("machine") or machine_specs()
        repo["integration"] = {"status": "planning", "updated": NOW}
        snapshot = dict(repo)
    # make_plan calls an LLM — minutes, sometimes. Do it OUTSIDE the lock, then
    # re-open the store to write the result.
    plan = make_plan(snapshot, specs)
    with store_txn() as store:
        repo = _find(store, rid)
        if repo is None:
            print("not in store: %s" % rid); return 1
        repo["integration"] = {"status": "planned", "plan": plan, "updated": NOW}
    print("planned %s" % rid); return 0


def scan_mode(slug, as_json=False):
    slug = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    s = safety_scan(slug)
    if as_json:
        print(json.dumps({"repo": slug, **s}, indent=2)); return 0
    icon = {"clean": "✓", "low": "·", "medium": "⚠", "high": "✗",
            "unknown": "?"}[s["level"]]
    print("%s %s — %s risk (%d/100), %d file(s) scanned" % (
        icon, slug, s["level"].upper(), s["risk"], s["files_scanned"]))
    for f in s["findings"]:
        print("  [%s] %s — %s%s" % (f["severity"], f["file"], f["kind"],
                                    ("  ›› " + f["excerpt"]) if f["excerpt"] else ""))
    print("  (%s)" % s["note"])
    return 0


def decide_mode(slug, decision):
    rid = re.sub(r".*github\.com/", "", slug).replace(".git", "").strip("/")
    with store_txn() as store:
        repo = _find(store, rid)
        if not repo:
            print("not in store: %s" % rid); return 1
        ig = repo.get("integration") or {}
        repo["integration"] = {"status": "approved" if decision == "approve" else "evaluated",
                               "plan": ig.get("plan"), "updated": NOW}
        status = repo["integration"]["status"]
    print("%s -> %s" % (rid, status)); return 0


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
    specs = machine_specs()
    src = {"type": "youtube", "title": title, "url": url, "id": info.get("id", "")}
    known = {x["id"].lower() for x in _load_store()["repos"]}
    wanted, fetched = [], []
    for slug in sorted(slugs):
        slug = re.sub(r"[^A-Za-z0-9_./\-]", "", slug)
        if slug.count("/") != 1 or slug.endswith("/"):
            continue
        wanted.append(slug)
        if slug in known:
            continue
        # Network work happens BEFORE the lock — holding it across N GitHub calls
        # would block every other repohunter process for minutes.
        meta = fetch_repo(slug)
        if not meta:
            continue
        meta.update({"category": "From a video", "why": "Recommended in: %s" % title,
                     "scores": score(meta, title), "resource_fit": resource_fit(meta, specs),
                     "status": "candidate", "sources": [src]})
        fetched.append(meta)
    added = 0
    with store_txn(specs) as store:
        have = {x["id"].lower(): x for x in store["repos"]}
        for slug in wanted:  # re-check under the lock; another run may have added it
            if slug in have:
                have[slug].setdefault("sources", [])
                if not any(x.get("id") == src["id"] for x in have[slug]["sources"]):
                    have[slug]["sources"].append(src)
        for meta in fetched:
            if meta["id"].lower() in have:
                continue
            store["repos"].append(meta); have[meta["id"].lower()] = meta; added += 1
            print("  + %s" % meta["id"].lower())
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


def profiles_mode():
    """List the project lenses this config can evaluate against."""
    names = profile_names(CFG)
    if not names:
        print("No named profiles. Using the single \"project\" block: %s"
              % (CFG["project"].get("name") or "(unnamed)"))
        print("\nAdd a \"profiles\" map to config.json to evaluate one repo against "
              "several projects.")
        return 0
    default = CFG.get("default_profile") or names[0]
    for n in names:
        p = (CFG.get("profiles") or {}).get(n) or {}
        mark = "*" if n == (ACTIVE_PROFILE or default) else " "
        print("%s %-16s %s" % (mark, n, (p.get("name") or "")))
    print("\n* = active. Select with --profile <name> or REPOHUNTER_PROFILE.")
    return 0


USAGE = """RepoHunter — reuse, don't reinvent.

  repohunter refresh                     build the store from your config.json seed
  repohunter evaluate <owner/repo>       deep-evaluate one repo
  repohunter plan <owner/repo>           draft an integration plan
  repohunter decide <owner/repo> approve|reject
  repohunter ingest-video <youtube-url>  mine a video for the repos it recommends
  repohunter scan <owner/repo> [--json]  safety scan only: prompt-injection, hidden
                                         text, piped installs, leaked secrets
  repohunter serve                       serve the UI + API on http://127.0.0.1:<port>
  repohunter profiles                    list the project lenses in your config

Global:
  --profile <name>                       evaluate against a named profile from config.json
                                         (or set REPOHUNTER_PROFILE)
"""


def main(argv=None):
    """CLI entry point. Also the console_scripts target so `repohunter <cmd>` works."""
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "refresh"
    a = argv[1:]
    if cmd in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    # Strict here even though import-time selection is lenient: scoring a repo against
    # the wrong project is a confidently wrong answer, and those are the expensive kind.
    want = os.environ.get("REPOHUNTER_PROFILE") or _argv_profile(argv)
    if want:
        try:
            resolve_profile(CFG, want)
        except KeyError:
            known = ", ".join(profile_names(CFG)) or "(none defined)"
            sys.stderr.write("error: unknown profile '%s'. Known profiles: %s\n" % (want, known))
            return 2
    needs = {"evaluate": 1, "plan": 1, "ingest-video": 1, "decide": 2, "scan": 1}
    if cmd in needs and len(a) < needs[cmd]:
        sys.stderr.write("error: '%s' needs %d argument(s).\n\n%s" % (cmd, needs[cmd], USAGE))
        return 2
    fn = {"evaluate": lambda: evaluate(a[0]), "plan": lambda: plan_mode(a[0]),
          "decide": lambda: decide_mode(a[0], a[1]), "ingest-video": lambda: ingest_video(a[0]),
          "scan": lambda: scan_mode(a[0], as_json="--json" in a),
          "serve": serve, "refresh": refresh, "profiles": profiles_mode}.get(cmd)
    if fn is None:
        sys.stderr.write("error: unknown command '%s'.\n\n%s" % (cmd, USAGE))
        return 2
    return fn() or 0


if __name__ == "__main__":
    sys.exit(main())
