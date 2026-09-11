"""Self-check for command dispatch. Run directly: python test_agent_commands.py

The thing worth checking: _apply_command routes each action to exactly the
right handler, and a bad service name reports failure rather than raising -
one bad RESTART_SERVICE must not take the whole agent down.
"""
import subprocess

import agent


def test_dispatch():
    calls = []
    agent._restart_service = lambda name: calls.append(("restart_service", name))
    agent._upload_screenshot = lambda api, token, server_id: calls.append(("screenshot", server_id))

    agent._apply_command("http://x", "tok", 1, {"action": "SCREENSHOT"})
    agent._apply_command("http://x", "tok", 1, {"action": "RESTART_SERVICE", "service_name": "Spooler"})
    assert calls == [("screenshot", 1), ("restart_service", "Spooler")], calls

    # RESTART/UPDATE still end the loop - unlike the two above, which don't.
    try:
        agent._apply_command("http://x", "tok", 1, {"action": "RESTART"})
        assert False, "RESTART must raise RestartRequested"
    except agent.RestartRequested:
        pass


def test_restart_service_survives_a_subprocess_failure(real_restart_service):
    def _boom(*args, **kwargs):
        raise OSError("no such service")

    original_run = subprocess.run
    subprocess.run = _boom
    try:
        real_restart_service("NotAThing")  # must not raise
    finally:
        subprocess.run = original_run


def main():
    real_restart_service = agent._restart_service  # captured before test_dispatch stubs it
    test_dispatch()
    test_restart_service_survives_a_subprocess_failure(real_restart_service)
    print("OK")


if __name__ == "__main__":
    main()
