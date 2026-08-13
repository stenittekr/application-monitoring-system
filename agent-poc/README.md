# Monitoring Agent

Collects CPU/RAM/disk/uptime and discovers services/ports on the machine it
runs on, then reports them to the Central Monitoring & Diagnostic Platform.

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
token, permissions locked to Administrators/SYSTEM). You never need to touch
this file again.

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
Check it's running: `sc query AMNSAgent`. Stop/remove with:
```
python agent_service.py stop
python agent_service.py remove
```

## Notes

- If the backend is briefly unreachable, failed heartbeats are queued
  locally (`C:\ProgramData\AMNS-Agent\heartbeat_queue.jsonl`, capped at 50
  entries / 24h) and retried automatically once it's back.
- One agent = one enrolled server. To monitor another machine, copy this
  folder there and repeat from step 1.
