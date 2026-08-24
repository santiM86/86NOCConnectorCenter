"""
Vital Freshness Watchdog — garantisce dati SEMPRE freschi sui dispositivi VITALI.

Problema che risolve: un device vitale puo' smettere di ricevere polling fresco
(es. switch cross-subnet scartato dal dispatcher, config non ripushata, ecc.),
restando "verde per inerzia" su un vecchio poll-record. In quel caso non abbiamo
dati attuali e lo stato up/down non e' verificabile in modo diretto.

Due azioni per ogni ciclo (default ogni 2 min), SOLO sui vitali di clienti con
una sonda (agent) ONLINE — se la sonda e' giu' e' un blackout, gestito altrove:

  1. AUTO-RIPARAZIONE: se il poll del vitale e' piu' vecchio di `repoll_after_min`,
     invia un re-poll FORZATO diretto all'agent online (bypassa la subnet-dispatch
     logic, come /api/admin/snmp-poll-now). Cosi' il dato torna fresco da solo.

  2. SENTINELLA: se il poll resta piu' vecchio di `stale_after_min`, emette un
     alert `monitoring_stale` (dedup + auto-resolve) → "sappiamo quando NON sappiamo".

Config (db.settings key "vital_freshness_config"):
  enabled, stale_after_min, repoll_after_min, repoll, alert
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("vital_freshness")

SETTINGS_KEY = "vital_freshness_config"
DEFAULT_CONFIG = {
    "enabled": True,
    "stale_after_min": 15,    # oltre questo → alert "monitoraggio non aggiornato"
    "repoll_after_min": 3,    # (se always_repoll=False) oltre questo → re-poll forzato
    "repoll": True,
    "always_repoll": True,    # RIPOLL FORZATO DI TUTTI I VITALI OGNI CICLO (2 min)
    "alert": True,
}


async def get_config() -> dict:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    cfg = dict(DEFAULT_CONFIG)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


async def set_config(patch: dict) -> dict:
    cfg = await get_config()
    for k in DEFAULT_CONFIG:
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"key": SETTINGS_KEY, "value": cfg,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return cfg


def _age_min(ts) -> float:
    """Eta' in minuti di un timestamp ISO; None/invalid → molto vecchio (1e9)."""
    if not ts:
        return 1e9
    try:
        if isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


async def _force_repoll(client_id: str, ip: str, community: str) -> bool:
    """Invia force_snmp_poll diretto all'agent online del cliente (bypass dispatcher)."""
    try:
        from routes.agent_ws import REGISTRY
    except Exception:
        return False
    candidates = [c for c in REGISTRY.list() if c.client_id == client_id]
    if not candidates:
        return False
    chosen = None
    for c in candidates:
        ag = await db.managed_agents.find_one({"agent_id": c.agent_id}, {"_id": 0, "role": 1})
        if ag and (ag.get("role") or "master").lower() == "master":
            chosen = c
            break
    chosen = chosen or candidates[0]
    try:
        await chosen.send_command("force_snmp_poll", {"ip": ip, "community": community or "public"}, timeout=12.0)
        return True
    except Exception as e:
        logger.debug("force_repoll %s/%s failed: %s", client_id, ip, e)
        return False


