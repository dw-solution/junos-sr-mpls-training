"""Unit tests for the QoS demo console state."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "isr_apps"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "console"))

import common  # noqa: E402
import console_core  # noqa: E402


def datagram(stream, dscp, seq, tx_ns, body=b"{}"):
    sid = common.STREAM_IDS[stream]
    return common.pack_header(sid, dscp, seq, tx_ns, len(body)) + body


def test_honored_stream_reports_honored():
    st = console_core.ConsoleState()
    for seq in range(5):
        st.observe_datagram(datagram("c2_messaging", 48, seq, seq * 1000000),
                            arrived_tos=48 << 2, rx_ns=seq * 1000000)
    s = st.streams["c2_messaging"]
    assert s.asked_dscp == 48
    assert s.arrived_dscp == 48
    assert s.packets == 5
    assert s.verdict() == "honored"


def test_class_collapse_is_detected():
    st = console_core.ConsoleState()
    st.observe_datagram(datagram("track_feed", 26, 0, 0), arrived_tos=34 << 2, rx_ns=0)
    s = st.streams["track_feed"]
    assert s.asked_dscp == 26
    assert s.arrived_dscp == 34
    assert s.verdict() == "CLASS COLLAPSED"


def test_gateway_remark_is_detected():
    st = console_core.ConsoleState()
    st.observe_datagram(datagram("imagery_push", 46, 0, 0), arrived_tos=8 << 2, rx_ns=0)
    s = st.streams["imagery_push"]
    assert s.verdict() == "RE-MARKED AT GATEWAY"


def test_sequence_gaps_count_as_loss():
    st = console_core.ConsoleState()
    for seq in (0, 1, 2, 5, 6):
        st.observe_datagram(datagram("fmv_stream", 34, seq, seq * 1000000),
                            arrived_tos=34 << 2, rx_ns=seq * 1000000)
    s = st.streams["fmv_stream"]
    assert s.packets == 5
    assert s.lost == 2
    assert 25.0 < s.loss_pct() < 30.0


def test_jitter_is_zero_for_perfectly_paced_traffic():
    st = console_core.ConsoleState()
    for seq in range(10):
        t = seq * 20000000
        st.observe_datagram(datagram("fmv_stream", 34, seq, t),
                            arrived_tos=34 << 2, rx_ns=t)
    assert st.streams["fmv_stream"].jitter_ms < 0.01


def test_jitter_rises_with_irregular_arrival():
    st = console_core.ConsoleState()
    arrivals = [0, 20, 65, 80, 145, 160, 225]
    for seq, ms in enumerate(arrivals):
        st.observe_datagram(datagram("fmv_stream", 34, seq, seq * 20000000),
                            arrived_tos=34 << 2, rx_ns=ms * 1000000)
    assert st.streams["fmv_stream"].jitter_ms > 1.0


def test_track_positions_are_captured():
    st = console_core.ConsoleState()
    body = json.dumps({"tracks": [{"id": "TRK001", "lat": 34.1, "lon": -117.2}]}).encode()
    sid = common.STREAM_IDS["track_feed"]
    blob = common.pack_header(sid, 26, 0, 0, len(body)) + body
    st.observe_datagram(blob, arrived_tos=26 << 2, rx_ns=0)
    assert st.tracks and st.tracks[0]["id"] == "TRK001"


def test_foreign_traffic_is_ignored():
    st = console_core.ConsoleState()
    st.observe_datagram(b"not ours at all", arrived_tos=0, rx_ns=0)
    assert st.streams == {}


def test_tcp_message_split_across_two_reads_is_reassembled_once():
    st = console_core.ConsoleState()
    blob = datagram("imagery_push", 46, 0, 0, body=b"x" * 100)
    split = len(blob) // 2
    st.observe_stream_bytes("conn1", blob[:split], arrived_tos=8 << 2, rx_ns=0)
    st.observe_stream_bytes("conn1", blob[split:], arrived_tos=None, rx_ns=1)
    s = st.streams["imagery_push"]
    assert s.packets == 1
    assert s.arrived_dscp == 8


def test_tcp_coalesced_messages_in_one_read_are_both_observed():
    st = console_core.ConsoleState()
    first = datagram("imagery_push", 46, 0, 0, body=b"x" * 10)
    second = datagram("imagery_push", 46, 1, 1000000, body=b"x" * 10)
    st.observe_stream_bytes("conn1", first + second, arrived_tos=8 << 2, rx_ns=0)
    s = st.streams["imagery_push"]
    assert s.packets == 2


def test_tcp_tos_reported_once_is_remembered_for_later_messages():
    st = console_core.ConsoleState()
    first = datagram("imagery_push", 46, 0, 0, body=b"x" * 10)
    second = datagram("imagery_push", 46, 1, 1000000, body=b"x" * 10)
    st.observe_stream_bytes("conn1", first, arrived_tos=8 << 2, rx_ns=0)
    st.observe_stream_bytes("conn1", second, arrived_tos=None, rx_ns=1)
    s = st.streams["imagery_push"]
    assert s.arrived_dscp == 8


def test_tcp_stream_reports_loss_as_unavailable():
    st = console_core.ConsoleState()
    blob = datagram("imagery_push", 46, 0, 0, body=b"x" * 10)
    st.observe_stream_bytes("conn1", blob, arrived_tos=8 << 2, rx_ns=0)
    s = st.streams["imagery_push"]
    assert s.loss_pct() is None


def test_no_data_verdict_when_arrived_tos_never_observed():
    st = console_core.ConsoleState()
    st.observe_datagram(datagram("imagery_push", 46, 0, 0), arrived_tos=None, rx_ns=0)
    s = st.streams["imagery_push"]
    assert s.arrived_dscp is None
    assert s.verdict() == "no data"


def test_stale_gap_resets_stream_counters_for_a_rerun():
    st = console_core.ConsoleState()
    # First run: seq 0, 1, 5 -> 2 packets missing between 1 and 5.
    for seq in (0, 1, 5):
        st.observe_datagram(datagram("track_feed", 26, seq, seq * 1000000),
                            arrived_tos=26 << 2, rx_ns=seq * 1000000)
    s = st.streams["track_feed"]
    assert s.packets == 3
    assert s.lost == 3

    # A new process starts more than STALE_GAP_NS later, with sequence
    # numbers and a monotonic clock unrelated to the first run's.
    restart_ns = s.last_seen + console_core.STALE_GAP_NS + 1
    for seq in (0, 1, 2):
        st.observe_datagram(datagram("track_feed", 26, seq,
                                     restart_ns + seq * 1000000),
                            arrived_tos=26 << 2, rx_ns=restart_ns + seq * 1000000)
    s = st.streams["track_feed"]
    assert s.packets == 3
    assert s.lost == 0
    assert s.jitter_ms < 0.01
