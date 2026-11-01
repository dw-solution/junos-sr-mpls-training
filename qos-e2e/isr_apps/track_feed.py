#!/usr/bin/env python3
"""Track position updates driving the map display. Steady, moderate rate.

Marks itself AF31 (26). Standard library only, Python 3.9 compatible.
"""
import argparse
import json
import math
import socket
import sys
import time

import common

STREAM = "track_feed"
DEFAULT_DSCP = "AF31"
DEFAULT_RATE = 20.0
TRACKS = 6


def track_positions(seq):
    """Synthetic tracks orbiting a centre point, so chips visibly move."""
    out = []
    for t in range(TRACKS):
        phase = (seq / 60.0) + (t * 2 * math.pi / TRACKS)
        out.append({
            "id": "TRK%03d" % (t + 1),
            "lat": round(34.0 + 0.4 * math.sin(phase), 5),
            "lon": round(-117.0 + 0.4 * math.cos(phase), 5),
        })
    return out


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
        body = json.dumps({"tracks": track_positions(seq)}).encode()
        head = common.pack_header(sid, dscp, seq, time.monotonic_ns(), len(body))
        sock.sendto(head + body, dest)

    sent = common.pace(args.rate, args.duration, send)
    sock.close()
    print("%s sent %d updates" % (STREAM, sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