async def scan_all() -> dict:
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"skipped": True}

    stale_after = float(cfg["stale_after_min"])
    repoll_after = float(cfg["repoll_after_min"])
    do_repoll = bool(cfg.get("repoll", True))
    always_repoll = bool(cfg.get("always_repoll", True))
    do_alert = bool(cfg.get("alert", True))
    now = datetime.now(timezone.utc)

    # Clienti SENZA sonda online → blackout, non "monitoraggio stale": li saltiamo.
    from liveness_resolver import build_clients_without_online_agent
    offline_clients = await build_clients_without_online_agent(db)

    # Vitali gestiti
    vitals = await db.managed_devices.find(
        {"is_vital": True, "ip": {"$ne": None}},
        {"_id": 0, "client_id": 1, "ip": 1, "name": 1, "community": 1,
         "snmp_community": 1, "device_type": 1, "last_seen_at": 1},
    ).to_list(3000)
    if not vitals:
        return {"vitals": 0}

    # Ultimo poll per (client, ip)
    poll_by_key = {}
    async for pd in db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "device_ip": 1, "last_poll": 1, "last_update": 1}):
        poll_by_key[(pd.get("client_id"), pd.get("device_ip"))] = pd

    client_names = {c["id"]: c["name"] for c in
                    await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)}

    repolled = 0
    alerted = 0
    resolved = 0
    checked = 0
    repoll_targets = []  # (cid, ip, community)
    for v in vitals:
        cid = v.get("client_id"); ip = v.get("ip")
        if not cid or not ip:
            continue
        # Salta clienti senza sonda online (blackout, non monitoring gap)
        if cid in offline_clients:
            continue
        checked += 1
        pd = poll_by_key.get((cid, ip)) or {}
        last_poll = pd.get("last_poll") or pd.get("last_update")
        age = _age_min(last_poll)

        # RIPOLL FORZATO: se always_repoll → TUTTI i vitali ogni ciclo (2 min),
        # per avere lo stato sempre in diretta; altrimenti solo quelli stale.
        if do_repoll and (always_repoll or age >= repoll_after):
            repoll_targets.append((cid, ip, v.get("community") or v.get("snmp_community")))

        dedup = f"monstale:{cid}:{ip}"
        existing = await db.alerts.find_one({"dedup_key": dedup, "status": "active"}, {"_id": 0, "id": 1})

        if age <= stale_after:
            # Fresco → risolvi eventuale alert stale
            if existing:
                await db.alerts.update_one(
                    {"id": existing["id"]},
                    {"$set": {"status": "resolved", "resolved_at": now.isoformat(),
                              "resolution_note": "Monitoraggio tornato aggiornato."}})
                resolved += 1
            continue

        # Alert solo oltre la soglia piu' alta (dopo che il nudge ha avuto tempo)
        if do_alert and age >= stale_after and not existing:
            name = v.get("name") or ip
            cname = client_names.get(cid, "")
            age_txt = "mai" if age >= 1e8 else f"{int(age)} min"
            alert = {
                "id": str(uuid.uuid4()),
                "client_id": cid,
                "device_ip": ip,
                "device_name": name,
                "device_type": v.get("device_type") or "network",
                "severity": "medium",
                "source_type": "monitoring_stale",
                "dedup_key": dedup,
                "title": f"Monitoraggio non aggiornato: {name}",
                "message": (f"Cliente {cname}: non riceviamo dati freschi dal dispositivo VITALE "
                            f"'{name}' ({ip}) da {age_txt}, pur essendo la sonda del cliente ONLINE. "
                            f"Le metriche non sono attuali e lo stato up/down non e' verificabile in "
                            f"modo diretto. Il sistema sta gia' tentando un re-poll forzato automatico."),
                "status": "active",
                "created_at": now.isoformat(),
                "last_poll_age_min": None if age >= 1e8 else int(age),
            }
            if await insert_alert_if_emit(db, alert):
                alerted += 1
                try:
                    from alert_engine import notify_alert_telegram
                    await notify_alert_telegram(db, alert)
                except Exception:
                    pass

    # RIPOLL FORZATO concorrente (a blocchi) su TUTTI i vitali raccolti.
    if repoll_targets:
        import asyncio
        CHUNK = 12
        for i in range(0, len(repoll_targets), CHUNK):
            batch = repoll_targets[i:i + CHUNK]
            results = await asyncio.gather(
                *[_force_repoll(c, p, comm) for (c, p, comm) in batch],
                return_exceptions=True)
            repolled += sum(1 for r in results if r is True)

    if repolled or alerted or resolved:
        logger.info("[vital-freshness] checked=%s repolled=%s/%s alerted=%s resolved=%s",
                    checked, repolled, len(repoll_targets), alerted, resolved)
    return {"checked": checked, "repolled": repolled, "repoll_targets": len(repoll_targets),
            "alerted": alerted, "resolved": resolved}
