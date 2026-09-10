"""Telegram anti-intasamento:
- OUTBOX: gli alert dello stesso cliente vengono raggruppati in UN messaggio ogni
  N minuti (default 5). Gli alert hardware "instant" bypassano il raggruppamento.
- AUTO-DELETE: i messaggi (alert + rientro) vengono cancellati dalla chat N minuti
  (default 10) dopo che TUTTI gli alert contenuti sono risolti.
Collezioni: telegram_outbox, telegram_messages."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "ℹ️"}
_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _esc(s: Any) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def record_message(db, res: dict, alert_ids: List[str], kind: str = "alert") -> None:
    """Salva message_id per la cancellazione futura. kind: alert | recovery."""
    if not res or not res.get("success") or not res.get("message_id"):
        return
    await db.telegram_messages.insert_one({
        "id": str(uuid.uuid4()), "chat_id": str(res.get("chat_id")), "message_id": int(res["message_id"]),
        "alert_ids": [a for a in alert_ids if a], "kind": kind,
        "sent_at": _now().isoformat(), "deleted": False,
    })


async def enqueue(db, alert_doc: Dict[str, Any], client_name: Optional[str]) -> None:
    await db.telegram_outbox.insert_one({
        "id": str(uuid.uuid4()),
        "client_id": alert_doc.get("client_id") or "", "client_name": client_name or "—",
        "alert_id": alert_doc.get("id"), "title": alert_doc.get("title", "Alert"),
        "message": alert_doc.get("message", ""), "severity": alert_doc.get("severity", "high"),
        "device_name": alert_doc.get("device_name") or alert_doc.get("device_ip"),
        "queued_at": _now().isoformat(), "sent": False,
    })


def _fmt_batch(client_name: str, items: List[dict]) -> str:
    items = sorted(items, key=lambda i: _SEV_RANK.get(i.get("severity"), 9))
    worst = items[0].get("severity", "high")
    head = f"{_SEV_ICON.get(worst, '⚠️')} <b>{_esc(client_name)}</b> — {len(items)} alert"
    lines = [head, ""]
    for it in items[:25]:
        dev = f" <i>({_esc(it.get('device_name'))})</i>" if it.get("device_name") else ""
        lines.append(f"{_SEV_ICON.get(it.get('severity'), '•')} <b>{_esc(it.get('title'))}</b>{dev}")
        msg = (it.get("message") or "").strip()
        if msg and msg != it.get("title"):
            lines.append(f"   {_esc(msg[:180])}")
    if len(items) > 25:
        lines.append(f"… e altri {len(items) - 25}")
    return "\n".join(lines)


async def flush_outbox(db) -> int:
    """Per ogni cliente con alert in coda: se il più vecchio ha superato la finestra,
    invia UN messaggio con tutti i pending e li marca inviati."""
    try:
        from alert_engine import get_config
        from telegram_notifier import send_telegram_text, send_alert_telegram
        cfg = await get_config(db)
        if not cfg.get("telegram_enabled"):
            return 0
        window = timedelta(minutes=int(cfg.get("telegram_batch_minutes") or 5))
        pending = await db.telegram_outbox.find({"sent": False}, {"_id": 0}).to_list(2000)
        if not pending:
            return 0
        # Alert già rientrati prima dell'invio → scarta (niente rumore per flap brevi)
        aids = [p["alert_id"] for p in pending if p.get("alert_id")]
        resolved = {d["id"] async for d in db.alerts.find(
            {"id": {"$in": aids}, "status": {"$ne": "active"}}, {"_id": 0, "id": 1})} if aids else set()
        if resolved:
            await db.telegram_outbox.delete_many({"alert_id": {"$in": list(resolved)}, "sent": False})
            pending = [p for p in pending if p.get("alert_id") not in resolved]
        if not pending:
            return 0
        by_client: Dict[str, List[dict]] = {}
        for p in pending:
            by_client.setdefault(p.get("client_id") or p.get("client_name") or "-", []).append(p)
        sent = 0
        now = _now()
        for _cid, items in by_client.items():
            oldest = min(datetime.fromisoformat(i["queued_at"]) for i in items)
            if now - oldest < window:
                continue
            client_name = items[0].get("client_name") or "—"
            chat_id = cfg.get("telegram_chat_id") or None
            token = cfg.get("telegram_bot_token") or None
            if len(items) == 1:
                it = items[0]
                res = await send_alert_telegram(db, title=it["title"], message=it.get("message", ""),
                                                severity=it.get("severity", "high"), chat_id=chat_id, token=token,
                                                client_name=client_name, device_name=it.get("device_name"))
            else:
                res = await send_telegram_text(db, _fmt_batch(client_name, items), chat_id=chat_id, token=token)
            ids = [i["id"] for i in items]
            if res.get("success"):
                await record_message(db, res, [i.get("alert_id") for i in items], kind="alert")
                await db.telegram_outbox.update_many({"id": {"$in": ids}}, {"$set": {"sent": True, "sent_at": now.isoformat()}})
                sent += 1
            else:
                # errore permanente (token/chat mancanti) → non ritentare all'infinito
                if res.get("error") in ("telegram_token_missing", "telegram_chat_id_missing"):
                    await db.telegram_outbox.update_many({"id": {"$in": ids}}, {"$set": {"sent": True, "error": res.get("error")}})
        if sent:
            logger.info("[telegram] outbox: %d messaggi raggruppati inviati", sent)
        return sent
    except Exception as e:  # noqa: BLE001
        logger.error("telegram outbox flush error: %s", e, exc_info=True)
        return 0


async def autodelete_resolved(db) -> int:
    """Cancella dalla chat i messaggi i cui alert sono TUTTI risolti da >= N minuti
    (e i messaggi di rientro dopo N minuti dall'invio)."""
    try:
        from alert_engine import get_config
        from telegram_notifier import delete_telegram_message
        cfg = await get_config(db)
        mins = int(cfg.get("telegram_autodelete_resolved_minutes") or 0)
        if mins <= 0:
            return 0
        cutoff = _now() - timedelta(minutes=mins)
        # Telegram: il bot può cancellare solo entro 48h
        too_old = (_now() - timedelta(hours=47)).isoformat()
        msgs = await db.telegram_messages.find({"deleted": False, "sent_at": {"$gte": too_old}}, {"_id": 0}).to_list(2000)
        n = 0
        for m in msgs:
            ok_to_delete = False
            if m.get("kind") == "recovery":
                ok_to_delete = datetime.fromisoformat(m["sent_at"]) <= cutoff
            else:
                ids = m.get("alert_ids") or []
                if not ids:
                    continue
                docs = await db.alerts.find({"id": {"$in": ids}}, {"_id": 0, "status": 1, "resolved_at": 1}).to_list(len(ids))
                if len(docs) < len(ids):
                    continue
                if all(d.get("status") == "resolved" for d in docs):
                    last = max((d.get("resolved_at") or "") for d in docs)
                    try:
                        ok_to_delete = datetime.fromisoformat(last) <= cutoff
                    except ValueError:
                        ok_to_delete = False
            if not ok_to_delete:
                continue
            if await delete_telegram_message(db, m["chat_id"], m["message_id"], token=cfg.get("telegram_bot_token") or None):
                await db.telegram_messages.update_one({"id": m["id"]}, {"$set": {"deleted": True, "deleted_at": _now().isoformat()}})
                n += 1
        # pulizia record vecchi (>3 giorni)
        await db.telegram_messages.delete_many({"sent_at": {"$lt": (_now() - timedelta(days=3)).isoformat()}})
        await db.telegram_outbox.delete_many({"sent": True, "queued_at": {"$lt": (_now() - timedelta(days=2)).isoformat()}})
        if n:
            logger.info("[telegram] auto-delete: %d messaggi rimossi (alert rientrati)", n)
        return n
    except Exception as e:  # noqa: BLE001
        logger.error("telegram autodelete error: %s", e, exc_info=True)
        return 0


async def tick(db) -> None:
    await flush_outbox(db)
    await autodelete_resolved(db)
