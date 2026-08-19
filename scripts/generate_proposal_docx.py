"""One-off generator for the Development Plan Word document (matches the
published artifact content). Not part of the running application - run once
to produce the .docx to attach/send."""
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ACCENT = RGBColor(0x2F, 0x6C, 0x4F)
MUTED = RGBColor(0x5B, 0x6B, 0x62)
WARN = RGBColor(0xA8, 0x3B, 0x34)

doc = Document()
doc.styles["Normal"].font.name = "Calibri"
doc.styles["Normal"].font.size = Pt(11)


def set_cell_shading(cell, color_hex):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color_hex)
    cell._tc.get_or_add_tcPr().append(shd)


def h1(text):
    p = doc.add_heading(text, level=1)
    p.runs[0].font.color.rgb = ACCENT


def h2(number, text):
    p = doc.add_paragraph()
    run = p.add_run(f"{number}  ")
    run.font.size = Pt(10)
    run.font.color.rgb = MUTED
    run.bold = True
    heading = doc.add_heading(text, level=2)
    heading.runs[0].font.color.rgb = RGBColor(0x14, 0x23, 0x1D)


def body(text):
    doc.add_paragraph(text)


def bullets(items):
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        hdr[i].paragraphs[0].runs[0].bold = True
        set_cell_shading(hdr[i], "E4EFE8")
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = val
    doc.add_paragraph()


def callout(title, text):
    p = doc.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    run.font.color.rgb = ACCENT
    p2 = doc.add_paragraph(text)
    p2.paragraph_format.left_indent = Inches(0.25)


# ---------------------------------------------------------------- title ----
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("Technical Proposal & Development Plan")
run.font.size = Pt(22)
run.bold = True
run.font.color.rgb = ACCENT

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run2 = subtitle.add_run("Centralized Server & Application Monitoring Platform")
run2.font.size = Pt(15)
run2.font.color.rgb = MUTED

lede = doc.add_paragraph()
lede.alignment = WD_ALIGN_PARAGRAPH.CENTER
run3 = lede.add_run(
    "Requirements, the stack chosen and why, how checks work without source code, "
    "scaling to many applications, the phase-by-phase approach, how the agent gets "
    "installed, and every access item needed to proceed."
)
run3.italic = True
run3.font.color.rgb = MUTED
doc.add_paragraph()

# --------------------------------------------------------------- 01 -------
h2("01", "Requirements")
body(
    "One live view of whether servers, services, and applications are actually "
    "working \u2014 not just running \u2014 via a central Main Monitoring Application "
    "and a lightweight Client Agent on every managed server. A failure at each of "
    "five layers means something different, so the platform must distinguish "
    "them rather than raise one generic alarm:"
)
bullets([
    "Server reachability \u2014 is anything home at all?",
    "Host health \u2014 reachable, but under pressure?",
    "Component health \u2014 is the required service/process/port present?",
    "Application health \u2014 running, but actually healthy?",
    "Business workflow \u2014 does it do its job end to end?",
])
body(
    "Two rules are non-negotiable: the central platform detects a missed heartbeat "
    "itself, never trusting a dead server to self-report; and the agent communicates "
    "outbound-only, buffering locally if the platform is briefly unreachable. Access "
    "is role-based across five roles \u2014 Platform Administrator, IT Manager, "
    "Application Owner (scoped to only their own applications), IT Support/Operator, "
    "and Auditor/Management."
)

# --------------------------------------------------------------- 02 -------
h2("02", "Technology stack")
body("Chosen for one developer to build, run, and maintain \u2014 not the trendiest option per layer.")
table(
    ["Layer", "Choice", "Why"],
    [
        ["Backend", "Python, Flask, SQLAlchemy", "Same code targets SQLite in dev and SQL Server in production."],
        ["Database", "SQL Server (prod) / SQLite (dev)", "SQL Server is the company standard; SQLite removes local-install friction."],
        ["Frontend", "Vanilla JS, Bootstrap", "No build pipeline or framework upgrade treadmill."],
        ["Agent", "Python, psutil, requests", "Reads CPU/RAM/disk/processes cross-platform without admin rights \u2014 confirmed, not assumed."],
        ["Agent lifecycle", "pywin32 Windows Service", "Real OS service, auto-starts on reboot, no one needs to stay logged in."],
        ["Auth", "JWT + LDAP/AD fallback", "Existing company AD logins work; local accounts as fallback."],
        ["Alerting", "SMTP email, Slack/Teams webhook", "Needs no vendor commitment yet."],
        ["Source control", "Git, GitHub (private)", "Real history, rollback-capable."],
    ],
)
body("React, Redis, Celery, Docker/Kubernetes deliberately left out for now \u2014 add only if scale genuinely demands it.")

