"""Aggancio MAC → IP: se un device gestito (DHCP) cambia IP, lo seguiamo automaticamente.

`apply_mac_follow(client_id, endpoints, source)` viene chiamata dopo ogni discovery batch (agent v4
o connector legacy). Per ogni managed_device con MAC noto (follow_mac != False, non LAA random):
- se il MAC è visto su UN solo IP diverso da quello registrato e quell'IP non appartiene ad un altro
  device gestito → aggiorna ip/ip_address su managed_devices + devices e ri-chiava le collezioni
  per-IP (credenziali, poll status, porte switch, memoria porte, mac_connections, ilo), salva
  `ip_history`, emette alert medium `mac_follow_ip_update` e ri-pusha la config all'agent.
MAC CONDIVISO (piu' device gestiti con lo stesso MAC, es. VM dietro la stessa NIC, o MAC visto su piu' IP):
nessuno spostamento/merge/alert. Alert `nic_changed` solo se lo stesso IP risponde stabilmente con un MAC nuovo.
Ritorna la lista dei cambi applicati ({mac, old_ip, new_ip, name, device_id}).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
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


NIC_CHANGE_TYPE = "nic_changed"
NIC_CONFIRM_COUNT = 2


async def mac_is_shared(client_id: str, mac: str) -> bool:
    """MAC censito su piu' device gestiti (es. VM dietro la stessa scheda di rete)."""
    mac = norm_mac(mac)
    if not mac:
        return False
    n = await db.managed_devices.count_documents(
        {"client_id": client_id, "$or": [{"mac": {"$in": [mac, mac.upper()]}}, {"mac_address": {"$in": [mac, mac.upper()]}}]})
    return n > 1


async def _emit(alert: dict) -> None:
    try:
        from alert_filter import insert_alert_if_emit
        if await insert_alert_if_emit(db, alert):
            import webpush as _wp
            await _wp.notify_new_alert(db, alert)
            if alert.get("force_telegram"):
                from alert_engine import notify_alert_telegram
                await notify_alert_telegram(db, alert)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"mac_follow alert {alert.get('title')}: {e}")


async def _resolve_shared_noise(client_id: str, now: str) -> None:
    """Chiude i vecchi alert 'stesso MAC visto anche su…': il MAC condiviso non e' un'anomalia."""
    try:
        await db.alerts.update_many(
            {"client_id": client_id, "source_type": "mac_follow_multi_ip", "status": {"$ne": "resolved"}},
            {"$set": {"status": "resolved", "resolved_at": now, "resolved_by_system": True,
                      "resolution_note": "MAC condiviso (piu' dispositivi sulla stessa scheda di rete): non e' un'anomalia"}})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"mac_follow resolve shared {client_id}: {e}")


async def _check_nic_change(client_id: str, md: dict, mac: str, cur_ip: str, ip_macs: dict, seen: dict,
                            group_ips: set, owned_macs: set, now: str) -> None:
    """Stesso IP che risponde con un MAC diverso (confermato su N rilevazioni) → scheda di rete cambiata."""
    observed = ip_macs.get(cur_ip)
    pending = md.get("mac_change_pending") or {}
    if not observed:
        return
    if mac in observed or len(observed) != 1:
        if pending:
            await db.managed_devices.update_one({"id": md["id"]}, {"$unset": {"mac_change_pending": ""}})
        return
    new_mac = next(iter(observed))
    # MAC di un altro device gestito, o visto su IP estranei al gruppo (gateway/proxy ARP) → non e' una NIC nuova
    if new_mac in owned_macs or _is_laa(new_mac) or not seen.get(new_mac, set()) <= group_ips:
        return
    count = int(pending.get("count") or 0) + 1 if pending.get("mac") == new_mac else 1
    if count < NIC_CONFIRM_COUNT:
        await db.managed_devices.update_one(
            {"id": md["id"]}, {"$set": {"mac_change_pending": {"mac": new_mac, "count": count, "first_seen": pending.get("first_seen") or now}}})
        return
    name = md.get("name") or md.get("device_name") or cur_ip
    await db.managed_devices.update_one(
        {"id": md["id"]},
        {"$set": {"mac": new_mac, "mac_address": new_mac, "mac_previous": mac, "mac_changed_at": now},
         "$unset": {"mac_change_pending": ""},
         "$push": {"mac_history": {"$each": [{"from": mac, "to": new_mac, "at": now}], "$slice": -20}}})
    vital = bool(md.get("is_vital"))
    await _emit({
        "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": cur_ip, "device_name": name, "device_type": "network",
        "severity": "high" if vital else "medium", "source_type": NIC_CHANGE_TYPE, "force_telegram": vital, "instant": vital,
        "title": f"{'VITALE ' if vital else ''}Scheda di rete cambiata: {name} ({cur_ip})",
        "message": f"L'IP {cur_ip} di {name} ora risponde con il MAC {new_mac.upper()} invece di {mac.upper()} "
                   f"(confermato su {NIC_CONFIRM_COUNT} rilevazioni). Scheda di rete sostituita o dispositivo diverso su questo IP: "
                   f"verifica che sia un intervento previsto. ARGUS ha aggiornato il MAC registrato.",
        "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
    })
    logger.info(f"nic_changed {client_id}: {name} {cur_ip} {mac} -> {new_mac}")


