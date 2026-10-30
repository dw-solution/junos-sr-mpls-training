# GNS3 SR-MPLS Training Lab Design

Date: 2026-06-28
Status: Approved for planning
Owner: Network Automation (Senior NAE persona)

## 1. Purpose

Build a portable GNS3 training lab that takes a Junos-new team from fundamentals to mastery-level command of SR-MPLS on Junos, so each member can configure, validate, troubleshoot, and brief the technology at a professional level. The lab mirrors the feature stack of the production 18-node vMX lab (IS-IS underlay, SR-MPLS transport, L3VPN services, Flexible-Algorithm traffic engineering, class-of-service, and TI-LFA fast reroute) on a slimmed, clean teaching topology.

The instructor builds and validates the project on the local GNS3 server (10.1.1.5) first, then exports a portable project the team imports onto their own GNS3 server.

## 2. Decisions (locked)

| Area | Decision |
| --- | --- |
| Platform | vJunos-router (MX lineage). One image, maximum reuse of existing config patterns. |
| Topology size | Slimmed teaching fabric: 10 vJunos-router nodes plus 2 lightweight Linux clients. Host has 64GB+. |
| Audience | New to Junos. Course includes a fundamentals on-ramp before SR content. |
| Tasking style | Hybrid: progressive build, then injected break/fix, plus "brief it back" mastery checkpoints. |
| Image portability | Image pre-installed and version-pinned on both servers. Export does NOT bundle base images. |
| Endpoints | vJunos-router CEs (dynamic eBGP PE-CE, multi-subnet customers) with Linux clients behind them for marked traffic. |
| Guide format | Printable .docx via the standard build_docx.py plus snaps/ plus screenshot-index.md workflow, with an instructor answer key. |
| Time model | Self-paced modules with checkpoints. |
| Addressing | Clean teaching scheme (readable loopbacks and node-SIDs), faithful to lab conventions. |

## 3. Topology

Ten vJunos-router nodes in two symmetric transit planes between two PEs, with two core route-reflectors and cross-links for backup paths. Two Linux clients sit behind the CEs as traffic sources.

```
 Client-1                                                        Client-2
    |                                                               |
  CE1 ---- PE1 ====(plane A)==== C1 ====(plane A)==== PE2 ---- CE2
             \                    |                    /
              P1 ---- P2        C1 -- C2 core        P3 ---- P4
             (plane A / plane B transit, cross-linked for TI-LFA backup)
```

Node roles:

- PE1, PE2: provider edge. Host the VRFs and PE-CE links. SR-MPLS imposition and class-of-service marking happen here.
- C1, C2: core routers acting as iBGP route reflectors (mirrors vjr-core-1 / vjr-core-2). Interconnected for path diversity.
- P1, P2, P3, P4: pure transit. Provide two disjoint PE-to-PE paths plus cross-links so every link has a loop-free backup.
- CE1, CE2: vJunos-router customer edge. Run eBGP to their PE, advertise multiple customer subnets, and can mark or transparently pass DSCP.
- Client-1, Client-2: lightweight Linux nodes behind the CEs. Generate DSCP-marked flows with iperf3 and ping.

Path design rationale:

- Two disjoint planes (A and B) give ECMP, Flexible-Algorithm plane separation (algo 128 IGP vs algo 129 delay), and TE steering targets.
- Cross-links (P1-P2, P3-P4, C1-C2) guarantee a post-convergence backup for TI-LFA on the primary links.

## 4. Addressing and SID plan (clean teaching scheme)

Loopbacks on 10.0.0.0/24, node-SID index equal to the last octet so labels read intuitively:

| Node | Loopback | Node-SID index | Algo-128 label |
| --- | --- | --- | --- |
| PE1 | 10.0.0.1 | 1 | 16001 |
| PE2 | 10.0.0.2 | 2 | 16002 |
| C1 | 10.0.0.11 | 11 | 16011 |
| C2 | 10.0.0.12 | 12 | 16012 |
| P1 | 10.0.0.21 | 21 | 16021 |
| P2 | 10.0.0.22 | 22 | 16022 |
| P3 | 10.0.0.23 | 23 | 16023 |
| P4 | 10.0.0.24 | 24 | 16024 |

- SRGB preserved at start-label 16000, index-range 8000 (immutable mandate).
- Core links use sequential /30s out of 10.1.0.0/16.
- ISO NET follows the lab convention 49.0001.<loopback-hex>.00.
- Flex-algo 129 (delay) uses a parallel index block (for example 2000 + last octet) consistent with the production EXPORT-FLEX-ALGO-SID pattern.
- Customer address space is deliberately overlapped across VRFs (CUST_A and CUST_B reuse the same subnets) to demonstrate VRF isolation.

The clean scheme is captured in a dedicated CSV in the training subtree so the existing SR-MPLS-IP-Subnets.csv remains the authoritative source for the production lab and is not modified.

## 5. Module curriculum

Self-paced. Every module follows the same spine: objective, concept primer, build steps, verification commands, an injected fault to diagnose and fix, and a "brief it back" checkpoint where the learner explains the mechanism aloud against the production Talking-Notes troubleshooting appendix.

