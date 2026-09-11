"""Self-check for the crash-memory round trip. Run directly: python test_crash_report.py

The one thing a dead process cannot report about itself is why it died - the
whole point of report_crash/_consume_last_crash is that the NEXT run says it
instead. Reported once: a second read after the first must come back empty,
or a stuck marker would repeat a stale crash forever.
"""
import os
import tempfile

import agent


def main():
    config_path = os.path.join(tempfile.mkdtemp(), "config.json")

    assert agent._consume_last_crash(config_path) is None, "nothing written yet"

    agent.report_crash(config_path, RuntimeError("disk full"))
    first = agent._consume_last_crash(config_path)
    assert first is not None
    assert first["error"] == "disk full", first
    assert "at" in first

    second = agent._consume_last_crash(config_path)
    assert second is None, "must be consumed exactly once, not repeated"

    print("OK")


if __name__ == "__main__":
    main()
