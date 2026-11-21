# Registers a scheduled task that starts the Fidelity server when you log on to Windows and keeps it running.
# Needs no administrator rights (the task belongs to the current user).
#   install:    powershell -ExecutionPolicy Bypass -File install-task.ps1
#   remove:     Unregister-ScheduledTask -TaskName "Fidelity Server" -Confirm:$false
param([string]$TaskName = "Fidelity Server", [int]$Port = 8000)

$script = Join-Path $PSScriptRoot "run-server.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '" -Port ' + $Port)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Output ("Task '" + $TaskName + "' registered. Start it now with:  Start-ScheduledTask -TaskName '" + $TaskName + "'")