# --------------------------------------------------------------- 03 -------
h2("03", "Checking an application without its source code")
body(
    "This is deliberate, not a limitation \u2014 it's called black-box monitoring: "
    "check what a system does from the outside, never how it does it internally. "
    "Almost nothing the platform checks needs source code."
)
callout(
    "Layers 1\u20134: no code, no business knowledge, ever",
    "Server, host, component, and application-level checks only need external facts "
    "\u2014 a hostname, a service/process name, a port number, a URL and what status "
    "code means \u201cup.\u201d None of that requires reading a single line of anyone's code.",
)
callout(
    "Layer 5 (business workflow): no code either, but needs a short description",
    "Example \u2014 a leave-application workflow: a dedicated test account submits a "
    "leave request marked clearly as a test (e.g. SYNTHETIC-CHECK-DO-NOT-ACTION), the "
    "check confirms it actually reaches \u201cPending Approval,\u201d a second test account "
    "can approve it, and the check confirms the status flips correctly \u2014 then the "
    "test request is deleted so no real balance or real manager is ever touched. The "
    "same pattern applies to any other workflow application: raise a test ticket in "
    "ITSM and confirm it queues correctly, update a test record in HRMS and confirm "
    "it saves, submit a test entry in Production System and confirm the expected "
    "status change happens.",
)
callout(
    "\u201cWhat other applications are actually running on a server?\u201d",
    "Honestly: not known in advance, and not guessed. That's exactly what discovery "
    "solves \u2014 the moment the agent runs on a real server, it automatically lists "
    "every running service and every open port on that machine, with zero prior "
    "knowledge needed. Proven on a laptop stand-in: 314 services and 136 ports found "
    "automatically in one cycle. Nothing on that list is monitored yet; an owner or "
    "admin reviews it afterward and decides what's worth watching.",
)

# --------------------------------------------------------------- 04 -------
h2("04", "Scaling to 20+ applications and multiple servers")
body(
    "Applications and servers are rows in a database, not hardcoded \u2014 going from "
    "7 to 20+ applications, or from 1 to 75 servers, is the same action repeated "
    "(\u201cadd a row, enroll it\u201d), not a redesign. The dashboard, incidents, alerts, "
    "RBAC, and reporting already work generically across however many rows exist."
)
table(
    ["Layer", "Handled how", "Scales how"],
    [
        ["Server / OS / host health", "One agent enrollment per server", "Each new server is one more enrollment, same steps as the first"],
        ["Service", "Discovery, automatic once the agent is installed", "Comes free with the server enrollment, no extra work"],
        ["Application", "HTTP/HTTPS/TCP check config per app", "Each new app is one more form, same as the existing 7"],
        ["Database", "Read-only credentials per app", "Each new app's DB is one more set of credentials"],
    ],
)
body("All of it lands on the same dashboard, the same Incidents list, the same alert pipeline \u2014 whether it's 7 applications or 27.")
callout(
    "Two honest caveats, not blockers",
    "This is proportional work, not zero work: 20+ applications means 20+ owners "
    "providing their app's URL/DB details/workflow description \u2014 exactly why the "
    "Application Owner role and the \u201cInformation Required\u201d workflow exist. And "
    "application-to-server mapping isn't built yet: today an application and a "
    "server are monitored side by side without the platform formally knowing which "
    "app runs on which server \u2014 real, doable work, on the Phase 2 list.",
)

# --------------------------------------------------------------- 05 -------
h2("05", "Approach, phase by phase")
body("Five phases, each a complete, demonstrable increment on its own.")

phases = [
    ("Phase 0", "Discovery & proof of concept", [
        "Validate low-privilege data collection is technically viable",
        "Establish agent-enrollment and heartbeat protocol on one real server",
        "Confirm the alerting pipeline end to end",
    ]),
    ("Phase 1", "MVP", [
        "Agent enrollment, heartbeat, auto-start after reboot",
        "Host metrics, service/port discovery, HTTP/HTTPS/TCP application checks",
        "Incident detection, email alerting, 5-role access, dashboard, audit trail",
        "Named pilot group of 3\u20135 real servers, not the full fleet",
    ]),
    ("Phase 2", "Application intelligence", [
        "Full application profiles: ownership, dependencies, thresholds",
        "Database/file/scheduled-task/log/certificate checks",
        "\u201cInformation Required\u201d review workflow; maintenance windows for servers too",
    ]),
    ("Phase 3", "Enterprise capabilities", [
        "Linux/container support, once a real Linux server is in scope",
        "Native Teams/Slack/SMS, SSO if required, high availability",
        "Fleet-wide agent updates, capacity forecasting",
    ]),
    ("Phase 4", "Controlled automation", [
        "Only after governance sign-off \u2014 a different risk category from watching/alerting",
        "Pre-approved remediation actions only; synthetic workflow checks; anomaly detection",
    ]),
]
for label, name, items in phases:
    p = doc.add_paragraph()
    run = p.add_run(f"{label} \u2014 {name}")
    run.bold = True
    run.font.color.rgb = ACCENT
    bullets(items)