async def apply_mac_follow(client_id: str, endpoints: list[dict], source: str = "discovery") -> list[dict]:
    """MAC-follow solo per MAC esclusivi; MAC condivisi (VM sulla stessa NIC) mai spostati/uniti/allertati;
    alert 'Scheda di rete cambiata' quando lo stesso IP risponde stabilmente con un MAC diverso."""
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
         "follow_mac": 1, "mac_is_random": 1, "is_vital": 1, "mac_change_pending": 1},
    ).to_list(5000)
    managed_ips: set[str] = set()
    owners: dict[str, list[dict]] = {}
    for md in mds:
        for k in ("ip", "ip_address"):
            if md.get(k):
                managed_ips.add(md[k])
        m = norm_mac(md.get("mac") or md.get("mac_address"))
        if m:
            owners.setdefault(m, []).append(md)
    # anche i device gestiti SENZA MAC occupano il loro IP
    managed_ips |= {d.get("ip") or d.get("ip_address") async for d in db.managed_devices.find(
        {"client_id": client_id, "$or": [{"ip": {"$in": list(ip_macs)}}, {"ip_address": {"$in": list(ip_macs)}}]},
        {"_id": 0, "ip": 1, "ip_address": 1})}
    owned_macs = set(owners)
    changes: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    shared_seen = False
    for mac, group in owners.items():
        group_ips = {g.get("ip") or g.get("ip_address") for g in group} - {None, ""}
        if len(group) > 1 or len(seen.get(mac, set())) > 1:
            shared_seen = True
        for md in group:
            if md.get("follow_mac") is False or md.get("mac_is_random") or _is_laa(mac):
                continue
            cur_ip = md.get("ip") or md.get("ip_address")
            if cur_ip:
                await _check_nic_change(client_id, md, mac, cur_ip, ip_macs, seen, group_ips, owned_macs - {mac}, now)
            # MAC condiviso (piu' device gestiti o piu' IP vivi) → nessuno spostamento
            if len(group) > 1:
                continue
            ips = seen.get(mac)
            if not ips or len(ips) != 1:
                continue
            new_ip = next(iter(ips))
            if new_ip == cur_ip or new_ip in managed_ips:
                continue
            name = md.get("name") or md.get("device_name") or cur_ip or mac.upper()
            first_bind = not cur_ip
            hist = {"from": cur_ip, "to": new_ip, "at": now, "source": source}
            await db.managed_devices.update_one(
                {"id": md["id"]},
                {"$set": {"ip": new_ip, "ip_address": new_ip, "ip_previous": cur_ip, "ip_changed_at": now, "follow_mac": True, "ip_pending": False},
                 "$unset": {"mac_change_pending": ""},
                 "$push": {"ip_history": {"$each": [hist], "$slice": -20}}},
            )
            managed_ips.add(new_ip)
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
                               f"Per fissarlo, assegna una prenotazione DHCP.",
                    "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
                }
            await _emit(alert)
            changes.append({"mac": mac, "old_ip": cur_ip, "new_ip": new_ip, "name": name, "device_id": md["id"]})
            logger.info(f"mac_follow {client_id}: {name} {mac} {cur_ip} -> {new_ip} ({source})")
    if shared_seen:
        await _resolve_shared_noise(client_id, now)
    if changes:
        try:
            from routes.agent_ws import push_config_to_client
            await push_config_to_client(client_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"mac_follow push_config {client_id}: {e}")
    return changes
