"""
Correlation Engine — evidence fusion per alert davvero precisi.

Invece di fidarsi di un singolo segnale (es. solo ping o solo Datto), Argus
INCROCIA piu' sorgenti per dedurre la CAUSA REALE e la CONFIDENZA prima di
allertare. Riduce drasticamente i falsi positivi.

Sorgenti (signal vector per device):
  - PING        : device_poll_status + liveness_resolver (icmp/tcp)
  - L2          : MAC visto su switch FDB / ARP scanner (<15 min)
  - DATTO       : datto_devices.online + datto_last_seen
  - CONNETTORE  : agent v4 vivo per il cliente (heartbeat <3min)
  - WAN         : wan_probe_results (firewall/router del cliente su/giu')
  - iLO POWER   : Redfish PowerState (On/Off) — risolto SOLO quando serve
  - SNMP        : device_poll_status.snmp_reachable

Output verdetto per device:
  { up, alertable, severity, confidence, root_cause, reasoning }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import liveness_resolver as lr

logger = logging.getLogger("correlation_engine")

SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

SERVER_TYPES = {"server", "ilo", "hpe-ilo", "nas", "server_oob"}
FIREWALL_TYPES = {"firewall", "router", "gateway"}
SWITCH_TYPES = {"switch", "switch_l3"}


def _norm_name(s: Any) -> str:
    return (str(s or "").strip().lower())


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


async def build_context(db) -> Dict[str, Any]:
    """Raccoglie i segnali comuni una volta per ciclo (tutti i clienti)."""
    ip_ev, mac_ev = await lr.build_evidence_maps(db, client_id=None)
    offline_clients = await lr.build_clients_without_online_agent(db)

    # WAN per cliente (ultimo probe per target)
    wan: Dict[str, Dict[str, Any]] = {}
    async for r in db.wan_probe_results.find(
        {}, {"_id": 0, "client_id": 1, "device_type": 1, "status": 1, "ping": 1, "ports": 1},
    ):
        cid = r.get("client_id")
        if not cid:
            continue
        w = wan.setdefault(cid, {"fw_up": None, "rt_up": None})
        reachable = (
            (r.get("ping") or {}).get("reachable")
            or r.get("status") in ("online", "filtered", "degraded")
            or any(p.get("open") for p in (r.get("ports") or []))
        )
        key = "rt_up" if r.get("device_type") == "router" else "fw_up"
        w[key] = bool(reachable) if w.get(key) is None else (w[key] or bool(reachable))

    # Datto per cliente: mappe by_ip / by_mac / by_name
    datto: Dict[str, Dict[str, dict]] = {}
    async for d in db.datto_devices.find(
        {}, {"_id": 0, "client_id": 1, "name": 1, "ip": 1, "mac": 1,
             "ip_list": 1, "mac_list": 1, "online": 1, "datto_last_seen": 1,
             "device_type": 1, "is_server": 1},
    ):
        cid = d.get("client_id")
        if not cid:
            continue
        b = datto.setdefault(cid, {"by_ip": {}, "by_mac": {}, "by_name": {}})
        for ip in ([d.get("ip")] + (d.get("ip_list") or [])):
            if ip:
                b["by_ip"].setdefault(ip, d)
        for mac in ([d.get("mac")] + (d.get("mac_list") or [])):
            if mac:
                b["by_mac"].setdefault(mac.lower().replace("-", ":"), d)
        if d.get("name"):
            b["by_name"].setdefault(_norm_name(d.get("name")), d)

    # child_ip -> switch_ip (dalla FDB SNMP in mac_connections, con filtro uplink)
    child_to_switch = await build_child_to_switch(db)

    return {
        "ip_ev": ip_ev, "mac_ev": mac_ev, "offline_clients": offline_clients,
        "wan": wan, "datto": datto, "child_to_switch": child_to_switch,
    }


async def build_child_to_switch(db) -> Dict[str, str]:
    """Mappa device_ip -> switch_ip di accesso, ricavata dalla FDB SNMP
    (mac_connections: from_ip=switch, from_port=porta, to_ip=device).

    Esclude:
      - archi switch->switch (uplink);
      - device visti su porte uplink (identificate via LLDP verso altri switch);
    e in caso di ambiguita' preferisce la porta di ACCESSO (meno MAC appresi).
    """
    # Insieme degli IP che sono switch
    switch_ips = set()
    async for m in db.managed_devices.find(
        {"device_type": {"$in": list(SWITCH_TYPES)}}, {"_id": 0, "ip": 1}
    ):
        if m.get("ip"):
            switch_ips.add(m["ip"])
    async for sp in db.switch_ports.find({}, {"_id": 0, "local_ip": 1}):
        if sp.get("local_ip"):
            switch_ips.add(sp["local_ip"])
    async for ln in db.lldp_neighbors.find({}, {"_id": 0, "local_ip": 1}):
        if ln.get("local_ip"):
            switch_ips.add(ln["local_ip"])

    # Porte uplink: (switch_ip, port) il cui neighbor LLDP e' un altro switch
    uplink_ports = set()
    async for ln in db.lldp_neighbors.find(
        {}, {"_id": 0, "local_ip": 1, "local_port_id": 1, "local_port_desc": 1, "remote_ip": 1}
    ):
        port = ln.get("local_port_id") or ln.get("local_port_desc")
        if ln.get("local_ip") and port and (ln.get("remote_ip") in switch_ips or not ln.get("remote_ip")):
            uplink_ports.add((ln["local_ip"], str(port)))

    # Conteggio MAC per (switch, porta) — le porte uplink/trunk hanno molti MAC
    port_mac_count: Dict[tuple, int] = {}
    edges = []
    async for mc in db.mac_connections.find(
        {"source": {"$in": ["mac_table", "fdb", "arp"]}},
        {"_id": 0, "from_ip": 1, "from_port": 1, "to_ip": 1, "updated_at": 1},
    ):
        sw = mc.get("from_ip"); dev = mc.get("to_ip"); port = str(mc.get("from_port") or "")
        if not sw or not dev or sw not in switch_ips or dev in switch_ips:
            continue
        port_mac_count[(sw, port)] = port_mac_count.get((sw, port), 0) + 1
        edges.append((dev, sw, port, mc.get("updated_at", "")))

    best: Dict[str, tuple] = {}  # dev -> (switch, port, score_tuple)
    for dev, sw, port, ts in edges:
        is_access = (sw, port) not in uplink_ports
        maccount = port_mac_count.get((sw, port), 1)
        score = (1 if is_access else 0, -maccount, ts)
        cur = best.get(dev)
        if cur is None or score > cur[2]:
            best[dev] = (sw, port, score)
    return {dev: v[0] for dev, v in best.items()}


async def persist_switch_links(db, mapping: Optional[Dict[str, str]] = None) -> int:
    """Scrive switch_ip sui managed_devices e discovered_endpoints (per UI/topology).
    Ritorna il numero di device aggiornati."""
    if mapping is None:
        mapping = await build_child_to_switch(db)
    n = 0
    for dev_ip, sw_ip in mapping.items():
        r1 = await db.managed_devices.update_many(
            {"ip": dev_ip}, {"$set": {"switch_ip": sw_ip}})
        await db.discovered_endpoints.update_many(
            {"ip": dev_ip}, {"$set": {"switch_ip": sw_ip}})
        n += r1.modified_count
    return len(mapping)


def _datto_lookup(ctx: dict, md: dict) -> Optional[dict]:
    cid = md.get("client_id")
    b = (ctx.get("datto") or {}).get(cid)
    if not b:
        return None
    ip = md.get("ip")
    mac = (md.get("mac") or "").lower().replace("-", ":")
    name = _norm_name(md.get("name") or md.get("device_name"))
    return (
        (ip and b["by_ip"].get(ip))
        or (mac and b["by_mac"].get(mac))
        or (name and b["by_name"].get(name))
        or None
    )


def gather_signals(md: dict, pd: Optional[dict], ctx: dict) -> Dict[str, Any]:
    cid = md.get("client_id")
    ip = md.get("ip") or ""
    mac = (md.get("mac") or "").lower().replace("-", ":")

    ping = lr.effective_reachable(pd) if pd else None
    l2_alive = bool((ip and ctx["ip_ev"].get(ip)) or (mac and ctx["mac_ev"].get(mac)))
    connector_live = cid not in ctx["offline_clients"]

    dd = _datto_lookup(ctx, md)
    datto_state = None
    datto_minutes = None
    if dd is not None and dd.get("online") is not None:
        datto_state = "online" if dd.get("online") else "offline"
        if datto_state == "offline":
            ls = _parse_dt(dd.get("datto_last_seen"))
            if ls:
                datto_minutes = (datetime.now(timezone.utc) - ls).total_seconds() / 60.0

    w = (ctx.get("wan") or {}).get(cid) or {}
    return {
        "ping": ping,
        "ping_method": (pd or {}).get("method") or (pd or {}).get("ping_method"),
        "l2_alive": l2_alive,
        "datto": datto_state,
        "datto_minutes": datto_minutes,
        "connector_live": connector_live,
        "fw_up": w.get("fw_up"),
        "rt_up": w.get("rt_up"),
        "snmp": (pd or {}).get("snmp_reachable"),
    }


def _V(up, alertable, severity, confidence, root_cause, reasoning) -> Dict[str, Any]:
    return {
        "up": up, "alertable": alertable, "severity": severity,
        "confidence": confidence, "root_cause": root_cause, "reasoning": reasoning,
    }


def verdict_server(s: dict, ilo_power: Optional[str]) -> Dict[str, Any]:
    dm = f" da {int(s['datto_minutes'])}min" if s.get("datto_minutes") else ""
    # 1) Ping raggiungibile = server sicuramente UP a livello IP
    if s.get("ping") is True:
        if s.get("datto") == "offline":
            return _V(True, True, "low", 85, "datto_agent_issue",
                      f"Ping OK ma Datto OFFLINE{dm} → il server e' OPERATIVO, "
                      f"problema all'agent Datto (non e' un down).")
        return _V(True, False, "none", 100, "healthy", "Server raggiungibile via ping.")

    # 2) Ping non raggiungibile — connettore cieco e Datto non conferma → incerto
    if not s.get("connector_live") and s.get("datto") != "offline":
        return _V(False, False, "none", 30, "connector_blind",
                  "Connettore di monitoraggio non disponibile: stato incerto, nessun alert.")

    # 3) Ping FAIL + Datto OFFLINE
    if s.get("datto") == "offline":
        if ilo_power == "Off":
            return _V(False, True, "critical", 100, "server_powered_off",
                      f"Ping FAIL + Datto OFFLINE{dm} + iLO PowerState=Off → SERVER SPENTO (100%).")
        if ilo_power == "On":
            return _V(False, True, "critical", 92, "os_hung",
                      f"Ping FAIL + Datto OFFLINE{dm} + iLO acceso → hardware ON ma SO NON RISPONDE (blocco/crash).")
        if s.get("l2_alive"):
            return _V(False, True, "high", 70, "unresponsive_l2_present",
                      f"Ping FAIL + Datto OFFLINE{dm} ma MAC ancora vivo sullo switch → "
                      f"server presente in rete ma NON risponde (SO/stack di rete KO o riavvio).")
        return _V(False, True, "critical", 95, "server_down",
                  f"Ping FAIL + Datto OFFLINE{dm} + nessuna evidenza L2 → SERVER DOWN (95%).")

    # 4) Ping FAIL + Datto ONLINE
    if s.get("datto") == "online":
        if s.get("l2_alive"):
            return _V(True, False, "none", 70, "icmp_filtered",
                      "Ping FAIL ma Datto ONLINE e MAC vivo a L2 → ICMP filtrato, server operativo (nessun alert).")
        return _V(False, True, "medium", 50, "monitoring_blind",
                  "Ping FAIL ma Datto vede il server ONLINE → probabile ICMP filtrato o cache agent. Verifica.")

    # 5) Nessun segnale Datto
    if s.get("l2_alive"):
        return _V(False, True, "high", 55, "icmp_filtered_l2",
                  "Ping FAIL ma MAC vivo a L2 (switch/ARP) → probabilmente ICMP filtrato, device presente.")
    return _V(False, True, "high", 80, "unreachable",
              "Ping FAIL, nessun altro segnale positivo → server irraggiungibile.")


def verdict_firewall(s: dict, majority_down: bool) -> Dict[str, Any]:
    fw_up = s.get("fw_up")
    rt_up = s.get("rt_up")
    internet_up = rt_up if rt_up is not None else fw_up
    reachable = s.get("ping") is True or s.get("l2_alive") or fw_up is True

    if reachable:
        if internet_up is False:
            return _V(True, True, "critical", 95, "isp_down",
                      "Firewall raggiungibile ma Internet DOWN → LINEA ISP GIU'.")
        return _V(True, False, "none", 100, "healthy", "Firewall/WAN raggiungibile.")

    # Firewall non raggiungibile
    if majority_down:
        return _V(False, True, "critical", 97, "site_isolated",
                  "Firewall/Gateway DOWN e la maggior parte dei device del sito irraggiungibili → SITO ISOLATO.")
    return _V(False, True, "high", 60, "firewall_mgmt_down",
              "IP di gestione del firewall non raggiungibile (il resto del sito sembra ok).")


def verdict_switch(s: dict, children_all_down: bool, has_children: bool) -> Dict[str, Any]:
    reachable = s.get("ping") is True or s.get("l2_alive")
    if reachable:
        return _V(True, False, "none", 100, "healthy", "Switch raggiungibile.")
    if not s.get("connector_live"):
        return _V(False, False, "none", 30, "connector_blind",
                  "Connettore non disponibile: stato switch incerto.")
    if has_children and children_all_down:
        return _V(False, True, "critical", 95, "switch_down",
                  "Switch DOWN e tutti i device a valle irraggiungibili → SEGMENTO ISOLATO.")
    if s.get("l2_alive"):
        return _V(False, True, "medium", 55, "switch_mgmt_down",
                  "Ping FAIL ma switch vivo a L2 → probabile solo mgmt-plane.")
    return _V(False, True, "high", 75, "switch_unreachable", "Switch irraggiungibile.")


def verdict_generic(s: dict) -> Dict[str, Any]:
    if s.get("ping") is True or s.get("l2_alive"):
        return _V(True, False, "none", 100, "healthy", "Dispositivo raggiungibile.")
    if not s.get("connector_live"):
        return _V(False, False, "none", 30, "connector_blind", "Stato incerto (connettore giu').")
    if s.get("l2_alive"):
        return _V(False, True, "medium", 55, "icmp_filtered_l2", "Ping FAIL ma vivo a L2.")
    return _V(False, True, "high", 80, "unreachable", "Dispositivo irraggiungibile.")


def device_family(md: dict) -> str:
    dt = (md.get("device_type") or "").lower()
    if dt in FIREWALL_TYPES:
        return "firewall"
    if dt in SWITCH_TYPES:
        return "switch"
    if dt in SERVER_TYPES:
        return "server"
    return "generic"


async def resolve_ilo_power(db, security_manager, redfish_poller, device_ip: str) -> Optional[str]:
    """PowerState On/Off via Redfish, SOLO per server con credenziali iLO."""
    try:
        cred = await db.device_credentials.find_one(
            {"device_ip": device_ip, "credential_type": "ilo"}, {"_id": 0}
        )
        if not cred or not cred.get("external_url"):
            return None
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
        res = await redfish_poller.get_power_state(cred["external_url"].rstrip("/"), username, password)
        if res.get("success"):
            ps = (res.get("power_state") or "").lower()
            if ps.startswith("on"):
                return "On"
            if ps.startswith("off"):
                return "Off"
    except Exception as e:  # noqa: BLE001
        logger.debug("ilo power probe failed %s: %s", device_ip, e)
    return None
