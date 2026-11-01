"""Unit tests for the stage 7 QoS config block."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import generate_lab_configs as g  # noqa: E402


def build(hostname):
    nodes, links = g.load_data()
    return g.block_qos_e2e(nodes[hostname], nodes, links)


def cumulative(hostname):
    """Concatenate every stage block through stage 7, the way write_all does.

    Most tests here assert against the stage 7 delta, because that is what the
    block function returns. This one asserts against the cumulative result,
    because EXP rewrite coverage is a property of the config that reaches a
    router, and two of the four classes are contributed by stage 5.
    """
    nodes, links = g.load_data()
    node = nodes[hostname]
    lines = []
    for _, fn in g.STAGES:
        block = fn(node, nodes, links)
        if block:
            lines += block
    return lines


def test_ce_and_client_nodes_get_nothing():
    assert build("CE1") == []


def test_four_forwarding_classes_on_a_transit_node():
    lines = build("C1")
    assert "set class-of-service forwarding-classes queue 2 assured-forwarding" in lines
    assert "set class-of-service forwarding-classes queue 3 network-control" in lines


def test_buffer_percentages_total_one_hundred():
    lines = build("C1")
    buffers = {}
    for line in lines:
        if "buffer-size percent" in line:
            parts = line.split()
            buffers[parts[3]] = int(parts[-1])
    assert sum(buffers.values()) == 100, buffers


def test_exp_rewrite_covers_all_four_classes():
    lines = cumulative("C1")
    for fc, cp in (("network-control", "110"), ("premium-priority", "101"),
                  ("assured-forwarding", "100"), ("best-effort", "000")):
        needle = ("set class-of-service rewrite-rules exp SR-MPLS-EXP-REWRITE "
                  "forwarding-class %s loss-priority low code-point %s" % (fc, cp))
        assert needle in lines


def test_pe_gets_the_trusted_ba_classifier_with_six_code_points():
    lines = build("PE1")
    points = [l for l in lines if "classifiers dscp DSCP-TRUSTED" in l
              and "code-points" in l]
    assert len(points) == 6
    for cp in ("110000", "101110", "100010", "011010", "001000", "000000"):
        assert any(l.endswith(cp) for l in points), cp


def test_pe_deletes_the_superseded_stage5_classifier():
    lines = build("PE1")
    assert "delete class-of-service classifiers dscp DSCP-INGRESS" in lines
    assert ("delete class-of-service interfaces ge-0/0/3 unit 100 "
            "classifiers dscp DSCP-INGRESS") in lines


def test_pe_gets_the_untrusted_multifield_filter_bound_as_input():
    lines = build("PE1")
    assert ("set firewall family inet filter UNTRUSTED-REMARK term imagery "
            "from destination-port 9300") in lines
    assert ("set firewall family inet filter UNTRUSTED-REMARK term imagery "
            "then forwarding-class best-effort") in lines
    assert ("set firewall family inet filter UNTRUSTED-REMARK term imagery "
            "then dscp cs1") in lines
    assert ("set firewall family inet filter UNTRUSTED-REMARK term default "
            "then accept") in lines
    assert ("set interfaces ge-0/0/3 unit 100 family inet filter input "
            "UNTRUSTED-REMARK") in lines


def test_pe_gets_the_egress_dscp_rewrite():
    lines = build("PE2")
    assert ("set class-of-service rewrite-rules dscp EGRESS-DSCP forwarding-class "
            "assured-forwarding loss-priority low code-point 100010") in lines
    assert ("set class-of-service interfaces ge-0/0/3 unit 100 rewrite-rules "
            "dscp EGRESS-DSCP") in lines


def test_transit_interfaces_get_the_scheduler_map():
    lines = build("C1")
    assert any(l.startswith("set class-of-service interfaces ge-") and
               l.endswith("scheduler-map SR-MPLS-SMAP") for l in lines)
