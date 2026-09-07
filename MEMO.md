# MemeHunter 交接 memo — Windows 接手入口

更新日期：2026-09-07。本文记录用户已确认的方向、已完成工作及接手验收；具体安装命令以 [WINDOWS.md](WINDOWS.md) 为准。Windows agent 请先读本文，再操作。本文随Git同步，不依赖Mac上的CC聊天记录。

## 用户目标和当前状态

用户要求扩大Robinhood Chain meme样本、让MiniMax与DeepSeek参与、支持回测；随后要求更新监控规则、推到Git，让Windows负责常驻监控。规则、研究包与接管工具均已提交并推送。

**截至本次交接，运行归属仍是GitHub Actions，目标Windows尚未安装或接管。** 仓库变量`MH_RUNNER`尚未设置，云端job条件`vars.MH_RUNNER != 'windows'`成立。接手前重新核验变量与任务，不把本文的时点记录当实时状态。

- 主仓库：<https://github.com/mobius0087x/meme-hunter>，分支`main`。Mac原位置`~/Desktop/meme-hunter`；Windows可放任意目录，按自己的实际路径运行。
- 展示端是另一个仓库`paul-agent/web/src/components/signals`，经`/api/mh`读取本仓库`main/feed/signals.json`。本轮无需迁移或部署前端。
- 已核验Mac没有猎手进程、launchd或cron任务；旧`state.json`来自7月，并不说明Mac仍在运行。
- 云端`hunt.yml`计划每30分钟运行；核验时最近实际约2小时一次，不能把cron表达式当实际告警延迟。
- 本轮先fetch远端再rebase了两笔原有未推送的forensics提交。此前本地feed历史只到8月8日，远端实际上一直更新至9月7日。

## 已推送版本及验证

| 提交 | 内容 |
|---|---|
| `20e6c9b` | 样本、两家模型评审、历史回放研究包 |
| `3e1e3ec` | 规则修正、全候选归档、Windows服务和接管工具 |
| `fb5c4f1` | Windows回放CI与接管账号权限检查 |

功能代码验收基线是`fb5c4f1`；本文所在提交是后续文档交接，不应把旧基线误当远端最新HEAD。拉取最新`main`即可。