- M0 Junos fundamentals. CLI operational vs configuration modes, candidate config, commit and commit confirmed, rollback, groups and apply-groups, interface and loopback setup. Build the base system and interfaces.
- M1 IS-IS underlay. Level-2-only, wide-metrics-only, family iso and family mpls, traffic-engineering l3-unicast-topology. Verify adjacencies and the link-state database.
- M2 SR-MPLS transport. source-packet-routing, SRGB, node-segments, explicit-null, inet.3 and mpls.0, labeled traceroute. Verify label imposition and the transit label table.
- M3 L3VPN overlay. iBGP to the C1/C2 route reflectors, family inet-vpn and evpn signaling, VRFs with RD and RT, vrf-table-label, eBGP PE-CE on the vJunos CEs, overlapping customer subnets. Achieve end-to-end client reachability and prove VRF isolation.
- M4 Traffic engineering with Flexible Algorithms. Flex-algo 128 (IGP metric) and 129 (delay metric), transport-classes, color-mapped VRF steering, inetcolor.0 resolution. The learner injects link latency in GNS3 on plane A, watches the IS-IS delay measurement rise, and observes the flagged customer move to plane B.
- M5 Class of service. Behavior-aggregate classifiers (DSCP to forwarding-class), forwarding-classes, scheduler-maps, EXP rewrite rules. The learner sources EF and best-effort flows from the Linux clients with iperf3 --tos, then proves classification via queue counters and EXP marking via a Wireshark capture on a core link.
- M6 Fast reroute. TI-LFA via post-convergence-lfa and backup-spf-options. The learner fails a primary link (interface disable or GNS3 link drop), observes the precomputed backup path, and inspects convergence.
- M7 Capstone break/fix and brief. A multi-fault scenario spanning underlay, SR transport, service, TE, and CoS. The learner diagnoses with the troubleshooting guide, restores service, and delivers a root-cause brief.

Mapping to production assets: the verification steps in each module reuse the eight-step troubleshooting appendix in SR_MPLS_Talking_Notes.md, and the configs reuse the patterns in baseline_configs/ adapted to the clean addressing.

## 6. GNS3-specific techniques

- Link degradation for TE (M4). GNS3 per-link packet filters (latency, jitter, frequency, packet loss) apply to all traffic on the wire, including the IS-IS delay-measurement probes. Injecting latency on plane A raises the measured delay, recomputes the delay-metric SPF, and steers the delay-colored customer onto plane B. This makes the Flexible-Algorithm behavior a learner-triggered cause and effect rather than a static metric.
- Failure injection for FRR (M6). Backup-path activation is exercised by a clean down event: interface disable on a transit link, or a GNS3 link stop / 100% loss filter. Latency filters alone do not bring a link down, so they are not used for FRR.
- Packet capture for QoS proof (M5). GNS3 link capture on a core segment opens in Wireshark and shows the EXP/TC bits stamped on the MPLS label, reproducing the production "smoking gun" demonstration.

## 7. Class-of-service fidelity caveat

vJunos-router uses a virtualized PFE in lite-mode. Behavior-aggregate classification, forwarding-class assignment, EXP rewrite, and queue counters are configuration-faithful and observable. Hardware-accurate scheduling, shaping, and tail-drop under congestion are not reproduced. M5 therefore proves the marking and classification chain through queue counters and capture, not through real drop behavior, which matches how the production demo proves it.

## 8. Configuration generation and staging

- Adapt the existing generate_all_configs.py and automate_configs.py to emit the clean 10-node .set files from the training CSV.
- Produce staged config snapshots per module: base, plus-isis, plus-sr, plus-l3vpn, plus-flexalgo, plus-qos, plus-frr. Each module also ships a solution snapshot so a learner can reset to a known-good state or skip ahead.
- Preserve every immutable mandate from CLAUDE.md in the generated configs (MTU 9192, post-convergence-lfa, apply-groups, ecmp-fast-reroute, explicit-null, l3-unicast-topology, advertisement always).
- Provide an initial-config injection method for the GNS3 nodes (per-node startup config) so an imported project boots into the M0 base state.

## 9. Deliverables

All training artifacts live under a dedicated training subtree so they are isolated from the production lab assets.

- The GNS3 portable project file (.gns3project) exported without base images.
- A clean training addressing CSV.
- Staged and solution .set config snapshots per module.
- A draw.io topology diagram in the existing scaled-testbed style.
- A printable student lab guide built with build_docx.py plus a snaps/ directory and screenshot-index.md, following the standard screenshot workflow.
- A separate instructor answer key (fault list, expected outputs, brief-back model answers).
- A README covering config regeneration and the GNS3 build steps.

## 10. Portability and export workflow

- Both servers must have the identical vJunos-router image installed and the GNS3 template named identically, with the version pinned and recorded in the README. A version or template-name mismatch breaks import.
- Export uses GNS3 "Export portable project" with base images excluded.
- The Linux client nodes use a small, commonly available appliance (for example a Docker or tiny Linux template) named identically on both servers, or are documented for the team to add.
- A receiving-end checklist verifies: image present and version match, template names match, project imports without missing-image prompts, all nodes boot, and the M0 base adjacencies form.

## 11. Out of scope (YAGNI)

- The full 18-node topology and exact production addressing.
- vJunos-switch or vJunosEvolved variants and any L2/EVPN access demonstration.
- SRv6, MACsec, and the symmetric-RR scale work tracked in other specs.
- Hardware-accurate congestion and shaping demonstrations.
- Automated grading or an LMS integration.

## 12. Validation checklist (per CLAUDE.md mandates)

- [ ] Configs align with Junos 25.4R1.12 syntax.
- [ ] ISO NET formatted as 49.0001.<loopback-hex>.00.
- [ ] All immutable mandates preserved in generated configs.
- [ ] SRGB consistent at 16000 / 8000, node-SIDs unique.
- [ ] enhanced-ip mode set on all vJunos nodes.
- [ ] family iso and family mpls on all transit interfaces.

## 13. Open items to resolve during planning

- Exact vJunos-router image filename and version (instructor selects before build).
- Linux client appliance choice and how it is referenced in the portable export.
- Whether M3 PE-CE uses eBGP as the primary teaching protocol with static as a documented alternative (current default: eBGP primary).
