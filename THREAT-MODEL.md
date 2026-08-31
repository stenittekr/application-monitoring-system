# Threat model

**Centralized Server & Application Monitoring Platform**
Requirements v1.0 · §18 Security Controls · §21 acceptance criterion 10 · §23 item 20

Written 31 August 2026 against the platform as it stands, not as it is intended
to be. Where a control is missing it says so, and where something has already
gone wrong it says that too — a threat model that only lists the defences is a
brochure.

---

## 1. What this system is, from an attacker's point of view

A monitoring platform is an unusually attractive target, and not for its own
data.

It holds **credentials to other systems** — database logins, an LDAP bind
account, SMTP credentials, and test accounts for synthetic workflows. It holds
**a map of the estate**: every server, every service, every listening port,
every installed program, and which applications matter. And it holds **an agent
running as LocalSystem on every monitored machine**, which is the most valuable
thing in the building if you can make it run your code.

Nobody attacks a monitoring platform for its uptime graphs.

---

## 2. Assets, in order of what their loss would cost

| Asset | Where it lives | Loss means |
|---|---|---|
| Database credentials | `backend/.env`, expanded at check time | Direct access to production databases |
| Agent tokens | `servers.token_hash` (SHA-256); plaintext in each agent's `config.json` | Impersonate a server, or feed false health data |
| LDAP bind credentials | `.env` | Directory reconnaissance; possibly worse |
| SMTP credentials | `.env` or `system_settings` | Send mail as the organisation |
| Synthetic workflow accounts | `.env` as `${VAR}` references | Whatever that account can do in the target application |
| Estate inventory | Database | A map for planning a real attack |
| The agent itself | LocalSystem on every monitored server | Arbitrary code on every server at once |
| Incident and audit history | Database | Cover tracks; dispute what happened |

---

## 3. Trust boundaries

```
   Browser ──HTTP──▶ Platform ──▶ SQLite / SQL Server
                        │
                        ├──HTTP──▶ monitored applications, databases
                        ├──LDAPS─▶ Active Directory
                        └──SMTP──▶ Office 365
                        ▲
                        │ HTTP, agent-initiated outbound
                 Agents (LocalSystem, one per server)
```

Four boundaries matter: **browser → platform**, **agent → platform**,
**platform → monitored systems**, and **repository → the world**.

The last one is not in the requirements' diagram and should be. It is the
boundary this project has already lost twice.

---

## 4. Threats, controls, and what is missing

### 4.1 Browser → platform

| Threat | Control | Status |
|---|---|---|
| Credential theft in transit | — | **Missing. Plain HTTP.** Passwords and JWTs cross the network in clear text. |
| Weak password storage | bcrypt | In place |
| Session theft | JWT in `Authorization` header, 8-hour expiry | In place, but 8 hours is generous over plain HTTP |
| Brute force | flask-limiter, 200 requests/minute per IP | In place, though shared with normal traffic |
| Privilege escalation | `@roles_required` on every route, five roles | In place |
| Cross-origin abuse | `CORS_ORIGINS` defaults to `*` | **Weak.** Fine on an internal network with no browser-based attacker; not fine once exposed |
| MFA / SSO | — | Missing. AD authentication only |

**Highest risk here: no TLS.** Everything else on this row is undermined by it.
Anyone able to observe the internal network sees an administrator's password
the next time one is typed.

### 4.2 Agent → platform

| Threat | Control | Status |
|---|---|---|
| Forged heartbeats | Per-agent token, SHA-256 hashed at rest | In place |
| Token theft from a compromised server | `config.json` locked to Administrators/SYSTEM | Partial — a local administrator can read it |
| Token replay from elsewhere | — | **Missing.** A stolen token works from any address |
| Cloned identity | — | **Missing.** §18 asks for duplicate-identity detection |
| Revocation | Re-enrolment rotates the token | Partial — no way to revoke without re-enrolling |
| Malicious payload from an agent | Field whitelist on ingest; no eval anywhere | In place |
| Denial of service by volume | Rate limit; payload caps (150 processes, 60 tasks) | In place |

**Deliberate design strength:** communication is agent-initiated outbound only.
The platform cannot reach into a monitored server, so compromising the platform
does not immediately yield code execution on the estate. This is the single most
valuable security property the system has, and **FR-020's signed agent updates
would trade it away if implemented carelessly** — an update channel is precisely
a way to run code on every server.

### 4.3 Platform → monitored systems

