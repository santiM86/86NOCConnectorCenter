"""
Rogue / New Device Detection (NDR-lite, ispirato a LECS)
========================================================
Rileva dispositivi/MAC MAI visti prima sulla rete di un cliente e genera un
alert. Risposta SUGGERITA a conferma umana (nessuna azione automatica):
  - "Autorizza": aggiunge il MAC all'allow-list del cliente e risolve l'alert.
  - "Isola (guida)": fornisce i passi di remediation (l'agent NON ha ancora un
    comando di SNMP-SET per spegnere la porta, quindi niente azioni finte).

Multi-tenant: baseline e allow-list sono PER-CLIENTE. Alla prima attivazione per
un cliente si fissa una baseline: l'inventario preesistente NON genera alert;
vengono segnalati solo i dispositivi comparsi DOPO l'attivazione.

Collections:
  - rogue_state       {client_id, baseline_at}
  - rogue_allowlist   {client_id, mac, note, added_by, added_at}
  - config in db.settings key "rogue_detection_config"
Alert: source_type = "rogue_device".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from database import db
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("rogue")

SETTINGS_KEY = "rogue_detection_config"
DEFAULT_CONFIG = {"enabled": True, "severity": "warning"}
VALID_SEVERITIES = ("info", "warning", "high", "critical")


# ==================== CONFIG ====================

async def get_config() -> dict:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    cfg = dict(DEFAULT_CONFIG)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


async def set_config(patch: dict) -> dict:
    cfg = await get_config()
    if "enabled" in patch:
        cfg["enabled"] = bool(patch["enabled"])
    if "severity" in patch and patch["severity"] in VALID_SEVERITIES:
        cfg["severity"] = patch["severity"]
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"key": SETTINGS_KEY, "value": cfg,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return cfg


# ==================== ALLOW-LIST ====================

def _norm_mac(mac: str) -> str:
    return (mac or "").lower().replace("-", ":").strip()


async def is_allowed(client_id: str, mac: str) -> bool:
    mac = _norm_mac(mac)
    if not mac:
        return True  # senza MAC non possiamo valutare: non allarmiamo
    doc = await db.rogue_allowlist.find_one({"client_id": client_id, "mac": mac}, {"_id": 0, "mac": 1})
    return doc is not None


async def add_to_allowlist(client_id: str, mac: str, note: str, added_by: str) -> None:
    mac = _norm_mac(mac)
    if not mac:
        return
    await db.rogue_allowlist.update_one(
        {"client_id": client_id, "mac": mac},
        {"$set": {"client_id": client_id, "mac": mac, "note": note or "",
                  "added_by": added_by or "", "added_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def remove_from_allowlist(client_id: str, mac: str) -> bool:
    res = await db.rogue_allowlist.delete_one({"client_id": client_id, "mac": _norm_mac(mac)})
    return res.deleted_count > 0


async def list_allowlist(client_id: str | None = None) -> list[dict]:
    q = {"client_id": client_id} if client_id else {}
    return await db.rogue_allowlist.find(q, {"_id": 0}).sort("added_at", -1).to_list(2000)


# ==================== BASELINE ====================

async def _get_baseline(client_id: str) -> str | None:
    doc = await db.rogue_state.find_one({"client_id": client_id}, {"_id": 0, "baseline_at": 1})
    return doc.get("baseline_at") if doc else None


async def set_baseline(client_id: str, when: str | None = None) -> str:
    """Fissa/azzera la baseline del cliente a `when` (default ora): tutto ciò che
    esiste ora diventa 'noto', si segnaleranno solo i nuovi arrivi successivi."""
    ts = when or datetime.now(timezone.utc).isoformat()
    await db.rogue_state.update_one(
        {"client_id": client_id},
        {"$set": {"client_id": client_id, "baseline_at": ts}},
        upsert=True,
    )
    return ts


# ==================== DETECTION ====================

async def scan_client(client_id: str) -> dict:
    """Scansiona gli endpoint di un cliente e allerta sui nuovi (post-baseline)."""
    baseline = await _get_baseline(client_id)
    if baseline is None:
        # Prima attivazione per questo cliente: fissa baseline, NON allarmare l'inventario.
        baseline = await set_baseline(client_id)
        return {"client_id": client_id, "baseline_set": True, "new": 0, "alerts": 0}

    # Candidati: endpoint comparsi DOPO la baseline (first_seen_at > baseline)
    cursor = db.discovered_endpoints.find(
        {"client_id": client_id, "first_seen_at": {"$gt": baseline}},
        {"_id": 0, "mac": 1, "ip": 1, "first_seen_at": 1, "vendor_scanner": 1,
         "hostname_scanner": 1, "sys_name_scanner": 1, "switch_ip": 1, "port": 1,
         "port_name": 1, "last_seen_subnet": 1, "vlan_id": 1},
    )
    endpoints = await cursor.to_list(5000)

    alerts = 0
    new = 0
    for ep in endpoints:
        mac = _norm_mac(ep.get("mac"))
        if not mac:
            continue
        if await is_allowed(client_id, mac):
            continue
        new += 1
        created = await _emit_rogue_alert(client_id, ep, mac)
        if created:
            alerts += 1
    if new:
        logger.info(f"[rogue] client={client_id} new={new} alerts={alerts}")
    return {"client_id": client_id, "baseline_set": False, "new": new, "alerts": alerts}


async def scan_all() -> dict:
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"skipped": True}
    client_ids = [c["id"] for c in await db.clients.find({}, {"_id": 0, "id": 1}).to_list(500)]
    total_new = 0
    total_alerts = 0
    for cid in client_ids:
        try:
            r = await scan_client(cid)
            total_new += r.get("new", 0)
            total_alerts += r.get("alerts", 0)
        except Exception as e:
            logger.warning(f"[rogue] scan_client {cid} failed: {e}")
    return {"clients": len(client_ids), "new": total_new, "alerts": total_alerts}


def _is_randomized_mac(mac: str) -> bool:
    """True se il MAC è locally-administered/randomizzato (privacy: iPhone/Android moderni).
    Bit 1 (0x02) del primo byte = 1 → MAC non globale (tipico di dispositivi personali)."""
    mac = _norm_mac(mac)
    try:
        first = int(mac.split(":")[0], 16)
        return bool(first & 0x02)
    except Exception:
        return False


async def enrich_endpoint(ep: dict, mac: str) -> dict:
    """Arricchisce un dispositivo rogue con fingerprint (OUI/vendor) e reputazione,
    e calcola un verdetto di rischio 'a colpo d'occhio'."""
    from routes.oui_lookup import lookup_oui
    from services import osint_service as osint

    vendor = ep.get("vendor_scanner") or lookup_oui(mac) or ""
    randomized = _is_randomized_mac(mac)
    ip = ep.get("ip") or ""

    # Fingerbank (device type/OS) se configurato — best-effort, non blocca
    device_class = ""
    try:
        from services import fingerbank_service as fb_svc
        if await fb_svc.is_configured():
            fb = await fb_svc.interrogate(mac=mac)
            if isinstance(fb, dict):
                device_class = fb.get("device_name") or fb.get("device_type") or ""
    except Exception:
        pass

    # Reputazione IP: ha senso SOLO per IP pubblici. Gli IP privati (LAN) non
    # vanno mai confrontati con blocklist internet (alcune includono i bogon 10/8).
    ip_public = osint._is_public_ip(ip) if ip else False
    ioc_matches = []
    abuse_conf = None
    if ip and ip_public:
        try:
            ioc_matches = await osint._local_ioc_match(ip)
        except Exception:
            ioc_matches = []
        try:
            full = await osint.lookup_ip(ip)
            ab = full.get("abuseipdb") or {}
            if isinstance(ab, dict):
                abuse_conf = ab.get("abuse_confidence")
        except Exception:
            pass

    # Verdetto di rischio
    reasons = []
    risk = "medio"
    if ioc_matches:
        risk = "alto"; reasons.append("IP presente in blocklist/IOC")
    elif isinstance(abuse_conf, int) and abuse_conf >= 50:
        risk = "alto"; reasons.append(f"AbuseIPDB {abuse_conf}%")
    elif randomized and vendor:
        risk = "basso"; reasons.append("MAC privacy + vendor noto (probabile smartphone/dispositivo personale)")
    elif randomized:
        risk = "basso"; reasons.append("MAC randomizzato (tipico di dispositivi personali/guest)")
    elif vendor:
        risk = "medio"; reasons.append(f"Vendor riconosciuto ({vendor})")
    else:
        risk = "alto"; reasons.append("Vendor sconosciuto e MAC non randomizzato (dispositivo non identificato)")

    return {
        "vendor": vendor,
        "device_class": device_class,
        "mac_type": "randomizzato/privacy" if randomized else "vendor globale",
        "ip_public": ip_public,
        "ip_reputation": ("privata (LAN) — reputazione non applicabile" if (ip and not ip_public)
                          else ("nessuna" if not ioc_matches and not abuse_conf else "sospetta")),
        "ioc_matches": [m.get("source") for m in ioc_matches],
        "abuse_confidence": abuse_conf,
        "risk": risk,
        "risk_reasons": reasons,
    }


