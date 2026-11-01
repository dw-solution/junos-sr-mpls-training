#!/usr/bin/env python3
"""Generate topology/sr-mpls-training.drawio from the node and link CSVs.

The diagram used to be hand-built, so it drifted every time the topology
changed. Deriving it from the same CSVs the configs come from means it cannot
disagree with the lab.

    python generate_topology_diagram.py

Also renders topology/sr-mpls-training.png when the drawio CLI is installed.
"""
import csv, os, html, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "topology", "sr-mpls-training.drawio")
PNG = os.path.join(HERE, "topology", "sr-mpls-training.png")

# canvas placement, mirroring build_gns3_project.POSITIONS
POS = {
    "Client1": (40, 300), "CE1": (230, 300), "PE1": (440, 300),
    "C1": (740, 140), "C2": (740, 460),
    "PE2": (1040, 300), "CE2": (1250, 300), "Client2": (1440, 300),
}
PLANE_COLOR = {"A": "#2E75B6", "B": "#548235", "X": "#7030A0", "ce": "#C55A11"}
ROLE_FILL = {"pe": "#DDEBF7", "core": "#E2EFDA", "ce": "#FCE4D6", "client": "#F2F2F2"}
W, H = 120, 60


def host_octet(ip):
    return f" .{ip.split('.')[-1]}" if ip else ""


def if_labels(eid, a, b, a_txt, b_txt, colour):
    """Interface names at each end of edge eid. On a horizontal link the two
    labels sit above and below the line (left-hand node above) because the
    short PE-CE and client links leave no room to place them side by side."""
    out = []
    for k, (node, other, txt) in enumerate(((a, b, a_txt), (b, a, b_txt))):
        if POS[a][1] == POS[b][1]:
            x, dy = 0, -11 if POS[node][0] < POS[other][0] else 11
        else:
            x, dy = (-0.72, 0) if k == 0 else (0.72, 0)
        out.append(f'<mxCell id="{eid}_if{k}" value="{html.escape(txt)}" style="edgeLabel;align=center;verticalAlign=middle;'
                   f'html=1;fontSize=9;fontStyle=1;fontColor={colour};'
                   f'labelBackgroundColor=#FFFFFF" vertex="1" connectable="0" parent="{eid}">'
                   f'<mxGeometry x="{x}" relative="1" as="geometry"><mxPoint x="0" y="{dy}" '
                   'as="offset"/></mxGeometry></mxCell>')
    return out


