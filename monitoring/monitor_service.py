"""Windows Service wrapper around monitor.py's scheduling loop, so the
monitoring worker survives reboots and this laptop sleeping/closing the same
way the agent's service already does. Requires pywin32 (see agent-poc's
README for the elevated-install gotcha - the same trap applies here) and an
elevated terminal to install.

One-time setup:
    python monitor_service.py --startup auto install
    python monitor_service.py start

To stop/uninstall:
    python monitor_service.py stop
    python monitor_service.py remove

Check status any time with: sc query AMNSMonitor
"""
import sys
from pathlib import Path

import servicemanager
import win32service
import win32serviceutil

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(REPO_ROOT))


class MonitorService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AMNSMonitor"
    _svc_display_name_ = "Centralized Monitoring Worker"
    _svc_description_ = "Periodically checks applications and servers for the Centralized Server & Application Monitoring Platform."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.scheduler = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                               (self._svc_name_, ""))
        try:
            from monitor import _setup_logging
            from app import create_app
            from monitoring.scheduler import build_scheduler
            from monitoring.health_checker import run_monitoring_cycle

            _setup_logging()
            flask_app = create_app()
            with flask_app.app_context():
                run_monitoring_cycle()

            self.scheduler = build_scheduler(flask_app)
            # BlockingScheduler.start() blocks this thread until shutdown() is
            # called from SvcStop (which runs on the SCM's own control thread).
            self.scheduler.start()
        except Exception as exc:
            servicemanager.LogErrorMsg(f"Monitor service crashed: {exc}")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(MonitorService)
