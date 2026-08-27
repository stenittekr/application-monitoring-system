# Taking the platform live

Everything runs on a laptop today. That is the cause of the DHCP breakage, the
nightly false outages, the monitoring gaps when the lid closes, and the SQLite
locking. This moves it to a machine that stays on.

**Target machine.** Anything that is always on, has a fixed address, and can
reach the systems being monitored. `AWGTC-PORTAL-QAS` (172.50.35.75) works and
is available today. A dedicated VM is better: a monitoring platform sharing a
machine with the applications it watches fails at the same moment they do.

Run every command in an **elevated PowerShell on the target machine**. Run
`hostname` first and read the answer — nearly every problem during the last
deployment was a command run on the wrong machine.

In PowerShell `sc` means `Set-Content`, not the service tool. Use `sc.exe`,
`Restart-Service`, or the Services window.

---

## Before you start

| Check | Command |
|---|---|
| It is the machine you think it is | `hostname` |
| Python 3.11+ is installed | `python --version` |
| At least 2 GB free | `Get-PSDrive C` |
| You are an administrator | the prompt says `Administrator`, or UAC accepted |
| SQL Server reachable, if using it | `Test-NetConnection <sqlhost> -Port 1433` |

---

## 1. Copy the code

Put the whole repository at `C:\AMNS-Platform`.

**Not in a user profile and not in OneDrive.** The services run as LocalSystem,
which frequently cannot read profile paths, and OneDrive sync corrupts database
files while they are open — the current database lives in a synced folder and
should not have.

## 2. Create the database

```powershell
cd C:\AMNS-Platform\scripts
.\setup_database.bat
```

At the prompts: instance `localhost`, login **blank** for Windows authentication.

This creates `ApplicationMonitoringDB` and runs **all 27 migrations** in filename
order, halting on the first failure. Re-running it is safe — every script guards
its own changes.

> If this fails with **error 18456**, the login has no access to SQL Server. That
> is a permission to request, not something to work around. Until it is granted,
> skip to *Staying on SQLite* below — SQLite on a server is still far better than
> SQLite on a laptop.

## 3. Configure

Edit `C:\AMNS-Platform\backend\.env`:

```
SQL_SERVER=localhost
SQL_DATABASE=ApplicationMonitoringDB
SQL_USERNAME=
SQL_PASSWORD=
HOST=0.0.0.0
```

Empty username and password means Windows authentication.

**Delete the `DATABASE_URL` line.** While it exists it overrides everything above
and silently keeps you on SQLite.

Carry over from the old `.env`: `SECRET_KEY`, `JWT_SECRET_KEY`, the `SMTP_*`
settings, `EMAIL_FROM`, `WATCHDOG_RECIPIENTS`, the `DB_*` database passwords, the
`LDAP_*` settings, and any `SYN_*` workflow credentials.

### Staying on SQLite

Keep `DATABASE_URL` pointing at a path **outside** OneDrive:

```
DATABASE_URL=sqlite:///C:/AMNS-Platform/data/monitoring.db
```

Create that folder first. Everything works; you lose concurrent write
performance, which at this scale you will not notice.

## 4. Install dependencies

```powershell
cd C:\AMNS-Platform\backend
python -m pip install -r requirements.txt
python -m pip install pywin32
python -m pywin32_postinstall -install
```

**Machine-wide, never `--user`.** A user-scope install reports success and is
invisible to LocalSystem. That trap has cost two outages already: pywin32 on
19 August and the database driver on 26 August, the second of which left two
checks silently dead for two days.

Verify the interpreter the service will use can actually see them:

```powershell
python -c "import pyodbc, pymysql, psutil, win32serviceutil; print('all present')"
```

## 5. Prove it works before installing anything as a service

```powershell
cd C:\AMNS-Platform\backend
python -c "from app import create_app; create_app(); print('config OK')"
python -m pytest tests -q
```

**177 tests should pass.** A wrong connection string shows up here rather than
at 3am.

## 6. Install the services

```powershell
cd C:\AMNS-Platform\backend
python platform_service.py --startup auto install
Start-Service AMNSPlatform

cd C:\AMNS-Platform\monitoring
python monitor_service.py --startup auto install
Start-Service AMNSMonitor
```

`--startup auto` is what brings them back after a reboot.

### Let Windows restart them if they crash

Nothing does this today. Two lines each, in **cmd**:

