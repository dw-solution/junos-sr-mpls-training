"""Shared helpers for the ISR QoS marking demo.

Standard library only, and Python 3.9 compatible: the lab endpoints run Rocky
Linux 9.3 with Python 3.9.18, where socket.IP_RECVTOS does not exist.
"""
import socket
import struct
import time

# socket.IP_TOS exists everywhere. socket.IP_RECVTOS arrived in Python 3.10, so
# on the endpoints it must come from the raw Linux uapi value.
IP_TOS = getattr(socket, "IP_TOS", 1)
IP_RECVTOS = getattr(socket, "IP_RECVTOS", 13)

DSCP_BY_NAME = {
    "CS0": 0,
    "BE": 0,
    "CS1": 8,
    "AF31": 26,
    "AF41": 34,
    "EF": 46,
    "CS6": 48,
}

DSCP_NAMES = {
    0: "CS0",
    8: "CS1",
    26: "AF31",
    34: "AF41",
    46: "EF",
    48: "CS6",
}

STREAM_IDS = {
    "c2_messaging": 1,
    "track_feed": 2,
    "fmv_stream": 3,
    "imagery_push": 4,
}
STREAM_NAMES = {v: k for k, v in STREAM_IDS.items()}

PORTS = {
    "c2_messaging": 9100,
    "track_feed": 9200,
    "imagery_push": 9300,
    "fmv_stream": 9400,
}

MAGIC = b"ISRQ"
VERSION = 1
# magic, version, stream_id, asked_dscp, flags, seq, tx_ns, payload_len, pad
HEADER = struct.Struct("!4sBBBBIQHH")
HEADER_SIZE = HEADER.size


def dscp_value(name):
    """Map a DSCP name such as 'EF' to its 6-bit value."""
    return DSCP_BY_NAME[name.upper()]


def dscp_label(value):
    """Render a DSCP value for humans, e.g. 46 becomes 'EF (46)'."""
    return "%s (%d)" % (DSCP_NAMES.get(value, "DSCP%d" % value), value)


def set_dscp(sock, dscp):
    """Mark every packet from this socket with the given DSCP.

    This single line is the entire "my application is important" claim. The
    value lands in the IPv4 header's TOS byte, shifted left by two because DSCP
    occupies the top six bits and ECN owns the bottom two.
    """
    sock.setsockopt(socket.IPPROTO_IP, IP_TOS, dscp << 2)


def enable_tos_readback(sock):
    """Ask the kernel to report each datagram's arriving TOS byte."""
    sock.setsockopt(socket.IPPROTO_IP, IP_RECVTOS, 1)


def tos_from_ancdata(ancdata):
    """Extract the arriving TOS byte from recvmsg ancillary data."""
    for level, ctype, cdata in ancdata:
        if level == socket.IPPROTO_IP and ctype == IP_TOS and cdata:
            return cdata[0]
    return None


def pack_header(stream_id, asked_dscp, seq, tx_ns, payload_len, flags=0):
    return HEADER.pack(MAGIC, VERSION, stream_id, asked_dscp, flags,
                       seq & 0xFFFFFFFF, tx_ns & 0xFFFFFFFFFFFFFFFF,
                       payload_len & 0xFFFF, 0)


def unpack_header(buf):
    """Decode a wire header, or return None if this is not our traffic."""
    if len(buf) < HEADER_SIZE:
        return None
    magic, version, stream_id, asked_dscp, flags, seq, tx_ns, plen, _ = \
        HEADER.unpack(buf[:HEADER_SIZE])
    if magic != MAGIC or version != VERSION:
        return None
    return {
        "stream_id": stream_id,
        "asked_dscp": asked_dscp,
        "flags": flags,
        "seq": seq,
        "tx_ns": tx_ns,
        "payload_len": plen,
    }


def pace(rate_hz, duration, fn):
    """Call fn(seq) at approximately rate_hz for duration seconds.

    Returns the number of calls made. Sleeps against a monotonic deadline so
    the send rate does not drift with the cost of fn.
    """
    if rate_hz <= 0:
        raise ValueError("rate_hz must be positive")
    interval = 1.0 / rate_hz
    start = time.monotonic()
    deadline = start + duration
    seq = 0
    while True:
        now = time.monotonic()
        if now >= deadline:
            return seq
        fn(seq)
        seq += 1
        target = start + seq * interval
        gap = target - time.monotonic()
        if gap > 0:
            time.sleep(min(gap, max(0.0, deadline - time.monotonic())))
