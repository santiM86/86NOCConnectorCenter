"""Network topology inference engine and routes."""
from fastapi import APIRouter, Depends, HTTPException
import re
import ipaddress
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["topology"])


def classify_device(dev):
    """Classify device type from name, sys_descr, and other hints."""
    name = (dev.get("device_name") or "").lower()
    descr = (dev.get("sys_descr") or "").lower()
    combined = name + " " + descr

    if any(k in combined for k in ["ilo", "redfish", "integrated lights"]):
        return "ilo"
    if any(k in combined for k in ["firewall", "usg", "zyxel", "fortigate", "pfsense", "sophos", "watchguard"]):
        return "firewall"
    if any(k in combined for k in ["router", "gateway", "mikrotik", "routeros"]):
        return "router"
    if any(k in combined for k in ["switch", "officeconnect", "hpe", "aruba", "netgear", "gs1", "gs2", "gs3", "gs5", "catalyst", "procurve"]):
        return "switch"
    if any(k in combined for k in ["server", "srv", "windows server", "linux", "vmware", "esxi", "proxmox"]):
        return "server"
    if any(k in combined for k in ["access point", "wifi", "ap ", "unifi"]):
        return "ap"
    if any(k in combined for k in ["printer", "mfp", "laserjet", "epson"]):
        return "printer"
    if any(k in combined for k in ["camera", "nvr", "dvr", "hikvision", "dahua"]):
        return "camera"
    if any(k in combined for k in ["nas", "synology", "qnap"]):
        return "nas"
    return "generic"


def get_subnet(ip_str):
    """Extract /24 subnet from IP."""
    try:
        ip = ipaddress.ip_address(ip_str)
        network = ipaddress.ip_network(f"{ip_str}/24", strict=False)
        return str(network.network_address)
    except Exception:
        return "unknown"


def is_gateway_ip(ip_str):
    """Check if IP looks like a gateway (.1 or .254)."""
    try:
        last_octet = int(ip_str.split(".")[-1])
        return last_octet in (1, 254)
    except Exception:
        return False


def classify_switch_role(dev, all_switches):
    """
    Classifica il ruolo di uno switch nella rete enterprise:
    - core: switch ad alta capacità nel rack principale (molte porte, location "armadio")
    - distribution: switch con uplink ad alta velocità che collega access switch
    - access: switch periferico (sotto scrivanie, sale, ecc.)
    """
    name = (dev.get("name") or "").lower()
    descr = (dev.get("sys_descr") or "").lower()
    combined = name + " " + descr
    ports = dev.get("ports", [])
    port_count = len(ports)
    
    # Location hints
    is_rack = any(k in combined for k in ["armadio", "rack", "mdf", "idf", "closet", "sala server", "server room"])
    is_peripheral = any(k in combined for k in ["under counter", "under desk", "piano", "sala", "boiler", "reception", "ufficio", "office", "room"])
    
    # Capacity hints
    is_high_capacity = port_count >= 24 or any(k in combined for k in ["48g", "24g", "48p", "24p"])
    has_10g = any(k in combined for k in ["10g", "multi-gig", "sfp+", "10gbase"])
    
    # Core: high capacity in rack location (e.g., HPE 48G in Armadio)
    if is_high_capacity and (is_rack or not is_peripheral):
        return "core"
    
    # Distribution: in rack with 10G uplinks (e.g., Netgear GS110EMX in Armadio)
    if is_rack and has_10g:
        return "distribution"
    
    # Distribution: has 10G and not peripheral
    if has_10g and not is_peripheral:
        return "distribution"
    
    # Access: peripheral location or small switch
    if is_peripheral:
        return "access"
    
    # Default: if it has 10G uplinks, it's probably distribution
    if has_10g:
        return "distribution"
    
    # Default based on port count
    if port_count >= 24:
        return "core"
    
    return "access"