```
sc failure AMNSPlatform reset= 86400 actions= restart/60000/restart/60000/restart/60000
sc failureflag AMNSPlatform 1
sc failure AMNSMonitor reset= 86400 actions= restart/60000/restart/60000/restart/60000
sc failureflag AMNSMonitor 1
```

The spaces after `=` are required. `failureflag 1` matters more than it looks:
without it Windows only reacts to a crash, and a service that exits cleanly
because of a bug is not a crash.

### Confirm it is listening to the network

```powershell
netstat -ano | findstr ":5000"
```

Must show `0.0.0.0:5000`. `127.0.0.1:5000` means `HOST` did not take.

## 7. Open the firewall

```powershell
New-NetFirewallRule -DisplayName "AMNS Platform API" -Direction Inbound `
    -Protocol TCP -LocalPort 5000 -Action Allow
```

## 8. Install the watchdog

Nothing else notices when the platform stops. On 25 August both services
stopped overnight and the dashboard went on showing the last status everything
had before the lights went out.

```
schtasks /create /tn "AMNS Watchdog" /sc minute /mo 10 /ru SYSTEM /tr "\"C:\Python314\python.exe\" \"C:\AMNS-Platform\monitoring\watchdog.py\""
```

Adjust the Python path to match. Verify:

```powershell
Start-ScheduledTask -TaskName "AMNS Watchdog"
Get-ScheduledTaskInfo -TaskName "AMNS Watchdog" | Select-Object LastTaskResult
```

`0` means it ran and found the platform healthy. `1` means it found a problem
and emailed. `2` means the watchdog itself could not run — usually the wrong
Python path, or SQLAlchemy missing for that interpreter.

**Test it properly once:** stop `AMNSMonitor`, wait ten minutes for
`[MONITORING DOWN]` to arrive, then start it again. An emergency alert nobody
has ever seen fire is a guess, not a safeguard.

## 9. Repoint the agents

Use the **hostname**, not the address:

```json
"api": "http://<platform-hostname>:5000/api"
```

If AD DNS registers the machine — check with `ping <hostname>` from another
server — the agents then follow it automatically if the address ever changes.
That single change ended five DHCP-related breakages in eight days.

On each monitored machine, edit `C:\ProgramData\AMNS-Agent\config.json`, then
restart the agent service. `server_id` and `token` stay as they are; only `api`
changes.

Agents below **v0.7.0** report no network, hardware, scheduled-task, container
or clock data. To update one: copy `agent-poc/agent.py` over the installed
`agent.py`, keep a copy of the old one, and restart the service. From v0.6.0
onward an agent re-reads its config every cycle, so a future address change
needs no restart at all.

## 10. Stop the old copies

On the laptop: stop and disable `AMNSMonitor` and `AMNSPlatform`, remove the
watchdog scheduled task, and close any `python run.py` windows. Two platforms
against two databases will disagree, and alert twice about everything.

---

## What does not come across

The new database starts empty apart from the seed accounts. The existing
history — incidents, health checks, configured servers and applications — stays
in the old `dev.db`.

Two options. Ask for a migration script, which is not difficult but is easy to
get subtly wrong. Or re-add the applications and re-enrol the agents by hand,
about twenty minutes, and accept that availability history starts fresh.

Doing it deliberately afterwards beats doing it as step 11 of a deployment.

---

## Afterwards

**Change the seed password** for `admin@example.com`.

**Back up the database.** There is currently no backup of anything. If you are on
SQL Server, a maintenance plan; if on SQLite, a scheduled copy of the file to
somewhere else. Then restore it once, to a different name, to prove the backup
works. An untested backup is a belief, not a backup.

**Serve over TLS.** The platform speaks plain HTTP and agents post their tokens
over it. On an internal network with a hostname, IIS as a reverse proxy with a
certificate is the usual route.

**Set the retention periods** in Settings — `retention_health_checks_days` and
the rest. They default to 90 days, 2 years, 1 year, with audit records kept
indefinitely, and nothing is deleted until a period elapses.

**Point the alerts where they belong** — `alert_cc_recipients`, `oncall_recipients`,
`digest_hour`, and the per-server *Alerts* column, which decides whether a
machine's problems reach everyone or only its owner.

**Set `slack_webhook_url`** if you want alerts in Teams or Slack. It is built and
waiting for a URL.
