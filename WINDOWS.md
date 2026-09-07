# Windows 接管监控

2026-09-07 已核验：此前实际运行者是 GitHub Actions，workflow `hunt.yml` 每30分钟计划执行，但最近实际运行约2小时一次；本地Mac未发现猎手进程、launchd或cron任务。此提交保留云端，Windows验收成功后再接管。

## 安装与预检

Windows 10/11，Python 3.10+、Git、GitHub CLI (`gh`)。以将长期运行监控的Windows用户打开PowerShell：

```powershell
git clone https://github.com/mobius0087x/meme-hunter.git
cd meme-hunter
Copy-Item .env.example .env
notepad .env
gh auth login
gh auth setup-git
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1
```

`.env` 中按需填写 Telegram token/chat ID。GitHub仓库中的Secrets不会自动下载到Windows；从原配置安全转移，勿提交到Git。默认不配置Telegram时仍有本地日志和Web feed。预检只安装依赖、运行测试和读取市场数据，不发Telegram，也不改变云端归属。

本轮已在Mac完成只读数据源预检，取得40条新池/热门池记录。真实Windows任务注册与首次发布必须在目标机器验收，CI只能验证Windows上的代码测试和PowerShell语法。

## 接管

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/install.ps1 -TakeOver
```

脚本将：

1. 先完成上述预检并检查GitHub认证。
2. 注册当前用户的 `MemeHunter` 登录计划任务，设置失败重启及禁止并发。
3. 设置GitHub仓库变量 `MH_RUNNER=windows`，云端猎手任务因此跳过。
4. 等待已排队/运行的旧云端猎手结束，再启动Windows任务。
5. 等待Windows成功完成一轮并发布feed，最长10分钟；失败则停止/移除Windows任务并恢复`MH_RUNNER=cloud`。恢复失败会在终端显示，需手动确认仓库变量。

**默认任务在该用户已登录时运行**：锁屏可继续，注销、睡眠、休眠、关机均会中断。重启后登录会自动恢复；应在Windows电源设置中关闭自动睡眠。若要求“重启后无人登录也运行”，在任务计划程序中改为同一用户“无论用户是否登录都运行”，通过Windows界面提供该用户密码并实测Git/gh凭据访问；本脚本不存储密码。

同一台Windows只能有一个服务进程（localhost:46630锁）。不要在第二台电脑同时启动。服务每轮检查GitHub归属；无法验证时停止，由计划任务重试。GitHub网络故障时不会继续盲发告警。

## 检查运行状态

```powershell
Get-ScheduledTask -TaskName MemeHunter
Get-ScheduledTaskInfo -TaskName MemeHunter
Get-Content .runtime/health.json
Get-Content .runtime/service.log -Tail 60 -Wait
gh variable get MH_RUNNER --repo mobius0087x/meme-hunter
```

重点检查`health.json`的`last_cycle_at`和`last_publish_at`是否持续更新，不只看任务显示“Running”。一轮目标60秒，接口限流、RPC预算和候选数量会延长实际周期；每5分钟最多发布一次Git feed。Web仍读取原来的`main/feed/signals.json`，前端无需迁移。日志轮转为5MB × 6份。

`.runtime/archive/YYYY-MM-DD/`存每轮未过滤候选、拒绝原因、源请求/失败和原始响应，作为后续回测数据。只覆盖本轮实际读取的API页，不能称全链完整样本。目录不会自动清理，请备份并监测磁盘。云端回退模式把同类记录作为Actions artifact保存14天。

`state.json`保留冷启动去重和7天跟踪名单；`.runtime/`、`.env`均不上传。若从旧机器迁移`state.json`，先停止旧实例后复制，不要多端共用写入。独立发布器只提交`feed/signals.json`，保留远端并发代码变更，拒绝覆盖更新的feed；不会自动拉取并执行新代码。

## 更新代码

先停止任务，备份运行文件，然后：

```powershell
Stop-ScheduledTask -TaskName MemeHunter
Copy-Item feed/signals.json .runtime/feed-before-update.json
# feed是生成文件；备份后恢复为本地Git基线，避免pull被生成差异挡住。
git restore -- feed/signals.json
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 上面每一步成功后再启动
Start-ScheduledTask -TaskName MemeHunter
```

若有自己修改的源代码，先另行保存，不要强制reset。更新不会删除state或archive。

## 回到云端

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/return-to-cloud.ps1
```

先停用Windows任务，再设置`MH_RUNNER=cloud`；下一次云端定时任务接手。不会自动执行`test-tg`或发测试消息。

参考：[GitHub变量与条件执行](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)、[Windows任务设置](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)。
