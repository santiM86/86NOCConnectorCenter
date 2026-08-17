"""Diagramma di rete auto-generato (PNG) per il report white-label.

Costruisce il backbone switch<->switch dalle adiacenze LLDP (fonte autorevole)
e marca ogni link come VERIFICATO quando la MAC-table (FDB) corrobora l'LLDP
(il MAC base di uno switch compare nella FDB dell'altro). Rende un PNG con PIL
(nessuna dipendenza da graphviz/matplotlib) da incorporare nel PDF ReportLab.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from database import db

_FONT_REG = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
_FONT_BLD = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"

INFRA_TYPES = ["switch", "router", "firewall", "l3_switch", "core_switch", "access_switch"]


def _hex12(v: Any) -> str:
    s = str(v or "").strip()
    if s.lower().startswith("hex:"):
        s = s[4:]
    if s.lower().startswith("0x"):
        s = s[2:]
    h = re.sub(r"[^0-9a-fA-F]", "", s).lower()
    return h if len(h) == 12 else ""


def _font(bold: bool, size: int):
    try:
        return ImageFont.truetype(_FONT_BLD if bold else _FONT_REG, size)
    except Exception:
        return ImageFont.load_default()


async def build_topology_graph(client_id: Optional[str]) -> dict:
    base = {"client_id": client_id} if client_id else {}
    infra = await db.managed_devices.find(
        {**base, "device_type": {"$in": INFRA_TYPES}},
        {"_id": 0, "ip": 1, "hostname": 1, "name": 1, "device_name": 1, "device_type": 1},
    ).to_list(300)
    switches: dict = {}
    for d in infra:
        ip = d.get("ip")
        if not ip or ip in switches:
            continue
        switches[ip] = {
            "ip": ip,
            "name": d.get("hostname") or d.get("name") or d.get("device_name") or ip,
            "type": d.get("device_type") or "switch",
            "mac": "",
            "endpoints": 0,
        }
    if not switches:
        return {"switches": [], "edges": []}

    # MAC base + FDB (mac->vlan) per switch
    fdb_macs: dict = {}
    fdb_mac_vlan: dict = {}
    for ip in list(switches):
        ps = await db.device_poll_status.find_one(
            {**base, "device_ip": ip}, {"_id": 0, "primary_mac": 1})
        if ps and ps.get("primary_mac"):
            switches[ip]["mac"] = _hex12(ps["primary_mac"])
        docs = await db.discovered_endpoints.find(
            {**base, "switch_ip": ip, "source": "agent_fdb"},
            {"_id": 0, "mac": 1, "vlan": 1}).to_list(5000)
        mv: dict = {}
        for dd in docs:
            h = _hex12(dd.get("mac"))
            if h:
                mv[h] = dd.get("vlan")
        fdb_mac_vlan[ip] = mv
        fdb_macs[ip] = set(mv.keys())
        switches[ip]["endpoints"] = len(mv)

    mac_to_switch = {s["mac"]: ip for ip, s in switches.items() if s["mac"]}
    host_to_switch = {s["name"].lower(): ip for ip, s in switches.items() if s.get("name")}

    # Indice per chassis-id ANNUNCIATO da ogni switch (LLDP local_chassis_id):
    # e' l'ID che i vicini riportano come remote_chassis_id. Fondamentale quando il
    # peer si annuncia con un mgmt-IP di un'altra subnet e con chassis != primary_mac.
    chassis_to_switch: dict = {}
    async for ld in db.lldp_neighbors.find(
        base, {"_id": 0, "local_ip": 1, "local_chassis_id": 1}):
        li = ld.get("local_ip")
        lc = _hex12(ld.get("local_chassis_id"))
        if li in switches and lc:
            chassis_to_switch.setdefault(lc, li)

    # Edges backbone da LLDP
    edges: dict = {}
    async for ld in db.lldp_neighbors.find(
        base, {"_id": 0, "local_ip": 1, "local_port_id": 1, "local_port_desc": 1,
               "remote_ip": 1, "remote_sys_name": 1, "remote_chassis_id": 1,
               "remote_port_id": 1, "remote_port_desc": 1}):
        a = ld.get("local_ip")
        if a not in switches:
            continue
        b = None
        if ld.get("remote_ip") in switches:
            b = ld["remote_ip"]
        if not b:
            rc = _hex12(ld.get("remote_chassis_id"))
            if rc and rc in mac_to_switch:
                b = mac_to_switch[rc]
            elif rc and rc in chassis_to_switch:
                b = chassis_to_switch[rc]
        if not b:
            rn = (ld.get("remote_sys_name") or "").strip().lower()
            if rn and rn in host_to_switch:
                b = host_to_switch[rn]
        if not b or b == a:
            continue
        key = tuple(sorted([a, b]))
        ap = ld.get("local_port_desc") or ld.get("local_port_id") or ""
        rp = ld.get("remote_port_desc") or ld.get("remote_port_id") or ""
        e = edges.get(key) or {"a": key[0], "b": key[1], "a_port": "", "b_port": "",
                               "verified": False}
        if a == key[0]:
            e["a_port"] = e["a_port"] or ap
            e["b_port"] = e["b_port"] or rp
        else:
            e["a_port"] = e["a_port"] or rp
            e["b_port"] = e["b_port"] or ap
        edges[key] = e

    # Verifica FDB + VLAN nativa del link: il MAC di uno dei due compare nella
    # FDB dell'altro? Se si, il link e' verificato e ne ricaviamo la VLAN.
    for key, e in edges.items():
        a, b = key
        ma, mb = switches[a]["mac"], switches[b]["mac"]
        vlan = None
        verified = False
        if mb and mb in fdb_mac_vlan.get(a, {}):
            verified = True
            vlan = fdb_mac_vlan[a].get(mb)
        elif ma and ma in fdb_mac_vlan.get(b, {}):
            verified = True
            vlan = fdb_mac_vlan[b].get(ma)
        e["verified"] = verified
        try:
            e["vlan"] = int(vlan) if vlan is not None and str(vlan).strip() != "" else None
        except (ValueError, TypeError):
            e["vlan"] = None

    return {"switches": list(switches.values()), "edges": list(edges.values())}


async def compute_switch_cascade(client_id: Optional[str]) -> dict:
    """Ordina gli switch in cascata (1°, 2°, 3°...) partendo da quello collegato
    al firewall/gateway (il piu' vicino a Internet) e scendendo lungo la catena.

    Usa build_topology_graph (LLDP + verifica FDB + VLAN del link) per i link
    switch<->switch, poi calcola:
      - il "root" = switch adiacente (LLDP) al gateway; fallback = grado piu' alto
      - il livello BFS di ogni switch (0 = root)
      - il rank sequenziale 1..N (ordine di visita BFS: livello, poi nome/ip)
      - l'uplink di ogni switch (verso il parent piu' vicino al gateway) con
        porte locali/remote, stato verificato (LLDP+FDB) e VLAN nativa del link.
    """
    graph = await build_topology_graph(client_id)
    switches = {s["ip"]: s for s in graph.get("switches", [])}
    edges = graph.get("edges", [])

    # Gateway del cliente (firewall/router) per ancorare la cascata a Internet
    base = {"client_id": client_id} if client_id else {}
    gw_docs = await db.managed_devices.find(
        {**base, "device_type": {"$in": ["firewall", "router", "gateway"]}},
        {"_id": 0, "ip": 1, "name": 1, "device_name": 1, "hostname": 1, "device_type": 1},
    ).to_list(50)
    gateways = [{
        "ip": g.get("ip"),
        "name": g.get("hostname") or g.get("name") or g.get("device_name") or g.get("ip"),
        "type": g.get("device_type"),
    } for g in gw_docs if g.get("ip")]
    gw_ips = {g["ip"] for g in gateways}

    # Adiacenza SOLO tra switch (esclude i gateway, che non sono "in cascata")
    sw_ips = [ip for ip in switches if ip not in gw_ips]
    adj = defaultdict(list)  # ip -> [(neighbor_ip, edge)]
    for e in edges:
        a, b = e.get("a"), e.get("b")
        if a in switches and b in switches:
            adj[a].append((b, e))
            adj[b].append((a, e))

    # Root: switch che vede un gateway via LLDP (remote_ip == gw). Se piu' d'uno,
    # quello con piu' link (grado). Fallback: switch con grado piu' alto.
    roots: list = []
    if gw_ips:
        async for ld in db.lldp_neighbors.find(
            base, {"_id": 0, "local_ip": 1, "remote_ip": 1}):
            li, ri = ld.get("local_ip"), ld.get("remote_ip")
            if li in switches and li not in gw_ips and ri in gw_ips:
                if li not in roots:
                    roots.append(li)
    if not roots and sw_ips:
        roots = [max(sw_ips, key=lambda x: len(adj[x]))]

    # BFS multi-root: livello 0 = root(s). Ordine deterministico.
    level: dict = {}
    parent: dict = {}
    q = deque()
    for r in sorted(roots, key=lambda x: (-len(adj[x]), switches[x]["name"].lower(), x)):
        if r not in level:
            level[r] = 0
            q.append(r)
    # Eventuali switch isolati (nessun link): aggiungili come root aggiuntivi
    for ip in sorted(sw_ips, key=lambda x: (switches[x]["name"].lower(), x)):
        if ip not in level and not adj[ip]:
            level[ip] = 0
            q.append(ip)
    while q:
        n = q.popleft()
        for nb, e in sorted(adj[n], key=lambda t: (switches[t[0]]["name"].lower(), t[0])):
            if nb not in level:
                level[nb] = level[n] + 1
                parent[nb] = (n, e)
                q.append(nb)
    # Switch rimasti fuori (componenti separate senza gateway): assegna a livello 0
    for ip in sw_ips:
        if ip not in level:
            level[ip] = 0

    # Rank sequenziale: ordina per (livello, nome, ip)
    ordered = sorted(sw_ips, key=lambda x: (level.get(x, 0), switches[x]["name"].lower(), x))
    cascade = []
    for rank, ip in enumerate(ordered, start=1):
        s = switches[ip]
        up = None
        p = parent.get(ip)
        if p:
            pip, e = p
            # orienta le porte: a_port appartiene a e["a"]
            if e["a"] == ip:
                local_port, remote_port = e.get("a_port"), e.get("b_port")
            else:
                local_port, remote_port = e.get("b_port"), e.get("a_port")
            up = {
                "to_ip": pip,
                "to_name": switches[pip]["name"],
                "local_port": local_port or "",
                "remote_port": remote_port or "",
                "verified": bool(e.get("verified")),
                "vlan": e.get("vlan"),
            }
        elif gw_ips and level.get(ip) == 0 and ip in roots:
            # root collegato al gateway
            gw = gateways[0]
            up = {"to_ip": gw["ip"], "to_name": gw["name"], "local_port": "",
                  "remote_port": "", "verified": False, "vlan": None, "is_gateway": True}
        cascade.append({
            "rank": rank,
            "ip": ip,
            "name": s["name"],
            "type": s.get("type") or "switch",
            "level": level.get(ip, 0),
            "endpoints": s.get("endpoints", 0),
            "uplink": up,
        })

    return {
        "client_id": client_id,
        "gateways": gateways,
        "switch_count": len(sw_ips),
        "cascade": cascade,
        "edges": edges,
        "is_chain": all(len(adj[ip]) <= 2 for ip in sw_ips) if sw_ips else True,
    }



def _layers(switch_ips: list, edges: list) -> list:
    """BFS layering dal nodo con grado piu' alto. Ritorna lista di liste (layer)."""
    adj = defaultdict(set)
    for e in edges:
        adj[e["a"]].add(e["b"])
        adj[e["b"]].add(e["a"])
    ips = set(switch_ips)
    layers: list = []
    visited: set = set()
    remaining = sorted(ips, key=lambda x: -len(adj[x]))
    for root in remaining:
        if root in visited:
            continue
        # BFS component
        q = deque([(root, 0)])
        visited.add(root)
        comp: dict = defaultdict(list)
        while q:
            n, lvl = q.popleft()
            comp[lvl].append(n)
            for nb in sorted(adj[n]):
                if nb not in visited:
                    visited.add(nb)
                    q.append((nb, lvl + 1))
        for lvl in sorted(comp):
            if lvl < len(layers):
                layers[lvl].extend(comp[lvl])
            else:
                layers.append(list(comp[lvl]))
    return layers


