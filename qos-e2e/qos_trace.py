#!/usr/bin/env python3
"""Print the seven-stage QoS chain for one stream as a single ledger.

Read-only. Connects to PE1, C1 and PE2 over the management network, runs the
relevant show commands, and correlates them so the whole path fits on one
screen instead of six separate command outputs.

Stages 4 through 7 report configuration state read live from the routers
(classifiers, filters and rewrite rules bound to interfaces). That proves the
network is set up to act on markings, but it is not a packet-by-packet
observation. See the footer this tool prints for what actually is measured.
"""
import argparse
import os
import re
import sys

from netmiko import ConnectHandler

STREAMS = {
    "c2_messaging": {"dscp": 48, "name": "CS6", "fc": "network-control",
                     "queue": 3, "exp": "110", "port": 9100},
    "fmv_stream": {"dscp": 34, "name": "AF41", "fc": "assured-forwarding",
                   "queue": 2, "exp": "100", "port": 9400},
    "track_feed": {"dscp": 26, "name": "AF31", "fc": "assured-forwarding",
                   "queue": 2, "exp": "100", "port": 9200},
    "imagery_push": {"dscp": 8, "name": "CS1", "fc": "best-effort",
                     "queue": 0, "exp": "000", "port": 9300},
}

DEVICES = {"PE1": "10.0.0.40", "C1": "10.0.0.42", "PE2": "10.0.0.41"}


def connect(host, password):
    return ConnectHandler(device_type="juniper_junos", host=host, username="lab",
                          password=password, conn_timeout=60,
                          read_timeout_override=120, global_delay_factor=4)


def parse_egress_dscp_table(conn):
    """Read PE2's EGRESS-DSCP rewrite rule and return {forwarding_class: dscp}.

    This is the live source of truth for what DSCP a forwarding class gets
    rewritten to on the way out, so callers derive the delivered DSCP from it
    instead of assuming a fixed value. If the rule is missing or unparsable
    the caller gets an empty table and falls back to reporting "?".
    """
    out = conn.send_command("show class-of-service rewrite-rule name EGRESS-DSCP type dscp")
    table = {}
    for m in re.finditer(r"^\s*([a-zA-Z][\w-]*)\s+(low|high)\s+([01]{6})\s*$",
                          out, re.MULTILINE):
        fc, _loss_priority, code_point = m.groups()
        table[fc] = int(code_point, 2)
    return table


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stream", choices=sorted(STREAMS))
    ap.add_argument("--greedy", action="store_true",
                    help="match imagery_push.py --greedy: the stream asks for EF "
                         "(46) instead of its honest CS1 (8), so the trace can show "
                         "a claim the policy actually has to override")
    ap.add_argument("--password", default=os.environ.get("LAB_PASSWORD", "labpassword"))
    args = ap.parse_args()
    s = dict(STREAMS[args.stream])
    if args.greedy:
        if args.stream != "imagery_push":
            print("--greedy only changes anything for imagery_push")
        else:
            s["dscp"], s["name"] = 46, "EF"

    conns = {}
    try:
        for name, ip in DEVICES.items():
            conns[name] = connect(ip, args.password)

        pe1_cos = conns["PE1"].send_command("show class-of-service interface ge-0/0/3")
        pe1_filter_binding = conns["PE1"].send_command(
            "show configuration interfaces ge-0/0/3 unit 100 family inet filter")
        pe2_cos = conns["PE2"].send_command("show class-of-service interface ge-0/0/3")
        p1_cos = conns["C1"].send_command("show class-of-service interface ge-0/0/1")
        egress_table = parse_egress_dscp_table(conns["PE2"])

        trusted = "DSCP-TRUSTED" in pe1_cos
        # `show firewall filter UNTRUSTED-REMARK` returns output for any
        # CONFIGURED filter whether or not it is applied to an interface, so
        # that command cannot distinguish "defined" from "in the forwarding
        # path". Read the interface's own input-filter configuration instead,
        # which only shows a filter that is actually bound.
        mf_bound = "UNTRUSTED-REMARK" in pe1_filter_binding
        egress = "EGRESS-DSCP" in pe2_cos
        classifier_on = "SR-MPLS-EXP-CLASS" in p1_cos
        rewrite_on = "SR-MPLS-EXP-REWRITE" in p1_cos
        # The multifield filter only has anything to override when the
        # stream's claim actually conflicts with the policy it enforces.
        # imagery_push's honest default (CS1, 8) already maps to best-effort
        # through the BA classifier alone; crediting the MF filter for that
        # outcome would teach the wrong mechanism. Only imagery_push --greedy
        # (asking EF, 46) puts a claim in front of the filter that it has to
        # override.
        forced = args.stream == "imagery_push" and mf_bound and s["dscp"] == 46
        effective_fc = "best-effort" if forced else s["fc"]
        effective_exp = "000" if forced else s["exp"]
        # Delivered DSCP is read from PE2's live EGRESS-DSCP rewrite rule, not
        # assumed. Today that maps assured-forwarding to AF41 (34); if that
        # mapping is ever changed on the router this line follows it instead
        # of quietly going stale.
        delivered = egress_table.get(effective_fc)

        print()
        print("  QoS chain for %s" % args.stream)
        print("  " + "=" * 74)
        print("  %-3s %-26s %-18s %s" % ("#", "STAGE", "WHERE", "OBSERVED"))
        print("  " + "-" * 74)
        print("  %-3s %-26s %-18s %s" % ("1", "application asks", "Client1",
                                         "%s (%d)" % (s["name"], s["dscp"])))
        print("  %-3s %-26s %-18s %s" % ("2", "kernel writes TOS byte", "Client1 eth0",
                                         "tos 0x%02x" % (s["dscp"] << 2)))
        print("  %-3s %-26s %-18s %s" % ("3", "LAN carries it", "CE1",
                                         "unchanged by routing"))
        print("  %-3s %-26s %-18s %s" % ("4", "gateway decides", "PE1 ge-0/0/3.100",
                                         "BA=%s MF=%s -> %s"
                                         % ("on" if trusted else "OFF",
                                            "on" if mf_bound else "OFF",
                                            effective_fc)))
        print("  %-3s %-26s %-18s %s" % ("5", "collapse into label", "PE1 core egress",
                                         "EXP %s" % effective_exp))
        print("  %-3s %-26s %-18s %s" % ("6", "core acts on labels", "C1 ge-0/0/1",
                                         "classifier=%s rewrite=%s (acts on EXP, not IP header)"
                                         % ("on" if classifier_on else "OFF",
                                            "on" if rewrite_on else "OFF")))
        print("  %-3s %-26s %-18s %s" % ("7", "reverse translation", "PE2 ge-0/0/3.100",
                                         "rewrite=%s -> DSCP %s"
                                         % ("on" if egress else "OFF",
                                            delivered if delivered is not None else "?")))
        print()
        if delivered is not None and delivered != s["dscp"]:
            print("  NOTE: sent DSCP %d, delivered DSCP %d. Only the forwarding class"
                  % (s["dscp"], delivered))
            print("        crossed the core; the egress rewrite cannot recover which")
            print("        DSCP entered it.")
            print()
        print("  " + "-" * 74)
        print("  Stages 4-7 above are CONFIGURATION read live from the routers: they show")
        print("  what the network is set up to do, not a packet actually being caught in")
        print("  the act. The only per-packet proof of this behaviour comes from the")
        print("  receiving endpoint's console output and from an operator-driven packet")
        print("  capture on the core link. Treat this ledger as 'wired correctly', not")
        print("  'watched it happen'.")
        print()
    finally:
        for c in conns.values():
            c.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
