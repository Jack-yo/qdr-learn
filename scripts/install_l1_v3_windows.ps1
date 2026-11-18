# QDR L1 V3 Windows Task Scheduler installer (current user).
# No credentials are stored in the scheduled-task action.
param(
  [string]$TaskName = "QDR-L1-V3-Daily",
  [int]$EveryMinutes = 30
)
$ErrorActionPreference = "Stop"
if ($EveryMinutes -lt 15 -or $EveryMinutes -gt 1440) { throw "EveryMinutes must be 15..1440" }
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython=Join-Path $Root ".venv\Scripts\python.exe"
$Python=if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python -ErrorAction Stop).Source }
$JobArgs='-m quant_research.workflow.l1_v3_pipeline --root "{0}" daily' -f $Root
$Action=New-ScheduledTaskAction -Execute $Python -Argument $JobArgs -WorkingDirectory $Root
$Trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 365)
$Settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "QDR L1 V3 market research; no orders" -Force | Out-Null
Write-Host "Scheduled: $TaskName every $EveryMinutes minutes"
Write-Host "Review: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host 'Live check: python -m quant_research.workflow.l1_v3_verify --root . --live'
