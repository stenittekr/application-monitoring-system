# Moving the platform to AWGTC-PORTAL-QAS

Everything runs on your laptop today. That is the cause of the DHCP breakage,
the false weekend outages, and the SQLite locking. This moves it to a server
with a fixed address that stays on.

Run every command in an **elevated PowerShell on PS_QAS**, not on the laptop.
Run `hostname` first — it must print `AWGTC-PORTAL-QAS`.

In PowerShell, `sc` means `Set-Content`. Use `sc.exe` or `Restart-Service`.

---

## Before you start

| Check | Why |
|---|---|
| PS_QAS disk is at 82%, 36 GB free | The platform needs ~1 GB. Fine, but the disk itself needs attention separately. |
| SQL Server (`MSSQLSERVER`) is running there | Confirmed — it is one of the services we monitor. |
| Python is installed there | Confirmed — DMS, FeedBack and AWGTC-APP all run on it. |
| You are Administrator on PS_QAS | Confirmed by the `C:\Users\Administrator>` prompt. |

---

## 1. Copy the code

Put the whole repository at `C:\AMNS-Platform` on PS_QAS.

Not in a user profile and not in OneDrive: the services run as LocalSystem,
which often cannot read profile paths, and OneDrive sync corrupts database
files.

## 2. Create the database

```
cd C:\AMNS-Platform\scripts
.\setup_database.bat
```

At the prompts: instance `localhost`, login **blank** for Windows auth (you are
Administrator, so you are sysadmin locally).

This creates `ApplicationMonitoringDB` and runs all 16 migrations in order.
Re-running it is safe — every script guards its own changes.

## 3. Point the platform at SQL Server

Edit `C:\AMNS-Platform\backend\.env`:

```
SQL_SERVER=localhost
SQL_DATABASE=ApplicationMonitoringDB
SQL_USERNAME=
SQL_PASSWORD=
HOST=0.0.0.0
```

Leave `SQL_USERNAME` and `SQL_PASSWORD` empty to use Windows auth.

**Delete the `DATABASE_URL` line.** While it is present it overrides all of the
above and keeps you on SQLite.

Carry over from the laptop's `.env`: the SMTP settings, `SECRET_KEY`,
`JWT_SECRET_KEY`, the `DB_*` database passwords, and the LDAP settings.

## 4. Install the dependencies

```
cd C:\AMNS-Platform\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pywin32
.\.venv\Scripts\python.exe -m pywin32_postinstall -install
```

Machine-wide, never `--user`: a user-scope install is invisible to LocalSystem
and the services will fail to start.

## 5. Check it before installing anything as a service

```
cd C:\AMNS-Platform\backend
.\.venv\Scripts\python.exe -c "from app import create_app; create_app(); print('config OK')"
.\.venv\Scripts\python.exe -m pytest tests -q
```

100 tests should pass. If the database connection is wrong you will see it here,
not at 3am.

## 6. Install the two services

```
cd C:\AMNS-Platform\backend
.\.venv\Scripts\python.exe platform_service.py --startup auto install
Start-Service AMNSPlatform

cd C:\AMNS-Platform\monitoring
..\backend\.venv\Scripts\python.exe monitor_service.py --startup auto install
Start-Service AMNSMonitor
```

`--startup auto` is what makes them return after a reboot.

Confirm it is listening on the network, not just locally:

```
netstat -ano | findstr ":5000"
```

Must show `0.0.0.0:5000`. If it shows `127.0.0.1:5000`, `HOST` did not take.

## 7. Open the firewall

```
New-NetFirewallRule -DisplayName "AMNS Platform API" -Direction Inbound `
    -Protocol TCP -LocalPort 5000 -Action Allow
```

## 8. Repoint the agents

The platform is now at `http://172.50.35.75:5000`.

**On PS_QAS**, edit `C:\ProgramData\AMNS-Agent\config.json`:

```
"api": "http://172.50.35.75:5000/api"
```

**On the laptop**, edit the same file, then restart
`Centralized Monitoring Agent` in Services on each machine.

`server_id` and `token` stay as they are. Only `api` changes.

## 9. Stop the laptop copies

On the **laptop**: stop `AMNSMonitor`, and close the `python run.py` windows —
there are several. Two platforms writing to two databases will disagree and
alert twice.

---

## What does not come across

The new database starts empty apart from the seed accounts. Your existing
history — 31 incidents, health checks, the servers and applications you have
configured — stays in `dev.db` on the laptop.

If you want that history moved, say so and I will write the migration script.
It is not difficult, but it is easy to get subtly wrong, and it is better done
deliberately than as step 10 of a deployment.

Simplest alternative: re-add the seven applications and two database checks by
hand, re-enrol the two agents, and accept starting availability history fresh.
About twenty minutes.

## Afterwards

- Change the seed password for `admin@example.com`.
- Ask for a DHCP reservation for the laptop anyway — the agent on it still
  points at an address that can move.
- Set up a SQL Server backup job for `ApplicationMonitoringDB`. There is
  currently no backup of anything.
- The platform still serves plain HTTP. Putting it behind IIS with a
  certificate is the next security step.
