#!/usr/bin/env python3
"""Push a generated stage to the lab over fxp0 management (netmiko)."""
import csv, os, sys, time
from netmiko import ConnectHandler

HERE = os.path.dirname(os.path.abspath(__file__))

def nodes():
    with open(os.path.join(HERE, "training-nodes.csv")) as f:
        return list(csv.DictReader(f))

def commands(stage, host):
    path = os.path.join(HERE, "configs", stage, host + ".set")
    out = []
    with open(path) as f:
        for line in f:
            cmd = line.split("#")[0].strip()
            if cmd:
                out.append(cmd)
    return out

def push(node, stage, password):
    host = node["hostname"]
    conn = ConnectHandler(
        device_type="juniper_junos", host=node["mgmt_ip"],
        username="lab", password=password,
        global_delay_factor=4, read_timeout_override=300, conn_timeout=60,
        session_log=os.path.join(HERE, f"{host}.push.log"),
    )
    time.sleep(2)
    conn.send_config_set(commands(stage, host), cmd_verify=False)
    out = conn.commit(comment=f"training {stage}")
    conn.disconnect()
    if "error" in out.lower():
        return f"FAILED {host}: {out}"
    return f"OK {host} <- {stage}"

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "stage6-frr"
    pw = os.environ.get("LAB_PASSWORD", "labpassword")
    for n in nodes():
        try:
            print(push(n, stage, pw))
        except Exception as e:
            print(f"FAILED {n['hostname']}: {e}")
