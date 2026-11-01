#!/usr/bin/env python3
"""Build the SR-MPLS training topology on a GNS3 server via REST."""
import argparse, csv, os, sys, requests

HERE = os.path.dirname(os.path.abspath(__file__))
INT_TO_ADAPTER = {  # confirmed against vJunos-router 25.4R1.12 (fxp0=0, ge-0/0/N=N+1)
    "fxp0": 0, "ge-0/0/1": 2,
    "ge-0/0/2": 3, "ge-0/0/3": 4, "ge-0/0/4": 5,
}

# Canvas coordinates mirroring topology/sr-mpls-training.drawio: two symmetric
# planes between PE1 (left) and PE2 (right), plane A across the top, plane B
# across the bottom, cores in the middle, CEs and clients on the edges.
POSITIONS = {
    "Client1": (40, 300), "CE1": (210, 300), "PE1": (420, 300),
    "C1": (760, 130),
    "C2": (760, 470),
    "PE2": (1100, 300), "CE2": (1310, 300), "Client2": (1480, 300),
}

def api(base, path):
    return f"{base}{path}"

def get_template(base, name):
    r = requests.get(api(base, "/templates")); r.raise_for_status()
    for t in r.json():
        if t["name"] == name:
            return t
    sys.exit(f"template not found: {name}")

def add_node(base, pid, tmpl, name, x, y):
    """Instantiate a node. Builtin types (e.g. VPCS) are created via the nodes
    endpoint with node_type; appliance templates via the templates endpoint."""
    if tmpl.get("builtin"):
        resp = requests.post(api(base, f"/projects/{pid}/nodes"), json={
            "name": name, "node_type": tmpl["template_type"],
            "compute_id": "local", "x": x, "y": y})
    else:
        resp = requests.post(api(base, f"/projects/{pid}/templates/{tmpl['template_id']}"),
                             json={"x": x, "y": y})
    resp.raise_for_status()
    nid = resp.json()["node_id"]
    requests.put(api(base, f"/projects/{pid}/nodes/{nid}"), json={"name": name}).raise_for_status()
    return nid

def add_builtin(base, pid, name, node_type, x, y, properties=None):
    """Create a builtin infrastructure node (ethernet_switch, cloud) directly."""
    body = {"name": name, "node_type": node_type, "compute_id": "local", "x": x, "y": y}
    if properties:
        body["properties"] = properties
    resp = requests.post(api(base, f"/projects/{pid}/nodes"), json=body)
    resp.raise_for_status()
    return resp.json()["node_id"]

LABEL_STYLE = ("font-family: TypeWriter;font-size: 10.0;font-weight: bold;"
               "fill: #000000;fill-opacity: 1.0;")


def labelled(endpoint, text):
    """Attach a port label. The REST API defaults link labels to 'adapter/port'
    (so a Junos port shows as '2/0'), where the GUI uses the interface name.
    Passing the real name keeps the canvas readable and matches what the router
    reports."""
    e = dict(endpoint)
    e["label"] = {"text": text, "x": None, "y": None, "rotation": 0,
                  "style": LABEL_STYLE}
    return e


def link(base, pid, a, b, a_name=None, b_name=None):
    if a_name:
        a = labelled(a, a_name)
    if b_name:
        b = labelled(b, b_name)
    r = requests.post(api(base, f"/projects/{pid}/links"), json={"nodes": [a, b]})
    r.raise_for_status()
    return r