def infer_topology(devices):
    """
    Enterprise-grade network topology inference engine.
    
    Hierarchy (5 layers):
    0. Internet (virtual WAN)
    1. Firewall / Router (gateway)
    2. Core Switch (alta capacità, armadio rete)
    3. Distribution Switch (uplink 10G, armadio → periferia)
    4. Access Switch (periferici) + Server + End devices
    5. Management (iLO, IPMI)
    """
    nodes = []
    edges = []
    
    # Classify all devices
    classified = []
    for dev in devices:
        dev_type = classify_device(dev)
        ip = dev.get("device_ip", "")
        classified.append({
            "ip": ip,
            "name": dev.get("device_name") or ip,
            "type": dev_type,
            "reachable": dev.get("reachable", False),
            "monitor_type": dev.get("monitor_type", "snmp"),
            "ping_ms": dev.get("ping_ms"),
            "ports": dev.get("ports", []),
            "sys_descr": dev.get("sys_descr", ""),
            "subnet": get_subnet(ip),
            "is_gateway_ip": is_gateway_ip(ip),
            "http_status": dev.get("http_status"),
        })
    
    if not classified:
        return {"nodes": [], "edges": [], "layers": []}
    
    # === Step 1: Identify gateway(s) ===
    gateways = [d for d in classified if d["type"] in ("firewall", "router")]
    if not gateways:
        candidates = [d for d in classified if d["is_gateway_ip"]]
        if candidates:
            gateways = [max(candidates, key=lambda d: len(d.get("ports", [])))]
    
    # === Step 2: Classify switches into core/distribution/access ===
    all_switches = [d for d in classified if d["type"] == "switch"]
    
    core_switches = []
    distrib_switches = []
    access_switches = []
    
    for sw in all_switches:
        role = classify_switch_role(sw, all_switches)
        if role == "core":
            core_switches.append(sw)
        elif role == "distribution":
            distrib_switches.append(sw)
        else:
            access_switches.append(sw)
    
    # If no distribution switches found but multiple switches exist,
    # promote the first access switch in rack location to distribution
    if not distrib_switches and len(access_switches) > 2:
        for i, sw in enumerate(access_switches):
            name_lower = (sw.get("name") or "").lower()
            if any(k in name_lower for k in ["armadio", "rack", "mdf"]):
                distrib_switches.append(access_switches.pop(i))
                break
    
    # === Step 3: Identify other device types ===
    management = [d for d in classified if d["type"] == "ilo"]
    servers = [d for d in classified if d["type"] == "server"]
    end_devices = [d for d in classified if d["type"] in ("ap", "printer", "camera", "nas", "generic")]
    
    categorized_ips = set()
    for group in [gateways, core_switches, distrib_switches, access_switches, management, servers, end_devices]:
        for d in group:
            categorized_ips.add(d["ip"])
    uncategorized = [d for d in classified if d["ip"] not in categorized_ips]
    end_devices.extend(uncategorized)
    
    # === Step 4: Build topology layers ===
    layers = []
    
    # Layer 0: Internet
    internet_node = {
        "id": "internet", "name": "Internet / WAN", "type": "internet",
        "layer": 0, "reachable": True, "virtual": True,
    }
    nodes.append(internet_node)
    layers.append({"name": "WAN", "nodes": ["internet"]})
    
    # Layer 1: Gateways
    gw_layer = []
    for gw in gateways:
        node = {**gw, "id": gw["ip"], "layer": 1, "role": "gateway"}
        nodes.append(node)
        gw_layer.append(gw["ip"])
        edges.append({"from": "internet", "to": gw["ip"], "type": "wan", "label": "WAN"})
    if gw_layer:
        layers.append({"name": "Firewall / Router", "nodes": gw_layer})
    
    # Layer 2: Core switches
    core_layer = []
    for sw in core_switches:
        node = {**sw, "id": sw["ip"], "layer": 2, "role": "core_switch"}
        nodes.append(node)
        core_layer.append(sw["ip"])
        parent = gateways[0]["ip"] if gateways else "internet"
        up_ports = [p for p in sw.get("ports", []) if p.get("status") == "up"]
        edges.append({
            "from": parent, "to": sw["ip"], "type": "trunk",
            "label": f"{len(up_ports)} porte" if up_ports else "",
        })
    if core_layer:
        layers.append({"name": "Core Switch", "nodes": core_layer})
    
    # Layer 3: Distribution switches
    distrib_layer = []
    for sw in distrib_switches:
        node = {**sw, "id": sw["ip"], "layer": 3, "role": "distribution_switch"}
        nodes.append(node)
        distrib_layer.append(sw["ip"])
        # Distribution connects to core (or gateway if no core)
        parent = _find_best_parent(sw, core_switches, gateways)
        edges.append({
            "from": parent, "to": sw["ip"], "type": "trunk",
            "label": "Trunk",
        })
    if distrib_layer:
        layers.append({"name": "Distribuzione", "nodes": distrib_layer})
    
    # Layer 4: Access switches — connect to distribution (or core)
    access_layer = []
    preferred_parents = distrib_switches if distrib_switches else core_switches
    
    for sw in access_switches:
        node = {**sw, "id": sw["ip"], "layer": 4, "role": "access_switch"}
        nodes.append(node)
        access_layer.append(sw["ip"])
        parent = _find_best_parent(sw, preferred_parents, core_switches + gateways)
        # Inferred edges use generic labels — real speeds come from MAC/LLDP discovery
        edges.append({
            "from": parent, "to": sw["ip"], "type": "access",
            "label": "",
        })
    
    # Servers — connect to nearest access/distribution switch
    for srv in servers:
        node = {**srv, "id": srv["ip"], "layer": 4, "role": "server"}
        nodes.append(node)
        access_layer.append(srv["ip"])
        parent = _find_best_parent(srv, access_switches + distrib_switches, core_switches + gateways)
        edges.append({"from": parent, "to": srv["ip"], "type": "server", "label": ""})
    
    # End devices — connect to nearest access switch
    for dev in end_devices:
        node = {**dev, "id": dev["ip"], "layer": 4, "role": "endpoint"}
        nodes.append(node)
        access_layer.append(dev["ip"])
        parent = _find_best_parent(dev, access_switches + distrib_switches, core_switches + gateways)
        edges.append({"from": parent, "to": dev["ip"], "type": "access", "label": ""})
    
    if access_layer:
        layers.append({"name": "Accesso / Server", "nodes": access_layer})
    
    # Layer 5: Management (iLO)
    mgmt_layer = []
    for ilo in management:
        node = {**ilo, "id": ilo["ip"], "layer": 5, "role": "management"}
        nodes.append(node)
        mgmt_layer.append(ilo["ip"])
        parent = _find_ilo_parent(ilo, servers, core_switches + distrib_switches, gateways)
        edges.append({"from": parent, "to": ilo["ip"], "type": "mgmt", "label": "iLO/MGMT"})
    
    if mgmt_layer:
        layers.append({"name": "Management", "nodes": mgmt_layer})
    
    return {"nodes": nodes, "edges": edges, "layers": layers}


