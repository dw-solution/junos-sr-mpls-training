#!/usr/bin/env python3
"""Cumulative staged config generator for the SR-MPLS training lab."""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "configs")

def load_data():
    nodes = {r["hostname"]: r for r in csv.DictReader(open(os.path.join(HERE, "training-nodes.csv")))}
    links = list(csv.DictReader(open(os.path.join(HERE, "training-links.csv"))))
    return nodes, links

def iso_net(loopback):
    # 10.0.0.1 -> 0100.0000.0001 -> 49.0001.0100.0000.0001.00
    octs = [int(x) for x in loopback.split(".")]
    packed = "".join(f"{o:03d}" for o in octs)        # 12 digits
    groups = [packed[i:i+4] for i in range(0, 12, 4)]
    return "49.0001." + ".".join(groups) + ".00"

def node_links(name, links):
    """Return (local_int, local_ip, peer, peer_ip, link) for each link touching `name`."""
    out = []
    for l in links:
        if l["a_node"] == name:
            out.append((l["a_int"], l["a_ip"], l["b_node"], l["b_ip"], l))
        elif l["b_node"] == name:
            out.append((l["b_int"], l["b_ip"], l["a_node"], l["a_ip"], l))
    return out

def transit_links(name, links):
    """Core/PE/transit interfaces only (exclude PE-CE and CE-facing)."""
    return [x for x in node_links(name, links) if x[4]["plane"] != "ce"]

def block_base(node, nodes, links):
    host = node["hostname"]
    rid = node["loopback"]
    role = node["role"]
    c = [
        "#" + "-" * 74,
        f"# STAGE 0 BASE: {host} ({role})",
        "#" + "-" * 74,
        f"set system host-name {host}",
        "set system time-zone UTC",
        # Lab credentials: user 'lab' / root, password 'labpassword' (SHA-512). Change for any non-lab use.
        "set system root-authentication encrypted-password \"$6$0OeCYa28gJMGyhoq$.jbWNa7gp5NIGSOpaCZuz0vvo.gOCwier5XtM.vBvBjIM3.vqOA0.Q9tQQiLeF3kGdset19/quynqKmyFGXBs/\"",
        "set system services ssh root-login allow",
        "set system login user lab class super-user authentication encrypted-password \"$6$0OeCYa28gJMGyhoq$.jbWNa7gp5NIGSOpaCZuz0vvo.gOCwier5XtM.vBvBjIM3.vqOA0.Q9tQQiLeF3kGdset19/quynqKmyFGXBs/\"",
        "set chassis fpc 0 lite-mode",
        "set chassis network-services enhanced-ip",
        "set groups MTU interfaces <ge-*> mtu 9192",
        "set apply-groups MTU",
        # vJunos factory default puts fxp0 on DHCP; a static address conflicts with it.
        "delete interfaces fxp0 unit 0 family inet dhcp",
        f"set interfaces fxp0 unit 0 family inet address {node['mgmt_ip']}/24",
        "",
        "# --- Loopback ---",
        f"set interfaces lo0 unit 0 family inet address {rid}/32",
    ]
    if role in ("pe", "core", "transit"):
        c += [
            "set interfaces lo0 unit 0 family mpls",
            f"set interfaces lo0 unit 0 family iso address {iso_net(rid)}",
            "",
            "# --- Transit interfaces (inet + iso + mpls) ---",
        ]
        for li, lip, peer, pip, link in transit_links(host, links):
            c += [
                f"set interfaces {li} unit 0 family inet address {lip}/30",
                f"set interfaces {li} unit 0 family iso",
                f"set interfaces {li} unit 0 family mpls",
            ]
        c += [
            "",
            "# --- Routing options ---",
            f"set routing-options router-id {rid}",
            "set routing-options autonomous-system 64512",
            "set routing-options forwarding-table ecmp-fast-reroute",
        ]
    else:  # ce: physical PE-CE and client-facing interfaces only, no IP yet
        c += [
            "set interfaces ge-0/0/1 vlan-tagging",
        ]
    return c

