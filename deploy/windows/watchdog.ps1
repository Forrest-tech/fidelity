# Watchdog for the Fidelity server (requirements v3 S-3; failure-mode table #1 and #2, docs/quality/FMEA.md).
# Run every 5 minutes by the scheduled task "Fidelity Watchdog" (install-watchdog.ps1).
#  - asks the server's sign-in page; two failed checks in a row count as down;
#  - down and the "Fidelity Server" task is not running: starts the task;
#  - down although the task runs (hung): ends the server process, the supervisor in run-server.ps1 starts it again;
#  - tells the administrators by e-mail when it acted and again when the server is back.
# Everything it does is written to data\work\watchdog.log.
param([int]$Port = 8000, [string]$Task = "Fidelity Server", [string]$WorkDir = "")

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$work = if ($WorkDir) { $WorkDir } else { Join-Path $root "data\work" }
$state = Join-Path $work "watchdog.json"
$log = Join-Path $work "watchdog.log"
$py = Join-Path $root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Write-Log([string]$m) { Add-Content -Path $log -Value ("[" + (Get-Date -Format s) + "] " + $m) }

function Send-Alert([string]$subject, [string]$text) {
    try {
        $env:PYTHONUTF8 = "1"
        & $py (Join-Path $root "backend\scripts\alert_mail.py") $subject $text | Out-Null
    } catch { Write-Log ("alert mail failed: " + $_.Exception.Message) }
}

$s = @{ fails = 0; down_since = $null; alerted = $false }
if (Test-Path $state) {
    try { $j = Get-Content $state -Raw | ConvertFrom-Json; $s.fails = [int]$j.fails; $s.down_since = $j.down_since; $s.alerted = [bool]$j.alerted } catch {}
}

$ok = $false
try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 ("http://127.0.0.1:" + $Port + "/login")
    $ok = ($r.StatusCode -eq 200)
} catch { $ok = $false }

if ($ok) {
    if ($s.alerted) {
        Write-Log "server is back"
        Send-Alert "Fidelity is back online / Fidelity 已恢复" ("The server answers again (down since " + $s.down_since + "). / 服务器已恢复（自 " + $s.down_since + " 起不可用）。")
    }
    $s = @{ fails = 0; down_since = $null; alerted = $false }
} else {
    $s.fails = $s.fails + 1
    if (-not $s.down_since) { $s.down_since = (Get-Date -Format s) }
    Write-Log ("health check failed (" + $s.fails + " in a row)")
    if ($s.fails -ge 2) {
        $t = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
        $action = ""
        if ($t -and $t.State -ne "Running") {
            Start-ScheduledTask -TaskName $Task
            $action = "started the task '" + $Task + "' (it was " + $t.State + ")"
        } else {
            # running but not answering: end the server process; the supervisor loop starts it again
            $procs = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($p in $procs) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
            $action = "ended the hung server process(es) " + ($procs -join ",") + "; the supervisor starts it again"
        }
        Write-Log $action
        if (-not $s.alerted) {
            Send-Alert "Fidelity server was down / Fidelity 服务中断" ("Since " + $s.down_since + " the server did not answer. The watchdog " + $action + ". / 自 " + $s.down_since + " 起服务器无响应，看门狗已自动处理：" + $action + "。")
            $s.alerted = $true
        }
    }
}
$s | ConvertTo-Json | Set-Content -Path $state -Encoding utf8
