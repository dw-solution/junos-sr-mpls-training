#!/usr/bin/env python3
"""Bulk imagery dissemination over TCP. The elephant flow.

Marks itself CS1 (8) by default, which is a lower priority than best effort
traffic and is the honest marking for a bulk transfer. With --greedy it marks
itself EF (46) instead, claiming the same treatment as real-time traffic. The
gateway is expected to refuse that claim.
"""
import argparse
import socket
import sys
import time

import common

STREAM = "imagery_push"
DEFAULT_DSCP = "CS1"
GREEDY_DSCP = "EF"
CHUNK_BYTES = 4096


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--peer", default="10.50.2.10")
    ap.add_argument("--dscp", default=None,
                    help="override the marking; defaults to CS1, or EF with --greedy")
    ap.add_argument("--greedy", action="store_true",
                    help="claim EF, the marking a real-time application would use")
    ap.add_argument("--duration", type=float, default=60.0)
    args = ap.parse_args()

    name = args.dscp or (GREEDY_DSCP if args.greedy else DEFAULT_DSCP)
    dscp = common.dscp_value(name)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    common.set_dscp(sock, dscp)

    if args.greedy:
        print("%s asking for %s  <- claiming real-time priority for a bulk transfer"
              % (STREAM, common.dscp_label(dscp)))
    else:
        print("%s asking for %s" % (STREAM, common.dscp_label(dscp)))

    sock.connect((args.peer, common.PORTS[STREAM]))
    sid = common.STREAM_IDS[STREAM]
    filler = b"\xc3" * CHUNK_BYTES
    deadline = time.monotonic() + args.duration
    seq = 0
    sent_bytes = 0
    try:
        while time.monotonic() < deadline:
            head = common.pack_header(sid, dscp, seq, time.monotonic_ns(), len(filler))
            sock.sendall(head + filler)
            sent_bytes += len(head) + len(filler)
            seq += 1
    except (BrokenPipeError, ConnectionResetError):
        print("%s peer closed the connection" % STREAM)
    finally:
        sock.close()

    print("%s sent %d chunks, %.1f MB" % (STREAM, seq, sent_bytes / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
