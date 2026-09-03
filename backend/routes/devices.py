"""Device CRUD and credentials routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Optional, Dict, Any
import uuid
import re
from datetime import datetime, timezone, timedelta

from database import db
from models import DeviceCreate, DeviceResponse, DeviceCredentials, RedfishTestRequest
from security import security_manager
from audit import AuditAction
from deps import get_current_user, audit_logger, redfish_poller
from display_name import best_display_name
from device_type_resolver import best_device_type

router = APIRouter(prefix="/api", tags=["devices"])


@router.post("/devices", response_model=DeviceResponse)
async def create_device(device: DeviceCreate, current_user: dict = Depends(get_current_user)):
    client = await db.clients.find_one({"id": device.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    device_doc = {
        "id": str(uuid.uuid4()), "client_id": device.client_id,
        "name": device.name, "device_type": device.device_type,
        "ip_address": device.ip_address, "hostname": device.hostname or "",
        "location": device.location or "", "status": "active",
        "redfish_enabled": device.redfish_enabled or False,
        "last_poll": None, "health_status": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.devices.insert_one(device_doc)
    await audit_logger.log(
        AuditAction.CREATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_doc["id"],
        details={"name": device.name, "type": device.device_type}
    )
    return DeviceResponse(**device_doc, client_name=client["name"], has_credentials=False)


@router.get("/devices")
async def get_devices(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id

    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch manually added devices
    devices = await db.devices.find(query, {"_id": 0}).to_list(1000)
    manual_ips = {d["ip_address"] for d in devices}

    # Fetch connector-reported devices (device_poll_status).
    # v4.15.x BUG-FIX multi-connector: ci possono essere PIU' record per
    # lo stesso IP (uno per agent_id) — es. master + scanner sullo stesso
    # cliente. Se prendiamo random, il record "sbagliato" (cross-VLAN,
    # reachable=false) puo' mascherare quello "buono" del master.
    # Strategia di scelta:
    #   1) Preferisci record reachable=true e con last_ping_at piu' recente
    #   2) In caso di pareggio, prendi il last_ping_at piu' recente in assoluto
    poll_query = query.copy()
    poll_devices = await db.device_poll_status.find(poll_query, {"_id": 0}).to_list(5000)

    # v4.15.x ZOMBIE V3 PROTECTION: se per questo cliente esiste un agent v4
    # master LIVE (heartbeat negli ultimi 3 min), allora **ignoriamo
    # completamente i record `device_poll_status` scritti dal vecchio
    # Connector v3 PowerShell** (che potrebbe ancora girare su un PC
    # dismenticato). Sintomo classico del v3 fantasma: tutti i device
    # OFFLINE con `unreachable_since=now` che cambia in tempo reale
    # nonostante un connector v4 sia LIVE. I record v4 hanno
    # `source="agent_v4"`. I record v3 hanno `source` assente o diverso.
    # NB: il campo per heartbeat e' `last_heartbeat_at` (impostato in
    # `_on_heartbeat`), non `last_seen_at`. Match con $or per essere
    # tolleranti se uno dei due e' stato impostato (e.g. da
    # registration vs heartbeat).
    v4_master_alive = False
    if client_id:
        try:
            three_min_ago_iso = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
            v4_master = await db.managed_agents.find_one(
                {"client_id": client_id, "role": "master",
                 "$or": [
                     {"last_heartbeat_at": {"$gte": three_min_ago_iso}},
                     {"last_seen_at": {"$gte": three_min_ago_iso}},
                 ]},
                {"_id": 0, "agent_id": 1, "hostname": 1},
            )
            v4_master_alive = v4_master is not None
        except Exception:
            v4_master_alive = False

    if v4_master_alive:
        before = len(poll_devices)
        poll_devices = [pd for pd in poll_devices if pd.get("source") == "agent_v4"]
        if before != len(poll_devices):
            import logging as _logging
            _logging.getLogger(__name__).info(
                "get_devices: zombie v3 protection for client %s — filtrati %d record legacy (rimasti %d v4)",
                client_id, before - len(poll_devices), len(poll_devices),
            )

    def _pd_ts(pd_doc):
        ts = (pd_doc.get("last_ping_at") or pd_doc.get("last_poll_at")
              or pd_doc.get("last_poll") or "")
        return ts or ""

    poll_by_ip: Dict[str, Any] = {}
    for pd in poll_devices:
        ip = pd.get("device_ip")
        if not ip:
            continue
        cur = poll_by_ip.get(ip)
        if cur is None:
            poll_by_ip[ip] = pd
            continue
        # Decidi quale tenere: reachable wins; se entrambi reachable o
        # entrambi non reachable, prendi quello piu' recente.
        cur_ok = bool(cur.get("ping_reachable") or cur.get("reachable"))
        new_ok = bool(pd.get("ping_reachable") or pd.get("reachable"))
        if new_ok and not cur_ok:
            poll_by_ip[ip] = pd
        elif cur_ok and not new_ok:
            pass  # tieni quello vecchio (reachable)
        else:
            # Stesso "reachable" → vince il piu' recente
            if _pd_ts(pd) > _pd_ts(cur):
                poll_by_ip[ip] = pd

    # Fetch managed devices for community/snmp info
    managed_query = query.copy()
    managed_devices_raw = await db.managed_devices.find(managed_query, {"_id": 0}).to_list(5000)
    managed_by_ip = {}
    # v2026-08 DEDUP-READ-MERGE (fix "salvo ma non mantiene / non categorizza"):
    # per lo stesso IP possono esistere piu' doc (canonico con `ip` + legacy con
    # solo `ip_address`). Le scritture finiscono su doc diversi a seconda
    # dell'endpoint; prima la lettura sceglieva UN doc "per punteggio" (che NON
    # includeva device_type!) e perdeva impostazioni/categoria salvate. Ora
    # FONDIAMO i duplicati: priorita' ai valori non vuoti del canonico, i campi
    # mancanti riempiti dai legacy → nessuna impostazione salvata va persa.
    def _md_nonempty(v):
        return v not in (None, "", [], {})

    def _merge_md(a, b):
        canonical = a if _md_nonempty(a.get("ip")) else b
        legacy = b if canonical is a else a
        merged = dict(legacy)
        for k, v in canonical.items():
            if _md_nonempty(v):
                merged[k] = v
        return merged

    for md in managed_devices_raw:
        md_ip = md.get("ip") or md.get("ip_address", "")
        if not md_ip:
            continue
        cur = managed_by_ip.get(md_ip)
        managed_by_ip[md_ip] = md if cur is None else _merge_md(cur, md)

    # v2026-07-24 DATTO-AS-EVIDENCE (fix falso-rosso su server ICMP-bloccati):
    # i server Windows/Hyper-V spesso bloccano ICMP e possono NON comparire in
    # ARP/FDB/SNMP (VM su vSwitch isolato) → risultavano OFFLINE (rosso) pur
    # essendo online. Se l'agent Datto RMM riporta il device ONLINE (heartbeat
    # fresco), lo usiamo come evidenza positiva per lo status del pallino,
    # esattamente come fa il motore di alerting (evidence fusion).
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _dnow = _dt.now(_tz.utc)
    datto_online_by_uid: dict = {}
    datto_online_by_ip: dict = {}
    datto_online_by_mac: dict = {}
    try:
        async for dd in db.datto_devices.find(
            {"online": True},
            {"_id": 0, "client_id": 1, "uid": 1, "ip": 1, "ip_list": 1,
             "mac": 1, "mac_list": 1, "datto_last_seen": 1},
        ):
            ls = dd.get("datto_last_seen")
            fresh = True
            if ls:
                try:
                    lsd = _dt.fromisoformat(str(ls).replace("Z", "+00:00"))
                    fresh = (_dnow - lsd) < _td(minutes=30)
                except Exception:
                    fresh = True
            if not fresh:
                continue
            cid = dd.get("client_id")
            if dd.get("uid"):
                datto_online_by_uid[(cid, dd["uid"])] = True
            for _ip in ([dd.get("ip")] + (dd.get("ip_list") or [])):
                if _ip:
                    datto_online_by_ip[(cid, _ip)] = True
            for _m in ([dd.get("mac")] + (dd.get("mac_list") or [])):
                _mn = (_m or "").lower().replace("-", ":")
                if _mn:
                    datto_online_by_mac[(cid, _mn)] = True
    except Exception:
        pass

    def _datto_online(md_doc, ip_val):
        cid = (md_doc or {}).get("client_id")
        uid = (md_doc or {}).get("datto_uid")
        if uid and datto_online_by_uid.get((cid, uid)):
            return True
        if ip_val and datto_online_by_ip.get((cid, ip_val)):
            return True
        _mn = ((md_doc or {}).get("mac") or "").lower().replace("-", ":")
        if _mn and datto_online_by_mac.get((cid, _mn)):
            return True
        return False

    # v2026-07-25: HYPER-V POWER STATE (fonte autorevole dall'host).
    # L'host Hyper-V riporta per ogni VM lo stato Running/Off/Saved/Paused via
    # agent WMI (hyperv_snapshots). E' la fonte piu' affidabile per sapere se
    # una VM e' accesa o spenta, indipendente da ICMP/firewall/rete:
    #   - Running  -> evidenza positiva di accensione (come Datto online)
    #   - Off/Saved/Paused -> VM SPENTA di proposito -> stato "off" (non offline)
    # Match VM->device per hostname corto (nome VM == hostname device), scoping
    # per cliente. Solo snapshot freschi (<15min) contano come "live evidence".
    def _short(s):
        return (str(s or "").strip().lower().split(".")[0])

    hyperv_state_by_key: dict = {}  # (cid, short_name) -> {"state":..., "host":...}
    try:
        async for snap in db.hyperv_snapshots.find(
            {}, {"_id": 0, "client_id": 1, "hostname": 1, "vms": 1, "collected_at": 1},
        ):
            ca = snap.get("collected_at")
            fresh = True
            if ca:
                try:
                    cad = _dt.fromisoformat(str(ca).replace("Z", "+00:00"))
                    fresh = (_dnow - cad) < _td(minutes=15)
                except Exception:
                    fresh = True
            if not fresh:
                continue
            cid = snap.get("client_id")
            for vm in (snap.get("vms") or []):
                nm = _short(vm.get("name"))
                if nm:
                    hyperv_state_by_key[(cid, nm)] = {
                        "state": (vm.get("state") or "").strip(),
                        "host": snap.get("hostname") or "",
                    }
    except Exception:
        pass

    def _hyperv_state(md_doc):
        """Ritorna (state, host) della VM Hyper-V matchata, o (None, None)."""
        cid = (md_doc or {}).get("client_id")
        for key in (md_doc.get("hyperv_vm_name"), md_doc.get("hostname"), md_doc.get("name"), md_doc.get("device_name")):
            k = _short(key)
            if k and (cid, k) in hyperv_state_by_key:
                e = hyperv_state_by_key[(cid, k)]
                return e.get("state"), e.get("host")
        return None, None

    _HV_OFF = {"Off", "Saved", "Paused"}


    # v3.8.22 SCANNER LIVE-SEEN: cross-check con discovered_endpoints.
    # Lo Scanner aggiorna SEMPRE discovered_endpoints (lan-scan ARP/mDNS) anche
    # per device aggiunti manualmente (source=manual / connector-master). Usiamo
    # questa collection come fonte di verita' "device visto recentemente sulla
    # rete dello Scanner". Se IP visto < 15min => online, prevale sul Master.
    # v4.16.x EVIDENCE-BASED LIVENESS: rimosso il filtro
    # `source_connector_mode=scanner` perche' escludeva i record dell'agent_v4
    # (Go connector) e quelli dalla MAC table SNMP degli switch (`switch_ip`,
    # `last_seen_via=snmp`). Ora consideriamo ONLINE qualsiasi IP che:
    #   - ha record in discovered_endpoints con last_seen_at < 15 min
    #   - O ha un MAC presente nella MAC table di uno switch managed
    #     (= la porta dello switch ha quel MAC nella sua FDB attiva)
    # Questo allinea la vista "Dispositivi" con quella "Switch ports" che
    # mostra UP/DOWN reale + traffico bps.
    DEBOUNCE_MIN_FAILURES = 3      # 3 cicli consecutivi falliti
    DEBOUNCE_GRACE_SECONDS = 300   # 5 minuti senza nessun successo
    SNMP_FRESHNESS_SECONDS = 600   # SNMP poll < 10 min = device raggiungibile
    def _effective_reachable(pd_doc):
        """True = mostra online, False = mostra offline.
        pd_doc e' il record di device_poll_status (puo' essere None o {}).

        v2026-06-12 fix critico "device sempre offline ma SNMP fresco":
        prima questa funzione guardava SOLO `reachable` (che e' il flag
        del ping ICMP). Su switch HP Comware, server Windows con firewall
        ICMP bloccato, ecc., il ping fallisce sempre ma SNMP funziona
        perfettamente -> la UI mostrava OFFLINE nonostante il connector
        passasse dati freschi. Ora consideriamo ONLINE anche un device
        che ha snmp_reachable=True con poll recente, indipendentemente
        dal ping. Lo stesso pattern di Zabbix: SNMP-only checks rendono
        l'host "Available SNMP", senza richiedere ICMP.
        """
        if not pd_doc:
            return False
        if pd_doc.get("reachable"):
            return True
        # v2026-06-12: SNMP-only liveness — se il poll SNMP e' fresco e
        # reachable=True, il device E' raggiungibile anche se ping fallisce.
        if pd_doc.get("snmp_reachable"):
            snmp_at = pd_doc.get("snmp_last_check_at") or pd_doc.get("last_poll_at")
            if snmp_at:
                try:
                    snmp_dt = datetime.fromisoformat(str(snmp_at).replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - snmp_dt).total_seconds() < SNMP_FRESHNESS_SECONDS:
                        return True
                except Exception:
                    pass
        # reachable=false: applichiamo debounce
        consec = int(pd_doc.get("consecutive_failures") or 0)
        last_ok = pd_doc.get("last_reachable_at")
        # Se non abbiamo ancora un successo registrato, comportamento legacy
        # (probabilmente device appena aggiunto o counter non ancora popolato):
        # se non c'e' last_reachable_at, ci fidiamo del flag reachable=false.
        if not last_ok:
            # Backward-compat: campi nuovi assenti → comportamento attuale (offline)
            return False
        try:
            last_ok_dt = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
            secs_since = (datetime.now(timezone.utc) - last_ok_dt).total_seconds()
        except Exception:
            secs_since = 1e9
        # offline solo se ENTRAMBE le condizioni sono superate
        if consec >= DEBOUNCE_MIN_FAILURES and secs_since >= DEBOUNCE_GRACE_SECONDS:
            return False
        return True

    # v4.16.x EVIDENCE TRACKING: per ogni IP / MAC visto recentemente,
    # tieni traccia di COME e' stato visto (via SNMP FDB switch, via scanner
    # ARP, via agent_v4 heartbeat). Cosi' la UI puo' mostrare "Vivo via"
    # con il metodo esatto, facilitando il debug.
    scanner_seen_recent_ips = {}   # ip -> evidence string
    scanner_seen_recent_macs = {}  # mac_lower -> evidence string
    try:
        fifteen_min_ago_iso = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        de_query = query.copy()
        de_query["last_seen_at"] = {"$gte": fifteen_min_ago_iso}
        async for de in db.discovered_endpoints.find(
            de_query,
            {"_id": 0, "ip": 1, "mac": 1, "source_connector_mode": 1,
             "last_seen_via": 1, "switch_ip": 1},
        ):
            de_ip = de.get("ip")
            de_mac = (de.get("mac") or "").lower().replace("-", ":")
            # Determine evidence label
            mode = (de.get("source_connector_mode") or "").lower()
            seen_via = (de.get("last_seen_via") or "").lower()
            has_switch = bool(de.get("switch_ip"))
            if has_switch or seen_via == "snmp":
                evidence = "mac_table_switch"
            elif mode == "agent_v4":
                evidence = "agent_v4_arp"
            elif mode == "scanner":
                evidence = "scanner_lan"
            else:
                evidence = seen_via or mode or "scanner"
            if de_ip and de_ip not in scanner_seen_recent_ips:
                scanner_seen_recent_ips[de_ip] = evidence
            if de_mac and de_mac not in scanner_seen_recent_macs:
                scanner_seen_recent_macs[de_mac] = evidence
    except Exception:
        pass

    # v4.17.x SEEN-BY: per ogni device managed, costruisci la lista degli
    # agent v4 che lo hanno effettivamente pollato/visto negli ultimi
    # 5 minuti. Usato per la colonna UI "Visto da".
    # Source 1: device_poll_status grouped by agent_id
    # Source 2: discovered_endpoints recenti del cliente
    seen_by_ip: Dict[str, List[Dict[str, str]]] = {}
    if client_id:
        try:
            five_min_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            # Mappa agent_id → hostname/role per il display
            agent_meta: Dict[str, Dict[str, str]] = {}
            async for a in db.managed_agents.find(
                {"client_id": client_id},
                {"_id": 0, "agent_id": 1, "hostname": 1, "role": 1},
            ):
                if a.get("agent_id"):
                    agent_meta[a["agent_id"]] = {
                        "hostname": a.get("hostname") or a["agent_id"][:8],
                        "role": a.get("role") or "master",
                    }
            # Source: device_poll_status (chi polla attualmente)
            async for ps in db.device_poll_status.find(
                {"client_id": client_id, "agent_id": {"$ne": None},
                 "last_ping_at": {"$gte": five_min_iso}},
                {"_id": 0, "device_ip": 1, "agent_id": 1, "ping_reachable": 1,
                 "reachable": 1, "method": 1},
            ):
                ip = ps.get("device_ip")
                aid = ps.get("agent_id")
                if not ip or not aid:
                    continue
                meta = agent_meta.get(aid)
                if not meta:
                    continue
                seen_by_ip.setdefault(ip, []).append({
                    "agent_id": aid,
                    "hostname": meta["hostname"],
                    "role": meta["role"],
                    "reachable": bool(ps.get("ping_reachable") or ps.get("reachable")),
                    "method": ps.get("method") or "",
                })
        except Exception:
            pass

    # Enrich manually-added devices with profile_key from managed_devices/poll_status
    for d in devices:
        ip = d.get("ip_address")
        if not ip:
            continue
        md = managed_by_ip.get(ip) or {}
        pd = poll_by_ip.get(ip) or {}
        d["profile_key"] = d.get("profile_key") or md.get("profile_key") or pd.get("profile_key")
        d["vendor"] = d.get("vendor") or md.get("vendor") or pd.get("vendor")
        d["family"] = d.get("family") or md.get("family") or pd.get("family")
        # alerts_silenced flag (managed_devices wins; default False)
        d["alerts_silenced"] = bool(md.get("alerts_silenced", d.get("alerts_silenced", False)))
        d["alerts_silenced_reason"] = md.get("alerts_silenced_reason") or d.get("alerts_silenced_reason") or ""
        # v2026-02-28: criticality tier (is_vital). True = mission critical
        # (alert sempre inviati). False = best-effort (alert silenziati di
        # default). Missing = backward compat (treat as undecided → emit).
        if "is_vital" in md:
            d["is_vital"] = bool(md.get("is_vital"))
        elif "is_vital" in d:
            d["is_vital"] = bool(d.get("is_vital"))
        # else: NOT setting is_vital → frontend distingue "non scelto" vs False
        # v2026-06: Hyper-V power state + alert opzionale "VM spenta" (managed_devices wins)
        _mhv_state, _mhv_host = _hyperv_state(md)
        d["hyperv_state"] = _mhv_state or d.get("hyperv_state") or ""
        d["hyperv_host"] = _mhv_host or d.get("hyperv_host") or ""
        d["hyperv_alert_on_off"] = bool(md.get("hyperv_alert_on_off", d.get("hyperv_alert_on_off", False)))
        d["virtualization"] = md.get("virtualization") or d.get("virtualization") or ""
        d["hyperv_vm_name"] = md.get("hyperv_vm_name") or d.get("hyperv_vm_name") or ""
        d["hyperv_host_hint"] = md.get("hyperv_host_hint") or d.get("hyperv_host_hint") or ""
        d["virtualization_auto_matched"] = bool(md.get("virtualization_auto_matched"))
        # v3.8.22 LIVE-SEEN: se lo Scanner ha visto questo IP nelle ultime 15min,
        # forza "online" anche se Master/manual lo davano per offline.
        # v4.16.x EXTEND: anche se il MAC e' nella MAC table SNMP recente di
        # uno switch managed (= device fisicamente collegato e attivo a livello L2)
        # forziamo "online". Cosi' i device che bloccano ICMP ma sono visibili
        # via FDB switch (Wildix phone, GALV-UFF, ecc.) vengono mostrati ONLINE
        # come dovrebbero.
        md_mac = ((md.get("mac") or "")).lower().replace("-", ":")
        ip_ev = scanner_seen_recent_ips.get(ip)
        mac_ev = scanner_seen_recent_macs.get(md_mac) if md_mac else None
        evidence = ip_ev or mac_ev
        # v2026-06-03 fix bug "pallino verde su device spento": NON promuovere
        # online via L2 evidence se il device_poll_status fresco dice
        # reachable=False (entry ARP/scanner cache stale del router). Solo
        # mac_table_switch (FDB SNMP) e' affidabile come single-source-of-truth.
        pd_reachable_explicit = pd.get("reachable") is not None
        if evidence == "mac_table_switch":
            d["status"] = "online"
            d["live_evidence"] = evidence
        elif evidence and (not pd_reachable_explicit or pd.get("reachable")):
            # ARP/scanner OK ed il ping non smentisce
            d["status"] = "online"
            d["live_evidence"] = evidence
        elif pd.get("reachable"):
            # Niente evidence L2 ma il ping_poll dice raggiungibile → mostra il method
            d["live_evidence"] = (pd.get("method") or pd.get("ping_method") or "ping").strip()
        # v4.17.x STATUS NORMALIZATION: i device manuali legacy (collection
        # `db.devices`) hanno default `status="active"`. La panoramica
        # considerava active=online, la tabella no → inconsistenza visiva.
        # Normalizziamo sempre a "online" se evidence/reachable/active.
        if d.get("status") == "active":
            d["status"] = "online"
        # v4.17.x SEEN-BY: lista agent che vedono questo device
        d["seen_by"] = seen_by_ip.get(ip, [])

    # Merge: add connector devices that aren't already in manual list
    for pd in poll_devices:
        ip = pd.get("device_ip", "")
        if ip and ip not in manual_ips:
            manual_ips.add(ip)
            # Get managed device config (community, snmp version, etc.)
            md = managed_by_ip.get(ip, {})
            # Device type centralizzato: best_device_type rispetta md.lock,
            # poi prova md.device_type, classifier (Printer-MIB OID + regex
            # multi-vendor), OUI vendor hint, infine "generic".
            # Risolve le incoerenze tra Panoramica e lista Dispositivi e
            # garantisce che es. tutte le stampanti finiscano sotto "printer".
            dev_type = best_device_type(md, pd)
            # Profile key: managed_devices wins over poll_status (manual override > auto-detect)
            profile_key = md.get("profile_key") or pd.get("profile_key")
            vendor = md.get("vendor") or pd.get("vendor")
            family = md.get("family") or pd.get("family")
            # v3.8.22: SCANNER OVERRIDE — se il device e' scoperto dallo Scanner
            # (source=connector-scanner) e visto recentemente (<5min), il Master
            # NON puo' decidere il suo status: la sua connettivita' L2 non
            # raggiunge la VLAN remota, quindi pd.reachable=false e' un falso
            # negativo. Diamo precedenza alla telemetria dello Scanner che lo vede.
            md_status = "online" if _effective_reachable(pd) else "offline"
            try:
                if md.get("source") == "connector-scanner" and md.get("last_seen_at"):
                    last_seen_dt = datetime.fromisoformat(md["last_seen_at"].replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - last_seen_dt).total_seconds() < 300:
                        md_status = "online"
            except Exception:
                pass
            # v3.8.22 LIVE-SEEN: anche per device manuali, se lo Scanner li vede
            # recentemente in discovered_endpoints, prevale "online".
            # v4.16.x EXTEND: anche match per MAC (FDB switch SNMP).
            md_mac_norm = ((md.get("mac") or "")).lower().replace("-", ":")
            ip_ev2 = scanner_seen_recent_ips.get(ip)
            mac_ev2 = scanner_seen_recent_macs.get(md_mac_norm) if md_mac_norm else None
            live_evidence2 = ip_ev2 or mac_ev2
            # v2026-06-03 fix bug "pallino verde su device spento": stessa
            # logica del branch manual. mac_table_switch = single source of
            # truth, altre evidence L2 valide solo se ping NON smentisce.
            if live_evidence2 == "mac_table_switch":
                md_status = "online"
            elif live_evidence2 and _effective_reachable(pd):
                md_status = "online"
            elif _effective_reachable(pd):
                live_evidence2 = (pd.get("method") or pd.get("ping_method") or "ping").strip()
            # v2026-07-24: Datto agent online (heartbeat fresco) come evidenza
            # positiva → niente falso-rosso su server ICMP-bloccati/non in FDB.
            if md_status == "offline" and _datto_online(md, ip):
                md_status = "online"
                live_evidence2 = "datto"
            # v2026-07-25: Hyper-V host = fonte autorevole di accensione VM.
            _hv_state, _hv_host = _hyperv_state(md)
            if md_status in ("offline", "pending") and _hv_state == "Running":
                md_status = "online"
                live_evidence2 = "hyperv"
            elif md_status in ("offline", "pending") and _hv_state in _HV_OFF:
                md_status = "off"
                live_evidence2 = "hyperv_off"
            # display name: priorità centralizzata su best_display_name():
            # sys_name (SNMP) → hostname (NBNS) → mdns_name → name → fingerbank.
            # Vedi nota nel branch managed_devices sotto.
            _pd_name = best_display_name(md, pd, ip)
            devices.append({
                "id": f"poll_{ip.replace('.','_')}",
                "client_id": pd.get("client_id", ""),
                "name": _pd_name,
                "device_type": dev_type,
                "ip_address": ip,
                "hostname": pd.get("sys_name", ""),
                "location": pd.get("sys_location", ""),
                "status": md_status,
                "live_evidence": live_evidence2,
                "seen_by": seen_by_ip.get(ip, []),
                "redfish_enabled": False,
                # v3.8.18: source = chi ha SCOPERTO il device, non chi lo polla.
                # Se il device esiste in managed_devices con source=connector-scanner,
                # e' stato scoperto dallo Scanner anche se ora il Master lo polla via SNMP.
                # Solo se NON e' in managed_devices o e' in con altro source -> "connector-master".
                "source": (md.get("source") if md.get("source") in ("connector-scanner", "connector-master") else "connector-master"),
                "auto_added": bool(md.get("auto_added", False)),
                "discovered_via": md.get("discovered_via"),
                "discovered_subnet": md.get("discovered_subnet"),
                "vlan_id": md.get("vlan_id"),
                "mac": md.get("mac", ""),
                "mac_is_random": bool(md.get("mac_is_random", False)),
                "fingerbank_device_name": md.get("fingerbank_device_name"),
                "fingerbank_score": md.get("fingerbank_score"),
                "mdns_name": md.get("mdns_name"),
                "mdns_services": md.get("mdns_services") or [],
                "http_server": md.get("http_server"),
                "notes": md.get("notes"),
                "connection_type": md.get("connection_type"),
                "connection_source": md.get("connection_source"),
                "connection_via_switch": md.get("connection_via_switch"),
                "connection_via_port": md.get("connection_via_port"),
                "connection_confidence": md.get("connection_confidence"),
                "connector_hostname": pd.get("connector_hostname", ""),
                "last_poll": pd.get("last_poll"),
                # v3.8.37: per badge "down da Xh" della UI quando offline
                "last_seen_at": md.get("last_seen_at"),
                "unreachable_since": pd.get("unreachable_since"),
                "sys_descr": pd.get("sys_descr", ""),
                "cpu_usage": pd.get("cpu_usage"),
                "memory_usage": pd.get("memory_usage"),
                "temperature": pd.get("temperature"),
                "uptime": pd.get("sys_uptime") or pd.get("uptime", ""),
                "ports": pd.get("ports"),
                "monitor_type": md.get("monitor_type") or pd.get("monitor_type", ""),
                "snmp_community": md.get("community") or pd.get("snmp_community") or pd.get("community", ""),
                "snmp_version": md.get("snmp_version") or pd.get("snmp_version", ""),
                "http_port": md.get("http_port"),
                "ping_ms": pd.get("ping_ms"),
                # Web Console (auto-detected dal Connector tray)
                "web_console_url": md.get("web_console_url"),
                "web_console_port": md.get("web_console_port"),
                "web_console_scheme": md.get("web_console_scheme"),
                "web_console_title": md.get("web_console_title"),
                # Device Profile (vendor auto-config)
                "profile_key": profile_key,
                "vendor": vendor,
                "family": family,
                "profile_auto_matched": pd.get("profile_auto_matched", False) if not md.get("profile_key") else False,
                "alerts_silenced": bool(md.get("alerts_silenced", False)),
                "alerts_silenced_reason": md.get("alerts_silenced_reason") or "",
                "is_vital": md.get("is_vital"),  # bool|None (None = non scelto)
                "is_vital_set_at": md.get("is_vital_set_at") or "",
                # Datto RMM match (popolato da _match_with_center)
                "datto_name": md.get("datto_name") or "",
                "datto_match": md.get("datto_match") or "",
                "datto_matched_at": md.get("datto_matched_at") or "",
                # v2026-07-25 Hyper-V power state (host WMI) — badge scheda device
                "hyperv_state": _hv_state or "",
                "hyperv_host": _hv_host or "",
                "hyperv_alert_on_off": bool(md.get("hyperv_alert_on_off")),
                "virtualization": md.get("virtualization") or "",
                "hyperv_vm_name": md.get("hyperv_vm_name") or "",
                "hyperv_host_hint": md.get("hyperv_host_hint") or "",
                "virtualization_auto_matched": bool(md.get("virtualization_auto_matched")),
                # v2026-07-23 FIX: created_at MANCANTE qui faceva fallire la
                # validazione DeviceResponse (campo obbligatorio) → il device
                # cadeva nel fallback `except` che NON copiava is_vital → i
                # dispositivi marcati vitali non comparivano mai nel tab Vitali.
                "created_at": md.get("created_at") or pd.get("created_at") or now_iso,
            })

    # v3.8.36 FIX bug status fasullo: i device source=connector-scanner venivano
    # marcati ONLINE anche con last_seen_at di ore/giorni fa (mancava check
    # freschezza). Definiamo una soglia "scanner stale" oltre la quale il device
    # passa a offline. Ratio: lo Scanner gira ~5min, quindi 30min = 6 cicli falliti
    # → realmente offline. La soglia "live" del blocco scanner_seen_recent_ips
    # (10min) resta separata perché serve a "forzare online" un device che il
    # Master non vede ma lo Scanner sì (override anti-flap di v3.8.22).
    SCANNER_STALE_SECONDS = 1800  # 30 minuti — un device non visto da >30min e' offline
    now_dt = datetime.now(timezone.utc)
    def _scanner_status_from_last_seen(last_seen_iso):
        """Ritorna 'online' / 'offline' / 'pending' per device scanner-source
        in base alla freschezza di last_seen_at."""
        if not last_seen_iso:
            return "pending"
        try:
            ls = datetime.fromisoformat(last_seen_iso.replace("Z", "+00:00"))
            age_s = (now_dt - ls).total_seconds()
        except Exception:
            return "pending"
        if age_s < SCANNER_STALE_SECONDS:
            return "online"
        return "offline"

    # 3rd pass: managed_devices orfani (aggiunti manualmente via UI, dal tray
    # Apri Web UI, oppure auto-censiti dal Connector Scanner via /lan-scan
    # con source="connector-scanner") - altrimenti sparirebbero
    # dalla UI del cliente finche' il connector non li vede.
    for md in managed_devices_raw:
        md_ip = md.get("ip") or md.get("ip_address", "")
        if not md_ip or md_ip in manual_ips:
            continue
        manual_ips.add(md_ip)
        # v2026-08 DEDUP-READ-MERGE: usa il doc FUSO (canonico + legacy) invece
        # del doc grezzo, cosi' impostazioni/categoria salvate su un doc
        # duplicato diverso non vengono perse (fix "salvo ma non mantiene").
        md = managed_by_ip.get(md_ip, md)
        # v3.8.15: preserva il source originale (connector-scanner / connector-master / manual)
        # cosi' la colonna FONTE in UI distingue MASTER vs SCANNER vs MANUALE.
        md_source = md.get("source") or "managed"
        # Status:
        # 1. Se lo Scanner lo ha visto negli ultimi 10min via discovered_endpoints
        #    → online (override anti-flap)
        # 2. Se source=connector-scanner → calcolo freschezza (online se <30min, offline se piu' vecchio)
        # 3. Altrimenti pending (manuale mai polleato)
        # v4.2.0 AGENT GO LIVE POLLING: prima di tutto, se l'agent v4 ha
        # scritto un device_poll_status fresco (<3 min) per questo IP,
        # quello è la verità più recente. Sostituisce il vecchio
        # Connector Master per device approvati via Auto-Discovery.
        pd_v4 = poll_by_ip.get(md_ip)
        v4_age = None
        if pd_v4 and pd_v4.get("source") == "agent_v4":
            last_seen_str = pd_v4.get("last_ping_at") or pd_v4.get("last_poll_at")
            if last_seen_str:
                try:
                    lp_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                    v4_age = (now_dt - lp_dt).total_seconds()
                except Exception:
                    v4_age = None
        # v4.16.x EVIDENCE-BASED LIVENESS
        md_mac_x = ((md.get("mac") or "")).lower().replace("-", ":")
        ip_ev3 = scanner_seen_recent_ips.get(md_ip)
        mac_ev3 = scanner_seen_recent_macs.get(md_mac_x) if md_mac_x else None
        live_evidence3 = ip_ev3 or mac_ev3
        if v4_age is not None and v4_age < 180:
            reachable_v4 = bool(pd_v4.get("ping_reachable") or pd_v4.get("reachable"))
            md_status = "online" if reachable_v4 else "offline"
            if reachable_v4 and not live_evidence3:
                live_evidence3 = (pd_v4.get("method") or pd_v4.get("ping_method") or "ping").strip()
            # v2026-06-03 fix bug "pallino verde per device offline da settimane":
            # NON promuovere offline → online via L2 evidence quando il poll v4
            # fresco dice reachable=false. La cache ARP del router/switch puo'
            # mantenere la entry per ore/giorni anche dopo lo spegnimento del
            # device, e prima questo "magic upgrade" rendeva la card OFFLINE
            # (ping reale) ma la lista mostrava pallino verde (ARP cache).
            # Eccezione legittima: il device blocca ICMP ma risponde a SNMP →
            # se sys_name e' presente nel poll fresco, lo consideriamo online.
            if md_status == "offline":
                snmp_alive_recent = bool(
                    pd_v4.get("sys_name")
                    and pd_v4.get("last_poll_at")
                    and v4_age is not None and v4_age < 180
                )
                # v2026-06-23 fix bug "alive 1ms in scanner ma OFFLINE nella
                # scheda": il poll ICMP del Connector puo' fallire su Windows
                # Server con firewall ICMP rate-limited, MA lo scanner LAN
                # broadcast (ARP + mini-ping in burst) vede il device come
                # vivo. Se discovered_endpoints ha evidence fresca (<15min) di
                # tipo ARP/mac_table/scanner_lan promuoviamo a online. Senza
                # questo i 192.168.16.20 (SRVPALMOGAL) finivano "OFFLINE HARD
                # confermato" pur essendo `alive 1ms` nella tab scanner.
                arp_alive_recent = live_evidence3 in (
                    "agent_v4_arp", "mac_table_switch", "scanner_lan"
                )
                if snmp_alive_recent or arp_alive_recent:
                    md_status = "online"
                    if not live_evidence3 and snmp_alive_recent:
                        live_evidence3 = "snmp_sysname"
        elif live_evidence3:
            # v2026-06-03 fix bug "pallino verde": senza poll v4 recente,
            # la sola L2 evidence (ARP cache stale) non basta per dire
            # online. Tuttavia se l'evidenza arriva dalla mac_table del
            # switch (che si pulisce molto piu' rapidamente di ARP/scanner)
            # E' un indicatore affidabile.
            if live_evidence3 == "mac_table_switch":
                md_status = "online"
            else:
                md_status = "pending"
        elif md_source == "connector-scanner":
            md_status = _scanner_status_from_last_seen(md.get("last_seen_at"))
        else:
            md_status = "pending"
        # v2026-07-24: Datto agent online (heartbeat fresco) come evidenza
        # positiva → elimina il falso-rosso sui server Windows/Hyper-V che
        # bloccano ICMP e non compaiono in ARP/FDB/SNMP.
        if md_status in ("offline", "pending") and _datto_online(md, md_ip):
            md_status = "online"
            live_evidence3 = "datto"
        # v2026-07-25: Hyper-V host = fonte autorevole di accensione VM.
        hv_state, hv_host = _hyperv_state(md)
        if md_status in ("offline", "pending") and hv_state == "Running":
            md_status = "online"
            live_evidence3 = "hyperv"
        elif md_status in ("offline", "pending") and hv_state in _HV_OFF:
            md_status = "off"
            live_evidence3 = "hyperv_off"
        # display name: priorità centralizzata su best_display_name():
        # sys_name (SNMP) → hostname (NBNS) → mdns_name → name → fingerbank.
        # Questo evita la UI con righe "10.10.1.55  10.10.1.55  snmp:public"
        # quando i metadati di enrichment esistono ma il name non è stato
        # aggiornato dall'import iniziale, e impedisce che la categoria
        # Fingerbank (es. "Switch and Wireless Controller/HP Switches")
        # mascheri il sysName reale ("Switch02 HP 5130 52G").
        raw_name = best_display_name(md, pd_v4, md_ip)
        # Device type centralizzato anche nel branch managed-only.
        # Prima qui ritornava "server" hard-coded come default → stampanti
        # senza device_type DB apparivano nella card "Server" invece che
        # in "Stampanti".
        raw_dev_type = best_device_type(md, pd_v4)
        devices.append({
            "id": md.get("id") or f"md_{md_ip.replace('.','_')}",
            "client_id": md.get("client_id", ""),
            "name": raw_name,
            "device_type": raw_dev_type,
            "ip_address": md_ip,
            "mac": md.get("mac", ""),
            "hostname": md.get("hostname", ""),
            "location": md.get("location", ""),
            "status": md_status,
            "live_evidence": live_evidence3,
            "seen_by": seen_by_ip.get(md_ip, []),
            "redfish_enabled": False,
            "source": md_source,
            "auto_added": bool(md.get("auto_added", False)),
            "discovered_via": md.get("discovered_via"),
            "discovered_subnet": md.get("discovered_subnet"),
            "vlan_id": md.get("vlan_id"),
            "last_poll": md.get("last_seen_at") or md.get("web_console_last_tested"),
            "last_seen_at": md.get("last_seen_at"),
            "web_console_last_tested": md.get("web_console_last_tested"),
            "monitor_type": md.get("monitor_type", ""),
            "snmp_community": md.get("community") or md.get("snmp_community", ""),
            "snmp_version": md.get("snmp_version", ""),
            "http_port": md.get("http_port"),
            "web_console_url": md.get("web_console_url"),
            "web_console_port": md.get("web_console_port"),
            "web_console_scheme": md.get("web_console_scheme"),
            "web_console_title": md.get("web_console_title"),
            "profile_key": md.get("profile_key"),
            "vendor": md.get("vendor"),
            "family": md.get("family"),
            "fingerbank_device_name": md.get("fingerbank_device_name"),
            "fingerbank_score": md.get("fingerbank_score"),
            "mdns_name": md.get("mdns_name"),
            "mdns_services": md.get("mdns_services") or [],
            "http_server": md.get("http_server"),
            "notes": md.get("notes"),
            "mac_is_random": bool(md.get("mac_is_random", False)),
            "connection_type": md.get("connection_type"),  # lan|wifi|unknown
            "connection_source": md.get("connection_source"),
            "connection_via_switch": md.get("connection_via_switch"),
            "connection_via_port": md.get("connection_via_port"),
            "connection_confidence": md.get("connection_confidence"),
            "alerts_silenced": bool(md.get("alerts_silenced", False)),
            "alerts_silenced_reason": md.get("alerts_silenced_reason") or "",
            "is_vital": md.get("is_vital"),
            "is_vital_set_at": md.get("is_vital_set_at") or "",
            # Datto RMM match (popolato da _match_with_center quando il device
            # e' presente anche nell'inventario Datto del cliente). Permette alla
            # UI di mostrare il nome ufficiale RMM accanto al device.
            "datto_name": md.get("datto_name") or "",
            "datto_match": md.get("datto_match") or "",  # "mac" | "ip" | ""
            "datto_matched_at": md.get("datto_matched_at") or "",
            # v2026-07-25 Hyper-V power state (host WMI) — badge scheda device
            "hyperv_state": hv_state or "",
            "hyperv_host": hv_host or "",
            "hyperv_alert_on_off": bool(md.get("hyperv_alert_on_off")),
            "virtualization": md.get("virtualization") or "",
            "hyperv_vm_name": md.get("hyperv_vm_name") or "",
            "hyperv_host_hint": md.get("hyperv_host_hint") or "",
            "virtualization_auto_matched": bool(md.get("virtualization_auto_matched")),
            "created_at": md.get("created_at") or md.get("auto_added_at") or now_iso,
        })

    client_ids = list(set(d["client_id"] for d in devices if d.get("client_id")))
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    client_map = {c["id"]: c["name"] for c in clients}
    device_ids = [d["id"] for d in devices if not d["id"].startswith("poll_")]
    creds = await db.device_credentials.find({"device_id": {"$in": device_ids}}, {"_id": 0, "device_id": 1}).to_list(1000)
    cred_device_ids = {c["device_id"] for c in creds}

    # === LIVENESS OVERRIDE — SINGLE SOURCE OF TRUTH (fix discrepanza pagine) ===
    # Applichiamo la stessa logica di overview.py PRIMA di serializzare, sui DICT.
    # BUG STORICO RICORRENTE (Gualdi): l'override girava DOPO, sugli oggetti Pydantic
    # DeviceResponse, usando API da dict (r.get / r["status"]=) dentro un
    # try/except: pass -> AttributeError inghiottito -> override MAI applicato ->
    # /api/devices mostrava device ONLINE durante il blackout mentre
    # /api/overview/clients li mostrava offline/stale => discrepanza tra
    # ClientOverviewPage e ClientsPage segnalata dall'utente.
    # Regola: se l'agent del cliente e' OFFLINE la liveness ARP/scan/poll e' stantia:
    #   - blackout confermato (agent giu' + WAN giu' dalla sonda Center) -> "offline" (site_blackout)
    #   - solo agent giu' (WAN ancora su) -> "stale" (agent_offline)
    #   - eccezione: device confermato ONLINE indipendentemente da Datto RMM -> resta online
    try:
        from liveness_resolver import (
            build_clients_without_online_agent, build_blackout_clients,
        )
        offline_clients = await build_clients_without_online_agent(db)
        blackout_clients = await build_blackout_clients(db, offline_clients) if offline_clients else set()
    except Exception as _lv_err:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger(__name__).warning("get_devices: liveness override non disponibile: %s", _lv_err)
        offline_clients, blackout_clients = set(), set()

    if offline_clients:
        for d in devices:
            cid = d.get("client_id")
            # Estendiamo il gating anche a 'pending'/'unknown' (device scanner-source o
            # mai polleati): durante un blackout devono degradare come fa compute_status
            # in overview.py, altrimenti restano grigi in /api/devices -> discrepanza pagine.
            if not cid or cid not in offline_clients or d.get("status") not in ("online", "pending", "unknown"):
                continue
            ipv = d.get("ip_address") or d.get("ip")
            if ipv and datto_online_by_ip.get((cid, ipv)):
                continue  # ONLINE confermato dall'agent Datto sul device stesso
            if cid in blackout_clients:
                d["status"] = "offline"
                d["status_reason"] = "site_blackout"
            else:
                d["status"] = "stale"
                d["status_reason"] = "agent_offline"

    result = []
    for d in devices:
        d["client_name"] = client_map.get(d["client_id"], "")
        d["has_credentials"] = d["id"] in cred_device_ids
        try:
            result.append(DeviceResponse(**d))
        except Exception as _dr_err:
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "get_devices: DeviceResponse validation fallita per ip=%s id=%s: %s",
                d.get("ip_address"), d.get("id"), str(_dr_err)[:200],
            )
            result.append({
                "id": d["id"], "client_id": d.get("client_id", ""), "client_name": d.get("client_name", ""),
                "name": d.get("name", "?"), "device_type": d.get("device_type", ""), "ip_address": d.get("ip_address", ""),
                "hostname": d.get("hostname", ""), "location": d.get("location", ""), "status": d.get("status", "unknown"),
                "status_reason": d.get("status_reason"),
                "redfish_enabled": d.get("redfish_enabled", False), "has_credentials": d.get("has_credentials", False),
                "source": d.get("source", "manual"), "sys_descr": d.get("sys_descr", ""),
                "cpu_usage": d.get("cpu_usage"), "memory_usage": d.get("memory_usage"),
                "temperature": d.get("temperature"), "uptime": d.get("uptime", ""),
                "connector_hostname": d.get("connector_hostname", ""),
                "monitor_type": d.get("monitor_type", ""), "snmp_community": d.get("snmp_community", ""),
                "snmp_version": d.get("snmp_version", ""), "http_port": d.get("http_port"),
                "ping_ms": d.get("ping_ms"), "last_poll": d.get("last_poll"),
                # Web Console (auto-detected dal Connector tray)
                "web_console_url": d.get("web_console_url"),
                "web_console_port": d.get("web_console_port"),
                "web_console_scheme": d.get("web_console_scheme"),
                "web_console_title": d.get("web_console_title"),
                "profile_key": d.get("profile_key"),
                "vendor": d.get("vendor"),
                "family": d.get("family"),
                "alerts_silenced": d.get("alerts_silenced", False),
                "alerts_silenced_reason": d.get("alerts_silenced_reason", ""),
                # v2026-07-23 FIX: preserva is_vital anche nel path degradato
                # (altrimenti i device marcati vitali sparivano dal tab Vitali).
                "is_vital": d.get("is_vital"),
                "is_vital_set_at": d.get("is_vital_set_at", ""),
            })
    return result


@router.get("/clients/{client_id}/snmp-defaults")
async def client_snmp_defaults(client_id: str, current_user: dict = Depends(get_current_user)):
    """Suggerimento AUTOFILL: community + versione SNMP piu' usate tra i dispositivi
    gia' configurati dello STESSO cliente. Usato dal modal 'Modifica Dispositivo'
    per precompilare i campi senza scrivere a mano. Non decide nulla: e' solo un
    suggerimento (il piu' frequente vince)."""
    from collections import Counter
    comm_counter: Counter = Counter()
    ver_counter: Counter = Counter()
    async for m in db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "snmp_community": 1, "community": 1, "snmp_version": 1, "monitor_type": 1},
    ):
        comm = (m.get("snmp_community") or m.get("community") or "").strip()
        # Ignora il default generico 'public' per non proporlo come se fosse scelto.
        if comm and comm.lower() != "public":
            comm_counter[comm] += 1
        ver = (m.get("snmp_version") or "").strip()
        if ver:
            ver_counter[ver] += 1
    # Anche le community impostate a mano in db.devices contano.
    async for d in db.devices.find(
        {"client_id": client_id}, {"_id": 0, "snmp_community": 1, "community": 1, "snmp_version": 1}
    ):
        comm = (d.get("snmp_community") or d.get("community") or "").strip()
        if comm and comm.lower() != "public":
            comm_counter[comm] += 1
        ver = (d.get("snmp_version") or "").strip()
        if ver:
            ver_counter[ver] += 1
    top_comm = comm_counter.most_common(1)
    top_ver = ver_counter.most_common(1)
    return {
        "client_id": client_id,
        "community": top_comm[0][0] if top_comm else "",
        "community_count": top_comm[0][1] if top_comm else 0,
        "snmp_version": top_ver[0][0] if top_ver else "",
        "snmp_version_count": top_ver[0][1] if top_ver else 0,
        "total_configured": sum(comm_counter.values()),
    }



