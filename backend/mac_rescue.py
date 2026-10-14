"""MAC rescue: quando un device VITALE smette di rispondere al ping, prima di dichiararlo offline
l'Agent esegue uno scan ARP mirato della sua subnet per cercare il suo MAC su un altro IP (cambio DHCP).
Se lo trova → apply_mac_follow aggiorna l'IP (alert HIGH + Telegram "IP cambiato") e il falso offline non parte.
Stato in `mac_rescue_state` (client_id, ip): started_at, scan_id, done, found. Finestra di attesa: RESCUE_WAIT_S.
"""
from __future__ import annotations

import ipaddress
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import db
from mac_follow import mac_is_shared, norm_mac

logger = logging.getLogger("mac_rescue")
RESCUE_WAIT_S = 120
RESCUE_COOLDOWN_S = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def start_mac_rescue(conn: Any, client_id: str, md: dict) -> Optional[str]:
    """Avvia lo scan di soccorso (idempotente: max uno ogni RESCUE_COOLDOWN_S per device). Ritorna scan_id o None."""
    ip = md.get("ip") or md.get("ip_address")
    mac = norm_mac(md.get("mac") or md.get("mac_address"))
    if not ip or not mac or md.get("follow_mac") is False:
        return None
    if await mac_is_shared(client_id, mac):  # VM sulla stessa NIC: impossibile sapere quale sia → niente rescue
        return None
    st = await db.mac_rescue_state.find_one({"client_id": client_id, "ip": ip}, {"_id": 0})
    if st and (_now() - datetime.fromisoformat(st["started_at"])).total_seconds() < RESCUE_COOLDOWN_S:
        return None
    try:
        cidr = str(ipaddress.ip_network(f"{ip}/24", strict=False))
    except ValueError:
        return None
    scan_id = uuid.uuid4().hex
    await db.lan_scan_runs.insert_one({
        "scan_id": scan_id, "agent_id": getattr(conn, "agent_id", None), "client_id": client_id, "cidr": cidr,
        "status": "running", "started_at": _now().isoformat(), "ended_at": None, "progress": {"done": 0, "total": 0, "found": 0},
        "error": None, "results": [], "initiated_by": "mac_rescue", "purpose": "mac_rescue",
        "rescue": {"device_id": md.get("id"), "ip": ip, "mac": mac, "name": md.get("name")},
    })
    await db.mac_rescue_state.update_one({"client_id": client_id, "ip": ip},
                                         {"$set": {"started_at": _now().isoformat(), "scan_id": scan_id, "done": False, "found": None, "mac": mac}}, upsert=True)
    try:
        await conn.send_command("lan_scan", {"scan_id": scan_id, "cidr": cidr}, timeout=8.0)
        logger.info("mac_rescue started client=%s ip=%s mac=%s cidr=%s", client_id, ip, mac, cidr)
    except Exception as e:  # noqa: BLE001
        logger.warning("mac_rescue send failed ip=%s: %s", ip, e)
        await db.mac_rescue_state.update_one({"client_id": client_id, "ip": ip}, {"$set": {"done": True, "found": False, "error": str(e)[:120]}})
        await db.lan_scan_runs.update_one({"scan_id": scan_id}, {"$set": {"status": "error", "error": str(e)[:120], "ended_at": _now().isoformat()}})
        return None
    return scan_id


async def rescue_pending(client_id: str, ip: str) -> bool:
    """True se c'è uno scan di soccorso in corso (< RESCUE_WAIT_S) per questo device: il watchdog attende."""
    st = await db.mac_rescue_state.find_one({"client_id": client_id, "ip": ip}, {"_id": 0, "started_at": 1, "done": 1})
    if not st or st.get("done"):
        return False
    return (_now() - datetime.fromisoformat(st["started_at"])).total_seconds() < RESCUE_WAIT_S


async def on_rescue_scan_event(kind: str, run: dict, data: dict) -> None:
    """Chiamata dal bridge lan_scan per i run con purpose=mac_rescue: prova il follow su ogni risultato con MAC e alla fine chiude lo stato."""
    rescue = run.get("rescue") or {}
    client_id, old_ip, mac = run.get("client_id"), rescue.get("ip"), rescue.get("mac")
    if not client_id or not old_ip:
        return
    from mac_follow import apply_mac_follow
    found = False
    if kind == "lan_scan_result" and norm_mac(data.get("mac")) == mac and data.get("ip") and data.get("ip") != old_ip:
        changes = await apply_mac_follow(client_id, [{"ip": data["ip"], "mac": mac}], source="mac_rescue")
        found = bool(changes)
    elif kind == "lan_scan_done":
        results = [{"ip": r.get("ip"), "mac": r.get("mac")} for r in (run.get("results") or []) if r.get("mac")]
        changes = await apply_mac_follow(client_id, results, source="mac_rescue") if results else []
        found = any(c["mac"] == mac for c in changes)
    if found:
        await db.vital_offline_state.delete_one({"client_id": client_id, "ip": old_ip})
        await db.alerts.update_many({"client_id": client_id, "device_ip": old_ip, "status": "active",
                                     "source_type": {"$regex": "^(corr_|connector_offline|vital_device_offline|device_offline)"}},
                                    {"$set": {"status": "resolved", "resolved_at": _now().isoformat(),
                                              "resolution_note": "Falso offline: il dispositivo ha cambiato IP (riconosciuto dal MAC)."}})
        await db.mac_rescue_state.update_one({"client_id": client_id, "ip": old_ip}, {"$set": {"done": True, "found": True, "ended_at": _now().isoformat()}})
        logger.info("mac_rescue FOUND client=%s %s mac=%s", client_id, old_ip, mac)
    elif kind == "lan_scan_done":
        await db.mac_rescue_state.update_one({"client_id": client_id, "ip": old_ip}, {"$set": {"done": True, "found": False, "ended_at": _now().isoformat()}})
        logger.info("mac_rescue not found client=%s %s mac=%s → offline reale", client_id, old_ip, mac)


async def expire_stale() -> None:
    """Chiude gli stati di soccorso senza esito oltre la finestra (agent muto) così il watchdog procede."""
    cutoff = (_now() - timedelta(seconds=RESCUE_WAIT_S)).isoformat()
    await db.mac_rescue_state.update_many({"done": False, "started_at": {"$lt": cutoff}}, {"$set": {"done": True, "found": False}})
