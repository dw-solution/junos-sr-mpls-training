# Instructor Build Guide: SR-MPLS Training Lab, Start to Finish

This is the primary, authoritative procedure for building the GNS3 SR-MPLS training
lab from nothing to a fully configured, verified network, then handing it off as a
portable project. Follow it top to bottom the first time you stand the lab up.

Related documents:
- `export_checklist.md` - exporting and importing the portable project (Step 9 here).
- `contingency-runbook.md` - what to do when a portable import fails on another server
  (it reuses Steps 1 through 8 of this guide).
- `guide/instructor-answer-key.md` - fault injection and fixes for running the class.
- `guide/troubleshooting.md` - the eight-step diagnosis flow used in verification.

Everything runs from a clone of this repo on a host that can reach the GNS3 server
and, once nodes boot, their fxp0 management addresses.

---

## 0. What you are building

Ten vJunos-router nodes in two symmetric transit planes between two PEs, two core
route reflectors, and two Linux clients behind the CEs. Plane A is
PE1-C1-PE2; plane B is PE1-C2-PE2; cross-links (P1-P2, P3-P4, C1-C2)
provide TI-LFA backups. See `topology/sr-mpls-training.drawio` for the canvas.

| Node | Role | Loopback | Node-SID | Mgmt (fxp0) |
| --- | --- | --- | --- | --- |
| PE1 | provider edge | 10.20.255.1 | 16001 | 10.0.0.40 |
| PE2 | provider edge | 10.20.255.2 | 16002 | 10.0.0.41 |
| C1 | core / route reflector | 10.20.255.11 | 16011 | 10.0.0.42 |
| C2 | core / route reflector | 10.20.255.12 | 16012 | 10.0.0.43 |
| P1 | transit | 10.20.255.21 | 16021 | 10.0.0.44 |
| P2 | transit | 10.20.255.22 | 16022 | 10.0.0.45 |
| P3 | transit | 10.20.255.23 | 16023 | 10.0.0.46 |
| P4 | transit | 10.20.255.24 | 16024 | 10.0.0.47 |
| CE1 | customer edge | 10.20.255.101 | n/a | 10.0.0.48 |
| CE2 | customer edge | 10.20.255.102 | n/a | 10.0.0.49 |
| Client1 | Linux (CUST_A) | eth0 10.50.1.10/24 gw 10.50.1.1 | n/a | n/a |
| Client2 | Linux (CUST_A) | eth0 10.50.2.10/24 gw 10.50.2.1 | n/a | n/a |

SRGB start 16000, range 8000. Two VRFs: CUST_A (RT target:64512:100, algo 128) and
CUST_B (RT target:64512:200, algo 129, delay-optimized). CUST_A and CUST_B reuse
customer prefix 192.168.50.0/24 on purpose to demonstrate VRF isolation.

The configuration is built in seven cumulative stages, one per teaching module:
stage0-base, stage1-isis, stage2-sr, stage3-l3vpn, stage4-flexalgo, stage5-qos,
stage6-frr. Each stage file contains every earlier stage, so stage6-frr is the full
solution config.

---

## 1. Prerequisites

On the GNS3 server (default 10.1.1.5):

- [ ] `vJunos-router` image installed, version **25.4R1.12** (the image the lab
      nodes actually reference, and the version the configs were authored against;
      any receiving server must match it exactly). `commit` rejects any
      unsupported knob at push (Step 7), which is where version fit is confirmed.
- [ ] GNS3 template named exactly **`vJunos-router`**, RAM 6144, 18
      adapters, first port `fxp0`, port-name format `ge-0/0/{port0}`.
- [ ] Client template named exactly **`RockyLinux 9.3`** (a qemu Linux VM). The
      server is offline, so no runtime `dnf install`: the M5 QoS test relies on
      what the image already carries. `ping` gives reachability, `ping -Q <tos>`
      gives DSCP marking, and the MPLS EXP capture is taken on a core link in the
      GNS3 GUI. `iperf3 --tos` is used only if the image already includes iperf3.
- [ ] A host NIC that carries the management LAN (VLAN 103, 10.0.0.0/24), default
      `bridge103`. The builder creates the management Cloud/switch and binds the Cloud to
      this NIC automatically (Step 5); you do not pre-create it. The nodes use
      10.0.0.40 through 10.0.0.49 (table in Step 0).

