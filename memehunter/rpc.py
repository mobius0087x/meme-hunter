"""Minimal Robinhood-Chain JSON-RPC client + address classification.

Used by forensics.py to do the cheap-on-fresh-tokens on-chain checks that
GeckoTerminal can't answer: who actually holds the token, and is a "holder"
a real wallet, a shared router/market-maker, or the launchpad factory.

Design notes learned the hard way (2026-07-13 WALLET/CASHCAT study):
  * NEVER attribute a "cluster" before excluding multi-token routers/MM. A
    contract that has *sent >~20 distinct tokens* in a recent window is shared
    infrastructure, not a bespoke bot — its balance/flow is not a red flag.
  * `0xd9ec…` is the Noxa launchpad *factory* (minted 60k+ tokens); a mint
    from it is the pad mechanic, not insider premine.
All calls are best-effort: on any failure they return None/〈empty〉 so a
forensics hiccup never kills the hunting loop.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from .config import RPC_URL

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40
DEAD = "0x000000000000000000000000000000000000dead"
# Noxa launchpad factory — mints go THROUGH here; treat as infra, not a holder.
NOXA_FACTORY = "0xd9ec2db5f3d1b236843925949fe5bd8a3836fccb"

_UA = {"Content-Type": "application/json", "User-Agent": "rh-meme-hunter/1.0"}


class RPC:
    def __init__(self, url: str = RPC_URL) -> None:
        self.url = url
        self._id = 0
        self._session = requests.Session()
        self._session.headers.update(_UA)
        self._code_cache: Dict[str, bool] = {}
        self._router_cache: Dict[str, bool] = {}

    def call(self, method: str, params: list, retries: int = 3) -> Any:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        for attempt in range(retries):
            try:
                r = self._session.post(self.url, json=body, timeout=30)
                r.raise_for_status()
                d = r.json()
                if "error" in d:
                    return None
                return d.get("result")
            except (requests.RequestException, ValueError):
                time.sleep(0.4 * (attempt + 1))
        return None

    # ---- primitives ----------------------------------------------------
    def block_number(self) -> Optional[int]:
        return _hexint(self.call("eth_blockNumber", []))

    def eth_call(self, to: str, data: str) -> Any:
        return self.call("eth_call", [{"to": to, "data": data}, "latest"])

    def get_code(self, addr: str) -> str:
        c = self.call("eth_getCode", [addr, "latest"])
        return c if isinstance(c, str) else "0x"

    def is_contract(self, addr: str) -> bool:
        if addr not in self._code_cache:
            self._code_cache[addr] = self.get_code(addr) != "0x"
        return self._code_cache[addr]

    def total_supply(self, token: str) -> Optional[int]:
        return _hexint(self.eth_call(token, "0x18160ddd"))

    def balance_of(self, token: str, holder: str) -> Optional[int]:
        data = "0x70a08231" + holder[2:].rjust(64, "0")
        return _hexint(self.eth_call(token, data))

    def get_logs(self, params: dict) -> Optional[list]:
        r = self.call("eth_getLogs", [params])
        return r if isinstance(r, list) else None

    # ---- classification -------------------------------------------------
    def is_router_or_mm(self, addr: str, latest: int, span: int = 60_000,
                        threshold: int = 20) -> bool:
        """True if `addr` is shared infra (a contract that has SENT >=threshold
        distinct token contracts in the last `span` blocks). Cached."""
        if addr in self._router_cache:
            return self._router_cache[addr]
        if not self.is_contract(addr):
            self._router_cache[addr] = False
            return False
        top = "0x" + addr[2:].rjust(64, "0")
        toks: set[str] = set()
        b = max(0, latest - span)
        chunk = 30_000
        while b <= latest and len(toks) < threshold:
            hi = min(b + chunk, latest)
            logs = self.get_logs({"topics": [TRANSFER_TOPIC, top],
                                  "fromBlock": hex(b), "toBlock": hex(hi)})
            if logs is None:
                break
            for lg in logs:
                toks.add(lg["address"].lower())
            b = hi + 1
        infra = len(toks) >= threshold
        self._router_cache[addr] = infra
        return infra

    def is_infra(self, addr: str, latest: int) -> bool:
        """Any address whose balance should NOT count as a concentrated holder:
        the pool itself is handled by the caller; here we catch burn, the Noxa
        factory, and shared routers/MM."""
        a = addr.lower()
        if a in (ZERO, DEAD, NOXA_FACTORY):
            return True
        return self.is_router_or_mm(addr, latest)


def _hexint(h: Any) -> Optional[int]:
    if not isinstance(h, str) or h in ("0x", "0x0"):
        return 0 if h == "0x0" else None
    try:
        return int(h, 16)
    except ValueError:
        return None
