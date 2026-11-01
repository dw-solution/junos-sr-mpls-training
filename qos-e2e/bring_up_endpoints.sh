#!/bin/bash
# Configure the lab-facing data NIC on a QoS demo endpoint.
# Usage: bring_up_endpoints.sh <local-cidr> <gateway> <far-subnet>
# Example: bring_up_endpoints.sh 10.50.1.10/24 10.50.1.1 10.50.2.0/24
set -euo pipefail
LOCAL_CIDR="$1"; GATEWAY="$2"; FAR_SUBNET="$3"
CON="lab-data"

# The image ships a pre-existing "System eth0" profile with
# autoconnect-priority 120. NetworkManager picks the highest-priority
# autoconnect profile for a device at boot, so lab-data must outrank it
# or a reboot silently reverts eth0 to that profile and drops lab
# addressing. Do not delete "System eth0"; it can be image-provided and
# may return, so win on priority instead of on absence.
sudo nmcli connection delete "$CON" 2>/dev/null || true
sudo nmcli connection add type ethernet ifname eth0 con-name "$CON" \
    ipv4.method manual \
    ipv4.addresses "$LOCAL_CIDR" \
    ipv4.never-default yes \
    ipv4.routes "$FAR_SUBNET $GATEWAY" \
    ipv6.method disabled \
    connection.autoconnect yes \
    connection.autoconnect-priority 200
sudo nmcli connection up "$CON"

echo "--- eth0 ---"
ip -br addr show eth0
echo "--- route to far subnet ---"
ip route get "${FAR_SUBNET%/*}" | head -1
echo "--- default route must still be eth1 ---"
ip route show default
