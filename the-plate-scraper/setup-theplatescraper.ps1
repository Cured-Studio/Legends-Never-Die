# ============================================================
#  THE PLATE SCRAPER — theplatescraper.com
#  One-click Windows setup (PowerShell)
#
#  What this does:
#    1. Finds Python (3.9+)
#    2. Creates a virtual environment in .venv and installs
#       the optional MySQL driver (pip install -r requirements.txt)
#    3. Runs the MySQL Wizard headlessly:
#         CREATE DATABASE  ->  schema.sql  ->  migrate JSON data  ->  activate
#       (skipped with -SkipDb, or if no MySQL server is reachable;
#        the site then runs on its built-in JSON store)
#    4. Starts the web server on the port you choose
#    5. Opens the site in your browser
#
#  Usage (from this folder):
#    powershell -ExecutionPolicy Bypass -File .\setup-theplatescraper.ps1
#    .\setup-theplatescraper.ps1 -DbPassword 'secret' -Port 8090
#    .\setup-theplatescraper.ps1 -SkipDb
#
#  You can also skip MySQL entirely and finish the setup later in the
#  browser: open  http://localhost:<port>/setup.html  (the visual wizard).
# ============================================================
param(
    [string]$DbHost      = "127.0.0.1",
    [int]   $DbPort      = 3306,
    [string]$DbUser      = "root",
    [string]$DbPassword  = "",
    [string]$DbName      = "theplatescraper",
    [int]   $Port        = 8080,
    [switch]$SkipDb,
    [switch]$NoBrowser,
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"
$Site = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Site

function Say($m, $c = "Cyan") { Write-Host ("  " + $m) -ForegroundColor $c }
function Banner($m) { Write-Host ""; Write-Host ("== " + $m + " " + ("=" * [Math]::Max(1, 58 - $m.Length))) -ForegroundColor White -BackgroundColor DarkGray }

Banner "THE PLATE SCRAPER — setup wizard"

# ----------------------------------------------------------- 1. Python
Banner "1/4 Python"
$py = $null
foreach ($cand in @("py", "python3", "python")) {
    try {
        $v = & $cand -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($v -match "^\d") { $py = $cand; $pyVer = $v; break }
    } catch { }
}
if (-not $py) {
    Write-Host "  Python not found. Install it from https://python.org (tick 'Add to PATH'), then re-run." -ForegroundColor Red
    exit 1
}
Say ("Using " + $py + " " + $pyVer) "Green"

# ----------------------------------------------------------- 2. venv + deps
Banner "2/4 Environment (venv + MySQL driver)"
$venvDir = Join-Path $Site ".venv"
if ($NoVenv) {
    Say "Skipping venv (-NoVenv) — using system Python." "Yellow"
    $pyRun = $py
} else {
    if (-not (Test-Path (Join-Path $venvDir "Scripts\python.exe"))) {
        Say "Creating virtual environment in .venv ..."
        & $py -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    }
    $pyRun = Join-Path $venvDir "Scripts\python.exe"
    Say "Installing requirements (pymysql) ..."
    & $pyRun -m pip install --quiet --disable-pip-version-check -r (Join-Path $Site "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Say "pip install failed (offline?). Continuing — MySQL wizard will guide you in the browser." "Yellow"
    } else {
        Say "Dependencies ready." "Green"
    }
}

# ----------------------------------------------------------- 3. MySQL wizard
$mysqlOn = $false
if ($SkipDb) {
    Banner "3/4 MySQL (skipped with -SkipDb)"
    Say "The site will run on the built-in JSON store. Finish MySQL later at /setup.html" "Yellow"
} else {
    Banner "3/4 MySQL — create database, schema, migrate, activate"
    if (-not $DbPassword) {
        $sec = Read-Host -Prompt ("MySQL password for " + $DbUser + "@" + $DbHost + " (press Enter if none)") -AsSecureString
        $DbPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    $cli = @(
        "--host", $DbHost, "--port", "$DbPort", "--user", $DbUser,
        "--password", $DbPassword, "--database", $DbName
    )
    Say ("Testing connection to " + $DbHost + ":" + $DbPort + " ...")
    & $pyRun (Join-Path $Site "tools\mysql_setup.py") @cli --test
    if ($LASTEXITCODE -eq 0) {
        & $pyRun (Join-Path $Site "tools\mysql_setup.py") @cli --create
        if ($LASTEXITCODE -eq 0) {
            & $pyRun (Join-Path $Site "tools\mysql_setup.py") @cli --migrate
            & $pyRun (Join-Path $Site "tools\mysql_setup.py") @cli --activate
            if ($LASTEXITCODE -eq 0) { $mysqlOn = $true; Say ("MySQL database '" + $DbName + "' created and is the live store.") "Green" }
        }
    }
    if (-not $mysqlOn) {
        Say "MySQL unavailable — the site will use the JSON store (MySQL can be enabled later via /setup.html)." "Yellow"
    }
}

# ----------------------------------------------------------- 4. Launch
Banner "4/4 Launch"
$base = "http://localhost:$Port"
$proc = Start-Process -FilePath $pyRun -ArgumentList @((Join-Path $Site "server.py"), "$Port") -WorkingDirectory $Site -PassThru
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -Uri ($base + "/healthz") -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) {
    Write-Host "  The server did not answer on port $Port yet. Check:  $pyRun server.py $Port" -ForegroundColor Red
    exit 1
}

Write-Host ""
Say "The Plate Scraper is live at  $base" "Green"
Say "  Recipes            $base/recipes.html"
Say "  Recipe Scraper     $base/scraper.html"
Say "  Feed Room (RSS)    $base/feedroom.html"
Say "  Members area       $base/dashboard.html"
Say "  Affiliate panel    $base/affiliate.html   (demo admin: admin@theplatescraper.com / plate-admin-2026)"
Say "  MySQL Wizard       $base/setup.html"
Say ("  Store backend      " + $(if ($mysqlOn) { "MySQL ($DbName)" } else { "JSON (data/db.json)" }))
Say ("  Server PID         " + $proc.Id + "   (stop with:  taskkill /PID " + $proc.Id + ")")
if (-not $NoBrowser) { Start-Process $base }
