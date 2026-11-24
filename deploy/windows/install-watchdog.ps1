# Registers the "Fidelity Watchdog" scheduled task: watchdog.ps1 every 5 minutes as the current user (no admin rights).
# Requirements v3 S-3. Re-running it replaces the task.
$script = Join-Path $PSScriptRoot "watchdog.ps1"
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '"')
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Unregister-ScheduledTask -TaskName "Fidelity Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "Fidelity Watchdog" -Action $a -Trigger $t -Settings $s -Description "Checks the Fidelity server every 5 minutes; restarts it and mails administrators when it is down (requirements v3 S-3)." | Out-Null
"Fidelity Watchdog registered; log: data\work\watchdog.log"
