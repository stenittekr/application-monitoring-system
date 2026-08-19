"""One-off generator for the Pilot Installation & Handoff Guide, covering the
9 items Ajoy specified should be handed to the System Administrator before
pilot installation. Not part of the running application."""
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
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


def h2(number, text):
    heading = doc.add_heading(f"{number}. {text}", level=1)
    heading.runs[0].font.color.rgb = ACCENT


def body(text):
    doc.add_paragraph(text)


def bullets(items):
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def numbered(items):
    for item in items:
        doc.add_paragraph(item, style="List Number")


def checklist(items):
    for item in items:
        doc.add_paragraph(f"\u2610  {item}")


def code(text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(10)
    p.paragraph_format.left_indent = Pt(18)


def table(headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
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


# ---------------------------------------------------------------- title ----
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("Pilot Installation & Handoff Guide")
run.font.size = Pt(22)
run.bold = True
run.font.color.rgb = ACCENT

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run2 = subtitle.add_run("Centralized Server & Application Monitoring Platform \u2014 Pilot Server: AWGTC-PORTAL-QAS")
run2.font.size = Pt(14)
run2.font.color.rgb = MUTED

lede = doc.add_paragraph()
lede.alignment = WD_ALIGN_PARAGRAPH.CENTER
run3 = lede.add_run(
    "Prepared by Stenitte K R for Shantharam Rajendran (System Administrator), "
    "per the process confirmed by Ajoy M. Dsilva: the System Administrator installs "
    "and configures the agent on the approved pilot server; Stenitte provides this "
    "package and supports installation and testing throughout."
)
run3.italic = True
run3.font.color.rgb = MUTED
doc.add_paragraph()

# ------------------------------------------------------------- overview ----
h2("0", "Overview")
body(
    "The client agent is a small Python program that runs as a Windows Service on "
    "the monitored server. It reads CPU/RAM/disk/uptime, discovers running services "
    "and open ports, and reports all of this back to the central monitoring "
    "platform every 60 seconds. It never receives incoming connections from "
    "anywhere \u2014 it only ever calls out to the central platform."
)
table(
    ["Item", "Value"],
    [
        ["Pilot server", "AWGTC-PORTAL-QAS"],
        ["IP address", "172.50.35.75"],
        ["What gets installed", "One Python-based Windows Service (\u201cAMNSAgent\u201d)"],
        ["Who installs it", "Shantharam Rajendran (System Administrator)"],
        ["Who supports/tests", "Stenitte K R"],
    ],
)

# ------------------------------------------------------- 1 prerequisites ---
h2("1", "Software prerequisites and dependencies")
body("The target server needs:")
bullets([
    "Windows Server (this agent is Windows-only for now; Linux support is a later phase)",
    "Python 3.10 or newer installed",
    "The three Python packages listed in requirements.txt: psutil, requests, and pywin32 "
    "(installed via a single pip command, no manual downloads)",
    "Administrator rights, needed only once, to register the Windows Service",
])
body("No other software, no database driver, and no reboot is required to install these prerequisites.")

# ------------------------------------------------------- 2 ports/firewall --
h2("2", "Required ports and firewall rules")
body(
    "The agent only ever makes outbound connections \u2014 it calls the central "
    "platform, the central platform never calls it. No inbound firewall rule "
    "needs to be opened on AWGTC-PORTAL-QAS at all."
)
table(
    ["Direction", "Port", "Purpose"],
    [["Outbound only", "Whichever port hosts the central platform's API (production target: 443/HTTPS)", "Enrollment (once) and heartbeat (every 60s)"]],
)
body("If this server sits behind a proxy, the proxy needs to allow outbound HTTPS to the central platform's address.")

# ------------------------------------------------------- 3 install steps ---
h2("3", "Step-by-step installation and configuration instructions")
numbered([
    "Copy the provided agent-poc folder onto the server (any local path is fine, e.g. C:\\Monitoring\\agent).",
    "Open an elevated (Administrator) PowerShell or Command Prompt in that folder.",
    "Install dependencies: pip install -r requirements.txt",
    "Get a one-time enrollment token: Stenitte will supply an admin login token for the platform.",
    "Enroll this server (run once): python agent.py enroll --admin-token <token> --api <platform-url>",
    "Confirm enrollment: check the platform's Servers page \u2014 AWGTC-PORTAL-QAS should appear.",
    "Install as a Windows Service: python agent_service.py --startup auto install",
    "Start the service: python agent_service.py start",
    "Confirm it's running: sc query AMNSAgent should show RUNNING",
])
body("Full detail on each step, including exact commands, is in the accompanying agent-poc/README.md.")

# ------------------------------------------------------- 4 service details -
h2("4", "Windows Service installation details")
table(
    ["Property", "Value"],
    [
        ["Service name", "AMNSAgent"],
        ["Display name", "Centralized Monitoring Agent"],
        ["Startup type", "Automatic (survives reboot, starts before any user logs in)"],
        ["Install command", "python agent_service.py --startup auto install"],
        ["Start/stop commands", "python agent_service.py start / stop"],
        ["Uninstall command", "python agent_service.py remove (after stopping it)"],
    ],
)

# ------------------------------------------------------- 5 account perms ---
h2("5", "Required service account permissions")
body(
    "By default the service runs as LocalSystem \u2014 this is the configuration "
    "that has been tested. LocalSystem has full local privileges but no domain "
    "or network credentials, which is sufficient: the agent only reads local "
    "system data (CPU/RAM/disk/services/ports) and makes outbound HTTPS calls; "
    "it never accesses network shares, other servers, or domain resources."
)
body(
    "If your security policy requires a dedicated low-privilege service account "
    "instead of LocalSystem, pywin32 supports this via additional install "
    "flags \u2014 this specific configuration has not been tested yet, so it should "
    "be validated as part of this pilot rather than assumed to work identically."
)

# ------------------------------------------------------- 6 enrollment ------
h2("6", "Agent enrollment and connectivity procedure")
body(
    "Enrollment is a one-time handshake: the agent introduces itself to the "
    "platform once, and the platform issues it a unique, secret authentication "
    "token, stored locally in a locked-down config file "
    "(C:\\ProgramData\\AMNS-Agent\\config.json, readable only by Administrators, "
    "SYSTEM, and the account that ran the enrollment command)."
)
numbered([
    "Stenitte logs into the platform as an Administrator and generates a temporary enrollment token.",
    "Shantharam runs the enroll command with that token (Section 3, step 5).",
    "The platform registers the server and returns its own permanent secret \u2014 written automatically to the config file, never displayed or typed again.",
    "From then on, the running service reads that config file and sends a heartbeat every 60 seconds using that secret \u2014 no further manual steps.",
])

# ------------------------------------------------------- 7 uninstall -------
h2("7", "Uninstallation and rollback procedure")
code("python agent_service.py stop\npython agent_service.py remove")
body("Then, optionally, to remove all trace of the agent from the server:")
bullets([
    "Delete the C:\\ProgramData\\AMNS-Agent folder (removes the config file and local retry queue)",
    "An Administrator on the platform side can soft-delete the server's entry from the Servers page",
])
body(
    "The agent does not modify the operating system, install any drivers, or change "
    "any other software on the server \u2014 removal is limited to the two commands above."
)

# ------------------------------------------------------- 8 validation ------
h2("8", "Testing and validation checklist")
body("To be completed jointly by Stenitte and Shantharam after installation:")
checklist([
    "sc query AMNSAgent shows RUNNING",
    "sc qc AMNSAgent shows START_TYPE : AUTO_START",
    "AWGTC-PORTAL-QAS appears on the platform's Servers page with status UP",
    "Last Heartbeat timestamp updates roughly every 60 seconds",
    "CPU/RAM/disk figures shown look realistic (not blank or zero)",
    "Discovered services/ports count is non-zero",
    "Stopping the service flips the server's status to DOWN within ~3 minutes, and a DOWN email is received",
    "Starting the service again returns status to UP, and a RECOVERY email is received",
    "After a coordinated reboot, the service auto-starts with nobody logged in and heartbeats resume without manual action",
])

# ------------------------------------------------------- 9 later items -----
h2("9", "Items deferred to later phases (not needed for this pilot)")
body(
    "Per Ajoy's confirmation, these are reviewed and provided progressively and "
    "should not block this initial pilot installation:"
)
bullets([
    "Read-only database credentials for application-level database health checks",
    "Production SMTP relay configuration",
    "Confirmed critical-application list and owners",
    "Alerting channels beyond email (Teams/Slack/SMS/ITSM)",
    "SSO/MFA requirements",
    "Code-signing certificate and penetration test arrangements",
])

doc.add_paragraph()
footer = doc.add_paragraph()
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = footer.add_run("Pilot Installation & Handoff Guide \u00b7 Centralized Server & Application Monitoring Platform")
run.font.size = Pt(9)
run.font.color.rgb = MUTED

out_path = r"C:\Users\stenitte\OneDrive - AWGTC\Desktop\Pilot_Installation_Handoff_Guide.docx"
doc.save(out_path)
print("Saved:", out_path)
