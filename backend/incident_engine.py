"""Incidenti investigati: correlazione automatica alert → incidente + indagine AI (cronologia, prove, azioni)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db

logger = logging.getLogger("incident_engine")
MODEL = ("openai", "gpt-5.4")
WINDOW_MIN = 30
SEV_RANK = {"low": 0, "info": 0, "medium": 1, "high": 2, "critical": 3}
SECURITY_SOURCES = ("ueba_", "seclog_", "osint", "shodan", "hornet", "nic_changed", "port_new_vm")
PRIO = {0: "low", 1: "medium", 2: "high", 3: "critical"}

AI_PROMPT = (
    "Sei un analista SOC senior di un MSP italiano. Ricevi un incidente composto da alert correlati (JSON). "
    "Indaga come farebbe un SOC MDR: ricostruisci la cronologia, individua la causa più probabile, distingui fatti da ipotesi, "
    "valuta l'impatto e proponi azioni concrete in ordine di priorità (contenimento → verifica → ripristino → prevenzione). "
    "Non inventare dati che non sono negli alert. Rispondi SOLO con JSON valido: "
    '{"headline": str, "verdict": "vero_positivo"|"probabile"|"falso_positivo"|"da_verificare", "severity": "low"|"medium"|"high"|"critical", '
    '"summary": str, "root_cause": str, "timeline": [{"at": str, "event": str}], "evidence": [str], "impact": str, '
    '"actions": [{"priority": int, "action": str, "why": str}], "confidence": int}'
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_security(a: dict) -> bool:
    st = a.get("source_type") or ""
    return any(st.startswith(p) or p in st for p in SECURITY_SOURCES)


def _group_key(a: dict) -> str:
    return (a.get("ueba_user") or a.get("device_ip") or a.get("device_name") or "?").lower()


async def correlate(now: Optional[datetime] = None) -> int:
    """Raggruppa alert attivi recenti non ancora in un incidente. Regole:
    - 3+ alert sullo stesso device/utente entro 30 min, oppure
    - 2+ alert di sicurezza (UEBA/registro/OSINT) sullo stesso device/utente, oppure
    - 6+ alert dello stesso cliente entro 30 min (ondata)."""
    now = now or _now()
    since = (now - timedelta(minutes=WINDOW_MIN)).isoformat()
    alerts = await db.alerts.find({"created_at": {"$gte": since}, "status": {"$ne": "resolved"}, "incident_id": {"$in": [None, ""]}},
                                  {"_id": 0}).to_list(3000)
    by_client: dict = {}
    for a in alerts:
        if a.get("client_id"):
            by_client.setdefault(a["client_id"], []).append(a)
    created = 0
    for cid, items in by_client.items():
        groups: dict = {}
        for a in items:
            groups.setdefault(_group_key(a), []).append(a)
        used: set = set()
        for key, g in groups.items():
            sec = [a for a in g if _is_security(a)]
            if len(g) >= 3 or len(sec) >= 2:
                await _open_incident(cid, g, f"{key}", "entity")
                used |= {a["id"] for a in g}
                created += 1
        rest = [a for a in items if a["id"] not in used]
        if len(rest) >= 6:
            await _open_incident(cid, rest, "ondata di alert", "burst")
            created += 1
    return created


async def _open_incident(client_id: str, alerts: list[dict], entity: str, kind: str) -> dict:
    alerts = sorted(alerts, key=lambda a: a.get("created_at") or "")
    top = max(SEV_RANK.get(a.get("severity") or "low", 0) for a in alerts)
    existing = await db.incidents.find_one({"client_id": client_id, "auto_entity": entity, "status": {"$in": ["open", "in_progress"]},
                                            "updated_at": {"$gte": (_now() - timedelta(hours=6)).isoformat()}}, {"_id": 0})
    ids = [a["id"] for a in alerts]
    now = _now().isoformat()
    tl = [{"action": "alert", "user": "ARGUS", "timestamp": a.get("created_at"), "note": f"[{a.get('severity')}] {a.get('title')}"} for a in alerts]
    if existing:
        await db.incidents.update_one({"id": existing["id"]}, {"$addToSet": {"alert_ids": {"$each": ids}}, "$push": {"timeline": {"$each": tl}},
                                                              "$set": {"updated_at": now, "priority": PRIO[max(top, SEV_RANK.get(existing.get("priority"), 0))]}})
        inc_id = existing["id"]
    else:
        cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
        first = alerts[0]
        inc_id = str(uuid.uuid4())
        title = (f"Incidente di sicurezza: {entity}" if any(_is_security(a) for a in alerts) else
                 f"Ondata di {len(alerts)} alert" if kind == "burst" else f"Più problemi su {first.get('device_name') or entity}")
        doc = {"id": inc_id, "_id": inc_id, "title": title, "description": f"Creato automaticamente da ARGUS correlando {len(alerts)} alert in {WINDOW_MIN} minuti.",
               "client_id": client_id, "client_name": (cl or {}).get("name", ""), "device_ip": first.get("device_ip", ""),
               "device_name": first.get("device_name", ""), "alert_id": first["id"], "alert_ids": ids, "priority": PRIO[top],
               "status": "open", "assigned_to": "", "created_by": "ARGUS (correlazione)", "created_at": now, "updated_at": now,
               "resolved_at": None, "timeline": [{"action": "created", "user": "ARGUS", "timestamp": now, "note": "Incidente creato dalla correlazione automatica"}] + tl,
               "tags": ["auto", kind], "auto_entity": entity, "source": "auto_correlation"}
        await db.incidents.insert_one(doc)
    await db.alerts.update_many({"id": {"$in": ids}}, {"$set": {"incident_id": inc_id}})
    if top >= 2 and not existing and os.environ.get("EMERGENT_LLM_KEY"):
        _bg.add(asyncio.create_task(_auto_investigate(inc_id)))
    return {"id": inc_id}


_bg: set = set()


async def _auto_investigate(inc_id: str) -> None:
    """Indagine AI in background: non blocca il tick dell'Alert Engine."""
    try:
        await investigate(inc_id, "ARGUS (auto)")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"auto investigate {inc_id}: {e}")
    finally:
        _bg.difference_update({t for t in _bg if t.done()})


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0) if m else raw)


