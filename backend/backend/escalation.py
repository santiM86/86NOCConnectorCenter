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
    candidates = await db.alerts.find(
        {
            "status": "active",
            "severity": {"$in": severities},
            "escalated": {"$ne": True},
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
