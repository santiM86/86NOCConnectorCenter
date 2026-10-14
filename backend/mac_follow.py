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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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


async def resolve_ip_from_discovery(client_id: str, mac: str, max_age_h: int = 48) -> str | None:
    """Ultimo IP su cui il discovery (ARP/scan) ha visto questo MAC, se recente e non conteso da altro device gestito."""
    mac = norm_mac(mac)
    if not mac:
        return None
    since = (datetime.now(timezone.utc) - timedelta(hours=max_age_h)).isoformat()
    ep = await db.discovered_endpoints.find_one(
        {"client_id": client_id, "$or": [{"mac": mac}, {"mac": mac.upper()}], "last_seen_at": {"$gte": since}, "ip": {"$nin": [None, ""]}},
        {"_id": 0, "ip": 1}, sort=[("last_seen_at", -1)])
    if not ep:
        return None
    other = await db.managed_devices.find_one({"client_id": client_id, "$or": [{"ip": ep["ip"]}, {"ip_address": ep["ip"]}]}, {"_id": 0, "mac": 1, "mac_address": 1})
    if other and norm_mac(other.get("mac") or other.get("mac_address")) != mac:
        return None
    return ep["ip"]


async def _emit_multi_ip_alert(client_id: str, md: dict, name: str, mac: str, cur_ip: Optional[str], others: list[str]) -> None:
    """Il MAC di un device gestito risponde anche su altri IP (o il vecchio IP e' ancora vivo): avvisa senza spostare."""
    if not others:
        return
    title = f"{name}: stesso MAC visto anche su {', '.join(others[:3])}"
    if await db.alerts.find_one({"client_id": client_id, "title": title, "status": "active"}, {"_id": 1}):
        return
    vital = bool(md.get("is_vital"))
    alert = {
        "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": cur_ip or others[0], "device_name": name, "device_type": "network",
        "severity": "high" if vital else "medium", "source_type": "mac_follow_multi_ip", "force_telegram": vital, "instant": vital,
        "title": title,
        "message": f"Il MAC {mac.upper()} di {name} (IP monitorato {cur_ip or '—'}) è stato visto anche su {', '.join(others)}. "
                   f"Può essere un secondo IP dello stesso dispositivo (NAS multi-subnet) o un cambio IP in corso con voce ARP stantia. "
                   f"ARGUS non sposta l'IP finché quello attuale risponde: se il device ha davvero cambiato indirizzo, l'aggiornamento avverrà appena il vecchio IP smette di rispondere.",
        "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from alert_filter import insert_alert_if_emit
        if await insert_alert_if_emit(db, alert) and vital:
            from alert_engine import notify_alert_telegram
            await notify_alert_telegram(db, alert)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"mac_follow multi-ip alert {name}: {e}")


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
         "follow_mac": 1, "mac_is_random": 1, "is_vital": 1, "status": 1, "consecutive_ping_failures": 1},
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
        if not ips or (cur_ip and ips == {cur_ip}):
            continue
        name = md.get("name") or md.get("device_name") or cur_ip or mac.upper()
        candidates = sorted(ip for ip in ips if ip != cur_ip)
        old_dead = (not cur_ip) or md.get("status") == "offline" or int(md.get("consecutive_ping_failures") or 0) >= 2
        if cur_ip and cur_ip in ips and not old_dead:
            # vecchio IP ancora vivo + MAC visto anche altrove: NAS multi-IP o ARP stantio → avvisa, non spostare
            await _emit_multi_ip_alert(client_id, md, name, mac, cur_ip, candidates)
            continue
        if len(candidates) != 1:
            await _emit_multi_ip_alert(client_id, md, name, mac, cur_ip, candidates)
            continue
        new_ip = candidates[0]
        other = by_ip.get(new_ip)
        merged_dup = None
        if other and other.get("id") != md.get("id"):
            if norm_mac(other.get("mac") or other.get("mac_address")) == mac:
                # voce DUPLICATA (stesso MAC censito due volte, es. auto-censimento dello scan sul nuovo IP) → merge
                await db.managed_devices.delete_one({"id": other["id"]})
                merged_dup = other.get("name") or new_ip
                logger.info(f"mac_follow merge duplicato {mac}: rimosso '{merged_dup}' ({new_ip}), tengo '{name}'")
            else:
                logger.info(f"mac_follow skip {mac}: {new_ip} appartiene ad altro device gestito ({other.get('name')})")
                continue
        first_bind = not cur_ip
        hist = {"from": cur_ip, "to": new_ip, "at": now, "source": source}
        await db.managed_devices.update_one(
            {"id": md["id"]},
            {"$set": {"ip": new_ip, "ip_address": new_ip, "ip_previous": cur_ip, "ip_changed_at": now, "follow_mac": True, "ip_pending": False},
             "$push": {"ip_history": {"$each": [hist], "$slice": -20}}},
        )
        by_ip[new_ip] = md
        if first_bind:
            await db.deleted_devices.delete_many({"client_id": client_id, "device_ip": new_ip})
            alert = {
                "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": new_ip, "device_name": name, "device_type": "network",
                "severity": "low", "source_type": SOURCE_TYPE,
                "title": f"IP rilevato: {name} → {new_ip}",
                "message": f"Il dispositivo {name} agganciato tramite MAC {mac.upper()} è stato visto sulla rete con IP {new_ip}: "
                           f"il monitoraggio parte ora automaticamente.",
                "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
            }
        else:
            await _rekey(client_id, cur_ip, new_ip)
            vital = bool(md.get("is_vital")) or source == "mac_rescue"
            alert = {
                "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": new_ip, "device_name": name, "device_type": "network",
                "severity": "high" if vital else "medium", "source_type": SOURCE_TYPE, "force_telegram": vital, "instant": vital,
                "title": f"{'VITALE ' if vital else ''}IP cambiato: {name} {cur_ip} → {new_ip}",
                "message": f"Il dispositivo {name} (MAC {mac.upper()}) è stato rivisto su {new_ip} invece di {cur_ip} (lease DHCP cambiato). "
                           f"ARGUS ha aggiornato l'IP monitorato e spostato credenziali/porte/storico: nessuna azione richiesta. "
                           f"Per fissarlo, assegna una prenotazione DHCP."
                           + (f" Voce duplicata '{merged_dup}' su {new_ip} unificata in questo dispositivo." if merged_dup else ""),
                "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
            }
        try:
            from alert_filter import insert_alert_if_emit
            if await insert_alert_if_emit(db, alert):
                import webpush as _wp
                await _wp.notify_new_alert(db, alert)
                if alert.get("force_telegram"):
                    from alert_engine import notify_alert_telegram
                    await notify_alert_telegram(db, alert)
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