def block_isis(node, nodes, links):
    if node["role"] not in ("pe", "core", "transit"):
        return []
    host = node["hostname"]
    c = [
        "# --- STAGE 1: IS-IS underlay ---",
        "set groups ISIS-PARAMETERS protocols isis interface <ge-*> point-to-point",
        "set groups ISIS-PARAMETERS protocols isis level 1 disable",
        "set groups ISIS-PARAMETERS protocols isis level 2 wide-metrics-only",
        "set apply-groups ISIS-PARAMETERS",
        "set protocols isis traffic-engineering l3-unicast-topology",
        "set protocols isis traffic-engineering advertisement always",
        "set protocols isis interface lo0.0 passive",
    ]
    for li, lip, peer, pip, link in transit_links(host, links):
        metric = link["igp_metric"] or "10"
        c.append(f"set protocols isis interface {li}.0")
        c.append(f"set protocols isis interface {li}.0 level 2 metric {metric}")
    return c

def block_sr(node, nodes, links):
    if node["role"] not in ("pe", "core", "transit"):
        return []
    host = node["hostname"]
    idx = node["sid_index"]
    c = [
        "# --- STAGE 2: SR-MPLS transport ---",
        "set protocols isis source-packet-routing srgb start-label 16000 index-range 8000",
        f"set protocols isis source-packet-routing node-segment ipv4-index {idx}",
        "set protocols isis source-packet-routing explicit-null",
        "set protocols mpls traffic-engineering mpls-forwarding",
        "set protocols mpls interface lo0.0",
    ]
    for li, lip, peer, pip, link in transit_links(host, links):
        c.append(f"set protocols mpls interface {li}.0")
    return c

CORE_LOOPBACKS = ("10.0.0.11", "10.0.0.12")

# (vrf, vlan, rt, pe1_ce_subnet, pe1_ce_ip, ce1_ip, pe2_ce_subnet, pe2_ce_ip, ce2_ip)
VRFS = [
    {"name": "CUST_A", "vlan": 100, "rt": "target:64512:100",
     "pe1": ("172.16.100.0/30", "172.16.100.1", "172.16.100.2"),
     "pe2": ("172.16.110.0/30", "172.16.110.1", "172.16.110.2")},
    {"name": "CUST_B", "vlan": 200, "rt": "target:64512:200",
     "pe1": ("172.16.101.0/30", "172.16.101.1", "172.16.101.2"),
     "pe2": ("172.16.111.0/30", "172.16.111.1", "172.16.111.2")},
]
CE_AS = {"CE1": 65001, "CE2": 65002}
CUSTOMER_PREFIX = "192.168.50.0/24"   # reused across VRFs on purpose

def block_l3vpn(node, nodes, links):
    role = node["role"]
    if role not in ("pe", "core"):
        return []
    host = node["hostname"]
    rid = node["loopback"]
    c = ["# --- STAGE 3: L3VPN overlay (iBGP) ---",
         "set protocols bgp group OVERLAY type internal",
         f"set protocols bgp group OVERLAY local-address {rid}",
         "set protocols bgp group OVERLAY family inet-vpn unicast",
         "set protocols bgp group OVERLAY family evpn signaling"]
    if role == "core":
        c.append("set protocols bgp group OVERLAY cluster 0.0.0.1")
        for other, n in nodes.items():
            if n["role"] in ("pe", "core") and n["loopback"] != rid:
                c.append(f"set protocols bgp group OVERLAY neighbor {n['loopback']}")
    else:  # pe peers with the two cores only
        for clb in CORE_LOOPBACKS:
            c.append(f"set protocols bgp group OVERLAY neighbor {clb}")
        # PE-CE physical + VRFs + eBGP
        c.append("set interfaces ge-0/0/3 vlan-tagging")
        c.append("set interfaces ge-0/0/3 encapsulation flexible-ethernet-services")
        side = "pe1" if host == "PE1" else "pe2"
        ce = "CE1" if host == "PE1" else "CE2"
        for v in VRFS:
            subnet, pe_ip, ce_ip = v[side]
            c += [
                f"set interfaces ge-0/0/3 unit {v['vlan']} vlan-id {v['vlan']}",
                f"set interfaces ge-0/0/3 unit {v['vlan']} family inet address {pe_ip}/30",
                f"set routing-instances {v['name']} instance-type vrf",
                f"set routing-instances {v['name']} interface ge-0/0/3.{v['vlan']}",
                f"set routing-instances {v['name']} route-distinguisher {rid}:{v['vlan']}",
                f"set routing-instances {v['name']} vrf-target {v['rt']}",
                f"set routing-instances {v['name']} vrf-table-label",
                f"set routing-instances {v['name']} protocols bgp group CE type external",
                f"set routing-instances {v['name']} protocols bgp group CE peer-as {CE_AS[ce]}",
                f"set routing-instances {v['name']} protocols bgp group CE neighbor {ce_ip}",
            ]
    return c

