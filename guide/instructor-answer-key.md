# Instructor Answer Key

For instructor use only. Each section identifies the exact fault to inject, the expected diagnostic output using the same verify commands from the student guide (`modules.py`), the fix commands, and a model brief-back answer. All fault and fix commands use real topology values from `training-nodes.csv` and `training-links.csv`. Topology reference: PE1 loopback 10.20.255.1 (SID 16001), PE2 loopback 10.20.255.2 (SID 16002), C1 loopback 10.20.255.11 (SID 16011), C2 loopback 10.20.255.12 (SID 16012), P1 loopback 10.20.255.21 (SID 16021), P2 loopback 10.20.255.22 (SID 16022), P3 loopback 10.20.255.23 (SID 16023), P4 loopback 10.20.255.24 (SID 16024). SRGB start 16000, range 8000.

---

## M0 Junos Fundamentals

- **Fault to inject:** In configuration mode on PE1, issue `set system host-name PE1-BROKEN` then type `exit` without running `commit`. This leaves a dangling candidate edit in the configuration database.

- **Expected symptom:** In operational mode, `show configuration | display set | match host-name` still returns `set system host-name PE1` because the committed database is unchanged. `show system commit` shows the last commit predates the fault injection with no new entry for the hostname change. The mismatch only becomes visible when entering configuration mode and running `show | compare`, which outputs `[edit system] + host-name PE1-BROKEN;`.

- **Fix:** Enter configuration mode, run `rollback 0`, then `commit`.

- **Model brief:** Junos maintains two separate configuration databases: the active (committed) database, which drives the running network state, and the candidate database, which holds all pending edits. The `set` command writes only to the candidate; nothing changes in the network until `commit` is issued. Running `rollback 0` reloads the last committed snapshot into the candidate, discarding all pending edits. This is fundamentally different from IOS `write memory`, which simply saves the running config to NVRAM with no staging or atomic-swap step.

---

## M1 IS-IS Underlay

- **Fault to inject:** `set protocols isis interface ge-0/0/2.0 level 2 metric 9000` on C1. C1 ge-0/0/2 is the plane-A link between C1 (10.20.0.9) and P3 (10.20.0.10) in the 10.20.0.8/30 subnet.

- **Expected symptom:** `show isis adjacency` on all routers shows all neighbors in the Up state. `show isis database` for C1 shows ge-0/0/2 advertised with metric 9000 instead of the baseline 10. `show isis interface` on C1 confirms the same elevated metric. `traceroute 10.20.255.2` from PE1 exits via ge-0/0/2 (plane B: PE1-C2-PE2, metric 40) rather than the expected plane-A path; `show route 10.20.255.2` shows the plane-A cost inflated to 9030 (10 + 10 + 9000 + 10).

- **Fix:** `delete protocols isis interface ge-0/0/2.0 level 2 metric 9000` on C1, then `commit`. Verify `show route 10.20.255.2` on PE1 shows plane A restored at metric 40 and ECMP with plane B.

- **Model brief:** IS-IS SPF selects the path with the lowest cumulative link-state metric, not the fewest hops. Adjacency state and metric are independent: all neighbors remain Up because metric configuration does not affect neighbor formation. A single inflated metric on one link is enough to shift the entire SPF tree, silently rerouting all transit traffic without any adjacency alarm. The student must look at the IS-IS database and routing table, not just adjacency state, to find this class of fault.

---

## M2 SR-MPLS Transport

- **Fault to inject:** `set protocols isis source-packet-routing node-segment ipv4-index 2` on P3. P3's correct SID index is 23 (absolute label 16023). Assigning index 2 causes P3 to advertise label 16002, which is PE2's node-SID (SRGB-start 16000 + index 2).

- **Expected symptom:** `show route table mpls.0 | match 16002` on C1 resolves label 16002 to a SINGLE next-hop toward the nearer advertiser (P3 via ge-0/0/2) instead of toward PE2, because when two routers advertise the same node-SID index Junos installs the label toward the nearest one by IS-IS SPF distance. `show route table inet.3` on PE1 for 10.20.255.2 shows an ambiguous or looping label-push entry because IS-IS resolves the SID to the nearest advertising router. `traceroute mpls segment-routing isis 10.20.255.2` from PE1 times out or returns inconsistent hop counts because transit routers swap label 16002 toward P3 instead of PE2.

