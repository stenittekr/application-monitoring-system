<#
Installs (or updates) the monitoring agent on many servers at once over
PowerShell Remoting, instead of copying the folder and running install steps
by hand on each one - the process described in agent-poc/README.md, just not
repeated 75 times by a person.

Run from an admin workstation that has WinRM access to the target servers
(the servers do NOT need inbound access from the monitoring platform itself -
only from whoever is running this script, same as any other remote admin
task). Needs Administrator rights on each target to register the service.

    # first install on a batch of servers
    .\install-agent-fleet.ps1 -ServerListFile .\servers.txt `
        -AdminToken <JWT> -Api https://monitoring.awgtc.internal/api

    # re-run against the same list later to push out a new agent.py -
    # already-enrolled servers get new files + service restart, not re-enrolled
    .\install-agent-fleet.ps1 -ServerListFile .\servers.txt `
        -Api https://monitoring.awgtc.internal/api

One bad server does not stop the rest - each is tried independently and the
failures are listed at the end, so a fleet of 75 does not die on server #3.
#>
param(
    [string[]]$Servers,
    [string]$ServerListFile,
    [string]$AdminToken,
    [Parameter(Mandatory)][string]$Api,
    [pscredential]$Credential,
    [string]$Source = (Join-Path (Split-Path -Parent $PSScriptRoot) "agent-poc")
)

$ErrorActionPreference = "Stop"
$installDir = "C:\AMNS-Agent"
$files = @("agent.py", "agent_config.py", "agent_service.py", "requirements.txt")

if ($ServerListFile) { $Servers = Get-Content $ServerListFile | Where-Object { $_.Trim() -and $_ -notmatch "^\s*#" } }
if (-not $Servers) { Write-Host "STOPPED: pass -Servers or -ServerListFile." -ForegroundColor Red; exit 1 }
foreach ($f in $files) {
    if (-not (Test-Path (Join-Path $Source $f))) {
        Write-Host "STOPPED: $f not found in $Source." -ForegroundColor Red; exit 1
    }
}
if (-not $Credential) { $Credential = Get-Credential -Message "Admin credential for the target servers" }

$results = foreach ($server in $Servers) {
    Write-Host "`n== $server" -ForegroundColor Cyan
    $status = "OK"; $detail = ""
    try {
        if (-not (Test-WSMan -ComputerName $server -ErrorAction Stop)) { throw "WinRM not reachable" }
        $session = New-PSSession -ComputerName $server -Credential $Credential

        Invoke-Command -Session $session -ScriptBlock {
            param($dir) New-Item -ItemType Directory -Force -Path $dir | Out-Null
        } -ArgumentList $installDir | Out-Null

        foreach ($f in $files) {
            Copy-Item -Path (Join-Path $Source $f) -Destination $installDir -ToSession $session -Force
        }

        $outcome = Invoke-Command -Session $session -ScriptBlock {
            param($dir, $token, $api)
            Set-Location $dir
            $configPath = "C:\ProgramData\AMNS-Agent\config.json"
            $alreadyEnrolled = Test-Path $configPath

            if (-not $alreadyEnrolled -and -not $token) {
                return "SKIPPED: not enrolled yet and no -AdminToken given"
            }

            python -m pip install --no-user --quiet -r requirements.txt
            if ($LASTEXITCODE -ne 0) { return "FAILED: pip install" }

            if (-not $alreadyEnrolled) {
                python agent.py enroll --admin-token $token --api $api
                if ($LASTEXITCODE -ne 0) { return "FAILED: enroll" }
                python agent_service.py --startup auto install
                if ($LASTEXITCODE -ne 0) { return "FAILED: service install" }
            } else {
                python agent_service.py stop 2>$null
            }
            python agent_service.py start
            if ($LASTEXITCODE -ne 0) { return "FAILED: service start" }

            $svc = Get-Service AMNSAgent -ErrorAction SilentlyContinue
            if ($svc.Status -ne "Running") { return "FAILED: service not running after start" }
            "OK: $(if ($alreadyEnrolled) {'updated'} else {'enrolled + installed'})"
        } -ArgumentList $installDir, $AdminToken, $Api

        Remove-PSSession $session
        if ($outcome -notmatch "^OK") { $status = ($outcome -split ":")[0]; $detail = $outcome }
        Write-Host "  $outcome" -ForegroundColor $(if ($outcome -match "^OK") { "Green" } else { "Yellow" })
    } catch {
        $status = "FAILED"; $detail = $_.Exception.Message
        Write-Host "  FAILED: $detail" -ForegroundColor Red
    }
    [PSCustomObject]@{ Server = $server; Status = $status; Detail = $detail }
}

Write-Host "`n== Summary" -ForegroundColor Cyan
$results | Format-Table -AutoSize
$failed = $results | Where-Object { $_.Status -ne "OK" }
if ($failed) {
    Write-Host "$($failed.Count) of $($results.Count) server(s) need attention (see above)." -ForegroundColor Yellow
    exit 1
}
Write-Host "All $($results.Count) server(s) done." -ForegroundColor Green