On the repo host (can be the GNS3 server or any host that reaches it):

- [ ] This repo cloned.
- [ ] Python environment active:

      python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
      source .venv/bin/activate

- [ ] Reachability to the GNS3 REST API (`http://10.1.1.5:3080`) and, after boot,
      to the 10.0.0.40-.49 management LAN.

---

## 2. Regenerate and validate the configs

Always regenerate and gate the configs before building, so the topology you build
matches the configs you will push.

    python generate_lab_configs.py         # writes configs/stage0-base .. stage6-frr
    python validate_lab_configs.py         # MUST print ALL CHECKS PASSED

Do not proceed until the validator prints `ALL CHECKS PASSED`. It checks that every
node has a file in every stage, that enhanced-ip, the loopback, and the ISO NET are
present at base, that every immutable mandate (MTU 9192, post-convergence-lfa,
apply-groups, ecmp-fast-reroute, explicit-null, l3-unicast-topology, advertisement
always) is present in the final stage, and that node-SIDs are unique.

---

## 3. Confirm the interface-to-adapter map

`build_gns3_project.py` maps Junos interfaces to GNS3 adapter numbers. If your
template's port list differs, links land on the wrong adapters. The expected map,
from the `vJunos-router` template (`first_port_name fxp0` plus
`port_name_format ge-0/0/{port0}`):

    fxp0 = adapter 0
    ge-0/0/1 = adapter 2
    ge-0/0/2 = adapter 3
    ge-0/0/3 = adapter 4
    ge-0/0/4 = adapter 5

The CEs deliberately avoid `ge-0/0/0` (flaky in GNS3): they use `ge-0/0/1` toward
the PE and `ge-0/0/2` toward the client. Open the template's "Show node" port list in
GNS3 and confirm it matches. If it does not, edit `INT_TO_ADAPTER` at the top of
`build_gns3_project.py` before building.

---

## 4. Build the GNS3 topology

From the repo root:

    python build_gns3_project.py          # defaults to http://10.1.1.5:3080

- Add `--v3` if the server runs the GNS3 v3 REST API.
- Override template names with `--router-template` / `--client-template` if yours
  differ from the defaults `vJunos-router` and `RockyLinux 9.3`.

The script creates a project named `SR-MPLS-Training`, instantiates the 10 vJunos
nodes and 2 clients at their two-plane canvas coordinates, builds every data-plane
link from `training-links.csv` (including the two CE-to-client links), and wires the
management plane (Step 5): an Ethernet switch and a Cloud bound to `bridge103` carrying all
10 fxp0 interfaces. It prints one line per node, per data-plane link, and per `mgmt`
link, then ends with `DONE.`

Open the project in the GNS3 GUI and confirm the canvas matches
`topology/sr-mpls-training.drawio`: plane A across the top, plane B across the
bottom, cores in the middle, CEs and clients on the edges.

---

## 5. Confirm the management plane

`build_gns3_project.py` now wires the management plane automatically. It creates a
builtin Ethernet switch (**MGMT-SW**) and a **MGMT-CLOUD** node bound to the host NIC
that carries the management LAN (default `bridge103`, the VLAN 103 interface), then links
**fxp0** of all 10 vJunos nodes to the switch and uplinks the switch to the cloud.
This is what makes each node reachable at its 10.0.0.40-.49 address for the SSH config
push in Step 7.

By hand in the GUI, just confirm the wiring: MGMT-SW and MGMT-CLOUD appear at the
bottom of the canvas, every vJunos fxp0 lands on MGMT-SW, and MGMT-CLOUD is bound to
the correct host interface. If your management LAN rides a different NIC than `bridge103`,
rebuild with `--mgmt-interface <nic>` (list host NICs at
`GET /v2/computes/local/network/interfaces`). Use `--no-mgmt` only if you intend to
wire the cloud by hand.

---

## 6. Bootstrap the base config over the console

A fresh vJunos boots with no configuration, so fxp0 has no address and SSH is
impossible until stage0 is loaded. This is the one step that must be done over the
console; every later stage goes over SSH.

For each of the 10 vJunos nodes:

