"""Aggancio MAC → IP: se un device gestito (DHCP) cambia IP, lo seguiamo automaticamente.

`apply_mac_follow(client_id, endpoints, source)` viene chiamata dopo ogni discovery batch (agent v4
o connector legacy). Per ogni managed_device con MAC noto (follow_mac != False, non LAA random):
- se il MAC è visto su UN solo IP diverso da quello registrato e quell'IP non appartiene ad un altro
  device gestito → aggiorna ip/ip_address su managed_devices + devices e ri-chiava le collezioni
  per-IP (credenziali, poll status, porte switch, memoria porte, mac_connections, ilo), salva
  `ip_history`, emette alert medium `mac_follow_ip_update` e ri-pusha la config all'agent.
Ritorna la lista dei cambi applicati ({mac, old_ip, new_ip, name, device_id}).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from database import db

logger = logging.getLogger("mac_follow")
SOURCE_TYPE = "mac_follow_ip_update"


def norm_mac(m: Any) -> str:
    s = str(m or "").lower().replace("-", ":").replace(".", ":").strip()
    if ":" not in s and len(s) == 12:
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    return s if len(s) == 17 and s not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") else ""


def _is_laa(mac: str) -> bool:
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


async def _rekey(client_id: str, old_ip: str, new_ip: str) -> None:
    """Sposta i documenti per-IP dal vecchio al nuovo IP (best-effort, ogni collezione indipendente)."""
    targets = [
        ("devices", {"client_id": client_id, "ip_address": old_ip}, {"ip_address": new_ip}),
        ("device_credentials", {"client_id": client_id, "device_ip": old_ip}, {"device_ip": new_ip}),
        ("device_poll_status", {"client_id": client_id, "device_ip": old_ip}, {"device_ip": new_ip}),
        ("device_status_state", {"client_id": client_id, "device_ip": old_ip}, {"device_ip": new_ip}),
        ("ilo_status", {"client_id": client_id, "device_ip": old_ip}, {"device_ip": new_ip}),
        ("switch_ports", {"client_id": client_id, "local_ip": old_ip}, {"local_ip": new_ip}),
        ("port_memory", {"client_id": client_id, "local_ip": old_ip}, {"local_ip": new_ip}),
        ("mac_connections", {"client_id": client_id, "from_ip": old_ip}, {"from_ip": new_ip}),
        ("mac_connections", {"client_id": client_id, "to_ip": old_ip}, {"to_ip": new_ip}),
    ]
    for coll, q, upd in targets:
        try:
            await db[coll].update_many(q, {"$set": upd})
        except Exception as e:  # noqa: BLE001
            logger.debug(f"mac_follow rekey {coll} {old_ip}->{new_ip}: {e}")


async def apply_mac_follow(client_id: str, endpoints: list[dict], source: str = "discovery") -> list[dict]:
    if not client_id or not endpoints:
        return []
    seen: dict[str, set[str]] = {}
    ip_macs: dict[str, set[str]] = {}
    for ep in endpoints:
        mac, ip = norm_mac(ep.get("mac")), ep.get("ip")
        if mac and ip:
            seen.setdefault(mac, set()).add(ip)
            ip_macs.setdefault(ip, set()).add(mac)
    if not seen:
        return []
    mds = await db.managed_devices.find(
        {"client_id": client_id, "$or": [{"mac": {"$nin": [None, ""]}}, {"mac_address": {"$nin": [None, ""]}}]},
        {"_id": 0, "id": 1, "ip": 1, "ip_address": 1, "mac": 1, "mac_address": 1, "name": 1, "device_name": 1,
         "follow_mac": 1, "mac_is_random": 1},
    ).to_list(5000)
    by_ip: dict[str, dict] = {}
    for md in mds:
        for k in ("ip", "ip_address"):
            if md.get(k):
                by_ip.setdefault(md[k], md)
    changes: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for md in mds:
        if md.get("follow_mac") is False or md.get("mac_is_random"):
            continue
        mac = norm_mac(md.get("mac") or md.get("mac_address"))
        if not mac or _is_laa(mac):
            continue
        cur_ip = md.get("ip") or md.get("ip_address")
        ips = seen.get(mac)
        if not ips or not cur_ip or cur_ip in ips or len(ips) != 1:
            continue
        new_ip = next(iter(ips))
        other = by_ip.get(new_ip)
        if other and other.get("id") != md.get("id") and norm_mac(other.get("mac") or other.get("mac_address")) != mac:
            logger.info(f"mac_follow skip {mac}: {new_ip} appartiene ad altro device gestito ({other.get('name')})")
            continue
        name = md.get("name") or md.get("device_name") or cur_ip
        hist = {"from": cur_ip, "to": new_ip, "at": now, "source": source}
        await db.managed_devices.update_one(
            {"id": md["id"]},
            {"$set": {"ip": new_ip, "ip_address": new_ip, "ip_previous": cur_ip, "ip_changed_at": now, "follow_mac": True},
             "$push": {"ip_history": {"$each": [hist], "$slice": -20}}},
        )
        by_ip[new_ip] = md
        await _rekey(client_id, cur_ip, new_ip)
        alert = {
            "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": new_ip, "device_name": name, "device_type": "network",
            "severity": "medium", "source_type": SOURCE_TYPE,
            "title": f"IP aggiornato automaticamente: {name} {cur_ip} → {new_ip}",
            "message": f"Il dispositivo {name} (MAC {mac.upper()}) è stato rivisto su {new_ip} invece di {cur_ip} (lease DHCP cambiato). "
                       f"ARGUS ha aggiornato l'IP monitorato e spostato credenziali/porte/storico: nessuna azione richiesta. "
                       f"Per fissarlo, assegna una prenotazione DHCP.",
            "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
        }
        try:
            from alert_filter import insert_alert_if_emit
            if await insert_alert_if_emit(db, alert):
                import webpush as _wp
                await _wp.notify_new_alert(db, alert)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"mac_follow alert {name}: {e}")
        changes.append({"mac": mac, "old_ip": cur_ip, "new_ip": new_ip, "name": name, "device_id": md["id"]})
        logger.info(f"mac_follow {client_id}: {name} {mac} {cur_ip} -> {new_ip} ({source})")
    if changes:
        try:
            from routes.agent_ws import push_config_to_client
            await push_config_to_client(client_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"mac_follow push_config {client_id}: {e}")
    return changes
