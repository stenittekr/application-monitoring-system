"""One-off generator for the Platform Deployment Guide - the main web
application/API, not the monitoring agent (see generate_handoff_docx.py for
that one). Not part of the running application."""
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


def warn_note(text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.color.rgb = WARN


# ---------------------------------------------------------------- title ----
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("Platform Deployment Guide")
run.font.size = Pt(22)
run.bold = True
run.font.color.rgb = ACCENT

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run2 = subtitle.add_run("Centralized Server & Application Monitoring Platform \u2014 Main Application")
run2.font.size = Pt(14)
run2.font.color.rgb = MUTED

lede = doc.add_paragraph()
lede.alignment = WD_ALIGN_PARAGRAPH.CENTER
run3 = lede.add_run(
    "This deploys the central web dashboard and API itself \u2014 a different, larger "
    "piece than the client agent covered in the Pilot Installation & Handoff Guide. "
    "Same process: Stenitte prepares and tests, the System Administrator installs "
    "on the approved server."
)
run3.italic = True
run3.font.color.rgb = MUTED
doc.add_paragraph()

# ------------------------------------------------------------- overview ----
h2("0", "Overview")
body(
    "The platform is a Python web application (Flask) with a browser-based dashboard. "
    "It needs to run continuously on a server that other machines (monitored servers, "
    "and anyone's browser) can reach \u2014 this is the one meaningful difference from the "
    "agent: the agent only ever calls out, but this application must accept incoming "
    "connections."
)
table(
    ["Item", "Value"],
    [
        ["What gets installed", "The web application, running as a Windows Service (\u201cAMNSPlatform\u201d)"],
        ["Database for this deployment", "SQLite (a local file) \u2014 the simplest path to get a real, reachable URL live now. Migrating to SQL Server/PostgreSQL later does not require reinstalling anything; only the database connection setting changes"],
        ["Who installs it", "The System Administrator"],
        ["Who supports/tests", "Stenitte K R"],
    ],
)

# ------------------------------------------------------- 1 prerequisites ---
h2("1", "Software prerequisites and dependencies")
bullets([
    "Windows Server, Python 3.10 or newer",
    "All packages in backend/requirements.txt (installed via a single pip command) \u2014 "
    "including waitress (a production-grade WSGI server) and pywin32 for the Windows Service",
    "Administrator rights, needed only once, to register the Windows Service",
])

# ------------------------------------------------------- 2 ports/firewall --
h2("2", "Required ports and firewall rules")
warn_note("Unlike the agent, this application needs an INBOUND port opened.")
body(
    "Anyone reaching the dashboard, and every monitored server's agent sending a "
    "heartbeat, connects INTO this server. An inbound firewall rule is required."
)
table(
    ["Direction", "Port", "Purpose"],
    [["Inbound", "5000 (or 443 once HTTPS/a reverse proxy is set up)", "Dashboard access and all agent/API traffic"]],
)
body(
    "For this initial deployment, plain HTTP on port 5000 is acceptable to get a live "
    "URL working. Before this carries real credentials/production traffic long-term, "
    "HTTPS should be added (a certificate plus a reverse proxy such as IIS or a "
    "dedicated TLS-terminating layer) \u2014 out of scope for this first deployment."
)

# ------------------------------------------------------- 3 install steps ---
h2("3", "Step-by-step installation and configuration instructions")
numbered([
    "Copy the provided application folder onto the server (e.g. C:\\Monitoring\\platform), "
    "or git clone the repository if this server has access to it.",
    "Open an elevated (Administrator) PowerShell in the backend/ folder.",
    "Install dependencies: pip install -r requirements.txt",
    "Copy .env.example to .env and fill in production values (Section 6).",
    "Install as a Windows Service: python platform_service.py --startup auto install",
    "Start the service: python platform_service.py start",
    "Confirm it's running: sc query AMNSPlatform should show RUNNING",
    "From another machine on the network, browse to http://<this-server's-address>:5000 "
    "and confirm the login page loads.",
])

# ------------------------------------------------------- 4 service details -
h2("4", "Windows Service installation details")
table(
    ["Property", "Value"],
    [
        ["Service name", "AMNSPlatform"],
        ["Display name", "Centralized Monitoring Platform"],
        ["Startup type", "Automatic (survives reboot)"],
        ["Install command", "python platform_service.py --startup auto install"],
        ["Start/stop commands", "python platform_service.py start / stop"],
        ["Uninstall command", "python platform_service.py remove (after stopping it)"],
        ["Serves via", "waitress (a real WSGI server) \u2014 not Flask's development server, which is not meant for production traffic"],
    ],
)

# ------------------------------------------------------- 5 account perms ---
h2("5", "Required service account permissions")
body(
    "By default the service runs as LocalSystem, matching the agent's tested "
    "configuration. It needs read/write access to its own application folder "
    "(for the SQLite database file and log files) \u2014 LocalSystem already has this "
    "on a standard install. No domain or network credentials are required."
)

# ------------------------------------------------------- 6 environment -----
h2("6", "Environment configuration (.env)")
body("Copy backend/.env.example to backend/.env and set real values before starting the service:")
table(
    ["Setting", "Production guidance"],
    [
        ["SECRET_KEY / JWT_SECRET_KEY", "Generate long random values \u2014 do not use the development defaults"],
        ["DATABASE_URL", "Leave as the default SQLite path for this deployment, or point it at a specific file location if this server has a dedicated data drive"],
        ["SMTP_* settings", "Fill in once production mail relay credentials are confirmed (deferred item, Section 9)"],
        ["HOST", "0.0.0.0 (accept connections from other machines \u2014 required, not optional, for this to work as a central platform)"],
        ["PORT", "5000, or whichever port was agreed for this server"],
    ],
)

# ------------------------------------------------------- 7 the live url ----
h2("7", "Getting the real, reachable URL")
body(
    "Once the service is running and the firewall rule is in place, the platform is "
    "reachable at:"
)
code("http://<server-hostname-or-IP>:5000")
body(
    "Agents on other pilot servers should use this same address (instead of "
    "127.0.0.1) in their --api argument or enrollment step. A proper domain name and "
    "HTTPS can be layered on later without changing anything about this install."
)

# ------------------------------------------------------- 8 uninstall -------
h2("8", "Uninstallation and rollback procedure")
code("python platform_service.py stop\npython platform_service.py remove")
body(
    "Then, optionally, delete the application folder and its SQLite database file. "
    "This does not touch any other software on the server."
)

# ------------------------------------------------------- 9 validation ------
h2("9", "Testing and validation checklist")
checklist([
    "sc query AMNSPlatform shows RUNNING",
    "sc qc AMNSPlatform shows START_TYPE : AUTO_START",
    "The login page loads from another machine on the network, using the server's real address",
    "Logging in with a valid account succeeds and the dashboard loads",
    "An enrolled agent (pointed at this server's new address) shows up on the Servers page with a live heartbeat",
    "Restarting the server (coordinated timing) brings the service back up automatically, with the dashboard reachable again without manual intervention",
])

# ------------------------------------------------------- 10 later items ----
h2("10", "Items deferred to later (not needed for this first live deployment)")
bullets([
    "Migrating from SQLite to SQL Server/PostgreSQL, once that decision and access is finalized",
    "HTTPS via a certificate and reverse proxy",
    "Production SMTP relay configuration",
    "A proper domain name instead of a raw IP/hostname",
])

doc.add_paragraph()
footer = doc.add_paragraph()
footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = footer.add_run("Platform Deployment Guide \u00b7 Centralized Server & Application Monitoring Platform")
run.font.size = Pt(9)
run.font.color.rgb = MUTED

out_path = r"C:\Users\stenitte\OneDrive - AWGTC\Desktop\Platform_Deployment_Guide.docx"
doc.save(out_path)
print("Saved:", out_path)