# --------------------------------------------------------------- 06 -------
h2("06", "How the agent gets installed on a server")
steps = [
    "Get remote admin access to the box (this is the current blocker \u2014 see Section 08).",
    "Copy the agent folder over and run pip install -r requirements.txt \u2014 Python plus a few small libraries, no heavy install.",
    "Log into the dashboard as an Admin, get a token, run agent.py enroll once \u2014 this registers the server and writes a locked-down config file. No secret is ever copy-pasted by hand.",
    "Install it as a real Windows Service (agent_service.py install, then start). From here it survives reboots on its own.",
    "Check the Servers page in the dashboard \u2014 it should appear live within a minute.",
]
for i, s in enumerate(steps, 1):
    doc.add_paragraph(f"{i}. {s}")
body("Already built and proven end to end on a laptop stand-in. The only missing piece is a real server to run Step 1 on.")

# --------------------------------------------------------------- 07 -------
h2("07", "Servers known today")
table(
    ["Server", "Status"],
    [
        ["AWGTC-PORTAL-QAS (172.50.35.75)", "Identified \u2014 network & WinRM confirmed reachable; account not yet authorized"],
        ["Laptop stand-in (proof-of-concept only)", "Enrolled & live \u2014 not production infrastructure"],
        ["Remaining pilot servers (3\u20135 total expected)", "Not yet named \u2014 awaiting confirmation"],
        ["Full ~75-server fleet", "Not yet scoped \u2014 Phase 3, after the pilot"],
    ],
)
body("No other server names are assumed or guessed anywhere in this plan.")

# --------------------------------------------------------------- 08 -------
h2("08", "Access required")

p = doc.add_paragraph()
run = p.add_run("Remote administration access to pilot servers \u2014 BLOCKING")
run.bold = True
run.font.color.rgb = WARN
body(
    "Approved WinRM (Windows) or SSH (Linux) access to a named pilot list of 3\u20135 "
    "real servers, with rights to install and run the agent as a service. This is "
    "the same account that needs host-level rights \u2014 nothing additional beyond it."
)
p2 = doc.add_paragraph()
run2 = p2.add_run("Without this, the following cannot be validated at all:")
run2.bold = True
bullets([
    "Real network conditions \u2014 latency, intermittent connectivity, firewall/proxy behavior",
    "The agent actually installing and auto-starting as a service on infrastructure we don't control",
    "Real service/port inventories at production scale, and discovery of other applications actually running there",
    "Whether the least-privilege account model holds up against real corporate AD/GPO policy",
    "True heartbeat-loss and recovery behavior under a real reboot/patch cycle",
])
body("Everything proven so far is proven on one personal laptop. Phase 1 cannot be called complete without this.")

for title_text, desc in [
    ("Read-only database credentials, per application",
     "A login for each monitored application's own database, with rights to run one simple, safe read-only query \u2014 not admin rights, not write access. Needed for the database health check type: confirms the database is actually reachable, not just that the application's web page loads."),
    ("Production database for the platform itself",
     "SQL Server vs. PostgreSQL decision, plus an instance with table-creation rights. Separate from the item above \u2014 this is the database the monitoring platform stores its own data in, not the databases being monitored."),
    ("Production SMTP relay",
     "Credentials for the mail relay real alerts should send through."),
    ("Critical application list and owners",
     "The authoritative list of business-critical applications, owners, and criticality \u2014 and, per Section 03, a short description of each one's key workflow if a synthetic check is wanted for it."),
    ("Alerting, escalation, and security confirmations",
     "Teams/SMS/ITSM channels beyond email; existing on-call rotation; SSO/MFA requirement; code-signing and pentest arrangements before wider rollout."),
]:
    p = doc.add_paragraph()
    run = p.add_run(title_text)
    run.bold = True
    body(desc)

doc.add_paragraph()
footer = doc.add_paragraph()
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = footer.add_run("Technical Proposal & Development Plan \u00b7 Centralized Server & Application Monitoring Platform")
run.font.size = Pt(9)
run.font.color.rgb = MUTED

out_path = r"C:\Users\stenitte\OneDrive - AWGTC\Desktop\Monitoring_Platform_Development_Plan.docx"
doc.save(out_path)
print("Saved:", out_path)
