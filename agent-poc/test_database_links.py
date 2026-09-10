"""Self-check for database-link discovery. Run directly: python test_database_links.py

The retention is the part worth a test: a link observed once must survive later
samples that do not see it, because a request-scoped connection is open for
milliseconds and a heartbeat looks once a minute.
"""
import time
import types

import psutil

import agent


class _Addr(types.SimpleNamespace):
    pass


def _conn(pid, remote_port, remote_ip="10.0.0.5", local_port=51000):
    return types.SimpleNamespace(
        status="ESTABLISHED", pid=pid,
        laddr=_Addr(ip="127.0.0.1", port=local_port),
        raddr=_Addr(ip=remote_ip, port=remote_port))


def _with_connections(connections, names):
    psutil.net_connections = lambda kind="tcp": connections
    psutil.Process = lambda pid: types.SimpleNamespace(name=lambda: names.get(pid, "x.exe"))


def main():
    agent._database_link_history.clear()

    # A live connection to SQL Server is reported, with the engine named.
    _with_connections([_conn(4242, 1433), _conn(4242, 1433)], {4242: "python.exe"})
    links = agent._database_connections()
    assert len(links) == 1, links
    assert links[0]["engine"] == "SQL Server"
    assert links[0]["connections"] == 2, "sockets to one endpoint collapse to one row"
    assert links[0]["open_now"] is True
    assert links[0]["local_port"] != 1433, "local port is ephemeral, not the remote port"

    # Nothing open now: the link is remembered, and marked as not currently open.
    _with_connections([], {})
    links = agent._database_connections()
    assert len(links) == 1, "a link seen a minute ago is still a fact"
    assert links[0]["open_now"] is False

    # Ports nothing serves a database on are ignored.
    _with_connections([_conn(99, 8080)], {99: "chrome.exe"})
    assert all(l["pid"] != 99 for l in agent._database_connections())

    # Past the retention window it is forgotten rather than reported forever.
    for entry in agent._database_link_history.values():
        entry["last_seen"] = time.time() - agent.DATABASE_LINK_RETAIN_SECONDS - 1
    assert agent._database_connections() == []

    # A failure enumerating sockets must not lose what is already known.
    agent._database_link_history.clear()
    _with_connections([_conn(7, 3306)], {7: "python.exe"})
    agent._database_connections()
    psutil.net_connections = lambda kind="tcp": (_ for _ in ()).throw(OSError("denied"))
    links = agent._database_connections()
    assert len(links) == 1 and links[0]["engine"] == "MySQL/MariaDB"

    print("database link discovery: 6 checks passed")


if __name__ == "__main__":
    main()