@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    client = await db.clients.find_one({"id": device["client_id"]}, {"_id": 0})
    device["client_name"] = client["name"] if client else ""
    cred = await db.device_credentials.find_one({"device_id": device_id})
    device["has_credentials"] = cred is not None
    return DeviceResponse(**device)


@router.get("/devices/by-ip/{device_ip}/vendor-details")
async def device_vendor_details(device_ip: str, client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Returns full vendor-specific telemetry (vendor_metrics + profile info) for a device.
    Used by the vendor-specific detail pages in the frontend.

    v2026-06 FIX multi-tenant: client_id (query param) filtra le sorgenti per
    evitare leak cross-tenant su IP privati condivisi tra clienti.
    """
    _ps_q = {"device_ip": device_ip}
    _md_q = {"ip": device_ip}
    if client_id:
        _ps_q["client_id"] = client_id
        _md_q["client_id"] = client_id
    ps = await db.device_poll_status.find_one(_ps_q, {"_id": 0})
    md = await db.managed_devices.find_one(_md_q, {"_id": 0})
    if not ps and not md:
        raise HTTPException(status_code=404, detail="Device non trovato")

    profile_key = (md or {}).get("profile_key") or (ps or {}).get("profile_key")
    profile_data = None
    if profile_key:
        try:
            from device_profiles import get_profile
            profile_data = get_profile(profile_key)
        except Exception:
            profile_data = None

    return {
        "device_ip": device_ip,
        "name": (md or ps or {}).get("name") or (ps or {}).get("device_name") or device_ip,
        "profile_key": profile_key,
        "profile": {
            "vendor": (profile_data or {}).get("vendor"),
            "family": (profile_data or {}).get("family"),
            "label": (profile_data or {}).get("label"),
            "thresholds": (profile_data or {}).get("thresholds"),
        } if profile_data else None,
        "vendor_metrics": (ps or {}).get("vendor_metrics") or {},
        "cpu_usage": (ps or {}).get("cpu_usage"),
        "memory_usage": (ps or {}).get("memory_usage"),
        "temperature": (ps or {}).get("temperature"),
        "hardware": (ps or {}).get("hardware"),
        "last_poll": (ps or {}).get("last_poll"),
        "status": (ps or {}).get("status"),
    }


@router.post("/devices/{device_id}/credentials")
async def set_device_credentials(device_id: str, credentials: DeviceCredentials, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    encrypted_username = security_manager.encrypt_credential(credentials.username)
    encrypted_password = security_manager.encrypt_credential(credentials.password)
    await db.device_credentials.update_one(
        {"device_id": device_id},
        {"$set": {
            "device_id": device_id,
            "username_encrypted": encrypted_username,
            "password_encrypted": encrypted_password,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": current_user["id"]
        }},
        upsert=True
    )
    await audit_logger.log(
        AuditAction.STORE_CREDENTIAL, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential", resource_id=device_id,
        details={"device_name": device["name"]}
    )
    return {"message": "Credentials stored securely"}


@router.delete("/devices/{device_id}/credentials")
async def delete_device_credentials(device_id: str, current_user: dict = Depends(get_current_user)):
    await db.device_credentials.delete_one({"device_id": device_id})
    await audit_logger.log(
        AuditAction.DELETE_CREDENTIAL, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential", resource_id=device_id
    )
    return {"message": "Credentials deleted"}


@router.post("/devices/{device_id}/test-redfish")
async def test_device_redfish(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    cred = await db.device_credentials.find_one({"device_id": device_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=400, detail="No credentials stored")
    try:
        username = security_manager.decrypt_credential(cred["username_encrypted"])
        password = security_manager.decrypt_credential(cred["password_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials")
    result = await redfish_poller.test_connection(device["ip_address"], username, password)
    return result


@router.post("/devices/test-redfish")
async def test_redfish_connection(test: RedfishTestRequest, current_user: dict = Depends(get_current_user)):
    result = await redfish_poller.test_connection(test.ip_address, test.username, test.password)
    return result


@router.get("/clients/{client_id}/agents-coverage")
async def get_agents_coverage(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """v4.17.x: ritorna la coverage subnet di un cliente.

    Per ogni connector v4 LIVE, calcola:
      - subnet /24 dedotta da last_ip
      - quanti managed_devices del cliente cadono in quella subnet
      - quanti device "orfani" (fuori da qualsiasi subnet coperta)

    Usato dalla mini-card "Subnet coperte" nell'header del cliente.
    """
    # Lazy import per evitare circular deps
    from routes.agent_ws import _agent_subnet_from_ip, _ip_in_subnet

    three_min_iso = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    agents = []
    async for a in db.managed_agents.find(
        {"client_id": client_id,
         "$or": [
             {"last_heartbeat_at": {"$gte": three_min_iso}},
             {"last_seen_at": {"$gte": three_min_iso}},
         ]},
        {"_id": 0, "agent_id": 1, "hostname": 1, "role": 1, "last_ip": 1,
         "agent_version": 1},
    ):
        a["subnet"] = _agent_subnet_from_ip(a.get("last_ip"))
        a["device_count"] = 0
        agents.append(a)

    # Conta device per subnet di ogni agent
    all_ips: List[str] = []
    async for d in db.managed_devices.find(
        {"client_id": client_id, "ip": {"$ne": None, "$exists": True},
         "disabled": {"$ne": True}},
        {"_id": 0, "ip": 1},
    ):
        ip = d.get("ip")
        if ip:
            all_ips.append(ip)

    orphan_ips: List[str] = []
    for ip in all_ips:
        matched = False
        for a in agents:
            if a.get("subnet") and _ip_in_subnet(ip, a["subnet"]):
                a["device_count"] += 1
                matched = True
                break
        if not matched:
            orphan_ips.append(ip)

    return {
        "client_id": client_id,
        "total_devices": len(all_ips),
        "agents": agents,
        "orphan_count": len(orphan_ips),
        "orphan_sample": orphan_ips[:10],
    }


@router.get("/clients/{client_id}/devices/diagnose-offline")
async def diagnose_offline_devices(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """v4.15.x: diagnostica per capire perche' i device sono OFFLINE.

    Ritorna:
      - quanti agent v4 live e quale role
      - quanti record device_poll_status raggruppati per source/agent_id
      - se esiste un Connector v3 zombie che spara `device-report` legacy
      - sample dei device con `last_poll_at` piu' vecchio di 1h
    """
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    now = datetime.now(timezone.utc)
    three_min_iso = (now - timedelta(minutes=3)).isoformat()

    # 1. agent v4 live (heartbeat o last_seen entro 3 min)
    live_agents = []
    async for ag in db.managed_agents.find(
        {"client_id": client_id,
         "$or": [
             {"last_heartbeat_at": {"$gte": three_min_iso}},
             {"last_seen_at": {"$gte": three_min_iso}},
         ]},
        {"_id": 0, "agent_id": 1, "hostname": 1, "role": 1, "last_seen_at": 1,
         "last_heartbeat_at": 1, "last_ip": 1, "agent_version": 1},
    ):
        live_agents.append(ag)

    # 2. group device_poll_status by source
    pipeline = [
        {"$match": {"client_id": client_id}},
        {"$group": {
            "_id": {"source": "$source", "agent_id": "$agent_id"},
            "count": {"$sum": 1},
            "reachable_count": {"$sum": {"$cond": [
                {"$or": [{"$eq": ["$reachable", True]},
                         {"$eq": ["$ping_reachable", True]}]},
                1, 0,
            ]}},
            "latest": {"$max": {"$ifNull": ["$last_ping_at", "$last_poll_at"]}},
        }},
        {"$sort": {"count": -1}},
    ]
    poll_breakdown = []
    async for grp in db.device_poll_status.aggregate(pipeline):
        poll_breakdown.append({
            "source": grp["_id"].get("source") or "legacy_v3",
            "agent_id": grp["_id"].get("agent_id") or "(none)",
            "count": grp["count"],
            "reachable_count": grp["reachable_count"],
            "latest_poll": grp.get("latest"),
        })

    # 3. detect v3 zombie
    v3_zombie_warning = None
    v4_master_live = any(a.get("role") == "master" for a in live_agents)
    for b in poll_breakdown:
        if b["source"] == "legacy_v3" and b["count"] > 0:
            # ha senso solo se v4 e' attivo: significa che il v3 sta ancora scrivendo
            if v4_master_live and b.get("latest_poll") and b["latest_poll"] > three_min_iso:
                v3_zombie_warning = {
                    "active": True,
                    "message": (
                        "Rilevato Connector v3 PowerShell ATTIVO che continua a scrivere "
                        "su device_poll_status nonostante esista un agent v4 master LIVE. "
                        "Disinstalla il vecchio Connector v3 dal server cliente per evitare "
                        "conflitti di polling."
                    ),
                    "last_v3_write": b["latest_poll"],
                    "records_written_by_v3": b["count"],
                }
                break

    # 4. sample device con poll stantio
    stale_devices = []
    async for d in db.managed_devices.find(
        {"client_id": client_id, "status": "offline"},
        {"_id": 0, "ip": 1, "name": 1, "last_poll_at": 1, "last_seen_at": 1,
         "consecutive_ping_failures": 1, "source": 1, "last_poll_source": 1},
    ).limit(10):
        stale_devices.append(d)

    return {
        "client_id": client_id,
        "now": now.isoformat(),
        "live_v4_agents": live_agents,
        "poll_status_breakdown": poll_breakdown,
        "v3_zombie": v3_zombie_warning,
        "stale_offline_sample": stale_devices,
        "recommendations": _build_recommendations(live_agents, poll_breakdown, v3_zombie_warning),
    }


def _build_recommendations(live_agents, poll_breakdown, v3_zombie):
    recs = []
    if not live_agents:
        recs.append("NESSUN agent v4 LIVE. Verifica che il connector Go sia avviato sul server cliente.")
    masters = [a for a in live_agents if a.get("role") == "master"]
    if live_agents and not masters:
        recs.append("Ci sono agent LIVE ma NESSUNO ha role=master. Almeno un agent deve essere master per pollare i device.")
    if v3_zombie:
        recs.append(v3_zombie["message"])
    v4_records = sum(b["count"] for b in poll_breakdown if b["source"] == "agent_v4")
    if masters and v4_records == 0:
        recs.append(
            "Master v4 LIVE ma 0 record device_poll_status da agent_v4: il modulo di polling "
            "interno del Go agent potrebbe essere bloccato. Riavvia il servizio Argus sul server."
        )
    return recs


@router.patch("/devices/{device_id}")
async def patch_device(device_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Aggiorna in modo selettivo i campi di un device (es. client_id, name).
    Pensato per cleanup multi-tenant: riassegnazione device a un cliente diverso.
    Whitelist dei campi modificabili - mai concedere update arbitrari da JSON."""
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    allowed = {"client_id", "name", "device_type", "ip_address", "hostname", "location", "status", "redfish_enabled"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail=f"No valid fields. Allowed: {sorted(allowed)}")

    # Se cambia client_id, verifica che il nuovo cliente esista
    if "client_id" in updates:
        target = await db.clients.find_one({"id": updates["client_id"]}, {"_id": 0, "id": 1, "name": 1})
        if not target:
            raise HTTPException(status_code=400, detail=f"Target client_id {updates['client_id']} not found")

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Se l'utente sta cambiando il nome, blocca l'auto-promote dal connector
    # (sys_name SNMP) per evitare che sovrascriva la rinomina manuale.
    if "name" in updates and updates["name"] != device.get("name"):
        updates["name_user_locked"] = True
    await db.devices.update_one({"id": device_id}, {"$set": updates})
    # Cascade su managed_devices: stesso lock + nome aggiornato per coerenza UI
    if "name" in updates:
        try:
            await db.managed_devices.update_one(
                {"ip": device.get("ip_address")},
                {"$set": {
                    "device_name": updates["name"],
                    "name": updates["name"],
                    "name_user_locked": True,
                }},
            )
        except Exception:
            pass
    # Cascade update su collezioni correlate per coerenza multi-tenant
    if "client_id" in updates:
        try:
            await db.device_poll_status.update_many(
                {"device_ip": device.get("ip_address")},
                {"$set": {"client_id": updates["client_id"]}}
            )
            await db.managed_devices.update_many(
                {"ip": device.get("ip_address")},
                {"$set": {"client_id": updates["client_id"]}}
            )
        except Exception:
            pass

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.CREATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_id,
        details={"patched_fields": list(updates.keys())}
    )
    updated = await db.devices.find_one({"id": device_id}, {"_id": 0})
    return updated


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.device_credentials.delete_one({"device_id": device_id})
    await audit_logger.log(
        AuditAction.DELETE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_id
    )
    return {"message": "Device deleted"}