| Threat | Control | Status |
|---|---|---|
| Credentials in profile text | Validation rejects literals; `${ENV_VAR}` only | In place |
| Credentials in logs, emails, webhooks | `redaction.py`, applied at storage, send and log | In place |
| Credentials in error messages | Driver errors redacted with the expanded password | In place |
| Over-privileged check accounts | — | **Weak.** One check used `sa`. A `SELECT 1` needs no such thing |
| Secrets at rest | `.env` file, plain text, filesystem ACLs only | **Missing.** §18 asks for a vault |
| Arbitrary command execution | Only allow-listed check types; no eval, no shell | In place |
| Synthetic workflow abuse | Declarative steps only; no scripting; login rate-limit awareness | In place |

### 4.4 Repository → the world

| Threat | Control | Status |
|---|---|---|
| Secrets committed | `.env` gitignored | In place |
| Secrets in code or tests | Review | **Failed twice.** See §5 |
| Database committed | `dev.db*` gitignored | In place, after an earlier failure |
| Dependency vulnerabilities | `pip-audit` | In place as of 31 August; 12 CVEs closed |

---

## 5. Incidents that have already happened

A threat model written as if nothing has gone wrong is worth very little. These
are real, from this project, in the last three weeks.

**Production passwords in source.** The `awgtcps` and `sap` database passwords
were used as worked examples in a docstring explaining URL parsing, and again as
test fixtures — in the module whose purpose is redacting exactly those values,
and in the tests proving that it works. Committed and pushed. The repository is
private, which limits but does not remove the exposure. **These need rotating.**

**An agent token in a test fixture.** PS_QAS's real token, committed the same
way. **Needs rotating.**

**Personal data in the repository.** Two people's email addresses were kept in a
hard-coded block list so they could not be re-added to alerts. Holding someone's
address in source to remember not to contact them is still holding their
address. Removed from code, tests, migrations, settings, database and history.

**The SQLite database in a synced folder.** `dev.db` lives inside OneDrive.
Every incident, every credential-bearing connection string, every audit record
has been replicated to cloud storage as a side effect of where the folder is.

**A benchmark that reached production data.** A load test wrote a thousand
fabricated servers into the live database because setting `DATABASE_URL` from
inside the process does not rebind an already-created engine. It now verifies
the bound engine and refuses.

The pattern in four of these five is the same: **the secret was never in the
file meant to hold secrets. It was in the files meant to be shared.**

---

## 6. Attack scenarios worth defending against

**A malicious insider with network access.** Today: sniff plain HTTP, capture an
admin JWT or password, log in, read every connection string in the applications
list. *Mitigation: TLS, then shorter token lifetime.*

**A compromised monitored server.** Today: read `config.json` as local
administrator, take the agent token, submit false health data from anywhere so
a real outage is reported healthy. *Mitigation: token binding to source address,
plus duplicate-identity detection.*

**Someone with repository access.** Today: read production database passwords
from git history. *Mitigation: rotate; scan on every commit.*

**The monitoring platform itself compromised.** Today: the attacker gains the
credentials in `.env` and the estate map, but not code execution on monitored
servers — agents only ever call outward. *Mitigation: keep it that way. A signed
update channel must be signed, or not built.*

**Loss of the platform's host.** Today: total loss of monitoring history. No
backup exists. *Mitigation: backups, tested by restoring.*

---

## 7. What to fix, in order

| | Fix | Cost | Why this order |
|---|---|---|---|
| 1 | **Rotate the three exposed credentials** | Hours | They are already exposed; nothing else matters until they are not |
| 2 | **Move off the laptop** | A day | Unblocks 3, 4 and 5, and removes the OneDrive exposure |
| 3 | **TLS in transit** | Hours after 2 | Undermines almost every other browser-side control while missing |
| 4 | **Backups, with a tested restore** | Hours after 2 | Currently no recovery from any failure |
| 5 | **Restrict `CORS_ORIGINS`** | Minutes | Trivial once there is a fixed hostname |
| 6 | **Least-privilege check accounts** | Hours | A connectivity check needs `CONNECT`, nothing more |
| 7 | **Dependency scan in CI** | Hours | Already proven to find real issues; make it automatic |
| 8 | **Secrets vault** | Days | Replaces `.env`; worth doing once the platform is stable |
| 9 | **Agent revocation and clone detection** | Days | §18 asks for both; matters more as the estate grows |
| 10 | **Penetration test** | £3–8k | Do it once 1–5 are done, or you pay someone to find them |

---

## 8. What this model does not cover

The monitored applications themselves. The network. Physical access. The
Active Directory it authenticates against. Those have their own owners, and a
monitoring platform's threat model that claims to cover them is overreaching.

It also does not cover a formal penetration test's findings, because one has not
been done. Everything above is reasoning about the design; a test is evidence
about the implementation, and the two are not substitutes.
