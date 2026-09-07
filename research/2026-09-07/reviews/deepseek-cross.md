## 对其他独立评审的交叉审核

基本同意大部分缺陷判定，但有三处需修正或区分：

1. **min_age_min 不是纯 warning**。代码中软 warning 会把 ALERT/HOT 降级为 WATCH，因此它对输出层有实际影响。但它确实不会影响 momentum score 中的 acceleration 或 freshness 分值；不能据此说“安全门不参与”。
2. **“多池储备相加重复计量供应”只是假设，不是代码证明**。`graduation()` 简单对 `reserve_in_usd` 求和；同 token 的多池可能在资产/池级重复计算，但目前没有逐池份额数据可证明供应重复。应作为待验证项，不是已证实缺陷。
3. **V4 判定准确**。`rug_scan` 把 `pool.address` 当作余额地址调用 `balance_of`；Uniswap v4 PoolId 不是持币地址，会产生假 LP drain。fixture 已证实。

## Replay 实现审计

优点：bad bar 不跳过、duplicate/gap 失败关闭、pre-entry 容量检查、未知结果不计 PnL、Manski bounds、保守处理同 bar 触及止损/止盈。

需修正的技术问题：

- **cohort 按 token 而不是按 pool 去重**。同一 token 多池时，首个低流动性池会被当作执行池，后续更优池被忽略；应按 `(pool, token)` 或显式多池联合事件。
- **入场对齐依赖 rows start 为 interval 整数倍，但未验证**。若真实 start 非对齐，会全部 missing entry。应强制 `start % interval == 0`，否则数据质量失败。
- **入场容量只用 pre-entry bar**，没有检查 entry bar 自身成交量/成交额。这既可能高估可成交，也可能在 exit 时用上一 bar 容量误拒绝当前 bar 足够流动性。应分别用所在 bar 的成交额/量检查 fill。
- **gas_usd 语义不明确**。若每笔 gas 为固定值，现逻辑可能只减少 buy amount、又在卖出 proceeds 扣除一次；默认 0 没问题，但成本敏感性回测需显式区分 entry/exit gas 与 per-side cost。
- **intrabar ambiguous 已记录但聚合未披露**。必须报告 ambiguous 比例并按此分层，否则 TP/SL 结果不可复现。
- **未报告 censored 原因分布**。`status_counts` 有，但 summary 未展开；至少要有 `censored_*` 的分类占比。
- **gap 处理基本正确**：时间退出用 open，跳空触及止损先于止盈；这些可保留。

## 我修订后的优先级

1. **先修 V4 holder/LP 逻辑**：为 v4 PoolId 建立专门的 manager 状态，否则 `lp_pct`、顶尖持有人、LP drain 全部不可用；fixture 通过才可继续。
2. **修加速公式为 disjoint 窗口**：现有重叠窗会使常数成交量（500/5m,1000/1h）产生 6x 加速假象。对 age≥5min 用 \(V5/5)/((V60-V5)/(min(age,60)-5)\)，且要求 V60>0、覆盖率≥95% 才计分；不能修复前不报告。
3. **回测最小可实现范围**：先按 `(pool, token)` 去重，用 bar 对齐检查、entry/exit fill 检查、gas 语义、模糊比例披露重跑；只要存在 missing candles，一律输出“可评估事件数”而非 PnL。
4. **样本层**：全市场 new_pools 全量保存原始响应+时间戳+拒绝原因，不能只存 filtered board；失败池（zero sells、honeypot、rug、撤池）必须纳入分母。
5. **策略假设收敛为两个可证伪方向**：等长窗加速延续；链上真实 depth/可退出性。蜂蜜高买压先不做，因为当前无连续 K 线且税费无法验证。

## 与另一评审的主要 disagreement

- 对方认为 min_age_min 完全无效，我修正为“对输出层有影响、对 score 无影响”。
- 对方把“储备重复计量”当作已证缺陷，我降级为待验证假设。
- 对方没有指出 replay cohort 按 token 去重、arbar 对齐、entry/exit fill 容量这些实现缺陷；这些对回测是否可复现影响更大。

## 当前可合法运行 vs 需要新采集

**现在可合法运行**：数据质量审计、V4 fixture 回归、加速/score 敏感性、candidate/reject 漏斗、缺失率和 alert 延迟报告；不得声称收益、胜率或 alpha。

**必须新增**：连续 1m OHLCV（含成交量）、逐笔/池级深度、税费验证、撤池日志、全量 rejected 池、同步时间戳和 API 版本。

**首版验收门槛**：v4 fixture 100% 通过身份/LP 测试；所有 replay 行可复现且未跳过坏 bar；缺失/删失分成和 ambiguous 比例披露；任一收益结论在删失下界仍与留出期方向一致，否则只发布“无可验证回测结果”，并明确 fixture 不是市场回测。