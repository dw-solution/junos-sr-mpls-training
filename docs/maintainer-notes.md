# Maintainer Notes

Reference detail for whoever maintains the lab. Paths are relative to the repo root.

## Topology diagram
`topology/sr-mpls-training.png` is the diagram to build from: every node, link, /30,
and interface name. Both it and `topology/sr-mpls-training.drawio` are generated from
the CSVs by `python generate_topology_diagram.py` (the PNG needs the drawio CLI), so
change the CSVs and regenerate rather than editing the diagram by hand.
`training-links.csv` is the same wiring as a table.

## Regenerate configs
    source .venv/bin/activate
    python generate_lab_configs.py        # writes configs/stage*/
    python validate_lab_configs.py        # must print ALL CHECKS PASSED

## Build the trainee handouts
    cd guide
    python build_docx.py
Produces three things from the single content source in `guide/modules.py`:
- `sr-mpls-training-guide.docx` - the combined book, M0 through M7.
- `guide/handouts/<Mx>-<slug>.docx` - one standalone printable packet per module.
- `guide/screenshot-index.md` - the 3-digit screenshot code map.
Each module walks a trainee through objective, concept primer, build steps with the
exact commands to type, verification with expected output, a student-facing break/fix
exercise, and brief-it-back checkpoints. The instructor answer key
(`guide/instructor-answer-key.md`) holds the fault-injection and fix commands; the
eight-step diagnosis flow is in `guide/troubleshooting.md`. Both docx targets are
regenerable build output and are gitignored.

## Deliverables map
- Instructor build (start to finish): `instructor-build-guide.md` is the primary,
  authoritative procedure to build the topology and load every router config from
  zero, then hand off to export.
- Trainee handouts: `guide/` (combined guide + per-module packets, source in `modules.py`).
- Portable export procedure and receiving-end checklist: `export_checklist.md`.
- Contingency (portable import failed): `contingency-runbook.md` decides repair-vs-rebuild
  and, when rebuilding, reuses `instructor-build-guide.md` Steps 1 through 8.
- Instructor answer key and eight-step diagnosis flow: `guide/instructor-answer-key.md`,
  `guide/troubleshooting.md`.

## Build the GNS3 project (on 10.1.1.5)
    python build_gns3_project.py          # defaults to http://10.1.1.5:3080
    python push_lab_configs.py            # after nodes boot and fxp0 is reachable

## GNS3 node templates (must match on both servers)
- Router: template named `vJunos-router` (qemu, RAM 6144, adapters 18),
  confirmed against the lab GNS3 server. Interface-to-adapter map used by
  build_gns3_project.py (from the template's first_port_name fxp0 +
  port_name_format ge-0/0/{port0}): fxp0=adapter0, ge-0/0/0=adapter1,
  ge-0/0/1=adapter2, ge-0/0/2=adapter3, ge-0/0/3=adapter4, ge-0/0/4=adapter5.
  The CEs deliberately avoid ge-0/0/0 (flaky in GNS3); they use ge-0/0/1
  (toward PE) and ge-0/0/2 (toward client).
- Client: `RockyLinux 9.3` (qemu Linux VM, 1 adapter), the default in
  build_gns3_project.py. The GNS3 server is offline, so there is no runtime
  apt install: the M5 QoS test uses only what the image already carries.
  Reachability is `ping`; DSCP marking is `ping -Q <tos>` (present in every
  base image, e.g. `ping -Q 0xb8` for EF); the MPLS EXP capture is taken on a
  core link in the GNS3 GUI, not on the client. If the image happens to carry
  `iperf3`, the `iperf3 --tos` flow works too. Per-client config: Client1 eth0
  10.50.1.10/24 gw 10.50.1.1; Client2 eth0 10.50.2.10/24 gw 10.50.2.1 (both
  reach across CUST_A).

## Management plane
build_gns3_project.py wires this automatically: it creates MGMT-SW (Ethernet
switch) and MGMT-CLOUD (bound to host NIC bridge103, override with
--mgmt-interface) and connects fxp0 of all 6 vJunos nodes onto the
management LAN (VLAN 103, 10.0.0.0/24; GNS3 server 10.1.1.5, push host 10.0.0.253). Node
mgmt addresses are 10.0.0.40 through 10.0.0.49, one per node in training-nodes.csv. push_lab_configs.py reaches the
nodes directly on that LAN. Lab login is user 'lab' (or root), password
'labpassword'; export LAB_PASSWORD to override the push password.

Bootstrap order: a fresh vJunos boots with no config, so fxp0 has no address
until stage0-base is loaded. Console (telnet) into each node once and load
stage0-base (sets fxp0, root/lab auth, ssh), commit; after that
push_lab_configs.py drives stage1-isis through stage6-frr over SSH.

## Image pinning
vJunos-router image and GNS3 template name must match EXACTLY on both
servers. Record the chosen version here before export: 25.4R1.12.
