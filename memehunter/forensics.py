"""Graduation grading + on-chain rug forensics — the third stage of the brain.

Validated 2026-07-13 against WALLET (fresh, thin, sniped, narrative-pumped) vs
CASHCAT (graduated $163M blue-chip). The lesson that shaped this module:
*launch* forensics (snipe %, "whale" wallets, holder clusters) do NOT separate
winners from losers on a launchpad chain — CASHCAT was sniped HARDER than
WALLET yet graduated. What separates them is POST-launch structure: liquidity
depth, pool proliferation, use as an ecosystem quote asset, normalized turnover.

So this module splits cleanly:
  * graduation()  — ranks survival/depth from GeckoTerminal (the buy-side tag)
  * rug_scan()    — a hard AVOID gate only, from on-chain holders (cheap on
                    fresh tokens: a 4h token is ~150k blocks). Self-validates
                    via supply conservation; if it can't fully reconstruct in
                    budget it emits nothing rather than a wrong number.
On-chain gives a reliable AVOID and a weak BUY — labels are honest about that.
Everything here is best-effort: any failure returns a neutral grade so the
hunting loop never dies.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .rpc import RPC, TRANSFER_TOPIC, ZERO, DEAD
from .sources import GeckoTerminal, Pool

# rough recent cadence (862k blocks/day ≈ 600/min); only used to size the scan
# window for a token of known age — conservation check corrects any error.
BLOCKS_PER_MIN = 600
MAX_SCAN_BLOCKS = 700_000            # ~19h of history; older => rely on graduation only

# graduation thresholds — calibrated 2026-07-13 against the live RH token
# distribution (top ~28 by liquidity). CASHCAT ~94, VEX/ARROW (multi-pool
# ecosystems) ~70-79, $2M single-pools ~44, WALLET-class ~36, thin tail ~28-33.
GRADUATED_DEPTH_USD = 2_000_000      # deep enough to be "made" on depth alone
GRADUATED_SCORE = 65                 # or a multi-pool ecosystem (VEX/ARROW) even if shallower
GRADUATING_DEPTH_USD = 150_000
GRADUATING_SCORE = 35
GRADUATED_POOLS = 3                  # *material* pools (dust pools don't count)
# GeckoTerminal's /tokens/{addr}/pools caps at ~20 and lists dust pools, so raw
# pool count and any-quote flags are noise — only pools with real reserve count.
MATERIAL_POOL_USD = 10_000
# rug gate
RUG_TOP_HOLDER_PCT = 30.0           # one non-pool/non-router wallet holds >= this
RUG_VAULT_PCT = 15.0                # a fed contract (0 buys) holds >= this


@dataclass
class ForensicGrade:
    stage: str = "UNKNOWN"                       # RUG-RISK/FRESH/GRADUATING/GRADUATED/COOLING
    graduation_score: float = 0.0               # 0-100 survival/depth
    depth_usd: float = 0.0
    n_pools: int = 0
    used_as_quote: bool = False
    top_holder_pct: Optional[float] = None      # largest real (non-pool/non-infra) holder
    scanned: bool = False                        # did the on-chain rug scan complete?
    rug_flags: List[str] = field(default_factory=list)
    grad_signals: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# stage 1: graduation (GeckoTerminal only — cheap, run on every candidate)
# --------------------------------------------------------------------------
def graduation(pool: Pool, token_pools: List[dict]) -> ForensicGrade:
    g = ForensicGrade()
    if not token_pools:
        # fall back to the single pool we already have
        g.depth_usd = pool.liquidity_usd
        g.n_pools = 1 if pool.liquidity_usd >= MATERIAL_POOL_USD else 0
    else:
        g.depth_usd = sum(_num(p.get("reserve_in_usd")) for p in token_pools)
        # count only *material* pools; dust pools (and the API's 20-cap) are noise
        material = [p for p in token_pools if _num(p.get("reserve_in_usd")) >= MATERIAL_POOL_USD]
        g.n_pools = len(material)
        g.used_as_quote = any(p.get("_is_quote") for p in material)

    import math
    depth_pts = min(50.0, max(0.0, 12.5 * math.log10(max(g.depth_usd, 1) / 4_000)))
    pool_pts = min(20.0, 5.0 * max(0, g.n_pools - 1))
    quote_pts = 20.0 if g.used_as_quote else 0.0
    buyers = pool.tx("h24").get("buyers", 0) or pool.tx("h1").get("buyers", 0)
    buyer_pts = min(10.0, buyers / 50.0)
    g.graduation_score = round(min(100.0, depth_pts + pool_pts + quote_pts + buyer_pts), 1)

    if g.depth_usd >= GRADUATED_DEPTH_USD:
        g.grad_signals.append(f"deep liquidity ${g.depth_usd:,.0f} across {g.n_pools} pools")
    elif g.depth_usd >= GRADUATING_DEPTH_USD:
        g.grad_signals.append(f"building depth ${g.depth_usd:,.0f} ({g.n_pools} pools)")
    if g.n_pools >= 3:
        g.grad_signals.append(f"{g.n_pools} independent pools (LP conviction)")
    if g.used_as_quote:
        g.grad_signals.append("used as a quote/pairing asset (ecosystem base)")
    return g


# --------------------------------------------------------------------------
# stage 2: on-chain rug scan (RPC — only worth it on WATCH+ fresh tokens)
# --------------------------------------------------------------------------
def _reconstruct(rpc: RPC, token: str, start: int, latest: int
                 ) -> Optional[Tuple[Dict[str, int], int]]:
    """Return (balances, minted_supply) from Transfer logs in [start, latest],
    or None on RPC failure."""
    bal: Dict[str, int] = defaultdict(int)
    minted = 0
    b, chunk = start, 40_000
    while b <= latest:
        hi = min(b + chunk, latest)
        logs = rpc.get_logs({"address": token, "topics": [TRANSFER_TOPIC],
                             "fromBlock": hex(b), "toBlock": hex(hi)})
        if logs is None:
            if chunk > 2_000:
                chunk //= 2
                continue
            return None
        for lg in logs:
            frm = "0x" + lg["topics"][1][-40:]
            to = "0x" + lg["topics"][2][-40:]
            data = lg.get("data") or "0x"
            val = int(data, 16) if data not in ("0x", "") else 0
            if frm == ZERO:
                minted += val
            else:
                bal[frm] -= val
            bal[to] += val
        if len(logs) < 500 and chunk < 80_000:
            chunk = min(chunk * 2, 80_000)
        b = hi + 1
    return bal, minted


def rug_scan(rpc: RPC, token: str, pool_addr: str, age_min: Optional[float]) -> ForensicGrade:
    g = ForensicGrade()
    latest = rpc.block_number()
    if latest is None:
        return g
    # size the window from age (+30% buffer); cap it.
    if age_min is None:
        window = MAX_SCAN_BLOCKS
    else:
        window = min(MAX_SCAN_BLOCKS, int(age_min * BLOCKS_PER_MIN * 1.3) + 20_000)
    start = max(0, latest - window)

    rec = _reconstruct(rpc, token, start, latest)
    if rec is None:
        return g
    bal, minted = rec
    supply = rpc.total_supply(token) or minted
    if not supply:
        return g

    # conservation guard: if we didn't capture the whole history, don't trust
    # concentration numbers. Retry once at full window, else bail (scanned=False).
    total = sum(bal.values())
    if abs(total - supply) > supply // 1000 and window < MAX_SCAN_BLOCKS:
        rec = _reconstruct(rpc, token, max(0, latest - MAX_SCAN_BLOCKS), latest)
        if rec is None:
            return g
        bal, minted = rec
        total = sum(bal.values())
    if abs(total - supply) > supply // 1000:
        return g  # incomplete — leave scanned=False, rely on graduation grade

    g.scanned = True
    pool_l = pool_addr.lower()
    holders = sorted(((a, v) for a, v in bal.items()
                      if v > 0 and a not in (ZERO, DEAD) and a != pool_l),
                     key=lambda x: -x[1])

    # find the largest REAL holder (exclude shared routers / MM / factory)
    top_real_pct = 0.0
    for a, v in holders[:15]:
        if rpc.is_infra(a, latest):
            continue
        pct = 100.0 * v / supply
        if top_real_pct == 0.0:
            top_real_pct = pct
            g.top_holder_pct = round(pct, 2)
        # fed vault: a non-infra CONTRACT holding a big stack (bundled allocation)
        if rpc.is_contract(a) and pct >= RUG_VAULT_PCT:
            g.rug_flags.append(f"contract wallet holds {pct:.1f}% (fed/vault allocation)")
        break  # only need the top real holder for the headline flag

    if top_real_pct >= RUG_TOP_HOLDER_PCT:
        g.rug_flags.append(f"single wallet holds {top_real_pct:.1f}% (excl pool/router)")

    # LP drain: almost nothing left in the pool relative to supply on an
    # already-aged token => liquidity pulled.
    lp_pct = 100.0 * bal.get(pool_l, 0) / supply
    if age_min and age_min > 60 and lp_pct < 1.0:
        g.rug_flags.append(f"LP holds only {lp_pct:.1f}% of supply — possible drain")
    return g


# --------------------------------------------------------------------------
# combine
# --------------------------------------------------------------------------
def grade(pool: Pool, gt: GeckoTerminal, rpc: Optional[RPC] = None,
          do_rug_scan: bool = True) -> ForensicGrade:
    """Full third-stage grade for one pool. GeckoTerminal graduation always;
    on-chain rug scan only when `rpc` given and `do_rug_scan` (reserve it for
    WATCH+ candidates so a cron cycle stays inside its minute budget)."""
    token = pool.base_address
    try:
        tp = gt.token_pools_raw(token) if token else []
    except Exception:
        tp = []
    g = graduation(pool, tp)

    if rpc is not None and do_rug_scan and token:
        try:
            rg = rug_scan(rpc, token, pool.address, pool.age_min)
            g.scanned = rg.scanned
            g.top_holder_pct = rg.top_holder_pct
            g.rug_flags = rg.rug_flags
        except Exception:
            pass

    # ---- stage label ----
    pc_h1 = pool.price_change.get("h1", 0)
    turnover = pool.volume.get("h1", 0) / max(pool.liquidity_usd, 1)
    if g.rug_flags:
        g.stage = "RUG-RISK"
    elif pc_h1 <= -30 and turnover >= 3:
        g.stage = "COOLING"          # dumping on high turnover = distribution
    elif g.depth_usd >= GRADUATED_DEPTH_USD or g.graduation_score >= GRADUATED_SCORE:
        g.stage = "GRADUATED"        # deep, or a real multi-pool ecosystem — move mostly made
    elif (g.depth_usd >= GRADUATING_DEPTH_USD or g.n_pools >= 2
          or g.graduation_score >= GRADUATING_SCORE):
        g.stage = "GRADUATING"       # building real depth — the buy-side sweet spot
    else:
        g.stage = "FRESH"            # thin/young — momentum lottery, size accordingly
    return g


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
