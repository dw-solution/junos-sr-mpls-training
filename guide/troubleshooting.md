# SR-MPLS Eight-Step Troubleshooting Guide

This guide covers the verification and troubleshooting flow for the GNS3 SR-MPLS training lab. Topology reference: PE1 loopback 10.20.255.1 (node-SID 16001), PE2 loopback 10.20.255.2 (SID 16002), C1 10.20.255.11 (SID 16011), C2 10.20.255.12 (SID 16012), P1 10.20.255.21 (SID 16021), P2 10.20.255.22 (SID 16022), P3 10.20.255.23 (SID 16023), P4 10.20.255.24 (SID 16024). SRGB start 16000, range 8000. VRFs: CUST_A (RT target:64512:100, algo 128), CUST_B (RT target:64512:200, algo 129 delay-optimized). Plane A: PE1-C1-PE2. Plane B: PE1-C2-PE2.

Work through the steps in order: underlay before transport, transport before service. A broken lower layer masks faults at higher layers.

---

### Step 1: Verify IS-IS Underlay Adjacencies

**Goal:** Confirm every router has formed IS-IS Level 2 adjacencies with all expected neighbors. If any adjacency is down, no SR SIDs are distributed and every higher-layer check is unreliable.

**Command:** `show isis adjacency`

*What to look for: Every neighbor listed must show State `Up`. Cross-reference the expected neighbor count for each router against the topology (PE1 and PE2 each have two plane neighbors; P and C routers have two to three neighbors). A `Down` or `Init` state indicates a physical link, MTU, or IS-IS family-iso configuration fault.*

```
root@PE1> show isis adjacency
Interface             System         L State        Hold (secs)
ge-0/0/0.0            P1             2  Up                    23
ge-0/0/1.0            P2             2  Up                    19
```

---

### Step 2: Verify Flexible Algorithms and Transport Classes (`inetcolor.0`)

**Goal:** Confirm the router computes both the IGP-metric path (algo 128) and the delay-optimized path (algo 129), and pushes the correct node-SID label for each.

**Command:** `show route table inetcolor.0`

*What to look for: For each remote PE loopback, expect two colored route entries: one ending in `-128` and one ending in `-129`. From PE1, `10.20.255.2-128<c>/64` and `10.20.255.2-129<c>/64` must both appear. If the `-129` entry is missing, a `delay-measurement` stanza is not advertising APP-LRTT sub-TLVs on one or more interfaces, or Flex-Algo 129 has not converged.*

```
root@PE1> show route table inetcolor.0
10.20.255.2-128<c>/64
                   *[L-ISIS/14] 00:15:32, metric 40
                    >  to 10.20.0.2 via ge-0/0/0.0, Push 16002
10.20.255.2-129<c>/64
                   *[L-ISIS/14] 00:15:32, metric 300
                    >  to 10.20.0.2 via ge-0/0/0.0, Push 16002
```

---

### Step 3: Verify VRF Service Steering (BGP Color Mapping)

**Goal:** Confirm that CUST_A and CUST_B routes carry the correct VPN route-target and, for CUST_B, the correct BGP color community that steers traffic onto algo 129.

**Command:** `show route <CE-destination-prefix> extensive table CUST_B.inet.0 | match Communities`

*What to look for: CUST_A routes must carry `target:64512:100`. CUST_B routes must carry `target:64512:200` and `color:0:129`. If `color:0:129` is absent, CUST_B falls back to best-effort (algo 128). If the route-target does not match the local VRF import policy, the route does not appear in the VRF table at all, even though it is present in `bgp.l3vpn.0`. Confirm presence in bgp.l3vpn.0 with `show route receive-protocol bgp 10.20.255.11 table bgp.l3vpn.0`.*

```
root@PE1> show route 192.168.20.0/24 extensive table CUST_B.inet.0 | match Communities
                Communities: target:64512:200 color:0:129
```

---

### Step 4: Verify Quality of Service Interface Mapping

**Goal:** Confirm every transit interface applies the correct scheduler map and EXP rewrite and classifier rules.

**Command:** `show class-of-service interface <interface-name>`

*What to look for: The physical interface must show `Scheduler map: SR-MPLS-SMAP`. The logical `.0` sub-interface must list both `Rewrite-Output SR-MPLS-EXP-REWRITE exp (mpls-any)` and `Classifier SR-MPLS-EXP-CLASS exp`. A missing rewrite rule causes all MPLS frames leaving that interface to carry EXP 000, collapsing QoS differentiation from that hop onward.*

