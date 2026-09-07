"""Configuration for the Robinhood Chain meme hunter.

Every threshold is overridable via environment variable so you can retune the
agent mid-run without touching code. Defaults are tuned for a 2-week short-play:
biased toward *early* entries with enough liquidity to actually exit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ---- optional .env loading (no hard dependency) ---------------------------
try:  # pragma: no cover - convenience only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv not installed -> rely on real env
    pass


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _s(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Robinhood Chain identity (verified 2026-07-09).
CHAIN_ID = 4663
GT_NETWORK = "robinhood"        # GeckoTerminal network id
DS_CHAIN = "robinhood"          # Dexscreener chain slug
RPC_URL = _s("RH_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")

# The quote tokens we treat as "real" liquidity. Pools quoted in anything else
# get a warning (could be a paired-shitcoin trap).
GOOD_QUOTE_SYMBOLS = {"WETH", "ETH", "USDG", "USDC", "USDT"}

# Narrative lexicon — Robinhood-chain memes that fit the current meta score
# higher (CASHCAT-style mascot / ticker-culture plays run hardest here).
NARRATIVE_KEYWORDS = {
    "cash", "cat", "hood", "robin", "vlad", "tendies", "diamond", "hand",
    "hodl", "moon", "rocket", "gme", "stonk", "yolo", "ape", "degen", "pepe",
    "doge", "wojak", "chad", "based", "flat",  # "the world is flat" launch meme
}


@dataclass
class Thresholds:
    # ---- hard safety gate (fail => rejected outright) ----
    min_liquidity_usd: float = field(default_factory=lambda: _f("MH_MIN_LIQ", 4_000))
    min_buyers_h1: int = field(default_factory=lambda: _i("MH_MIN_BUYERS", 3))
    # honeypot proxy: many buys, zero sells, past the grace window => can't sell
    honeypot_min_buys: int = field(default_factory=lambda: _i("MH_HP_BUYS", 8))
    honeypot_grace_min: float = field(default_factory=lambda: _f("MH_HP_GRACE_MIN", 12))
    # thin-float trap: FDV wildly above pooled liquidity
    max_fdv_to_liq: float = field(default_factory=lambda: _f("MH_MAX_FDV_LIQ", 60))

    # ---- soft warnings (cap tier at WATCH, dock score) ----
    min_age_min: float = field(default_factory=lambda: _f("MH_MIN_AGE_MIN", 3))
    # already-pumped: if 1h change above this, entry is late
    late_pump_h1_pct: float = field(default_factory=lambda: _f("MH_LATE_PUMP", 500))

    # ---- discovery window ----
    max_age_min: float = field(default_factory=lambda: _f("MH_MAX_AGE_MIN", 240))

    # ---- tier cutoffs on the 0-100 momentum score ----
    tier_watch: float = field(default_factory=lambda: _f("MH_TIER_WATCH", 42))
    tier_alert: float = field(default_factory=lambda: _f("MH_TIER_ALERT", 60))
    tier_hot: float = field(default_factory=lambda: _f("MH_TIER_HOT", 78))


@dataclass
class Settings:
    poll_seconds: int = field(default_factory=lambda: _i("MH_POLL_SECONDS", 30))
    # re-alert the same token only if its tier escalates, or after this cooldown
    alert_cooldown_min: float = field(default_factory=lambda: _f("MH_COOLDOWN_MIN", 30))
    # cloud/cron cold start: on the very first run (empty state) only alert pools
    # younger than this, so a cold start doesn't dump the whole board at once.
    cold_start_max_age_min: float = field(default_factory=lambda: _f("MH_COLD_START_AGE_MIN", 15))
    # GeckoTerminal free tier is ~30 req/min; keep a floor between calls
    gt_min_interval_s: float = field(default_factory=lambda: _f("MH_GT_INTERVAL_S", 2.2))
    thresholds: Thresholds = field(default_factory=Thresholds)

    # notifier config
    telegram_token: Optional[str] = field(default_factory=lambda: os.environ.get("MH_TG_TOKEN"))
    telegram_chat_id: Optional[str] = field(default_factory=lambda: os.environ.get("MH_TG_CHAT_ID"))
    # optional GoPlus token-security enrichment (may not cover chain 4663 yet)
    enable_goplus: bool = field(default_factory=lambda: _s("MH_GOPLUS", "1") == "1")
    # third stage: graduation grading + on-chain rug scan (forensics.py). The
    # rug scan is cheap on fresh tokens (a 4h token ~= 150k blocks); it stages
    # each actionable pool GRADUATED/GRADUATING/FRESH and drops RUG-RISK ones.
    enable_forensics: bool = field(default_factory=lambda: _s("MH_FORENSICS", "1") == "1")
    # cap deep on-chain scans per cycle so a cron run stays inside its budget
    forensic_max: int = field(default_factory=lambda: _i("MH_FORENSIC_MAX", 25))

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


SETTINGS = Settings()
