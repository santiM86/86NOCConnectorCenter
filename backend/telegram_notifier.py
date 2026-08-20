"""
Telegram notifier — invio messaggi di alert via Telegram Bot API.

Approccio leggero via httpx (nessuna dipendenza extra), coerente con
notifications.py. Il token e il chat_id sono letti dalla config
dell'Alert Engine (alert_engine_config._id="global") oppure da env
TELEGRAM_BOT_TOKEN come fallback.

Uso principale (dall'Alert Engine):
    from telegram_notifier import send_alert_telegram
    await send_alert_telegram(db, title, message, severity, chat_id=..., token=...)
"""
from __future__ import annotations

import os
import re
import html
import logging
from typing import Optional

import httpx

logger = logging.getLogger("telegram_notifier")

_API_BASE = "https://api.telegram.org/bot{token}/{method}"

_SEVERITY_EMOJI = {
    "critical": "\U0001F6A8",  # 🚨
    "high": "\u26A0\uFE0F",     # ⚠️
    "medium": "\u2139\uFE0F",   # ℹ️
    "low": "\u2705",            # ✅
    "recovery": "\U0001F7E2",   # 🟢
}


def _fmt(title: str, message: str, severity: str,
         client_name: Optional[str] = None, device_name: Optional[str] = None) -> str:
    """Formato standard: sempre <b>NOME CLIENTE</b> in testa, poi
    dispositivo · stato · [SEVERITÀ], quindi l'escalation/messaggio.
    Così si capisce SEMPRE a colpo d'occhio di quale cliente si tratta."""
    emoji = _SEVERITY_EMOJI.get((severity or "medium").lower(), "\U0001F4E2")
    sev_label = (severity or "medium").upper()
    # Pulisci il titolo dai prefissi ridondanti ("CRITICO:", "CRITICAL —", ...)
    raw_title = title or "Alert"
    state = re.sub(r"^\s*(critico|critical|alert|allarme|warning|attenzione)\s*[:\-\u2014]?\s*",
                   "", raw_title, flags=re.IGNORECASE).strip() or raw_title
    cli = html.escape(client_name) if client_name else "Cliente sconosciuto"
    dev = html.escape(device_name) if device_name else ""
    # Riga 1: 🚨 <b>CLIENTE</b> — dispositivo — [SEV]
    head = f"{emoji} <b>{cli}</b>"
    if dev and dev.lower() not in state.lower():
        head += f" \u2014 {dev}"
    head += f" \u2014 [{sev_label}]"
    safe_state = html.escape(state)
    safe_msg = html.escape(message or "")
    parts = [head, safe_state]
    if safe_msg:
        parts.append("")
        parts.append(safe_msg)
    return "\n".join(parts)


async def _resolve_token(db, token: Optional[str]) -> Optional[str]:
    if token:
        return token
    cfg = await db.alert_engine_config.find_one({"_id": "global"}, {"_id": 0, "telegram_bot_token": 1})
    if cfg and cfg.get("telegram_bot_token"):
        return cfg["telegram_bot_token"]
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


async def _resolve_chat_id(db, chat_id: Optional[str]) -> Optional[str]:
    if chat_id:
        return str(chat_id)
    cfg = await db.alert_engine_config.find_one({"_id": "global"}, {"_id": 0, "telegram_chat_id": 1})
    if cfg and cfg.get("telegram_chat_id"):
        return str(cfg["telegram_chat_id"])
    return os.environ.get("TELEGRAM_CHAT_ID") or None


async def send_telegram_text(
    db,
    text: str,
    chat_id: Optional[str] = None,
    token: Optional[str] = None,
    parse_mode: str = "HTML",
) -> dict:
    """Invia testo grezzo. Ritorna {success, ...}. Non solleva eccezioni."""
    tok = await _resolve_token(db, token)
    cid = await _resolve_chat_id(db, chat_id)
    if not tok:
        return {"success": False, "error": "telegram_token_missing"}
    if not cid:
        return {"success": False, "error": "telegram_chat_id_missing"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(
                _API_BASE.format(token=tok, method="sendMessage"),
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            ok = r.status_code == 200 and (r.json() or {}).get("ok", False)
            if not ok:
                logger.warning("telegram send failed: %s %s", r.status_code, r.text[:200])
                return {"success": False, "status": r.status_code, "detail": r.text[:200]}
            return {"success": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("telegram send exception: %s", e)
        return {"success": False, "error": str(e)[:160]}


async def send_alert_telegram(
    db,
    title: str,
    message: str,
    severity: str = "high",
    chat_id: Optional[str] = None,
    token: Optional[str] = None,
    client_name: Optional[str] = None,
    device_name: Optional[str] = None,
) -> dict:
    """Invia un alert formattato su Telegram (sempre con NOME CLIENTE in testa)."""
    return await send_telegram_text(
        db, _fmt(title, message, severity, client_name, device_name),
        chat_id=chat_id, token=token)


async def detect_chats(db, token: Optional[str] = None) -> dict:
    """getUpdates → ritorna gli ultimi chat che hanno scritto al bot,
    cosi' l'admin puo' scegliere il chat_id senza conoscerlo a priori.
    L'utente deve prima inviare un messaggio (es. /start) al bot.
    """
    tok = await _resolve_token(db, token)
    if not tok:
        return {"success": False, "error": "telegram_token_missing"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.get(_API_BASE.format(token=tok, method="getUpdates"))
            if r.status_code != 200:
                return {"success": False, "status": r.status_code, "detail": r.text[:200]}
            data = r.json() or {}
            chats: dict = {}
            for upd in data.get("result", []):
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat") or {}
                cid = chat.get("id")
                if cid is None:
                    continue
                title = chat.get("title") or " ".join(
                    filter(None, [chat.get("first_name"), chat.get("last_name")])
                ) or chat.get("username") or str(cid)
                chats[str(cid)] = {"chat_id": str(cid), "title": title, "type": chat.get("type")}
            return {"success": True, "chats": list(chats.values())}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)[:160]}