def wire_management(base, pid, node_ids, router_hosts, iface):
    """Bridge every router's fxp0 onto the physical management LAN.

    fxp0 addresses (10.0.0.40-.45) live on VLAN 103, the 10.0.0.0/24 lab bridge
    segment that the host carries on `iface` (bridge103). A single Cloud port
    bridges to one host NIC, so the six fxp0 links land on a builtin Ethernet
    switch that uplinks to a Cloud bound to `iface`. After this,
    push_lab_configs.py reaches each node over SSH once stage0 gives fxp0 its
    address."""
    sw_ports = [{"name": f"Ethernet{p}", "port_number": p, "type": "access", "vlan": 1}
                for p in range(len(router_hosts) + 6)]   # + clients, uplink, spare
    sw = add_builtin(base, pid, "MGMT-SW", "ethernet_switch", 880, 680,
                     {"ports_mapping": sw_ports})
    cloud = add_builtin(base, pid, "MGMT-CLOUD", "cloud", 880, 790,
                        {"ports_mapping": [{"interface": iface, "name": iface,
                                            "port_number": 0, "type": "ethernet"}]})
    p = 0
    for host in router_hosts:
        link(base, pid,
             {"node_id": node_ids[host], "adapter_number": INT_TO_ADAPTER["fxp0"], "port_number": 0},
             {"node_id": sw, "adapter_number": 0, "port_number": p},
             "fxp0", f"Ethernet{p}")
        print("mgmt", host, "fxp0 <-> MGMT-SW", p)
        p += 1
    link(base, pid,
         {"node_id": sw, "adapter_number": 0, "port_number": p},
         {"node_id": cloud, "adapter_number": 0, "port_number": 0},
         f"Ethernet{p}", iface)
    print("mgmt MGMT-SW <-> MGMT-CLOUD", f"({iface})")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://10.1.1.5:3080")
    ap.add_argument("--project", default="SR-MPLS-Training")
    ap.add_argument("--router-template", default="vJunos-router 25.4R1.12")
    ap.add_argument("--client-template", default="RockyLinux 9.3")
    ap.add_argument("--mgmt-interface", default="bridge103",
                    help="host NIC/bridge carrying VLAN 103, the 10.0.0.0/24 lab LAN")
    ap.add_argument("--no-mgmt", action="store_true",
                    help="skip the management switch/cloud wiring")
    ap.add_argument("--v3", action="store_true")
    args = ap.parse_args()
    base = args.server + ("/v3" if args.v3 else "/v2")

    nodes = {r["hostname"]: r for r in csv.DictReader(open(os.path.join(HERE, "training-nodes.csv")))}
    links = list(csv.DictReader(open(os.path.join(HERE, "training-links.csv"))))

    proj = requests.post(api(base, "/projects"), json={"name": args.project})
    proj.raise_for_status()
    pid = proj.json()["project_id"]
    print("project", pid)

    rt = get_template(base, args.router_template)
    ct = get_template(base, args.client_template)

    # Instantiate the vJunos nodes at their two-plane coordinates.
    node_ids = {}
    for host in nodes:
        x, y = POSITIONS[host]
        node_ids[host] = add_node(base, pid, rt, host, x, y)
        print("node", host, node_ids[host])

    # Add the two clients at their coordinates (CE-facing links added below).
    for client in ("Client1", "Client2"):
        x, y = POSITIONS[client]
        node_ids[client] = add_node(base, pid, ct, client, x, y)
        print("node", client, node_ids[client])

    def port(host, intf):
        return {"node_id": node_ids[host],
                "adapter_number": INT_TO_ADAPTER[intf], "port_number": 0}

    for l in links:
        link(base, pid,
             port(l["a_node"], l["a_int"]), port(l["b_node"], l["b_int"]),
             l["a_int"], l["b_int"])
        print("link", l["a_node"], l["a_int"], "<->", l["b_node"], l["b_int"])

    # CE ge-0/0/2 to client adapter 0.
    for client, ce in (("Client1", "CE1"), ("Client2", "CE2")):
        link(base, pid,
             port(ce, "ge-0/0/2"),
             {"node_id": node_ids[client], "adapter_number": 0, "port_number": 0},
             "ge-0/0/2", "eth0")
        print("link", ce, "ge-0/0/2 <->", client, "eth0")

    # Management plane: fxp0 of the six vJunos routers -> MGMT-SW -> MGMT-CLOUD(bridge103).
    if args.no_mgmt:
        print("SKIPPED management wiring (--no-mgmt).")
    else:
        wire_management(base, pid, node_ids, list(nodes), args.mgmt_interface)

    print("DONE. Open the project in GNS3 and start nodes; fxp0 mgmt is wired to",
          args.mgmt_interface + ("." if not args.no_mgmt else " (SKIPPED)."))

if __name__ == "__main__":
    main()
