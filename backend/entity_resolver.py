"""
Entity Resolution — CMDB unificata (Argus Center)
==================================================
Fonde le fonti (managed_devices, device_poll_status, managed_agents, Datto,
telemetria iLO, cmdb_assets manuali) in UN'unica entita' asset con identita'
stabile, indipendente dall'IP.

Chiavi d'identita' (priorita'): serial -> mac -> datto_uid -> agent_id ->
hostname(client) -> ip(client). Le chiavi osservate sono mappate in
`cmdb_identity_keys` -> entity_id, cosi' un asset resta lo stesso anche se
cambia IP e viene riconosciuto da qualunque fonte.

Collezioni: cmdb_entities, cmdb_identity_keys.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("entity_resolver")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_mac(v) -> Optional[str]:
    if not v or not isinstance(v, str):
        return None
    m = v.strip().lower().replace("-", ":")
    return m if len(m) >= 11 and ":" in m else None


async def _collect_units(db, client_id: str) -> List[Dict[str, Any]]:
    """Costruisce le 'unita' asset (una per IP monitorato) fondendo le fonti."""
    units: Dict[str, Dict[str, Any]] = {}

    # agenti del cliente: indicizza per IP e per hostname
    agents = await db.managed_agents.find(
        {"client_id": client_id}, {"_id": 0}).to_list(2000)
    agent_by_ip: Dict[str, dict] = {}
    for a in agents:
        for ip in (a.get("ips") or []):
            agent_by_ip[ip] = a

    mds = await db.managed_devices.find({"client_id": client_id}, {"_id": 0}).to_list(20000)
    for md in mds:
        ip = md.get("ip") or md.get("ip_address")
        if not ip:
            continue
        u = units.setdefault(ip, {"ip": ip, "keys": {}, "sources": set(), "attrs": {}})
        u["sources"].add("monitoring")
        name = md.get("name") or md.get("device_name")
        u["attrs"].update({
            "name": name, "device_type": md.get("device_type") or md.get("device_class"),
            "is_vital": md.get("is_vital"), "virtualization": md.get("virtualization"),
            "hyperv_vm_name": md.get("hyperv_vm_name"), "managed_device_id": md.get("id"),
        })
        if name:
            u["keys"]["hostname"] = str(name).strip().lower()
        if md.get("datto_uid"):
            u["keys"]["datto_uid"] = md["datto_uid"]
            u["sources"].add("datto")
            u["attrs"]["datto_name"] = md.get("datto_name")
        ag = agent_by_ip.get(ip)
        if ag:
            u["keys"]["agent_id"] = ag.get("agent_id")
            u["sources"].add("agent")
            u["attrs"]["agent_hostname"] = ag.get("hostname")
            u["attrs"]["agent_os"] = ag.get("os")

    # device_poll_status: monitor_type / class + eventuali mac/serial
    async for pd in db.device_poll_status.find({"client_id": client_id}, {"_id": 0}):
        ip = pd.get("device_ip")
        if not ip:
            continue
        u = units.setdefault(ip, {"ip": ip, "keys": {}, "sources": set(), "attrs": {}})
        if pd.get("monitor_type") == "snmp":
            u["sources"].add("snmp")
        u["attrs"].setdefault("name", pd.get("device_name"))
        u["attrs"].setdefault("device_type", pd.get("device_class"))
        mac = _norm_mac(pd.get("mac"))
        if mac:
            u["keys"]["mac"] = mac
        if pd.get("serial_number"):
            u["keys"]["serial"] = str(pd["serial_number"]).strip()

    # telemetria iLO/Redfish: serial + modello (fonte forte per il serial)
    async for t in db.ilo_telemetry.find({"client_id": client_id}, {"_id": 0}):
        ip = t.get("device_ip")
        if not ip or ip not in units:
            continue
        u = units[ip]
        u["sources"].add("ilo")
        if t.get("serial_number"):
            u["keys"]["serial"] = str(t["serial_number"]).strip()
        u["attrs"].setdefault("model", t.get("model"))
        u["attrs"].setdefault("vendor", t.get("manufacturer") or t.get("vendor"))

    # anagrafica manuale CMDB (garanzie, owner, sede, serial inserito a mano)
    async for a in db.cmdb_assets.find(
        {"$or": [{"client_id": client_id}, {"client_id": {"$exists": False}}]}, {"_id": 0}
    ):
        ip = a.get("ip_address") or a.get("device_ip")
        if not ip:
            continue
        manual = {k: a.get(k) for k in (
            "serial_number", "asset_tag", "model", "vendor", "owner", "site",
            "building", "rack", "rack_unit", "cost_monthly", "warranty_expiry",
            "purchase_date", "lifecycle", "notes") if a.get(k) is not None}
        if ip in units:
            u = units[ip]
        elif a.get("client_id") == client_id:
            # asset manuale ORFANO (IP non monitorato): crea comunque un'entita'
            u = units[ip] = {"ip": ip, "keys": {}, "sources": set(), "attrs": {}}
            u["attrs"]["name"] = a.get("hostname") or ip
            u["attrs"]["device_type"] = a.get("device_type")
        else:
            continue  # senza client_id e IP non monitorato: non attribuibile
        u["sources"].add("cmdb_manual")
        u["manual"] = manual
        if a.get("serial_number"):
            u["keys"].setdefault("serial", str(a["serial_number"]).strip())
        if a.get("hostname") and not u["attrs"].get("name"):
            u["attrs"]["name"] = a.get("hostname")

    for u in units.values():
        u["keys"]["ip"] = f"{client_id}:{u['ip']}"
        if u["keys"].get("hostname"):
            u["keys"]["hostname"] = f"{client_id}:{u['keys']['hostname']}"
        u["sources"] = sorted(u["sources"])
    return list(units.values())


# Ordine di priorita' delle chiavi forti per il match trasversale
_STRONG = ["serial", "mac", "datto_uid", "agent_id", "hostname", "ip"]


async def _resolve_entity_id(db, client_id: str, keys: Dict[str, str]) -> str:
    """Trova l'entity_id esistente da una qualunque chiave nota; se piu' entita'
    combaciano le fonde nella piu' vecchia; altrimenti ne crea una nuova."""
    found: Dict[str, str] = {}
    for ktype in _STRONG:
        kval = keys.get(ktype)
        if not kval:
            continue
        doc = await db.cmdb_identity_keys.find_one(
            {"client_id": client_id, "key_type": ktype, "key_value": str(kval)},
            {"_id": 0, "entity_id": 1})
        if doc:
            found[doc["entity_id"]] = doc["entity_id"]
    if not found:
        return str(uuid.uuid4())
    ids = list(found)
    if len(ids) == 1:
        return ids[0]
    # merge: sopravvive l'entita' piu' vecchia
    ents = await db.cmdb_entities.find(
        {"entity_id": {"$in": ids}}, {"_id": 0, "entity_id": 1, "created_at": 1}
    ).to_list(100)
    ents.sort(key=lambda e: e.get("created_at") or "")
    survivor = ents[0]["entity_id"]
    losers = [i for i in ids if i != survivor]
    if losers:
        await db.cmdb_identity_keys.update_many(
            {"entity_id": {"$in": losers}}, {"$set": {"entity_id": survivor}})
        await db.cmdb_entities.delete_many({"entity_id": {"$in": losers}})
    return survivor


