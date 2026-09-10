<#
Installs the platform on a server. Run once, elevated, from the repo root.

    .\scripts\deploy.ps1                     # SQLite, port 5000
    .\scripts\deploy.ps1 -SetupDatabase      # also create the SQL Server database
    .\scripts\deploy.ps1 -Port 443

Does: dependencies, secrets scaffold, migrations, both Windows services with
crash recovery, the firewall rule, and a health check that proves it works.

Does not: choose your database, or write your credentials. Those are decisions,
and a deploy script that invents a password is a deploy script that hides one.
It stops and tells you what to fill in.

Safe to re-run - every step checks before it acts.
#>
param(
    [int]$Port = 5000,
    [switch]$SetupDatabase
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$services = @("AMNSPlatform", "AMNSMonitor")

function Fail($message) { Write-Host "`nSTOPPED: $message" -ForegroundColor Red; exit 1 }
function Step($message) { Write-Host "`n== $message" -ForegroundColor Cyan }

# --- refuse to run where it cannot work ------------------------------------

if (-not ([Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole("Administrators")) {
    Fail "not elevated. Registering a Windows service needs Administrator."
}
if (-not (Test-Path "$repo\backend\run.py")) { Fail "run this from the repo, not a copy of one folder." }

# The platform has spent its life inside a synced folder, which replicated every
# credential in dev.db to cloud storage. Not again.
if ($repo -match "OneDrive|Dropbox|Google Drive") {
    Fail "the repo is inside a synced folder ($repo). Clone it to C:\AMNS instead."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python is not on PATH." }

# --- dependencies ----------------------------------------------------------

Step "Installing dependencies"
# --no-user is not optional. Without it pip falls back to the profile, the
# services run as LocalSystem, cannot see them, and die with ModuleNotFoundError
# while reporting a successful install. That cost two days of dead monitoring.
python -m pip install --no-user --quiet -r "$repo\backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }

# --- secrets ---------------------------------------------------------------

$envFile = "$repo\backend\.env"
if (-not (Test-Path $envFile)) {
    Step "Creating backend\.env"
    Copy-Item "$repo\backend\.env.example" $envFile
    $keys = python -c "import secrets;print(secrets.token_urlsafe(48));print(secrets.token_urlsafe(48))"
    Add-Content $envFile "`nSECRET_KEY=$($keys[0])`nJWT_SECRET_KEY=$($keys[1])`nHOST=0.0.0.0"
    Write-Host "`nFill in backend\.env before continuing:" -ForegroundColor Yellow
    Write-Host "  SMTP_*, EMAIL_FROM, WATCHDOG_RECIPIENTS, DB_* passwords, LDAP_*, any SYN_*"
    Write-Host "  For SQL Server: set SQL_SERVER/SQL_DATABASE and DELETE the DATABASE_URL line."
    Write-Host "`nThen run this script again." -ForegroundColor Yellow
    exit 0
}

# --- database --------------------------------------------------------------

if ($SetupDatabase) {
    Step "Creating the database and running every migration"
    & "$repo\scripts\setup_database.bat"
    if ($LASTEXITCODE -ne 0) { Fail "database setup failed - nothing after the failing migration ran." }
}

# --- prove it starts before installing anything as a service ---------------

Step "Checking the app starts"
# run.py reads PORT from the environment, so the test listens where we are
# about to open the firewall - not on 5000 while we punch a hole in 443.
$env:PORT = $Port
$test = Start-Process python -ArgumentList "run.py" -WorkingDirectory "$repo\backend" -PassThru -WindowStyle Hidden
try {
    $ok = $false
    foreach ($attempt in 1..20) {
        Start-Sleep -Seconds 2
        try {
            if ((Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) {
                $ok = $true; break
            }
        } catch { }
    }
} finally { Stop-Process -Id $test.Id -Force -ErrorAction SilentlyContinue }
if (-not $ok) { Fail "the app did not answer /api/health. Run 'python run.py' by hand and read the error." }
Write-Host "  answered on port $Port"

# --- services --------------------------------------------------------------

# Stopped first: pywin32 relocates its host exe on install, and Windows refuses
# to move an executable that a running service is using.
Step "Installing services"
foreach ($name in $services + @("AMNSAgent")) {
    if (Get-Service $name -ErrorAction SilentlyContinue) { Stop-Service $name -Force -ErrorAction SilentlyContinue }
}
python "$repo\backend\platform_service.py" --startup auto install
python "$repo\monitoring\monitor_service.py" --startup auto install

foreach ($name in $services) {
    # Three restarts a minute apart. Without this a crashed service stays
    # crashed, which is how PS_QAS went 65 minutes unmonitored.
    sc.exe failure $name reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
    Start-Service $name
}

# --- firewall --------------------------------------------------------------

Step "Opening port $Port inbound"
if (-not (Get-NetFirewallRule -DisplayName "AMNS Platform" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "AMNS Platform" -Direction Inbound -Protocol TCP `
        -LocalPort $Port -Action Allow -Profile Domain | Out-Null
}

# --- verify ----------------------------------------------------------------

Step "Result"
Get-Service AMNS* | Select-Object Name, Status, StartType | Format-Table -AutoSize
Write-Host "Platform: http://$env:COMPUTERNAME`:$Port"
Write-Host "`nStill to do by hand:" -ForegroundColor Yellow
Write-Host "  1. Repoint each agent's config.json 'api' at $env:COMPUTERNAME (hostname, not IP)"
Write-Host "  2. Install the watchdog - see DEPLOYMENT.md step 8"
Write-Host "  3. Change the seeded admin password"
Write-Host "  4. Stop and remove the services on the old machine"
