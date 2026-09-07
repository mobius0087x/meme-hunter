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
_STAGE_EMOJI = {
    "GRADUATED": "🎓", "GRADUATING": "🌱", "FRESH": "🍃",
    "COOLING": "🧊", "RUG-RISK": "⛔",
}


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}k"
    return f"${v:.0f}"


def _stage_str(v: Verdict) -> str:
    fg = v.forensic
    if fg is None:
        return ""
    return f"{_STAGE_EMOJI.get(fg.stage, '·')} {fg.stage}"


def render_line(v: Verdict) -> str:
    p = v.pool
    age = f"{p.age_min:.0f}m" if p.age_min is not None else "?"
    stage = f" {_stage_str(v)}" if v.forensic else ""
    return (
        f"{_TIER_EMOJI[v.tier]} {TIER_LABEL[v.tier]} [{v.score:.0f}]{stage} "
        f"{p.base_symbol}  liq {_fmt_usd(p.liquidity_usd)}  "
        f"vol1h {_fmt_usd(p.volume.get('h1', 0))}  age {age}  "
        f"{'+' if p.price_change.get('h1',0)>=0 else ''}{p.price_change.get('h1',0):.0f}%/1h"
    )


def _links_line(p) -> str:
    return (
        f'🔗 <a href="{p.dexscreener_url}">Dexscreener</a> · '
        f'<a href="{p.geckoterminal_url}">GeckoTerminal</a> · '
        f'<a href="{p.uniswap_url}">Uniswap</a>'
    )


def _telegram_text(v: Verdict) -> str:
    """Multi-line, section-separated card for readability in the TG feed."""
    p = v.pool
    fg = v.forensic
    h1 = p.tx("h1")
    age = f"{p.age_min:.0f}m" if p.age_min is not None else "?"
    turn = p.volume.get("h1", 0) / p.liquidity_usd if p.liquidity_usd else 0

    # header block
    head = [f"{_TIER_EMOJI[v.tier]} <b>{TIER_LABEL[v.tier]}</b> · <b>{p.base_symbol}</b>"]
    if fg is not None:
        head.append(f"{_STAGE_EMOJI.get(fg.stage, '·')} <b>{fg.stage}</b> · grad {fg.graduation_score:.0f} · mom {v.score:.0f}")
    else:
        head.append(f"momentum {v.score:.0f}")
    head.append(f"<i>{p.name}</i>")

    # stats block
    stats = [
        f"💧 liq {_fmt_usd(p.liquidity_usd)} · FDV {_fmt_usd(p.fdv_usd)}",
        f"📊 vol1h {_fmt_usd(p.volume.get('h1',0))} · {turn:.1f}x turnover",
        f"👥 buys {h1['buys']} / sells {h1['sells']} · {h1['buyers']} buyers",
        f"📈 1h {p.price_change.get('h1',0):+.0f}% · age {age}",
    ]
    if fg is not None and fg.scanned and fg.top_holder_pct is not None:
        stats.append(f"🧬 top holder {fg.top_holder_pct:.1f}% (excl pool/router)")

    # read block
    read = []
    if v.signals:
        read += [f"✅ {s}" for s in v.signals[:4]]
    if v.warnings:
        read += [f"⚠️ {w}" for w in v.warnings[:3]]

    blocks = ["\n".join(head), "\n".join(stats)]
    if read:
        blocks.append("\n".join(read))
    blocks.append(_links_line(p) + f"\n<code>{p.base_address}</code>")
    return "\n\n".join(blocks)


def _telegram_transition_text(v: Verdict, kind: str, from_stage: str) -> str:
    """Re-grade card: a token changed forensic stage since last cycle."""
    p = v.pool
    fg = v.forensic
    to_stage = fg.stage if fg is not None else "?"
    icon = "🎓⬆️" if kind == "upgrade" else "⚠️⬇️"
    head = [
        f"{icon} <b>RE-GRADE · {kind.upper()}</b> · <b>{p.base_symbol}</b>",
        f"{_STAGE_EMOJI.get(from_stage,'·')} {from_stage or '—'} → {_STAGE_EMOJI.get(to_stage,'·')} <b>{to_stage}</b>",
    ]
    stats = [f"💧 depth {_fmt_usd(fg.depth_usd)} · {fg.n_pools} material pools"] if fg else []
    if fg is not None:
        stats.append(f"🎯 grad {fg.graduation_score:.0f} · mom {v.score:.0f}")
        if fg.rug_flags:
            stats += [f"⛔ {r}" for r in fg.rug_flags[:2]]
        elif fg.grad_signals:
            stats += [f"✅ {s}" for s in fg.grad_signals[:2]]
    blocks = ["\n".join(head)]
    if stats:
        blocks.append("\n".join(stats))
    blocks.append(_links_line(p) + f"\n<code>{p.base_address}</code>")
    return "\n\n".join(blocks)


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

    def transition(self, v: Verdict, kind: str, from_stage: str) -> None:
        """Announce a forensic stage re-grade (upgrade/downgrade)."""
        to_stage = v.forensic.stage if v.forensic is not None else "?"
        arrow = "⬆️" if kind == "upgrade" else "⬇️"
        line = f"{arrow} RE-GRADE {v.pool.base_symbol}: {from_stage or '—'} → {to_stage}"
        if _HAS_RICH:
            _console.print(line, style="bold magenta")
        else:
            print(line)
        if self.tg:
            self._send_telegram(_telegram_transition_text(v, kind, from_stage))

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
