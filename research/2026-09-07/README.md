# MemeHunter 样本研究、双模型评审与回测原型

研究日期：2026-09-07。最终数据汇总时间：2026-09-07T01:59:14.954600+00:00。

**结论：优先修复新池假加速度、V4池身份与时点数据记录；支持回测应先从旧告警的价格路径和可执行性研究做起。当前结果不能证明策略盈利。** 本包没有修改正式Hunter或发布Telegram信号。

## 原工作位置与上下文

- 主程序：`/Users/witness/Desktop/meme-hunter`。评分在`memehunter/analyze.py`，采集与周期在`hunter.py`，风险检查在`forensics.py`，输出在`feed/signals.json`。
- 展示端：`/Users/witness/Desktop/paul-agent/web/src/components/signals`。
- Claude Code记忆：`/Users/witness/.claude/projects/-Users-witness-Desktop-paul-agent/memory/robinhood-chain-meme-hunter.md`及同目录`noxa-launchpad-forensics.md`。本轮结合这些上下文检查代码，历史说明与当前源码冲突时以复现实验和当前源码为准。
- 本研究包保存独立脚本和冻结源码，便于CC后续从本README、STRATEGY-SPEC及reviews/ADJUDICATION继续工作。

## 本轮实际完成

- 当前市场：抓取并整理 **60行网页观察样本**（新池20、股票配对20、热门池20）。已解析 **44个不同池标识**；14行因页面失败/动态链接变化未确定池身份。不是60个独立币，也不是同一时间/区块截面。
- 历史：从本地Git逐次提取 **427份feed、2405条去重告警、2441条观测、2399个池、2397个token**。时间范围7月10日至8月8日。保存原始JSON、提交时间、生成时间、首次可见时间与SHA-256。
- 模型：真实调用 **MiniMax M3、DeepSeek V4 Pro**，各一轮独立评审加一轮交叉复核，原文与调用元数据可审计。见 [评审裁决](reviews/ADJUDICATION.md)。模型文中的旧覆盖率、错误数字与公式不作为结论。
- 回测：已实现并测试下一bar执行、成本/延迟/规模敏感性、止盈止损双触发、缺失与未成交分类。**48个预先选定历史样本，已获得 48 份行情文件、2761根分钟bar**。这是OHLCV成交代理研究，缺历史真实深度、路线与已验证税费。

## 当前市场样本说明

| 分组 | 代表观察对象 | 改版应验证的内容 |
|---|---|---|
| 股票配对与平台资产 | AI/NVDA、PAIR/SPY、MOO/MU、DOGGIE/TSLA、SCHIFFY/GLD | 地址身份、报价资产风险、美元/报价币双收益、池类型 |
| 同主题退潮观察 | BABYAI/NVDA、CHROME/SLV、KPOP/EWY、RIDE/RIVN | 热主题不等于每个币都强；保留弱势样本，不能只挑龙头 |
| 活跃老币/再启动 | CASHCAT、PONS、CHUMP、EQUI | 老币及新开的辅助池不能被4小时总开关误删 |
| 新发射与低成交对照 | PATTON、PETAL、PDOG、DAYS、Nasduck | 真正新币、少量成交、冷启动和无效放量 |
| 同名/方向对照 | 多行ROBINCAT、VIDA、MEME/amc、USDG/WETH | 名称重复不等于同一token；股票本体/稳定币不作meme |

网页样本中的股票配对组20/20、热门组19/20超过4小时。后者包括非meme控制池，不应误读成“19个买入机会”。这些是规则覆盖诊断，不是新策略的收益评估。

