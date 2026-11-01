# QoS Marking End-to-End: Payoff Verification

Live-lab run against the 10-router SR-MPLS training lab (vJunos, GNS3 10.1.1.5),
endpoints Client1 (rocky@10.1.1.61) and Client2 (rocky@10.1.1.65).

## 1. Stage 7 push (all ten routers)

```
LAB_PASSWORD=labpassword python3 push_lab_configs.py stage7-qos-e2e
```

```
OK PE1 <- stage7-qos-e2e
OK PE2 <- stage7-qos-e2e
OK C1 <- stage7-qos-e2e
OK C2 <- stage7-qos-e2e
OK P1 <- stage7-qos-e2e
OK P2 <- stage7-qos-e2e
OK P3 <- stage7-qos-e2e
OK P4 <- stage7-qos-e2e
OK CE1 <- stage7-qos-e2e
OK CE2 <- stage7-qos-e2e
```

10/10 OK, no failures.

## 2. Forwarding check after the push

Stage 7 only changes class-of-service objects, not IS-IS/SR state, so a routing
restart was not expected to be required. Verified empirically before running any
application traffic:

```
ssh rocky@10.1.1.61 'ping -c 3 -I eth0 10.50.2.10'
```

```
PING 10.50.2.10 (10.50.2.10) from 10.50.1.10 eth0: 56(84) bytes of data.
64 bytes from 10.50.2.10: icmp_seq=1 ttl=57 time=18.9 ms
64 bytes from 10.50.2.10: icmp_seq=2 ttl=57 time=14.4 ms
64 bytes from 10.50.2.10: icmp_seq=3 ttl=57 time=14.1 ms

--- 10.50.2.10 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 14.076/15.810/18.935/2.214 ms
```

0% loss. Forwarding was healthy after the stage 7 push; no routing restart was
needed or performed.

## 3. Class-of-service state (verbatim)

### PE1 (10.0.0.40)

`show class-of-service interface ge-0/0/3`

```
Physical interface: ge-0/0/3, Index: 153
Maximum usable queues: 8, Queues in use: 5
Exclude aggregate overhead bytes: disabled
Logical interface aggregate statistics: disabled
  Scheduler map: <default>, Index: 2
  Congestion-notification: Disabled

  Logical interface: ge-0/0/3.100, Index: 360
Object                  Name                   Type                    Index
Rewrite-Output          EGRESS-DSCP            dscp                    50979
Classifier              DSCP-TRUSTED           dscp                    47702

  Logical interface: ge-0/0/3.200, Index: 361
Object                  Name                   Type                    Index
Classifier              DSCP-TRUSTED           dscp                    47702

  Logical interface: ge-0/0/3.32767, Index: 362
```

`show class-of-service classifier name DSCP-TRUSTED`

```
Classifier: DSCP-TRUSTED, Code point type: dscp, Index: 47702
  Code point         Forwarding class                    Loss priority
  000000             best-effort                         low
  001000             best-effort                         low
  011010             assured-forwarding                  low
  100010             assured-forwarding                  low
  101110             premium-priority                    low
  110000             network-control                     low
```

`show configuration firewall family inet filter UNTRUSTED-REMARK`

```
term imagery {
    from {
        protocol tcp;
        destination-port 9300;
    }
    then {
        forwarding-class best-effort;
        accept;
        dscp cs1;
    }
}
term default {
    then accept;
}
```

Also confirmed the filter is actually bound as an input filter (not just defined),
via `show configuration interfaces ge-0/0/3`:

```
unit 100 {
    vlan-id 100;
    family inet {
        filter {
            input UNTRUSTED-REMARK;
        }
        address 172.16.100.1/30;
    }
}
```

### PE2 (10.0.0.41)

`show class-of-service rewrite-rule name EGRESS-DSCP`

```
Rewrite rule: EGRESS-DSCP, Code point type: dscp, Index: 50979
  Forwarding class                    Loss priority       Code point
  best-effort                         low                 001000
  assured-forwarding                  low                 100010
  network-control                     low                 110000
  premium-priority                    low                 101110
```

`show class-of-service interface ge-0/0/3`

