"""Public signal feed: feed/signals.json, committed back to the repo by the
cloud cron (git-as-database, same pattern as predictpaul-track).

The Mobius Agent web console reads this file from raw.githubusercontent.com
to render the /signals page. Two sections:

  board  — every actionable (WATCH+) verdict from the LATEST cycle, ranked.
           A live "what is hot right now" view, regardless of alert dedup.
  alerts — rolling history of alerts that actually FIRED (what Telegram got),
           newest first, capped so the file stays small.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from .analyze import TIER_LABEL, Verdict

FEED_PATH = Path(__file__).resolve().parent.parent / "feed" / "signals.json"
ALERT_HISTORY_CAP = 100
BOARD_CAP = 25
TRANSITION_HISTORY_CAP = 60


def entry(v: Verdict, ts: Optional[float] = None, transition: Optional[Dict] = None) -> Dict:
    """Flatten a Verdict into a JSON-friendly record for the web feed."""
    p = v.pool
    h1 = p.tx("h1")
    fg = v.forensic
    forensic = None
    if fg is not None:
        forensic = {
            "stage": fg.stage,
            "graduation_score": fg.graduation_score,
            "depth_usd": round(fg.depth_usd, 2),
            "material_pools": fg.n_pools,
            "used_as_quote": fg.used_as_quote,
            "top_holder_pct": fg.top_holder_pct,
            "rug_scanned": fg.scanned,
            "rug_flags": fg.rug_flags,
        }
    return {
        "ts": int(ts if ts is not None else time.time()),
        "tier": TIER_LABEL[v.tier],
        "stage": fg.stage if fg is not None else None,
        "score": round(v.score, 1),
        "symbol": p.base_symbol,
        "name": p.base_name or p.name,
        "pool": p.address,
        "token": p.base_address,
        "dex": p.dex,
        "quote": p.quote_symbol,
        "liquidity_usd": round(p.liquidity_usd, 2),
        "fdv_usd": round(p.fdv_usd, 2),
        "vol_h1_usd": round(p.volume.get("h1", 0), 2),
        "price_usd": p.price_usd,
        "price_change_h1": round(p.price_change.get("h1", 0), 2),
        "age_min": round(p.age_min, 1) if p.age_min is not None else None,
        "buys_h1": h1["buys"],
        "sells_h1": h1["sells"],
        "buyers_h1": h1["buyers"],
        "signals": v.signals,
        "warnings": v.warnings,
        "forensic": forensic,
        "transition": transition,   # {kind, from, to} on re-grade entries, else None
        "links": {
            "dexscreener": p.dexscreener_url,
            "geckoterminal": p.geckoterminal_url,
            "uniswap": p.uniswap_url,
        },
    }


def _load_list(path: Path, key: str) -> List[Dict]:
    try:
        return json.loads(path.read_text()).get(key, [])
    except (OSError, ValueError, TypeError):
        return []


def write_feed(
    board: List[Verdict],
    fired: List[Verdict],
    stats: Dict,
    path: Path = FEED_PATH,
    transitions: Optional[List] = None,
) -> None:
    """Rewrite the feed file: fresh board, fired alerts + stage re-grades
    prepended to their rolling histories.

    Best-effort like the rest of the notifier stack — a feed write must never
    kill the hunting loop.
    """
    now = time.time()
    alerts = [entry(v, now) for v in fired] + _load_list(path, "alerts")
    new_trans = [
        entry(v, now, transition={
            "kind": kind,
            "from": from_stage or None,
            "to": (v.forensic.stage if v.forensic is not None else None),
        })
        for (v, kind, from_stage) in (transitions or [])
    ]
    trans_all = new_trans + _load_list(path, "transitions")
    payload = {
        "version": 1,
        "chain": "robinhood",
        "generated_at": int(now),
        "cycle": stats,
        "board": [entry(v, now) for v in board[:BOARD_CAP]],
        "alerts": alerts[:ALERT_HISTORY_CAP],
        "transitions": trans_all[:TRANSITION_HISTORY_CAP],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass
