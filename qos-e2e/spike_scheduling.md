# Spike: Does the vJunos lite-mode PFE actually schedule traffic, or only report queue placement?

## The question

Does the vJunos lite-mode packet forwarding engine genuinely schedule traffic
under congestion (marked traffic protected, bulk traffic dropped), or does it
only report which queue a packet was placed in without differentially
servicing those queues? The QoS demo for software engineers depends on this
being answered honestly, because a wrong claim in front of an audience is
worse than an honest limitation.

## Method actually used, and why the plan's original method was rejected

The plan called for clamping the PE1-P1 link with a GNS3 link "Bandwidth"
filter. That filter does not exist in GNS3 2.2.59; the live API was queried
and the only link filters available are `frequency_drop`, `packet_loss`,
`delay`, `corrupt`, and `bpf`. Even if it existed, it would be the wrong
instrument: a link filter drops packets on the virtual wire outside the
router, so the router's own egress queue never experiences backpressure and
the scheduler is never exercised. That would have produced a demo that
appeared to run but measured nothing.

Instead, the bottleneck was created inside the router, where the scheduler
actually lives, using class-of-service shaping on PE1's two core-facing
interfaces (ge-0/0/1 to P1, ge-0/0/2 to P2), then two competing UDP flows
(EF-marked and unmarked) were offered well above the shaped rate.

## Setup confirmed before the test

PE1 is a vMX running Junos 25.4R1.12 with `chassis { fpc 0 { lite-mode; } }`
and `network-services enhanced-ip` explicitly configured (`show version`
also lists a "Packet Forwarding Engine Simulation Package", confirming this
is a software-simulated PFE, not silicon). The stage 5 CoS scheme was
verified active on both core-facing interfaces before shaping was applied:

```
scheduler-maps {
    SR-MPLS-SMAP {
        forwarding-class best-effort scheduler BE-SCHEDULER;
        forwarding-class premium-priority scheduler PREMIUM-SCHEDULER;
    }
}
schedulers {
    BE-SCHEDULER {
        transmit-rate percent 70;
        buffer-size percent 70;
    }
    PREMIUM-SCHEDULER {
        buffer-size percent 30;
        priority strict-high;
    }
}
```

`show class-of-service interface ge-0/0/1` confirmed the scheduler-map,
classifier, and rewrite-rules were bound to unit 0 of both ge-0/0/1 and
ge-0/0/2 as expected.

## Step 1: Baseline queue counters

```
show interfaces queue ge-0/0/1
Physical interface: ge-0/0/1, Enabled, Physical link is Up
  Interface index: 151, SNMP ifIndex: 529

show interfaces queue ge-0/0/2
Physical interface: ge-0/0/2, Enabled, Physical link is Up
  Interface index: 152, SNMP ifIndex: 530
```

This is the complete, verbatim output. Neither invocation returns a
per-queue breakdown (no "Queue: 0 best-effort", no Queued/Transmitted/Tail-
dropped packet counts) despite CoS being actively configured on both
interfaces. This was re-verified with `| display xml`: the RPC reply
contains only a bare `<physical-interface>` element with name, admin/oper
status, and indices, no `<queue>` child elements at all, for every
interface on the box (checked via `show interfaces queue` with no argument
across all ~40 interfaces on PE1). This is a structural property of this
platform's `show interfaces queue` RPC, not a symptom of idle traffic; it
did not change later in the test even under heavy load. A search for an
alternate counter source via `request pfe execute target fpc0 command
"show cos halp ..."` did not turn up per-interface per-queue drop counters
either; that path is undocumented and was not pursued further since it
would be off the plan's instrument entirely.

Because no per-queue Transmitted/Dropped counters exist to diff, the test
fell back to the physical/logical interface Traffic statistics counters
(from `show interfaces <ifd> extensive`, also captured at each stage) as
the substitute measurement of whether the shaper was doing anything to
aggregate throughput.

## Step 2: Apply shaping to both core-facing interfaces

```
set class-of-service interfaces ge-0/0/1 shaping-rate 5m
set class-of-service interfaces ge-0/0/2 shaping-rate 5m
commit
```

Commit succeeded: `commit complete`. Verified with
`show configuration class-of-service interfaces`; both ge-0/0/1 and
ge-0/0/2 showed `shaping-rate 5m;` alongside the existing scheduler-map
binding. `show interfaces ge-0/0/1 extensive` also showed the scheduler
math recompute against the new 5 Mbps envelope: best-effort's absolute
bandwidth column changed from `700000000` (70% of the 1 Gbps physical
link) to `3500000` (70% of 5 Mbps), confirming the configuration was
accepted and processed, not merely stored inertly.

## Step 3-4: Competing flows and queue capture during/after

iperf3 servers started on Client2 (10.1.1.65): `-s -p 5301 -D`,
`-s -p 5302 -D`. From Client1 (10.1.1.61), both flows run concurrently for
30 seconds, 20 Mbps offered each (40 Mbps combined into a 5 Mbps shaper):

```
iperf3 -c 10.50.2.10 -p 5301 -u -b 20M -t 30 --tos 184   # EF, queue 5
iperf3 -c 10.50.2.10 -p 5302 -u -b 20M -t 30              # unmarked, queue 0
```

