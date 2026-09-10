Centralized Monitoring Agent
============================

To install on a machine
-----------------------
1. Copy this whole folder to the machine (USB, network share, anywhere).
2. Right-click Install.bat -> "Run as administrator".
3. Paste the admin token when asked.

That is all. The machine appears on the Servers page within a minute and
starts itself after every reboot.


Before sharing this folder
--------------------------
Open Install.bat and set PLATFORM (line 19) to wherever the platform runs:

    set "PLATFORM=AWGTC-PORTAL-QAS:5000"

Then nobody who runs it needs to know or type the address.


What gets installed
-------------------
C:\AMNSAgent                       the agent
C:\ProgramData\AMNS-Agent          this machine's id and token, readable
                                   only by Administrators and SYSTEM
Windows service "AMNSAgent"        automatic start, restarts itself on crash


What it collects
----------------
CPU, RAM, disk (space and throughput), network, uptime, temperature where
exposed; installed programs, services, processes, scheduled tasks, containers,
listening ports; device identity - name, serial, model, Device ID, Product ID;
which databases each program is connected to; and its own health.

What it does NOT do
-------------------
It never accepts commands, never opens an inbound port, never runs anything
sent to it, and never reads configuration files or credentials. It only makes
outbound calls to the platform. No inbound firewall rule is needed.

Removing it
-----------
    cd C:\AMNSAgent
    python agent_service.py stop
    python agent_service.py remove

Then delete the machine on the platform's Servers page.


Machines without Python
-----------------------
Most user PCs do not have Python. Download the official Windows installer
once from python.org, rename it to python-setup.exe, and put it in this
folder. Install.bat then installs Python silently before the agent, and
nobody has to do anything by hand.

    python-setup.exe        <- the python.org installer, renamed


Machines that cannot reach PyPI
-------------------------------
If a machine's proxy blocks the Python package index, pip will fail. Build
the packages ON A MACHINE RUNNING THE SAME PYTHON VERSION you are deploying,
and put the folder here:

    pip download -r requirements.txt -d wheels

Install.bat picks that folder up automatically. The version must match:
wheels built for Python 3.10 will not install on 3.13.


Requirements
------------
Windows, Python 3.10 or later with "Add python.exe to PATH" ticked, and
outbound network access to the platform's port.


Troubleshooting
---------------
"Python is not installed"        install it, tick Add to PATH, re-run
"pip install failed"             the machine cannot reach the package index
"Enrolment failed"               token expired (log in again for a fresh one)
                                 or this machine cannot reach the platform
"installed but is not running"   Event Log -> Application -> "AMNS Agent crashed"
