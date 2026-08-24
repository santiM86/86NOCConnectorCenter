"""
Pre-Alarm (C) — avviso "soft" precoce sui dispositivi VITALI che stanno
fallendo, PRIMA dell'allarme pieno (debounce). Da' all'operatore un anticipo:
  - dopo ~90s di fallimenti  → PRE-ALLARME (severity low)
  - dopo ~120s (debounce vitale) → allarme pieno (gestito dal motore alert)

Gira ogni 1 min. Salta i clienti senza sonda online (blackout). Auto-risolve il
pre-allarme quando il device torna su O quando scatta il down confermato.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from database import db
from alert_filter import insert_alert_if_emit
from liveness_resolver import down_phase, build_clients_without_online_agent

logger = logging.getLogger("pre_alarm")


async def scan_all() -> dict:
    now = datetime.now(timezone.utc)
    offline_clients = await build_clients_without_online_agent(db)
    vitals = await db.managed_devices.find(
        {"is_vital": True, "ip": {"$ne": None}},
        {"_id": 0, "client_id": 1, "ip": 1, "name": 1, "device_type": 1},
    ).to_list(3000)
    if not vitals:
        return {"vitals": 0}

    poll = {}
    async for pd in db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "device_ip": 1, "reachable": 1,
             "consecutive_failures": 1, "last_reachable_at": 1}):
        poll[(pd.get("client_id"), pd.get("device_ip"))] = pd

    names = {c["id"]: c["name"] for c in
             await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)}

    emitted = resolved = 0
    for v in vitals:
        cid = v.get("client_id"); ip = v.get("ip")
        if not cid or not ip or cid in offline_clients:
            continue
        phase = down_phase(poll.get((cid, ip)), is_vital=True)
        dedup = f"prealarm:{cid}:{ip}"
        existing = await db.alerts.find_one({"dedup_key": dedup, "status": "active"}, {"_id": 0, "id": 1})
        if phase == "prealarm":
            if existing:
                continue
            name = v.get("name") or ip
            alert = {
                "id": str(uuid.uuid4()), "client_id": cid, "device_ip": ip,
                "device_name": name, "device_type": v.get("device_type") or "network",
                "severity": "low", "source_type": "pre_down_warning", "dedup_key": dedup,
                "title": f"PRE-ALLARME: {name} non risponde",
                "message": (f"Cliente {names.get(cid,'')}: il dispositivo VITALE '{name}' ({ip}) "
                            f"non risponde da ~1-2 minuti. NON ancora confermato down (anti-flap): "
                            f"potrebbe essere un blip transitorio. Se persiste scatta l'allarme pieno."),
                "status": "active", "created_at": now.isoformat(),
            }
            if await insert_alert_if_emit(db, alert):
                emitted += 1
                try:
                    from alert_engine import notify_alert_telegram
                    await notify_alert_telegram(db, alert)
                except Exception:
                    pass
        elif existing:
            # tornato su ("ok") o passato a down confermato → chiudi il pre-allarme
            note = "Device tornato raggiungibile." if phase == "ok" else "Escalato ad allarme pieno (down confermato)."
            await db.alerts.update_one(
                {"id": existing["id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat(), "resolution_note": note}})
            resolved += 1

    if emitted or resolved:
        logger.info("[pre-alarm] emitted=%s resolved=%s", emitted, resolved)
    return {"vitals": len(vitals), "emitted": emitted, "resolved": resolved}