来源：[GeckoTerminal热门池](https://www.geckoterminal.com/robinhood/pools)、[新池](https://www.geckoterminal.com/explore/new-crypto-pools/robinhood)、[股票配对分类](https://www.geckoterminal.com/category/stock-paired-tokens/robinhood)。逐行来源及解析状态在 [current_samples.json](current_samples.json)。部分页面的base/quote标签、价格对象并不一致，因此网页价格未送入回测。

## 旧算法已复现的问题

1. **假加速度**：出生10分钟、始终每分钟100美元成交的合成池，旧代码把V5/5与V60/60相比，输出6倍加速并拿满20分。无重叠有效窗口的恒速基准应为1倍。历史340条ALERT/HOT中，181条池龄<5分钟，143条带“12.0x加速”标签；这是偏差暴露证据，不等于证明143条全部虚假。
2. **V4假LP告警**：已识别为基础设施的manager持有990/1000供应、普通地址持有10，bytes32 PoolId不持币；旧代码仍判LP=0。该合成测试复现代码错误，不针对任何真实代币作rug定性。Uniswap官方说明：[PoolId和单例架构](https://developers.uniswap.org/docs/ecosystem/subgraphs/concepts/v4/queries)。
3. **发布稀疏**：本地保存的feed生成间隔中位数 **85.7分钟**，最长 **9.64小时**；只能证明所保存feed的节奏，不能断言每次云端任务是否执行。只有 **40个池** 有两条以上观测；旧feed没有存拒绝候选及完整V5数据。

复现实验：`python3 scripts/audit_legacy.py`。输出在 [legacy_audit.json](results/legacy_audit.json)，输入代码冻结在legacy_source，附Git版本与文件hash。

## 回测试验：先看能否评估，再看收益

历史共有338个token的首次高等级告警。公开API曾限流，本轮预选全部21个HOT，加按时间等间距抽取的27个ALERT，共48个；覆盖5个日历周、5类DEX标签。样本选择在读取其K线收益前完成，HOT被过采样，不能直接代表338个token或全链总体。

主情景：每个token首个高等级告警、原告警池；公开可见时点=max(提交、feed、原始观测)+60秒后下一分钟开盘；名义100美元；上一完整分钟成交额的1%作为容量门；每边2%假设费用；-20%/+40%退出或最长60分钟。当前bar成交额只用于事后成交代理检查，不用于信号选择。价格bar并不保证能真实卖出。

| 主情景状态 | 样本数 |
|---|---:|
| `entry_capacity_rejected` | 42 |
| `missing_pre_entry_bar` | 3 |
| `censored_exit_capacity` | 1 |
| `priced_proxy` | 1 |
| `unfilled_entry_capacity` | 1 |

**能完成价格代理回放：1/48（2.1%）。** 缺失和删失仍留在48的分母里，未把它们当归零，也未把少数可定价结果外推为整体胜率。容量拒绝表示该假设规则下不入场，不能推断实际市场绝对无法成交。

以下仅作条件样本诊断；不同情景能完成退出的样本可能不同，均值/中位数不能直接当策略优劣排序。未知税费和深度不允许报告真实交易收益。

| 情景 | 有入场与退出代理价 | 入场后删失 | 可定价子集净收益中位数 |
|---|---:|---:|---:|
| `fixed_hold-h60m-c50bps-l60s` | 0/48 | 2 | — |
| `stop20_target40-h60m-c50bps-l60s` | 1/48 | 1 | 38.6% |
| `fixed_hold-h60m-c200bps-l60s` | 0/48 | 2 | — |
| `stop20_target40-h60m-c200bps-l60s` | 1/48 | 1 | 34.5% |
| `fixed_hold-h60m-c500bps-l60s` | 0/48 | 2 | — |
| `stop20_target40-h60m-c500bps-l60s` | 1/48 | 1 | 26.3% |
| `stop20_target40-h60m-c200bps-l60s-size25-cap0.01` | 10/48 | 9 | 5.6% |
| `stop20_target40-h60m-c200bps-l60s-size25-cap0.05` | 23/48 | 10 | 34.5% |
| `stop20_target40-h60m-c200bps-l60s-size100-cap0.01` | 1/48 | 1 | 34.5% |
| `stop20_target40-h60m-c200bps-l60s-size100-cap0.05` | 13/48 | 9 | 34.5% |
| `stop20_target40-h60m-c200bps-l60s-size500-cap0.01` | 0/48 | 0 | — |
| `stop20_target40-h60m-c200bps-l60s-size500-cap0.05` | 1/48 | 1 | 34.5% |

其余情景包括15/60/240分钟固定持有与止盈止损、每边0.5%/2%/5%费用、0/60/120/300秒延迟、同bar乐观/保守顺序。没有在这些结果上选择“最赚钱阈值”。见 [完整汇总](results/final_summary.json) 和 [逐事件结果](results/pilot_event_results.jsonl)。

## 下一版的具体方向

- P0：按地址与池型建模，修正年龄偏差，分开币龄/池龄，保存未过滤候选与拒绝原因，未知风险不标安全。
- P1：先复核旧告警的价格路径、容量和退出；同时开始时点数据连续采集。新评分缺历史V5及拒绝样本，当前不能完整重跑。
- P2：增加股票配对轮动、Pons版本化生命周期、已告警币退出监控。协议毕业与市场成熟度用两个字段。
- P3：冻结阈值后做独立时间留出验证，再决定正式推送与刷新频率；负结果照样保留。

完整输入、假设、对照、采集与验收规则见 [STRATEGY-SPEC.md](STRATEGY-SPEC.md)。Pons协议差异参考[官方v1文档](https://docs.ponsfamily.com/)与[v2文档](https://docs.ponsfamily.com/v2)；本轮v2正文访问出现地区阻断，使用官方文档的检索可见内容，未对所有部署合约做链上认证。

## 如何复现

Python 3；回放和汇总仅用标准库。旧源码复现实验需requests，可用原项目requirements.txt安装。所有命令在本研究包目录运行。

```bash
python3 scripts/test_replay.py
python3 scripts/audit_legacy.py
python3 scripts/replay.py --selected-plan candles-selected-plan.json
python3 scripts/summarize.py
python3 scripts/make_report.py
```

已有原始JSON、K线与模型最终答复均在包中，以上步骤不需要API或模型付费。要追加行情：

```bash
python3 scripts/collect.py candles --sample 48 --limit 48 --execute --interval 13
python3 scripts/collect.py snapshots --execute --limit 9 --interval 13
```

采集器默认只生成计划，`--execute`才请求；保留错误与空K线，不自动补价格。CoinGecko替代入口需自行提供`COINGECKO_DEMO_API_KEY`，本包不含密钥。历史OHLCV的参数、跳过无成交bar的默认行为与计划权限需按[官方文档](https://docs.coingecko.com/demo/reference/pool-ohlcv-contract-address)核对；本次成功请求使用GeckoTerminal公开入口，不能以CoinGecko付费计划说明保证公开入口完整覆盖。

模型重评审会产生API费用：`python3 scripts/review_models.py`。它从原quant-research-agent的.env.local读取两家模型配置，仅发送相关代码、公开样本与评审材料；不把密钥写进请求留档。模型原文有错误，阅读时务必同时看裁决文件。
