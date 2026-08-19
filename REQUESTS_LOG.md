# Requests Log — Centralized Server & Application Monitoring Platform

A record of what's been asked for across this project, organized by phase. Kept
as a reference for what was requested and why — not a design doc, not a status
report (see the published artifacts and `docs/` for those).

## Phase 1 — Existing app: verification, running, simplification

- Verify, run, and confirm the already-built app compiles and its full test suite passes
- Activate the venv and run the application
- Add 6 real AWGTC applications with real URLs: Leave Balance, Production System, Employee
  Count, Feedback, HRMS, then ITSM added separately
- Repeatedly trim the dashboard/table down: keep only application, environment, status,
  response time, last checked
- Remove and later reconsider: Activity Logs page, Reports page, Applications page,
  Maintenance Windows/Notification Settings (keep Settings to SMTP only)
- Fix a timestamp display bug (backend naive-datetime vs. JS timezone misread)
- Consolidate frontend + backend onto one port
- Rebrand the app to "Central Monitoring & Diagnostic Platform" (later renamed again —
  see Phase 5)
- Add TLS-verify toggle, maintenance windows, Slack/Teams webhook, dashboard auto-refresh,
  uptime reports
- Run a security audit against a pasted corporate security policy document and fix findings
  (password strength validation, login rate limiting)
- Add LDAP/AD authentication as a fallback alongside local accounts — explicitly no
  auto-provisioning or role-mapping from AD
- Manage user accounts: rename, delete, disable

## Phase 2 — Enterprise platform planning

- Reviewed a large requirements document ("Server and Application Monitoring Platform
  Requirements") sent by the manager, Ajoy M. Dsilva (Group IT Manager), for a much bigger
  Centralized Server and Application Monitoring Platform covering ~75 servers
- Explicit instruction: do not treat the document as a limitation — contribute technical
  ideas, recommend improvements, prepare a detailed technical proposal and development plan
- Clarified real-world constraints: solo full-stack developer, not a platform
  engineer/DevOps/DBA, limited infrastructure/admin access, wants a practical MVP without
  overengineering, wants plain-language explanations throughout ("make me understand each
  and everything")

## Phase 3 — Real implementation ("just do it")

- Explicit instruction to stop planning and start building — prove server heartbeat
  monitoring actually works, not just on paper
- Built and proved live: agent enrollment, heartbeat, server health monitoring,
  service/process/port discovery, connected to the existing alert pipeline
- Provided real AD credentials at one point to attempt connecting to a real pilot server
  (172.50.35.75) — later formally withdrawn (see Phase 6)
- Agent v0.2: packaged as a Windows Service (auto-start on reboot), config-file-based
  execution (no more secrets in CLI args/history), config file permissions locked down,
  local heartbeat retry/buffer queue for backend outages
- Added server restart detection (compares estimated boot time across heartbeats)
- Added incident acknowledge/assign/escalation workflow, with automatic one-time escalation
  email if unacknowledged past a configurable window
- Rebuilt RBAC from the original 3-role model (ADMIN/MANAGER/VIEWER) to the full 5-role
  model from the requirements document: Platform Administrator, IT Manager, Application
  Owner (scoped to only their own applications), IT Support/Operator, Auditor/Management
- Built the Reports and Activity Logs pages (previously backend-only, unreachable in the UI)
- Updated the SQL Server schema scripts (`database/*.sql`) to match everything added to the
  dev database, so a real SQL Server deployment isn't missing tables/columns
- Set up local git version control and pushed to a private GitHub repository
- Restyled the app's visual theme (pill buttons, richer gradient, matching accent tokens)
  to match a shared AWGTC portal theme from another internal tool, without adding a new
  frontend framework
- Built a TV/wallboard display mode (`wallboard.html`) — no sidebar, big stat tiles, an
  unmissable alert banner, auto-refreshing, ServiceNow-inspired clean layout
- Made the entire application responsive across phone/tablet/desktop/TV — added an
  off-canvas sidebar with a hamburger toggle for small screens, fixed the login page's
  edge-to-edge issue on narrow phones

## Phase 4 — Documentation and communication

- Repeated requests for plain-language, step-by-step summaries and explanations,
  "like a baby," of technical concepts (LDAP, the requirements document, JWT tokens,
  code-signing certificates, black-box monitoring, synthetic workflow checks)
- Draft and redraft an email response to the manager's requirements-review request,
  evolving through several iterations as the actual project situation changed
- Produced and published several reference documents as artifacts:
  - Monitoring Platform Blueprint (formal technical proposal)
  - Requirements Walkthrough (plain-language section-by-section explainer)
  - Monitoring Platform Playbook → later rewritten as the Development Plan
  - Platform Inventory (current-state snapshot)
  - Status & Access Brief (understanding, what's built, recommendations, access needed)
  - Monitoring Platform Development Plan (requirements, stack, black-box monitoring
    explanation, scaling to 20+ applications, phased approach, agent install steps,
    known servers, access required)
- Requested a single downloadable file (not just an artifact link) to actually send —
  produced `Monitoring_Platform_Development_Plan.docx`
- Feedback/comparison requested on an alternative AI-generated (BizChat) proposal
  recommending React/Postgres/Redis/Celery/Docker — explicit decision made to stay on
  Python + vanilla JavaScript only

## Phase 5 — Pilot rollout coordination

- Manager clarified the actual approved process: no direct remote server access for the
  developer — instead, fully test locally, then hand a complete installation package and
  documentation to the System Administrator (Shantharam Rajendran), who installs on the
  approved pilot server (`AWGTC-PORTAL-QAS`, `172.50.35.75`) with the developer supporting
  and testing alongside
- Produced `Pilot_Installation_Handoff_Guide.docx` covering the 9 specific items requested:
  prerequisites, ports/firewall, step-by-step install, Windows Service details, service
  account permissions, enrollment/connectivity procedure, uninstall/rollback, and a joint
  testing/validation checklist
- Produced `AMNSAgent_Install_Package.zip` — the actual installable code
- Created two dedicated local platform accounts (not real AD/LDAP credentials) so neither
  the developer nor the System Administrator has to use personal Windows passwords to
  generate an agent-enrollment token
- Fixed a real dependency bug found live during testing: `pywin32==306` isn't available for
  the newer Python version on the test laptop — relaxed to `pywin32>=306`
- Successfully enrolled a laptop as a live test server end to end
- Added a `HOST` environment variable to the backend so the platform can be made reachable
  from the network when needed (defaults to unchanged, localhost-only behavior)

## Phase 6 — Naming

- Renamed the application from "Central Monitoring & Diagnostic Platform" to
  "Centralized Server & Application Monitoring Platform" across every page title, the
  shared navigation shell, the Windows Service description, and supporting documents