def render_topology_png(graph: dict, brand_name: Optional[str] = None,
                        logo_bytes: Optional[bytes] = None,
                        client_name: Optional[str] = None) -> bytes:
    switches = graph.get("switches", [])
    edges = graph.get("edges", [])
    by_ip = {s["ip"]: s for s in switches}

    BW, BH = 210, 60
    HGAP, VGAP = 60, 120
    MARGIN = 48
    HEADER = 96
    LEGEND = 54

    layers = _layers([s["ip"] for s in switches], edges) or [[s["ip"] for s in switches]]
    max_per_row = max((len(l) for l in layers), default=1)
    content_w = max_per_row * BW + (max_per_row - 1) * HGAP
    W = max(900, content_w + 2 * MARGIN)

    # Palette VLAN: colore deterministico per ogni VLAN nativa presente
    VLAN_PALETTE = [
        (56, 189, 248), (250, 204, 21), (244, 114, 182), (52, 211, 153),
        (167, 139, 250), (251, 146, 60), (34, 197, 94), (248, 113, 113),
        (45, 212, 191), (129, 140, 248), (232, 121, 249), (163, 230, 53),
    ]
    vlans_present = sorted({e.get("vlan") for e in edges if e.get("vlan") is not None})
    vlan_color = {v: VLAN_PALETTE[i % len(VLAN_PALETTE)] for i, v in enumerate(vlans_present)}
    # Altezza legenda: cresce se ci sono molte VLAN (righe da ~6 swatch)
    legend_rows = 1 + (len(vlans_present) + 5) // 6 if vlans_present else 1
    LEGEND_H = 30 + legend_rows * 22
    H = HEADER + len(layers) * (BH + VGAP) - VGAP + LEGEND_H + MARGIN

    img = Image.new("RGB", (W, H), (15, 23, 42))  # slate-900
    d = ImageDraw.Draw(img)
    f_title = _font(True, 26)
    f_sub = _font(False, 14)
    f_node = _font(True, 15)
    f_small = _font(False, 11)
    f_port = _font(False, 10)

    # Header + logo
    x_txt = MARGIN
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
            lh = 48
            lw = int(logo.width * (lh / logo.height))
            logo = logo.resize((lw, lh))
            img.paste(logo, (MARGIN, 24), logo)
            x_txt = MARGIN + lw + 18
        except Exception:
            pass
    d.text((x_txt, 26), (brand_name or "Network") + " — Diagramma di Rete", font=f_title, fill=(226, 232, 240))
    sub = datetime.now(timezone.utc).strftime("Generato %d/%m/%Y %H:%M UTC")
    if client_name:
        sub = f"Cliente: {client_name}  ·  " + sub
    d.text((x_txt, 62), sub, font=f_sub, fill=(148, 163, 184))
    d.line([(MARGIN, HEADER - 12), (W - MARGIN, HEADER - 12)], fill=(51, 65, 85), width=1)

    # posizioni nodi
    pos: dict = {}
    for li, layer in enumerate(layers):
        row_w = len(layer) * BW + (len(layer) - 1) * HGAP
        x0 = (W - row_w) // 2
        y = HEADER + li * (BH + VGAP)
        for i, ip in enumerate(layer):
            pos[ip] = (x0 + i * (BW + HGAP), y)

    def center(ip):
        x, y = pos[ip]
        return (x + BW // 2, y + BH // 2)

    def _dashed(p0, p1, fill, width):
        import math
        x0, y0 = p0
        x1, y1 = p1
        dist = math.hypot(x1 - x0, y1 - y0) or 1
        steps = int(dist // 12)
        for s in range(0, steps, 2):
            t0 = s / steps
            t1 = min((s + 1) / steps, 1)
            d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                    (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=fill, width=width)

    # edges — colore per VLAN nativa (verde/grigio se VLAN sconosciuta),
    # stile SOLIDO = verificato (LLDP+FDB), TRATTEGGIATO = solo LLDP.
    for e in edges:
        if e["a"] not in pos or e["b"] not in pos:
            continue
        ca, cb = center(e["a"]), center(e["b"])
        vlan = e.get("vlan")
        col = vlan_color.get(vlan) if vlan is not None else (
            (34, 197, 94) if e.get("verified") else (148, 163, 184))
        if e.get("verified"):
            d.line([ca, cb], fill=col, width=4)
        else:
            _dashed(ca, cb, col, 2)
        # etichetta VLAN a meta' link
        if vlan is not None:
            mx, my = (ca[0] + cb[0]) // 2, (ca[1] + cb[1]) // 2
            lbl = f"VLAN {vlan}"
            tw = d.textlength(lbl, font=f_port)
            d.rectangle([mx - tw / 2 - 3, my - 8, mx + tw / 2 + 3, my + 8], fill=(15, 23, 42))
            d.text((mx - tw / 2, my - 6), lbl, font=f_port, fill=col)
        # etichette porte vicino ai box
        for cc, port in ((ca, e.get("a_port")), (cb, e.get("b_port"))):
            if not port:
                continue
            ox = cb if cc is ca else ca
            tx = cc[0] + (ox[0] - cc[0]) * 0.18
            ty = cc[1] + (ox[1] - cc[1]) * 0.18
            d.text((tx - 20, ty - 6), str(port)[:14], font=f_port, fill=(203, 213, 225))

    # nodi
    for ip, (x, y) in pos.items():
        s = by_ip[ip]
        d.rounded_rectangle([x, y, x + BW, y + BH], radius=10,
                            fill=(30, 41, 59), outline=(56, 189, 248), width=2)
        d.text((x + 12, y + 8), s["name"][:24], font=f_node, fill=(224, 242, 254))
        d.text((x + 12, y + 30), ip, font=f_small, fill=(148, 163, 184))
        if s.get("endpoints"):
            tag = f"{s['endpoints']} endpoint"
            d.text((x + BW - 12 - d.textlength(tag, font=f_small), y + 30), tag,
                   font=f_small, fill=(94, 234, 212))

    # legenda
    ly = H - LEGEND_H + 8
    d.line([(MARGIN, ly - 6), (W - MARGIN, ly - 6)], fill=(51, 65, 85), width=1)
    d.line([(MARGIN, ly + 10), (MARGIN + 36, ly + 10)], fill=(34, 197, 94), width=4)
    d.text((MARGIN + 44, ly + 3), "Verificato (LLDP+FDB)", font=f_small, fill=(203, 213, 225))
    _dashed((MARGIN + 260, ly + 10), (MARGIN + 296, ly + 10), (148, 163, 184), 2)
    d.text((MARGIN + 304, ly + 3), "Solo adiacenza LLDP", font=f_small, fill=(203, 213, 225))
    # swatch VLAN
    if vlans_present:
        d.text((MARGIN, ly + 30), "VLAN native:", font=f_small, fill=(148, 163, 184))
        vx = MARGIN + 90
        vy = ly + 30
        for i, v in enumerate(vlans_present):
            if vx > W - MARGIN - 90:
                vx = MARGIN + 90
                vy += 22
            c = vlan_color[v]
            d.rectangle([vx, vy + 1, vx + 16, vy + 13], fill=c)
            lab = f"VLAN {v}"
            d.text((vx + 22, vy), lab, font=f_small, fill=(203, 213, 225))
            vx += 26 + int(d.textlength(lab, font=f_small)) + 22

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out.getvalue()
