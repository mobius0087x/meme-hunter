param([string]$TaskName = "MemeHunter", [switch]$TakeOver)
$ErrorActionPreference = "Stop"
$Repo = "mobius0087x/meme-hunter"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $Python)) {
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required" }
}
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
& $Python -m memehunter.service --check
if ($LASTEXITCODE -ne 0) { throw "Market preflight failed; cloud unchanged" }
$DataRoot = & $Python -c "from memehunter.storage import RUNTIME; print(RUNTIME)"
if ($LASTEXITCODE -ne 0) { throw "Cannot resolve runtime data directory" }
if (-not $TakeOver) {
    Write-Host "Preflight complete. Configure .env, run gh auth login and gh auth setup-git, then rerun with -TakeOver."
    exit 0
}
& gh auth status
if ($LASTEXITCODE -ne 0) { throw "Run gh auth login under this Windows user first" }
& gh auth setup-git
if ($LASTEXITCODE -ne 0) { throw "Git authentication setup failed" }
$CanPush = & gh api "repos/$Repo" --jq '.permissions.push'
if ($LASTEXITCODE -ne 0 -or $CanPush -ne "true") { throw "Active gh account cannot push this repository; select the owner account" }
& git ls-remote origin main
if ($LASTEXITCODE -ne 0) { throw "Cannot access Git remote" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Task already exists. Stop/unregister it before replacing; cloud unchanged."
}
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-u -m memehunter.service' -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# Registration is inert until ownership is explicitly transferred below.
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings | Out-Null
try {
    & gh variable set MH_RUNNER --repo $Repo --body windows
    if ($LASTEXITCODE -ne 0) { throw "Cannot transfer ownership" }
    # Drain pre-existing cloud jobs before starting the Windows notifier.
    $Deadline = (Get-Date).AddMinutes(12)
    do {
        $Json = & gh run list --repo $Repo --workflow hunt.yml --limit 30 --json status
        if ($LASTEXITCODE -ne 0) { throw "Cannot verify cloud jobs have drained" }
        $Active = @($Json | ConvertFrom-Json | Where-Object { $_.status -ne "completed" })
        if ($Active.Count -eq 0) { break }
        if ((Get-Date) -gt $Deadline) { throw "Cloud jobs did not drain in 12 minutes" }
        Start-Sleep -Seconds 10
    } while ($true)
    Start-ScheduledTask -TaskName $TaskName
    $Started = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $Deadline = (Get-Date).AddMinutes(10)
    do {
        Start-Sleep -Seconds 5
        $HealthPath = Join-Path $DataRoot "health.json"
        if (Test-Path $HealthPath) {
            $Health = Get-Content -Raw -Encoding UTF8 $HealthPath | ConvertFrom-Json
            if ($Health.last_publish_at -ge $Started) { break }
        }
        if ((Get-Date) -gt $Deadline) { throw "Windows did not publish within 10 minutes; returning ownership to cloud" }
    } while ($true)
    Write-Host "Windows owns monitoring. Check .runtime/health.json and .runtime/service.log. Task runs while this user is logged in (locking is OK; logout/sleep stops monitoring)."
} catch {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    & gh variable set MH_RUNNER --repo $Repo --body cloud
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    throw
}
