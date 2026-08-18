"""Aggregated client overview for NOC Dashboard."""
from fastapi import APIRouter, Depends
from database import db
from deps import get_current_user
from datetime import datetime, timezone, timedelta
from display_name import best_display_name
from device_type_resolver import best_device_type, is_endpoint_type
from liveness_resolver import (
    build_evidence_maps, compute_status, build_clients_without_online_agent,
    build_blackout_clients,
)

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview/clients")
async def get_clients_overview(current_user: dict = Depends(get_current_user)):
    """Returns aggregated status for all clients: WAN, devices, alerts, backup, printers."""
    clients_raw = await db.clients.find({}, {"_id": 0}).to_list(500)
    clients = clients_raw if isinstance(clients_raw, list) else []

    # Pre-fetch all data in parallel-ish
    wan_targets = await db.wan_targets.find({"enabled": True}, {"_id": 0}).to_list(1000)
    wan_results_raw = await db.wan_probe_results.find({}, {"_id": 0}).to_list(5000)

    active_alerts = await db.alerts.find(
        {"status": "active"}, {"_id": 0, "client_id": 1, "severity": 1, "title": 1, "device_name": 1, "created_at": 1, "id": 1}
    ).to_list(10000)

    devices = await db.devices.find({}, {"_id": 0, "client_id": 1, "status": 1, "ip_address": 1, "name": 1, "device_type": 1}).to_list(10000)

    # Also include connector-discovered devices (device_poll_status) and manually managed devices (managed_devices)
    # Also need reachable + last_poll to infer status
    poll_devices = await db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "device_ip": 1, "device_name": 1, "sys_name": 1, "sys_descr": 1, "sys_object_id": 1, "status": 1, "device_type": 1, "device_class": 1, "reachable": 1, "last_poll": 1, "monitor_type": 1, "consecutive_failures": 1, "last_reachable_at": 1, "vendor": 1, "model": 1, "method": 1, "ping_method": 1}
    ).to_list(10000)
    managed_devices_raw = await db.managed_devices.find(
        {}, {"_id": 0, "client_id": 1, "ip": 1, "mac": 1, "name": 1, "name_locked": 1, "hostname": 1, "mdns_name": 1, "fingerbank_device_name": 1, "device_type": 1, "device_type_user_locked": 1, "vendor": 1, "model": 1, "sys_descr": 1, "sys_object_id": 1, "mac_is_random": 1, "source": 1, "last_seen_at": 1, "is_vital": 1}
    ).to_list(10000)
    # Build maps for dedup merging by (client_id, ip)
    seen_device_keys = {(d.get("client_id"), d.get("ip_address")) for d in devices if d.get("ip_address")}
    managed_by_key = {(m.get("client_id"), m.get("ip")): m for m in managed_devices_raw if m.get("ip")}

    # v4.17.x EVIDENCE-BASED LIVENESS UNIFICATO: stessa logica di /api/devices.
    # Prima qui filtravamo solo source_connector_mode=scanner ed entro 10 min.
    # Ora usiamo build_evidence_maps() che include anche agent_v4 ARP e FDB
    # switch SNMP, con finestra 15 min, allineando esattamente Panoramica
    # e lista Dispositivi.
    ip_evidence, mac_evidence = await build_evidence_maps(db, window_minutes=15)
    # v2026-02-13 CASCADE FIX: identifica i client con TUTTI i connector
    # offline. I device "offline" per debounce di questi client vengono
    # marcati "stale" (stato incerto) invece di "offline" (fault confermato).
    # Mitiga il bug Galvan dove ZITACSRV offline → 36 device "offline" cascade
    # → card cliente tutta rossa anche se i device probabilmente sono OK.
    offline_clients = await build_clients_without_online_agent(db)
    # v2026-blackout: sottoinsieme di offline_clients con ANCHE la WAN giu'
    # (sonda Center indipendente). Per questi il device diventa OFFLINE (rosso),
    # non solo "stale": abbiamo la prova indipendente del blackout del sito.
    blackout_clients = await build_blackout_clients(db, offline_clients)
    poll_by_key = {(p.get("client_id"), p.get("device_ip")): p for p in poll_devices}

    # Merge poll_devices and managed_devices into the unified list (skip duplicates)
    for pd in poll_devices:
        ip = pd.get("device_ip")
        cid = pd.get("client_id")
        if not ip or not cid:
            continue
        key = (cid, ip)
        if key in seen_device_keys:
            continue
        seen_device_keys.add(key)
        md = managed_by_key.get(key, {})
        display_name = best_display_name(md, pd, ip)
        dev_type = best_device_type(md, pd, name_hint=display_name)
        # Status centralizzato: identico a /api/devices
        # (evidence override -> debounce -> cascade-stale -> scanner-source -> pending)
        status, _evidence = compute_status(pd, md, ip_evidence, mac_evidence, offline_clients, blackout_clients)
        devices.append({
            "client_id": cid,
            "name": display_name,
            "ip_address": ip,
            "status": status,
            "device_type": dev_type,
            "is_vital": md.get("is_vital"),
        })
    # Also add managed_devices that never polled yet
    for md in managed_devices_raw:
        ip = md.get("ip")
        cid = md.get("client_id")
        if not ip or not cid:
            continue
        key = (cid, ip)
        if key in seen_device_keys:
            continue
        seen_device_keys.add(key)
        # Status centralizzato: stessa logica del branch polled
        # (gestisce scanner-source + evidence FDB/ARP cross-VLAN + cascade-stale).
        pd = poll_by_key.get(key)
        md_status, _ev = compute_status(pd, md, ip_evidence, mac_evidence, offline_clients, blackout_clients)
        devices.append({
            "client_id": cid,
            "name": best_display_name(md, pd, ip),
            "ip_address": ip,
            "status": md_status,
            "device_type": best_device_type(md, pd),
            "is_vital": md.get("is_vital"),
        })

    # === VITAL-ONLY SCOPING (richiesto utente 2026-07-24) ===
    # La Panoramica deve mostrare SEMPRE E SOLO situazione + alert dei dispositivi
    # VITALI. Costruiamo qui l'insieme (per cliente) di nomi e IP vitali per:
    #  - scopare gli alert (per device_name)
    #  - calcolare salute/conteggi solo sui vitali (piu' sotto).
    vital_names_by_client: dict[str, set] = {}
    vital_ips_by_client: dict[str, set] = {}
    for d in devices:
        cid = d.get("client_id")
        if not cid:
            continue
        iv = d.get("is_vital")
        if iv is None:
            _mv = managed_by_key.get((cid, d.get("ip_address")))
            iv = _mv.get("is_vital") if _mv else None
        if iv is True:
            nm = (d.get("name") or "").strip().lower()
            if nm:
                vital_names_by_client.setdefault(cid, set()).add(nm)
            ipx = d.get("ip_address")
            if ipx:
                vital_ips_by_client.setdefault(cid, set()).add(ipx)


    # Backup status (legacy)
    backup_data = await db.backup_status.find({}, {"_id": 0, "client_id": 1, "status": 1, "last_success": 1}).to_list(5000)

    # === Hornetsecurity 365 Total Backup aggregato per cliente via mapping ===
    # Schema mapping: clients.hornetsecurity_tenants = list of str (whole tenant)
    # oppure dict {tenant, sub_groups: [...]}
    m365_by_client: dict[str, dict[str, int]] = {}
    clients_hs_raw = await db.clients.find(
        {"hornetsecurity_tenants": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "hornetsecurity_tenants": 1},
    ).to_list(500)
    if clients_hs_raw:
        m365_workloads = await db.backup_job_status.find(
            {"source": "hornetsecurity"},
            {"_id": 0, "tenant": 1, "sub_group": 1, "status": 1},
        ).to_list(20000)
        for c in clients_hs_raw:
            cid = c.get("id")
            raw = c.get("hornetsecurity_tenants") or []
            if isinstance(raw, str):
                raw = [raw]
            filters = []
            for it in raw:
                if isinstance(it, str) and it.strip():
                    filters.append((it.strip(), None))
                elif isinstance(it, dict) and (it.get("tenant") or "").strip():
                    sg = it.get("sub_groups")
                    if isinstance(sg, list) and sg:
                        filters.append((it["tenant"].strip(), {str(x).lower() for x in sg if x}))
                    else:
                        filters.append((it["tenant"].strip(), None))
            if not filters:
                continue
            agg = {"total": 0, "ok": 0, "error": 0}
            for w in m365_workloads:
                t = w.get("tenant")
                sg = w.get("sub_group")
                for (ft, fsg) in filters:
                    if ft != t:
                        continue
                    if fsg is not None and sg not in fsg:
                        continue
                    agg["total"] += 1
                    st = w.get("status")
                    if st == "success":
                        agg["ok"] += 1
                    elif st == "failed":
                        agg["error"] += 1
                    break
            m365_by_client[cid] = agg

    # === Hornetsecurity VM Backup (Altaro) aggregato per cliente ===
    vm_by_client: dict[str, dict[str, int]] = {}
    clients_vm_raw = await db.clients.find(
        {"hornetsecurity_vm_customers": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "hornetsecurity_vm_customers": 1},
    ).to_list(500)
    if clients_vm_raw:
        vm_workloads = await db.vmbackup_jobs.find(
            {"source": "hornetsecurity-vm"},
            {"_id": 0, "customer_name": 1, "host_name": 1, "alert_reason": 1, "onsite_status": 1},
        ).to_list(20000)
        for c in clients_vm_raw:
            cid = c.get("id")
            raw_vm = c.get("hornetsecurity_vm_customers") or []
            if isinstance(raw_vm, str):
                raw_vm = [raw_vm]
            # Filters: str → (customer, None) | dict → (customer, hosts_set|None)
            vm_filters = []
            for it in raw_vm:
                if isinstance(it, str) and it.strip():
                    vm_filters.append((it.strip(), None))
                elif isinstance(it, dict) and (it.get("customer") or "").strip():
                    hs = it.get("hosts")
                    if isinstance(hs, list) and hs:
                        vm_filters.append((it["customer"].strip(), {str(h) for h in hs if h}))
                    else:
                        vm_filters.append((it["customer"].strip(), None))
            if not vm_filters:
                continue
            agg = {"total": 0, "ok": 0, "error": 0, "warning": 0, "stale": 0}
            for w in vm_workloads:
                cn = w.get("customer_name")
                hn = w.get("host_name") or ""
                match = False
                for (fc, fh) in vm_filters:
                    if fc != cn:
                        continue
                    if fh is not None and hn not in fh:
                        continue
                    match = True
                    break
                if not match:
                    continue
                agg["total"] += 1
                r = w.get("alert_reason")
                if r == "failed":
                    agg["error"] += 1
                elif r == "warning":
                    agg["warning"] += 1
                elif r == "stale":
                    agg["stale"] += 1
                elif w.get("onsite_status") == "success":
                    agg["ok"] += 1
            vm_by_client[cid] = agg

    # Printer status
    printer_data = await db.printers.find({}, {"_id": 0, "client_id": 1, "toner_levels": 1, "status": 1}).to_list(5000)

    # Connector status
    # v3.8.41 watchdog: includiamo last_lan_scan_at + mode + hostname per
    # rilevare scanner inattivi (sub-thread Poll-LanEndpoints crashato).
    connectors = await db.connector_status.find(
        {},
        {"_id": 0, "client_id": 1, "last_seen": 1, "last_lan_scan_at": 1,
         "mode": 1, "hostname": 1, "online": 1},
    ).to_list(500)

    # v2026-02-feb FIX CRITICO: il nuovo Go Agent v4.x scrive l'heartbeat in
    # `managed_agents.last_heartbeat_at` (via WebSocket /api/agent/ws), NON
    # in `connector_status`. I client che hanno migrato al nuovo agent (es.
    # Galvan, Zitac) risultavano sempre "CONN. OFF" anche se in realtà
    # l'agent v4 era online e i dati SNMP/discovery erano freschi. Carichiamo
    # anche gli agent v4 e li uniamo all'elenco connector per il calcolo di
    # `connector_online`.
    v4_agents = await db.managed_agents.find(
        {},
        {"_id": 0, "client_id": 1, "hostname": 1, "agent_id": 1,
         "last_heartbeat_at": 1, "last_seen_at": 1, "last_hello_at": 1,
         "connected": 1},
    ).to_list(1000)

    # Index by client_id
    wan_results_map = {}
    for r in wan_results_raw:
        wan_results_map[r.get("target_id")] = r

    wan_targets_by_client = {}
    for t in wan_targets:
        cid = t.get("client_id")
        if cid not in wan_targets_by_client:
            wan_targets_by_client[cid] = []
        wan_targets_by_client[cid].append(t)

    alerts_by_client = {}
    alerts_detail_by_client = {}
    # v3.8.29 FIX: gestione severity sconosciute (es. "info", "notice", null)
    # senza far crashare l'endpoint con KeyError. Il counter di severity custom
    # viene aggiunto dinamicamente al dict.
    for a in active_alerts:
        cid = a.get("client_id")
        # VITAL-ONLY: conta solo gli alert che riguardano un dispositivo VITALE.
        # Gli alert senza device_name (livello sito/cliente, es. WAN/connettore)
        # vengono mantenuti perche' impattano comunque i vitali.
        adev = (a.get("device_name") or "").strip().lower()
        if adev:
            vset = vital_names_by_client.get(cid) or set()
            if adev not in vset:
                continue
        if cid not in alerts_by_client:
            alerts_by_client[cid] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
            alerts_detail_by_client[cid] = []
        sev = (a.get("severity") or "low").lower()
        # Normalizzo severity non standard verso "low" (info/notice/debug -> low)
        if sev not in alerts_by_client[cid]:
            alerts_by_client[cid][sev] = 0
        alerts_by_client[cid][sev] += 1
        alerts_by_client[cid]["total"] += 1
        if len(alerts_detail_by_client[cid]) < 5:
            alerts_detail_by_client[cid].append({
                "id": a.get("id"), "severity": a.get("severity"), "title": a.get("title", ""),
                "device_name": a.get("device_name", ""), "created_at": a.get("created_at", ""),
            })

    def _empty_counts():
        return {"total": 0, "online": 0, "offline": 0, "stale": 0, "unknown": 0,
                "vital_total": 0, "vital_online": 0, "vital_offline": 0, "vital_stale": 0}

    # v2026-06 CATEGORIZZAZIONE ENDPOINT vs INFRASTRUTTURA:
    # I PC consumer (workstation/mobile/iot/endpoint) NON devono influenzare
    # le statistiche e la salute dell'infrastruttura. Vengono contati in un
    # blocco separato `endpoints`. Il conteggio VITALI resta trasversale (un PC
    # marcato vitale conta comunque nei vitali del cliente).
    devices_by_client = {}
    endpoints_by_client = {}
    devices_detail_by_client = {}
    endpoints_detail_by_client = {}
    vital_detail_by_client = {}  # SOLO dispositivi vitali (per vista mobile tecnici)
    for d in devices:
        cid = d.get("client_id")
        status = d.get("status")
        # Normalizza status legacy (db.devices usa "active"/"inactive") verso lo
        # schema unificato online/offline cosi' conteggi e liste sono coerenti.
        if status == "active":
            status = "online"
        elif status == "inactive":
            status = "offline"
        is_ep = is_endpoint_type(d.get("device_type"))
        if is_ep:
            bucket = endpoints_by_client
            detail_bucket = endpoints_detail_by_client
        else:
            bucket = devices_by_client
            detail_bucket = devices_detail_by_client
        if cid not in bucket:
            bucket[cid] = _empty_counts()
            detail_bucket[cid] = []
        bucket[cid]["total"] += 1
        if status == "online":
            bucket[cid]["online"] += 1
        elif status == "offline":
            bucket[cid]["offline"] += 1
        elif status == "stale":
            bucket[cid]["stale"] += 1
        else:
            bucket[cid]["unknown"] += 1
        # Conteggio VITALI trasversale: is_vital dal merge, fallback lookup
        # managed_devices. I vitali vengono sempre aggregati nel blocco `devices`
        # (infrastruttura) cosi' il badge "N/M VITALI" della card resta coerente
        # anche se un vitale e' un PC/endpoint.
        _iv = d.get("is_vital")
        if _iv is None:
            _mv = managed_by_key.get((cid, d.get("ip_address")))
            _iv = _mv.get("is_vital") if _mv else None
        if _iv is True:
            if cid not in devices_by_client:
                devices_by_client[cid] = _empty_counts()
            devices_by_client[cid]["vital_total"] += 1
            if status == "online":
                devices_by_client[cid]["vital_online"] += 1
            elif status == "offline":
                devices_by_client[cid]["vital_offline"] += 1
            elif status == "stale":
                devices_by_client[cid]["vital_stale"] += 1
            vital_detail_by_client.setdefault(cid, []).append({
                "name": d.get("name", "?"), "ip": d.get("ip_address", ""),
                "status": status or "unknown", "type": d.get("device_type", ""),
            })
        detail_bucket[cid].append({
            "name": d.get("name", "?"), "ip": d.get("ip_address", ""), "status": status or "unknown",
            "type": d.get("device_type", ""),
        })

    backup_by_client = {}
    for b in backup_data:
        cid = b.get("client_id")
        if cid not in backup_by_client:
            backup_by_client[cid] = {"ok": 0, "warning": 0, "error": 0, "total": 0, "stale": 0}
        st = b.get("status", "unknown")
        backup_by_client[cid]["total"] += 1
        if st in ("ok", "success", "completed"):
            backup_by_client[cid]["ok"] += 1
        elif st in ("warning",):
            backup_by_client[cid]["warning"] += 1
        else:
            backup_by_client[cid]["error"] += 1

    # Fondi i contatori Hornetsecurity 365 + VM (se presenti) nei totali per-cliente
    for cid, m in m365_by_client.items():
        if cid not in backup_by_client:
            backup_by_client[cid] = {"ok": 0, "warning": 0, "error": 0, "total": 0, "stale": 0}
        backup_by_client[cid]["total"] += m.get("total", 0)
        backup_by_client[cid]["ok"] += m.get("ok", 0)
        backup_by_client[cid]["error"] += m.get("error", 0)
    for cid, v in vm_by_client.items():
        if cid not in backup_by_client:
            backup_by_client[cid] = {"ok": 0, "warning": 0, "error": 0, "total": 0, "stale": 0}
        backup_by_client[cid]["total"] += v.get("total", 0)
        backup_by_client[cid]["ok"] += v.get("ok", 0)
        backup_by_client[cid]["error"] += v.get("error", 0)
        backup_by_client[cid]["warning"] += v.get("warning", 0)
        backup_by_client[cid]["stale"] += v.get("stale", 0)

    printer_by_client = {}
    for p in printer_data:
        cid = p.get("client_id")
        if cid not in printer_by_client:
            printer_by_client[cid] = {"total": 0, "low_toner": 0, "ok": 0}
        printer_by_client[cid]["total"] += 1
        toner = p.get("toner_levels", {})
        min_toner = min(toner.values()) if toner and isinstance(toner, dict) else 100
        if min_toner < 15:
            printer_by_client[cid]["low_toner"] += 1
        else:
            printer_by_client[cid]["ok"] += 1

    connector_by_client = {}
    # v3.8.41 watchdog: scanner_health per cliente — rileva quando il sub-thread
    # Poll-LanEndpoints del Master Connector e' bloccato (last_lan_scan_at >30min).
    # Permette al frontend di mostrare un banner "Scanner inattivo da Xh, riavvia
    # il servizio" senza richiedere modifiche al connector PowerShell.
    SCANNER_HEALTH_STALE_MIN = 30
    scanner_health_by_client = {}
    now = datetime.now(timezone.utc)
    for c in connectors:
        cid = c.get("client_id")
        last_seen = c.get("last_seen")
        is_online = False
        if last_seen:
            if isinstance(last_seen, str):
                try:
                    ls = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    is_online = (now - ls).total_seconds() < 120
                except Exception:
                    pass
            elif isinstance(last_seen, datetime):
                is_online = (now - last_seen).total_seconds() < 120
        # v3.8.22: se il cliente ha PIU' connector (master + scanner), basta
        # che UNO sia online perche' connector_online sia true. Non sovrascrivere
        # un True con un False successivo.
        if cid in connector_by_client:
            connector_by_client[cid] = connector_by_client[cid] or is_online
        else:
            connector_by_client[cid] = is_online

        # v3.8.41 calcolo scanner_health (per ogni connector che fa lan-scan)
        last_scan_raw = c.get("last_lan_scan_at")
        if last_scan_raw:
            try:
                ls_dt = datetime.fromisoformat(last_scan_raw.replace("Z", "+00:00"))
                age_min = int((now - ls_dt).total_seconds() / 60)
                is_stale = age_min > SCANNER_HEALTH_STALE_MIN
                entry = {
                    "hostname": c.get("hostname") or "",
                    "mode": c.get("mode") or "master",
                    "last_lan_scan_at": last_scan_raw,
                    "minutes_since_last_scan": age_min,
                    "is_stale": is_stale,
                }
                if cid not in scanner_health_by_client:
                    scanner_health_by_client[cid] = []
                scanner_health_by_client[cid].append(entry)
            except Exception:
                pass

    # v2026-02-feb FIX CRITICO (continua): include heartbeat dei Go Agent v4
    # nel calcolo di connector_online. Soglia 300s (5 min) coerente con il
    # watchdog SNMP del nuovo agent (heartbeat: 15s, tolleranza per network
    # jitter / brief disconnects). Se ALMENO un agent (legacy O v4) è online
    # per il cliente, connector_online=True.
    AGENT_V4_FRESH_SECONDS = 300
    for a in v4_agents:
        cid = a.get("client_id")
        if not cid:
            continue
        # Prendi il timestamp più recente disponibile tra heartbeat / hello / seen
        candidates = [a.get("last_heartbeat_at"), a.get("last_seen_at"), a.get("last_hello_at")]
        is_online = False
        for ts in candidates:
            if not ts:
                continue
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    dt = ts
                else:
                    continue
                if (now - dt).total_seconds() < AGENT_V4_FRESH_SECONDS:
                    is_online = True
                    break
            except Exception:
                continue
        # Stesso pattern del legacy: True ha priorità su False (OR logico)
        if cid in connector_by_client:
            connector_by_client[cid] = connector_by_client[cid] or is_online
        else:
            connector_by_client[cid] = is_online

    # Build response
    result = []
    for c in clients:
        cid = c.get("id")
        alerts_info = alerts_by_client.get(cid, {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0})
        devices_info = devices_by_client.get(cid, _empty_counts())
        endpoints_info = endpoints_by_client.get(cid, _empty_counts())
        backup_info = backup_by_client.get(cid, {"ok": 0, "warning": 0, "error": 0, "total": 0, "stale": 0})
        printer_info = printer_by_client.get(cid, {"total": 0, "low_toner": 0, "ok": 0})
        wan_tgts = wan_targets_by_client.get(cid, [])
        connector_online = connector_by_client.get(cid)

        # WAN summary — compute from probe results directly
        wan_status = "not_configured"
        wan_latency = None
        wan_gateway = None
        if wan_tgts:
            all_online = True
            any_online = False
            best_latency = None
            has_gateway = False
            gw_online = None
            for t in wan_tgts:
                r = wan_results_map.get(t.get("id"))
                if not r:
                    continue
                st = r.get("status", "unknown")
                if st in ("online", "degraded"):
                    any_online = True
                else:
                    all_online = False
                lat = r.get("ping", {}).get("latency_ms")
                if lat and (best_latency is None or lat < best_latency):
                    best_latency = lat
                # Check gateway
                gw = r.get("gateway_ping")
                if gw:
                    has_gateway = True
                    if gw.get("reachable"):
                        gw_online = "online"
                    elif gw_online is None:
                        gw_online = "offline"

            wan_latency = best_latency
            wan_gateway = gw_online
            if any_online and all_online:
                wan_status = "ok"
            elif any_online:
                wan_status = "degraded"
            elif has_gateway and gw_online == "online":
                wan_status = "router_down"
            elif has_gateway and gw_online == "offline":
                wan_status = "isp_down"
            elif not any_online and len([t for t in wan_tgts if wan_results_map.get(t.get("id"))]) > 0:
                wan_status = "offline"
            else:
                wan_status = "pending"

        # Overall health score — VITAL-ONLY (richiesto utente 2026-07-24):
        # la salute del cliente riflette SOLO i dispositivi vitali (+ connettore/WAN
        # che comunque impattano i vitali). I device non-vitali non alterano il dot.
        devices_offline = devices_info.get("vital_offline", 0) if isinstance(devices_info, dict) else 0
        devices_stale = devices_info.get("vital_stale", 0) if isinstance(devices_info, dict) else 0
        backup_errors = backup_info.get("error", 0) if isinstance(backup_info, dict) else 0
        backup_warnings = backup_info.get("warning", 0) if isinstance(backup_info, dict) else 0
        backup_stale = backup_info.get("stale", 0) if isinstance(backup_info, dict) else 0
        toner_low = printer_info.get("low_toner", 0) if isinstance(printer_info, dict) else 0

        health = "ok"
        # CRITICAL: qualcosa di importante non funziona ORA
        # NOTA: devices_stale NON e' critical (mitiga cascata "connector down ->
        # 36 device cascata-offline -> card rossa", vedi liveness_resolver
        # build_clients_without_online_agent). Quando il connector e' giu'
        # il connector_online=False fa scattare comunque critical per il
        # CONNETTORE, evitando di nascondere il problema reale.
        if (devices_offline > 0
                or connector_online is False
                or wan_status in ("isp_down", "firewall_down", "router_down", "offline")):
            health = "critical"
        # WARNING: degradi noti + device stale (monitor offline)
        elif (wan_status in ("firewall_degraded", "router_degraded", "degraded")
                or backup_errors > 0 or backup_warnings > 0 or backup_stale > 0
                or devices_stale > 0):
            health = "warning"
        # ATTENTION: piccole anomalie da monitorare (toner basso)
        elif toner_low > 0:
            health = "attention"
        # else: ok (verde) — ANCHE con alert in coda, che sono mostrati nel pill dedicato

        # WAN targets detail for expansion
        wan_detail = []
        for t in wan_tgts:
            r = wan_results_map.get(t.get("id"))
            wan_detail.append({
                "label": t.get("label", "?"), "device_type": t.get("device_type", "?"),
                "ip": t.get("public_ip", ""), "gateway_ip": t.get("gateway_ip"),
                "check_ping": t.get("check_ping", False),
                "status": r.get("status", "unknown") if r else "pending",
                "latency_ms": r.get("ping", {}).get("latency_ms") if r else None,
                "loss_pct": r.get("ping", {}).get("packet_loss_pct") if r else None,
                "gateway_ok": r.get("gateway_ping", {}).get("reachable") if r and r.get("gateway_ping") else None,
                "gateway_latency": r.get("gateway_ping", {}).get("latency_ms") if r and r.get("gateway_ping") else None,
                "ports": r.get("ports", []) if r else [],
                "checked_at": r.get("checked_at") if r else None,
            })

        result.append({
            "id": cid,
            "name": c.get("name", "?"),
            "health": health,
            "alerts": alerts_info,
            "devices": devices_info,
            "wan": {
                "status": wan_status,
                "latency_ms": wan_latency,
                "gateway": wan_gateway,
            },
            "backup": backup_info,
            "printers": printer_info,
            "endpoints": endpoints_info,
            "connector_online": connector_online,
            # v3.8.41: lista scanner per cliente con info su staleness (per banner watchdog UI)
            "scanner_health": scanner_health_by_client.get(cid, []),
            "detail": {
                "wan_targets": wan_detail,
                "devices_list": devices_detail_by_client.get(cid, []),
                "endpoints_list": endpoints_detail_by_client.get(cid, []),
                "vital_list": sorted(
                    vital_detail_by_client.get(cid, []),
                    key=lambda x: {"offline": 0, "stale": 1, "unknown": 2, "online": 3}.get(x.get("status"), 4),
                ),
                "recent_alerts": alerts_detail_by_client.get(cid, []),
            },
        })

    # Sort: critical first, then warning, then ok
    priority = {"critical": 0, "warning": 1, "attention": 2, "ok": 3}
    result.sort(key=lambda x: (priority.get(x["health"], 9), x["name"]))

    # Global stats
    total_alerts = sum(a["total"] for a in alerts_by_client.values())
    total_critical = sum(a["critical"] for a in alerts_by_client.values())

    return {
        "clients": result,
        "global": {
            "total_clients": len(clients),
            "clients_ok": sum(1 for r in result if r["health"] == "ok"),
            "clients_warning": sum(1 for r in result if r["health"] in ("warning", "attention")),
            "clients_critical": sum(1 for r in result if r["health"] == "critical"),
            "total_alerts": total_alerts,
            "critical_alerts": total_critical,
            "total_devices": sum(d["vital_total"] for d in devices_by_client.values()),
            "devices_online": sum(d["vital_online"] for d in devices_by_client.values()),
            "total_endpoints": sum(d["total"] for d in endpoints_by_client.values()),
            "endpoints_online": sum(d["online"] for d in endpoints_by_client.values()),
        },
    }



