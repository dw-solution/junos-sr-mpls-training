#!/usr/bin/env python3
"""Structural validator for generated training configs. The test harness."""
import csv, os, sys, re
from generate_lab_configs import transit_links

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "configs")

MANDATES = [
    "set groups MTU interfaces <ge-*> mtu 9192",
    "set apply-groups MTU",
    "set groups ISIS-PARAMETERS protocols isis interface <ge-*> level 2 post-convergence-lfa",
    "set groups ISIS-PARAMETERS protocols isis backup-spf-options use-post-convergence-lfa",
    "set apply-groups ISIS-PARAMETERS",
    "set routing-options forwarding-table ecmp-fast-reroute",
    "set protocols isis source-packet-routing explicit-null",
    "set protocols isis traffic-engineering l3-unicast-topology",
    "set protocols isis traffic-engineering advertisement always",
]

def load_nodes():
    p = os.path.join(HERE, "training-nodes.csv")
    return {r["hostname"]: r for r in csv.DictReader(open(p))}

def read(stage, host):
    return open(os.path.join(CFG, stage, host + ".set")).read()

def check(cond, msg, errs):
    if not cond:
        errs.append(msg)

def main():
    errs = []
    nodes = load_nodes()
    links = list(csv.DictReader(open(os.path.join(HERE, "training-links.csv"))))
    sr_nodes = [h for h, r in nodes.items() if r["role"] in ("pe", "core", "transit")]

    # 1. Every stage dir exists and has a file per node.
    stages = ["stage0-base", "stage1-isis", "stage2-sr",
              "stage3-l3vpn", "stage4-flexalgo", "stage5-qos", "stage6-frr"]
    for st in stages:
        d = os.path.join(CFG, st)
        check(os.path.isdir(d), f"missing stage dir {st}", errs)
        if not os.path.isdir(d):
            continue
        for h in nodes:
            check(os.path.exists(os.path.join(d, h + ".set")),
                  f"missing {st}/{h}.set", errs)

    # 2. Base: enhanced-ip + loopback + ISO NET on every SR node.
    for h in sr_nodes:
        c = read("stage0-base", h)
        check("set chassis network-services enhanced-ip" in c,
              f"{h}: missing enhanced-ip", errs)
        rid = nodes[h]["loopback"]
        check(f"set interfaces lo0 unit 0 family inet address {rid}/32" in c,
              f"{h}: missing loopback {rid}", errs)
        check(re.search(r"family iso address 49\.0001\.[0-9a-f.]+\.00", c),
              f"{h}: missing/invalid ISO NET", errs)

    # 3. Final stage: all immutable mandates present on every SR node.
    if os.path.isdir(os.path.join(CFG, "stage6-frr")):
        for h in sr_nodes:
            c = read("stage6-frr", h)
            for m in MANDATES:
                check(m in c, f"{h}: stage6 missing mandate: {m}", errs)

    # 5. IS-IS underlay present on SR nodes at stage1.
    if os.path.isdir(os.path.join(CFG, "stage1-isis")):
        for h in sr_nodes:
            c = read("stage1-isis", h)
            check("set apply-groups ISIS-PARAMETERS" in c, f"{h}: no ISIS-PARAMETERS", errs)
            check("set protocols isis traffic-engineering l3-unicast-topology" in c,
                  f"{h}: no l3-unicast-topology", errs)
            check("set protocols isis interface lo0.0 passive" in c, f"{h}: lo0 not passive", errs)
            for li, lip, peer, pip, link in transit_links(h, links):
                check(f"set protocols isis interface {li}.0" in c, f"{h}: isis not on {li}", errs)

    # 4. Unique node-SIDs.
    sids = [r["sid_index"] for r in nodes.values() if r["sid_index"]]
    check(len(sids) == len(set(sids)), "duplicate node-SID index", errs)

    # 6. SR-MPLS transport at stage2.
    if os.path.isdir(os.path.join(CFG, "stage2-sr")):
        for h in sr_nodes:
            c = read("stage2-sr", h)
            check("source-packet-routing srgb start-label 16000 index-range 8000" in c,
                  f"{h}: SRGB wrong/missing", errs)
            idx = nodes[h]["sid_index"]
            check(f"source-packet-routing node-segment ipv4-index {idx}" in c,
                  f"{h}: node-segment index missing", errs)
            check("set protocols isis source-packet-routing explicit-null" in c,
                  f"{h}: explicit-null missing", errs)
            check("set protocols mpls interface lo0.0" in c, f"{h}: mpls lo0 missing", errs)

    # 7. L3VPN overlay at stage3.
    if os.path.isdir(os.path.join(CFG, "stage3-l3vpn")):
        for h in ("PE1", "PE2", "C1", "C2"):
            c = read("stage3-l3vpn", h)
            check("set protocols bgp group OVERLAY family inet-vpn unicast" in c,
                  f"{h}: inet-vpn family missing", errs)
        for h in ("C1", "C2"):
            c = read("stage3-l3vpn", h)
            check("set protocols bgp group OVERLAY cluster" in c, f"{h}: RR cluster missing", errs)
        for h in ("PE1", "PE2"):
            c = read("stage3-l3vpn", h)
            check("set routing-instances CUST_A instance-type vrf" in c, f"{h}: CUST_A VRF missing", errs)
            check("set routing-instances CUST_A vrf-target target:64512:100" in c, f"{h}: CUST_A RT missing", errs)
            check("group CE type external" in c, f"{h}: eBGP PE-CE missing", errs)
        for h in ("CE1", "CE2"):
            c = read("stage3-l3vpn", h)
            check("protocols bgp group TO-PE type external" in c, f"{h}: CE eBGP missing", errs)

    # 8. Flex-algo + TE at stage4.
    if os.path.isdir(os.path.join(CFG, "stage4-flexalgo")):
        for h in sr_nodes:
            c = read("stage4-flexalgo", h)
            check("flex-algorithm 128 definition metric-type igp-metric" in c, f"{h}: algo128 missing", errs)
            check("flex-algorithm 129 definition metric-type delay-metric" in c, f"{h}: algo129 missing", errs)
            check("set protocols isis source-packet-routing flex-algorithm 129" in c, f"{h}: isis algo129 missing", errs)
            check("delay-measurement" in c, f"{h}: delay-measurement missing", errs)
        for h in ("PE1", "PE2"):
            c = read("stage4-flexalgo", h)
            check("resolution-map COLOR-RESOLUTION-MAP" in c, f"{h}: resolution-map missing", errs)

    # 9. CoS at stage5.
    if os.path.isdir(os.path.join(CFG, "stage5-qos")):
        for h in sr_nodes:
            c = read("stage5-qos", h)
            check("scheduler-maps SR-MPLS-SMAP" in c, f"{h}: scheduler-map missing", errs)
            check("classifiers exp SR-MPLS-EXP-CLASS" in c, f"{h}: exp classifier missing", errs)
            check("rewrite-rules exp SR-MPLS-EXP-REWRITE" in c, f"{h}: exp rewrite missing", errs)
        for h in ("PE1", "PE2"):
            c = read("stage5-qos", h)
            check("classifiers dscp DSCP-INGRESS" in c, f"{h}: dscp classifier missing", errs)

    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 1
    print("ALL CHECKS PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
