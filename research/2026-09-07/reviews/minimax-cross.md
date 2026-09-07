# 独立交叉复核与修订（2026-09-07）

## 0. 对父级审阅与 DeepSeek 的分歧

| 项 | 父级/DeepSeek 立场 | 代码/语料实际 | 判定 |
|---|---|---|---|
| 加速度公式 | DeepSeek 用 `max(5,age)/max(60,age)` "修正" | 该乘子恒=1（5–60 区间），不能压缩零基线；fixture 中 100 USD/min 常量池仍得 6× / 20 分 | 父级 fixture 与 DeepSeek 公式均未消除机械放大；正确做法是**去除重叠 5 分钟的 disjoint 公式**，并要求覆盖度 |
| v4 PoolId | 父级标记缺陷 | `sources.py` 把 GT `id` 当合约地址；`forensics.rug_scan` 用 `pool_addr.lower()` 排除；fixture `v4_poolid_as_wallet` 中 manager 余额 990/1000 被误报 LP=0%（PoolId 本就不是 token） | 缺陷成立，且**严重程度高于父级描述**：rug_scan 在 v4 上既错算供应，又会把 PoolManager 当"单钱包"扣分 |
| 非蓝筹 quote | DeepSeek 当硬拒 | `safety_gate` 仅 `warning` + WATCH 上限（`analyze.py`）；narrative 不扣分 | DeepSeek 与代码不一致，**代码当前更宽松**，不构成"硬拒" |
| 338 全 missing | 父级陈述事实 | `replay_summary.json` 全部 `missing_candles`，无 priced 样本；`aggregate()` 仍输出 [0,1] 胜率界 | 父级正确；该界**无信息量**，不应用作策略声明 |

## 1. Top 5 缺陷（更新版，按代码可证性排序）

1. **v4 PoolId 被当 token/池地址处理**【代码可证】  
   `sources._addr_from_gt_id` 直接切 `0x…`，未做 v4 判定；`Pool.address` 在 v4 是 bytes32 PoolId。`forensics.rug_scan` 据此排除、查 `balance`，结果恒为零或恒非零且无意义；`rug_scan` 还用 `pool_l` 当 LP 持仓地址，v4 下完全错误。**修复**：v4 时从 `pool.attributes` 解析 `PoolManager` + token0/token1，按池份额折算；否则禁止调用 rug_scan 并把代币池的 graduation 也按 quote 侧份额计入。
2. **年龄归一化未进入加速度分母**【代码可证】  
   `analyze.momentum_score` 步骤 4 用 `rate5 = vol_m5/5`、`rate1h = vol_h1/60`。对 age<60 的池，h1 大段为零，accel 必虚高；`min_age_min` 是软警告。`legacy_audit.json` 显示 WATCH 中 1603/2065 age<5、1464 声称 "12× accel"，与 fixture 100 USD/min 常量池同样得到 6× 一致——**这是同一类系统误差**。DeepSeek 的 `max(5,age)/max(60,age)` 在 5–60 区间恒为 1，不修复。
3. **base-vs-quote 储备求和不区分方向**【代码可证】  
   `forensics.graduation` 对 `token_pools_raw` 全量 `sum(reserve_in_usd)`；`used_as_quote` 只标志、不参与求和调整。同 ticker 多池会出现 tokenA 既作 base 又作 quote 时重复计入；多池 quote 资产被低估"作为基底"的深度。**修复**：每个池按 `quote_addr == token ? quote_reserve : base_reserve * price` 取 token 侧份额后再求和。
4. **集中度推断仅排除当前池地址，且 age 取实时**【代码可证+结构性】  
   `rug_scan` 排除列表仅 `ZERO/DEAD/pool_l + is_infra`，多池 LP、跨池路由、金库合约未识别；`Pool.age_min` 由 `datetime.now()` 计算，回测/历史观测无法复用，且多池 token 用首池 age 估算窗口会漏早期分配。**修复**：扫描窗口按 **token 创建块**确定；维护多池 LP 集与 router 名单。
