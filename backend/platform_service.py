"""Windows Service wrapper that serves the platform via cheroot (a real WSGI
server) instead of Flask's development server, which explicitly warns it
isn't meant for production traffic. Requires pywin32 and cheroot
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

TLS: on by default. Remote-support sessions (screen + input) must not cross
the network in plaintext, so this refuses to fall back to HTTP silently -
either point TLS_CERT_FILE/TLS_KEY_FILE at a real certificate (an internal
CA-issued one for production; certs/cert.pem + certs/key.pem, generated
alongside this file, is a self-signed one to get started with - browsers
will warn until it is replaced) or set ALLOW_PLAINTEXT=1 to explicitly
accept running without encryption.
"""
import os

import servicemanager
import win32service
import win32serviceutil
from cheroot.wsgi import Server
from cheroot.ssl.builtin import BuiltinSSLAdapter

from app import create_app

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CERT = os.path.join(_HERE, "certs", "cert.pem")
_DEFAULT_KEY = os.path.join(_HERE, "certs", "key.pem")


def _build_server(flask_app, host, port):
    """Builds the cheroot server, TLS-enabled unless explicitly opted out."""
    server = Server((host, port), flask_app, numthreads=16)

    cert = os.environ.get("TLS_CERT_FILE", _DEFAULT_CERT)
    key = os.environ.get("TLS_KEY_FILE", _DEFAULT_KEY)
    if os.path.exists(cert) and os.path.exists(key):
        server.ssl_adapter = BuiltinSSLAdapter(cert, key)
        return server, True

    if os.environ.get("ALLOW_PLAINTEXT") == "1":
        return server, False

    raise RuntimeError(
        f"No TLS certificate found ({cert}, {key}). Remote-support sessions must not run "
        "over plaintext HTTP. Generate/point TLS_CERT_FILE and TLS_KEY_FILE at a real "
        "certificate, or set ALLOW_PLAINTEXT=1 to run without encryption anyway.")


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
            self.server.stop()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                               (self._svc_name_, ""))
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", 5000))
        try:
            flask_app = create_app()
            self.server, tls = _build_server(flask_app, host, port)
            if not tls:
                servicemanager.LogMsg(servicemanager.EVENTLOG_WARNING_TYPE, servicemanager.PYS_SERVICE_STARTED,
                                       (self._svc_name_, " running WITHOUT TLS (ALLOW_PLAINTEXT=1)"))
            self.server.start()  # blocks until self.server.stop() is called from SvcStop
        except Exception as exc:
            servicemanager.LogErrorMsg(f"Platform service crashed: {exc}")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PlatformService)