- **Fix:** `set protocols isis source-packet-routing node-segment ipv4-index 23` on P3, then `commit`. Wait for IS-IS convergence, then verify `show route table mpls.0 | match 16002` returns a single next-hop pointing toward PE2 and `traceroute mpls segment-routing isis 10.20.255.2` completes end to end.

- **Model brief:** Each router's node-SID index must be globally unique within the SRGB. The absolute label is SRGB-start plus the index: with SRGB start 16000 and index 2, the label is 16002. When two routers advertise the same index, every transit router's MPLS forwarding table develops a split-brain entry for that label. The label is resolved to the topologically nearest advertising router, which may be the wrong destination, causing label-switched path loops or black holes. The fault is diagnosable only from the MPLS and inet.3 tables; the IS-IS adjacency table remains clean.

---

## M3 L3VPN Services

- **Fault to inject:** On PE1, change the CUST_B VRF route-target to a non-matching value:
  ```
  delete routing-instances CUST_B vrf-target
  set routing-instances CUST_B vrf-target target:64512:999
  commit
  ```
  The correct CUST_B route-target is `target:64512:200`. After this change, PE1 no longer imports CUST_B VPN routes from the route reflectors (C1 at 10.20.255.11 and C2 at 10.20.255.12), and PE1 exports CUST_B routes with the wrong community so PE2 drops them as well.

- **Expected symptom:** `show route table CUST_A.inet.0` on PE1 is unaffected and shows full reachability, confirming the L3VPN transport layer is healthy and isolating the fault to CUST_B. `show bgp summary` shows all BGP sessions Up, giving no alarm. `show route receive-protocol bgp 10.20.255.11 table bgp.l3vpn.0` on PE1 shows CUST_B VPN routes present in the global BGP l3vpn RIB (they carry `target:64512:200`) but those routes are absent from `show route table CUST_B.inet.0` because the local import RT `target:64512:999` does not match.

- **Fix:** On PE1:
  ```
  delete routing-instances CUST_B vrf-target
  set routing-instances CUST_B vrf-target target:64512:200
  commit
  ```
  Verify `show route table CUST_B.inet.0` shows remote CE routes within one BGP refresh cycle.

- **Model brief:** The route distinguisher makes each VPN prefix globally unique in bgp.l3vpn.0, which is why two customers can use the same RFC 1918 subnet without conflict. The route-target community is the import/export filter that controls which prefixes land in which VRF. A mismatched import RT silently drops all VPN routes that carry the correct RT; BGP still receives and holds them in bgp.l3vpn.0, but they are never installed in the VRF table. Pings fail with no IGP or BGP session alarm, which makes RT mismatches one of the most common and hardest-to-spot silent L3VPN faults.

---

## M4 Traffic Engineering (Flex-Algo)

- **Fault to inject:** `deactivate protocols isis interface ge-0/0/1.0 delay-measurement` on P3. P3 ge-0/0/1 is the plane-A link between P3 (10.20.0.10) and C1 (10.20.0.9). Without delay measurement active on this interface, P3 cannot advertise an APP-LRTT delay sub-TLV for the P3-C1 link.

- **Expected symptom:** `show isis database extensive | match delay` on P3 shows no delay sub-TLV for ge-0/0/1, while all other plane-A and plane-B links show valid advertised delay values. `show route table inetcolor.0` on PE1 for the 10.20.255.2 transport route in inetcolor.0 associated with color 129 (Flex-Algo 129, delay-optimized) shows either a missing route or a path that avoids the P3-C1 segment because algo-129 treats a missing delay metric as infinite cost. `show route table CUST_B.inet.0 detail` on PE1 confirms CUST_B (which is steered onto algo-129) is no longer following the expected delay-optimized path toward PE2.

- **Fix:** `activate protocols isis interface ge-0/0/1.0 delay-measurement` on P3, then `commit`. After IS-IS reconverges, verify `show isis database extensive | match delay` shows the APP-LRTT sub-TLV restored for ge-0/0/1 and `show route table inetcolor.0` shows `10.20.255.2-129` resuming the correct path.

