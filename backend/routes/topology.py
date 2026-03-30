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


def infer_topology(devices):
    """
    Infer network topology from device data.
    Returns nodes and edges for a hierarchical layout.
    
    Hierarchy:
    1. Internet (virtual node)
    2. Firewall/Router (gateway)
    3. Core switches (main distribution)
    4. Access switches / Servers / End devices
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
            "device_class": dev.get("device_class", "generic"),
        })
    
    if not classified:
        return {"nodes": [], "edges": [], "layers": []}
    
    # Step 1: Identify gateway(s) - firewall or router
    gateways = [d for d in classified if d["type"] in ("firewall", "router")]
    if not gateways:
        # Fallback: device with gateway IP that has most ports
        candidates = [d for d in classified if d["is_gateway_ip"]]
        if candidates:
            gateways = [max(candidates, key=lambda d: len(d.get("ports", [])))]
    
    # Step 2: Identify switches
    switches = [d for d in classified if d["type"] == "switch"]
    
    # Step 3: Sort switches by port count (more ports = more central/core)
    switches.sort(key=lambda d: len(d.get("ports", [])), reverse=True)
    core_switches = switches[:2] if len(switches) > 2 else switches
    access_switches = switches[2:] if len(switches) > 2 else []
    
    # Step 4: Identify management devices (iLO)
    management = [d for d in classified if d["type"] == "ilo"]
    
    # Step 5: Everything else
    servers = [d for d in classified if d["type"] == "server"]
    end_devices = [d for d in classified if d["type"] in ("ap", "printer", "camera", "nas", "generic")]
    # Exclude already categorized
    categorized_ips = set()
    for group in [gateways, core_switches, access_switches, management, servers, end_devices]:
        for d in group:
            categorized_ips.add(d["ip"])
    uncategorized = [d for d in classified if d["ip"] not in categorized_ips]
    end_devices.extend(uncategorized)
    
    # Step 6: Build topology layers
    layers = []
    
    # Layer 0: Internet (virtual)
    internet_node = {
        "id": "internet",
        "name": "Internet / WAN",
        "type": "internet",
        "layer": 0,
        "reachable": True,
        "virtual": True,
    }
    nodes.append(internet_node)
    layers.append({"name": "WAN", "nodes": ["internet"]})
    
    # Layer 1: Gateway(s)
    gateway_layer_nodes = []
    for gw in gateways:
        node = {**gw, "id": gw["ip"], "layer": 1, "role": "gateway"}
        nodes.append(node)
        gateway_layer_nodes.append(gw["ip"])
        edges.append({
            "from": "internet",
            "to": gw["ip"],
            "type": "wan",
            "label": "WAN",
        })
    if gateway_layer_nodes:
        layers.append({"name": "Firewall / Router", "nodes": gateway_layer_nodes})
    
    # Layer 2: Core switches
    core_layer_nodes = []
    for sw in core_switches:
        node = {**sw, "id": sw["ip"], "layer": 2, "role": "core_switch"}
        nodes.append(node)
        core_layer_nodes.append(sw["ip"])
        # Connect to gateway or internet
        parent = gateways[0]["ip"] if gateways else "internet"
        up_ports = [p for p in sw.get("ports", []) if p.get("status") == "up"]
        edges.append({
            "from": parent,
            "to": sw["ip"],
            "type": "trunk",
            "label": f"{len(up_ports)} porte attive" if up_ports else "",
            "bandwidth": "trunk",
        })
    if core_layer_nodes:
        layers.append({"name": "Switch Core / Distribuzione", "nodes": core_layer_nodes})
    
    # Layer 3: Access switches, servers, management
    access_layer_nodes = []
    
    for sw in access_switches:
        node = {**sw, "id": sw["ip"], "layer": 3, "role": "access_switch"}
        nodes.append(node)
        access_layer_nodes.append(sw["ip"])
        # Connect to closest core switch (by subnet or first core)
        parent = _find_best_parent(sw, core_switches, gateways)
        edges.append({
            "from": parent,
            "to": sw["ip"],
            "type": "access",
            "label": "",
        })
    
    for srv in servers:
        node = {**srv, "id": srv["ip"], "layer": 3, "role": "server"}
        nodes.append(node)
        access_layer_nodes.append(srv["ip"])
        parent = _find_best_parent(srv, core_switches, gateways)
        edges.append({
            "from": parent,
            "to": srv["ip"],
            "type": "server",
            "label": "",
        })
    
    for ilo in management:
        node = {**ilo, "id": ilo["ip"], "layer": 3, "role": "management"}
        nodes.append(node)
        access_layer_nodes.append(ilo["ip"])
        # iLO connects to management port of closest server or switch
        parent = _find_ilo_parent(ilo, servers, core_switches, gateways)
        edges.append({
            "from": parent,
            "to": ilo["ip"],
            "type": "mgmt",
            "label": "MGMT",
        })
    
    if access_layer_nodes:
        layers.append({"name": "Accesso / Server / Mgmt", "nodes": access_layer_nodes})
    
    # Layer 4: End devices
    end_layer_nodes = []
    for dev in end_devices:
        node = {**dev, "id": dev["ip"], "layer": 4, "role": "endpoint"}
        nodes.append(node)
        end_layer_nodes.append(dev["ip"])
        # Connect to closest access switch, or core switch, or gateway
        parent = _find_best_parent(dev, access_switches + core_switches, gateways)
        edges.append({
            "from": parent,
            "to": dev["ip"],
            "type": "access",
            "label": "",
        })
    
    if end_layer_nodes:
        layers.append({"name": "Dispositivi", "nodes": end_layer_nodes})
    
    return {
        "nodes": nodes,
        "edges": edges,
        "layers": layers,
    }


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
    
    topology["health"] = health
    topology["client_id"] = client_id
    topology["client_name"] = client_name
    topology["has_custom_layout"] = False
    topology["lldp_count"] = len(lldp_neighbors)
    topology["mac_connections_count"] = len(mac_connections)
    
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