async def investigate(incident_id: str, user: str) -> dict:
    inc = await db.incidents.find_one({"id": incident_id}, {"_id": 0})
    if not inc:
        raise ValueError("Incidente non trovato")
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY non configurata")
    ids = inc.get("alert_ids") or ([inc["alert_id"]] if inc.get("alert_id") else [])
    alerts = await db.alerts.find({"id": {"$in": ids}}, {"_id": 0, "created_at": 1, "severity": 1, "source_type": 1, "title": 1, "message": 1,
                                                       "device_ip": 1, "device_name": 1, "ueba_user": 1, "status": 1}).to_list(200)
    ctx = {"incident": {k: inc.get(k) for k in ("title", "description", "client_name", "device_ip", "device_name", "priority", "created_at")},
           "alerts": sorted(alerts, key=lambda a: a.get("created_at") or "")}
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=api_key, session_id=f"incident-{incident_id}-{uuid.uuid4().hex[:6]}", system_message=AI_PROMPT).with_model(*MODEL)
    raw = await chat.send_message(UserMessage(text=f"Indaga questo incidente.\n\nDATI (JSON):\n{json.dumps(ctx, ensure_ascii=False, default=str)}"))
    raw = raw if isinstance(raw, str) else str(raw)
    try:
        result = _parse_json(raw)
    except Exception:
        result = {"headline": "Risposta AI non strutturata", "summary": raw[:3000], "actions": [], "evidence": [], "timeline": []}
    now = _now().isoformat()
    inv = {"result": result, "at": now, "by": user, "model": f"{MODEL[0]}/{MODEL[1]}", "alerts_analyzed": len(alerts)}
    await db.incidents.update_one({"id": incident_id}, {"$set": {"ai_investigation": inv, "updated_at": now,
                                                                 **({"status": "in_progress"} if inc.get("status") == "open" else {})},
                                                        "$push": {"timeline": {"action": "ai_investigation", "user": user, "timestamp": now,
                                                                               "note": f"Indagine AI: {result.get('headline', '')}"}}})
    return inv
