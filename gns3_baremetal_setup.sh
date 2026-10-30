#!/usr/bin/env bash
#
# gns3_baremetal_setup.sh  --  automate the GNS3-server layer of
# "GNS3 Server Bare Metal Install.pdf" on the lab server (192.168.90.230).
#
# This is the part of the guide that CAN be automated: OS update, KVM check,
# gns3-server + docker install, and the gns3.service systemd unit. It does the
# same steps as the PDF but is adapted for this environment:
#   - Ubuntu 24.04 (the PDF targets 18.04/19.10; the gns3server binary path and
#     the PPA behaviour differ, so the path is auto-detected).
#   - Offline aware: it refuses to run the apt/PPA steps with no internet and
#     tells you what to stage instead, rather than failing halfway.
#   - The destructive "make headless" step (removing the desktop) is OFF by
#     default and only runs with MAKE_HEADLESS=1.
#
# IT DOES NOT RUN ANYTHING BY ITSELF FROM THE REPO. Copy it to the server and
# run with sudo, AFTER you have:
#   1. Backed up the qcow2 base images and GNS3 projects (air-gapped = you
#      cannot re-download vJunos-router 24.2R1-S2 / ubuntu24.04). See the
#      companion notes; a rebuild WIPES the current SR-MPLS-Training lab.
#   2. Decided how the box gets packages (temporary internet, or pre-staged .debs).
#
# Usage (on the server):
#   sudo bash gns3_baremetal_setup.sh                 # install + service
#   sudo MAKE_HEADLESS=1 bash gns3_baremetal_setup.sh # + strip the desktop
#   sudo DO_UPGRADE=1 bash gns3_baremetal_setup.sh    # + apt full-upgrade first
#
set -euo pipefail

log() { printf '\n=== %s ===\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)."
. /etc/os-release 2>/dev/null || true
log "Host: ${PRETTY_NAME:-unknown}  ($(uname -r))"
[ "${ID:-}" = "ubuntu" ] || printf 'WARNING: not Ubuntu; the PPA steps may not apply.\n'

# --- Preflight: internet reachability (the guide's apt/PPA steps need it) ---
have_net=1
timeout 5 apt-get -o Acquire::ForceIPv4=true update -qq >/dev/null 2>&1 || have_net=0
if [ "$have_net" -eq 0 ]; then
  cat <<'EOF'

This server cannot reach the apt repositories (air-gapped). The guide's
ppa:gns3/ppa + apt install steps CANNOT run offline. Options:
  A. Give the server temporary internet, then re-run this script, or
  B. Pre-stage on an online host:
       apt-get download gns3-server docker.io <their deps...>
     copy the .debs over and: sudo dpkg -i *.deb ; sudo apt-get -f install
Aborting before any package operations.
EOF
  exit 2
fi

# --- OS update (optional; PDF step) ---
if [ "${DO_UPGRADE:-0}" = "1" ]; then
  log "apt full-upgrade"
  apt-get update && apt-get -y full-upgrade
fi

# --- Virtualization check (PDF step) ---
log "KVM check"
apt-get -y install cpu-checker >/dev/null
kvm-ok || die "KVM acceleration not available; enable VT-x/AMD-V in BIOS."

# --- Install GNS3 server + Docker (PDF steps) ---
log "Add gns3 PPA and install gns3-server + docker.io"
apt-get -y install software-properties-common
add-apt-repository -y ppa:gns3/ppa
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install gns3-server docker.io

# --- systemd service (PDF step, path auto-detected for 24.04) ---
GNS3_BIN="$(command -v gns3server || true)"
[ -n "$GNS3_BIN" ] || GNS3_BIN=/usr/bin/gns3server
log "Create gns3.service (ExecStart=$GNS3_BIN)"
cat > /etc/systemd/system/gns3.service <<EOF
[Unit]
Description=GNS3 Server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$GNS3_BIN
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
chmod 644 /etc/systemd/system/gns3.service
systemctl daemon-reload
systemctl enable gns3
systemctl restart gns3
sleep 2
systemctl --no-pager --full status gns3 || true

# --- Optional: strip the desktop to a headless "server" (DESTRUCTIVE) ---
if [ "${MAKE_HEADLESS:-0}" = "1" ]; then
  log "MAKE_HEADLESS=1: removing desktop, switching to multi-user.target"
  systemctl set-default multi-user.target
  DEBIAN_FRONTEND=noninteractive apt-get -y purge ubuntu-desktop gnome-shell gdm3 >/dev/null || true
  apt-get -y autoremove --purge >/dev/null || true
  printf 'Desktop removed. Reboot to come up headless.\n'
fi

cat <<EOF

DONE. GNS3 server should be listening on 3080.
Point the GNS3 client at it: Edit > Preferences > Server >
  uncheck "Enable local server", Host = <this server IP>, uncheck "Auth", OK.
Verify remotely: curl http://<this server IP>:3080/v2/version
EOF
