# Contingency Runbook: Rebuild the Lab From Scratch

Use this when the portable project (`sr-mpls-training.gns3project`) will not import,
or imports but will not run, on the receiving GNS3 server. It rebuilds the entire
topology and configuration from the source in this repository, with no dependency on
the portable file, by running the primary build procedure on the receiving server.

The portable-import path is in `export_checklist.md`; try that first and come here
only if it fails. Section 1 helps you decide whether to repair the import or rebuild.
The rebuild itself is the primary build in `instructor-build-guide.md`; Section 2
below points you into it rather than duplicating the steps.

---

## 1. Decide: repair the import, or rebuild

Work the import-failure table before abandoning the portable file. A rebuild is a
last resort; most import failures are a one-line template or image mismatch.

| Symptom on import | Most likely cause | Action |
| --- | --- | --- |
| "Missing image" prompt | vJunos image version does not match the README pin (25.4R1.12) | Install the pinned image, retry import. No rebuild needed. |
| Nodes import but will not start | Template vCPU/RAM differs from the source | Match the template (RAM 6144, adapters 18), retry. No rebuild. |
| Nodes start, console scrolls ZTP messages, routing never converges, node ignores `request system halt` | Zero-Touch Provisioning still enabled; auto-image upgrade retries forever and starves the routing daemons | On each node: `configure`, `delete chassis auto-image-upgrade`, `commit`. Present in `stage0-base`, so this only bites hand-bootstrapped nodes. No rebuild. |
| Links missing or on wrong ports | Interface-to-adapter map differs | Rebuild is the clean fix (Section 4 uses the exact map). |
| Client nodes absent or unknown template | `RockyLinux 9.3` not present | Add the client template, or rebuild (Section 4 recreates them). |
| Import aborts / project corrupt | Portable file damaged in transit | Rebuild from Section 2 onward. |

If any row says "No rebuild," fix that and re-import. Otherwise continue.

---

## 2. Rebuild from the repo

A rebuild is exactly the primary build, run on the receiving server. Do not duplicate
the steps here; follow **`instructor-build-guide.md` Steps 1 through 8** end to end:

1. **Step 1 Prerequisites** - image 25.4R1.12, templates `vJunos-router` and
   `RockyLinux 9.3`, a host NIC on the management LAN (bridge103), repo clone, Python env.
2. **Step 2** - regenerate and validate the configs (`ALL CHECKS PASSED`).
3. **Step 3** - confirm the interface-to-adapter map.
4. **Steps 4-5** - build the topology with `build_gns3_project.py`, which also wires
   fxp0 of all 10 nodes to the management Cloud; confirm the wiring in the GUI.
5. **Step 6** - console-bootstrap `stage0-base` on each node.
6. **Step 7** - push stages 1 through 6 over SSH (`push_lab_configs.py`).
7. **Step 8** - verify from the underlay up.

The one thing to keep in mind that differs from a first build: you are rebuilding on
a server that already tried to import, so delete any half-imported `SR-MPLS-Training`
project first to avoid a name clash before running `build_gns3_project.py`.

When Step 8 is green, the rebuild is complete and the lab is ready for the class.

---

## 3. What this runbook does not cover

- The trainee walk-through content (modules M0 through M7) is in `guide/` and is
  independent of how the topology got built; it applies identically to an imported
  or a rebuilt lab.
- Hardware-accurate QoS congestion behavior is not reproduced on the lite-mode PFE
  (see the M5 primer). This is a property of vJunos, not of the build method.