- **Model brief:** Flex-Algo 129 builds a separate SPF tree using link-delay metrics distributed by IS-IS as APP-LRTT sub-TLVs. Each participating interface must actively measure and advertise its delay; the algo has no fallback to the IGP metric. A single interface missing its delay advertisement is treated as infinite delay, forcing algo-129 to route around that link. Because IGP-metric-based algo-128 is unaffected, CUST_A traffic continues normally while CUST_B, which is color-steered onto algo-129, silently takes a suboptimal or broken path with no session-layer alarm.

---

## M5 Quality of Service

- **Fault to inject:** `delete class-of-service interfaces ge-0/0/1 unit 0 rewrite-rules exp SR-MPLS-EXP-REWRITE` on P1. P1 ge-0/0/1 is the plane-A link between P1 (10.20.0.2) and PE1 (10.20.0.1) in the 10.20.0.0/30 subnet. Removing the EXP rewrite rule means all MPLS frames leaving P1 on this interface carry EXP bits of zero.

- **Expected symptom:** `show class-of-service interface ge-0/0/1` on P1 shows no Rewrite-Output (exp) entry bound to unit 0 (the rewrite rule is gone). Egress queue counters from `show interfaces queue ge-0/0/1` do NOT change, because queue placement is set by ingress classification, not by the rewrite rule. The true data-plane symptom is a GNS3 packet capture on the P1 to PE1 link showing MPLS EXP = 000 on premium traffic that should carry EXP = 101.

- **Fix:** `set class-of-service interfaces ge-0/0/1 unit 0 rewrite-rules exp SR-MPLS-EXP-REWRITE` on P1, then `commit`. Verify `show class-of-service interface ge-0/0/1` shows `Rewrite-Output SR-MPLS-EXP-REWRITE exp (mpls-any)` on the logical interface, and `show interfaces queue ge-0/0/1` shows premium-priority traffic in the correct queue.

- **Model brief:** The DSCP-to-forwarding-class classification happens at the ingress PE as traffic enters the VRF. The EXP rewrite rule translates the forwarding-class assignment into MPLS EXP bits as packets leave each transit interface, propagating the QoS intent hop by hop across the core. Without the rewrite rule on a transit interface, downstream routers receive EXP 000 and queue everything as best-effort, collapsing all service differentiation from that hop onward regardless of what the ingress PE marked. The fault is invisible at the session level; only queue statistics and a packet capture reveal it.

---

## M6 Fast Reroute (TI-LFA)

- **Fault to inject:** `deactivate groups ISIS-PARAMETERS protocols isis backup-spf-options use-post-convergence-lfa` then commit. (This is the mandate-negation the module exists to teach restoring; do not leave it negated.)

- **Expected symptom:** `show isis backup spf results` shows no post-convergence backup coverage and `show route 10.20.255.2 detail` shows a primary next-hop with no Backup next-hop; `show route forwarding-table destination 10.20.255.2` confirms no backup in the FIB.

- **Fix:** `activate groups ISIS-PARAMETERS protocols isis backup-spf-options use-post-convergence-lfa` then commit; the mandate is restored and TI-LFA backups reappear.

- **Model brief:** TI-LFA pre-computes a repair path using post-convergence labels: the backup next-hop encapsulates a label stack that steers traffic to the destination as if the failed link were already removed from the topology. This pre-computation is controlled by `use-post-convergence-lfa` in the `ISIS-PARAMETERS` group mandate. Deactivating that mandate at the group level removes the pre-computed backup for all IS-IS interfaces simultaneously, leaving traffic unprotected during the re-convergence window after a failure. Because the mandate is applied via a group, deactivating it without removing it is sufficient to break protection while leaving the underlying stanza in place, making this class of fault easy to miss in a group-heavy config.

---

## M7 Quality of Service (End-to-End DSCP Marking)

- **Fault to inject:** `delete interfaces ge-0/0/3 unit 100 family inet filter input UNTRUSTED-REMARK` on PE1, then `commit`. The `UNTRUSTED-REMARK` filter itself is untouched: its `imagery` term (TCP destination-port 9300, forwarding-class best-effort, `then dscp cs1`) still exists in the configuration, correctly written. What is removed is the one line that applies it to the customer-facing logical unit. A filter that is defined but not bound to any interface evaluates nothing.

