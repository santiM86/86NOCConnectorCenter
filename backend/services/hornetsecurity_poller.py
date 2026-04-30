"""
Hornetsecurity Backup Polling Scheduler
========================================
APScheduler-based background job that iterates `hornetsecurity_configs` every
minute and triggers a poll for any client whose `poll_interval_minutes` has
elapsed since `last_polled_at`. Each poll respects the global minimum
5-minute Hornetsecurity rate limit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import db
from routes.hornetsecurity_backup import (
    _fetch_backup_report,
    _persist_poll_results,
)
from security import security_manager

logger = logging.getLogger(__name__)


async def hornetsecurity_polling_tick():
    """Eseguito ogni minuto — verifica quali client devono essere pollati."""
    try:
        now = datetime.now(timezone.utc)
        cursor = db.hornetsecurity_configs.find({"enabled": True}, {"_id": 0})
        async for cfg in cursor:
            client_id = cfg["client_id"]
            interval = cfg.get("poll_interval_minutes", 30)
            last_polled = cfg.get("last_polled_at")

            should_poll = False
            if not last_polled:
                should_poll = True
            else:
                try:
                    last_dt = datetime.fromisoformat(
                        str(last_polled).replace("Z", "+00:00")
                    )
                    age_min = (now - last_dt).total_seconds() / 60.0
                    if age_min >= interval:
                        should_poll = True
                except Exception:
                    should_poll = True

            if not should_poll:
                continue

            try:
                api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
                code, body = await _fetch_backup_report(cfg["api_url"], api_key)
                now_iso = now.isoformat()
                if code == 200 and isinstance(body, dict):
                    summary = await _persist_poll_results(client_id, body)
                    await db.hornetsecurity_configs.update_one(
                        {"client_id": client_id},
                        {"$set": {
                            "last_polled_at": now_iso,
                            "last_poll_status": "success",
                            "last_poll_error": None,
                            "last_poll_summary": summary,
                        }},
                    )
                    logger.info(
                        f"[hornetsecurity-poll] client={client_id} "
                        f"workloads={summary['workloads_total']} "
                        f"failed={summary['workloads_failed']}"
                    )
                else:
                    err_msg = f"HTTP {code}: {str(body)[:200]}"
                    await db.hornetsecurity_configs.update_one(
                        {"client_id": client_id},
                        {"$set": {
                            "last_polled_at": now_iso,
                            "last_poll_status": "failed",
                            "last_poll_error": err_msg,
                        }},
                    )
                    logger.warning(
                        f"[hornetsecurity-poll] client={client_id} FAILED: {err_msg}"
                    )
            except Exception as e:
                logger.exception(
                    f"[hornetsecurity-poll] client={client_id} unhandled error: {e}"
                )
    except Exception as e:
        logger.exception(f"[hornetsecurity-poll] tick failed: {e}")
