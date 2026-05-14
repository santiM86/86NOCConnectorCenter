"""
Hornetsecurity Backup Polling Scheduler
========================================
APScheduler tick (1 min) — gestisce due fonti:

1) GLOBAL CONFIG (preferita): `hornetsecurity_global_config` con `_id="global"`.
   Una sola chiamata API copre tutti i tenant Hornetsecurity sotto il partner.
   I dati vengono persistiti senza `client_id` e filtrati a lettura via
   mapping `clients.hornetsecurity_tenants`.

2) PER-CLIENT LEGACY: configurazioni `hornetsecurity_configs` (modalita`
   storica). Ogni cliente ha la sua key. Mantenuta per backward-compat.

Rispetta il rate limit Hornetsecurity (1 req/5min per endpoint), default
30 min, minimo 5 min.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import db
from routes.hornetsecurity_backup import (
    GLOBAL_CONFIG_ID,
    _fetch_backup_report,
    _persist_poll_results,
    _persist_poll_results_global,
)
from security import security_manager

logger = logging.getLogger(__name__)


def _should_poll(cfg: dict, now: datetime) -> bool:
    """True se intervallo scaduto rispetto a last_polled_at."""
    interval = cfg.get("poll_interval_minutes", 30)
    last_polled = cfg.get("last_polled_at")
    if not last_polled:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last_polled).replace("Z", "+00:00"))
        return (now - last_dt).total_seconds() / 60.0 >= interval
    except Exception:
        return True


async def _tick_global(now: datetime) -> None:
    cfg = await db.hornetsecurity_global_config.find_one({"_id": GLOBAL_CONFIG_ID})
    if not cfg or not cfg.get("enabled", True):
        return
    if not _should_poll(cfg, now):
        return

    now_iso = now.isoformat()
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
        code, body = await _fetch_backup_report(cfg["api_url"], api_key)
        if code == 200 and isinstance(body, dict):
            summary = await _persist_poll_results_global(body)
            await db.hornetsecurity_global_config.update_one(
                {"_id": GLOBAL_CONFIG_ID},
                {"$set": {
                    "last_polled_at": now_iso,
                    "last_poll_status": "success",
                    "last_poll_error": None,
                    "last_poll_summary": summary,
                }},
            )
            logger.info(
                f"[hornetsecurity-global-poll] tenants={summary.get('tenants_seen')} "
                f"workloads={summary.get('workloads_total')} "
                f"failed={summary.get('workloads_failed')}"
            )
        else:
            err = f"HTTP {code}: {str(body)[:200]}"
            await db.hornetsecurity_global_config.update_one(
                {"_id": GLOBAL_CONFIG_ID},
                {"$set": {
                    "last_polled_at": now_iso,
                    "last_poll_status": "failed",
                    "last_poll_error": err,
                }},
            )
            logger.warning(f"[hornetsecurity-global-poll] FAILED: {err}")
    except Exception as e:
        logger.exception(f"[hornetsecurity-global-poll] unhandled error: {e}")


async def _tick_per_client(now: datetime) -> None:
    cursor = db.hornetsecurity_configs.find({"enabled": True}, {"_id": 0})
    async for cfg in cursor:
        client_id = cfg["client_id"]
        if not _should_poll(cfg, now):
            continue
        now_iso = now.isoformat()
        try:
            api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
            code, body = await _fetch_backup_report(cfg["api_url"], api_key)
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
                err = f"HTTP {code}: {str(body)[:200]}"
                await db.hornetsecurity_configs.update_one(
                    {"client_id": client_id},
                    {"$set": {
                        "last_polled_at": now_iso,
                        "last_poll_status": "failed",
                        "last_poll_error": err,
                    }},
                )
                logger.warning(f"[hornetsecurity-poll] client={client_id} FAILED: {err}")
        except Exception as e:
            logger.exception(f"[hornetsecurity-poll] client={client_id} error: {e}")


async def hornetsecurity_polling_tick():
    """Eseguito ogni minuto — gestisce sia config globale che per-cliente legacy."""
    try:
        now = datetime.now(timezone.utc)
        await _tick_global(now)
        await _tick_per_client(now)
    except Exception as e:
        logger.exception(f"[hornetsecurity-poll] tick failed: {e}")
