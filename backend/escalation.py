"""
Escalation background job — re-notifica alert critici non ACKed entro N minuti.

Config (singleton doc in db.escalation_config):
{
  "enabled": bool,
  "wait_minutes": 5,
  "severities": ["critical"],
  "escalate_to_roles": ["admin"]
}
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

logger = logging.getLogger("escalation")

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "wait_minutes": 5,
    "severities": ["critical"],
    "escalate_to_roles": ["admin"],
    # --- Regola dedicata agli alert C2 / OSINT (comunicazione con IP malevolo) ---
    "c2_enabled": True,
    "c2_wait_minutes": 10,
    "c2_notify_oncall": True,
    "c2_fallback_roles": ["admin", "operator"],
    # --- Livello 2: se il reperibile non risponde, avvisa un responsabile/manager ---
    "c2_l2_enabled": True,
    "c2_l2_wait_minutes": 10,
    "c2_l2_user_id": "",
    "c2_l2_roles": ["admin"],
}

CHECK_INTERVAL_SECONDS = 60


async def get_config(db) -> Dict[str, Any]:
    doc = await db.escalation_config.find_one({"_id": "singleton"}, {"_id": 0})
    cfg = dict(DEFAULT_CONFIG)
    if doc:
        for k in DEFAULT_CONFIG:
            if k in doc:
                cfg[k] = doc[k]
    return cfg


async def save_config(db, cfg: Dict[str, Any]) -> None:
    await db.escalation_config.update_one(
        {"_id": "singleton"},
        {"$set": cfg},
        upsert=True,
    )


async def _run_once(db) -> int:
    """Run one escalation pass. Returns number of alerts escalated.
    Ottimizzato: usa index composito (status+severity+escalated+created_at),
    query mirata con projection minima, limite a 100 alert per ciclo."""
    cfg = await get_config(db)
    if not cfg.get("enabled"):
        return 0

    wait_minutes = max(1, int(cfg.get("wait_minutes", 5)))
    severities = cfg.get("severities") or ["critical"]
    roles = cfg.get("escalate_to_roles") or ["admin"]

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=wait_minutes)).isoformat()

    # Find candidate alerts (usa index status_1_severity_1_escalated_1_created_at_1)
    # NB: gli alert C2 (source_type=osint_c2) sono ESCLUSI: hanno una regola di
    # escalation dedicata (_run_c2_once) che avvisa direttamente il reperibile.
    candidates = await db.alerts.find(
        {
            "status": "active",
            "severity": {"$in": severities},
            "escalated": {"$ne": True},
            "source_type": {"$ne": "osint_c2"},
            "created_at": {"$lte": cutoff},
            "$or": [
                {"acknowledged_by": None},
                {"acknowledged_by": {"$exists": False}},
                {"acknowledged_by": ""},
            ],
        },
        {"_id": 0},
    ).limit(100).to_list(length=100)

    if not candidates:
        return 0

    try:
        import webpush as wp
    except Exception as e:
        logger.warning(f"[escalation] webpush unavailable: {e}")
        return 0

    escalated = 0
    for alert in candidates:
        # Mark first (idempotent lock)
        result = await db.alerts.update_one(
            {"id": alert["id"], "escalated": {"$ne": True}},
            {
                "$set": {
                    "escalated": True,
                    "escalated_at": now.isoformat(),
                    "escalated_to_roles": roles,
                }
            },
        )
        if result.modified_count == 0:
            continue

        payload = wp.build_alert_payload(alert)
        payload["title"] = f"🔺 ESCALATION · {payload['title']}"
        payload["body"] = (
            f"Alert non riscontrato entro {wait_minutes}min · {payload.get('body','')}"
        )
        payload["tag"] = f"escalation-{alert.get('id','')}"
        try:
            await wp.send_to_roles(
                db, roles, payload,
                log_context={"alert_id": alert.get("id"), "type": "escalation"},
            )
            escalated += 1
            logger.info(
                f"[escalation] Alert {alert.get('id')} ({alert.get('severity')}) "
                f"escalated to roles {roles}"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[escalation] send failed for {alert.get('id')}: {e}")

    return escalated


async def _run_c2_once(db) -> int:
    """Escalation DEDICATA agli alert C2/OSINT: se una comunicazione con un IP
    malevolo noto non viene presa in carico (ACK) entro `c2_wait_minutes`, avvisa
    il reperibile (on-call). Se non c'è nessun reperibile attivo, notifica i ruoli
    di fallback. Restituisce il numero di alert escalati."""
    cfg = await get_config(db)
    if not cfg.get("c2_enabled", True):
        return 0

    wait_minutes = max(1, int(cfg.get("c2_wait_minutes", 10)))
    notify_oncall = bool(cfg.get("c2_notify_oncall", True))
    fallback_roles = cfg.get("c2_fallback_roles") or ["admin", "operator"]

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=wait_minutes)).isoformat()

    candidates = await db.alerts.find(
        {
            "status": "active",
            "source_type": "osint_c2",
            "c2_escalated": {"$ne": True},
            "created_at": {"$lte": cutoff},
            "$or": [
                {"acknowledged_by": None},
                {"acknowledged_by": {"$exists": False}},
                {"acknowledged_by": ""},
            ],
        },
        {"_id": 0},
    ).limit(100).to_list(length=100)

    if not candidates:
        return 0

    try:
        import webpush as wp
    except Exception as e:
        logger.warning(f"[escalation-c2] webpush unavailable: {e}")
        return 0

    # Destinatari: reperibile on-call (se abilitato e presente), altrimenti ruoli di fallback.
    oncall_ids: list[str] = []
    if notify_oncall:
        try:
            from oncall import get_on_call_user_ids
            oncall_ids = await get_on_call_user_ids(db)
        except Exception as e:
            logger.warning(f"[escalation-c2] on-call lookup failed: {e}")

    escalated = 0
    for alert in candidates:
        result = await db.alerts.update_one(
            {"id": alert["id"], "c2_escalated": {"$ne": True}},
            {"$set": {
                "c2_escalated": True,
                "c2_escalated_at": now.isoformat(),
                "c2_escalated_to": ("oncall" if oncall_ids else "roles"),
            }},
        )
        if result.modified_count == 0:
            continue

        payload = wp.build_alert_payload(alert)
        payload["title"] = f"🚨 C2 ESCALATION · {payload.get('title', '')}"
        payload["body"] = (
            f"Comunicazione con IP malevolo NON presa in carico entro {wait_minutes} min. "
            f"Intervenire subito. {payload.get('body', '')}"
        )
        payload["tag"] = f"c2-escalation-{alert.get('id', '')}"
        payload["severity"] = "critical"

        try:
            if oncall_ids:
                sent_any = False
                for uid in oncall_ids:
                    await wp.send_to_user(
                        db, uid, payload,
                        log_context={"alert_id": alert.get("id"), "type": "escalation"},
                    )
                    sent_any = True
                target = f"on-call {oncall_ids}"
                # Fallback difensivo: se on-call non ha subscription, avvisa comunque i ruoli
                if not sent_any:
                    await wp.send_to_roles(db, fallback_roles, payload,
                                           log_context={"alert_id": alert.get("id"), "type": "escalation"})
                    target = f"roles {fallback_roles} (no on-call subs)"
            else:
                await wp.send_to_roles(
                    db, fallback_roles, payload,
                    log_context={"alert_id": alert.get("id"), "type": "escalation"},
                )
                target = f"roles {fallback_roles}"
            escalated += 1
            logger.info(f"[escalation-c2] Alert {alert.get('id')} escalated to {target}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[escalation-c2] send failed for {alert.get('id')}: {e}")

    return escalated


async def _run_c2_l2_once(db) -> int:
    """LIVELLO 2 della catena di escalation C2: se dopo il primo avviso al reperibile
    (`c2_escalated_at`) l'alert C2 resta attivo e non preso in carico per altri
    `c2_l2_wait_minutes`, avvisa un responsabile/manager (utente specifico se
    configurato, altrimenti i ruoli manager di default). Idempotente via `c2_escalated_l2`."""
    cfg = await get_config(db)
    if not cfg.get("c2_l2_enabled", True):
        return 0

    wait_minutes = max(1, int(cfg.get("c2_l2_wait_minutes", 10)))
    mgr_uid = (cfg.get("c2_l2_user_id") or "").strip()
    mgr_roles = cfg.get("c2_l2_roles") or ["admin"]

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=wait_minutes)).isoformat()

    candidates = await db.alerts.find(
        {
            "status": "active",
            "source_type": "osint_c2",
            "c2_escalated": True,
            "c2_escalated_l2": {"$ne": True},
            "c2_escalated_at": {"$lte": cutoff},
            "$or": [
                {"acknowledged_by": None},
                {"acknowledged_by": {"$exists": False}},
                {"acknowledged_by": ""},
            ],
        },
        {"_id": 0},
    ).limit(100).to_list(length=100)

    if not candidates:
        return 0

    try:
        import webpush as wp
    except Exception as e:
        logger.warning(f"[escalation-c2-l2] webpush unavailable: {e}")
        return 0

    escalated = 0
    for alert in candidates:
        result = await db.alerts.update_one(
            {"id": alert["id"], "c2_escalated_l2": {"$ne": True}},
            {"$set": {
                "c2_escalated_l2": True,
                "c2_escalated_l2_at": now.isoformat(),
                "c2_escalated_l2_to": (mgr_uid or ",".join(mgr_roles)),
            }},
        )
        if result.modified_count == 0:
            continue

        payload = wp.build_alert_payload(alert)
        payload["title"] = f"🚨🚨 C2 ESCALATION L2 · {payload.get('title', '')}"
        payload["body"] = (
            f"Il reperibile NON ha preso in carico l'alert C2 entro {wait_minutes} min dal primo avviso. "
            f"Escalation al responsabile. {payload.get('body', '')}"
        )
        payload["tag"] = f"c2-escalation-l2-{alert.get('id', '')}"
        payload["severity"] = "critical"

        try:
            if mgr_uid:
                await wp.send_to_user(
                    db, mgr_uid, payload,
                    log_context={"alert_id": alert.get("id"), "type": "escalation"},
                )
                target = f"manager {mgr_uid}"
            else:
                await wp.send_to_roles(
                    db, mgr_roles, payload,
                    log_context={"alert_id": alert.get("id"), "type": "escalation"},
                )
                target = f"roles {mgr_roles}"
            escalated += 1
            logger.info(f"[escalation-c2-l2] Alert {alert.get('id')} escalated (L2) to {target}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[escalation-c2-l2] send failed for {alert.get('id')}: {e}")

    return escalated


class EscalationScheduler:
    """Background loop invoked from server startup."""

    def __init__(self, db):
        self.db = db
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _loop(self):
        logger.info(
            f"Escalation watchdog started (interval={CHECK_INTERVAL_SECONDS}s)"
        )
        while not self._stop.is_set():
            try:
                await _run_once(self.db)
                await _run_c2_once(self.db)
                await _run_c2_l2_once(self.db)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[escalation] loop error: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
