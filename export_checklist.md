# Portable Export and Import Checklist

## Before export (sending server 192.168.90.230)
1. Record the exact vJunos-router image filename and version in README.md
   (pinned image: vJunos-router-24.2R1-S2.qcow2).
2. Confirm both servers have that image installed and the template named
   `vJunos-router`, and the client template `ubuntu24.04` (a qemu Linux VM;
   the offline server has no runtime apt, so M5 relies on the image's own tools).
3. Stop all nodes in the project.

## Export (GNS3 GUI)
1. File > Export portable project.
2. UNCHECK "Include base image" (images are pre-installed on both servers).
3. Save as `sr-mpls-training.gns3project`.

## Receiving server (coworkers)
- [ ] vJunos-router image present and version matches the README pin.
- [ ] Template names match exactly: `vJunos-router` and `ubuntu24.04`.
- [ ] File > Import portable project completes with no missing-image prompt.
- [ ] All 12 nodes appear (10 vJunos + 2 clients) with all links.
- [ ] Start nodes in batches; fxp0 cloud is rebound to the local mgmt bridge.
- [ ] After boot, `show isis adjacency` on PE1 shows neighbors Up (M1 base state).
- [ ] Run `python validate_lab_configs.py` against the repo to confirm configs.

## Troubleshooting import
- Missing-image prompt: image version mismatch. Install the pinned version.
- Nodes import but will not start: template vCPU/RAM differs; match the README.
- Links missing: interface-to-adapter map differs; rebuild with build_gns3_project.py.
