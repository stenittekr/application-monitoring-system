import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    # Defaults to localhost-only, same as always. Set HOST=0.0.0.0 explicitly
    # (e.g. when a real server needs to reach this platform for enrollment/
    # heartbeat testing) rather than making network exposure the default.
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=int(os.environ.get("PORT", 5000)), debug=debug)
