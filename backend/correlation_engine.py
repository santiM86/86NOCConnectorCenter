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

# Source-health gating: soglie oltre cui una sorgente diventa INAFFIDABILE
# (i suoi segnali vengono SCARTATI dalla fusione per non generare falsi alert).
DATTO_BLACKOUT_RATIO_DEFAULT = 0.6      # >=60% device Datto offline insieme -> blackout
DATTO_SYNC_STALE_MINUTES_DEFAULT = 30   # sync fermo oltre N min -> Datto inaffidabile


def _norm_name(s: Any) -> str:
    return (str(s or "").strip().lower())


def _host_short(s: Any) -> str:
    """Hostname corto normalizzato: lowercase, senza dominio (FQDN -> host)."""
    n = _norm_name(s)
    return n.split(".")[0] if n else ""


def _norm_mac(m: Any) -> str:
    if not m:
        return ""
    s = str(m).upper().replace("-", ":").replace(".", ":").strip()
    if ":" not in s and len(s) == 12:
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    if s in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF") or len(s) != 17:
        return ""
    return s


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


async def build_context(db, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Raccoglie i segnali comuni una volta per ciclo (tutti i clienti) e
    valuta l'AFFIDABILITA' di ogni sorgente (source-health gating)."""
    cfg = cfg or {}
    now = datetime.now(timezone.utc)
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

    # Datto per cliente: mappe by_ip / by_mac / by_name / by_uid / by_serial / by_host
    datto: Dict[str, Dict[str, dict]] = {}
    async for d in db.datto_devices.find(
        {}, {"_id": 0, "client_id": 1, "uid": 1, "name": 1, "ip": 1, "mac": 1,
             "ip_list": 1, "mac_list": 1, "online": 1, "datto_last_seen": 1,
             "device_type": 1, "is_server": 1, "serial": 1, "fqdn": 1,
             "hostname_short": 1},
    ):
        cid = d.get("client_id")
        if not cid:
            continue
        b = datto.setdefault(cid, {"by_ip": {}, "by_mac": {}, "by_name": {},
                                   "by_uid": {}, "by_serial": {}, "by_host": {}})
        if d.get("uid"):
            b["by_uid"].setdefault(d["uid"], d)
        for ip in ([d.get("ip")] + (d.get("ip_list") or [])):
            if ip:
                b["by_ip"].setdefault(ip, d)
        for mac in ([d.get("mac")] + (d.get("mac_list") or [])):
            nm = _norm_mac(mac)
            if nm:
                b["by_mac"].setdefault(nm, d)
        for h in (d.get("name"), d.get("fqdn"), d.get("hostname_short")):
            if h:
                b["by_name"].setdefault(_norm_name(h), d)
                hs = _host_short(h)
                if hs:
                    b["by_host"].setdefault(hs, d)
        if d.get("serial"):
            b["by_serial"].setdefault(str(d["serial"]).strip().upper(), d)

    # child_ip -> switch_ip (dalla FDB SNMP in mac_connections, con filtro uplink)
    child_to_switch = await build_child_to_switch(db)

    # --- Source health: sync Datto fresco? ---
    stale_min = float(cfg.get("datto_sync_stale_minutes", DATTO_SYNC_STALE_MINUTES_DEFAULT))
    datto_sync_fresh: Dict[str, bool] = {}
    async for link in db.datto_client_links.find({}, {"_id": 0, "client_id": 1, "last_sync_at": 1}):
        cid = link.get("client_id")
        if not cid:
            continue
        ls = _parse_dt(link.get("last_sync_at"))
        datto_sync_fresh[cid] = bool(ls and (now - ls).total_seconds() / 60.0 <= stale_min)

    # --- Source health: blackout Datto (offline di massa) + affidabilita' finale ---
    blackout_ratio = float(cfg.get("datto_blackout_ratio", DATTO_BLACKOUT_RATIO_DEFAULT))
    source_health: Dict[str, Dict[str, Any]] = {}
    all_cids = set(wan) | set(datto) | set(datto_sync_fresh) | set(offline_clients)
    for cid in all_cids:
        connector_reliable = cid not in offline_clients
        w = wan.get(cid) or {}
        internet_up = w.get("rt_up") if w.get("rt_up") is not None else w.get("fw_up")
        datto_reliable = True
        datto_reason = "ok"
        b = datto.get(cid)
        if not b:
            datto_reliable = False
            datto_reason = "no_datto"
        elif cid in datto_sync_fresh and not datto_sync_fresh[cid]:
            datto_reliable = False
            datto_reason = "sync_stale"
        else:
            devs = list(b["by_uid"].values())
            known = [d for d in devs if d.get("online") is not None]
            if known:
                offline = sum(1 for d in known if not d.get("online"))
                ratio = offline / len(known)
                # Blackout di massa: molto probabilmente internet/portale Datto
                # giu', NON tutti i server spenti insieme -> scarta Datto.
                if ratio >= blackout_ratio:
                    datto_reliable = False
                    datto_reason = f"mass_offline_{int(ratio*100)}pct"
        source_health[cid] = {
            "connector_reliable": connector_reliable,
            "datto_reliable": datto_reliable,
            "datto_reason": datto_reason,
            "internet_up": internet_up,
        }

    # --- Hyper-V: stato accensione VM dall'host (fonte autorevole) ---
    # hyperv[cid][short_vm_name] = "Running"|"Off"|"Saved"|"Paused" (solo snapshot
    # freschi <15min). Analogo a iLO per il fisico: dice se la VM e' accesa a
    # livello di hypervisor, indipendente da rete/ICMP/firewall.
    hv_fresh_min = float(cfg.get("hyperv_fresh_minutes", 15))
    hyperv: Dict[str, Dict[str, str]] = {}
    async for snap in db.hyperv_snapshots.find(
        {}, {"_id": 0, "client_id": 1, "vms": 1, "collected_at": 1},
    ):
        cid = snap.get("client_id")
        if not cid:
            continue
        ca = _parse_dt(snap.get("collected_at"))
        if not (ca and (now - ca).total_seconds() / 60.0 <= hv_fresh_min):
            continue
        b = hyperv.setdefault(cid, {})
        for vm in (snap.get("vms") or []):
            nm = _host_short(vm.get("name"))
            if nm:
                b[nm] = (vm.get("state") or "").strip()

    return {
        "ip_ev": ip_ev, "mac_ev": mac_ev, "offline_clients": offline_clients,
        "wan": wan, "datto": datto, "child_to_switch": child_to_switch,
        "source_health": source_health, "hyperv": hyperv,
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
    # 0) link persistito (match certo calcolato al sync) -> massima affidabilita'
    uid = md.get("datto_uid")
    if uid and b.get("by_uid", {}).get(uid):
        return b["by_uid"][uid]
    ip = md.get("ip") or md.get("ip_address")
    mac = _norm_mac(md.get("mac") or md.get("mac_address"))
    serial = str(md.get("serial") or "").strip().upper()
    name = md.get("name") or md.get("device_name") or md.get("hostname")
    return (
        (mac and b["by_mac"].get(mac))
        or (ip and b["by_ip"].get(ip))
        or (serial and b.get("by_serial", {}).get(serial))
        or (name and b["by_name"].get(_norm_name(name)))
        or (name and b.get("by_host", {}).get(_host_short(name)))
        or None
    )


def gather_signals(md: dict, pd: Optional[dict], ctx: dict) -> Dict[str, Any]:
    cid = md.get("client_id")
    ip = md.get("ip") or ""
    mac = _norm_mac(md.get("mac") or md.get("mac_address"))

    ping = lr.effective_reachable(pd) if pd else None
    l2_alive = bool((ip and ctx["ip_ev"].get(ip)) or (mac and ctx["mac_ev"].get(mac)))
    connector_live = cid not in ctx["offline_clients"]

    # Source health del cliente (default: tutto affidabile se sconosciuto)
    sh = (ctx.get("source_health") or {}).get(cid) or {}
    datto_reliable = sh.get("datto_reliable", True)

    dd = _datto_lookup(ctx, md)
    datto_state = None
    datto_minutes = None
    # Datto contribuisce SOLO se la sorgente e' affidabile in questo momento.
    # Se il portale/internet e' giu' (blackout/sync stale) il segnale Datto
    # viene SCARTATO: mai usare "Datto offline" come prova di device down.
    if dd is not None and dd.get("online") is not None and datto_reliable:
        datto_state = "online" if dd.get("online") else "offline"
        if datto_state == "offline":
            ls = _parse_dt(dd.get("datto_last_seen"))
            if ls:
                datto_minutes = (datetime.now(timezone.utc) - ls).total_seconds() / 60.0

    w = (ctx.get("wan") or {}).get(cid) or {}

    # Hyper-V: stato accensione VM dall'host (match per hostname corto).
    hv = (ctx.get("hyperv") or {}).get(cid) or {}
    hyperv_state = None
    for _k in (md.get("hostname"), md.get("name"), md.get("device_name")):
        ks = _host_short(_k)
        if ks and ks in hv:
            hyperv_state = hv[ks]
            break

    return {
        "ping": ping,
        "ping_method": (pd or {}).get("method") or (pd or {}).get("ping_method"),
        "l2_alive": l2_alive,
        "datto": datto_state,
        "datto_minutes": datto_minutes,
        "datto_reliable": datto_reliable,
        "datto_matched": dd is not None,
        "hyperv_state": hyperv_state,
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
    hv = s.get("hyperv_state")
    # 0) Nessun dato di monitoraggio (device mai pollato) → non giudicabile
    if s.get("ping") is None and not s.get("l2_alive") and s.get("datto") is None and not hv:
        return _V(False, False, "none", 0, "no_data", "Nessun dato di monitoraggio ancora disponibile.")
    # 1) Ping raggiungibile = server sicuramente UP a livello IP
    if s.get("ping") is True:
        if s.get("datto") == "offline":
            return _V(True, True, "low", 85, "datto_agent_issue",
                      f"Ping OK ma Datto OFFLINE{dm} → il server e' OPERATIVO, "
                      f"problema all'agent Datto (non e' un down).")
        return _V(True, False, "none", 100, "healthy", "Server raggiungibile via ping.")

    # 1.5) HYPER-V host = fonte autorevole (come iLO per il fisico).
    #  - Off/Saved/Paused → VM SPENTA di proposito: NESSUN alert di down.
    #  - Running → evidenza forte di accensione: se c'e' anche L2/Datto online
    #    → operativa (ICMP filtrato); altrimenti VM accesa ma SO non risponde
    #    (verifica), MAI un "down" critico.
    if hv in ("Off", "Saved", "Paused"):
        return _V(False, False, "none", 100, "vm_powered_off",
                  f"VM Hyper-V in stato {hv} (dall'host) → spenta di proposito, nessun down.")
    if hv == "Running":
        if s.get("l2_alive") or s.get("datto") == "online":
            return _V(True, False, "none", 80, "icmp_filtered_hyperv",
                      "Ping FAIL ma la VM risulta Running sull'host Hyper-V + evidenza rete → "
                      "ICMP filtrato, VM operativa (nessun alert).")
        return _V(False, True, "medium", 55, "os_unresponsive_hyperv",
                  "VM Running sull'host Hyper-V ma nessuna risposta di rete → VM accesa, "
                  "SO forse non risponde. Verifica.")

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
    # Nessun dato (mai pollato, nessun probe WAN, nessun L2) → non giudicabile
    if s.get("ping") is None and not s.get("l2_alive") and fw_up is None and rt_up is None:
        return _V(False, False, "none", 0, "no_data", "Nessun dato di monitoraggio ancora disponibile.")
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
    if s.get("ping") is None and not s.get("l2_alive"):
        return _V(False, False, "none", 0, "no_data", "Nessun dato di monitoraggio ancora disponibile.")
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
    if s.get("ping") is None and not s.get("l2_alive") and s.get("datto") is None:
        return _V(False, False, "none", 0, "no_data", "Nessun dato di monitoraggio ancora disponibile.")
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