def _find_best_parent(device, preferred_parents, fallback_parents):
    """Find the best parent node for a device based on subnet proximity."""
    dev_subnet = device.get("subnet", "")
    
    # First try: same subnet in preferred parents
    for p in preferred_parents:
        if p.get("subnet") == dev_subnet:
            return p["ip"]
    
    # Second try: first preferred parent
    if preferred_parents:
        return preferred_parents[0]["ip"]
    
    # Fallback
    if fallback_parents:
        return fallback_parents[0]["ip"]
    
    return "internet"


def _find_ilo_parent(ilo, servers, switches, gateways):
    """Find the parent for an iLO interface - usually the server it manages."""
    ilo_ip = ilo.get("ip", "")
    ilo_name = (ilo.get("name") or "").lower()
    
    # Try to match by name (e.g., "iLO SRV3" -> "SRV3")
    for srv in servers:
        srv_name = (srv.get("name") or "").lower()
        # Check if they share hostname fragments
        if any(part in ilo_name for part in srv_name.split() if len(part) > 2):
            return srv["ip"]
    
    # Try same subnet
    ilo_subnet = ilo.get("subnet", "")
    for srv in servers:
        if srv.get("subnet") == ilo_subnet:
            return srv["ip"]
    
    # Fall back to closest switch
    return _find_best_parent(ilo, switches, gateways)


