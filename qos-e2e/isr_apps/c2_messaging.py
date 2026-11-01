#!/usr/bin/env python3
"""Command and status messaging. Small, infrequent, must never be late.

Marks itself CS6 (48). Standard library only, Python 3.9 compatible.
"""
import argparse
import json
import socket
import sys
import time

import common

STREAM = "c2_messaging"
DEFAULT_DSCP = "CS6"
DEFAULT_RATE = 2.0

MESSAGES = [
    {"type": "TASKING", "detail": "sensor slew to bearing 045"},
    {"type": "STATUS", "detail": "platform nominal"},
    {"type": "ACK", "detail": "tasking accepted"},
    {"type": "ALERT", "detail": "track threshold exceeded"},
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--peer", default="10.50.2.10")
    ap.add_argument("--dscp", default=DEFAULT_DSCP)
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE)
    ap.add_argument("--duration", type=float, default=60.0)
    args = ap.parse_args()

    dscp = common.dscp_value(args.dscp)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    common.set_dscp(sock, dscp)

    print("%s asking for %s" % (STREAM, common.dscp_label(dscp)))
    dest = (args.peer, common.PORTS[STREAM])
    sid = common.STREAM_IDS[STREAM]

    def send(seq):
        body = json.dumps(dict(MESSAGES[seq % len(MESSAGES)], seq=seq)).encode()
        head = common.pack_header(sid, dscp, seq, time.monotonic_ns(), len(body))
        sock.sendto(head + body, dest)

    sent = common.pace(args.rate, args.duration, send)
    sock.close()
    print("%s sent %d messages" % (STREAM, sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