async def _emit_rogue_alert(client_id: str, ep: dict, mac: str) -> bool:
    """Crea (con dedup) un alert di dispositivo rogue e notifica live."""
    existing = await db.alerts.find_one(
        {"client_id": client_id, "source_type": "rogue_device", "raw_data": mac, "status": "active"},
        {"_id": 0, "id": 1},
    )
    cfg = await get_config()
    severity = cfg.get("severity", "warning")

    enr = await enrich_endpoint(ep, mac)
    # Il rischio alza la severità in automatico
    if enr["risk"] == "alto":
        severity = "high"

    vendor = enr.get("vendor") or ""
    name = ep.get("hostname_scanner") or ep.get("sys_name_scanner") or ""
    ip = ep.get("ip") or ""
    where = ""
    if ep.get("switch_ip"):
        pn = ep.get("port_name") or (f"porta {ep.get('port')}" if ep.get("port") else "")
        where = f" · connesso a switch {ep['switch_ip']}{(' ' + pn) if pn else ''}"
    subnet = ep.get("last_seen_subnet") or ""

    title = f"Dispositivo non riconosciuto in rete: {mac}"
    msg = (f"Rilevato un nuovo dispositivo mai visto prima sulla rete del cliente. "
           f"MAC {mac}{(' · ' + vendor) if vendor else ''}"
           f"{(' · ' + name) if name else ''}{(' · IP ' + ip) if ip else ''}"
           f"{(' · subnet ' + subnet) if subnet else ''}{where}. "
           f"Rischio: {enr['risk'].upper()} ({'; '.join(enr['risk_reasons'])}). "
           f"Verifica se è autorizzato; in caso contrario isola la porta.")

    now_iso = datetime.now(timezone.utc).isoformat()
    if existing:
        await db.alerts.update_one({"id": existing["id"]}, {"$set": {"message": msg, "last_seen_at": now_iso}})
        return False

    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "device_id": None,
        "device_ip": ip or None,
        "device_name": name or vendor or mac,
        "device_type": "endpoint",
        "severity": severity,
        "source_type": "rogue_device",
        "title": title,
        "message": msg,
        "raw_data": mac,
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": now_iso,
        # metadati utili alla UI / remediation
        "rogue_switch_ip": ep.get("switch_ip"),
        "rogue_port": ep.get("port"),
        "rogue_port_name": ep.get("port_name"),
        "rogue_vendor": vendor,
        "rogue_device_class": enr.get("device_class"),
        "rogue_mac_type": enr.get("mac_type"),
        "rogue_risk": enr.get("risk"),
        "rogue_risk_reasons": enr.get("risk_reasons"),
        "rogue_ip_reputation": enr.get("ip_reputation"),
        "rogue_ioc_matches": enr.get("ioc_matches"),
        "rogue_abuse_confidence": enr.get("abuse_confidence"),
    }
    await insert_alert_if_emit(db, alert_doc)
    await _notify(alert_doc)
    try:
        from alert_engine import notify_alert_telegram
        await notify_alert_telegram(db, alert_doc)
    except Exception:
        pass
    return True