def _guess_endpoint_type(hostname, mac):
    """Guess endpoint type from hostname or MAC OUI prefix."""
    h = (hostname or "").lower()
    if any(k in h for k in ["srv", "server", "esxi", "vmware", "proxmox", "dc-", "ad-"]):
        return "server"
    if any(k in h for k in ["printer", "mfp", "laserjet", "epson", "prn"]):
        return "printer"
    if any(k in h for k in ["camera", "nvr", "dvr", "hikvision", "ipcam"]):
        return "camera"
    if any(k in h for k in ["ap-", "wifi", "unifi", "access point"]):
        return "ap"
    if any(k in h for k in ["nas", "synology", "qnap"]):
        return "nas"
    if any(k in h for k in ["phone", "voip", "sip"]):
        return "generic"
    if any(k in h for k in ["pc-", "desktop", "laptop", "workstation", "nb-"]):
        return "generic"
    return "generic"


def calculate_health_score(devices):
    """Calculate a 0-100 health score for a set of devices."""
    if not devices:
        return {"score": 0, "breakdown": {}}
    
    total = len(devices)
    reachable = sum(1 for d in devices if d.get("reachable", False))
    
    # Reachability score (50% weight)
    reachability_pct = (reachable / total * 100) if total > 0 else 0
    
    # Latency score (25% weight) - lower is better
    ping_values = [d.get("ping_ms") for d in devices if d.get("ping_ms") is not None and d.get("ping_ms") > 0]
    if ping_values:
        avg_ping = sum(ping_values) / len(ping_values)
        if avg_ping < 5: latency_score = 100
        elif avg_ping < 20: latency_score = 90
        elif avg_ping < 50: latency_score = 75
        elif avg_ping < 100: latency_score = 50
        elif avg_ping < 200: latency_score = 25
        else: latency_score = 10
    else:
        latency_score = 50  # Unknown
    
    # Port health score (25% weight)
    total_ports = 0
    up_ports = 0
    for d in devices:
        ports = d.get("ports", [])
        total_ports += len(ports)
        up_ports += sum(1 for p in ports if p.get("status") == "up")
    
    port_health = (up_ports / total_ports * 100) if total_ports > 0 else 100
    
    # Weighted score
    score = round(reachability_pct * 0.50 + latency_score * 0.25 + port_health * 0.25)
    
    return {
        "score": min(100, max(0, score)),
        "reachability": round(reachability_pct),
        "latency_score": round(latency_score),
        "port_health": round(port_health),
        "devices_total": total,
        "devices_online": reachable,
        "avg_ping_ms": round(sum(ping_values) / len(ping_values), 1) if ping_values else None,
        "ports_up": up_ports,
        "ports_total": total_ports,
    }


def build_lldp_edges(lldp_neighbors, device_ips):
    """Build edges from LLDP neighbor data (real physical connections)."""
    edges = []
    seen = set()
    ip_set = set(device_ips)

    for neighbor in lldp_neighbors:
        local_ip = neighbor.get("local_ip", "")
        remote_ip = neighbor.get("remote_ip", "")

        target = remote_ip if remote_ip in ip_set else None
        if not target:
            continue

        key = tuple(sorted([local_ip, target]))
        if key in seen:
            continue
        seen.add(key)

        local_port = neighbor.get("local_port_desc", neighbor.get("local_port_id", ""))
        remote_port = neighbor.get("remote_port_desc", neighbor.get("remote_port_id", ""))
        label_parts = []
        if local_port:
            label_parts.append(local_port)
        if remote_port:
            label_parts.append(remote_port)
        label = " <-> ".join(label_parts) if label_parts else ""

        edges.append({
            "from": local_ip,
            "to": target,
            "type": "lldp",
            "label": label,
            "source": "lldp",
            "local_port": local_port,
            "remote_port": remote_port,
        })

    return edges


