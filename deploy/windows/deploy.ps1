# Deploy the latest main to this machine, check it works, and put the previous version back if it does not.
# (requirements v2, S-7). Run from anywhere:   powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\deploy.ps1
#   -Check     only say what would change (nothing is touched)
#   -Port      the server's port (default 8000)
#
# Steps: fetch main -> stop if the checkout has changes -> back up and verify the data -> update the code ->
# install Python packages / web packages only when their lists changed -> build the web app into a new folder and
# swap it in -> restart the server process (run-server.ps1 starts it again; a distilling run in progress is taken
# back over) -> wait for /healthz and the new web bundle -> on failure: previous commit, previous web app, restart.
param([switch]$Check, [int]$Port = 8000, [int]$HealthTimeout = 420)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $root ".venv\Scripts\python.exe"
$web = Join-Path $root "web"
$log = Join-Path $root "data\work\deploy.log"
function Say($m) { $line = "[deploy " + (Get-Date -Format s) + "] " + $m; Write-Output $line; Add-Content -Path $log -Value $line }
# Not named "Git": PowerShell names are case-insensitive, so a function "Git" calling git would call itself for ever.
function Invoke-Git {
    $saved = $ErrorActionPreference; $ErrorActionPreference = "Continue"     # git writes progress to stderr
    try { $out = & git.exe -C $root @args 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed: $out" }
    return $out
}

function Restart-Server {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "uvicorn app.main:app --host 0.0.0.0 --port $Port" }
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -Confirm:$false }
    Say ("restarted the server (" + @($procs).Count + " process(es) stopped; run-server.ps1 starts it again)")
}

function Wait-Healthy($bundle) {
    $deadline = (Get-Date).AddSeconds($HealthTimeout)
    Start-Sleep -Seconds 15
    while ((Get-Date) -lt $deadline) {
        try {
            $h = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://localhost:$Port/healthz"
            if ($h.StatusCode -eq 200) {
                if (-not $bundle) { return $true }
                $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 "http://localhost:$Port/"
                if ($page.Content -match [regex]::Escape($bundle)) { return $true }
            }
        } catch { }
        Start-Sleep -Seconds 10
    }
    return $false
}

function Bundle { $f = Get-ChildItem (Join-Path $web "dist\assets") -Filter "index-*.js" -ErrorAction SilentlyContinue | Select-Object -First 1; if ($f) { $f.Name } else { "" } }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
Invoke-Git fetch -q origin main | Out-Null
$branch = (Invoke-Git rev-parse --abbrev-ref HEAD).Trim()
$prev = (Invoke-Git rev-parse HEAD).Trim()
$next = (Invoke-Git rev-parse origin/main).Trim()
$dirty = Invoke-Git status --porcelain --untracked-files=no
Say "on $branch at $($prev.Substring(0,7)); origin/main is $($next.Substring(0,7))"
if ($branch -ne "main") { throw "the checkout is on '$branch', not main: switch back first (git checkout main)" }
if ($dirty) { throw "the checkout has uncommitted changes; commit or remove them first:`n$dirty" }
if ($prev -eq $next) { Say "already up to date; nothing to deploy"; exit 0 }
$changed = Invoke-Git diff --name-only $prev $next
$needPip = $changed -match '^backend/requirements.*\.txt$'
$needNpm = $changed -match '^web/package(-lock)?\.json$'
$needWeb = $changed -match '^web/'
Say ("changes: " + @($changed).Count + " file(s); python packages: " + [bool]$needPip + "; web packages: " + [bool]$needNpm + "; web app: " + [bool]$needWeb)
if ($Check) { Invoke-Git log --oneline "$prev..$next"; exit 0 }

# 1. a verified backup before anything changes (made by the running version's code; a version older than the
#    backup module cannot, which is only the case when this deploy is the one that brings it)
if (-not (Test-Path (Join-Path $root "backend\app\ops\backup.py"))) {
    Say "the running version has no backup module yet (this deploy brings it): continuing without a pre-deploy backup"
} else {
    & $py -c "import sys; sys.path.insert(0, r'$root\backend'); from app.ops import backup as B; r = B.make(); print(r['path'], 'verified' if r['ok'] else 'NOT verified'); sys.exit(0 if r['ok'] else 1)"
    if ($LASTEXITCODE -ne 0) { throw "the backup did not verify; nothing was changed" }
    Say "backup made and verified"
}

$oldDist = Join-Path $web "dist.prev"
try {
    Invoke-Git merge -q --ff-only $next | Out-Null
    Say "code updated to $($next.Substring(0,7))"
    if ($needPip) { & $py -m pip install -q -r (Join-Path $root "backend\requirements.txt"); if ($LASTEXITCODE -ne 0) { throw "pip install failed" }; Say "python packages installed" }
    if ($needNpm) { Push-Location $web; npm ci --no-audit --no-fund; $rc = $LASTEXITCODE; Pop-Location; if ($rc -ne 0) { throw "npm ci failed" }; Say "web packages installed" }
    if ($needWeb) {
        Push-Location $web
        npx vite build --outDir dist.new --emptyOutDir
        $rc = $LASTEXITCODE; Pop-Location
        if ($rc -ne 0) { throw "web build failed" }
        if (Test-Path $oldDist) { Remove-Item -Recurse -Force $oldDist }
        if (Test-Path (Join-Path $web "dist")) { Rename-Item (Join-Path $web "dist") "dist.prev" }
        Rename-Item (Join-Path $web "dist.new") "dist"
        Say "web app built and swapped in"
    }
    Restart-Server
    $want = if ($needWeb) { Bundle } else { "" }
    if (-not (Wait-Healthy $want)) { throw "the server did not come back healthy within $HealthTimeout s" }
    Say "deployed $($next.Substring(0,7)): healthy$(if ($want) { ', serving ' + $want })"
} catch {
    Say ("FAILED: " + $_.Exception.Message + " - putting $($prev.Substring(0,7)) back")
    & git.exe -C $root reset -q --hard $prev
    if ($needWeb -and (Test-Path $oldDist)) {
        if (Test-Path (Join-Path $web "dist")) { Remove-Item -Recurse -Force (Join-Path $web "dist") }
        Rename-Item $oldDist "dist"
    }
    if ($needPip) { & $py -m pip install -q -r (Join-Path $root "backend\requirements.txt") }
    Restart-Server
    if (Wait-Healthy "") { Say "rolled back to $($prev.Substring(0,7)); the server is healthy" } else { Say "rolled back, but the server is NOT answering: check data\work\server-$Port.log" }
    exit 1
}