@router.get("/overview/site-down")
async def get_sites_down(current_user: dict = Depends(get_current_user)):
    """Sedi attualmente in BLACKOUT confermato (agent giu' + WAN giu'), con il
    timestamp di inizio ('down_since') per il timer "giu' da X min" del banner
    globale SITE DOWN. Verita' LIVE: usa build_blackout_clients, non solo lo
    stato persistito del watchdog."""
    offline_clients = await build_clients_without_online_agent(db)
    blackout_clients = await build_blackout_clients(db, offline_clients) if offline_clients else set()
    if not blackout_clients:
        return {"sites": [], "count": 0}

    clients = await db.clients.find(
        {"id": {"$in": list(blackout_clients)}}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(1000)
    name_by_id = {c["id"]: c.get("name", "") for c in clients}

    # down_since: preferisci lo stato del watchdog (first_at), poi l'alert di
    # correlazione attivo, infine 'adesso' (fallback → timer parte da 0).
    states = await db.site_blackout_state.find(
        {"client_id": {"$in": list(blackout_clients)}}, {"_id": 0, "client_id": 1, "first_at": 1}
    ).to_list(1000)
    first_by_id = {s["client_id"]: s.get("first_at") for s in states}
    now_iso = datetime.now(timezone.utc).isoformat()

    sites = []
    for cid in blackout_clients:
        down_since = first_by_id.get(cid)
        if not down_since:
            corr = await db.alerts.find_one(
                {"client_id": cid, "status": "active",
                 "source_type": {"$in": ["site_blackout", "corr_site_power_down", "corr_site_isolated"]}},
                {"_id": 0, "created_at": 1}, sort=[("created_at", 1)],
            )
            down_since = (corr or {}).get("created_at") or now_iso
        sites.append({
            "client_id": cid,
            "client_name": name_by_id.get(cid) or (cid[:8] if cid else "?"),
            "down_since": down_since,
        })
    sites.sort(key=lambda s: s["down_since"])
    return {"sites": sites, "count": len(sites)}