@router.post("/clients/{client_id}/devices/cleanup-stale-poll-status")
async def cleanup_stale_poll_status(
    client_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """v4.15.x: pulisce i record fantasma `device_poll_status` scritti da
    agent che hanno smesso di pollare il device (es. scanner che pingava
    cross-VLAN e ora ha targets=[] dopo il fix multi-connector).

    Strategia: per ogni IP del cliente, mantieni SOLO il record con
    `last_ping_at` piu' recente. Gli altri vengono cancellati.

    Cosi' il dropdown `poll_by_ip` in `get_devices` smette di pescare
    record stantii con `reachable=false` che mascherano lo stato reale.

    Body opzionale: `{"dry_run": true}` per anteprima.

    Restituisce `{candidates: [...], removed: N, dry_run: bool}`.
    """
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = bool((body or {}).get("dry_run", False))

    # Raggruppa record di device_poll_status per (client_id, device_ip)
    pipeline = [
        {"$match": {"client_id": client_id, "device_ip": {"$ne": None}}},
        {"$group": {
            "_id": "$device_ip",
            "count": {"$sum": 1},
            "docs": {"$push": {
                "agent_id": "$agent_id",
                "last_ping_at": "$last_ping_at",
                "last_poll_at": "$last_poll_at",
                "reachable": "$reachable",
                "ping_reachable": "$ping_reachable",
            }},
        }},
        {"$match": {"count": {"$gt": 1}}},  # solo IP con > 1 record
    ]
    candidates = []
    removed = 0
    async for grp in db.device_poll_status.aggregate(pipeline):
        ip = grp["_id"]
        docs = grp["docs"]
        # ordina per timestamp desc
        def _ts(d):
            return d.get("last_ping_at") or d.get("last_poll_at") or ""
        docs_sorted = sorted(docs, key=_ts, reverse=True)
        winner = docs_sorted[0]
        losers = docs_sorted[1:]
        candidates.append({
            "ip": ip,
            "kept_agent_id": winner.get("agent_id"),
            "kept_last": _ts(winner),
            "kept_reachable": bool(winner.get("ping_reachable") or winner.get("reachable")),
            "deleted": [
                {"agent_id": loser.get("agent_id"), "last_ping": _ts(loser),
                 "reachable": bool(loser.get("ping_reachable") or loser.get("reachable"))}
                for loser in losers
            ],
        })
        if not dry_run:
            for loser in losers:
                if loser.get("agent_id"):
                    r = await db.device_poll_status.delete_many({
                        "client_id": client_id,
                        "device_ip": ip,
                        "agent_id": loser["agent_id"],
                    })
                    removed += r.deleted_count

    if not dry_run:
        await audit_logger.log(
            AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
            ip_address=current_user.get("_request_ip"),
            resource_type="client", resource_id=client_id,
            details={"action": "cleanup_stale_poll_status", "removed": removed,
                     "ips_affected": len(candidates)},
        )

    return {
        "client_id": client_id,
        "dry_run": dry_run,
        "ips_with_duplicates": len(candidates),
        "removed": removed,
        "candidates": candidates,
    }


# ============================================================================
# PROFILE RE-MATCH — forza fingerprint vendor su device gia` polled
# ============================================================================
# Caso d'uso: device ingestati prima che SNMP/sys_descr funzionassero; ora i
# metadati sono disponibili ma il matcher automatico non si ri-attiva (prev_status
# non-None). Questi endpoint permettono di ri-agganciare il profilo:
#  - singolo device via id O ip
#  - bulk su tutti i device di un cliente
# NON sovrascrive profili impostati manualmente dall'utente.


async def _rematch_one(client_id: str, device_ip: str) -> dict:
    """Esegue il fingerprint su un device usando sys_object_id/sys_descr correnti.

    Ritorna un dict con l'esito: {matched: bool, profile_key?, vendor?, skipped_reason?}.
    """
    ps = await db.device_poll_status.find_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"_id": 0, "sys_descr": 1, "sys_object_id": 1, "profile_key": 1, "profile_auto_matched": 1},
    ) or {}
    md = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip},
        {"_id": 0, "profile_key": 1, "name": 1},
    ) or {}

    # Skip: profilo manuale (utente ha scelto esplicitamente) → non sovrascrivere
    manual_profile = bool(md.get("profile_key")) and not ps.get("profile_auto_matched", False)
    if manual_profile:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "manual-profile",
            "current_profile_key": md.get("profile_key"),
        }

    sys_object_id = ps.get("sys_object_id")
    sys_descr = ps.get("sys_descr")
    if not sys_object_id and not sys_descr:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "no-identifier",
        }

    from device_profiles import fingerprint as _fp
    matched = _fp(sys_object_id, sys_descr)
    if not matched:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "no-match",
            "sys_object_id": sys_object_id,
        }

    from datetime import datetime, timezone as _tz
    now_iso = datetime.now(_tz.utc).isoformat()
    snmp = matched.get("snmp") or {}
    wc = matched.get("web_console") or {}

    await db.device_poll_status.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"$set": {
            "profile_key": matched["key"],
            "vendor": matched["vendor"],
            "family": matched["family"],
            "profile_auto_matched": True,
            "profile_matched_at": now_iso,
        }},
    )
    # Aggiorna managed_device solo se non ha gia` un profilo manuale
    if md and not md.get("profile_key"):
        await db.managed_devices.update_one(
            {"client_id": client_id, "ip": device_ip},
            {"$set": {
                "profile_key": matched["key"],
                "vendor": matched["vendor"],
                "device_type": matched["family"],
                "snmp_port": snmp.get("port", 161),
                "snmp_version": snmp.get("version"),
                "web_console_port": wc.get("port"),
                "web_console_scheme": wc.get("scheme"),
            }},
        )
    return {
        "device_ip": device_ip, "name": md.get("name"),
        "matched": True,
        "profile_key": matched["key"],
        "vendor": matched["vendor"],
        "family": matched["family"],
    }


