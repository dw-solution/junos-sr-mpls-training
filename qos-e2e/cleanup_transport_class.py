#!/usr/bin/env python3
"""One-time remediation for labs built before transport-class was removed.

generate_lab_configs.py used to emit flex-algorithm use-transport-class,
transport-class auto-create, and a per-node route-distinguisher-id in
block_flexalgo. That mechanism diverted SR tunnel routes out of inet.3 and
broke BGP next-hop resolution for the L3VPN, so it was removed from the
generator. Junos config pushes are additive set commands, so removing lines
from the generator and re-pushing a stage does not delete anything a router
already committed from an earlier push. Any lab instance that was built
before the removal still carries the stale statements and needs them
explicitly deleted once.

A lab built from scratch with the current generator never receives these
statements in the first place, so it never needs this script. Do not fold
these deletes into generate_lab_configs.py; that would make them permanent
dead weight in the teaching configs.

Touches only the four pe/core routers (PE1, PE2, C1, C2).
CE1 and CE2 never received these statements and are left alone.
"""
import csv, os
from netmiko import ConnectHandler

HERE = os.path.dirname(os.path.abspath(__file__))
NODES_CSV = os.path.join(HERE, "..", "training-nodes.csv")

DELETES = [
    "delete routing-options flex-algorithm 128 use-transport-class",
    "delete routing-options flex-algorithm 129 use-transport-class",
    "delete routing-options transport-class",
    "delete routing-options route-distinguisher-id",
]

def nodes():
    with open(NODES_CSV) as f:
        return [n for n in csv.DictReader(f) if n["role"] in ("pe", "core", "transit")]

def cleanup(node, password):
    host = node["hostname"]
    conn = ConnectHandler(
        device_type="juniper_junos", host=node["mgmt_ip"],
        username="lab", password=password,
        global_delay_factor=4, read_timeout_override=300, conn_timeout=60,
        session_log=os.path.join(HERE, f"{host}.cleanup.log"),
    )
    conn.send_config_set(DELETES, cmd_verify=False)
    out = conn.commit(comment="cleanup: remove stale transport-class config")
    conn.disconnect()
    if "error" in out.lower():
        return f"FAILED {host}: {out}"
    return f"OK {host}"

if __name__ == "__main__":
    pw = os.environ.get("LAB_PASSWORD", "labpassword")
    for n in nodes():
        try:
            print(cleanup(n, pw))
        except Exception as e:
            print(f"FAILED {n['hostname']}: {e}")
