"""Receiver-side state for the QoS marking demo.

Holds what each stream asked for, what actually arrived, loss and jitter. Knows
nothing about how any of it is displayed.

Jitter follows the RFC 3550 smoothed estimator. It is deliberately the only
timing figure reported: the sender and receiver clocks are not synchronised, so
absolute one-way latency would be meaningless, while jitter is differential and
immune to clock offset.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "isr_apps"))

import common  # noqa: E402

# A gap this long between two packets on the same stream name means a sender
# was stopped and restarted (e.g. re-running track_feed during M7's tunnel-
# model step), not a real loss event within one run. Any run genuinely lasts
# well under this on the demo's traffic rates.
STALE_GAP_NS = 5 * 1000000000


class StreamState(object):
    def __init__(self, name, is_tcp=False):
        self.name = name
        self.is_tcp = is_tcp
        self.asked_dscp = None
        self.arrived_dscp = None
        self.packets = 0
        self.lost = 0
        self.jitter_ms = 0.0
        self.last_seen = None
        self._highest_seq = None
        self._prev_tx = None
        self._prev_rx = None

    def observe(self, header, arrived_tos, rx_ns):
        if self.last_seen is not None and (rx_ns - self.last_seen) > STALE_GAP_NS:
            # A gap this long means the sender process ended and a new one
            # started (e.g. re-running track_feed for M7's tunnel-model
            # step), not that this many nanoseconds of real traffic went
            # missing. The new process's sequence numbers restart at 0 and
            # its monotonic clock has no relationship to the old one's, so
            # without this reset _highest_seq would already be high (gaps
            # stop counting as loss) and the first jitter sample would spike
            # from comparing two unrelated clocks. Start this stream's
            # counters over rather than carrying stale state into a new run.
            self.packets = 0
            self.lost = 0
            self.jitter_ms = 0.0
            self._highest_seq = None
            self._prev_tx = None
            self._prev_rx = None

        self.asked_dscp = header["asked_dscp"]
        if arrived_tos is not None:
            self.arrived_dscp = arrived_tos >> 2
        self.packets += 1
        self.last_seen = rx_ns

        if self.is_tcp:
            # TCP retransmits instead of losing data, and stream reassembly
            # can decode several messages out of one read or split one
            # across several, so sequence-gap loss and inter-arrival jitter
            # measured this way would not reflect anything real. Skip both;
            # loss_pct() and the console report them as unavailable.
            return

        seq = header["seq"]
        if self._highest_seq is None:
            self._highest_seq = seq
        elif seq > self._highest_seq:
            self.lost += seq - self._highest_seq - 1
            self._highest_seq = seq

        tx = header["tx_ns"]
        if self._prev_tx is not None:
            transit = (rx_ns - tx) - (self._prev_rx - self._prev_tx)
            d_ms = abs(transit) / 1000000.0
            self.jitter_ms += (d_ms - self.jitter_ms) / 16.0
        self._prev_tx = tx
        self._prev_rx = rx_ns

    def loss_pct(self):
        if self.is_tcp:
            return None
        total = self.packets + self.lost
        if total == 0:
            return 0.0
        return 100.0 * self.lost / total

    def verdict(self):
        # These labels describe the DIRECTION the delivered DSCP moved
        # relative to what was asked for, not the cause. "RE-MARKED AT
        # GATEWAY" is this demo's known cause for a demotion, but do not
        # assume that label always means a gateway re-mark: any mechanism
        # that lands a stream on a lower code point than it asked for
        # (a different filter, a misconfigured classifier, etc.) produces
        # the same label.
        if self.asked_dscp is None or self.arrived_dscp is None:
            return "no data"
        if self.arrived_dscp == self.asked_dscp:
            return "honored"
        if self.arrived_dscp < self.asked_dscp:
            return "RE-MARKED AT GATEWAY"
        return "CLASS COLLAPSED"


class _TCPConnection(object):
    """Byte-stream reassembly state for one TCP connection.

    Whatever mechanism the caller uses to read the arriving TOS byte for a
    TCP connection (see render_tui.tcp_arrived_tos for what this lab's
    kernel actually requires: recvmsg() never delivers an IP_RECVTOS
    ancillary message for a stream socket here, so the receiver reads the
    kernel's cached IP options instead) is not guaranteed to hand back a
    value on every single read. We remember the last value we were given
    and keep using it until told otherwise, instead of treating a read
    with nothing new as "TOS unknown".
    """
    def __init__(self):
        self.buffer = b""
        self.last_tos = None


class ConsoleState(object):
    def __init__(self):
        self.streams = {}
        self.tracks = []
        self._tcp_conns = {}

    def observe_datagram(self, payload, arrived_tos, rx_ns, is_tcp=False):
        header = common.unpack_header(payload)
        if header is None:
            return None
        name = common.STREAM_NAMES.get(header["stream_id"])
        if name is None:
            return None
        state = self.streams.get(name)
        if state is None:
            state = StreamState(name, is_tcp=is_tcp)
            self.streams[name] = state
        state.observe(header, arrived_tos, rx_ns)

        if name == "track_feed":
            body = payload[common.HEADER_SIZE:]
            try:
                self.tracks = json.loads(body.decode()).get("tracks", [])
            except (ValueError, UnicodeDecodeError):
                pass
        return state

    def observe_stream_bytes(self, conn_id, data, arrived_tos, rx_ns):
        """Feed newly read TCP bytes for one connection through reassembly.

        A single recv() on a stream socket can return a partial header, a
        partial message, exactly one message, or several messages coalesced
        together. Bytes are buffered per connection and only handed off as
        whole messages once enough of them have accumulated.
        """
        conn = self._tcp_conns.get(conn_id)
        if conn is None:
            conn = _TCPConnection()
            self._tcp_conns[conn_id] = conn
        if arrived_tos is not None:
            conn.last_tos = arrived_tos
        conn.buffer += data

        while True:
            if len(conn.buffer) < common.HEADER_SIZE:
                break
            header = common.unpack_header(conn.buffer)
            if header is None:
                # Not our traffic, or the stream desynced. Nothing in this
                # buffer can be trusted, so drop it rather than spin forever.
                conn.buffer = b""
                break
            total = common.HEADER_SIZE + header["payload_len"]
            if len(conn.buffer) < total:
                break
            message = conn.buffer[:total]
            conn.buffer = conn.buffer[total:]
            self.observe_datagram(message, conn.last_tos, rx_ns, is_tcp=True)

    def close_stream(self, conn_id):
        """Drop reassembly state for a connection that has gone away."""
        self._tcp_conns.pop(conn_id, None)

    def snapshot(self):
        rows = []
        for name in sorted(self.streams):
            s = self.streams[name]
            rows.append({
                "name": s.name,
                "asked": common.dscp_label(s.asked_dscp) if s.asked_dscp is not None else "-",
                "arrived": common.dscp_label(s.arrived_dscp) if s.arrived_dscp is not None else "-",
                "packets": s.packets,
                "loss_pct": s.loss_pct(),
                "jitter_ms": None if s.is_tcp else s.jitter_ms,
                "verdict": s.verdict(),
            })
        return {"streams": rows, "tracks": list(self.tracks)}
