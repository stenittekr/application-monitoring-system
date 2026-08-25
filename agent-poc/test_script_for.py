"""Self-check for _script_for: the interpreter-script extraction must never emit
inline code, which can carry credentials. Run: python test_script_for.py"""
import agent

CASES = [
    # (process name, argv tail, expected script)
    ("python.exe", [r"C:\apps\ps\app.py", "--port", "8080"], r"C:\apps\ps\app.py"),
    ("python.exe", ["-m", "flask", "run"], "flask"),
    ("python.exe", ["-u", r"C:\jobs\sync.py"], r"C:\jobs\sync.py"),
    # Inline code, in every spelling these interpreters actually use.
    ("python.exe", ["-c", "import os; print(os.environ['DB_PASSWORD'])"], "-c (inline code)"),
    ("node.exe", ["-e", "require('db').connect('secret')"], "-e (inline code)"),
    ("powershell.exe", ["-noexit", "-command", r'try { . "C:\x.ps1" }'], "-command (inline code)"),
    ("powershell.exe", ["-Command", "Get-Secret"], "-Command (inline code)"),
    ("powershell.exe", ["-EncodedCommand", "SQBuAHYA"], "-EncodedCommand (inline code)"),
    ("pwsh.exe", ["-comm", "Get-Secret"], "-comm (inline code)"),
    # -File takes a real script path, so it must NOT be suppressed.
    ("powershell.exe", ["-File", r"C:\ops\backup.ps1"], r"C:\ops\backup.ps1"),
    # Not an interpreter at all.
    ("svchost.exe", ["-k", "netsvcs"], None),
]


def main():
    for name, tail, expected in CASES:
        actual = agent._script_for({"name": name, "cmdline": [name] + tail})
        assert actual == expected, f"{name} {tail}: expected {expected!r}, got {actual!r}"
    for name, tail, _ in CASES:
        result = agent._script_for({"name": name, "cmdline": [name] + tail}) or ""
        assert "DB_PASSWORD" not in result and "Get-Secret" not in result, result
    print(f"OK - {len(CASES)} cases, no inline code emitted")


if __name__ == "__main__":
    main()
