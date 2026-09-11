"""Self-check for MAC address collection. Run directly: python test_network_mac.py

The thing worth checking: an interface with several address families (IPv4,
IPv6, link-layer) must report its AF_LINK entry as the MAC, not whichever
happened to be listed first.
"""
import socket
import types

import psutil

import agent


def _addr(family, address):
    return types.SimpleNamespace(family=family, address=address)


def main():
    psutil.net_if_stats = lambda: {
        "Ethernet": types.SimpleNamespace(isup=True, speed=1000),
        "NoMac": types.SimpleNamespace(isup=True, speed=100),
    }
    psutil.net_io_counters = lambda pernic: {}
    psutil.net_if_addrs = lambda: {
        "Ethernet": [
            _addr(socket.AF_INET, "192.168.1.10"),
            _addr(psutil.AF_LINK, "AA-BB-CC-DD-EE-FF"),
        ],
        "NoMac": [_addr(socket.AF_INET, "192.168.1.11")],
    }

    interfaces = {i["name"]: i for i in agent._network_counters()}
    assert interfaces["Ethernet"]["mac_address"] == "AA-BB-CC-DD-EE-FF"
    assert interfaces["NoMac"]["mac_address"] is None, "no AF_LINK entry means no MAC to report"

    print("OK")


if __name__ == "__main__":
    main()
