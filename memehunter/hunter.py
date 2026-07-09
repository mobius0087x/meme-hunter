"""The hunting loop: poll -> dedup -> enrich -> gate -> score -> alert.

State (seen pools + last tier + cooldown) is persisted to a small JSON file so
restarts don't re-spam you with everything already surfaced.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .analyze import Tier, Verdict, evaluate
from .config import SETTINGS
from .notify import Notifier
from .sources import GeckoTerminal, goplus_security

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


@dataclass
class Seen:
    tier: int
    last_alert_ts: float
    best_score: float


class State:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.seen: Dict[str, Seen] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            self.seen = {k: Seen(**v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            self.seen = {}

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps({k: vars(v) for k, v in self.seen.items()})
            )
        except OSError:
            pass

    def mark_seen(self, addr: str, tier: Tier, score: float) -> None:
        """Record a pool as already-surfaced without firing an alert."""
        prev = self.seen.get(addr)
        best = max(score, prev.best_score) if prev else score
        self.seen[addr] = Seen(int(tier), time.time(), best)

    def should_alert(self, addr: str, tier: Tier, score: float, cooldown_min: float) -> bool:
        """Alert if new, tier escalated, or cooldown elapsed while still hot."""
        now = time.time()
        prev = self.seen.get(addr)
        fire = False
        if prev is None:
            fire = True
        elif tier > prev.tier:
            fire = True  # escalation always fires
        elif (now - prev.last_alert_ts) / 60.0 >= cooldown_min and tier >= Tier.ALERT:
            fire = True
        if fire:
            self.seen[addr] = Seen(int(tier), now, max(score, prev.best_score if prev else score))
        elif prev:
            prev.best_score = max(prev.best_score, score)
        return fire


class Hunter:
    def __init__(self) -> None:
        self.gt = GeckoTerminal()
        self.state = State()
        self.notifier = Notifier()
        self.t = SETTINGS.thresholds
        self.cycle = 0
        # cold start = no prior state (fresh process / first-ever cron run)
        self.cold_start = len(self.state.seen) == 0

    def _collect(self) -> Dict[str, "object"]:
        # merge new + trending, de-dup by pool address (trending flags momentum)
        pools = {}
        for p in self.gt.new_pools():
            if p.address:
                pools[p.address] = p
        for p in self.gt.trending_pools():
            if p.address:
                pools.setdefault(p.address, p)
        return pools

    def run_cycle(self) -> None:
        self.cycle += 1
        pools = self._collect()
        verdicts = []
        for p in pools.values():
            age = p.age_min
            if age is not None and age > self.t.max_age_min:
                continue  # outside discovery window
            gp = None
            # only spend a GoPlus call on things that already look interesting
            prelim = evaluate(p, self.t)
            if prelim.tier >= Tier.WATCH and SETTINGS.enable_goplus and p.base_address:
                gp = goplus_security(p.base_address)
            v = evaluate(p, self.t, gp) if gp is not None else prelim
            verdicts.append(v)

        actionable = sorted(
            (v for v in verdicts if not v.rejected and v.tier >= Tier.WATCH),
            key=lambda v: (v.tier, v.score),
            reverse=True,
        )
        fired = 0
        suppressed = 0
        for v in actionable:
            age = v.pool.age_min
            # cold-start guard: on the first run, silently record anything older
            # than the cold-start window so we don't flood on boot.
            if (
                self.cold_start
                and age is not None
                and age > SETTINGS.cold_start_max_age_min
            ):
                self.state.mark_seen(v.pool.address, v.tier, v.score)
                suppressed += 1
                continue
            if self.state.should_alert(
                v.pool.address, v.tier, v.score, SETTINGS.alert_cooldown_min
            ):
                self.notifier.alert(v)
                fired += 1
        self.state.save()
        self.cold_start = False  # only the first cycle is a cold start

        rejected = sum(1 for v in verdicts if v.rejected)
        cold = f" · {suppressed} cold-start-suppressed" if suppressed else ""
        self.notifier.log(
            f"cycle {self.cycle}: {len(pools)} pools · "
            f"{len(actionable)} actionable · {fired} alerted · {rejected} filtered{cold}"
        )

    def run(self) -> None:
        self.notifier.banner(
            f"Robinhood Chain meme hunter · poll {SETTINGS.poll_seconds}s · "
            f"telegram {'ON' if self.notifier.tg else 'off'}"
        )
        try:
            while True:
                start = time.monotonic()
                try:
                    self.run_cycle()
                except Exception as e:  # keep the loop alive on transient errors
                    self.notifier.log(f"cycle error: {e!r}")
                elapsed = time.monotonic() - start
                time.sleep(max(1.0, SETTINGS.poll_seconds - elapsed))
        except KeyboardInterrupt:
            self.notifier.banner("stopped")
            self.state.save()
