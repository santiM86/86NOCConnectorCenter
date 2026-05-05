"""Network topology inference engine and routes."""
from fastapi import APIRouter, Depends, HTTPException
import re
import ipaddress
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["topology"])

# ---------------------------------------------------------------------------
# Switch port detail (with LLDP neighbor enrichment + stats)
# ---------------------------------------------------------------------------
IF_OPER_STATUS_MAP = {
    1: "up", 2: "down", 3: "testing", 4: "unknown",
    5: "dormant", 6: "notPresent", 7: "lowerLayerDown",
}
IF_ADMIN_STATUS_MAP = {1: "up", 2: "down", 3: "testing"}


def _port_number_from_name(name: str) -> str:
    """Estrae il numero porta da nomi tipo 'Gi1/0/24', 'Port 12', 'GigabitEthernet0/8'."""
    import re as _re
    if not name:
        return ""
    # 'Gi1/0/24' → '24', 'Eth0/8' → '8'
    m = _re.search(r"(\d+)$", name)
    if m:
        return m.group(1)
    m = _re.search(r"Port[ _-]?(\d+)", name, _re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


@router.get("/devices/{device_ip}/switch-ports")
async def get_switch_ports(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Ritorna le porte dello switch con status arricchito da LLDP neighbor + MAC table.

    Matching in cascata (priorita' decrescente):
      1. LLDP neighbor (remote_sys_name/remote_ip) — funziona con device managed/LLDP-capable
      2. MAC Table -> managed_devices (via MAC di ifPhysAddress) — per NAS/stampanti/UPS
      3. MAC Table -> OUI vendor lookup — per device sconosciuti (es. "Apple laptop")
    """
    from .oui_lookup import lookup_oui, classify_device

    ports = await db.switch_ports.find({"local_ip": device_ip}, {"_id": 0}).sort("idx", 1).to_list(2000)
    neighbors = await db.lldp_neighbors.find({"local_ip": device_ip}, {"_id": 0}).to_list(500)

    # MAC-based enrichment: prendi endpoint FDB raccolti e i managed devices
    endpoints = await db.discovered_endpoints.find({"switch_ip": device_ip}, {"_id": 0}).to_list(5000)

    # Managed devices: costruisci MAC -> device map
    # NB: discovered_endpoints.ip e' gia' risolto lato connector per i MAC managed,
    # ma teniamo anche un fallback via device_poll_status/managed_devices
    md_all = await db.managed_devices.find({}, {"_id": 0, "ip": 1, "device_type": 1, "device_name": 1, "vendor": 1}).to_list(2000)
    md_by_ip = {d["ip"]: d for d in md_all if d.get("ip")}

    # v3.6.15: MAC Cross-Correlation per trunk switch-to-switch.
    # Se un endpoint sulla porta locale risolve a un altro switch managed, cerchiamo
    # nella FDB dell'altro switch quale porta vede i MAC delle interfacce di QUESTO
    # switch locale: quella e' la porta remota del trunk (FDB bidirezionale).
    local_ifmacs: set[str] = set()
    remote_port_cache: dict[str, str] = {}  # remote_ip -> port remota computata
    try:
        # v3.6.17 PERF: scope la query a un singolo client_id se conosciuto, e prendi
        # solo l'ultimo doc (era to_list(20)). Su scale evita full scan di network_discovery.
        local_md = next((d for d in md_all if d.get("ip") == device_ip), None)
        scope_client_id = (local_md or {}).get("client_id") if local_md else None
        nd_query = {"client_id": scope_client_id} if scope_client_id else {}
        nd_doc = await db.network_discovery.find_one(
            nd_query, {"_id": 0, "device_macs": 1, "client_id": 1},
            sort=[("updated_at", -1)],
        )
        ifmacs_by_ip: dict[str, set[str]] = {}
        if nd_doc:
            for dm in (nd_doc.get("device_macs") or []):
                dip = dm.get("ip", "")
                if not dip:
                    continue
                macs = set((m or "").upper() for m in (dm.get("macs") or []) if m)
                if macs:
                    ifmacs_by_ip[dip] = macs
        local_ifmacs = ifmacs_by_ip.get(device_ip, set())

        if endpoints and local_ifmacs:
            # IP managed riferiti dalle FDB del device locale (potenziali trunk peer)
            candidate_remote_ips = set()
            for e in endpoints:
                rip = e.get("ip") or ""
                if e.get("is_managed") and rip and rip != device_ip:
                    candidate_remote_ips.add(rip)
            # Per ciascun peer switch managed, cerca quale porta ha nei propri FDB
            # almeno un MAC delle interfacce locali (= trunk bidirezionale).
            from collections import Counter
            for rip in candidate_remote_ips:
                items = await db.discovered_endpoints.find(
                    {"switch_ip": rip, "mac": {"$in": list(local_ifmacs)}},
                    {"_id": 0, "port": 1, "mac": 1},
                ).to_list(100)
                if not items:
                    continue
                port_counter: Counter = Counter(
                    i.get("port") for i in items if i.get("port") is not None
                )
                if port_counter:
                    best_port, _cnt = port_counter.most_common(1)[0]
                    remote_port_cache[rip] = str(best_port)
    except Exception as _e_cc:
        # Non bloccare il rendering della pagina se il cross-correlation fallisce
        remote_port_cache = {}

    # Index neighbors by local_port_desc and by port_number extracted
    by_desc: dict[str, dict] = {}
    by_number: dict[str, dict] = {}
    for n in neighbors:
        pd = (n.get("local_port_desc") or "").strip().lower()
        pid = (n.get("local_port_id") or "").strip().lower()
        if pd:
            by_desc[pd] = n
        if pid:
            by_desc[pid] = n
        pnum = _port_number_from_name(n.get("local_port_desc") or n.get("local_port_id") or "")
        if pnum:
            by_number[pnum] = n

    # Index endpoints (MAC table) by port number (endpoint.port dal FDB e' l'ifIndex o bridge port index)
    # Per HPE Comware FDB il port e' il bridgePort, spesso coincide con un idx. Proviamo match multipli.
    endpoints_by_port_num: dict[str, list] = {}
    endpoints_by_idx: dict[int, list] = {}
    for e in endpoints:
        port_val = e.get("port")
        try:
            port_int = int(port_val) if port_val is not None else None
        except Exception:
            port_int = None
        if port_int is not None:
            endpoints_by_idx.setdefault(port_int, []).append(e)
            endpoints_by_port_num.setdefault(str(port_int), []).append(e)

    def _build_mac_neighbor(port_idx: int, port_name: str):
        """Costruisce un neighbor-like dict dai MAC endpoints della porta."""
        cand = endpoints_by_idx.get(port_idx) or []
        if not cand:
            pnum = _port_number_from_name(port_name or "")
            if pnum:
                cand = endpoints_by_port_num.get(pnum) or []
        if not cand:
            return None, []
        # v3.7.0 Privacy Hardened: Datto RMM match ha priorita' su MANUAL/MAC (subito sotto LLDP).
        # Usa SOLO datto_name per identificazione — OS/version NON vengono piu' persistiti.
        datto_match = next((x for x in cand if x.get("datto_name")), None)
        if datto_match:
            return {
                "remote_sys_name": datto_match.get("datto_name") or datto_match.get("ip", ""),
                "remote_ip": datto_match.get("ip", ""),
                "remote_device_type": "generic",
                "remote_device_name": datto_match.get("datto_name", ""),
                "remote_port_id": "",
                "remote_port_desc": "",
                "remote_chassis_id": datto_match.get("mac", ""),
                "remote_sys_cap": 0,
                "remote_sys_desc": "Identificato via Datto RMM",
                "match_source": "datto_rmm",
            }, cand
        # v3.6.16: Manual MAC binding ha priorita' su tutto il MAC fallback
        # (subito sotto LLDP/Datto). Se almeno un endpoint candidato ha un manual_binding,
        # restituiscilo come neighbor "manual_mac".
        manual = next((x for x in cand if x.get("manual_binding_ip")), None)
        if manual:
            return {
                "remote_sys_name": manual.get("manual_binding_name") or manual.get("manual_binding_ip"),
                "remote_ip": manual.get("manual_binding_ip"),
                "remote_device_type": manual.get("manual_binding_type") or "generic",
                "remote_device_name": manual.get("manual_binding_name") or "",
                "remote_port_id": "",
                "remote_port_desc": "",
                "remote_chassis_id": manual.get("mac", ""),
                "remote_sys_cap": 0,
                "remote_sys_desc": "Binding manuale impostato dall'admin",
                "match_source": "mac_manual",
            }, cand
        # Priorita': managed > unmanaged OUI-known > unknown
        managed = [x for x in cand if x.get("is_managed")]
        unmanaged = [x for x in cand if not x.get("is_managed")]
        # Preferisci un singolo device managed se presente
        if managed:
            e = managed[0]
            ip = e.get("ip") or ""
            md = md_by_ip.get(ip, {})
            # v3.6.15: se il peer e' un altro switch managed, risolvi anche la porta remota via FDB cross-correlation
            remote_port = remote_port_cache.get(ip, "")
            is_switch_trunk = bool(remote_port)
            return {
                "remote_sys_name": md.get("device_name") or ip or "Device managed",
                "remote_ip": ip,
                "remote_device_type": md.get("device_type") or "",
                "remote_device_name": md.get("device_name") or "",
                "remote_port_id": remote_port,
                "remote_port_desc": (f"port {remote_port}" if remote_port else ""),
                "remote_chassis_id": e.get("mac", ""),
                "remote_sys_cap": (0x04 if is_switch_trunk else 0),  # bit 2 = bridge/switch
                "remote_sys_desc": ("Trunk switch-to-switch (FDB correlation)" if is_switch_trunk else ""),
                "match_source": ("mac_fdb_trunk" if is_switch_trunk else "mac_managed"),
            }, cand
        # Nessun managed: prova OUI del primo MAC
        if unmanaged:
            e = unmanaged[0]
            mac = e.get("mac", "")
            vendor = lookup_oui(mac)
            label = f"{vendor} device" if vendor else "Dispositivo sconosciuto"
            return {
                "remote_sys_name": label,
                "remote_ip": e.get("ip") or "",
                "remote_device_type": "unmanaged",
                "remote_device_name": label,
                "remote_port_id": "",
                "remote_port_desc": "",
                "remote_chassis_id": mac,
                "remote_sys_cap": 0,
                "remote_sys_desc": f"MAC: {mac}" + (f" ({vendor})" if vendor else ""),
                "match_source": "mac_oui" if vendor else "mac_unknown",
                "mac_count": len(cand),
            }, cand
        return None, []

    # Lookup managed_devices by remote_ip to enrich neighbor with type/icon
    mgmt_by_ip: dict[str, dict] = {}
    if neighbors:
        rips = list({n.get("remote_ip") for n in neighbors if n.get("remote_ip")})
        if rips:
            md_docs = await db.managed_devices.find(
                {"ip": {"$in": rips}},
                {"_id": 0, "ip": 1, "device_type": 1, "device_name": 1, "vendor": 1, "profile_key": 1}
            ).to_list(500)
            mgmt_by_ip = {d["ip"]: d for d in md_docs}

    out = []
    ok_count = down_count = disabled_count = neighbor_count = 0
    poe_active_count = 0
    total_rx_bps = total_tx_bps = 0
    for p in ports:
        oper = p.get("oper", 0)
        admin = p.get("admin", 0)
        # Match neighbor in cascata:
        # 1) LLDP (priorita' alta)
        neigh = by_desc.get((p.get("name") or "").strip().lower())
        if not neigh:
            neigh = by_number.get(_port_number_from_name(p.get("name") or ""))
        match_source = "lldp" if neigh else None

        # 2) Fallback MAC Table (se porta UP e nessun LLDP match)
        mac_neigh = None
        mac_cand = []
        if not neigh and oper == 1:
            mac_neigh, mac_cand = _build_mac_neighbor(p.get("idx") or 0, p.get("name") or "")
            if mac_neigh:
                match_source = mac_neigh.get("match_source", "mac")

        # Port type classification (Nebula-style)
        # disabled: admin_down
        # empty: oper_down (no link)
        # poe: PoE deliveringPower (poe_status==3) regardless of neighbor
        # ap: LLDP cap bit 0x08 (WLAN) OR neighbor name contains AP/Wireless
        # switch: LLDP cap bit 0x04 (Bridge) OR vendor "switch" device_type
        # router/cloud: LLDP cap bit 0x10 (Router) OR device_type firewall/router/internet
        # device: link up + neighbor presente ma generic
        # link_up: link up senza neighbor
        port_type = "empty"
        if admin == 2:
            port_type = "disabled"
        elif oper != 1:
            port_type = "empty"
        else:
            # link up
            poe_status = int(p.get("poe_status") or 0)
            cap = int((neigh or {}).get("remote_sys_cap") or 0)
            md_remote = mgmt_by_ip.get((neigh or {}).get("remote_ip") or "") if neigh else None
            dtype = (md_remote or {}).get("device_type", "") if md_remote else ""
            sys_desc = ((neigh or {}).get("remote_sys_desc") or "").lower() if neigh else ""
            sys_name = ((neigh or {}).get("remote_sys_name") or "").lower() if neigh else ""

            is_ap = (cap & 0x08) != 0 or "ap" in sys_name.split() or "access point" in sys_desc or "wireless" in sys_desc or dtype == "ap"
            is_switch = (cap & 0x04) != 0 or dtype == "switch" or "switch" in sys_desc
            is_router = (cap & 0x10) != 0 or dtype in ("firewall", "router") or "router" in sys_desc or "firewall" in sys_desc

            if is_ap:
                port_type = "ap"
            elif is_router:
                port_type = "cloud"   # uplink internet/firewall
            elif is_switch:
                port_type = "switch"
            elif poe_status == 3:
                port_type = "poe"     # PoE attivo (telefono/cam IP non identificato)
            elif neigh:
                port_type = "device"
            else:
                port_type = "link_up"
            # match_source used below for neighbor_obj
            _ = match_source

        neighbor_obj = None
        if neigh:
            md_remote = mgmt_by_ip.get(neigh.get("remote_ip") or "")
            neighbor_obj = {
                "remote_sys_name": neigh.get("remote_sys_name") or "",
                "remote_port_desc": neigh.get("remote_port_desc") or "",
                "remote_port_id": neigh.get("remote_port_id") or "",
                "remote_ip": neigh.get("remote_ip") or "",
                "remote_chassis_id": neigh.get("remote_chassis_id") or "",
                "remote_sys_cap": int(neigh.get("remote_sys_cap") or 0),
                "remote_sys_desc": neigh.get("remote_sys_desc") or "",
                "remote_device_type": (md_remote or {}).get("device_type") or "",
                "remote_device_name": (md_remote or {}).get("device_name") or "",
                "match_source": "lldp",
            }
            neighbor_count += 1
        elif mac_neigh:
            # Fallback via MAC table (no LLDP, ma ce un endpoint FDB riconosciuto)
            neighbor_obj = dict(mac_neigh)
            # Allinea chiavi per compatibilita' con UI
            neighbor_obj.setdefault("remote_port_desc", "")
            neighbor_obj.setdefault("remote_port_id", "")
            neighbor_obj.setdefault("remote_sys_cap", 0)
            neighbor_obj.setdefault("remote_sys_desc", "")
            neighbor_count += 1
            # Se e' un device managed, migliora la port_type classification
            if neighbor_obj.get("match_source") == "mac_managed" and port_type == "link_up":
                dtype = (neighbor_obj.get("remote_device_type") or "").lower()
                if dtype in ("firewall", "router"):
                    port_type = "cloud"
                elif dtype == "switch":
                    port_type = "switch"
                elif dtype == "ap":
                    port_type = "ap"
                else:
                    port_type = "device"

        if admin == 2:
            disabled_count += 1
        elif oper == 1:
            ok_count += 1
        else:
            down_count += 1

        # ==== DEVICE CLASSIFICATION (Fase 1: OUI + LLDP + euristiche) ====
        # Aggiunge {device_category, classification_confidence, classification_source}
        # al neighbor_obj per device sconosciuti / parzialmente noti.
        # Si esegue solo se neighbor_obj esiste e non e' gia' un managed device noto.
        if neighbor_obj is not None and (
            neighbor_obj.get("match_source") in ("mac_oui", "mac_unknown", "mac_fdb_trunk")
            or not neighbor_obj.get("remote_device_type")
        ):
            try:
                _mac = neighbor_obj.get("remote_chassis_id") or ""
                _classification = classify_device(
                    mac=_mac,
                    sys_descr=neighbor_obj.get("remote_sys_desc"),
                    hostname=neighbor_obj.get("remote_sys_name"),
                    poe_class=p.get("poe_class") or p.get("poe_priority"),
                    lldp_caps=neigh.get("remote_sys_cap_str") if neigh else None,
                    lldp_med_class=neigh.get("remote_med_class") if neigh else None,
                    lldp_med_mfg=neigh.get("remote_med_mfg") if neigh else None,
                    lldp_med_model=neigh.get("remote_med_model") if neigh else None,
                )
                neighbor_obj["device_category"] = _classification.get("category")
                neighbor_obj["classification_confidence"] = _classification.get("confidence")
                neighbor_obj["classification_source"] = _classification.get("source")

                # ==== FALLBACK FINGERBANK (Fase 2) ====
                # Se la classificazione locale e' debole (< 70 confidence) E
                # l'integrazione Fingerbank e' configurata, interroga il database
                # online per ottenere device_name preciso (es. "HP LaserJet M404").
                # Tutto cacheato 30gg, quindi quota gratuita 250 query/g e' sufficiente
                # per ~7500 device/mese. La query negativa (no match) e' anch'essa
                # cacheata per non riprovare ad ogni reload.
                try:
                    if (_classification.get("confidence") or 0) < 70 and _mac:
                        from services import fingerbank_service
                        if await fingerbank_service.is_configured():
                            fb = await fingerbank_service.interrogate(mac=_mac)
                            if fb and fb.get("device_name"):
                                neighbor_obj["device_name_precise"] = fb["device_name"]
                                neighbor_obj["device_category"] = neighbor_obj.get("device_category") or "unknown"
                                neighbor_obj["classification_source"] = (
                                    (neighbor_obj.get("classification_source") or "") + "+fingerbank"
                                )
                                # Boost confidence se Fingerbank ha trovato qualcosa
                                fb_score = fb.get("score") or 60
                                neighbor_obj["classification_confidence"] = max(
                                    neighbor_obj.get("classification_confidence") or 0,
                                    int(fb_score),
                                )
                except Exception:
                    pass
            except Exception:
                pass

        rx_bps = int(p.get("rx_bps") or 0)
        tx_bps = int(p.get("tx_bps") or 0)
        total_rx_bps += rx_bps
        total_tx_bps += tx_bps
        if int(p.get("poe_status") or 0) == 3:
            poe_active_count += 1

        out.append({
            "idx": p.get("idx"),
            "name": p.get("name"),
            "alias": p.get("alias") or "",
            "oper": oper,
            "oper_status": IF_OPER_STATUS_MAP.get(oper, "unknown"),
            "admin": admin,
            "admin_status": IF_ADMIN_STATUS_MAP.get(admin, "unknown"),
            "speed_mbps": p.get("speed_mbps") or 0,
            "last_change_s": p.get("last_change_s") or 0,
            "rx_bps": rx_bps,
            "tx_bps": tx_bps,
            "rx_pps": int(p.get("rx_pps") or 0),
            "tx_pps": int(p.get("tx_pps") or 0),
            "in_octets": str(p.get("in_octets") or "0"),
            "out_octets": str(p.get("out_octets") or "0"),
            "poe_admin": int(p.get("poe_admin") or 0),
            "poe_status": int(p.get("poe_status") or 0),
            "poe_class": int(p.get("poe_class") or 0),
            "port_type": port_type,
            "neighbor": neighbor_obj,
        })

    # Port_number summary for UI badge
    first_updated = ports[0].get("updated_at") if ports else None
    # v3.6.16: include client_id + device_name per features come Manual MAC Binding nella UI
    md_local = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0, "client_id": 1, "device_name": 1, "name": 1}) or {}
    return {
        "device_ip": device_ip,
        "device_name": md_local.get("device_name") or md_local.get("name") or "",
        "client_id": md_local.get("client_id") or "",
        "ports": out,
        "totals": {
            "total": len(out),
            "up": ok_count,
            "down": down_count,
            "admin_down": disabled_count,
            "with_neighbor": neighbor_count,
            "poe_active": poe_active_count,
            "rx_bps": total_rx_bps,
            "tx_bps": total_tx_bps,
        },
        "updated_at": first_updated,
    }


@router.get("/devices/{device_ip}/switch-ports/{idx}/flaps")
async def get_port_flap_history(
    device_ip: str,
    idx: int,
    hours: int = 24,
    current_user: dict = Depends(get_current_user),
):
    """Ritorna gli eventi flap (UP/DOWN/ADMIN/SPEED change) per una porta, ultime N ore."""
    from datetime import datetime, timezone, timedelta
    hours = max(1, min(hours, 720))  # 1h..30gg
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    events = await db.port_flap_events.find(
        {"local_ip": device_ip, "idx": idx, "ts": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("ts", 1).to_list(500)
    # Breakdown per tipo
    kinds = {"oper_change": 0, "admin_change": 0, "speed_change": 0}
    for e in events:
        k = e.get("kind", "")
        if k in kinds:
            kinds[k] += 1
    return {
        "device_ip": device_ip,
        "idx": idx,
        "hours": hours,
        "events": events,
        "total": len(events),
        "by_kind": kinds,
    }




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
        full_name = dev.get("device_name") or ip
        classified.append({
            "ip": ip,
            "name": _clean_device_name(full_name),
            "full_name": full_name,
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


def _guess_endpoint_type(hostname, mac, listening_ports=None, bmc_kind=None):
    """Guess endpoint type from hostname, BMC fingerprint, TCP fingerprint, MAC OUI.

    Priority order:
      1. BMC fingerprint Redfish/IPMI attivo (iLO/iDRAC/IPMI/XCC) => sempre server
      2. Hostname keywords (strongest signal if naming convention exists)
      3. TCP port fingerprint (3389=Win Server, 22 only=Linux, 9100/515/631=Printer, ...)
      4. MAC OUI vendor fallback
    """
    from .oui_lookup import lookup_oui
    # v3.6.14: BMC Redfish rilevato -> server sicuro
    if bmc_kind and bmc_kind in ("ilo", "idrac", "ipmi", "xcc", "redfish_generic"):
        return "server"
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

    # v3.6.13: TCP port fingerprint (prima del fallback OUI, batte l'ambiguita')
    ports = set(listening_ports or [])
    if ports:
        # Printer: porta stampa diretta Raw/LPD/IPP
        if ports & {9100, 515, 631}:
            return "printer"
        # Windows Server/Workstation: RDP esposto
        if 3389 in ports:
            return "server"
        # VoIP phone/PBX
        if 5060 in ports:
            return "generic"
        # Linux/Unix server con SSH ma senza RDP - server di sicuro se anche altre porte tipiche
        if 22 in ports:
            if ports & {80, 443, 8080, 445}:
                return "server"
            # Solo SSH: managed appliance o server minimale
            return "server"
        # Solo HTTPS/HTTP: tipico di appliance/firewall/router management UI
        if ports & {443, 80, 8080} and not (ports & {22, 3389, 445}):
            # Se e' un vendor firewall lo sappiamo gia' da OUI piu' sotto, qui marca come generic
            pass

    # Fallback: usa OUI vendor del MAC per indovinare tipo
    vendor = lookup_oui(mac).lower() if mac else ""
    if vendor:
        # Firewall/security vendor - priorita' massima (se MAC proviene da un firewall, e' un firewall)
        if any(k in vendor for k in ["fortinet", "sophos", "sonicwall", "watchguard", "checkpoint", "palo alto", "juniper"]):
            return "firewall"
        if any(k in vendor for k in ["synology", "qnap"]):
            return "nas"
        if any(k in vendor for k in ["axis", "hikvision", "dahua", "uniview"]):
            return "camera"
        if any(k in vendor for k in ["yealink", "polycom", "grandstream", "snom"]):
            return "generic"
        if any(k in vendor for k in ["ubiquiti", "aruba", "meraki"]):
            return "ap"
        if any(k in vendor for k in ["apc", "eaton", "riello"]):
            return "ups"
        if any(k in vendor for k in ["brother", "canon", "epson", "ricoh", "xerox", "lexmark", "kyocera"]):
            return "printer"
        # Server management interface (iLO/iDRAC) - OUI dedicati dai vendor
        if "ilo" in vendor or "idrac" in vendor or "imm" in vendor:
            return "server"
        if any(k in vendor for k in ["vmware"]):
            return "server"
        if any(k in vendor for k in ["raspberry"]):
            return "generic"
        # HP/Dell/Lenovo/Supermicro: potrebbe essere sia server che workstation - marca generico
        # (il match con managed device da' il tipo preciso quando monitorato)
        if any(k in vendor for k in ["hp", "dell", "lenovo", "supermicro"]):
            return "generic"  # ambiguo, serve inferenza ulteriore
    return "generic"


def _vendor_from_mac(mac: str) -> str:
    """Wrapper to expose OUI vendor at module level for topology enrichment."""
    from .oui_lookup import lookup_oui
    return lookup_oui(mac or "")


def _clean_device_name(name):
    """Shorten overly long device names for display (keep model + location)."""
    if not name or len(name) < 50:
        return name
    # Pattern: "BRAND MODEL - long description - Location"
    # Extract brand+model and location
    parts = name.split(" - ", 2)
    if len(parts) >= 3:
        brand_model = parts[0].strip()
        location = parts[-1].strip()
        return f"{brand_model} - {location}"
    if len(parts) == 2:
        return name[:60]
    return name[:50]


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
    
    # Enrich managed device nodes with MAC addresses from discovery data
    nd = await db.network_discovery.find_one({"client_id": client_id}, {"_id": 0, "device_macs": 1})
    device_macs_map = {}
    if nd and nd.get("device_macs"):
        for dm in nd["device_macs"]:
            ip = dm.get("ip", "")
            macs = dm.get("macs", [])
            if ip and macs:
                device_macs_map[ip] = macs[0]  # primary MAC
    
    for node in topology["nodes"]:
        nip = node.get("ip", node.get("id", ""))
        if nip in device_macs_map:
            node["mac"] = device_macs_map[nip]
    
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

            # Determine endpoint type from MAC OUI, hostname, TCP fingerprint, BMC
            ep_type = _guess_endpoint_type(
                hostname, mac,
                ep.get("listening_ports") or [],
                ep.get("bmc_kind") or "",
            )
            vendor = _vendor_from_mac(mac)

            # Se non c'e' hostname, mostra vendor OUI come display name
            if not hostname and not ip and vendor:
                display_name = f"{vendor} device"
                subtitle = mac

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
                "vendor": vendor,  # v3.6.9+: OUI vendor per badge UI
                "switch_ip": switch_ip,
                "switch_port": port,
                "vlan": vlan,
                "hostname": hostname,
                "subtitle": subtitle,
                "listening_ports": ep.get("listening_ports") or [],  # v3.6.13: TCP fingerprint
                "bmc_kind": ep.get("bmc_kind") or "",  # v3.6.14: iLO/iDRAC/IPMI
                "bmc_version": ep.get("bmc_version") or "",
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

    # Managed device info (for SNMP config editability + primary metadata)
    # Senza questo il frontend non ha l'id interno del managed_device e non puo'
    # PUT /managed-devices/{id}/snmp → si blocca con "Device not found" 404.
    managed = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip}, {"_id": 0}
    )

    return {
        "device": device,
        "managed_device": managed,   # settings correnti (id, community, snmp_version, snmpv3_*, monitor_type, profile_key)
        "device_id": managed.get("id") if managed else None,
        "managed": managed is not None,
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



@router.post("/network/add-to-monitoring")
async def add_endpoint_to_monitoring(body: dict, current_user: dict = Depends(get_current_user)):
    """Promote a discovered endpoint to a monitored device."""
    client_id = body.get("client_id")
    ip = body.get("ip", "").strip()
    name = body.get("name", "").strip()
    mac = body.get("mac", "").strip()
    monitor_type = body.get("monitor_type", "ping")
    community = body.get("community", "public")

    if not client_id or not ip:
        raise HTTPException(status_code=400, detail="client_id e ip sono obbligatori")

    # Check if already monitored
    existing = await db.managed_devices.find_one({"client_id": client_id, "ip": ip})
    if existing:
        raise HTTPException(status_code=409, detail=f"Il dispositivo {ip} e' gia' monitorato")

    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    device_doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "ip": ip,
        "name": name or ip,
        "mac": mac,
        "community": community if monitor_type == "snmp" else "",
        "monitor_type": monitor_type,
        "http_port": 80,
        "created_at": now,
        "created_by": current_user.get("name", "Admin"),
    }
    await db.managed_devices.insert_one(device_doc)

    # Also create initial poll status
    await db.device_poll_status.update_one(
        {"client_id": client_id, "device_ip": ip},
        {"$set": {
            "client_id": client_id,
            "device_ip": ip,
            "device_name": name or ip,
            "monitor_type": monitor_type,
            "reachable": False,
            "last_seen": now,
        }},
        upsert=True,
    )

    # Mark discovered endpoint as managed
    await db.discovered_endpoints.update_many(
        {"client_id": client_id, "ip": ip},
        {"$set": {"is_managed": True}},
    )
    if mac:
        await db.discovered_endpoints.update_many(
            {"client_id": client_id, "mac": mac},
            {"$set": {"is_managed": True}},
        )

    device_doc.pop("_id", None)
    return {"status": "ok", "message": f"Dispositivo {ip} aggiunto al monitoraggio", "device": device_doc}


# ==================== MANUAL MAC BINDINGS (v3.6.16) ====================
# Permette all'admin di "agganciare" manualmente un MAC visto nella FDB ad un
# device (Nome + IP) quando l'auto-discovery non riesce a identificarlo.
# Il binding diventa permanente e ha priorita' immediatamente sotto LLDP nella
# risoluzione neighbor (sopra OUI e mac_unknown).

@router.post("/topology/mac-bindings")
async def create_mac_binding(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Crea o aggiorna un binding MAC -> {ip, name, device_type}.
    payload: { mac, ip, name, device_type?, client_id?, also_create_managed_device? }
    """
    mac = (payload.get("mac") or "").upper().strip()
    ip = (payload.get("ip") or "").strip()
    name = (payload.get("name") or "").strip()
    device_type = (payload.get("device_type") or "generic").strip().lower()
    client_id = (payload.get("client_id") or "").strip()
    also_create = bool(payload.get("also_create_managed_device", False))

    if not mac or not ip or not name:
        raise HTTPException(status_code=400, detail="mac, ip e name sono obbligatori")
    # Validate MAC format AA:BB:CC:DD:EE:FF
    if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac):
        raise HTTPException(status_code=400, detail="MAC non valido (atteso AA:BB:CC:DD:EE:FF)")
    # Validate IP
    try:
        ipaddress.ip_address(ip)
    except Exception:
        raise HTTPException(status_code=400, detail="IP non valido")

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "mac": mac, "ip": ip, "name": name,
        "device_type": device_type, "client_id": client_id,
        "updated_at": now, "updated_by": current_user.get("email", ""),
    }
    existing = await db.mac_device_bindings.find_one({"mac": mac}, {"_id": 0})
    if existing:
        await db.mac_device_bindings.update_one({"mac": mac}, {"$set": doc})
        action = "updated"
    else:
        doc["created_at"] = now
        doc["created_by"] = current_user.get("email", "")
        await db.mac_device_bindings.insert_one(doc.copy())
        action = "created"

    # Optional: create a managed device too (if it doesn't already exist)
    created_device_id = None
    if also_create and client_id:
        existing_dev = await db.devices.find_one({"client_id": client_id, "ip_address": ip}, {"_id": 0, "id": 1})
        if not existing_dev:
            import uuid as _uuid
            created_device_id = str(_uuid.uuid4())
            await db.devices.insert_one({
                "id": created_device_id, "client_id": client_id,
                "name": name, "device_type": device_type,
                "ip_address": ip, "hostname": "", "location": "",
                "status": "active", "redfish_enabled": False,
                "last_poll": None, "health_status": None,
                "created_at": now,
                "created_via": "manual_mac_binding",
                "bound_mac": mac,
            })
        else:
            created_device_id = existing_dev.get("id")

    # Aggiorna ALSO discovered_endpoints esistenti per match immediato
    await db.discovered_endpoints.update_many(
        {"mac": mac},
        {"$set": {"manual_binding_ip": ip, "manual_binding_name": name,
                  "manual_binding_type": device_type}},
    )

    return {"status": "ok", "action": action, "mac": mac,
            "device_id": created_device_id, "binding": doc}


@router.get("/topology/mac-bindings")
async def list_mac_bindings(
    client_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    q = {}
    if client_id:
        q["client_id"] = client_id
    items = await db.mac_device_bindings.find(q, {"_id": 0}).sort("updated_at", -1).to_list(500)
    return {"items": items, "count": len(items)}


@router.delete("/topology/mac-bindings/{mac}")
async def delete_mac_binding(
    mac: str,
    current_user: dict = Depends(get_current_user),
):
    mac_norm = mac.upper().strip()
    r = await db.mac_device_bindings.delete_one({"mac": mac_norm})
    # Cleanup discovered_endpoints overrides
    await db.discovered_endpoints.update_many(
        {"mac": mac_norm},
        {"$unset": {"manual_binding_ip": "", "manual_binding_name": "", "manual_binding_type": ""}},
    )
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Binding non trovato")
    return {"status": "ok", "deleted": r.deleted_count}