5. **`min_buyers_h1` 极低门槛 + 1h change 退化为整数百分比**【代码可证】  
   `min_buyers_h1=3`、`honeypot_min_buys=8` 配 12 分钟宽限期，1h 0 卖但未达 8 单时不拒；`pc ≥ 300` 硬返 -8，但 `pc ∈ [0,300)` 的最高档 `min(10, pc/20)` 在 pc=200 时也只 10 分，不能区分"刚启动"和"已 pump 数倍"。**修复**：h1 价格分段加宽 + 与流动性档联表；honeypot 宽限缩到 6 分钟、单买拉盘判据（buyer=1、vol>liq×2）。

## 2. 扩展样本设计

- **强制字段**：观测 UTC、原始 GT 响应 hash、base/quote **合约地址**、created_at、source_url、fetched_at；区分 `pool_age` 与 `token_age`。
- **失败/缺失显式化**：定时重观测；`status ∈ {ok, missing_bar, liquidity_removed, zero_volume_window, contract_unverified, dex_delisted}`，禁止隐式归零。
- **同 ticker 冒名**：仅按 `base_address`（小写、checksum 校验）聚合；ticker 进 bag-of-words 辅证。
- **池类型分层**：v2 / v3 / v4 / pons v1 / pons v2 / bankr / virtuals / dyorswap；quote 是否在 `GOOD_QUOTE_SYMBOLS`。
- **市场 regime**：把回测窗口按 gas 中位、链上拥堵指数、蓝筹 quote 流动性分桶；至少覆盖一次热潮与一次冷却期。
- **幸存者偏差**：保存 **rejected 全集**（含安全门被拒原因），并对每个 token 至少做 5 次以上重观测；当前 2441 obs / 2397 池、40 池有 2+ obs，**不足以做任何收益/生存推断**。

## 3. 3 条可证伪假设（修订版）

**H1：年龄归一化的早期加速度**  
输入：`age_min ∈ [5,90]`、`h1_buyers ≥ 3`、蓝筹 quote、`h1_price_change ∈ [-10%, +100%]`；信号 `S = (vol_m5 / min(age,5)) / (vol_h1 / min(age,60)) > 1.5`，且 `vol_m5/max(liq,1) ≥ 0.2`。  
基线：同日同流动性档、同 quote 类型未触发池。  
执行：信号 `available_ts + 60s` 对齐下一根 1m bar 开盘；24h 持有；TP +40%、SL -20%（保守）。  
成本：买/卖税取 `analyze._pct(GoPlus)`，默认 1% + 0.5% 滑点；敏感性 0/0.5/1/2%。  
**证伪**：purged split 后 bootstrap IC 不显著、或零流动性退出率 ≥ 50%。

**H2：多池早期深度信号**  
输入：token 首蓝筹 quote 池后 24h 内出现 ≥2 个 material pool（token 侧份额 ≥ $10k）；信号 = 第二池出现时刻。  
基线：同 age 单池 token。  
执行：第二池 next bar 入；48h 退出。  
成本同 H1。  
**证伪**：72h 后归一化深度 + 24h 成交量不高于基线；或 LR 检验 p>0.05。

**H3：安全门边际价值**  
输入：`safety_gate` 拒因分组（honeypot proxy / FDV/liq>60 / 非蓝筹 quote）。  
策略：A=拒因组空仓，B=可操作组等权买入；对照 C=等权买 filtered board 全集。  
执行：24h 持有，成本同 H1。  
**证伪**：B−C 的 bootstrap 均值/中位 < 0，或被拒组 72h 零流动性比例与可操作组无显著差（Fisher 精确 p>0.05）——则安全门无增量。

## 4. 最低可复现回测规格（贴合 `replay.py`）

