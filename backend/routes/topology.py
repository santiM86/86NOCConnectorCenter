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


@router.get("/network/topology/{client_id}")
async def get_network_topology(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get inferred network topology for a client."""
    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)
    
    if not devices:
        return {"nodes": [], "edges": [], "layers": [], "health": {"score": 0}}
    
    topology = infer_topology(devices)
    health = calculate_health_score(devices)
    topology["health"] = health
    topology["client_id"] = client_id
    
    # Get client name
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    topology["client_name"] = client.get("name", client_id) if client else client_id
    
    return topology
