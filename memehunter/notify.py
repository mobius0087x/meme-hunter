"""Alert sinks: console (always on) + Telegram (if configured).

Console output degrades gracefully to plain print if `rich` is not installed.
"""
from __future__ import annotations

from typing import List

import requests

from .analyze import TIER_LABEL, Tier, Verdict
from .config import SETTINGS

try:
    from rich.console import Console

    _console = Console()
    _HAS_RICH = True
except Exception:  # pragma: no cover
    _console = None
    _HAS_RICH = False

_TIER_STYLE = {Tier.HOT: "bold red", Tier.ALERT: "bold yellow", Tier.WATCH: "cyan"}
_TIER_EMOJI = {Tier.HOT: "🔥", Tier.ALERT: "🚨", Tier.WATCH: "👀"}


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}k"
    return f"${v:.0f}"


def render_line(v: Verdict) -> str:
    p = v.pool
    age = f"{p.age_min:.0f}m" if p.age_min is not None else "?"
    return (
        f"{_TIER_EMOJI[v.tier]} {TIER_LABEL[v.tier]} [{v.score:.0f}] "
        f"{p.base_symbol}  liq {_fmt_usd(p.liquidity_usd)}  "
        f"vol1h {_fmt_usd(p.volume.get('h1', 0))}  age {age}  "
        f"{'+' if p.price_change.get('h1',0)>=0 else ''}{p.price_change.get('h1',0):.0f}%/1h"
    )


def _telegram_text(v: Verdict) -> str:
    p = v.pool
    age = f"{p.age_min:.0f}m" if p.age_min is not None else "?"
    lines = [
        f"{_TIER_EMOJI[v.tier]} <b>{TIER_LABEL[v.tier]}</b> · score {v.score:.0f} · <b>{p.base_symbol}</b>",
        f"{p.name}  ({p.dex})",
        f"liq {_fmt_usd(p.liquidity_usd)} · vol1h {_fmt_usd(p.volume.get('h1',0))} · "
        f"FDV {_fmt_usd(p.fdv_usd)} · age {age}",
        f"1h {p.price_change.get('h1',0):+.0f}%  ·  buys/sells "
        f"{p.tx('h1')['buys']}/{p.tx('h1')['sells']}  ·  buyers {p.tx('h1')['buyers']}",
    ]
    if v.signals:
        lines.append("✅ " + " · ".join(v.signals))
    if v.warnings:
        lines.append("⚠️ " + " · ".join(v.warnings))
    lines.append(
        f'<a href="{p.dexscreener_url}">Dexscreener</a> · '
        f'<a href="{p.geckoterminal_url}">GeckoTerminal</a> · '
        f'<a href="{p.uniswap_url}">Uniswap</a>'
    )
    lines.append(f"<code>{p.base_address}</code>")
    return "\n".join(lines)


class Notifier:
    def __init__(self) -> None:
        self.tg = SETTINGS.telegram_enabled

    def banner(self, text: str) -> None:
        if _HAS_RICH:
            _console.rule(f"[dim]{text}[/dim]")
        else:
            print(f"--- {text} ---")

    def log(self, text: str) -> None:
        if _HAS_RICH:
            _console.print(f"[dim]{text}[/dim]")
        else:
            print(text)

    def alert(self, v: Verdict) -> None:
        # console
        if _HAS_RICH:
            style = _TIER_STYLE.get(v.tier, "white")
            _console.print(render_line(v), style=style)
            p = v.pool
            _console.print(
                f"    {p.name}  {p.dexscreener_url}", style="dim"
            )
            if v.signals:
                _console.print("    ✅ " + " · ".join(v.signals), style="green")
            if v.warnings:
                _console.print("    ⚠️  " + " · ".join(v.warnings), style="yellow")
        else:
            print(render_line(v))
            print(f"    {v.pool.name}  {v.pool.dexscreener_url}")
            if v.signals:
                print("    ✅ " + " · ".join(v.signals))
            if v.warnings:
                print("    ⚠️  " + " · ".join(v.warnings))

        # telegram
        if self.tg:
            self._send_telegram(_telegram_text(v))

    def _send_telegram(self, text: str) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{SETTINGS.telegram_token}/sendMessage",
                json={
                    "chat_id": SETTINGS.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
        except requests.RequestException:
            self.log("(telegram send failed)")
