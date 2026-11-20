# Keeps the Fidelity server running: starts it, and starts it again whenever it exits.
# Run it through the scheduled task made by install-task.ps1, or by hand:  powershell -File run-server.ps1
param([int]$Port = 8000)

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)        # deploy\windows -> the repository
$py = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
$log = Join-Path $root ("data\work\server-" + $Port + ".log")
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
$env:PYTHONUTF8 = "1"
Set-Location $backend

while ($true) {
    Add-Content -Path $log -Value ("[supervisor] starting " + (Get-Date -Format s))
    cmd.exe /c ('"' + $py + '" -m uvicorn app.main:app --host 0.0.0.0 --port ' + $Port + ' >> "' + $log + '" 2>&1')
    Add-Content -Path $log -Value ("[supervisor] server exited with code " + $LASTEXITCODE + " at " + (Get-Date -Format s) + "; starting again in 5 seconds")
    Start-Sleep -Seconds 5
}