- **时间索引**：信号时间戳 = `max(commit, feed_generation, observation_ts) + measured_tg_latency`；`replay()` 的 `available_ts` 必须独立字段，未测得 TG 延迟时记 `unknown_latency` 并以 `[60, 120, 300]s` 三档敏感性测试。
- **下一 bar 执行**：当前实现 `math.ceil(earliest/interval)*interval` 正确，但要求 **必须有 `entry_ts - interval` 的 pre-entry bar**（容量门），且 `entry` bar volume>0——已正确实现。
- **缺失/坏 bar**：当前 fail-closed 链 `missing_candles / invalid_* / censored_* / unfilled_entry_no_trades` 合格；但应把 `suspect_wick_requires_review` 单独保留为独立计数，不能与正常 priced 合并统计。
- **同 bar 触 TP+SL**：当前 `ambiguous=True` 是对的；保守结果仍按 `exit_px=stop_px` 计入，但需在 summary 单独报告 `ambiguous_rate`，并对其跑敏感性（按 TP 计算上界）。
- **税/费**：默认 `cost_bps_per_side`；**buy_tax/sell_tax 必须从链上读取**，缺失时按 1% 默认并在结果中标注。
- **流动性移除/未成交**：`censored_*` 必须与 `priced_proxy` 严格分离，禁止在 `conditional_mean_return` 中合并；`unconditional_mean_return` 当前为 null 是正确的，不能用 `[wins/n, (wins+n-k)/n]` 的界替代真实 PnL。
- **分组泄漏**：以 `token`（合约地址）为单位 purged；同一 token 多池在同一 split 折内不可同时入训练/验证；`cohort()` 当前用 `seen.add(token.lower())` 取首条 HOT/ALERT 已基本防重，但需增 `seen_pool_per_fold` 防止同一 token 不同池跨折。
- **不确定性**：每折 1000 次 bootstrap 入场延迟±60s、税/滑点 ±50%，报告 5/95 分位、最大回撤、零流动性率、状态计数直方图。

## 5. 现在可跑 vs 需新收集；首发验收

**现在（稀疏语料）可跑**  
- 单元测试覆盖：v4 PoolId 解析与 rug_scan 跳过、年龄归一化分母、`sum_reserve` 区分 base/quote、`min_buyers_h1` 单买拉盘、状态码穷举、identiy_mismatch、unsupported_interval、`suspect_wick` 不被静默吞掉。
- 离线审计 fixture：`legacy_audit.json` 重放——constant_volume_10m_pool 在修正公式下应 ≤ 2 分；`v4_poolid_as_wallet` 必须返回 `skipped_v4_no_inference` 且不进入 priced 集。
- 事件研究：仅 `current_summary.json` 范围——观测间价格/流动性变化、非 meme 对照（USDG/WETH、AI/NVDA、PAIR/SPY）随时间的相对走势。**不得报告 PnL 或胜率**。

**需新收集**  
- 每个池 ≥ 24h 的 1m OHLCV（USD 计价、附 source_url 与 fetched_at）。
- 每信号 `available_ts` 与实测 Telegram 投递延迟。
- **rejected universe** 完整落盘 + 拒因分布。
- v4 池的 PoolManager/token0/token1 解析、token 创建块、所有 material pool 的 LP 持仓地址集。
- GoPlus 缺失时的税默认策略与覆盖率。

**首发验收（硬指标）**  
1. 历史样本含 `rejected` 全集 + 观测时间戳；ALERT/HOT 信号 ≥ 90% 有 next-bar 可执行价（否则不予验收）。  
2. 无未来函数：purged chronological split，按 token 地址 5 折；任何 leak 触发 fail。  
3. **不报告**胜率/PnL 当存在以下任一：`coverage < 0.9` 或 `censored_*` 占比 > 20% 或 v4 池未分离。  
4. 单元测试集必须包含 v4、年龄归一化、side-specific 深度、pool-vs-token age、identity_mismatch、suspect_wick 六类强制用例。  
5. 输出除收益外必须含：状态计数、零流动性退出率、ambiguous 率、bootstrap 5/95 分位、最大回撤。

**结论**：`replay.py` 的 fail-closed 与统计降级逻辑工程上合格，但当前 corpus 下零 priced 样本，无任何策略声明依据；v4 解析与年龄归一化为必须前置修复，不可放到"二期"。