@router.post("/clients/{client_id}/rematch-profiles")
async def rematch_profiles_bulk(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il fingerprint dei profili vendor su tutti i device del cliente.

    Utile quando lo SNMP ha iniziato a funzionare dopo l'ingest iniziale e
    i device non hanno piu` ricevuto auto-classificazione. NON sovrascrive
    profili impostati manualmente.

    Ritorna summary: {total, matched, skipped, details[]}.
    """
    # Controllo cliente esistente
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Unione IP da managed_devices + device_poll_status (copre device auto-discovered)
    ips: set[str] = set()
    async for d in db.managed_devices.find({"client_id": client_id}, {"_id": 0, "ip": 1}):
        if d.get("ip"):
            ips.add(d["ip"])
    async for d in db.device_poll_status.find({"client_id": client_id}, {"_id": 0, "device_ip": 1}):
        if d.get("device_ip"):
            ips.add(d["device_ip"])

    # v3.8.18: propagazione community SNMP corretta del cliente.
    # I device auto-censiti dallo Scanner partono con community="public" (default).
    # Calcolo la community piu' usata dai device che il Master polla con SUCCESSO
    # (device_poll_status.reachable=true) e la propago a tutti i managed_devices
    # del cliente che hanno ancora "public" o community vuota.
    from datetime import datetime as _dt2, timezone as _tz2
    now_iso2 = _dt2.now(_tz2.utc).isoformat()
    community_counter: dict[str, int] = {}
    async for pd in db.device_poll_status.find(
        {"client_id": client_id, "reachable": True},
        {"_id": 0, "snmp_community": 1, "community": 1},
    ):
        c = pd.get("snmp_community") or pd.get("community") or ""
        c = c.strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 1
    # Anche le community manuali in db.devices contano (admin le ha settate a mano)
    async for dv in db.devices.find(
        {"client_id": client_id},
        {"_id": 0, "snmp_community": 1},
    ):
        c = (dv.get("snmp_community") or "").strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 2  # peso doppio: scelta umana
    # Anche managed_devices con community gia' valorizzata != public
    async for md in db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "community": 1, "snmp_community": 1},
    ):
        c = (md.get("community") or md.get("snmp_community") or "").strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 1

    community_propagated = 0
    best_community = ""
    if community_counter:
        best_community = max(community_counter, key=community_counter.get)
        # Aggiorna i managed_devices con community=public (o vuota): il Master ritentera'
        # il poll col valore corretto al prossimo ciclo.
        upd = await db.managed_devices.update_many(
            {
                "client_id": client_id,
                "$or": [
                    {"community": {"$in": ["", "public", None]}},
                    {"community": {"$exists": False}},
                ],
            },
            {"$set": {
                "community": best_community,
                "snmp_community": best_community,
                "community_propagated_at": now_iso2,
                "community_propagated_from": "rematch-profiles bulk",
            }},
        )
        community_propagated = upd.modified_count

    details = []
    matched_count = 0
    skipped_count = 0
    for ip in sorted(ips):
        try:
            res = await _rematch_one(client_id, ip)
            details.append(res)
            if res.get("matched"):
                matched_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            details.append({"device_ip": ip, "matched": False, "error": str(e)})
            skipped_count += 1

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "rematch_profiles_bulk", "total": len(ips), "matched": matched_count},
    )

    return {
        "client_id": client_id,
        "client_name": client.get("name"),
        "total": len(ips),
        "matched": matched_count,
        "skipped": skipped_count,
        "community_propagated": community_propagated,
        "community_used": best_community,
        "details": details,
    }


@router.post("/clients/{client_id}/devices/{device_ip}/rematch-profile")
async def rematch_profile_single(
    client_id: str,
    device_ip: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il fingerprint del profilo vendor su un singolo device."""
    res = await _rematch_one(client_id, device_ip)
    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_ip,
        details={"action": "rematch_profile", "result": res},
    )
    return res


@router.get("/clients/{client_id}/devices/recognize-debug")
async def recognize_unknown_devices_debug(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """DIAG endpoint: ritorna i conteggi delle source dei managed_devices del
    cliente, e quanti entrerebbero nel pipeline recognize-unknowns. Utile per
    capire se il filtro source matchi i dati reali. Aggiunto in v4.14.x per
    debuggare il caso "total_scanned: 0" con 40 device esistenti."""
    pipeline = [
        {"$match": {"client_id": client_id}},
        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    sources_count = []
    async for doc in db.managed_devices.aggregate(pipeline):
        sources_count.append({"source": doc["_id"], "count": doc["count"]})
    total = await db.managed_devices.count_documents({"client_id": client_id})
    matching = await db.managed_devices.count_documents({
        "client_id": client_id,
        "$or": [
            {"source": {"$in": [
                "connector-scanner", "connector-master",
                "scanner", "agent_v4", "auto-discovery",
            ]}},
            {"source": None},
            {"source": {"$exists": False}},
        ],
    })
    sample = await db.managed_devices.find_one(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "source": 1, "ip": 1, "ip_address": 1, "mac": 1, "name": 1, "vendor": 1},
    )
    arp_count = await db.discovered_endpoints.count_documents(
        {"client_id": client_id, "mac": {"$ne": None}},
    )
    return {
        "total_managed_devices": total,
        "matching_filter": matching,
        "by_source": sources_count,
        "sample_device": sample,
        "arp_cache_discovered": arp_count,
    }






# Macro → device_type canonico (mirror di frontend/utils/deviceCategory.js)
_MACRO_TO_TYPE = {
    "firewall": "firewall",
    "switch": "switch",
    "router": "router",
    "server": "server",
    "nas": "nas",
    "ups": "ups",
    "ap": "access-point",
    "tvcc": "tvcc",
    "printer": "printer",
    "voip": "voip",
    "workstation": "workstation",
    "mobile": "mobile",
    "iot": "iot",
    "other": "generic",
}


@router.post("/clients/{client_id}/devices/{device_ip}/move-category")
async def move_device_category(
    client_id: str,
    device_ip: str,
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Sposta manualmente un device in una macroarea diversa via drag&drop UI.

    v2026-02-13: richiesto dall'utente per riclassificare i device che
    Argus mette in workstation ma in realta' sono server (es. GALVANSRV
    con vendor HP, che il classifier vede come PC perche' HP fa anche
    workstation HP EliteDesk, ma in realta' e' un ProLiant DL).

    Body:
        {"macro": "<firewall|switch|server|nas|ups|ap|tvcc|printer|voip|"
                  "workstation|mobile|iot|other>"}

    Effetti:
      - managed_devices.device_type = <type canonico>
      - managed_devices.device_type_user_locked = True
        (cosi' best_device_type() rispetta la scelta e non la sovrascrive
         al prossimo classifier run / scanner refresh)
      - audit log con utente, ip, old → new
    """
    macro = (payload.get("macro") or "").strip().lower()
    new_type = _MACRO_TO_TYPE.get(macro)
    if not new_type:
        raise HTTPException(
            status_code=400,
            detail=f"macro non valida. Ammesse: {sorted(_MACRO_TO_TYPE.keys())}",
        )

    md = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip},
        {"_id": 0, "id": 1, "device_type": 1, "name": 1, "client_id": 1},
    )

    # Se il device esiste solo in device_poll_status (auto-scoperto, non
    # ancora promosso a managed_devices), creiamo l'entry "ghost" per
    # poter applicare il lock. Cosi' il classifier non lo riportera' alla
    # categoria automatica al prossimo run dello scanner.
    if not md:
        pd = await db.device_poll_status.find_one(
            {"client_id": client_id, "device_ip": device_ip},
            {"_id": 0, "device_name": 1, "sys_name": 1, "vendor": 1, "model": 1, "sys_descr": 1, "sys_object_id": 1},
        )
        if not pd:
            raise HTTPException(
                status_code=404,
                detail=f"Device {device_ip} non trovato per cliente {client_id} (ne' managed_devices ne' device_poll_status)",
            )
        # Crea record managed_devices con device_type forzato + lock.
        from uuid import uuid4
        await db.managed_devices.insert_one({
            "id": str(uuid4()),
            "client_id": client_id,
            "ip": device_ip,
            "name": pd.get("sys_name") or pd.get("device_name") or device_ip,
            "hostname": pd.get("sys_name") or "",
            "vendor": pd.get("vendor") or "",
            "model": pd.get("model") or "",
            "sys_descr": pd.get("sys_descr") or "",
            "sys_object_id": pd.get("sys_object_id") or "",
            "device_type": new_type,
            "device_type_user_locked": True,
            "device_type_user_locked_by": current_user.get("email"),
            "device_type_user_locked_at": datetime.now(timezone.utc).isoformat(),
            "source": "user_drag_and_drop",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await audit_logger.log(
            AuditAction.UPDATE_DEVICE,
            user_id=current_user["id"], user_email=current_user["email"],
            ip_address=current_user.get("_request_ip"),
            resource_type="device", resource_id=device_ip,
            details={
                "action": "move_category_create",
                "client_id": client_id,
                "new_type": new_type,
                "macro": macro,
            },
        )
        return {
            "ok": True, "ip": device_ip, "old_type": "", "new_type": new_type,
            "macro": macro, "locked": True, "created": True,
            "message": f"Device promosso e classificato come {new_type}",
        }

    old_type = md.get("device_type") or ""
    if old_type == new_type and md.get("device_type_user_locked"):
        return {
            "ok": True,
            "ip": device_ip,
            "old_type": old_type,
            "new_type": new_type,
            "noop": True,
            "message": "Gia' bloccato su questa categoria",
        }

    await db.managed_devices.update_one(
        {"client_id": client_id, "ip": device_ip},
        {"$set": {
            "device_type": new_type,
            "device_type_user_locked": True,
            "device_type_user_locked_by": current_user.get("email"),
            "device_type_user_locked_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_ip,
        details={
            "action": "move_category",
            "client_id": client_id,
            "device_name": md.get("name"),
            "old_type": old_type,
            "new_type": new_type,
            "macro": macro,
        },
    )

    return {
        "ok": True,
        "ip": device_ip,
        "old_type": old_type,
        "new_type": new_type,
        "macro": macro,
        "locked": True,
        "message": f"Categoria aggiornata: {old_type} → {new_type}",
    }

@router.post("/clients/{client_id}/devices/recognize-unknowns")
async def recognize_unknown_devices(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il riconoscimento (OUI + Fingerbank + reverse-DNS) sui device
    auto-censiti dallo Scanner che hanno ancora vendor/nome generici (es. "192.168.x.y"
    senza vendor). Utile dopo che Fingerbank è stato configurato a posteriori, o per
    device il cui MAC è arrivato in un secondo momento.
    """
    summary = await _enrich_devices_for_client(client_id)
    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "recognize_unknowns_manual", "summary": summary},
    )
    return {"client_id": client_id, **summary}


async def _enrich_devices_for_client(client_id: str) -> Dict[str, Any]:
    """Helper riutilizzabile: arricchisce i managed_devices del cliente con
    MAC (da discovered_endpoints ARP-cache), OUI vendor + Fingerbank + reverse
    DNS. Chiamato sia da:
      - POST /recognize-unknowns (trigger manuale dell'admin)
      - _bridge_discovery (auto-trigger quando il connector pusha discovery_batch)
      - POST /api/devices (auto-trigger quando un nuovo device viene aggiunto)
    Ritorna il summary del processo (total_scanned, fingerbank_matched, ...).
    """
    import socket
    from datetime import datetime, timezone
    from routes.oui_lookup import lookup_oui, classify_device
    from services import fingerbank_service

    fb_configured = await fingerbank_service.is_configured()
    now_iso = datetime.now(timezone.utc).isoformat()

    # v3.8.16: detection MAC LAA (randomizzato per privacy).
    def _is_laa_mac(mac_normalized: str) -> bool:
        try:
            first_byte = int(mac_normalized.split(":")[0], 16)
            return bool(first_byte & 0x02)
        except Exception:
            return False

    # Pesca i device da rivedere: qualunque source "scanner-like" (auto-discovery
    # del connector), "master", oppure source NULL/missing (device legacy o
    # importati prima che il campo source fosse introdotto). v4.14.x: il
    # cliente 86BITOffice aveva 35 device con source=null, quindi il filtro
    # $in non li includeva e total_scanned=0. Includiamo $exists:false e null
    # per processare anche quelli.
    candidates = await db.managed_devices.find(
        {
            "client_id": client_id,
            "$or": [
                {"source": {"$in": [
                    "connector-scanner", "connector-master",
                    "scanner", "agent_v4", "auto-discovery",
                ]}},
                {"source": None},
                {"source": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "ip": 1, "ip_address": 1, "mac": 1, "vendor": 1, "name": 1,
         "hostname": 1, "fingerbank_at": 1, "device_type": 1, "sys_descr": 1,
         "mac_is_random": 1,
         # v4.14.x BUG-FIX "profili non si agganciano": proteggi i field gia'
         # configurati manualmente dall'utente (profile_key, name_user_locked,
         # device_type_user_locked). Altrimenti l'enrichment automatico
         # sovrascrive il device_type scelto dall'admin (es. "stampante")
         # con la classificazione OUI (es. "endpoint" o "Apple").
         "profile_key": 1, "name_user_locked": 1, "device_type_user_locked": 1,
         "profile_auto_matched": 1},
    ).to_list(2000)

    # Pre-carica ARP-cache da discovered_endpoints (auto-scan del connector)
    # per arricchire i device managed che non hanno MAC. Indicizzato per IP.
    arp_by_ip: Dict[str, Dict[str, Any]] = {}
    async for ep in db.discovered_endpoints.find(
        {"client_id": client_id, "mac": {"$ne": None}},
        {"_id": 0, "ip": 1, "mac": 1, "vendor": 1, "hostname": 1},
    ):
        ip_key = (ep.get("ip") or "").strip()
        if ip_key:
            arp_by_ip[ip_key] = ep

    summary = {
        "total_scanned": 0,
        "oui_matched": 0,
        "fingerbank_matched": 0,
        "rdns_matched": 0,
        "private_mac_labeled": 0,
        "no_mac": 0,
        "skipped": 0,
    }

    for md in candidates:
        # v4.14.x: i device del Center usano `ip_address` (managed_devices schema),
        # mentre i device da connector-scanner legacy usano `ip`. Supportiamo entrambi.
        ip = md.get("ip") or md.get("ip_address")
        if not ip:
            continue
        # v4.14.x BUG-FIX "profili non si agganciano": se l'admin ha applicato
        # un profilo manuale (POST /api/device-profiles/apply), `profile_key`
        # e' valorizzato e `profile_auto_matched=False` → NON sovrascrivere
        # device_type/vendor/name con l'enrichment automatico.
        has_manual_profile = bool(md.get("profile_key")) and not md.get("profile_auto_matched", False)
        name_locked = bool(md.get("name_user_locked"))
        device_type_locked = bool(md.get("device_type_user_locked")) or has_manual_profile

        # Salta device gia' completi (hanno vendor + name diverso da IP + fingerbank fatto)
        has_vendor = bool((md.get("vendor") or "").strip())
        has_decent_name = bool((md.get("name") or "").strip()) and md.get("name") != ip
        has_fb = bool(md.get("fingerbank_at"))
        if has_vendor and has_decent_name and (has_fb or not fb_configured):
            summary["skipped"] += 1
            continue
        summary["total_scanned"] += 1
        update: dict = {}

        mac_norm = (md.get("mac") or "").lower().replace("-", ":").strip()
        mac_valid = mac_norm and len(mac_norm.replace(":", "")) == 12

        # FALLBACK ARP: se questo managed_device non ha MAC ma il connector
        # scanner ne ha scoperto uno per lo stesso IP, recupero MAC da
        # discovered_endpoints (arp_by_ip). Cosi' Fingerbank/OUI possono
        # funzionare anche su dispositivi inseriti senza MAC.
        if not mac_valid:
            ep = arp_by_ip.get((ip or "").strip())
            if ep and ep.get("mac"):
                mac_norm = ep["mac"].lower().replace("-", ":").strip()
                mac_valid = bool(mac_norm) and len(mac_norm.replace(":", "")) == 12
                if mac_valid:
                    update["mac"] = mac_norm
                    if not (md.get("hostname") or "").strip() and ep.get("hostname"):
                        update["hostname"] = ep["hostname"]

        mac_is_laa = mac_valid and _is_laa_mac(mac_norm)

        if mac_valid:
            if mac_is_laa:
                # MAC randomizzato → etichetta chiara, non chiamare OUI/Fingerbank
                update["mac_is_random"] = True
                if not has_vendor and not has_manual_profile:
                    update["vendor"] = "MAC randomizzato (privacy)"
                if not has_decent_name and not name_locked:
                    update["name"] = f"Dispositivo personale {ip}"
                if not device_type_locked:
                    update["device_type"] = "endpoint-private"
                summary["private_mac_labeled"] += 1
            else:
                # OUI lookup classico
                if not has_vendor and not has_manual_profile:
                    try:
                        v = lookup_oui(mac_norm) or ""
                        if v:
                            update["vendor"] = v
                            summary["oui_matched"] += 1
                            if not device_type_locked:
                                try:
                                    update["device_type"] = classify_device(
                                        mac=mac_norm, vendor=v, sys_descr=md.get("sys_descr") or ""
                                    ) or md.get("device_type") or "endpoint"
                                except Exception:
                                    pass
                    except Exception:
                        pass
                # Fingerbank lookup (solo MAC reali) — fingerbank_device_name e' un
                # field separato, non sovrascrive il name dell'admin: safe da chiamare.
                if fb_configured and not has_fb:
                    try:
                        fb = await fingerbank_service.interrogate(mac=mac_norm)
                        if fb and fb.get("device_name"):
                            update["fingerbank_device_name"] = fb["device_name"]
                            update["fingerbank_score"] = fb.get("score")
                            update["fingerbank_at"] = now_iso
                            summary["fingerbank_matched"] += 1
                    except Exception:
                        pass
        else:
            summary["no_mac"] += 1

        # Reverse DNS lookup (sempre tentato per device senza nome decente, anche LAA)
        if not has_decent_name and "name" not in update and not name_locked:
            try:
                old_to = socket.getdefaulttimeout()
                socket.setdefaulttimeout(2.0)
                try:
                    h, _, _ = socket.gethostbyaddr(ip)
                    if h and h != ip:
                        update["hostname"] = h
                        update["name"] = h.split(".")[0] if "." in h else h
                        summary["rdns_matched"] += 1
                finally:
                    socket.setdefaulttimeout(old_to)
            except Exception:
                pass

        # Se abbiamo trovato vendor ma name e' ancora ip, miglioriamo il name
        if "vendor" in update and not has_decent_name and "name" not in update and not name_locked:
            update["name"] = f"{update['vendor']} {ip}"

        if update:
            update["updated_at"] = now_iso
            # v4.14.x: usa id per il match (univoco) invece di filtro su source
            # che pre-fix era hardcoded a "connector-scanner" e mai matchava i
            # device con source=null/connector-master (35 device del cliente
            # 86BITOffice rimanevano senza enrichment Fingerbank).
            await db.managed_devices.update_one(
                {"client_id": client_id, "id": md.get("id")},
                {"$set": update},
            )

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id="system", user_email="system@argus",
        ip_address=None,
        resource_type="client", resource_id=client_id,
        details={"action": "recognize_unknowns_auto", "summary": summary},
    )
    return {"fingerbank_configured": fb_configured, **summary}


# v3.8.17: keyword-set per riconoscere se un LLDP neighbor remote_sys_name/desc
# rappresenta un Access Point WiFi vs uno switch/router cablato.
_AP_KEYWORDS = (
    "ap-", "ap_", " ap ", "wap", "wifi", "wi-fi", "wireless", "wlan",
    "aruba ap", "unifi ap", "uap", "meraki mr", "cisco air", "ruckus",
    "aerohive", "extreme ap", "mikrotik cap", "tp-link eap", "netgear wac",
    "engenius", "edgemax ap",
)


def _is_ap_neighbor(remote_sys_name: str, remote_sys_descr: str = "") -> bool:
    """Ritorna True se il neighbor LLDP/CDP è probabilmente un Access Point WiFi."""
    blob = f"{remote_sys_name or ''} {remote_sys_descr or ''}".lower()
    return any(k in blob for k in _AP_KEYWORDS)


@router.post("/clients/{client_id}/devices/correlate-connectivity")
async def correlate_connectivity(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Correla i device del cliente con la CAM table degli switch e i neighbor
    LLDP per stabilire se ogni device e' connesso via LAN (cavo) o Wi-Fi.

    Workflow:
    1. Per ogni managed_device con MAC valido del cliente.
    2. Cerca in `discovered_endpoints` (popolata dal Master via dot1dTpFdbTable)
       quale switch+port vede quel MAC.
    3. Risali in `switch_ports` per ottenere il nome porta (Gi1/0/5).
    4. Risali in `lldp_neighbors` per vedere se quella porta ha come neighbor
       un Access Point WiFi (matching keyword Aruba AP/Unifi/Meraki/AP-/WAP/...).
    5. Se neighbor=AP -> connection_type=wifi, altrimenti=lan.
    6. Fallback: se MAC non trovato in CAM E mac_is_random=True -> wifi (LAA).
    7. Altrimenti unknown.

    Salva su managed_devices: connection_type, connection_source,
    connection_via_switch, connection_via_port, connection_confidence.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    devices = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "ip": 1, "mac": 1, "mac_is_random": 1,
         "source": 1, "connection_type": 1, "device_type": 1, "vendor": 1},
    ).to_list(2000)

    # Index discovered_endpoints by MAC (uppercase as inserted by Master)
    cam_entries = await db.discovered_endpoints.find(
        {"client_id": client_id, "mac": {"$ne": ""}, "switch_ip": {"$ne": ""}},
        {"_id": 0, "mac": 1, "switch_ip": 1, "port": 1},
    ).to_list(20000)
    cam_by_mac: dict = {}
    for e in cam_entries:
        m = (e.get("mac") or "").upper().replace("-", ":")
        if m and len(m.replace(":", "")) == 12 and e.get("switch_ip"):
            cam_by_mac[m] = (e["switch_ip"], e.get("port", 0))

    # Index switch_ports for (switch_ip, idx) -> port_name
    sp_docs = await db.switch_ports.find(
        {"client_id": client_id},
        {"_id": 0, "local_ip": 1, "idx": 1, "name": 1},
    ).to_list(10000)
    port_name_by_key: dict = {}
    for sp in sp_docs:
        if sp.get("local_ip") and sp.get("idx") is not None:
            port_name_by_key[(sp["local_ip"], int(sp["idx"]))] = sp.get("name", "")

    # Index lldp_neighbors by (switch_ip, port_id_or_desc)
    lldp_docs = await db.lldp_neighbors.find(
        {"client_id": client_id},
        {"_id": 0, "local_ip": 1, "local_port_id": 1, "local_port_desc": 1,
         "remote_sys_name": 1, "remote_sys_descr": 1, "remote_chassis_id": 1},
    ).to_list(5000)
    lldp_by_port: dict = {}
    # Set di MAC che sono "device LLDP" stesso (AP/switch/IP-Phone neighbor)
    # → quei MAC sono dispositivi CABLATI (l'AP usa l'ethernet uplink, non e' un client WiFi).
    lldp_chassis_macs: set = set()

    def _normalize_chassis_to_mac(chassis: str) -> str:
        if not chassis:
            return ""
        # Cisco format: aabb.ccdd.eeff -> aabbccddeeff -> aa:bb:cc:dd:ee:ff
        cleaned = "".join(c for c in chassis.lower() if c in "0123456789abcdef")
        if len(cleaned) == 12:
            return ":".join(cleaned[i:i+2] for i in range(0, 12, 2)).upper()
        return ""

    for ln in lldp_docs:
        for pkey in (ln.get("local_port_id"), ln.get("local_port_desc")):
            if ln.get("local_ip") and pkey:
                lldp_by_port[(ln["local_ip"], str(pkey))] = ln
        chassis_mac = _normalize_chassis_to_mac(ln.get("remote_chassis_id", ""))
        if chassis_mac:
            lldp_chassis_macs.add(chassis_mac)

    summary = {
        "total_devices": len(devices),
        "lan_count": 0,
        "wifi_count": 0,
        "unknown_count": 0,
        "skipped_no_mac": 0,
        "via_lldp_ap": 0,
        "via_cam_lan": 0,
        "via_laa_inference": 0,
    }

    for d in devices:
        mac_norm = (d.get("mac") or "").upper().replace("-", ":").strip()
        if not mac_norm or len(mac_norm.replace(":", "")) != 12:
            summary["skipped_no_mac"] += 1
            # se non abbiamo MAC ma source e' connector-scanner, segna unknown
            await db.managed_devices.update_one(
                {"client_id": client_id, "id": d["id"]},
                {"$set": {
                    "connection_type": "unknown",
                    "connection_source": "no_mac",
                    "connection_correlated_at": now_iso,
                }},
            )
            continue

        ctype = "unknown"
        csource = "no_data"
        via_switch = ""
        via_port = ""
        confidence = 0  # 0-100

        cam_hit = cam_by_mac.get(mac_norm)
        if cam_hit:
            sw_ip, port_idx = cam_hit
            port_name = port_name_by_key.get((sw_ip, port_idx), str(port_idx))
            ln = lldp_by_port.get((sw_ip, port_name)) or lldp_by_port.get((sw_ip, str(port_idx)))
            via_switch = sw_ip
            via_port = port_name or str(port_idx)
            # v3.8.17: se il device E' lui stesso un LLDP neighbor (AP/IP-Phone/switch),
            # allora e' CABLATO per definizione (LLDP gira solo su Ethernet).
            if mac_norm in lldp_chassis_macs:
                ctype = "lan"
                csource = "self_is_lldp_device"
                confidence = 99
                summary["via_cam_lan"] += 1
            elif ln and _is_ap_neighbor(ln.get("remote_sys_name", ""), ln.get("remote_sys_descr", "")):
                ctype = "wifi"
                csource = f"lldp:ap={ln.get('remote_sys_name','?')}"
                confidence = 95
                summary["via_lldp_ap"] += 1
            else:
                ctype = "lan"
                csource = "cam_table"
                confidence = 90
                summary["via_cam_lan"] += 1
        else:
            # MAC non in CAM table del Master
            if d.get("mac_is_random"):
                ctype = "wifi"
                csource = "laa_inference"  # MAC randomizzato e' tipicamente Wi-Fi privacy
                confidence = 75
                summary["via_laa_inference"] += 1
            else:
                # v3.8.23 EURISTICA DEVICE_TYPE: il Master non polla la CAM table degli
                # switch in altre VLAN (es. 192.168.16.x dello Scanner Galvani), quindi
                # cam_hit=None per quei device. Diamo una stima sensata basata sul
                # device_type: server/switch/firewall/ups/nas/printer sono SEMPRE cablati
                # in ambiente enterprise (LAN). Phone/tablet/laptop sono tipicamente WiFi.
                dtype = (d.get("device_type") or "").lower()
                vendor = (d.get("vendor") or "").lower()
                LAN_TYPICAL = {
                    "server", "switch", "firewall", "router", "ups", "nas",
                    "storage", "printer", "voip-phone", "ipphone", "ipcamera",
                    "camera", "nvr", "dvr", "videosurveillance", "appliance",
                }
                WIFI_TYPICAL = {"phone", "tablet", "smartphone", "iphone", "ipad", "android"}
                if dtype in LAN_TYPICAL or any(k in vendor for k in ["hp", "hewlett", "cisco", "aruba", "fortinet", "zyxel", "tp-link"]):
                    ctype = "lan"
                    csource = "device_type_inference"
                    confidence = 65
                    summary.setdefault("via_devtype_lan", 0)
                    summary["via_devtype_lan"] += 1
                elif dtype in WIFI_TYPICAL:
                    ctype = "wifi"
                    csource = "device_type_inference"
                    confidence = 55
                    summary.setdefault("via_devtype_wifi", 0)
                    summary["via_devtype_wifi"] += 1
                else:
                    ctype = "unknown"
                    csource = "no_cam_match"
                    confidence = 0

        summary[f"{ctype}_count"] += 1

        await db.managed_devices.update_one(
            {"client_id": client_id, "id": d["id"]},
            {"$set": {
                "connection_type": ctype,
                "connection_source": csource,
                "connection_via_switch": via_switch,
                "connection_via_port": via_port,
                "connection_confidence": confidence,
                "connection_correlated_at": now_iso,
            }},
        )

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "correlate_connectivity", "summary": summary},
    )
    return {"client_id": client_id, **summary}


@router.post("/clients/{client_id}/ilo-link")
async def link_ilo_to_host(client_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Associa una credenziale iLO (ilo_ip) al server host (host_ip): stesso
    server fisico con IP management iLO diverso dall'IP del SO. Dopo il link i
    dati Redfish dell'iLO vengono mostrati sotto il server host nella tab Server.
    payload: {"ilo_ip": "10.10.10.203", "host_ip": "10.10.10.200"}.
    host_ip vuoto/None → rimuove l'associazione.
    """
    ilo_ip = (payload or {}).get("ilo_ip")
    host_ip = (payload or {}).get("host_ip") or None
    if not ilo_ip:
        raise HTTPException(status_code=400, detail="ilo_ip mancante")
    res = await db.device_credentials.update_one(
        {"client_id": client_id, "credential_type": "ilo", "device_ip": ilo_ip},
        {"$set": {"host_ip": host_ip}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Credenziale iLO {ilo_ip} non trovata per il cliente")
    return {"ok": True, "ilo_ip": ilo_ip, "host_ip": host_ip,
            "message": f"iLO {ilo_ip} associata al server {host_ip}" if host_ip else f"Associazione iLO {ilo_ip} rimossa"}


def _norm_serial(s: Optional[str]) -> str:
    """Normalizza un serial number per il match (solo alfanumerici maiuscoli)."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _norm_host(s: Optional[str]) -> str:
    """Normalizza un hostname per il match: minuscolo, senza dominio, trim."""
    v = (s or "").strip().lower()
    return v.split(".")[0] if v else ""


# Serial/hostname troppo generici da NON usare per il match (falsi positivi Datto/DMI)
_BAD_SERIALS = {"", "NONE", "NULL", "SYSTEMSERIALNUMBER", "TOBEFILLEDBYOEM",
                "DEFAULTSTRING", "NOTSPECIFIED", "NOTAPPLICABLE", "0", "NA", "N"}


@router.post("/clients/{client_id}/ilo-autolink")
async def autolink_ilo_hosts(client_id: str, dry_run: bool = False,
                             current_user: dict = Depends(get_current_user)):
    """Collega AUTOMATICAMENTE ogni iLO al suo server host, confrontando il
    serial number del chassis (Redfish `SerialNumber`) — e in fallback l'hostname
    del SO (Redfish `HostName`) — con gli identificatori dei `managed_devices`
    (serial da Datto RMM / nome host). Elimina il collegamento manuale iLO↔host.

    `dry_run=true` → ritorna solo le corrispondenze proposte senza applicarle.
    """
    # 1) iLO con dati Redfish (serial/host_name)
    ilo_docs = await db.device_poll_status.find(
        {"client_id": client_id, "$or": [
            {"device_class": "hpe-ilo"},
            {"monitor_type": "redfish_direct"},
            {"redfish.serial_number": {"$nin": [None, ""]}},
        ]},
        {"_id": 0, "device_ip": 1, "device_name": 1, "redfish": 1},
    ).to_list(300)

    # 2) Credenziali iLO (il link vive qui: campo host_ip)
    ilo_creds = await db.device_credentials.find(
        {"client_id": client_id, "credential_type": "ilo"},
        {"_id": 0, "device_ip": 1, "host_ip": 1},
    ).to_list(500)
    cred_by_ip = {c["device_ip"]: c for c in ilo_creds if c.get("device_ip")}

    # 3) Candidati host (managed_devices non-VM) + 4) serial Datto per uid
    managed = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "ip": 1, "name": 1, "device_type": 1, "virtualization": 1,
         "datto_uid": 1, "serial": 1, "hostname": 1, "datto_name": 1},
    ).to_list(3000)
    datto = await db.datto_devices.find(
        {"client_id": client_id},
        {"_id": 0, "uid": 1, "serial": 1, "name": 1, "hostname_short": 1, "fqdn": 1},
    ).to_list(5000)
    datto_by_uid = {d["uid"]: d for d in datto if d.get("uid")}

    _VM = {"hyperv", "vmware", "vm_generic"}
    hosts = []
    for m in managed:
        ip = m.get("ip")
        if not ip or (m.get("virtualization") or "") in _VM:
            continue
        serial = m.get("serial")
        hn = m.get("hostname") or m.get("name") or m.get("datto_name")
        du = m.get("datto_uid")
        if du and du in datto_by_uid:
            dd = datto_by_uid[du]
            serial = serial or dd.get("serial")
            hn = hn or dd.get("name") or dd.get("hostname_short")
        sn = _norm_serial(serial)
        if sn in _BAD_SERIALS:
            sn = ""
        hosts.append({
            "ip": ip, "name": m.get("name") or ip,
            "device_type": (m.get("device_type") or "").lower(),
            "serial_n": sn, "host_n": _norm_host(hn),
        })

    linked, suggestions, skipped = [], [], []
    for d in ilo_docs:
        ilo_ip = d.get("device_ip")
        if not ilo_ip:
            continue
        rf = d.get("redfish") or {}
        ilo_serial_n = _norm_serial(rf.get("serial_number"))
        if ilo_serial_n in _BAD_SERIALS:
            ilo_serial_n = ""
        ilo_host_n = _norm_host(rf.get("host_name"))

        match, match_by = None, None
        if ilo_serial_n:
            c = [h for h in hosts if h["serial_n"] and h["serial_n"] == ilo_serial_n and h["ip"] != ilo_ip]
            if c:
                match, match_by = c[0], "serial"
        if not match and ilo_host_n:
            c = [h for h in hosts if h["host_n"] and h["host_n"] == ilo_host_n and h["ip"] != ilo_ip]
            if c:
                match, match_by = c[0], "hostname"
        if not match:
            continue

        cred = cred_by_ip.get(ilo_ip)
        entry = {
            "ilo_ip": ilo_ip, "ilo_name": d.get("device_name") or ilo_ip,
            "host_ip": match["ip"], "host_name": match["name"],
            "match_by": match_by, "ilo_serial": rf.get("serial_number"),
            "ilo_host_name": rf.get("host_name"),
        }
        if (cred or {}).get("host_ip") == match["ip"]:
            entry["status"] = "already_linked"
            skipped.append(entry)
            continue
        if not cred:
            entry["status"] = "no_credential"  # iLO senza credenziale → link non memorizzabile
            skipped.append(entry)
            continue
        if dry_run:
            entry["status"] = "suggested"
            suggestions.append(entry)
        else:
            await db.device_credentials.update_one(
                {"client_id": client_id, "credential_type": "ilo", "device_ip": ilo_ip},
                {"$set": {"host_ip": match["ip"]}},
            )
            entry["status"] = "linked"
            linked.append(entry)

    return {
        "ok": True, "dry_run": dry_run,
        "linked": linked, "suggestions": suggestions, "skipped": skipped,
        "summary": {
            "linked": len(linked), "suggested": len(suggestions),
            "already_linked": len([s for s in skipped if s.get("status") == "already_linked"]),
            "no_credential": len([s for s in skipped if s.get("status") == "no_credential"]),
        },
    }




@router.get("/clients/{client_id}/ilo-health")
async def get_client_ilo_health(client_id: str, current_user: dict = Depends(get_current_user)):
    """Return Redfish/iLO hardware telemetry for all iLO servers of a client.

    v2026-02-14: estesa per includere anche i server senza credenziali iLO
    configurate (`ilo_configured: false`), cosi' l'admin vede TUTTI i server
    del cliente nella tab Server e puo' identificare quali necessitano di
    configurazione iLO (placeholder con CTA "Configura credenziali iLO").
    """
    # 1) Server con dati Redfish gia' raccolti
    docs = await db.device_poll_status.find(
        {
            "client_id": client_id,
            "$or": [
                {"device_class": "hpe-ilo"},
                {"redfish.server_model": {"$nin": [None, ""]}},
                {"redfish.bios_version": {"$nin": [None, ""]}},
                {"monitor_type": "redfish_direct"},
            ],
        },
        {"_id": 0}
    ).to_list(100)
    # 2) Lista nomi dai managed_devices per arricchimento
    managed = await db.managed_devices.find(
        {"client_id": client_id}, {"_id": 0, "ip": 1, "name": 1, "device_type": 1, "vendor": 1, "model": 1, "virtualization": 1}
    ).to_list(500)
    name_map = {m["ip"]: m.get("name") for m in managed}
    # v2026-06: IP marcati come VM dall'admin → esclusi dalla lista iLO
    # (sia dai device redfish/poll-only, sez.1, sia dai managed, sez.4).
    _VM_TYPES = {"hyperv", "vmware", "vm_generic"}
    vm_ips = {m.get("ip") for m in managed if (m.get("virtualization") or "") in _VM_TYPES}

    # 3) Credenziali iLO esistenti per questo client (per flag ilo_configured)
    ilo_creds = await db.device_credentials.find(
        {"client_id": client_id, "credential_type": "ilo"},
        {"_id": 0, "device_ip": 1, "external_url": 1, "connector_only": 1, "host_ip": 1}
    ).to_list(500)
    ilo_creds_map = {c.get("device_ip"): c for c in ilo_creds if c.get("device_ip")}
    # v2026-09: associazione iLO↔host. Una credenziale iLO puo' avere `host_ip`
    # (IP del SO/host, diverso dall'IP di management iLO). In tal caso i dati
    # Redfish letti sull'IP iLO vanno MOSTRATI sotto il server host, non come
    # entita' separata. host_to_ilo: {host_ip: ilo_device_ip}.
    host_to_ilo = {c["host_ip"]: c["device_ip"] for c in ilo_creds if c.get("host_ip") and c.get("device_ip")}
    linked_ilo_ips = set(host_to_ilo.values())
    poll_by_ip = {d.get("device_ip"): d for d in docs}

    result = []
    seen_ips = set()
    for d in docs:
        ip = d.get("device_ip")
        seen_ips.add(ip)
        if ip in vm_ips:
            continue  # VM (impostata dall'admin): esclusa dalla lista iLO
        if ip in linked_ilo_ips:
            continue  # IP iLO collegato a un host: i suoi dati vengono mostrati sotto il server host (sez.4)
        rf = d.get("redfish", {}) or {}
        hw = d.get("hardware", {}) or {}
        cred = ilo_creds_map.get(ip)
        result.append({
            "device_ip": ip,
            "device_name": name_map.get(ip) or d.get("device_name") or ip,
            "polling_mode": d.get("monitor_type", "unknown"),
            "last_poll": d.get("last_poll"),
            "reachable": d.get("reachable", False),
            "server_model": rf.get("server_model"),
            "serial_number": rf.get("serial_number"),
            "bios_version": rf.get("bios_version"),
            "ilo_firmware": rf.get("ilo_firmware"),
            "ilo_license": rf.get("ilo_license"),
            "power_watts": rf.get("power_watts"),
            "total_memory_gb": rf.get("total_memory_gb"),
            "memory_dimms": rf.get("memory_dimms", []),
            "network_adapters": rf.get("network_adapters", []),
            "storage_controllers": rf.get("storage_controllers", []),
            "health_status": hw.get("health_status"),
            "temperatures": hw.get("temperatures", []),
            "fans": hw.get("fans", []),
            "power_supplies": hw.get("power_supplies", []),
            "uuid": rf.get("uuid"),
            "power_state": rf.get("power_state"),
            "indicator_led": rf.get("indicator_led"),
            "post_state": rf.get("post_state"),
            "processors": rf.get("processors", []),
            "processor_summary": rf.get("processor_summary"),
            "ilo_configured": bool(cred),
            "ilo_external_url": (cred or {}).get("external_url"),
            "ilo_connector_only": bool((cred or {}).get("connector_only")),
            "has_redfish_data": bool(rf.get("server_model") or rf.get("bios_version")),
        })

    # 4) Server senza dati Redfish ma classificati come server in managed_devices.
    # v2026-02-14: filtro STRETTO. Solo device_type esplicitamente "server"
    # o "ilo" (settato dall'admin o dal classifier). Niente euristiche
    # su vendor HP/Dell/Lenovo perche' includerebbero workstation
    # (GALVAN-UFF002), stampanti (NPIC3C01E con OUI HP), notebook, NAS HP, ecc.
    # L'admin puo' sempre trascinare un device nella macro "server" dalla tab
    # Dispositivi → move-category, e il device apparira' anche qui.
    SERVER_LIKE_TYPES = {"server", "ilo", "hpe-ilo"}
    for m in managed:
        ip = m.get("ip")
        if not ip or ip in seen_ips:
            continue
        dtype = (m.get("device_type") or "").lower()
        if dtype not in SERVER_LIKE_TYPES:
            continue
        # v2026-06: le VM (impostate dall'admin) NON sono server iLO fisici →
        # escluse dalla lista "server senza credenziali iLO" per non chiedere
        # credenziali iLO inutili. Il loro stato vive nel pannello Hyper-V.
        if (m.get("virtualization") or "") in ("hyperv", "vmware", "vm_generic"):
            continue
        cred = ilo_creds_map.get(ip)
        # Merge iLO collegata via host_ip: se questo server host ha una iLO
        # associata, mostra i suoi dati Redfish qui (invece di "senza iLO").
        linked_ilo_ip = host_to_ilo.get(ip)
        ld = poll_by_ip.get(linked_ilo_ip) if linked_ilo_ip else None
        lrf = (ld or {}).get("redfish", {}) or {}
        lhw = (ld or {}).get("hardware", {}) or {}
        linked_cred = ilo_creds_map.get(linked_ilo_ip) if linked_ilo_ip else None
        has_linked_data = bool(lrf.get("server_model") or lrf.get("bios_version"))
        result.append({
            "device_ip": ip,
            "device_name": m.get("name") or ip,
            "ilo_ip": linked_ilo_ip,
            "polling_mode": (ld or {}).get("monitor_type", "not_configured") if linked_ilo_ip else "not_configured",
            "last_poll": (ld or {}).get("last_poll"),
            "reachable": (ld or {}).get("reachable") if linked_ilo_ip else None,
            "server_model": lrf.get("server_model") or m.get("model"),
            "serial_number": lrf.get("serial_number"),
            "bios_version": lrf.get("bios_version"),
            "ilo_firmware": lrf.get("ilo_firmware"),
            "ilo_license": lrf.get("ilo_license"),
            "power_watts": lrf.get("power_watts"),
            "total_memory_gb": lrf.get("total_memory_gb"),
            "memory_dimms": lrf.get("memory_dimms", []),
            "network_adapters": lrf.get("network_adapters", []),
            "storage_controllers": lrf.get("storage_controllers", []),
            "health_status": lhw.get("health_status", "unknown"),
            "temperatures": lhw.get("temperatures", []),
            "fans": lhw.get("fans", []),
            "power_supplies": lhw.get("power_supplies", []),
            "uuid": lrf.get("uuid"),
            "power_state": lrf.get("power_state"),
            "indicator_led": lrf.get("indicator_led"),
            "post_state": lrf.get("post_state"),
            "processors": lrf.get("processors", []),
            "processor_summary": lrf.get("processor_summary"),
            "ilo_configured": bool(cred or linked_cred),
            "ilo_external_url": (cred or linked_cred or {}).get("external_url"),
            "ilo_connector_only": bool((cred or linked_cred or {}).get("connector_only")),
            "has_redfish_data": has_linked_data,
            "needs_ilo_setup": not bool(cred or linked_cred),
        })

    return result