1. Start the node, then open its console.
2. Log in as `root` (no password on first boot), type `cli`, then `configure`.
3. Load that node's base config from `configs/stage0-base/<NODE>.set`. The quickest
   way is to paste the set-lines into a `load set terminal` session, then commit:

       root# load set terminal        # paste the file contents, then press Ctrl-D
       root# commit and-quit

   The stage0 file sets fxp0 (the node's 10.0.0.4x address on VLAN 103), the `lab` super-user and
   root authentication, SSH, the loopback, the transit interfaces, and the MTU group.
   It also runs `delete chassis auto-image-upgrade`, which is the single most important
   line in the file: vJunos ships with Zero-Touch Provisioning enabled, and on a fresh
   boot it retries auto-image upgrade forever, prints ZTP banners over the console
   continuously, and starves the routing daemons. Nodes left in that state look hung
   and stop responding to `request system halt`. If you bootstrap a node by hand rather
   than from the stage0 file, run that delete first, before anything else.
4. Confirm reachability from the repo host: `ping 10.0.0.40` (PE1), and so on.

Start the two `RockyLinux 9.3` clients as well. Set their addresses if the image
does not already: Client1 `eth0 10.50.1.10/24 gw 10.50.1.1`; Client2
`eth0 10.50.2.10/24 gw 10.50.2.1`.

Once every vJunos node answers on its management IP, the console phase is done.

---

## 7. Push the feature stages (all router configs) over SSH

`push_lab_configs.py` loads a stage's set-lines onto every node over SSH to its fxp0
management IP and commits. Because each stage file is cumulative, you have two paths:

**Fast path (bring the whole lab to the working end state in one shot):**

    python push_lab_configs.py stage6-frr

**Teaching path (build up layer by layer, mirroring the modules):**

    python push_lab_configs.py stage1-isis
    python push_lab_configs.py stage2-sr
    python push_lab_configs.py stage3-l3vpn
    python push_lab_configs.py stage4-flexalgo
    python push_lab_configs.py stage5-qos
    python push_lab_configs.py stage6-frr

Use the teaching path if you want to demonstrate the lab building up, or to reset the
class to a known-good snapshot at any module boundary. For a plain build-and-export,
the fast path is enough.

Each run prints `OK <node> <- <stage>` per node, or `FAILED <node>: <reason>`. The
push password defaults to `labpassword`; override with `export LAB_PASSWORD=...`.
Per-node session logs land in `<NODE>.push.log`. Re-running a stage is safe; the
set-commands are idempotent, so re-push any node that failed.

---

## 8. Verify the build

Prove the network from the bottom layer up, the same order the class uses. Run from
the repo host over SSH, or from each node's CLI.

    # Underlay: every adjacency Up
    ssh lab@10.0.0.40 "show isis adjacency"                 # PE1

    # Transport: label-switched path PE1 to PE2 completes
    ssh lab@10.0.0.40 "traceroute mpls segment-routing isis 10.20.255.2"

    # Service: CUST_A carries the remote CE routes
    ssh lab@10.0.0.40 "show route table CUST_A.inet.0"

    # End to end: client to client inside CUST_A
    # from the Client1 console: ping 10.50.2.10

Then re-run the structural gate to confirm the pushed configs still match the source
of truth:

    python validate_lab_configs.py        # ALL CHECKS PASSED

If all four checks pass and the validator is green, the lab is built and configured.
The eight-step flow in `guide/troubleshooting.md` covers anything that does not come
up clean.

---

## 9. Prepare the trainee handouts (screenshots and docx)

While the lab is up and healthy, capture the eight verification screenshots so the
printed guide is complete. Save them into `guide/snaps/` named by their 3-digit code
(`001.png` through `008.png`; the code-to-module map is in `guide/screenshot-index.md`).
Then rebuild the handouts:

    cd guide
    python build_docx.py

This regenerates `sr-mpls-training-guide.docx` (the combined book) and the per-module
packets in `guide/handouts/`, embedding any screenshot whose code has a file and
leaving a gray placeholder for the rest. Both docx targets are regenerable build
output and are gitignored.

---

## 10. Export the portable project

With the lab built, verified, and screenshots captured, follow `export_checklist.md`
to stop the nodes and export the portable project without base images
(`sr-mpls-training.gns3project`). That checklist also covers the receiving-end
verification the team runs on import.

---

## 11. If the import fails on another server

The team imports the portable project per `export_checklist.md`. If that import
fails, `contingency-runbook.md` walks the import-failure decision table and, when a
rebuild is the right call, sends them back through Steps 1 through 8 of this guide to
rebuild from the repo with no dependency on the portable file.
