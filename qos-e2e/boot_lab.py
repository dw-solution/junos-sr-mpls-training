#!/usr/bin/env python3
"""Start every node in the SR-MPLS-Training project and wait for boot.

vJunos takes several minutes to reach a usable state. Starting all ten at once
saturates the host, so nodes start in waves.
"""
import argparse
import sys
import time

import requests

PROJECT = "523b2db4-61c3-44e8-8015-8903e7d9001b"
WAVE_SIZE = 4
WAVE_GAP = 90


def nodes(base):
    r = requests.get(f"{base}/projects/{PROJECT}/nodes", timeout=30)
    r.raise_for_status()
    return r.json()


def start(base, node_id):
    r = requests.post(f"{base}/projects/{PROJECT}/nodes/{node_id}/start", timeout=60)
    r.raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://10.1.1.5:3080/v2")
    args = ap.parse_args()

    all_nodes = nodes(args.server)
    qemu = [n for n in all_nodes if n["node_type"] == "qemu"]
    other = [n for n in all_nodes if n["node_type"] != "qemu"]

    for n in other:
        if n.get("status") != "started":
            start(args.server, n["node_id"])
            print(f"started {n['name']}")

    for i in range(0, len(qemu), WAVE_SIZE):
        wave = qemu[i:i + WAVE_SIZE]
        for n in wave:
            if n.get("status") != "started":
                start(args.server, n["node_id"])
                print(f"started {n['name']}")
        if i + WAVE_SIZE < len(qemu):
            print(f"waiting {WAVE_GAP}s before next wave")
            time.sleep(WAVE_GAP)

    print("all start requests issued; routers need several more minutes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
