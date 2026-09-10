<#
Runs a Python application as a Windows scheduled task, and updates it from git.

Replaces copy-a-folder-then-start-it-by-hand. Two things it buys:

  * the application starts at boot, with nobody logged in, and restarts itself
    if it crashes - the reason AMNSAgent survives a reboot and your apps do not
  * deploying becomes "git pull, restart", with no path to register anywhere

Uses Task Scheduler rather than NSSM: it is already on every Windows machine,
needs no download and no approval, and does auto-start and restart-on-failure
natively. A service would be marginally tidier; it is not worth a dependency.

Run elevated, ON THE SERVER the application runs on.

    # once per application
    .\app-service.ps1 -Register -Name AWGTC-DMS `
        -Path "E:\Hosted-FIles\DMS\Live" -Script app.py -Port 5002

    # every deployment after that
    .\app-service.ps1 -Deploy -Name AWGTC-DMS

    .\app-service.ps1 -Status                # what is registered, and running
#>
param(
    [switch]$Register,
    [switch]$Deploy,
    [switch]$Status,
    [string]$Name,
    [string]$Path,
    [string]$Script = "app.py",
    [string]$Venv = ".venv",
    [int]$Port
)

$ErrorActionPreference = "Stop"
$prefix = "AMNSApp-"          # so these are findable, and never confused with Windows' own

function Fail($m) { Write-Host "`nSTOPPED: $m" -ForegroundColor Red; exit 1 }

if (-not ([Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole("Administrators")) {
    Fail "not elevated. Registering a scheduled task needs Administrator."
}

if ($Status) {
    Get-ScheduledTask -TaskName "$prefix*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $info = $_ | Get-ScheduledTaskInfo
            [PSCustomObject]@{
                Application = $_.TaskName -replace "^$prefix", ""
                State       = $_.State
                LastRun     = $info.LastRunTime
                LastResult  = $info.LastTaskResult
                Folder      = ($_.Actions[0].WorkingDirectory)
            }
        } | Format-Table -AutoSize
    exit 0
}

if (-not $Name) { Fail "-Name is required." }
$task = "$prefix$Name"

if ($Register) {
    if (-not $Path) { Fail "-Path is required when registering." }
    if (-not (Test-Path $Path)) { Fail "$Path does not exist." }

    $python = Join-Path $Path "$Venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Fail "no interpreter at $python. Create the venv first, or pass -Venv with its folder name."
    }
    if (-not (Test-Path (Join-Path $Path $Script))) { Fail "$Script is not in $Path." }

    $action = New-ScheduledTaskAction -Execute $python -Argument $Script -WorkingDirectory $Path
    $trigger = New-ScheduledTaskTrigger -AtStartup
    # SYSTEM, so it runs with nobody logged in - the whole point. It also means
    # the app cannot reach network shares or mapped drives; if it needs those,
    # register it under a service account instead.
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $task

    Write-Host "`nRegistered $task" -ForegroundColor Green
    Write-Host "  runs   : $python $Script"
    Write-Host "  in     : $Path"
    Write-Host "  starts : at boot, restarts up to 3 times a minute apart"
    if ($Port) {
        Start-Sleep -Seconds 4
        $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listening) {
            Write-Host "  port   : $Port listening on $($listening[0].LocalAddress)"
            if ($listening[0].LocalAddress -eq "127.0.0.1") {
                Write-Host "           bound to localhost only - nothing off this machine can reach it, " `
                           "monitoring included" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  port   : nothing listening on $Port yet - check the task's last result" -ForegroundColor Yellow
        }
    }
    Write-Host "`nNow add it on the platform's Applications page so a failure raises an incident."
    exit 0
}

if ($Deploy) {
    $existing = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if (-not $existing) { Fail "$task is not registered. Run with -Register first." }
    $folder = $existing.Actions[0].WorkingDirectory
    if (-not $folder -or -not (Test-Path $folder)) { Fail "the registered folder '$folder' is gone." }

    Write-Host "Stopping $task"
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue

    if (Test-Path (Join-Path $folder ".git")) {
        Write-Host "Pulling in $folder"
        git -C $folder pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            # Left stopped on purpose: starting the old code after a failed
            # update is how you end up debugging the wrong version.
            Fail "git pull failed. The application is stopped; fix the working tree and deploy again."
        }
        $requirements = Join-Path $folder "requirements.txt"
        if (Test-Path $requirements) {
            & (Join-Path $folder "$Venv\Scripts\python.exe") -m pip install --quiet -r $requirements
        }
    } else {
        Write-Host "No git repo in $folder - nothing to pull, restarting the code that is there." -ForegroundColor Yellow
    }

    Start-ScheduledTask -TaskName $task
    Start-Sleep -Seconds 4
    $info = Get-ScheduledTask -TaskName $task | Get-ScheduledTaskInfo
    Write-Host "`n$task : $((Get-ScheduledTask -TaskName $task).State), last result $($info.LastTaskResult)"
    exit 0
}

Fail "pass one of -Register, -Deploy or -Status."
