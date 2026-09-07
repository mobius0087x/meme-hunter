param([string]$TaskName = "MemeHunter")
$ErrorActionPreference = "Stop"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
}
& gh variable set MH_RUNNER --repo mobius0087x/meme-hunter --body cloud
if ($LASTEXITCODE -ne 0) { throw "Could not restore cloud ownership" }
Write-Host "Cloud owns monitoring again; next scheduled hunt will run."
