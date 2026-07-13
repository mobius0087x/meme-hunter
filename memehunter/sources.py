"""Data sources for Robinhood Chain pools.

Primary firehose: GeckoTerminal `new_pools` + `trending_pools` for network
`robinhood` (verified working 2026-07-09). Dexscreener + GoPlus are used only
for links / optional enrichment so the agent still runs if they are down.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .config import CHAIN_ID, DS_CHAIN, GT_NETWORK, SETTINGS

GT_BASE = "https://api.geckoterminal.com/api/v2"
DS_BASE = "https://api.dexscreener.com"
GOPLUS_BASE = "https://api.gopluslabs.io/api/v1"

_UA = {"Accept": "application/json", "User-Agent": "rh-meme-hunter/1.0"}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _addr_from_gt_id(gt_id: Optional[str]) -> Optional[str]:
    # GeckoTerminal ids look like "robinhood_0xabc..."; take the 0x part.
    if not gt_id:
        return None
    return gt_id.split("_", 1)[-1] if "_" in gt_id else gt_id


@dataclass
class Pool:
    """Normalized view of a Robinhood Chain pool + its base token."""

    address: str                       # pool/pair contract
    name: str                          # e.g. "Cashhat / WETH 1%"
    dex: str                           # e.g. "uniswap-v3-robinhood"
    base_symbol: str
    base_name: str
    base_address: str
    quote_symbol: str
    created_at: Optional[datetime]
    liquidity_usd: float               # reserve_in_usd
    fdv_usd: float
    market_cap_usd: float
    price_usd: float
    price_change: Dict[str, float]     # m5/m15/m30/h1/h6/h24 (percent)
    volume: Dict[str, float]           # usd per window
    txns: Dict[str, Dict[str, int]]    # window -> {buys,sells,buyers,sellers}
    source: str = "geckoterminal"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_min(self) -> Optional[float]:
        if not self.created_at:
            return None
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() / 60.0

    def tx(self, window: str) -> Dict[str, int]:
        return self.txns.get(window, {"buys": 0, "sells": 0, "buyers": 0, "sellers": 0})

    # ---- one-tap links --------------------------------------------------
    @property
    def dexscreener_url(self) -> str:
        return f"https://dexscreener.com/{DS_CHAIN}/{self.address}"

    @property
    def geckoterminal_url(self) -> str:
        return f"https://www.geckoterminal.com/{GT_NETWORK}/pools/{self.address}"

    @property
    def uniswap_url(self) -> str:
        # Robinhood-chain Uniswap; chain must be selected manually in-app, but
        # the output token is prefilled.
        return (
            "https://app.uniswap.org/swap?"
            f"outputCurrency={self.base_address}&chain={GT_NETWORK}"
        )


def _parse_created(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class GeckoTerminal:
    """Thin, rate-limited GeckoTerminal client."""

    def __init__(self) -> None:
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update(_UA)

    def _throttle(self) -> None:
        wait = SETTINGS.gt_min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        self._throttle()
        try:
            r = self._session.get(f"{GT_BASE}{path}", params=params, timeout=20)
            self._last_call = time.monotonic()
            if r.status_code == 429:
                time.sleep(3)
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            self._last_call = time.monotonic()
            return None

    def _pools_from(self, payload: Optional[dict]) -> List[Pool]:
        if not payload:
            return []
        included = {
            (item["type"], item["id"]): item
            for item in payload.get("included", [])
        }
        pools: List[Pool] = []
        for d in payload.get("data", []):
            a = d.get("attributes", {})
            rel = d.get("relationships", {})
            base_id = (((rel.get("base_token") or {}).get("data")) or {}).get("id")
            quote_id = (((rel.get("quote_token") or {}).get("data")) or {}).get("id")
            dex_id = (((rel.get("dex") or {}).get("data")) or {}).get("id", "")
            base_tok = included.get(("token", base_id), {}).get("attributes", {})
            quote_tok = included.get(("token", quote_id), {}).get("attributes", {})

            name = a.get("name", "") or ""
            # Fallback base symbol parsed from "BASE / QUOTE 1%" naming.
            fallback_base = name.split("/")[0].strip() if "/" in name else name
            fallback_quote = (
                name.split("/")[1].strip().split(" ")[0] if "/" in name else ""
            )
            pools.append(
                Pool(
                    address=a.get("address", ""),
                    name=name,
                    dex=dex_id,
                    base_symbol=base_tok.get("symbol") or fallback_base,
                    base_name=base_tok.get("name") or fallback_base,
                    base_address=base_tok.get("address") or _addr_from_gt_id(base_id) or "",
                    quote_symbol=quote_tok.get("symbol") or fallback_quote,
                    created_at=_parse_created(a.get("pool_created_at")),
                    liquidity_usd=_num(a.get("reserve_in_usd")),
                    fdv_usd=_num(a.get("fdv_usd")),
                    market_cap_usd=_num(a.get("market_cap_usd")),
                    price_usd=_num(a.get("base_token_price_usd")),
                    price_change={k: _num(v) for k, v in (a.get("price_change_percentage") or {}).items()},
                    volume={k: _num(v) for k, v in (a.get("volume_usd") or {}).items()},
                    txns={
                        k: {
                            "buys": int(v.get("buys", 0) or 0),
                            "sells": int(v.get("sells", 0) or 0),
                            "buyers": int(v.get("buyers", 0) or 0),
                            "sellers": int(v.get("sellers", 0) or 0),
                        }
                        for k, v in (a.get("transactions") or {}).items()
                    },
                    raw=a,
                )
            )
        return pools

    def new_pools(self) -> List[Pool]:
        return self._pools_from(
            self._get(f"/networks/{GT_NETWORK}/new_pools", {"include": "base_token,quote_token,dex"})
        )

    def trending_pools(self) -> List[Pool]:
        return self._pools_from(
            self._get(
                f"/networks/{GT_NETWORK}/trending_pools",
                {"include": "base_token,quote_token,dex", "duration": "5m"},
            )
        )

    def token_pools_raw(self, token_address: str) -> List[Dict[str, Any]]:
        """Every pool GeckoTerminal knows for a token, as raw dicts with a
        `_is_quote` flag (True when the token is the pool's QUOTE side — i.e.
        it is being used as a pairing/base currency by another token). Used by
        forensics.graduation() to measure depth / pool-proliferation / whether
        the token has 'graduated' to an ecosystem quote asset."""
        payload = self._get(
            f"/networks/{GT_NETWORK}/tokens/{token_address}/pools",
            {"include": "base_token,quote_token"},
        )
        if not payload:
            return []
        want = token_address.lower()
        out: List[Dict[str, Any]] = []
        for d in payload.get("data", []):
            a = dict(d.get("attributes", {}))
            rel = d.get("relationships", {})
            quote_id = (((rel.get("quote_token") or {}).get("data")) or {}).get("id", "")
            quote_addr = (_addr_from_gt_id(quote_id) or "").lower()
            a["_is_quote"] = (quote_addr == want)
            out.append(a)
        return out


def goplus_security(token_address: str) -> Optional[Dict[str, Any]]:
    """Optional GoPlus token-security lookup. Returns None if unsupported."""
    if not SETTINGS.enable_goplus or not token_address:
        return None
    try:
        r = requests.get(
            f"{GOPLUS_BASE}/token_security/{CHAIN_ID}",
            params={"contract_addresses": token_address.lower()},
            headers=_UA,
            timeout=15,
        )
        if r.status_code != 200:
            return None
        # GoPlus returns {"result": null} (or omits chains it doesn't index),
        # so guard against a null result, not just a missing key.
        data = (r.json() or {}).get("result") or {}
        return data.get(token_address.lower())
    except requests.RequestException:
        return None