async def _notify(alert_doc: dict) -> None:
    try:
        from deps import manager
        client = await db.clients.find_one({"id": alert_doc.get("client_id")}, {"_id": 0, "name": 1})
        payload = dict(alert_doc)
        payload["client_name"] = client["name"] if client else ""
        payload["ip_address"] = alert_doc.get("device_ip") or ""
        await manager.broadcast({"type": "new_alert", "alert": payload})
    except Exception as e:
        logger.warning(f"[rogue] WS broadcast failed: {e}")
    try:
        import webpush as _wp
        await _wp.notify_new_alert(db, alert_doc)
    except Exception as e:
        logger.warning(f"[rogue] webpush failed: {e}")


async def authorize(client_id: str, mac: str, added_by: str, note: str = "") -> dict:
    """Autorizza un MAC (allow-list) e risolve gli alert rogue attivi per quel MAC."""
    mac = _norm_mac(mac)
    await add_to_allowlist(client_id, mac, note, added_by)
    res = await db.alerts.update_many(
        {"client_id": client_id, "source_type": "rogue_device", "raw_data": mac, "status": "active"},
        {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat(),
                  "resolution_note": f"Dispositivo autorizzato da {added_by}."}},
    )
    return {"authorized": mac, "resolved_alerts": res.modified_count}


async def investigate(client_id: str, mac: str, by: str, note: str = "") -> dict:
    """Segna gli alert rogue attivi di un MAC come 'in indagine' (restano attivi,
    ma taggati con chi/quando/nota) per il workflow consenti/blocca/indaga."""
    mac = _norm_mac(mac)
    now_iso = datetime.now(timezone.utc).isoformat()
    res = await db.alerts.update_many(
        {"client_id": client_id, "source_type": "rogue_device", "raw_data": mac, "status": "active"},
        {"$set": {"investigating": True, "investigated_by": by or "",
                  "investigated_at": now_iso, "investigation_note": note or ""}},
    )
    return {"mac": mac, "updated": res.modified_count}


async def get_status() -> dict:
    cfg = await get_config()
    active = await db.alerts.count_documents({"source_type": "rogue_device", "status": "active"})
    allow = await db.rogue_allowlist.count_documents({})
    watched = await db.rogue_state.count_documents({})
    return {"config": cfg, "active_alerts": active, "allowlist_total": allow, "clients_watched": watched}
