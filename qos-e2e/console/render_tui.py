#!/usr/bin/env python3
"""ANSI console for the QoS marking demo. Runs on the receiving endpoint.

Binds the three UDP streams plus the TCP imagery listener, and redraws a
per-stream ledger with the track chips. Standard library only, Python 3.9.
"""
import argparse
import os
import select
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "isr_apps"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402
import console_core  # noqa: E402

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CLEAR = "\033[2J\033[H"

# socket.IP_PKTOPTIONS is not exposed by the socket module on Python 3.9,
# so fall back to the raw Linux uapi value, the same pattern common.py uses
# for IP_TOS/IP_RECVTOS.
IP_PKTOPTIONS = getattr(socket, "IP_PKTOPTIONS", 9)

# Native cmsghdr layout: size_t cmsg_len, int cmsg_level, int cmsg_type,
# followed by the data. "N" is struct's native size_t code, so this matches
# whatever the platform's actual cmsghdr looks like without hardcoding a
# byte width.
_CMSG_HDR = struct.Struct("NII")
_CMSG_ALIGN = struct.calcsize("N")


def _cmsg_align(n):
    return (n + _CMSG_ALIGN - 1) & ~(_CMSG_ALIGN - 1)


def tcp_arrived_tos(conn):
    """Read the arriving TOS byte the kernel has cached for a TCP connection.

    UDP gets this from recvmsg()'s IP_RECVTOS ancillary data, refreshed on
    every read. TCP does not work that way on this lab's kernel: direct
    testing against the lab endpoints (Rocky 9.3, 5.14.0-362.8.1.el9_3)
    showed recvmsg() returns empty ancillary data for a stream socket on
    every read, including immediately after a deliberate mid-connection TOS
    change and with IP_RECVTOS set on the listener before accept(). What
    does work is getsockopt(IPPROTO_IP, IP_PKTOPTIONS, ...), which hands
    back the kernel's cached IP options for the connection in the same cmsg
    wire format recvmsg() uses. Python only auto-parses that format when it
    comes from recvmsg() itself, so it is decoded here by hand.
    """
    try:
        raw = conn.getsockopt(socket.IPPROTO_IP, IP_PKTOPTIONS, 128)
    except OSError:
        return None
    offset = 0
    hdr_size = _CMSG_HDR.size
    while offset + hdr_size <= len(raw):
        cmsg_len, level, ctype = _CMSG_HDR.unpack_from(raw, offset)
        if cmsg_len < hdr_size:
            break
        data = raw[offset + hdr_size: offset + cmsg_len]
        if level == socket.IPPROTO_IP and ctype == common.IP_TOS and data:
            return data[0]
        offset += _cmsg_align(cmsg_len)
    return None

VERDICT_COLOUR = {
    "honored": GREEN,
    "CLASS COLLAPSED": YELLOW,
    "RE-MARKED AT GATEWAY": RED,
    "no data": "",
}

GRID_W, GRID_H = 52, 12
LAT_MIN, LAT_MAX = 33.5, 34.5
LON_MIN, LON_MAX = -117.5, -116.5


def udp_socket(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    common.enable_tos_readback(s)
    s.bind(("0.0.0.0", port))
    s.setblocking(False)
    return s


def tcp_listener(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    common.enable_tos_readback(s)
    s.bind(("0.0.0.0", port))
    s.listen(4)
    s.setblocking(False)
    return s


def render(state):
    snap = state.snapshot()
    out = [CLEAR, BOLD + "  ISR MISSION CONSOLE   what the application asked for "
           "versus what the network delivered" + RESET, ""]
    out.append("  %-14s %-12s %-12s %8s %7s %9s  %s"
               % ("STREAM", "ASKED", "ARRIVED", "PACKETS", "LOSS", "JITTER", "VERDICT"))
    out.append("  " + "-" * 82)
    for row in snap["streams"]:
        colour = VERDICT_COLOUR.get(row["verdict"], "")
        # TCP rows (imagery_push) carry no meaningful loss or jitter figure:
        # TCP retransmits rather than losing data, and reassembly can decode
        # several messages from one read, so neither number would measure
        # anything real. Show "n/a" rather than a misleading 0.0.
        loss_str = "n/a" if row["loss_pct"] is None else "%.1f%%" % row["loss_pct"]
        jitter_str = "n/a" if row["jitter_ms"] is None else "%.1fms" % row["jitter_ms"]
        out.append("  %-14s %-12s %-12s %8d %7s %9s  %s%s%s"
                   % (row["name"], row["asked"], row["arrived"], row["packets"],
                      loss_str, jitter_str, colour, row["verdict"], RESET))
    out.append("")
    out.append("  " + BOLD + "TRACK DISPLAY" + RESET)
    grid = [[" "] * GRID_W for _ in range(GRID_H)]
    for t in snap["tracks"]:
        try:
            lat, lon = float(t["lat"]), float(t["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        y = int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * (GRID_H - 1))
        x = int((lon - LON_MIN) / (LON_MAX - LON_MIN) * (GRID_W - 1))
        if 0 <= y < GRID_H and 0 <= x < GRID_W:
            grid[y][x] = "*"
    for line in grid:
        out.append("  |" + "".join(line) + "|")
    out.append("  +" + "-" * GRID_W + "+")
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", type=float, default=0.5)
    args = ap.parse_args()

    state = console_core.ConsoleState()
    socks = [udp_socket(common.PORTS[n])
             for n in ("c2_messaging", "track_feed", "fmv_stream")]
    listener = tcp_listener(common.PORTS["imagery_push"])
    conns = []
    last_draw = 0.0

    try:
        while True:
            readable = socks + [listener] + conns
            ready, _, _ = select.select(readable, [], [], 0.2)
            now = time.monotonic_ns()
            for s in ready:
                if s is listener:
                    try:
                        conn, _ = s.accept()
                    except OSError:
                        # A spuriously readable listener (e.g. a connection
                        # that was reset between select() and accept())
                        # must not kill the whole console process.
                        continue
                    conn.setblocking(False)
                    common.enable_tos_readback(conn)
                    conns.append(conn)
                    continue
                if s in conns:
                    try:
                        data = s.recv(65535)
                    except BlockingIOError:
                        continue
                    except (ConnectionResetError, OSError):
                        # A reset (or otherwise dead) socket stays readable
                        # forever once it is in this state: select() returns
                        # it immediately on every subsequent pass, which
                        # spins the loop at 100% CPU and freezes the display
                        # if the entry is left in conns. Tear it down exactly
                        # like a clean EOF.
                        conns.remove(s)
                        state.close_stream(s)
                        s.close()
                        continue
                    if not data:
                        conns.remove(s)
                        state.close_stream(s)
                        s.close()
                        continue
                    state.observe_stream_bytes(s, data, tcp_arrived_tos(s), now)
                else:
                    try:
                        data, anc, _, _ = s.recvmsg(65535, socket.CMSG_SPACE(4))
                    except (BlockingIOError, ConnectionResetError):
                        continue
                    state.observe_datagram(data, common.tos_from_ancdata(anc), now)
            if time.monotonic() - last_draw >= args.refresh:
                render(state)
                last_draw = time.monotonic()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