[CI 34080850148](https://github.com/mobius0087x/meme-hunter/actions/runs/34080850148)在Windows和Ubuntu均成功：15项规则/发布器测试、15项回放测试、48个真实历史样本离线回放；Windows另通过PowerShell脚本语法解析。

Mac只读数据源预检取得40条池记录；隔离的一轮运行采集39个去重池、输出新版feed、归档39个候选和2份原始请求。写入临时目录，没有发送Telegram。CI没有替代目标Windows上的任务注册、账户凭据与真实首次发布验收。

## 已实现的规则

1. **修正假加速度**：最后5分钟与此前不重叠窗口比较单位时间成交额，按池龄调整。少于15分钟、缺数据、窗口不一致或此前无成交时为unknown，不给机械加速分。池龄固定在抓取时刻，token年龄未知不伪造。
2. **扩展覆盖**：四小时只限制新池来源；热门老池和跟踪池不受统一年龄窗删除。已关注池掉榜后继续轮转补查，每轮最多3个，保留7天跟踪窗口，游标跨重启保存。并非每个跟踪池每分钟都刷新。
3. **修正风险判断**：V4 bytes32 PoolId不当钱包做持仓检查；不支持的检查标记unknown/unsupported并封顶WATCH。V2/V3也不再仅凭pool/supply比例低就认定撤池。RPC错误、超预算不作为已完成风险检查。
4. **容量筛选**：最近5分钟平均每分钟成交额×1%，与默认100美元假设规模比较，不足则封顶WATCH。它不是订单、报价或真实退出深度；与历史回放的“前一完整分钟成交额”门槛有区别。
5. **保留不确定性**：报价地址入feed，非传统报价仍警示；没有认证NVDA/SPY等股票代币地址。GRADUATED/GRADUATING沿用旧字段以兼容前端，含义是市场成熟度启发式，不代表发射协议实际毕业。
6. **回测采样基础**：每轮原始GT响应、请求错误、所有已读取候选和拒绝原因入`.runtime/archive/`。目前只覆盖实际抓取的API页，不是全链完整历史。`scan`已修成只读，不会因.env配置了Telegram就偷偷发消息。

关键文件：`memehunter/analyze.py`评分；`sources.py`池身份/时点/来源；`forensics.py`风险与成熟度；`hunter.py`采集/跟踪/周期；`storage.py`原子写入与归档；`service.py`常驻监督；`publish.py`仅feed发布。

## Windows接手：执行顺序与完成标准

先阅读 [WINDOWS.md](WINDOWS.md)。用户已要求Windows负责监控，继续完成安装、预检和接管；无需重新讨论迁移方案。若目标机器、账号或密钥确实不可用，应明确缺少哪项，不能声称已经迁移。

1. 安装Python 3.10+、Git、GitHub CLI；clone/pull本仓库`main`。
2. `.env.example`复制为`.env`，从用户现有配置安全取得可选Telegram配置。GitHub Secrets不会自动下载到Windows，不从公开Git寻找密钥，不把token/聊天ID贴进文档或提交。
3. `gh auth login`、`gh auth setup-git`，确认当前账号能推送仓库并修改Actions变量。仓库所有者为`mobius0087x`；多个账号时可用`gh auth switch --user mobius0087x`。
4. 先执行只读安装预检，再执行接管：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -TakeOver
```

接管脚本注册当前用户的`MemeHunter`任务，设置`MH_RUNNER=windows`，等待旧云端任务排空，再启动Windows服务；10分钟内须完成首次feed发布，失败则尝试停止Windows任务并恢复`cloud`。若回退命令也失败，必须手动确认归属。

**完成标准**：仓库变量为`windows`；Windows任务运行；`.runtime/health.json`的`last_cycle_at`、`last_publish_at`持续前进；远端feed出现Windows发布且`rules_version=2026-09-07-disjoint-v2`；云端后续猎手job跳过；没有第二个常驻实例。把核验时间、Windows位置、实际任务模式和首次发布commit写回本文，然后提交推送。不要为了验收额外执行`test-tg`。

默认任务**需要当前用户已登录**；锁屏可继续，注销/睡眠/关机会中断，重新登录会启动。应关闭自动睡眠。若需要无人登录启动，按WINDOWS.md通过Windows任务界面调整同一用户凭据并实测；不能把默认登录任务称为无人值守开机服务。

服务目标周期60秒，实际受接口耗时影响；feed最多每5分钟发布一次。`localhost:46630`防同机双实例；每轮检查GitHub运行归属，无法验证时停止。不要在另一台Windows/Mac同时启动普通`run`循环。

## 文件、发布与恢复边界

- `state.json`：去重/跟踪状态，留在运行机；需要迁移时先停旧实例再安全复制。
- `.runtime/health.json`与`service.log`：健康和轮转日志。
- `.runtime/archive/`：原始样本，不上传Git、不自动清理；接手方安排磁盘监测与备份。云端回退模式保存Actions artifact 14天。
- `.runtime/publisher.git`：独立发布缓存。只更新远端`feed/signals.json`，保留并发代码变更，不包含.env/state；不自动更新正在执行的程序。
- 更新代码须先停止Windows任务，备份生成feed，再按WINDOWS.md执行`git pull --ff-only`、依赖安装、测试及重启；不要强制覆盖用户源码。
- 回云端：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/return-to-cloud.ps1`。先停用Windows，再恢复`MH_RUNNER=cloud`。

本次Mac推送遇到两个已解决问题：默认Git账号无仓库写权限（403），改为仅该进程使用已登录的owner凭据；研究包上传发生HTTP 400，单次git使用`http.version=HTTP/1.1`、`http.postBuffer=104857600`后成功。未更改全局GitHub账号。Windows若遇403先查身份，不反复盲推，不输出token。

## 研究结论和下一步

完整资料在 [research/2026-09-07/README.md](research/2026-09-07/README.md)，模型争议见 [ADJUDICATION.md](research/2026-09-07/reviews/ADJUDICATION.md)，后续假设见 [STRATEGY-SPEC.md](research/2026-09-07/STRATEGY-SPEC.md)。

- MiniMax M3、DeepSeek V4 Pro都通过真实API各完成独立评审与交叉复核，不是用Codex子代理冒充；原始回复中的错误数字/公式以裁决文件为准。Windows运行监控或离线回放不需要这两家模型的API key。
- 当前市场60条网页观察，44个不同已确认池，14行身份未确定；不是60个独立币或同时点价格快照。涵盖新发、股票配对、热门老池以及弱势对照。
- 历史冻结427份feed、2405条去重告警、2441条观测，范围7月10日至8月8日；这是当时本地可见范围，不是截至9月7日的云端全集。
- 回放预选48个token首个高等级告警（21 HOT+27 ALERT），2761根分钟K线。主情景100美元/1%前分钟成交额容量门/每边2%假设成本下，42个入场容量拒绝、3个缺前置bar、1个入场未成交、1个退出删失，仅1个可完成价格代理回放。不能报总体胜率或盈利结论。
- 旧CC记忆里“缺池归零、mark-to-now亏损、亏在持有不在入场”等7月结论不视为本轮已验证。缺行情不等于归零、最高价不等于可成交退出，今天的热门币不能倒填旧候选。
- Windows先稳定接管并积累连续时点数据，再验证新币延续、股票配对/老币轮动、退出监控三条假设。新规则尚无独立留出期盈利验证；不添加自动交易或钱包签名功能。

Windows离线回放使用`python -X utf8`，避免系统代码页破坏中文输入；具体命令见WINDOWS.md。原始研究数据与模型回复按字节冻结，`.gitattributes`关闭该目录的换行转换以保留SHA-256。