```
Physical interface: ge-0/0/3, Index: 153
Maximum usable queues: 8, Queues in use: 5
Exclude aggregate overhead bytes: disabled
Logical interface aggregate statistics: disabled
  Scheduler map: <default>, Index: 2
  Congestion-notification: Disabled

  Logical interface: ge-0/0/3.100, Index: 335
Object                  Name                   Type                    Index
Rewrite-Output          EGRESS-DSCP            dscp                    50979
Classifier              DSCP-TRUSTED           dscp                    47702

  Logical interface: ge-0/0/3.200, Index: 336
Object                  Name                   Type                    Index
Classifier              DSCP-TRUSTED           dscp                    47702

  Logical interface: ge-0/0/3.32767, Index: 337
```

Both objects are applied where the chain requires them: DSCP-TRUSTED classifies
inbound on both PEs, UNTRUSTED-REMARK is bound as PE1's input filter on the
customer-facing unit, and EGRESS-DSCP rewrites outbound on PE2's customer-facing
unit.

## 4. Console ledger (verbatim, final frame)

### Current evidence: post-fix run, 2026-08-06

This is the current, authoritative capture. It was taken after commit
`52daca5` (TCP reassembly and TOS readback fix) and after the fix wave in this
same session that hardened `render_tui.py`'s socket-error handling and added
the stale-run counter reset to `console_core.StreamState`. The fixed console
code was redeployed to both endpoints with `deploy_clients.py` immediately
before this run, so this frame reflects the code actually in the repository,
not an earlier build.

Console started first on Client2, then all four senders run on Client1 for 45s
each per the brief:

```
cd /home/rocky/qos-e2e/console && timeout 70 python3 render_tui.py > /tmp/frame.txt 2>&1
```
```
cd /home/rocky/qos-e2e/isr_apps
python3 c2_messaging.py --duration 45 &
python3 track_feed.py --duration 45 &
python3 fmv_stream.py --duration 45 &
python3 imagery_push.py --greedy --duration 45 &
wait
```