def cells():
    nodes = list(csv.DictReader(open(os.path.join(HERE, "training-nodes.csv"))))
    links = list(csv.DictReader(open(os.path.join(HERE, "training-links.csv"))))
    out, ids = [], {}
    for i, n in enumerate(nodes + [{"hostname": "Client1", "role": "client"},
                                   {"hostname": "Client2", "role": "client"}], start=2):
        host = n["hostname"]
        if host not in POS:
            continue
        ids[host] = f"n{i}"
        x, y = POS[host]
        lb = n.get("loopback", "")
        sid = n.get("sid_index", "")
        # drawio expects the label as *escaped* HTML inside the XML attribute,
        # so the markup itself has to be entity-encoded, not literal.
        label = html.escape(host)
        if lb:
            label += "&lt;br&gt;&lt;font style=&quot;font-size:9px&quot;&gt;" + html.escape(lb)
            label += (f"&lt;br&gt;SID {16000 + int(sid)}&lt;/font&gt;" if sid
                      else "&lt;/font&gt;")
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={ROLE_FILL[n['role']]};"
                 "strokeColor=#1F3864;fontSize=12;fontColor=#1F3864;verticalAlign=middle")
        out.append(f'<mxCell id="{ids[host]}" value="{label}" style="{style}" vertex="1" '
                   f'parent="1"><mxGeometry x="{x}" y="{y}" width="{W}" height="{H}" '
                   'as="geometry"/></mxCell>')

    for j, l in enumerate(links, start=100):
        a, b = l["a_node"], l["b_node"]
        if a not in ids or b not in ids:
            continue
        colour = PLANE_COLOR.get(l["plane"], "#7F7F7F")
        metric = f"metric {l['igp_metric']}" if l["igp_metric"] else ""
        subnet = l["subnet"] or ""
        lab = html.escape(" ".join(x for x in (subnet, metric) if x))
        style = (f"endArrow=none;html=1;strokeColor={colour};strokeWidth=2;"
                 "fontSize=9;fontColor=#404040;labelBackgroundColor=#FFFFFF")
        out.append(f'<mxCell id="e{j}" value="{lab}" style="{style}" edge="1" parent="1" '
                   f'source="{ids[a]}" target="{ids[b]}"><mxGeometry relative="1" '
                   'as="geometry"/></mxCell>')
        out += if_labels(f"e{j}", a, b, l["a_int"] + host_octet(l["a_ip"]),
                         l["b_int"] + host_octet(l["b_ip"]), colour)

    # client access links
    for client, ce in (("Client1", "CE1"), ("Client2", "CE2")):
        if client in ids and ce in ids:
            out.append(f'<mxCell id="e{client}" value="" style="endArrow=none;html=1;'
                       'strokeColor=#7F7F7F;strokeWidth=2;dashed=1" edge="1" parent="1" '
                       f'source="{ids[client]}" target="{ids[ce]}">'
                       '<mxGeometry relative="1" as="geometry"/></mxCell>')
            out += if_labels(f"e{client}", client, ce, "eth0 .10", "ge-0/0/2 .1", "#7F7F7F")

    legend = ("&lt;b&gt;Link key&lt;/b&gt;&lt;br&gt;"
              "&lt;b style='color:#2E75B6'&gt;blue&lt;/b&gt; plane A&amp;nbsp;&amp;nbsp;"
              "&lt;b style='color:#548235'&gt;green&lt;/b&gt; plane B&amp;nbsp;&amp;nbsp;"
              "&lt;b style='color:#7030A0'&gt;purple&lt;/b&gt; C1-C2 cross-link (TI-LFA backup)"
              "&amp;nbsp;&amp;nbsp;&lt;b style='color:#C55A11'&gt;orange&lt;/b&gt; PE-CE&lt;br&gt;"
              "&lt;b&gt;Underlay&lt;/b&gt; IS-IS L2, post-convergence TI-LFA, ecmp-fast-reroute."
              "&amp;nbsp;&amp;nbsp;&lt;b&gt;SR-MPLS&lt;/b&gt; SRGB 16000 / range 8000, explicit-null."
              "&amp;nbsp;&amp;nbsp;&lt;b&gt;MGMT&lt;/b&gt; fxp0 on VLAN 103, 10.0.0.40-.45&lt;br&gt;"
              "&lt;b&gt;Interface labels&lt;/b&gt; interface name + host octet on the link "
              "(full table in training-links.csv); on horizontal links the upper label belongs "
              "to the left-hand node. PE-CE uses VLAN 100 (CUST_A) and 200 (CUST_B): CE1 "
              "172.16.100.0/30 + 172.16.101.0/30, CE2 172.16.110.0/30 + 172.16.111.0/30. "
              "Clients 10.50.1.0/24 and 10.50.2.0/24")
    out.append('<mxCell id="legend" value="' + legend + '" style="rounded=1;whiteSpace=wrap;'
               'html=1;fillColor=#F7F9FB;strokeColor=#9DB3CC;align=left;verticalAlign=top;'
               'fontSize=11;fontColor=#1F3864;spacingLeft=8;spacingTop=6" vertex="1" '
               'parent="1"><mxGeometry x="40" y="600" width="1520" height="100" '
               'as="geometry"/></mxCell>')
    return out


def main():
    body = "\n        ".join(cells())
    xml = ('<mxfile host="app.diagrams.net">\n'
           '  <diagram name="SR-MPLS Training Lab">\n'
           '    <mxGraphModel dx="1400" dy="800" grid="1" gridSize="10" guides="1" '
           'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
           'pageWidth="1654" pageHeight="1169" math="0" shadow="0">\n'
           '      <root>\n'
           '        <mxCell id="0"/>\n'
           '        <mxCell id="1" parent="0"/>\n'
           f'        {body}\n'
           '      </root>\n'
           '    </mxGraphModel>\n'
           '  </diagram>\n'
           '</mxfile>\n')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(xml)
    print(f"wrote {OUT}")
    if shutil.which("drawio"):
        subprocess.run(["drawio", "-x", "-f", "png", "-s", "2", "-o", PNG, OUT,
                        "--no-sandbox"], check=True, capture_output=True)
        print(f"wrote {PNG}")


if __name__ == "__main__":
    main()
