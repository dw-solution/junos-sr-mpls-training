#!/usr/bin/env python3
"""Full-motion video surrogate. Fat and latency sensitive.

Marks itself AF41 (34). Standard library only, Python 3.9 compatible.
"""
import argparse
import socket
import sys
import time

import common

STREAM = "fmv_stream"
DEFAULT_DSCP = "AF41"
DEFAULT_RATE = 100.0
FRAME_BYTES = 1200


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
    filler = b"\xa5" * FRAME_BYTES

    def send(seq):
        head = common.pack_header(sid, dscp, seq, time.monotonic_ns(), len(filler))
        sock.sendto(head + filler, dest)

    sent = common.pace(args.rate, args.duration, send)
    sock.close()
    print("%s sent %d frames" % (STREAM, sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