- **Expected symptom:** Every "is it configured" check looks healthy, which is what makes this fault worth teaching. `show class-of-service interface ge-0/0/3` on PE1 still shows `Classifier DSCP-TRUSTED` bound to `ge-0/0/3.100`. `show firewall filter UNTRUSTED-REMARK` (or `show configuration firewall family inet filter UNTRUSTED-REMARK`) still shows the filter fully defined with its `imagery` term intact, because that command reports any configured filter whether or not it is applied anywhere. The only router-side command that reveals the fault is `show configuration interfaces ge-0/0/3 unit 100 family inet filter`, which comes back empty where it should show `input UNTRUSTED-REMARK;`. On the receiving application's own output, run `python3 imagery_push.py --greedy --duration 30` on Client1 while the console runs on Client2: the ledger shows `imagery_push EF (46) EF (46) ... honored` instead of the expected `RE-MARKED AT GATEWAY`, and `qos_trace.py imagery_push --greedy` against the live routers reports `BA=on MF=OFF -> best-effort (forced)` never appearing, i.e. the claimed EF rides through uncontested. This matches the audit exactly: a bulk transfer is receiving EF treatment end to end even though the BA classifier, the core EXP marking and the L3VPN are all correct, because the one control designed to disbelieve the customer's claim was never wired in.

- **Fix:** `set interfaces ge-0/0/3 unit 100 family inet filter input UNTRUSTED-REMARK` on PE1, then `commit`. Verify on the router with `show configuration interfaces ge-0/0/3 unit 100 family inet filter`, which should now show `input UNTRUSTED-REMARK;`. Do not stop there: the task requires proof from the receiving application's own output, not only the router CLI. Re-run `python3 imagery_push.py --greedy --duration 30` on Client1 with the console running on Client2 (or `wire_peek.py` capturing on Client2's `eth0`) and confirm the ledger now reads `imagery_push EF (46) CS1 (8) ... RE-MARKED AT GATEWAY`, i.e. the bulk transfer's own claimed marking of EF is what it asked for, and CS1 is what actually arrived. That before/after contrast at the receiving endpoint, not a second router `show` command, is the evidence the audit needs.

- **Model brief:** A behaviour-aggregate (BA) classifier is not a security control; it maps whatever DSCP arrives to a forwarding class and believes the customer completely, which is exactly what it is designed to do. Disbelieving a customer's marking requires a second, independent control, a multifield (MF) filter that classifies on flow identity rather than on the claim, applied in the input direction on the customer-facing logical unit so its decision overrides the BA result before anything downstream acts on it. Defining that filter is not the same as applying it: Junos will commit a filter that exists nowhere in any interface's configuration without complaint, and every classifier- and rewrite-facing `show class-of-service` command continues to report the rest of the chain as correct, because it is. The gap is invisible to configuration-presence checks (this is the same class of gap `validate_lab_configs.py` closes for `EGRESS-DSCP`: checking that an object is bound is not the same as checking that it is defined, and neither alone is the same as checking that it is both) and invisible to the router CLI in general. Only a packet actually being classified, and the receiving application reporting what arrived versus what was asked for, proves the control is in the forwarding path rather than merely in the configuration.

---

## M8 Capstone Break/Fix and Brief

Three simultaneous faults are active. Diagnose using the eight-step troubleshooting flow from `guide/troubleshooting.md`. Resolve in order: underlay first, then transport, then service. Each layer must be verified and restored before the next layer's fault becomes cleanly observable.

**Fault to inject**

1. **Underlay metric blackhole on C1:** `set protocols isis interface ge-0/0/2.0 level 2 metric 9000` on C1. C1 ge-0/0/2 is the plane-A link between C1 (10.20.0.9) and P3 (10.20.0.10). Plane-A path (PE1-C1-PE2) cost becomes 9030; all traffic shifts to plane B (PE1-C2-PE2, cost 40).