async def reconcile_client(db, client_id: str) -> int:
    units = await _collect_units(db, client_id)
    now = _now()
    touched: List[str] = []
    for u in units:
        keys = {k: v for k, v in u["keys"].items() if v}
        entity_id = await _resolve_entity_id(db, client_id, keys)
        touched.append(entity_id)
        doc = {
            "entity_id": entity_id, "client_id": client_id,
            "primary_ip": u["ip"], "name": u["attrs"].get("name") or u["ip"],
            "device_type": u["attrs"].get("device_type"),
            "is_vital": bool(u["attrs"].get("is_vital")),
            "sources": u["sources"], "identity": keys,
            "attrs": u["attrs"], "manual": u.get("manual", {}),
            "updated_at": now,
        }
        await db.cmdb_entities.update_one(
            {"entity_id": entity_id},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        for ktype, kval in keys.items():
            await db.cmdb_identity_keys.update_one(
                {"client_id": client_id, "key_type": ktype, "key_value": str(kval)},
                {"$set": {"entity_id": entity_id, "updated_at": now}},
                upsert=True,
            )
    # Pruning: rimuove le entita' stale del cliente non piu' viste in questo giro
    # (device eliminati da managed_devices) per evitare drift dell'inventario.
    if touched:
        await db.cmdb_entities.delete_many(
            {"client_id": client_id, "entity_id": {"$nin": touched}})
        await db.cmdb_identity_keys.delete_many(
            {"client_id": client_id, "entity_id": {"$nin": touched}})
    return len(units)


async def reconcile_all(db) -> Dict[str, int]:
    try:
        await db.cmdb_identity_keys.create_index(
            [("client_id", 1), ("key_type", 1), ("key_value", 1)], unique=True)
        await db.cmdb_entities.create_index([("client_id", 1), ("entity_id", 1)])
    except Exception:  # noqa: BLE001
        pass
    out: Dict[str, int] = {}
    clients = await db.clients.find({}, {"_id": 0, "id": 1}).to_list(5000)
    for c in clients:
        cid = c.get("id")
        if not cid:
            continue
        try:
            out[cid] = await reconcile_client(db, cid)
        except Exception as e:  # noqa: BLE001
            logger.warning("reconcile_client %s failed: %s", cid, e)
    return out
