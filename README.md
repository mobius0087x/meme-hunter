# Robinhood Chain Meme Hunter 🔥

A general early-meme discovery **agent** for [Robinhood Chain](https://docs.robinhood.com/chain/) (Chain ID 4663). It watches every new pool on the chain, strips out rugs / wash / dumps, ranks the rest by live momentum, and pushes you a tiered, one-tap-to-trade shortlist — so you spend your attention on the 2–3 things worth it, not the firehose.

Built for a **2-week short-play**: biased toward *early* entries with enough liquidity to actually exit. Alert-first by design — it tells you where to look, **you** pull the trigger.

> ⚠️ **This is a hunting radar, not financial advice and not a contract auditor.** Every "signal" is a heuristic over on-chain activity. Meme coins go to zero as a base case. Size accordingly, verify before buying, use a burner wallet. Note that Robinhood *Stock Tokens* exclude US persons — meme tokens are permissionless, but know your own jurisdiction.

---

## Quickstart

```bash
cd meme-hunter
python3 -m pip install -r requirements.txt

# one-shot look at what's hot right now (no alerts, no state)
python3 -m memehunter scan

# continuous hunting loop (this is the agent)
python3 -m memehunter run
```

Zero config required — it runs against public GeckoTerminal + Dexscreener APIs out of the box. `rich` gives you a colored dashboard; without it, plain text.

Run it in the background for the 2 weeks:

```bash
nohup python3 -m memehunter run > hunter.log 2>&1 &
tail -f hunter.log
```

---

## How it works

```
GeckoTerminal /networks/robinhood/new_pools + /trending_pools   (the firehose)
        │
        ▼
  dedup by pool address · drop pools older than MH_MAX_AGE_MIN (early-hunt window)
        │
        ▼
  SAFETY GATE  →  hard-reject: low liquidity · <N buyers · honeypot-proxy
                  (buys≫0/sells=0) · thin-float (FDV≫liq) · GoPlus honeypot/tax
        │        soft-warn (cap tier at WATCH): brand-new · non-bluechip quote ·
        │        already-mooned · dumping · wash-risk
        ▼
  MOMENTUM SCORE (0–100): turnover · buy-pressure · unique-buyers ·
                          acceleration(5m vs 1h) · price-trend · narrative · freshness
        │
        ▼
  TIER: 👀 WATCH (≥42) · 🚨 ALERT (≥60) · 🔥 HOT (≥78)
        │
        ▼
  NOTIFY: console dashboard + Telegram · dedup + cooldown (no spam)
          each alert carries Dexscreener / GeckoTerminal / Uniswap links + token address
```

Data sources are **verified live** (2026-07-09): `robinhood` is the GeckoTerminal network id and Dexscreener chain slug; the RPC is `https://rpc.mainnet.chain.robinhood.com`.

### Why these signals
- **Turnover (vol/liquidity)** — real churn, not a dead pool.
- **Buy pressure + unique buyers** — a crowd entering, not one wallet wash-trading.
- **Acceleration (5m vs 1h)** — is it heating up *right now*, or already cooling?
- **Price trend** — rewards an early uptrend; **penalizes both already-mooned (+300%/1h = you're late) and active dumps (−40%/1h = you're exit liquidity).**
- **Narrative fit** — CASHCAT-style mascot/ticker-culture names run hardest in this meta.
- **Freshness** — sweet spot 5–90 min old.

---

## The 2-week playbook

1. **Run the loop**, let WATCH/ALERT/HOT scroll. Get a feel for the chain's baseline (what a "normal" new pool looks like) before you trade anything — first few hours are calibration.
2. **Only HOT (🔥) deserves a fast look.** ALERT (🚨) = keep half an eye. WATCH (👀) = context.
3. On a HOT hit, in ~30 seconds: open the Dexscreener link → check the holder distribution, the LP (burned/locked?), the buy/sell tax, and whether sells are actually going through. The agent's gate catches the obvious traps; **you** catch the rest.
4. **Entry thesis is momentum, not marriage.** Short-play = take profit in tranches on the way up, don't round-trip it. Set a mental stop before you buy.
5. **Retune live** via env vars (below) — e.g. tighten `MH_MIN_LIQ` if you're seeing too much dust, raise `MH_TIER_HOT` if HOT is too noisy.

---

## Telegram (optional, recommended for reacting fast)

```bash
# 1. create a bot with @BotFather → get the token
# 2. get your chat id from @userinfobot
cp .env.example .env      # then fill MH_TG_TOKEN + MH_TG_CHAT_ID
python3 -m memehunter test-tg     # should say "sent" and ping your phone
python3 -m memehunter run         # alerts now also hit Telegram
```

---

## Tuning (all optional, env vars)

| Var | Default | Meaning |
|---|---|---|
| `MH_POLL_SECONDS` | 30 | poll cadence |
| `MH_MIN_LIQ` | 4000 | reject pools with less pooled liquidity ($) |
| `MH_MIN_BUYERS` | 3 | reject pools with fewer unique 1h buyers |
| `MH_MAX_AGE_MIN` | 240 | ignore pools older than this — we hunt early |
| `MH_LATE_PUMP` | 500 | 1h % gain above which entry is flagged "late" |
| `MH_TIER_WATCH` / `_ALERT` / `_HOT` | 42 / 60 / 78 | score cutoffs |
| `MH_COOLDOWN_MIN` | 30 | re-alert cooldown for a still-hot token |
| `MH_GOPLUS` | 1 | try GoPlus token-security enrichment (auto-skips if 4663 unsupported) |

---

## Roadmap (where "drive" goes next)

- **Phase 2 — semi-auto execution.** One-tap buy from an alert: sign & send a Uniswap-V3 swap on Robinhood Chain via the RPC with a preset size + slippage + auto-stop. (Needs a burner wallet key; gated behind explicit confirm.)
- **Launchpad pre-graduation sniping.** Watch RobinFun / hood.fun (~$44k grad → Uniswap, LP burned) and NOXA (direct V3, LP locked) bonding curves *before* they hit the DEX firehose.
- **Whale-wallet tracking.** Reuse the Mobius `whale` agent: tag wallets that were early on winners, alert when they ape a fresh pool.
- **Exit signals.** Same engine, inverted: alert when a position you flagged starts distributing (the dump-penalty logic already detects it).

---

## Files
- `memehunter/config.py` — all thresholds (env-overridable)
- `memehunter/sources.py` — GeckoTerminal + Dexscreener + GoPlus clients, `Pool` model
- `memehunter/analyze.py` — safety gate + momentum scoring (the brain)
- `memehunter/notify.py` — console + Telegram sinks
- `memehunter/hunter.py` — the loop, dedup/cooldown state
- `memehunter/__main__.py` — `run` / `scan` / `test-tg`
