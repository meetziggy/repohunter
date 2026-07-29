#!/usr/bin/env python3
"""RepoHunter — the token-savings math, in the open.

This is the EXACT algorithm behind the calculator at https://repohunter.dev (#estimate).
No trust required: run it, change the assumptions, argue with them.

    python3 token-math.py                 # default "active dev" scenario
    python3 token-math.py 8 500 6 0       # reuses/mo  lines/reuse  build-hrs  $/hr

Honesty notes:
  * Token COUNTS are computable — a tokenizer literally counts them. The only estimate is how much
    code you'd have regenerated and how much overhead generating it takes.
  * Model prices are illustrative and move over time — verify current rates yourself.
  * The "ecosystem" section is a back-of-the-envelope THOUGHT EXPERIMENT, not a measurement. Every
    input is here so you can change it and see the result move.

MIT (c) 2026 Chris Gorzelic & Brian Gorzelic.
"""
import json
import sys

# ── assumptions (all debatable — edit them) ──────────────────────────────────
OUTPUT_TOKENS_PER_LINE = 13        # ~50 chars/line / ~4 chars/token — the code itself
GEN_OVERHEAD = 3                   # x: the context you send + the 2-4 iterations to land it
ALLIN_TOKENS_PER_LINE = 40         # ≈ OUTPUT_TOKENS_PER_LINE * GEN_OVERHEAD (rounded)

# illustrative model prices — $ per 1,000,000 tokens (blended; verify current rates)
RATES = {"Budget": 2, "Standard": 10, "Premium": 40}


def per_user(reuses_per_month, lines_per_reuse, build_hours=0.0, hourly_rate=0.0):
    """What ONE developer saves by reusing instead of regenerating."""
    tokens_month = reuses_per_month * lines_per_reuse * ALLIN_TOKENS_PER_LINE
    tokens_year = tokens_month * 12
    return {
        "tokens_saved_per_month": round(tokens_month),
        "tokens_saved_per_year": round(tokens_year),
        "ai_dollars_saved_per_year": {t: round(tokens_year / 1_000_000 * r, 2) for t, r in RATES.items()},
        "hours_saved_per_month": reuses_per_month * build_hours,
        "time_value_per_month": round(reuses_per_month * build_hours * hourly_rate, 2),
    }


def ecosystem(ai_devs, redundant_lines_per_dev_day):
    """The scale of the waste — a thought experiment. Change the two inputs and re-run."""
    tokens_day = ai_devs * redundant_lines_per_dev_day * ALLIN_TOKENS_PER_LINE
    tokens_year = tokens_day * 365
    return {
        "redundant_tokens_per_day": round(tokens_day),
        "redundant_tokens_per_year": round(tokens_year),
        "ai_dollars_per_year": {t: round(tokens_year / 1_000_000 * r) for t, r in RATES.items()},
    }


if __name__ == "__main__":
    a = sys.argv[1:]
    reuses = float(a[0]) if len(a) > 0 else 8      # times/month you reuse instead of rebuild
    lines = float(a[1]) if len(a) > 1 else 500     # avg lines you'd have regenerated
    hours = float(a[2]) if len(a) > 2 else 6        # hours to build+own one yourself
    rate = float(a[3]) if len(a) > 3 else 0         # your $/hour (0 = skip time-value)

    print(f"all-in tokens/line = {ALLIN_TOKENS_PER_LINE}  "
          f"(≈ {OUTPUT_TOKENS_PER_LINE} output × {GEN_OVERHEAD} for context + retries)")
    print(f"model rates ($/1M) = {RATES}\n")

    print("== YOUR reuse savings ==")
    print(json.dumps(per_user(reuses, lines, hours, rate), indent=2))

    print("\n== The ecosystem, per day (back-of-the-envelope — edit the inputs) ==")
    for label, devs, lpd in [("low", 5_000_000, 60), ("mid", 10_000_000, 100), ("high", 25_000_000, 200)]:
        e = ecosystem(devs, lpd)
        print(f"[{label:>4}] {devs:>12,} AI devs × {lpd:>3} redundant lines/day  "
              f"→ {e['redundant_tokens_per_day']:>15,} tokens/day  |  $/yr {e['ai_dollars_per_year']}")
