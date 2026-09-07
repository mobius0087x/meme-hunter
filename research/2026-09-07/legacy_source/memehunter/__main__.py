"""CLI entry point.

  python -m memehunter run     # continuous hunting loop (default, for a local/VPS host)
  python -m memehunter cloud   # ONE cycle then exit — for GitHub Actions / cron
  python -m memehunter scan    # one-shot: rank current pools, no alerts/state
  python -m memehunter test-tg # send a test Telegram message
"""
from __future__ import annotations

import argparse

from .analyze import TIER_LABEL, Tier, evaluate
from .config import SETTINGS
from .hunter import Hunter
from .notify import Notifier, render_line
from .sources import GeckoTerminal


def cmd_run() -> None:
    Hunter().run()


def cmd_cloud() -> None:
    """One cycle then exit — designed for a GitHub Actions / cron schedule.

    State (seen pools) is read from and written to state.json; in CI you restore
    and persist that file via actions/cache so alerts de-dup across runs.
    """
    h = Hunter()
    if not h.notifier.tg:
        h.notifier.log("⚠️  Telegram not configured — alerts go to this log only.")
    h.run_cycle()


def cmd_scan() -> None:
    gt = GeckoTerminal()
    t = SETTINGS.thresholds
    pools = {}
    for p in gt.new_pools() + gt.trending_pools():
        if p.address:
            pools.setdefault(p.address, p)
    verdicts = [
        evaluate(p, t)
        for p in pools.values()
        if p.age_min is None or p.age_min <= t.max_age_min  # early-hunt window
    ]
    shown = sorted(
        (v for v in verdicts if not v.rejected and v.tier >= Tier.WATCH),
        key=lambda v: (v.tier, v.score),
        reverse=True,
    )
    n = Notifier()
    n.banner(f"scan · {len(pools)} pools · {len(shown)} actionable")
    for v in shown:
        n.alert(v)
    if not shown:
        # show the closest misses so you can see the gate working
        near = sorted(verdicts, key=lambda v: v.score, reverse=True)[:5]
        n.log("no actionable pools. top rejected/low-score right now:")
        for v in near:
            why = "; ".join(v.reasons) if v.reasons else f"score {v.score:.0f}<watch"
            n.log(f"  {v.pool.base_symbol}: {why}")


def cmd_test_tg() -> None:
    if not SETTINGS.telegram_enabled:
        print("Telegram not configured. Set MH_TG_TOKEN and MH_TG_CHAT_ID.")
        return
    import requests

    r = requests.post(
        f"https://api.telegram.org/bot{SETTINGS.telegram_token}/sendMessage",
        json={"chat_id": SETTINGS.telegram_chat_id, "text": "✅ meme-hunter connected"},
        timeout=15,
    )
    print("sent" if r.ok else f"failed: {r.status_code} {r.text[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="memehunter", description="Robinhood Chain meme hunter")
    ap.add_argument(
        "command", nargs="?", default="run",
        choices=["run", "cloud", "scan", "test-tg"],
    )
    args = ap.parse_args()
    {"run": cmd_run, "cloud": cmd_cloud, "scan": cmd_scan, "test-tg": cmd_test_tg}[args.command]()


if __name__ == "__main__":
    main()
