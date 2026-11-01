#!/usr/bin/env python3
"""Push the QoS demo application tree to both endpoints.

Refuses to deploy if the lab static routes are missing, because that
misconfiguration produces a demo that looks healthy while never touching the
SR-MPLS core.
"""
import argparse
import os
import sys

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "/home/rocky/qos-e2e"

ENDPOINTS = {
    "Client1": {"host": "10.0.0.46", "data_ip": "10.50.1.10", "far_net": "10.50.2.0"},
    "Client2": {"host": "10.0.0.47", "data_ip": "10.50.2.10", "far_net": "10.50.1.0"},
}

TREE = [
    ("isr_apps", ["common.py", "c2_messaging.py", "track_feed.py",
                  "fmv_stream.py", "imagery_push.py", "wire_peek.py"]),
    ("console", ["console_core.py", "render_tui.py"]),
]


def connect(host):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="rocky", timeout=15)
    return c


def run(c, cmd):
    _, out, err = c.exec_command(cmd, timeout=30)
    return (out.read().decode() + err.read().decode()).strip()


def preflight(c, spec):
    """Confirm the data NIC and the far-subnet route are correct."""
    addr = run(c, "ip -br addr show eth0")
    if spec["data_ip"] not in addr:
        return "eth0 does not carry %s (got: %s)" % (spec["data_ip"], addr.strip())
    # far_net is a bare network address (e.g. 10.50.2.0), not a host, on
    # purpose: this check only cares which device the kernel would use to
    # reach that subnet, and "ip route get" resolves an egress device for a
    # network address just as well as for a real host, without needing one
    # to exist.
    route = run(c, "ip route get %s" % spec["far_net"])
    if "dev eth0" not in route:
        return "traffic to %s does not leave via eth0 (got: %s)" % (spec["far_net"], route)
    default = run(c, "ip route show default")
    if "dev eth1" not in default:
        return "default route is not on eth1 (got: %s)" % default
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()

    failed = False
    for name, spec in ENDPOINTS.items():
        print("=== %s (%s) ===" % (name, spec["host"]))
        c = connect(spec["host"])
        if not args.skip_preflight:
            problem = preflight(c, spec)
            if problem:
                print("  PREFLIGHT FAILED: %s" % problem)
                print("  run bring_up_endpoints.sh on this host first")
                failed = True
                c.close()
                continue
            print("  preflight OK")
        sftp = c.open_sftp()
        run(c, "mkdir -p %s/isr_apps %s/console" % (REMOTE, REMOTE))
        for subdir, files in TREE:
            for fn in files:
                local = os.path.join(HERE, subdir, fn)
                sftp.put(local, "%s/%s/%s" % (REMOTE, subdir, fn))
                print("  pushed %s/%s" % (subdir, fn))
        sftp.close()
        print("  " + run(c, "cd %s/isr_apps && python3 -c "
                             "'import common; print(\"common imports OK\")'" % REMOTE))
        c.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
