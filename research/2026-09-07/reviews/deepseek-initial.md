未把父级建议当正确；以下只基于所给代码与语料，不引外部事实。

## 一、Top 5 实际缺陷（代码证明情况）

1. **v4 holder/LP 逻辑错误**  
   `sources.py` 把 `pool.address` 当 token 持有地址，`forensics.rug_scan` 仅排除该地址并查 `bal.get(pool_l)`。代码无 Uniswap v4 `PoolManager` 单例分支。**代码已证明无 v4 处理**；实际后果取决于 GeckoTerminal 返回的是地址还是 PoolId，需链上验证（缺失证据）。

2. **min age 对滚动成交量加速的影响未修正**  
   `analyze.py` 中 `rate5=vol_m5/5`、`rate1h=vol_h1/60`，对 10 分钟新池，h1 分母包含出生前零额，accel 被机械放大；`min_age_min` 只做软警告不进入加速度分母。**代码证明**。

3. **base-vs-quote 方向错误地加总 reserve**  
   `forensics.graduation()` 对 token 所有池 `sum(reserve_in_usd)`，不区分 token 是 base 还是 quote、不取 token 侧份额；`used_as_quote` 方向判断正确，但 `depth_usd` 是池总储备，导致双计/错量。**代码证明**。

4. **集中度推断只排除一个池地址**  
   `rug_scan()` 排除当前 `pool_l`，但多池 LP、锁定/金库、v4 PoolManager 等未排除，可能把 LP 误判为单一巨鲸。`rpc.is_infra` 未展示，覆盖不明。**结构性缺陷成立，误报程度待链上验证**。

5. **pool-vs-token age 混淆，且 age 非 point-in-time**  
   `rug_scan` 用 `pool.age_min` 定扫描窗口；`Pool.age_min` 使用 `datetime.now()` 而非观测时间。对老 token 开新池，窗口可能漏早期分配；历史语料回测无法还原当时年龄。**代码证明**。

## 二、更广样本设计

- 存全量：每个观测含观测时间戳、池地址、dex、base/quote 地址与符号、reserve、volume、txns、价格变化、created_at、feed 生成时间、Telegram 投递延迟。
- 失败样本：定期重观测，记录 delist/zero liquidity/rug；不得用“后来缺席=零价”。
- 非 meme 对照：USDG/WETH、AMC/MEME 定向对照、已建立蓝筹。
- 同 ticker 冒名：只按合约地址聚合，ticker/名称仅辅助。
- 池类型/市场机制：Uniswap v2/v3/v4、pons v1/v2 等分层；记录 quote 是否为蓝筹、自定义 quote；跨不同波动/拥堵周期。
- 防幸存者：必须保存 rejected universe；对每个池至少多次观测，否则历史语料无因果推断力。

## 三、3 条可检验策略假设

1. **年龄修正加速度**  
   输入：`age_min∈[5,90]`、`h1 buys≥3`、`quote∈GOOD_QUOTE_SYMBOLS`、`h1 价格变化∈[-10%,+100%]`；信号为修正分母：`(vol_m5 / max(5,age_min)) / (vol_h1 / max(60,age_min)) > 1.5`。  
   基线：同日同池龄、同流动性档未触发信号池。  
   持有/退出：下一 1 分钟 bar 开盘+30s 延迟入场；24h 或 -20% 止损/+50% 止盈，先到先平。成本：买卖税各 1%、滑点 0.5%。  
   证伪：经过按 token 地址 purged split，IC 不显著或最大回撤>20%。

2. **多池早期深度**  
   输入：token 首个蓝筹 quote 池后 24h 内出现≥2 个 material pools（≥$10k）。  
   基线：同 age 单池 token。  
   持有：出现第二池时下一 bar 入场，48h 后退出。成本同上。  
   证伪：72h 后流动性留存/交易量不高于基线；或成功率低于随机匹配。

3. **安全门槛回避检验**  
   输入：`safety_gate` 硬拒（honeypot proxy、FDV/liq>60、非蓝筹 quote）。  
   策略：拒绝池不可买（空仓），可操作池等权买。  
   基线：不做过滤等权买全部 filtered board。  
   持有：24h。  
   证伪：若拒绝池组 72h 后零流动性比例不显著高于可操作组，或策略组合收益不低于基线，则安全门槛无增量。

## 四、最低可复现回测规格

- 时间索引：发布时刻=max(commit,feed,observation)+验证过的 TG 延迟；下一根 1 分钟 bar 开盘执行。
- 缺失/坏蜡烛：缺 bar 不补零；流动性消失或 30 分钟无成交则标记未完成退出，不得计入盈利。
- 税/费：买卖税从合约读取，默认 1%+0.5% 滑点；敏感性 0/0.5/1/2%。
- 止盈止损同 bar：若 bar 内同时触达，按先止损计（保守）；或用最高/最低价模拟最差成交。
- 流动性移除/未成交：若下一观测不存或流动性 <$4k，退出价取事后可验证死亡/归零，否则审查。
- 防泄漏：按 base 合约地址 purged split；滚动窗口不含未来；禁止同 token 跨组泄漏。
- 不确定性：bootstrap 重采样入场/滑点/税，报告 5/95 分位、最大回撤、零流动性率。

## 五、现在能跑 vs 需新收集；首发验收

**现在（稀疏语料）**：只能做事件研究：从 alert 观测到下一条观测的价格/流动性变化，但仅 40 池有 2+ 观测，无法回测收益/生存；可审计语料是否含点时间戳、可跑代码单测验证上述缺陷。  
**需要新收集**：逐池定时观测、观测时间戳、rejected universe、1m OHLCV、TG 延迟、v4 合约状态、token 创建块、链上持有者列表。  
**首发验收**：历史样本包含 rejected 全集及观测时间戳；≥90% 信号有下一 bar 可执行价；无未来函数、按地址 purged split；提供生存分析而非仅收益率；单元测试覆盖 v4 地址解析、年龄归一化、side-specific 深度、pool-vs-token age。