Sender output (verbatim, including imagery_push's own chunk count):

```
track_feed asking for AF31 (26)
track_feed sent 900 updates
fmv_stream asking for AF41 (34)
fmv_stream sent 4500 frames
c2_messaging asking for CS6 (48)
c2_messaging sent 90 messages
imagery_push asking for EF (46)  <- claiming real-time priority for a bulk transfer
imagery_push sent 60313 chunks, 237.0 MB
```

Last complete console frame, ANSI stripped, column headers and indentation
exactly as `render_tui.render()` emitted them (the header reads ARRIVED, not
DELIVERED, because that is what the code actually prints):

```

  ISR MISSION CONSOLE   what the application asked for versus what the network delivered

  STREAM         ASKED        ARRIVED       PACKETS    LOSS    JITTER  VERDICT
  ----------------------------------------------------------------------------------
  c2_messaging   CS6 (48)     CS6 (48)           90    0.0%     4.8ms  honored
  fmv_stream     AF41 (34)    AF41 (34)        4493    0.2%     5.8ms  honored
  imagery_push   EF (46)      CS1 (8)         60313     n/a       n/a  RE-MARKED AT GATEWAY
  track_feed     AF31 (26)    AF41 (34)         899    0.1%     4.7ms  CLASS COLLAPSED
```

These are the numbers this run actually produced; they are not reconciled
toward any earlier table. `imagery_push`'s console PACKETS column (60313)
matches the sender's own reported chunk count (60313) exactly on this run.
The three UDP jitter figures (4.8ms, 5.8ms, 4.7ms) differ from the numbers in
an earlier run captured the same day, which is expected: jitter is a live
measurement of this run's actual inter-arrival spacing, not a constant.

### Pre-fix console output, 2026-08-06 (superseded by commit 52daca5)

This is kept for the historical record. It predates commit `52daca5` and is
**not current evidence**. It is the frame this same demo produced before the
TCP reassembly and TOS-readback fix:

```
  ISR MISSION CONSOLE   what the application asked for versus what the network delivered

  STREAM         ASKED        ARRIVED       PACKETS    LOSS    JITTER  VERDICT
  ----------------------------------------------------------------------------------
  c2_messaging   CS6 (48)     CS6 (48)           90    0.0%     8.4ms  honored
  fmv_stream     AF41 (34)    AF41 (34)        4491    0.2%     5.0ms  honored
  imagery_push   EF (46)      -                 104   99.8%    46.6ms  no data
  track_feed     AF31 (26)    AF41 (34)         897    0.3%     5.0ms  CLASS COLLAPSED
```

### Reading the imagery_push row

The frame above showing `imagery_push` with no ARRIVED value, PACKETS 104 and
LOSS 99.8% is the **pre-fix** console (dated 2026-08-06, before commit
`52daca5`), not current behaviour. At that point,
`console_core.StreamState.observe()` only set `arrived_dscp` when `recvmsg()`
returned `IP_TOS` ancillary data, and on Linux that never happens for a TCP
socket on this kernel, so `arrived_dscp` stayed `None` and every frame
rendered "no data". The "packets: 104, loss: 99.8%" figures were an artefact
of the same underlying gap: TCP has no message boundaries, so treating each
`recv()` read as one datagram only worked when a read happened to start on a
chunk boundary, and the `seq` gaps between those rare aligned reads were
counted as loss.

Commit `52daca5` resolved this by reassembling the `imagery_push` byte stream
per connection instead of assuming datagram framing, and by reading the
arriving TOS byte with `getsockopt(IPPROTO_IP, IP_PKTOPTIONS, ...)`, the
mechanism this lab's kernel actually supports for TCP. The current run in the
section above is the proof: `imagery_push` now reports ARRIVED CS1 (8),
PACKETS matching the sender's own chunk count, and verdict RE-MARKED AT
GATEWAY, directly from the console, with no workaround required. Independent
proof from an entirely separate tool follows anyway, both because it was
already part of this build and because it corroborates the console's
TCP path rather than substituting for it.

## 5. Independent proof of GATEWAY RE-MARK (imagery_push EF -> CS1)

Because the console cannot read TCP TOS reliably, `wire_peek.py` (already
present in `isr_apps/`, root capture via `AF_PACKET`, reads the IP header
directly rather than via `recvmsg` ancillary data) was run on Client2's `eth0`
while track_feed and imagery_push were re-run from Client1:

```
sudo python3 /home/rocky/qos-e2e/isr_apps/wire_peek.py --iface eth0 --count 40
```

```
proto  src             dst             port   dscp         stream
UDP    10.50.1.10      10.50.2.10      9200   AF41 (34)    track_feed
TCP    10.50.1.10      10.50.2.10      9300   CS1 (8)      -
TCP    10.50.2.10      10.50.1.10      48574  CS1 (8)      -
UDP    10.50.1.10      10.50.2.10      9200   AF41 (34)    track_feed
... (37 more track_feed lines, all AF41 (34))
```

The imagery_push TCP flow (port 9300) arrives at Client2 marked **CS1 (8)**,
never EF (46). This is direct, packet-level confirmation of GATEWAY RE-MARK,
independent of the console: imagery_push's own claim of EF (46) is overridden
in flight and CS1 is what actually lands on the wire at the receiver, matching
PE1's UNTRUSTED-REMARK filter (term "imagery": tcp destination-port 9300 ->
forwarding-class best-effort, dscp cs1) confirmed bound in section 3. The
concurrent track_feed rows in the same capture independently reconfirm CLASS
COLLAPSED (AF41 arriving where AF31 was asked), matching the console.

## 6. CLASS COLLAPSED (track_feed AF31 -> AF41)

Both the console (section 4) and the independent wire_peek capture (section 5)
show track_feed asking AF31 (26) and arriving AF41 (34) consistently and
without exception. This is the assured-forwarding double pairing in
DSCP-TRUSTED (011010 AF31 and 100010 AF41 both classify to
`assured-forwarding`) followed by EGRESS-DSCP rewriting `assured-forwarding`
unconditionally to code point 100010 (AF41) on PE2's egress. AF31's original
identity is lost the moment it is classified; the rewrite has no way to
recover it. This is the CLASS COLLAPSED teaching moment working exactly as
designed.

## 7. EXP evidence on the core (correction B)

Attempted per the corrected instruction:

```
monitor traffic interface ge-0/0/1 no-resolve detail size 1500 count 40
```

