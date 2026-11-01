#!/usr/bin/env python3
"""Print the DSCP of IPv4 frames leaving or arriving on an interface.

tcpdump can do this, but prints 'tos 0xb8'. This prints 'EF (46)', which is
what the audience needs to read. Requires root for AF_PACKET.
"""
import argparse
import socket
import struct
import sys

import common

ETH_P_ALL = 0x0003
ETH_HDR = 14
ETH_P_IP = 0x0800


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", default="eth0")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--port", type=int, default=None,
                    help="only show frames whose UDP or TCP port matches")
    args = ap.parse_args()

    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    except PermissionError:
        print("wire_peek needs root: sudo python3 wire_peek.py --iface %s" % args.iface)
        return 1
    try:
        sock.bind((args.iface, 0))
    except OSError:
        print("no such interface '%s'; try: ip -br link" % args.iface)
        return 1

    print("%-6s %-15s %-15s %-6s %-12s %s"
          % ("proto", "src", "dst", "port", "dscp", "stream"))
    shown = 0
    while shown < args.count:
        frame = sock.recv(65535)
        if len(frame) < ETH_HDR + 20:
            continue
        if struct.unpack("!H", frame[12:14])[0] != ETH_P_IP:
            continue
        ip = frame[ETH_HDR:]
        vihl = ip[0]
        if vihl >> 4 != 4:
            continue
        ihl = (vihl & 0x0F) * 4
        tos = ip[1]
        proto = ip[9]
        src = socket.inet_ntoa(ip[12:16])
        dst = socket.inet_ntoa(ip[16:20])
        payload = ip[ihl:]
        if proto == 17 and len(payload) >= 8:
            name, dport, body = "UDP", struct.unpack("!H", payload[2:4])[0], payload[8:]
        elif proto == 6 and len(payload) >= 20:
            doff = (payload[12] >> 4) * 4
            name, dport, body = "TCP", struct.unpack("!H", payload[2:4])[0], payload[doff:]
        else:
            continue
        if args.port is not None and dport != args.port:
            continue
        head = common.unpack_header(body)
        stream = common.STREAM_NAMES.get(head["stream_id"], "?") if head else "-"
        print("%-6s %-15s %-15s %-6d %-12s %s"
              % (name, src, dst, dport, common.dscp_label(tos >> 2), stream))
        shown += 1
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
