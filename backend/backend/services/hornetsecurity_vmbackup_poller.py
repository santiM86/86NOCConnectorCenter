"""Hornetsecurity VM Backup polling tick (schedulato ogni minuto, rispetta
l'intervallo configurato di default 10 min)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import db
from routes.hornetsecurity_vmbackup import (
    GLOBAL_CONFIG_ID,
    _fetch_vmbackup_report,
    _persist_vmbackup_poll,
)
from security import security_manager

logger = logging.getLogger(__name__)


def _should_poll(cfg: dict, now: datetime) -> bool:
    interval = cfg.get("polling_interval_minutes", 10)
    last = cfg.get("last_polled_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        return (now - last_dt).total_seconds() / 60.0 >= interval
    except Exception:
        return True


async def run_vmbackup_tick(force: bool = False) -> dict:
    """Esegue un tick di polling. Se force=True ignora l'intervallo.

    Ritorna il summary delle VM processate (o {} se non configurato/skip).
    """
    now = datetime.now(timezone.utc)
    cfg = await db.hornetsecurity_vmbackup_config.find_one({"_id": GLOBAL_CONFIG_ID})
    if not cfg:
        return {"error": "Configurazione non presente. Vai in Settings e clicca Configura."}
    if not force and not cfg.get("enabled", True):
        return {}
    if not force and not _should_poll(cfg, now):
        return {}
    if not cfg.get("api_key_enc") or not cfg.get("user_id"):
        return {"error": "API key o User ID mancanti nella configurazione."}
    now_iso = now.isoformat()
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
        code, body = await _fetch_vmbackup_report(cfg["api_url"], api_key, cfg["user_id"])
        if code == 200 and isinstance(body, dict) and body.get("success"):
            summary = await _persist_vmbackup_poll(body)
            await db.hornetsecurity_vmbackup_config.update_one(
                {"_id": GLOBAL_CONFIG_ID},
                {"$set": {
                    "last_polled_at": now_iso,
                    "last_poll_status": "success",
                    "last_poll_error": None,
                    "last_poll_summary": summary,
                }},
            )
            logger.info(
                f"[vmbackup-poll] customers={summary.get('customers')} "
                f"vms={summary.get('vms')} failed={summary.get('failed')} "
                f"warning={summary.get('warning')} stale={summary.get('stale')}"
            )
            return summary
        else:
            err = f"HTTP {code}: {str(body)[:200]}"
            await db.hornetsecurity_vmbackup_config.update_one(
                {"_id": GLOBAL_CONFIG_ID},
                {"$set": {
                    "last_polled_at": now_iso,
                    "last_poll_status": "failed",
                    "last_poll_error": err,
                }},
            )
            logger.warning(f"[vmbackup-poll] FAILED: {err}")
            return {"error": err}
    except Exception as e:
        logger.exception(f"[vmbackup-poll] exception: {e}")
        return {"error": str(e)}


async def vmbackup_polling_tick():
    try:
        await run_vmbackup_tick(force=False)
    except Exception as e:
        logger.exception(f"[vmbackup-poll] tick failed: {e}")