`show interfaces queue ge-0/0/1` and `ge-0/0/2` were re-run mid-flow and
immediately after. Both returned the identical two-line output shown in
Step 1, unchanged by 40 Mbps of offered load. The queue-level instrument
never populated at any point in the test.

The interface-level counters, captured mid-flow via
`show interfaces ge-0/0/1 extensive`, told the real story:

```
Traffic statistics (mid-flow, ge-0/0/1):
   Output bytes  :            112731811             40778936 bps
   Output packets:                81486                 3453 pps
CoS information:
    0 best-effort            70        3500000    70              0      low    none
    5 premium-priority        r              r    30              0 strict-high    none
```

Output rate on ge-0/0/1 was running at ~40.78 Mbps, essentially the full
sum of the two 20 Mbps offered flows, against a configured shaping-rate of
5 Mbps. ge-0/0/2 stayed flat at background levels throughout (output
~952 bps, packet count static at ~5502-5517), confirming ECMP placed both
UDP flows entirely on the ge-0/0/1 (P1) path and never touched ge-0/0/2, so
ge-0/0/2's shaper was never tested by traffic in this run.

iperf3 results confirm the same story from the receiver side. Both flows
completed at their full requested rate with zero loss:

```
EF flow (--tos 184, queue 5):
[  5]   0.00-30.06  sec  71.5 MBytes  20.0 Mbits/sec  0.551 ms  0/51792 (0%)  receiver

BE flow (unmarked, queue 0):
[  5]   0.00-30.05  sec  71.5 MBytes  20.0 Mbits/sec  0.508 ms  0/51794 (0%)  receiver
```

## Step 5: Deltas

No per-queue Transmitted/Dropped packet counters exist on this platform to
diff (Step 1 finding), so the queue-0-vs-queue-5 delta the plan asked for
cannot be computed from `show interfaces queue`. The deltas that could be
measured:

| Metric | Queue 0 (best-effort, unmarked) | Queue 5 (premium, EF/tos 184) |
|---|---|---|
| Datagrams sent | 51,794 | 51,795 |
| Datagrams lost (iperf3 receiver) | 0 (0%) | 0 (0%) |
| Delta in drops vs baseline | 0 | 0 |

Interface-level delta on ge-0/0/1 (physical, both queues combined):
output packets went from 5,419 (pre-test) to 109,140 (post-test) at an
observed mid-flow rate of ~40.8 Mbps sustained, against a committed
shaping-rate of 5 Mbps, i.e. roughly 8x the shaped ceiling, for the full
30-second run, with zero packets dropped anywhere in the path.

## Conclusion

**Third outcome: shaping is not being enforced at all.** 40 Mbps offered
into a nominally 5 Mbps shaper produced zero drops in either queue and
sustained throughput around 40.8 Mbps, roughly eight times the configured
ceiling, for the full 30-second test. The configuration was accepted,
committed without error, and even changed the displayed scheduler math
(best-effort's absolute bandwidth recalculated from 700 Mbps to 3.5 Mbps
off the new 5 Mbps base), so this is not a case of the command being
silently rejected. The shaper simply has no effect on the forwarded rate
in this lite-mode PFE.

This result cannot by itself distinguish "the PFE schedules but not under
this kind of pressure" from "the PFE never schedules"; it only shows that
this specific instrument (interface shaping-rate) does not create real
congestion on this platform. It also surfaced a second, independent
finding worth carrying into the guide: `show interfaces queue` returns no
per-queue counters whatsoever on this vJunos lite-mode chassis (confirmed
via `| display xml`, which shows the RPC has no `<queue>` elements to
return), regardless of load. So even if congestion had been achieved by
some other means, this CLI path would not have been able to show the
premium-vs-best-effort split the demo wants to display.

For the QoS demo, the honest framing is: *"here is where your packet gets
placed by DSCP-to-forwarding-class classification and rewrite (which is
real and verifiable via `show class-of-service interface`), and here is
what that placement buys you on hardware that actually enforces shaping
and per-queue scheduling under load, which this lab's software-simulated
PFE does not."* Showing marked traffic surviving congestion while bulk
traffic drops is not a claim this lab environment can support.

### What would settle it further

To determine whether the underlying scheduler (strict-high priority for
queue 5, transmit-rate percent for queue 0) does anything at all when
congestion is real, congestion would need to be created by a mechanism
this platform actually enforces, for example a real bandwidth ceiling
upstream of PE1 (a lower-speed physical/virtual link, or an ingress
policer that does show effect, since ingress policing is a different code
path than the shaping-rate egress shaper tested here) rather than
`shaping-rate`. That is a separate, larger experiment than this spike's
scope and was not attempted here to avoid disturbing lab state further.

## Cleanup

```
delete class-of-service interfaces ge-0/0/1 shaping-rate
delete class-of-service interfaces ge-0/0/2 shaping-rate
commit
```

Commit succeeded (`commit complete`); `show configuration class-of-service
interfaces` confirmed both `shaping-rate` lines were gone, leaving only
the original scheduler-map/classifier/rewrite-rules bindings. iperf3
servers on Client2 were killed. Post-cleanup ping Client1 to Client2
confirmed 0% loss:

```
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 11.278/11.810/12.451/0.484 ms
```

No `restart routing` was performed at any point in this test, per
instruction, to avoid disturbing the state being measured.
