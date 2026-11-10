# Example only; not executed or registered automatically.
# Example time assumes the workstation is set to Asia/Shanghai.
# daily-ops checks XNYS close+20 minutes through the next open and preserves blocked exit codes.
# $action = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument '-NoProfile -WindowStyle Hidden -File "C:\path\quant-research\scripts\run_daily.ps1"'
# $trigger = New-ScheduledTaskTrigger -Daily -At '06:00'
# Register-ScheduledTask -TaskName 'QuantResearchLocalReport' -Action $action -Trigger $trigger -Description 'Verified local SIP observations and reports'
