"""Unit tests for the shared QoS demo helpers."""
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "isr_apps"))

import common  # noqa: E402


def test_dscp_names_round_trip():
    for name in ("CS6", "EF", "AF41", "AF31", "CS1", "CS0"):
        value = common.dscp_value(name)
        assert common.dscp_label(value).startswith(name) or name in common.dscp_label(value)


def test_dscp_known_values():
    assert common.dscp_value("CS6") == 48
    assert common.dscp_value("EF") == 46
    assert common.dscp_value("AF41") == 34
    assert common.dscp_value("AF31") == 26
    assert common.dscp_value("CS1") == 8
    assert common.dscp_value("CS0") == 0


def test_dscp_value_rejects_unknown():
    with pytest.raises(KeyError):
        common.dscp_value("NOPE")


def test_set_dscp_writes_the_tos_byte():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        common.set_dscp(sock, 46)
        assert sock.getsockopt(socket.IPPROTO_IP, common.IP_TOS) == 46 << 2
    finally:
        sock.close()


def test_header_round_trip():
    blob = common.pack_header(stream_id=2, asked_dscp=26, seq=12345,
                              tx_ns=1234567890123, payload_len=100)
    assert len(blob) == common.HEADER_SIZE == 24
    got = common.unpack_header(blob)
    assert got["stream_id"] == 2
    assert got["asked_dscp"] == 26
    assert got["seq"] == 12345
    assert got["tx_ns"] == 1234567890123
    assert got["payload_len"] == 100


def test_unpack_rejects_foreign_bytes():
    assert common.unpack_header(b"x" * 24) is None
    assert common.unpack_header(b"short") is None


def test_stream_tables_agree():
    for name, sid in common.STREAM_IDS.items():
        assert common.STREAM_NAMES[sid] == name
        assert name in common.PORTS


def test_pace_calls_the_callback_at_roughly_the_rate():
    seen = []
    sent = common.pace(rate_hz=50.0, duration=0.2, fn=lambda seq: seen.append(seq))
    assert sent == len(seen)
    assert 5 <= sent <= 20
    assert seen == list(range(len(seen)))