2. **Transport SID clash on P2:** `set protocols isis source-packet-routing node-segment ipv4-index 2` on P2. P2's correct SID index is 22 (label 16022). Assigning index 2 makes P2 also advertise label 16002, which is PE2's node-SID. P2 is on plane B, the path that fault 1 has just forced all traffic onto.

3. **VRF RT mismatch on PE2:**
   ```
   delete routing-instances CUST_A vrf-target
   set routing-instances CUST_A vrf-target target:64512:999
   commit
   ```
   on PE2. PE2's CUST_A VRF no longer imports routes carrying the correct `target:64512:100`. Even after the underlay and transport are restored, CUST_A service remains broken at PE2.

**Expected symptom**

Work through Appendix A in order:

- **Appendix A Step 1 (IS-IS adjacencies):** `show isis adjacency` on all routers shows all neighbors Up. No adjacency-layer issue.
- **IS-IS database check (related to Appendix A Step 6):** `show isis database` for C1 reveals ge-0/0/2 with metric 9000. Cross-reference with `show route 10.20.255.2` on PE1 showing plane A at cost 9030 and plane B at 40, confirming the metric blackhole.
- **Appendix A Step 7 (transit label table):** `show route table mpls.0 | match 16002` on PE1 or P1 resolves label 16002 to a SINGLE next-hop toward P2 (the nearer advertiser on plane B) instead of toward PE2, because Junos installs the label toward the nearest IS-IS SPF advertiser. The SID clash on the active plane-B path is now visible.
- **Appendix A Step 8 (tunnel resolution):** `show route 10.20.255.2 table inet.3 extensive` on PE1 shows the label-push entry resolving to P2 rather than PE2, or shows an unresolvable path, confirming the transport tunnel is broken.
- **Appendix A Step 3 (VRF service steering, after faults 1 and 2 are fixed):** `show route table CUST_A.inet.0` on PE2 is empty despite the transport layer being healthy. `show route receive-protocol bgp 10.20.255.11 table bgp.l3vpn.0` on PE2 shows CUST_A VPN routes present in bgp.l3vpn.0 (carrying `target:64512:100`) but not imported into the VRF because the local import RT is `target:64512:999`.

Note: Appendix A Step 3 (VRF/service verification) is intentionally performed last, after the underlay and transport faults are cleared, because a broken lower layer masks the service-layer fault.

**Fix**

1. Fix the underlay on C1: `delete protocols isis interface ge-0/0/2.0 level 2 metric 9000`, then `commit`. Verify `show route 10.20.255.2` on PE1 shows plane A restored to metric 40 with ECMP across both planes.
2. Fix the SID clash on P2: `set protocols isis source-packet-routing node-segment ipv4-index 22`, then `commit`. Verify `show route table mpls.0 | match 16002` on PE1 returns a single next-hop toward PE2 and `traceroute mpls segment-routing isis 10.20.255.2` from PE1 completes end to end.
3. Fix the RT mismatch on PE2:
   ```
   delete routing-instances CUST_A vrf-target
   set routing-instances CUST_A vrf-target target:64512:100
   commit
   ```
   Verify `show route table CUST_A.inet.0` on PE2 shows CE1's routes and end-to-end pings between CE1 and CE2 succeed.

**Model brief**

The SR-MPLS stack is strictly layered and each layer depends on the one below it. IS-IS underlay drives the SPF topology, which determines both the IGP next-hop and the set of node-SIDs reachable from each router. A metric fault shifts the IGP path, which silently redirects all SR label-switched paths because SIDs resolve via the same SPF tree. A SID clash breaks the MPLS forwarding table on whichever path IS-IS has selected: fixing the underlay alone is not sufficient because the restored path still hits the clashed label. Only after both underlay and transport are verified healthy does the BGP/VPN service layer become cleanly diagnosable, because BGP session state is independent of the transport and routes continue to arrive at the PE correctly, stranded in bgp.l3vpn.0 until the VRF import policy accepts them. Diagnosing in layer order (IS-IS adjacency, then IS-IS topology and MPLS table, then inet.3 tunnel, then VRF/BGP) is the only reliable approach to a multi-fault scenario where faults at lower layers mask or mimic faults at higher layers.
