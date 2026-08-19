"""Windows Service wrapper that serves the platform via waitress (a real
WSGI server) instead of Flask's development server, which explicitly warns
it isn't meant for production traffic. Requires pywin32 and waitress
(pip install -r requirements.txt) and an elevated terminal to install.

One-time setup:
    python platform_service.py --startup auto install
    python platform_service.py start

--startup auto sets the service's Windows startup type to Automatic, so it
comes back up after a reboot with nobody logging in - same as the agent.

To stop/uninstall:
    python platform_service.py stop
    python platform_service.py remove

Check status any time with: sc query AMNSPlatform
Reads HOST/PORT from the environment the same way run.py does (defaults:
0.0.0.0:5000 here, since a server hosting this for others necessarily needs
to accept connections from more than just itself).
"""
import os

import servicemanager
import win32service
import win32serviceutil
from waitress.server import create_server

from app import create_app


class PlatformService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AMNSPlatform"
    _svc_display_name_ = "Centralized Monitoring Platform"
    _svc_description_ = "Serves the Centralized Server & Application Monitoring Platform's web dashboard and API."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.server is not None:
            self.server.close()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                               (self._svc_name_, ""))
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", 5000))
        try:
            flask_app = create_app()
            self.server = create_server(flask_app, host=host, port=port)
            self.server.run()  # blocks until self.server.close() is called from SvcStop
        except Exception as exc:
            servicemanager.LogErrorMsg(f"Platform service crashed: {exc}")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PlatformService)
