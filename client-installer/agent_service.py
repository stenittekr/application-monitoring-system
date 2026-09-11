"""Windows Service wrapper around agent.py's heartbeat loop, so the agent
survives reboots and runs with nobody logged in. Requires pywin32
(pip install pywin32) and an elevated (Administrator) terminal to install.

One-time setup on a machine that has already run `agent.py enroll`
(so C:\\ProgramData\\AMNS-Agent\\config.json exists):

    python agent_service.py --startup auto install
    python agent_service.py start

--startup auto sets the service's Windows startup type to Automatic, which
is what makes it come back up after a reboot with nobody logging in.

To stop watching logs / uninstall:
    python agent_service.py stop
    python agent_service.py remove

Check status any time with: sc query AMNSAgent
"""
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

import agent
import agent_config


class AgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AMNSAgent"
    _svc_display_name_ = "Centralized Monitoring Agent"
    _svc_description_ = "Sends heartbeat and system metrics to the Centralized Server & Application Monitoring Platform."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                               (self._svc_name_, ""))
        try:
            agent.run_from_config(agent_config.DEFAULT_CONFIG_PATH, stop_event=self.stop_event)
        except agent.RestartRequested as exc:
            # Not a crash - an admin asked for this (restart, or an update
            # that just wrote a new agent.py) from the dashboard. Still let
            # the process end abnormally: the service's own crash-recovery
            # (see Install.bat's `sc failure`) is what actually brings it
            # back up, this time running whatever agent.py now says.
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STOPPED,
                                   (self._svc_name_, f" restarting ({exc})"))
            raise
        except Exception as exc:
            servicemanager.LogErrorMsg(f"AMNS Agent crashed: {exc}")
            # So the reason shows up on the platform when this service restarts
            # itself, instead of only in this machine's own Event Viewer.
            agent.report_crash(agent_config.DEFAULT_CONFIG_PATH, exc)
            # Re-raised so the process actually ends abnormally: swallowing it
            # here made SvcDoRun return normally, which Windows reads as a
            # clean stop - the crash-recovery Install.bat configures only
            # fires on a failure, so a crash caught here never triggered it.
            raise


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(AgentService)
