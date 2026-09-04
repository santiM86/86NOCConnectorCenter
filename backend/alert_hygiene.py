"""Igiene allarmi + riepilogo giornaliero Telegram.

1) expire_stale_alerts: auto-risolve gli allarmi MEDIUM/LOW vecchi che non
   rientrano da soli (es. eventi one-shot mai richiusi), così TV e console
   mostrano solo problemi reali attuali. NON tocca critical/high. Chiusura
   silenziosa (nessun messaggio di rientro: è pulizia, non un recovery reale).
   Se la condizione persiste davvero, il poller ricrea l'alert al ciclo dopo.

2) send_daily_summary: una volta al giorno (21:00 Europe/Rome) invia su Telegram
   un riepilogo compatto (aperti oggi / rientrati oggi / durata media), così si
   ha il polso della giornata senza scorrere i singoli messaggi.
"""
import logging
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover
    _TZ = timezone.utc

logger = logging.getLogger("alert_hygiene")

DEFAULT_MEDIUM_MAX_AGE_HOURS = 24


async def _medium_max_age_hours(db) -> int:
    try:
        s = await db.settings.find_one({"key": "alert_hygiene_medium_hours"})
        v = int((s or {}).get("value"))
        return v if v >= 1 else DEFAULT_MEDIUM_MAX_AGE_HOURS
    except Exception:
        return DEFAULT_MEDIUM_MAX_AGE_HOURS


async def expire_stale_alerts(db) -> int:
    """Auto-risolve gli alert medium/low più vecchi della soglia. Ritorna il numero risolti."""
    try:
        hours = await _medium_max_age_hours(db)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        res = await db.alerts.update_many(
            {
                "status": "active",
                "severity": {"$in": ["medium", "low"]},
                "created_at": {"$lt": cutoff},
            },
            {"$set": {
                "status": "resolved",
                "resolved_at": now_iso,
                "resolution_note": f"Auto-scaduto (igiene allarmi: oltre {hours}h senza rientro)",
                "auto_expired": True,
            }},
        )
        n = res.modified_count
        if n:
            logger.info(f"Alert hygiene: auto-risolti {n} alert medium/low oltre {hours}h")
        return n
    except Exception as e:
        logger.error(f"Alert hygiene error: {e}", exc_info=True)
        return 0


def _day_bounds_utc():
    """Inizio/fine della giornata CORRENTE in ora italiana, come iso UTC."""
    now_local = datetime.now(_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    return start_utc.isoformat(), now_local


def _parse(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fmt_minutes(mins: float) -> str:
    mins = int(mins)
    if mins < 1:
        return "meno di 1 min"
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    return f"{h} h {m} min" if m else f"{h} h"


async def send_daily_summary(db) -> bool:
    """Invia su Telegram il riepilogo della giornata (se Telegram è abilitato)."""
    try:
        cfg = await db.alert_engine_config.find_one({"_id": "global"}) or {}
        channels = cfg.get("channels") or ["push"]
        if "telegram" not in channels or not cfg.get("telegram_enabled"):
            logger.info("Daily summary: Telegram disabilitato, salto")
            return False

        start_iso, now_local = _day_bounds_utc()

        opened = await db.alerts.count_documents({"created_at": {"$gte": start_iso}})
        resolved_today = await db.alerts.find(
            {"status": "resolved", "resolved_at": {"$gte": start_iso}},
            {"_id": 0, "created_at": 1, "resolved_at": 1},
        ).to_list(20000)
        n_resolved = len(resolved_today)

        durations = []
        for a in resolved_today:
            c = _parse(a.get("created_at"))
            r = _parse(a.get("resolved_at"))
            if c and r and r >= c:
                durations.append((r - c).total_seconds() / 60.0)
        avg_str = _fmt_minutes(sum(durations) / len(durations)) if durations else "—"

        active_crit = await db.alerts.count_documents({"status": "active", "severity": "critical"})
        active_high = await db.alerts.count_documents({"status": "active", "severity": "high"})

        data_str = now_local.strftime("%d/%m/%Y")
        text = (
            f"📊 <b>Riepilogo giornaliero NOC</b> — {data_str}\n"
            f"────────────────\n"
            f"🔴 Problemi aperti oggi: <b>{opened}</b>\n"
            f"🟢 Rientrati oggi: <b>{n_resolved}</b>\n"
            f"⏱ Durata media disservizio: <b>{avg_str}</b>\n"
            f"────────────────\n"
            f"Attualmente attivi: <b>{active_crit}</b> critici · <b>{active_high}</b> high"
        )

        from telegram_notifier import send_telegram_text
        res = await send_telegram_text(
            db, text,
            chat_id=cfg.get("telegram_chat_id") or None,
            token=cfg.get("telegram_bot_token") or None,
        )
        ok = bool(res.get("success"))
        logger.info(f"Daily summary inviato: {ok} (aperti={opened}, rientrati={n_resolved})")
        return ok
    except Exception as e:
        logger.error(f"Daily summary error: {e}", exc_info=True)
        return False