```
root@P1> show class-of-service interface ge-0/0/1
Physical interface: ge-0/0/1, Index: 151
  Scheduler map: SR-MPLS-SMAP, Index: 57302

  Logical interface: ge-0/0/1.0, Index: 343
Object                  Name                   Type
Rewrite-Output          SR-MPLS-EXP-REWRITE    exp (mpls-any)
Classifier              SR-MPLS-EXP-CLASS      exp
```

---

### Step 5: Verify QoS Rewrite Rules (EXP Marking)

**Goal:** Confirm the EXP rewrite rule maps each forwarding class to the correct MPLS EXP code point so core routers can apply priority queuing.

**Command:** `show class-of-service rewrite-rule name SR-MPLS-EXP-REWRITE`

*What to look for: `premium-priority` at low loss priority must map to code point `101` (EXP 5). `best-effort` maps to `000`. If `premium-priority` maps to `000`, CUST_B traffic enters the best-effort queue at every transit router regardless of the PE classification.*

```
root@PE1> show class-of-service rewrite-rule name SR-MPLS-EXP-REWRITE
Rewrite rule: SR-MPLS-EXP-REWRITE, Code point type: exp
  Forwarding class          Loss priority    Code point
  best-effort               low              000
  premium-priority          low              101
```

---

### Step 6: Verify MPLS Label Distribution and TI-LFA (IS-IS Route)

**Goal:** Confirm IS-IS has computed the correct shortest path to a remote node-SID and that TI-LFA has pre-computed a loop-free backup path.

**Command:** `show isis route <remote-loopback> extensive`

*What to look for: `TILFA computed MPLS paths` with `Valid: 1` means a pre-programmed backup is ready. From PE1, `show isis route 10.20.255.2 extensive` should show plane-A and plane-B primary paths toward PE2 (SID 16002) and a valid TI-LFA backup. `Valid: 0` indicates the `use-post-convergence-lfa` mandate is missing or deactivated.*

```
root@PE1> show isis route 10.20.255.2 extensive
10.20.255.2/32  L2  metric 40
  ge-0/0/0.0  IPV4 P1
  ge-0/0/1.0  IPV4 P2
  TILFA computed MPLS paths, Count:1, Valid:1
      PathId:0, SID count:1
```

---

### Step 7: Verify the Data Plane: Transit Label Table (`mpls.0`)

**Goal:** Confirm the router has programmed the MPLS forwarding table with the correct Swap or Pop actions for each node-SID.

**Command:** `show route table mpls.0 | match <SID-label>`

*What to look for: Each node-SID must resolve to a single authoritative next-hop. From any transit router, `show route table mpls.0 | match 16002` must show a single Swap entry pointing toward PE2. If the label resolves to two next-hops at different routers, a SID clash (duplicate `ipv4-index`) is present. If the label is absent entirely, IS-IS has not distributed the SID for that router.*

```
root@P1> show route table mpls.0 | match 16002
16002              *[L-ISIS/14] 00:12:14, metric 30
                    >  to 10.20.0.6 via ge-0/0/1.0, Swap 16002
```

---

### Step 8: Verify End-to-End Tunnel Resolution (`inet.3`)

**Goal:** Confirm BGP can resolve the remote PE loopback to a valid SR-MPLS transport tunnel. This is the final proof that the underlay will carry VPN traffic.

**Command:** `show route <remote-pe-loopback> table inet.3 extensive`

*What to look for: `Label operation: Push <node-SID>` is required. From PE1, `show route 10.20.255.2 table inet.3 extensive` must show `Push 16002`. If `inet.3` has no entry for the remote PE, or the label operation is wrong, all VRF routes for CUST_A and CUST_B remain stranded in `bgp.l3vpn.0` and are unreachable regardless of BGP session state or correct route-targets.*

```
root@PE1> show route 10.20.255.2 table inet.3 extensive
inet.3: 7 destinations, 7 routes (7 active, 0 holddown, 0 hidden)
10.20.255.2/32 (1 entry, 1 announced)
        *L-ISIS Preference: 14
                Next hop: 10.20.0.2 via ge-0/0/0.0, selected
                Label operation: Push 16002
                Label TTL action: prop-ttl
```
