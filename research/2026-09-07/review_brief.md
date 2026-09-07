# Independent MemeHunter redesign and backtest review — 2026-09-07

User request: broaden research beyond a few currently popular tokens; obtain samples; have MiniMax and DeepSeek participate; preferably support backtesting. Existing tool is read-only discovery + Telegram alerting, not automated trading. Propose a concrete redesign, but distinguish what we can evaluate now from future data needs. Do not assume the parent's previous recommendation is correct.

Current public-page observations (asynchronously refreshed website snapshots, not synchronized API data or a trade recommendation):
- GT Robinhood board has CHUMP, MEME, SIRIUS, PONS, UPS, ROBIN, AI, Pushin P, EQUI, PAIR, USDG/WETH (non-meme control), AOBS, CASHCAT, QSTRAT, AMC/MEME (orientation control), PROLOGUE, MOO/MU. Pool ages range from 3 hours to 2 months; NEKO/NVDA is another Pons v2 sample. Some names recur across pools; contract identity must dominate ticker.
- AI/NVDA example: age 1 month, ~$5.2M daily pool volume, ~$20.9M reported reserves. PAIR/SPY age 8d ~$7.1M/$2.6M. MEME/USDG age 1d ~$52.7M/$1.9M. PONS/USDG age 1mo ~$31.8M/$8.7M. These do NOT establish returns, organic demand or executable depth.
- Sources: https://www.geckoterminal.com/robinhood/pools and per-pool links therein. Exact page timestamp is unknown; observed date 2026-09-07. Never present webpage snapshots as a same-block cross-section.
- Pons v1 official docs https://docs.ponsfamily.com/: own WETH pool exists from launch; graduation is a threshold, no pool migration. Pons v2 https://docs.ponsfamily.com/v2: curve before graduation, v4 pool after; custom quote assets; launch stack versions differ; query factory to resolve each launch. Current page access is region-blocked, search index provided documentation text; contract state has not been independently verified in this session.
- Uniswap official docs https://developers.uniswap.org/docs/ecosystem/subgraphs/concepts/v4/queries: v4 pools use bytes32 PoolId, assets held in singleton PoolManager; a pool ID is not a token-holding address.

New local historical corpus is summarized below. It contains only already filtered board + repeated alert history, not rejected candidates. There are almost no repeated observations per pool. This is a severe backtest limitation. Historical OHLCV access is currently being tested; unavailable candles must not become zero prices or disappear from denominators. Prior cc memory claimed poor mark-to-now results for 124 high-tier signals, but that is unverified historical prose, not a rerun.

Please independently return:
1. Top 5 actual defects and whether code proves them; explicitly test v4 holder/LP logic, min age effects on rolling-volume acceleration, base-vs-quote orientation, concentration inference and pool-vs-token age.
2. Broader sample design including failures, non-meme controls, same-ticker impostors, pool types and market regimes. Identify survivorship/selection and missing-history traps.
3. Up to 3 testable strategy hypotheses with exact point-in-time inputs, baseline, holding/exit logic, costs, and what data would falsify each. No fitting today's winners.
4. Minimum reproducible backtest specification: next-bar execution after observed publication + latency, missing/invalid candle handling, buy/sell taxes, fee/slippage sensitivity, intrabar TP/SL ambiguity, liquidity removal/unfilled exits, token-group leakage, purged chronological split, uncertainty metrics.
5. What can legitimately run on the available sparse historical corpus today vs what requires new collection; concrete first release acceptance criteria.