def block_ce_service(node, nodes, links):
    if node["role"] != "ce":
        return []
    host = node["hostname"]
    asn = CE_AS[host]
    pe_side = "pe1" if host == "CE1" else "pe2"
    c = ["# --- STAGE 3: CE service (eBGP to PE) ---"]
    for v in VRFS:
        subnet, pe_ip, ce_ip = v[pe_side]
        c += [
            f"set interfaces ge-0/0/1 unit {v['vlan']} vlan-id {v['vlan']}",
            f"set interfaces ge-0/0/1 unit {v['vlan']} family inet address {ce_ip}/30",
            f"set routing-instances {v['name']} instance-type virtual-router",
            f"set routing-instances {v['name']} interface ge-0/0/1.{v['vlan']}",
            f"set routing-instances {v['name']} interface lo0.{v['vlan']}",
            f"set interfaces lo0 unit {v['vlan']} family inet address 192.168.50.1/32",
            f"set routing-instances {v['name']} protocols bgp group TO-PE type external",
            f"set routing-instances {v['name']} protocols bgp group TO-PE peer-as 64512",
            f"set routing-instances {v['name']} protocols bgp group TO-PE neighbor {pe_ip}",
            f"set routing-instances {v['name']} protocols bgp group TO-PE export ADV-CUST",
        ]
    # Client-access port bound into CUST_A; per-CE subnet avoids collision.
    client_oct = 1 if host == "CE1" else 2
    c += [
        f"set interfaces ge-0/0/2 unit 0 family inet address 10.50.{client_oct}.1/24",
        "set routing-instances CUST_A interface ge-0/0/2.0",
    ]
    c += [
        f"set routing-options autonomous-system {asn}",
        "set policy-options policy-statement ADV-CUST term lo from protocol direct",
        "set policy-options policy-statement ADV-CUST term lo then accept",
    ]
    return c

def block_stage3(node, nodes, links):
    return block_l3vpn(node, nodes, links) + block_ce_service(node, nodes, links)

def block_flexalgo(node, nodes, links):
    if node["role"] not in ("pe", "core", "transit"):
        return []
    host = node["hostname"]
    rid = node["loopback"]
    idx = int(node["sid_index"])
    c = [
        "# --- STAGE 4: Flexible-Algorithm TE ---",
        "set routing-options flex-algorithm 128 definition metric-type igp-metric",
        "set routing-options flex-algorithm 128 color 128",
        "set routing-options flex-algorithm 128 use-transport-class",
        "set routing-options flex-algorithm 129 definition metric-type delay-metric",
        "set routing-options flex-algorithm 129 color 129",
        "set routing-options flex-algorithm 129 use-transport-class",
        "set routing-options transport-class auto-create",
        "set routing-options transport-class name ipv4-tc-128-igp color 128",
        "set routing-options transport-class name ipv4-tc-129-delay color 129",
        "set protocols isis source-packet-routing flex-algorithm 128",
        "set protocols isis source-packet-routing flex-algorithm 129",
        "set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid from interface lo0.0",
        f"set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid from route-filter {rid}/32 exact",
        f"set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid then prefix-segment algorithm 128 index {1000 + idx}",
        "set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid then prefix-segment algorithm 128 node-segment",
        f"set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid then prefix-segment algorithm 129 index {2000 + idx}",
        "set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid then prefix-segment algorithm 129 node-segment",
        "set policy-options policy-statement EXPORT-FLEX-ALGO-SID term sid then accept",
        "set protocols isis export EXPORT-FLEX-ALGO-SID",
    ]
    # delay-measurement on transit interfaces drives algo-129 SPF
    for li, lip, peer, pip, link in transit_links(host, links):
        c += [
            f"set protocols isis interface {li}.0 delay-measurement probe-interval 1",
            f"set protocols isis interface {li}.0 delay-measurement probe-count 3",
            f"set protocols isis interface {li}.0 delay-measurement advertisement periodic threshold 90",
            f"set protocols isis interface {li}.0 delay-measurement advertisement periodic interval 60",
        ]
    if node["role"] == "pe":
        c += [
            "set policy-options resolution-map COLOR-RESOLUTION-MAP mode ip-color",
            "set policy-options policy-statement VPN-COLOR-RESOLUTION term map then resolution-map COLOR-RESOLUTION-MAP",
            "set protocols bgp group OVERLAY import VPN-COLOR-RESOLUTION",
            # Steer CUST_B onto the delay plane (algo 129 / color 129).
            "set policy-options community COLOR-129 members color:0:129",
            "set policy-options policy-statement SET-COLOR-129 term t1 then community add COLOR-129",
            "set policy-options policy-statement SET-COLOR-129 term t1 then accept",
            "set routing-instances CUST_B protocols bgp group CE import SET-COLOR-129",
        ]
    return c

