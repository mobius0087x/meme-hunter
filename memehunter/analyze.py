"""Safety gating + momentum scoring.

`evaluate()` is the whole brain: it takes a normalized Pool, runs the hard
safety gate, computes a 0-100 momentum score, applies soft-warning caps, and
returns a Verdict the loop can act on.

None of these checks are a substitute for reading the contract. They are
*heuristics over on-chain activity* designed to strip obvious rugs/wash and
rank what is worth a human's 30 seconds. Treat every alert as "look now", not
"buy now".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

from .config import GOOD_QUOTE_SYMBOLS, NARRATIVE_KEYWORDS, Thresholds
from .sources import Pool


class Tier(IntEnum):
    IGNORE = 0
    WATCH = 1
    ALERT = 2
    HOT = 3


TIER_LABEL = {Tier.IGNORE: "ignore", Tier.WATCH: "WATCH", Tier.ALERT: "ALERT", Tier.HOT: "HOT"}


@dataclass
class Verdict:
    pool: Pool
    tier: Tier
    score: float
    rejected: bool
    reasons: List[str] = field(default_factory=list)      # why rejected
    warnings: List[str] = field(default_factory=list)     # soft flags
    signals: List[str] = field(default_factory=list)      # positive drivers
    score_parts: Dict[str, float] = field(default_factory=dict)
    goplus: Optional[Dict[str, Any]] = None
    forensic: Optional[Any] = None                        # forensics.ForensicGrade (3rd stage)


def _narrative_hit(pool: Pool) -> bool:
    text = f"{pool.base_symbol} {pool.base_name} {pool.name}".lower()
    return any(k in text for k in NARRATIVE_KEYWORDS)


def safety_gate(pool: Pool, t: Thresholds, goplus: Optional[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    """Return (hard_reject_reasons, soft_warnings)."""
    reasons: List[str] = []
    warnings: List[str] = []
    h1 = pool.tx("h1")
    age = pool.age_min

    # --- hard rejects ---
    if pool.liquidity_usd < t.min_liquidity_usd:
        reasons.append(f"liquidity ${pool.liquidity_usd:,.0f} < ${t.min_liquidity_usd:,.0f}")
    if h1["buyers"] < t.min_buyers_h1:
        reasons.append(f"only {h1['buyers']} buyers/1h (< {t.min_buyers_h1})")
    # honeypot proxy: lots of buys, zero sells, past the grace window => nobody can sell
    if (
        age is not None
        and age >= t.honeypot_grace_min
        and h1["buys"] >= t.honeypot_min_buys
        and h1["sells"] == 0
    ):
        reasons.append(f"honeypot-proxy: {h1['buys']} buys / 0 sells after {age:.0f}m")
    if pool.liquidity_usd > 0 and pool.fdv_usd / max(pool.liquidity_usd, 1) > t.max_fdv_to_liq:
        reasons.append(
            f"thin float: FDV/liq {pool.fdv_usd / max(pool.liquidity_usd, 1):.0f}x > {t.max_fdv_to_liq:.0f}x"
        )

    # --- GoPlus hard flags (only if the endpoint returned data) ---
    if goplus:
        if str(goplus.get("is_honeypot")) == "1":
            reasons.append("GoPlus: honeypot")
        if str(goplus.get("cannot_sell_all")) == "1":
            reasons.append("GoPlus: cannot sell all")
        buy_tax = _pct(goplus.get("buy_tax"))
        sell_tax = _pct(goplus.get("sell_tax"))
        if sell_tax >= 20 or buy_tax >= 20:
            reasons.append(f"GoPlus: tax buy {buy_tax:.0f}% / sell {sell_tax:.0f}%")

    # --- soft warnings ---
    if age is not None and age < t.min_age_min:
        warnings.append(f"very new ({age:.1f}m) — data thin")
    if pool.quote_symbol and pool.quote_symbol.upper() not in GOOD_QUOTE_SYMBOLS:
        warnings.append(f"quoted in {pool.quote_symbol} (not a blue-chip quote)")
    if pool.price_change.get("h1", 0) > t.late_pump_h1_pct:
        warnings.append(f"already +{pool.price_change['h1']:.0f}%/1h — late entry")
    if pool.price_change.get("h1", 0) < -40:
        warnings.append(f"dumping {pool.price_change['h1']:.0f}%/1h — distribution")
    if h1["buyers"] <= 2 and pool.volume.get("h1", 0) > pool.liquidity_usd:
        warnings.append("wash-risk: high volume from <=2 buyers")
    if goplus and str(goplus.get("is_open_source")) == "0":
        warnings.append("GoPlus: contract not open-source")

    return reasons, warnings


def _pct(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f * 100 if f <= 1 else f  # GoPlus returns fractions like "0.05"


def momentum_score(pool: Pool) -> tuple[float, Dict[str, float], List[str]]:
    """0-100 momentum score with a breakdown and human-readable drivers."""
    parts: Dict[str, float] = {}
    signals: List[str] = []
    h1 = pool.tx("h1")
    m5 = pool.tx("m5")
    liq = max(pool.liquidity_usd, 1.0)

    # 1) turnover: 1h volume relative to pooled liquidity (max 30)
    vol_liq = pool.volume.get("h1", 0) / liq
    parts["turnover"] = min(30.0, vol_liq * 15)
    if vol_liq >= 1:
        signals.append(f"turnover {vol_liq:.1f}x liq/1h")

    # 2) buy pressure: skew of buys vs sells (max 20)
    buys, sells = h1["buys"], h1["sells"]
    buy_ratio = buys / (buys + sells + 1)
    parts["buy_pressure"] = max(0.0, (buy_ratio - 0.5) * 2) * 20
    if buy_ratio > 0.65 and buys >= 5:
        signals.append(f"{buy_ratio*100:.0f}% buys ({buys}/{buys+sells})")

    # 3) unique buyers: real distribution, not one whale (max 15)
    parts["buyers"] = min(15.0, h1["buyers"])
    if h1["buyers"] >= 15:
        signals.append(f"{h1['buyers']} unique buyers/1h")

    # 4) acceleration: is the last 5m hotter than the 1h average? (max 20)
    rate5 = pool.volume.get("m5", 0) / 5.0
    rate1h = pool.volume.get("h1", 0) / 60.0
    accel = rate5 / (rate1h + 1e-9)
    parts["acceleration"] = min(20.0, max(0.0, (accel - 1.0) * 10)) if rate1h > 0 else 0.0
    if accel > 1.5 and rate1h > 0:
        signals.append(f"accelerating {accel:.1f}x vs 1h avg")

    # 5) price change: reward an early uptrend, punish both already-mooned tops
    #    and active dumps (high turnover on a -60% candle is distribution).
    pc = pool.price_change.get("h1", 0)
    if pc >= 300:
        parts["price"] = -8.0                 # already mooned — late entry
    elif pc >= 0:
        parts["price"] = min(10.0, pc / 20)
    elif pc > -30:
        parts["price"] = max(-6.0, pc / 5)    # mild dip
    else:
        parts["price"] = -15.0                # being dumped
    if 20 < pc < 300:
        signals.append(f"+{pc:.0f}%/1h uptrend")

    # 6) narrative fit (max 8)
    if _narrative_hit(pool):
        parts["narrative"] = 8.0
        signals.append("on-meta name")
    else:
        parts["narrative"] = 0.0

    # 7) freshness sweet spot 5-90m (max 7)
    age = pool.age_min
    if age is not None and 5 <= age <= 90:
        parts["freshness"] = 7.0
    elif age is not None and age < 5:
        parts["freshness"] = 3.0
    else:
        parts["freshness"] = 0.0

    score = max(0.0, min(100.0, sum(parts.values())))
    return score, parts, signals


def evaluate(pool: Pool, t: Thresholds, goplus: Optional[Dict[str, Any]] = None) -> Verdict:
    reasons, warnings = safety_gate(pool, t, goplus)
    score, parts, signals = momentum_score(pool)

    if reasons:
        return Verdict(pool, Tier.IGNORE, score, True, reasons, warnings, signals, parts, goplus)

    # tier from score
    if score >= t.tier_hot:
        tier = Tier.HOT
    elif score >= t.tier_alert:
        tier = Tier.ALERT
    elif score >= t.tier_watch:
        tier = Tier.WATCH
    else:
        tier = Tier.IGNORE

    # soft warnings cap the tier at WATCH (still surfaced, just not hyped)
    if warnings and tier > Tier.WATCH:
        tier = Tier.WATCH
        signals.append("(tier capped: has warnings)")

    return Verdict(pool, tier, score, False, reasons, warnings, signals, parts, goplus)