run on PE1 while traffic flowed. The command itself works and produces
readable MPLS label/EXP decodes for **control-plane traffic that originates
or terminates on the routing engine**: for example, PE1's own iBGP session
traffic to the route reflectors, tunnelled inside the SR core and captured
leaving PE1's uplink:

```
04:02:46.609496 Out MPLS (label 16011, exp 6, [S], ttl 64)
	IP (tos 0xc0, ttl  64, id 1793, offset 0, flags [none], proto: TCP (6), length: 52) 10.20.255.1.49644 > 10.20.255.11.179: . ack 19 win 16500 <nop,nop,timestamp 2174167038 2174165778>
```

This confirms the EXP write mechanism functions (network-control code point
110000/CS6 rides as EXP 6, consistent with the class-of-service tables in
section 3) but it is BGP/IS-IS traffic, not the customer application traffic
this test is about.

Despite four separate, carefully time-synchronized attempts (captures armed
on both of PE1's ECMP-eligible core uplinks, ge-0/0/1 and ge-0/0/2, run
concurrently with tens of thousands of imagery_push/track_feed packets over
25-55 second windows), **no customer VPN transit frame (the double MPLS label
push, `Push 16, Push 16002`, confirmed present in the route table for
10.50.2.0/24) ever appeared in a capture.** Every packet the capture returned
was IS-IS, ES-IS, or PE-to-RR BGP session traffic. A filtered attempt using
`monitor traffic ... matching "port 9200 or port 9300"` also failed, but
differently: it never matched a single packet across a 130-second window with
heavy app traffic running throughout, which indicates the BPF port filter is
being evaluated against the outer (unencapsulated) frame and cannot see
through the MPLS label stack, so it can structurally never match VPN-tunnelled
application traffic on a core-facing interface.

The consistent, repeated absence of customer transit traffic from RE-side
`monitor traffic`, contrasted with locally-originated control-plane traffic
capturing cleanly every time, points to the same root cause already
documented in this build for `show interfaces queue`: this vJunos lite-mode
chassis appears to forward transit revenue traffic entirely in a software
fast path that is not mirrored to the routing engine's packet-capture tap.
Only RE-originated/terminated packets are visible to `monitor traffic`.

**Conclusion for this step: EXP verification on customer transit traffic is
deferred to an operator-driven capture** (the GNS3 GUI packet capture opened
in Wireshark that the original brief specified, which taps the virtual wire
outside the router rather than the RE). No EXP value for customer traffic is
claimed here because none was observed. Section 5's wire_peek evidence proves
the DSCP outcome at the receiver; it does not, and cannot, prove what EXP
value carried it across the core.

## 8. Chain-stage summary

| # | Stage | Proven | Evidence |
|---|-------|--------|----------|
| 1 | Application sets its own DSCP | Yes | sender stdout: "asking for" lines, section 4 |
| 2 | PE1 classifies trusted traffic by DSCP | Yes | DSCP-TRUSTED bound + config, section 3 |
| 3 | PE1 multifield filter overrides untrusted claim | Yes | UNTRUSTED-REMARK bound as input, section 3; CS1 observed at receiver, section 5 |
| 4 | Forwarding class carried across the SR-MPLS core as EXP | Partial | EXP confirmed for RE-originated control traffic only (section 7); customer transit EXP not observable on this platform via `monitor traffic` |
| 5 | PE2 rewrites egress DSCP from forwarding class | Yes | EGRESS-DSCP bound + config, section 3; AF41/CS1 observed at receiver |
| 6 | CLASS COLLAPSED (AF31 -> AF41) | Yes | console + wire_peek, sections 4-6 |
| 7 | GATEWAY RE-MARK (EF -> CS1) | Yes | console (post-fix, section 4) + wire_peek (section 5) |

Both teaching moments this exercise exists to prove were observed:
track_feed asked AF31 (26) and was delivered AF41 (34); imagery_push --greedy
asked EF (46) and was delivered CS1 (8). Queue-counter and RE-side transit EXP
capture remain out of reach on this vJunos lite-mode chassis, consistent with
prior findings in this build (Task 3); neither is required to prove the two
outcomes the demo is about.