def block_qos(node, nodes, links):
    if node["role"] not in ("pe", "core", "transit"):
        return []
    host = node["hostname"]
    c = [
        "# --- STAGE 5: Class of service ---",
        "set class-of-service forwarding-classes queue 0 best-effort",
        "set class-of-service forwarding-classes queue 5 premium-priority",
        "set class-of-service schedulers BE-SCHEDULER transmit-rate percent 70",
        "set class-of-service schedulers BE-SCHEDULER buffer-size percent 70",
        "set class-of-service schedulers PREMIUM-SCHEDULER priority strict-high",
        "set class-of-service schedulers PREMIUM-SCHEDULER buffer-size percent 30",
        "set class-of-service scheduler-maps SR-MPLS-SMAP forwarding-class best-effort scheduler BE-SCHEDULER",
        "set class-of-service scheduler-maps SR-MPLS-SMAP forwarding-class premium-priority scheduler PREMIUM-SCHEDULER",
        "set class-of-service classifiers exp SR-MPLS-EXP-CLASS forwarding-class premium-priority loss-priority low code-points 101",
        "set class-of-service classifiers exp SR-MPLS-EXP-CLASS forwarding-class best-effort loss-priority low code-points 000",
        "set class-of-service rewrite-rules exp SR-MPLS-EXP-REWRITE forwarding-class premium-priority loss-priority low code-point 101",
        "set class-of-service rewrite-rules exp SR-MPLS-EXP-REWRITE forwarding-class best-effort loss-priority low code-point 000",
    ]
    for li, lip, peer, pip, link in transit_links(host, links):
        c += [
            f"set class-of-service interfaces {li} scheduler-map SR-MPLS-SMAP",
            f"set class-of-service interfaces {li} unit 0 classifiers exp SR-MPLS-EXP-CLASS",
            f"set class-of-service interfaces {li} unit 0 rewrite-rules exp SR-MPLS-EXP-REWRITE",
        ]
    if node["role"] == "pe":
        # Map customer DSCP EF (46) to premium on PE-CE ingress.
        c += [
            "set class-of-service classifiers dscp DSCP-INGRESS forwarding-class premium-priority loss-priority low code-points 101110",
            "set class-of-service classifiers dscp DSCP-INGRESS forwarding-class best-effort loss-priority low code-points 000000",
            "set class-of-service interfaces ge-0/0/3 unit 100 classifiers dscp DSCP-INGRESS",
            "set class-of-service interfaces ge-0/0/3 unit 200 classifiers dscp DSCP-INGRESS",
        ]
    return c

def block_frr(node, nodes, links):
    if node["role"] not in ("pe", "core", "transit"):
        return []
    return [
        "# --- STAGE 6: TI-LFA fast reroute ---",
        "set groups ISIS-PARAMETERS protocols isis interface <ge-*> level 2 post-convergence-lfa",
        "set groups ISIS-PARAMETERS protocols isis backup-spf-options use-post-convergence-lfa",
        "set groups ISIS-PARAMETERS protocols isis backup-spf-options use-source-packet-routing",
    ]

# Stages are appended by later tasks: (dirname, block_fn).
STAGES = [
    ("stage0-base", block_base),
    ("stage1-isis", block_isis),
    ("stage2-sr", block_sr),
    ("stage3-l3vpn", block_stage3),
    ("stage4-flexalgo", block_flexalgo),
    ("stage5-qos", block_qos),
    ("stage6-frr", block_frr),
]

def write_all():
    nodes, links = load_data()
    for idx, (dirname, _) in enumerate(STAGES):
        out = os.path.join(CFG, dirname)
        os.makedirs(out, exist_ok=True)
        for host, node in nodes.items():
            lines = []
            for _, fn in STAGES[:idx + 1]:
                block = fn(node, nodes, links)
                if block:
                    lines += block + [""]
            with open(os.path.join(out, host + ".set"), "w") as f:
                f.write("\n".join(lines).rstrip() + "\n")
    print(f"Generated {len(STAGES)} stage(s) for {len(nodes)} nodes.")

if __name__ == "__main__":
    write_all()
