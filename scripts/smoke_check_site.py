#!/usr/bin/env python3
"""Post-deploy smoke check for repohunter.dev.

Confirms a handful of real pages return 200 and serve the expected <title>.
Stdlib only, matching the rest of this repo. Exits non-zero on any failure so
the deploy workflow fails loudly instead of a human noticing the site is down.

Run manually anytime: python3 scripts/smoke_check_site.py
"""
import re
import sys
import urllib.request

BASE = "https://repohunter.dev"
CHECKS = [
    ("/", "RepoHunter — reuse, don't reinvent"),
    ("/about", "About Chris Gorzelic — RepoHunter"),
    ("/brand", "RepoHunter — Brand Guide"),
    # Add ("/dickie-integration", "...") once that page's PR merges.
]


def check(path, expected_title):
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": "repohunter-smoke-check/1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
            body = r.read().decode("utf-8", "ignore")
    except Exception as e:
        return False, "request failed: %s" % e
    if status != 200:
        return False, "status %d, expected 200" % status
    m = re.search(r"<title>([^<]*)", body)
    title = m.group(1).strip() if m else ""
    if expected_title not in title:
        return False, "title %r does not contain %r" % (title, expected_title)
    return True, "ok"


def main():
    failures = 0
    for path, expected_title in CHECKS:
        ok, detail = check(path, expected_title)
        print(("OK  " if ok else "FAIL") + " %s — %s" % (path, detail))
        if not ok:
            failures += 1
    if failures:
        print("%d/%d checks failed" % (failures, len(CHECKS)), file=sys.stderr)
        sys.exit(1)
    print("%d/%d checks passed" % (len(CHECKS), len(CHECKS)))


if __name__ == "__main__":
    main()