def build_mac_edges(mac_connections, device_ips, port_speeds_data):
    """Build edges from MAC address table analysis."""
    edges = []
    seen = set()
    ip_set = set(device_ips)

    # Build port speed lookup: {switch_ip: {port: speed_mbps}}
    speed_map = {}
    for ps in port_speeds_data:
        sw_ip = ps.get("switch_ip", "")
        for hp in ps.get("high_speed_ports", []):
            if sw_ip not in speed_map:
                speed_map[sw_ip] = {}
            speed_map[sw_ip][str(hp.get("port", ""))] = hp.get("speed_mbps", 0)

    for conn in mac_connections:
        from_ip = conn.get("from_ip", "")
        to_ip = conn.get("to_ip", "")

        if from_ip not in ip_set or to_ip not in ip_set:
            continue

        key = tuple(sorted([from_ip, to_ip]))
        if key in seen:
            continue
        seen.add(key)

        port = str(conn.get("from_port", ""))
        speed = speed_map.get(from_ip, {}).get(port, 0)

        label = f"Port {port}"
        if speed >= 10000:
            label += f" (10G)"
            edge_type = "trunk"
        elif speed >= 1000:
            label += f" ({speed // 1000}G)"
            edge_type = "trunk"
        else:
            edge_type = "access"

        edges.append({
            "from": from_ip,
            "to": to_ip,
            "type": edge_type,
            "label": label,
            "source": "mac_table",
        })

    return edges


