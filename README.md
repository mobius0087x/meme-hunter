# Robinhood Chain Meme Hunter

**Windows / CC / Codex 接手先读：[MEMO.md](MEMO.md)**，再按 [WINDOWS.md](WINDOWS.md) 安装与验收。

Robinhood Chain 的只读池监控、注意力评分和可复核样本采集。输出本地日志、可选Telegram和Web feed；不签名、不下单。WATCH/ALERT/HOT是关注等级，行情成交量和TVL都不是可执行报价。

## 当前运行与Windows迁移

2026-09-07确认现有监控在GitHub Actions运行，本地Mac没有常驻猎手。仓库变量`MH_RUNNER`为空或`cloud`时继续云端运行；Windows接管脚本设置为`windows`后云端跳过。完整安装、接管验收、更新和恢复步骤见 **[WINDOWS.md](WINDOWS.md)**。

```powershell
# Windows先预检，配置好.env和gh认证后接管
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -TakeOver
```

默认是当前用户登录任务，锁屏可运行；睡眠/注销会中断。尚未在你的目标Windows上安装。

## 2026-09-07规则更新

- 新池加速度改成最后5分钟与此前不重叠窗口的单位时间成交额比较，按池龄校正；不足15分钟、缺字段或此前无成交时为unknown，不奖励机械高倍数。
- 4小时仅限制新池发现；热门池和已告警跟踪池可继续参与。池龄按抓取时刻冻结，token年龄未知时不伪造。掉榜池按轮转每轮最多补查3个，跟踪窗口7天。
- V4 PoolId不再当作钱包执行持仓检查；不支持的风险检查明确标记并封顶WATCH。即使V2/V3也不再凭低pool/supply比例认定撤池。
- 用最近5分钟平均每分钟成交额 × 1% 与100美元假设规模比较，容量不足封顶WATCH；这是筛选代理，不能证明能买卖，也不等同历史回放的一分钟前量门槛。
- 非常规报价资产继续带警示并封顶WATCH；保留报价地址，不把NVDA/SPY等名称当地址认证。股票配对可以被发现，专门的轮动收益模型尚待时点样本验证。
- 原有GRADUATED/GRADUATING字段为市场成熟度启发式，保留前端兼容；不代表Pons等协议真实毕业。聚合池TVL不称为真实退出深度。
- 原始API响应、失败记录、全部已采集候选（含被拒绝/超龄）逐轮存到`.runtime/archive/`。只有本次抓取页面的覆盖，尚非全链全集。

## 开发与验证

Python 3.10+：

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m memehunter.service --check  # 只读市场预检，不发通知或写状态
python -m memehunter scan            # 只读评分预览
```

已有CLI保留：`run`为普通循环，`cloud`为一轮状态/通知/feed任务；启用Telegram时它们会发送真实告警。Windows请用接管脚本管理的`python -m memehunter.service`，不要再同时运行普通循环。`test-tg`只在你主动需要测试发送时使用。

## 主要配置

复制`.env.example`为`.env`。密钥不入Git；Windows须自行安全转移，GitHub Secrets不会自动同步。

| 配置 | 默认 | 说明 |
|---|---:|---|
| MH_POLL_SECONDS | 60 | 目标周期；实际受接口/扫描耗时影响 |
| MH_MIN_LIQ | 4000 | 最低池TVL代理 |
| MH_MAX_AGE_MIN | 240 | 仅新池来源的年龄上限 |
| MH_NOTIONAL_USD | 100 | 容量筛选假设金额 |
| MH_PARTICIPATION_CAP | 0.01 | 成交额参与率代理 |
| MH_FORENSIC_MAX | 3 | 每轮最多深查候选，RPC另有总预算 |
| MH_TIER_WATCH / MH_TIER_ALERT / MH_TIER_HOT | 42 / 60 / 78 | 关注档位，警示可封顶 |
| MH_TG_TOKEN / MH_TG_CHAT_ID | 空 | 可选Telegram |

## 研究和回测

[2026-09-07研究报告](research/2026-09-07/README.md)包含MiniMax M3与DeepSeek V4 Pro的独立/交叉评审、原始样本和离线回放脚本。该历史研究冻结了当时本地Git可见的7月10日至8月8日样本；本次同步远端后发现后续云端feed仍在更新，研究包不是截至9月7日的完整告警全集。新规则版本不会冒充旧回测已经验证。

```bash
cd research/2026-09-07
python scripts/test_replay.py
python scripts/replay.py --selected-plan candles-selected-plan.json
python scripts/summarize.py
```

历史试验48个样本只有1个在主容量/退出情景下完成价格代理回放，不支持盈利结论。新规则需用后续连续记录再评估。
