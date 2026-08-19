# Monitoring Agent

Collects CPU/RAM/disk/uptime and discovers services/ports on the machine it
runs on, then reports them to the Centralized Server & Application Monitoring Platform.

## Prerequisites

- Windows Server (tested on Windows 10/Server-class Windows; Linux not yet supported)
- Python 3.10+ installed on the target server
- Administrator rights **only for the one-time install step** (registering
  the Windows Service). The agent's own data collection does not need admin
  rights - proven separately in `poc_check.py`.
- Outbound network connectivity from this server to the central platform's
  address - see **Ports and firewall** below. No inbound port needs to be
  opened on this server at all.

## Ports and firewall

The agent only ever makes **outbound** connections - it initiates every
request itself, the central platform never connects into the server. No
inbound firewall rule is needed on the monitored server.

| Direction | Port | Purpose |
|---|---|---|
| Outbound | Whatever port the central platform's API is hosted on (dev: `5000`/HTTP, production: `443`/HTTPS) | Enrollment and every heartbeat |

If this server sits behind a corporate proxy, the proxy must allow outbound
HTTPS to the platform's address.

## 1. Install dependencies

```
pip install -r requirements.txt
```

## 2. Enroll the machine (once)

Get a JWT by logging into the platform as an ADMIN, then:

```
python agent.py enroll --admin-token <JWT> --api http://<server>:5000/api
```

This writes `C:\ProgramData\AMNS-Agent\config.json` (server id + secret
token, permissions locked to Administrators/SYSTEM/the account that ran this
command). You never need to touch this file again.

**Confirm it worked:** log into the dashboard's Servers page - the new
server should appear (status may show as UNKNOWN until the first heartbeat
arrives in step 3).

## 3. Run it

**Quick test in a terminal:**
```
python agent.py run
```
Ctrl+C to stop. It reads everything from the config file written in step 2.

**As a Windows Service (recommended for real servers)** — survives reboots,
runs with nobody logged in. Needs an elevated (Administrator) terminal:
```
python agent_service.py --startup auto install
python agent_service.py start
```
Check it's running: `sc query AMNSAgent`.

### Service account

By default, `pywin32` installs the service to run as **LocalSystem** - this
is what has been tested. LocalSystem has full local privileges but no
domain/network credentials, which is fine since the agent only reads local
system data and makes outbound HTTPS calls; it never touches network
shares or other servers.

If your security policy requires a dedicated low-privilege service account
instead of LocalSystem, `pywin32` supports installing under one via
`agent_service.py --username <domain\user> --password <pw> install` - this
has **not** been tested by us yet, so validate it during the pilot rather
than assuming it works identically.

## 4. Confirm it's actually working (validation checklist)

Run through these in order after installing:

- [ ] `sc query AMNSAgent` shows `RUNNING`
- [ ] `sc qc AMNSAgent` shows `START_TYPE : AUTO_START`
- [ ] The server appears on the platform's Servers page with status `UP`
      and a `Last Heartbeat` timestamp updating roughly every 60 seconds
- [ ] CPU/RAM/disk figures shown for the server look sane (not blank, not zero)
- [ ] The Discovered services/ports count is non-zero
- [ ] Stop the Windows service (`agent_service.py stop`) and confirm the
      server's status flips to `DOWN` on the dashboard within ~3 minutes,
      and a DOWN email is received
- [ ] Start the service again and confirm the status returns to `UP` and a
      RECOVERY email is received
- [ ] Reboot the server (coordinate the timing) and confirm the service
      auto-starts with nobody logged in, and heartbeats resume without
      manual intervention

## Uninstall / rollback

```
python agent_service.py stop
python agent_service.py remove
```
Then, optionally:
- Delete `C:\ProgramData\AMNS-Agent\` (removes the config file and the
  local heartbeat retry queue - no other trace is left on the server)
- On the platform side, an admin can soft-delete the server entry from the
  Servers page so it stops appearing in the dashboard

Nothing about this agent modifies the operating system, the registry (beyond
the service registration itself), or any other installed software - removal
is limited to the two steps above.

## Notes

- If the backend is briefly unreachable, failed heartbeats are queued
  locally (`C:\ProgramData\AMNS-Agent\heartbeat_queue.jsonl`, capped at 50
  entries / 24h) and retried automatically once it's back.
- One agent = one enrolled server. To monitor another machine, copy this
  folder there and repeat from step 1.