@router.get("/network/topology/{client_id}")
async def get_network_topology(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get network topology for a client. Returns saved layout if available, otherwise inferred."""
    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)
    
    if not devices:
        return {"nodes": [], "edges": [], "layers": [], "health": {"score": 0}, "has_custom_layout": False}
    
    # Calculate health from real device data
    health = calculate_health_score(devices)
    
    # Fetch LLDP neighbor data (if available)
    lldp_neighbors = await db.lldp_neighbors.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(1000)
    
    # Check if a custom layout exists
    saved_layout = await db.topology_layouts.find_one(
        {"client_id": client_id}, {"_id": 0}
    )
    
    # Get client name
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    client_name = client.get("name", client_id) if client else client_id
    
    if saved_layout and saved_layout.get("nodes"):
        # Merge saved positions with live device data (reachable, ports, ping_ms, etc.)
        dev_map = {}
        for d in devices:
            dev_map[d.get("device_ip", "")] = d
        
        enriched_nodes = []
        for sn in saved_layout["nodes"]:
            node_id = sn.get("id", "")
            live = dev_map.get(node_id, {})
            enriched_nodes.append({
                **sn,
                "reachable": live.get("reachable", sn.get("reachable", False)),
                "ping_ms": live.get("ping_ms", sn.get("ping_ms")),
                "ports": live.get("ports", sn.get("ports", [])),
                "monitor_type": live.get("monitor_type", sn.get("monitor_type", "snmp")),
                "sys_descr": live.get("sys_descr", sn.get("sys_descr", "")),
                "http_status": live.get("http_status", sn.get("http_status")),
            })
        
        return {
            "nodes": enriched_nodes,
            "edges": saved_layout.get("edges", []),
            "layers": saved_layout.get("layers", []),
            "health": health,
            "client_id": client_id,
            "client_name": client_name,
            "has_custom_layout": True,
            "lldp_count": len(lldp_neighbors),
        }
    
    # No saved layout — return inferred topology, enriched with LLDP/MAC if available
    topology = infer_topology(devices)
    
    device_ips = [d.get("device_ip", "") for d in devices]
    discovered_edges = []
    
    if lldp_neighbors:
        lldp_edges = build_lldp_edges(lldp_neighbors, device_ips)
        discovered_edges.extend(lldp_edges)
    
    # Also check MAC-based connections
    mac_connections = await db.mac_connections.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(1000)
    port_speeds_data = await db.port_speeds.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(100)
    
    if mac_connections:
        mac_edges = build_mac_edges(mac_connections, device_ips, port_speeds_data)
        # Only add MAC edges that don't overlap with LLDP
        lldp_pairs = set(tuple(sorted([e["from"], e["to"]])) for e in discovered_edges)
        for me in mac_edges:
            key = tuple(sorted([me["from"], me["to"]]))
            if key not in lldp_pairs:
                discovered_edges.append(me)
                lldp_pairs.add(key)
    
    if discovered_edges:
        # Replace inferred edges with discovered edges where available
        discovered_pairs = set(tuple(sorted([e["from"], e["to"]])) for e in discovered_edges)
        kept_inferred = [
            e for e in topology["edges"]
            if tuple(sorted([e["from"], e["to"]])) not in discovered_pairs
        ]
        topology["edges"] = discovered_edges + kept_inferred
    
    # === Add discovered endpoints (MAC-based leaf nodes) ===
    endpoints = await db.discovered_endpoints.find(
        {"client_id": client_id, "is_managed": False}, {"_id": 0}
    ).to_list(500)
    
    if endpoints:
        existing_node_ids = set(n.get("id") for n in topology["nodes"])
        endpoint_layer_nodes = []
        
        for ep in endpoints:
            mac = ep.get("mac", "")
            ip = ep.get("ip", "")
            switch_ip = ep.get("switch_ip", "")
            port = ep.get("port", "")
            hostname = ep.get("hostname", "")
            vlan = ep.get("vlan", "")
            
            # Use MAC as node ID (unique per endpoint)
            node_id = f"mac-{mac.replace(':', '')}" if mac else f"ep-{switch_ip}-{port}"
            if node_id in existing_node_ids:
                continue
            existing_node_ids.add(node_id)
            
            # Build display name
            display_name = hostname or ip or mac
            subtitle = mac
            if ip and ip != display_name:
                subtitle = f"{ip} | {mac}"
            
            # Determine endpoint type from MAC OUI or hostname
            ep_type = _guess_endpoint_type(hostname, mac)
            
            # Create endpoint node
            ep_node = {
                "id": node_id,
                "name": display_name,
                "type": ep_type,
                "layer": 5,
                "role": "discovered_endpoint",
                "reachable": True,
                "ip": ip,
                "mac": mac,
                "switch_ip": switch_ip,
                "switch_port": port,
                "vlan": vlan,
                "hostname": hostname,
                "subtitle": subtitle,
            }
            topology["nodes"].append(ep_node)
            endpoint_layer_nodes.append(node_id)
            
            # Create edge: parent switch -> endpoint
            speed_label = ""
            for ps in port_speeds_data:
                if ps.get("switch_ip") == switch_ip:
                    for hp in ps.get("high_speed_ports", []):
                        if str(hp.get("port", "")) == str(port):
                            speed_mbps = hp.get("speed_mbps", 0)
                            if speed_mbps >= 10000:
                                speed_label = " (10G)"
                            elif speed_mbps >= 1000:
                                speed_label = f" ({speed_mbps // 1000}G)"
            
            edge_label = f"Port {port}{speed_label}" if port else ""
            if vlan:
                edge_label += f" VLAN {vlan}"
            
            topology["edges"].append({
                "from": switch_ip,
                "to": node_id,
                "type": "access",
                "label": edge_label,
                "source": "mac_discovery",
            })
        
        if endpoint_layer_nodes:
            topology["layers"].append({"name": "Endpoint Scoperti", "nodes": endpoint_layer_nodes})
    
    topology["health"] = health
    topology["client_id"] = client_id
    topology["client_name"] = client_name
    topology["has_custom_layout"] = False
    topology["lldp_count"] = len(lldp_neighbors)
    topology["mac_connections_count"] = len(mac_connections)
    topology["discovered_endpoints_count"] = len(endpoints) if endpoints else 0
    
    return topology


@router.get("/network/lldp/{client_id}")
async def get_lldp_neighbors(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get raw LLDP neighbor data for a client."""
    neighbors = await db.lldp_neighbors.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(1000)
    return {"client_id": client_id, "neighbors": neighbors, "count": len(neighbors)}


@router.post("/network/topology/{client_id}/layout")
async def save_topology_layout(client_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Save custom topology layout (node positions and edges) for a client."""
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    
    layout_doc = {
        "client_id": client_id,
        "nodes": nodes,
        "edges": edges,
        "layers": payload.get("layers", []),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": current_user.get("email", "unknown"),
    }
    
    await db.topology_layouts.update_one(
        {"client_id": client_id},
        {"$set": layout_doc},
        upsert=True
    )
    
    return {"status": "ok", "message": "Layout salvato"}


@router.delete("/network/topology/{client_id}/layout")
async def reset_topology_layout(client_id: str, current_user: dict = Depends(get_current_user)):
    """Delete custom layout and revert to auto-inferred topology."""
    await db.topology_layouts.delete_one({"client_id": client_id})
    return {"status": "ok", "message": "Layout resettato"}



@router.get("/network/device-detail/{client_id}/{device_ip}")
async def get_device_detail(client_id: str, device_ip: str, current_user: dict = Depends(get_current_user)):
    """Get detailed info for a specific device: alerts, connected endpoints, LLDP neighbors."""
    # Device info
    device = await db.device_poll_status.find_one(
        {"client_id": client_id, "device_ip": device_ip}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")

    # Alerts for this device
    alerts = await db.alerts.find(
        {"device_ip": device_ip},
        {"_id": 0, "severity": 1, "message": 1, "created_at": 1, "acknowledged": 1, "source": 1}
    ).sort("created_at", -1).to_list(20)

    # Connected endpoints (MAC discovery)
    connected = await db.discovered_endpoints.find(
        {"client_id": client_id, "switch_ip": device_ip}, {"_id": 0}
    ).to_list(100)

    # LLDP neighbors for this device
    lldp = await db.lldp_neighbors.find(
        {"client_id": client_id, "local_ip": device_ip}, {"_id": 0}
    ).to_list(50)

    # Port speeds
    port_speeds = await db.port_speeds.find_one(
        {"client_id": client_id, "switch_ip": device_ip}, {"_id": 0}
    )

    # MAC connections from this device
    mac_conns = await db.mac_connections.find(
        {"client_id": client_id, "from_ip": device_ip}, {"_id": 0}
    ).to_list(50)

    return {
        "device": device,
        "alerts": alerts,
        "alerts_count": len(alerts),
        "active_alerts": sum(1 for a in alerts if not a.get("acknowledged")),
        "connected_endpoints": connected,
        "connected_count": len(connected),
        "lldp_neighbors": lldp,
        "port_speeds": port_speeds.get("high_speed_ports", []) if port_speeds else [],
        "mac_connections": mac_conns,
    }


@router.get("/network/alerts-summary/{client_id}")
async def get_topology_alerts_summary(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get alert counts per device IP for topology overlay."""
    # Get all device IPs for this client
    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0, "device_ip": 1}
    ).to_list(500)
    device_ips = [d["device_ip"] for d in devices]

    # Get alerts for these devices
    pipeline = [
        {"$match": {"device_ip": {"$in": device_ips}, "acknowledged": {"$ne": True}}},
        {"$group": {
            "_id": "$device_ip",
            "total": {"$sum": 1},
            "critical": {"$sum": {"$cond": [{"$eq": ["$severity", "critical"]}, 1, 0]}},
            "high": {"$sum": {"$cond": [{"$eq": ["$severity", "high"]}, 1, 0]}},
            "medium": {"$sum": {"$cond": [{"$eq": ["$severity", "medium"]}, 1, 0]}},
            "low": {"$sum": {"$cond": [{"$eq": ["$severity", "low"]}, 1, 0]}},
        }}
    ]
    results = await db.alerts.aggregate(pipeline).to_list(500)

    alert_map = {}
    for r in results:
        alert_map[r["_id"]] = {
            "total": r["total"],
            "critical": r["critical"],
            "high": r["high"],
            "medium": r["medium"],
            "low": r["low"],
        }

    return {"client_id": client_id, "alerts": alert_map}
