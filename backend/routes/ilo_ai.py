"""Analisi AI dei log hardware iLO/Redfish (IML/SEL) con contesto hardware live.

- POST /api/servers/ilo-ai-analysis/{ip}?client_id=  → esegue l'analisi (GPT-5.4 via Universal Key), salva in `ilo_ai_analyses`
- GET  /api/servers/ilo-ai-analysis/{ip}?client_id=   → ultima analisi + storico (10)
- `maybe_auto_analyze(...)`: chiamata quando la cache eventi riceve NUOVI eventi critici/warning non riparati
  → analisi automatica (debounce 6h per device) + Telegram se rischio high/critical.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user, require_admin

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/servers", tags=["ilo-ai"])

MODEL = ("openai", "gpt-5.4")
AUTO_DEBOUNCE_H = 6
_auto_running: set = set()

SYSTEM_PROMPT = """Sei un ingegnere senior di supporto hardware server (HPE ProLiant/iLO, Dell iDRAC, Lenovo XCC) che lavora in un NOC di un MSP italiano.
Ricevi il log eventi hardware (IML/SEL) di un server, lo stato live dei sensori e gli alert attivi. Devi produrre consigli concreti e prioritizzati per il tecnico.
Regole:
- Rispondi SOLO con JSON valido (nessun testo fuori dal JSON), in italiano.
- Sii specifico: cita slot, porta, DIMM, bay, PSU, date e ricorrenze.
- Distingui ciò che è già riparato/rientrato (rumore) da ciò che richiede azione.
- Cerca pattern temporali (stessa ora, stessi giorni), degradi progressivi, componenti ricorrenti.
- Non inventare dati non presenti. Se il log è pulito dillo.
Schema JSON:
{
 "risk_level": "ok|low|medium|high|critical",
 "headline": "una frase (max 120 caratteri) con il messaggio più importante",
 "diagnosis": "2-5 frasi: cosa sta succedendo al server",
 "patterns": [{"title": "...", "detail": "...", "occurrences": 0}],
 "actions": [{"priority": 1, "action": "...", "why": "...", "component": "...", "when": "subito|entro 7 giorni|prossima manutenzione"}],
 "ignore": ["voci di log che sono rumore e perché"],
 "watch": ["cosa monitorare nei prossimi giorni"],
 "confidence": 0-100
}"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _context(client_id: str, ip: str, limit: int = 100) -> dict:
    q = {"device_ip": ip, "client_id": client_id}
    cache = await db.ilo_events.find_one(q, {"_id": 0}) or {}
    events = (cache.get("events") or [])[:limit]
    if not events:
        # nessuna cache: prova il canale diretto
        try:
            from routes.server_intelligence import fetch_redfish_log_entries, store_ilo_events_cache
            from security import security_manager
            cred = await db.device_credentials.find_one(
                {"device_ip": ip, "client_id": client_id, "credential_type": {"$in": ["ilo", "redfish", "idrac", "bmc"]}}, {"_id": 0})
            if cred:
                u = security_manager.decrypt_credential(cred["username_enc"])
                p = security_manager.decrypt_credential(cred["password_enc"])
                base = (cred.get("external_url") or "").rstrip("/") or f"https://{ip}:{cred.get('port') or 443}"
                events, path = await fetch_redfish_log_entries(base, (u, p), limit)
                if path:
                    await store_ilo_events_cache(client_id, ip, events, path, "direct")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ilo-ai: fetch diretto fallito {ip}: {e}")
    ilo = await db.ilo_status.find_one(q, {"_id": 0}) or await db.ilo_status.find_one({"device_ip": ip}, {"_id": 0}) or {}
    md = await db.managed_devices.find_one({"client_id": client_id, "$or": [{"ip": ip}, {"ip_address": ip}]}, {"_id": 0, "name": 1, "hostname": 1}) or {}
    alerts = [a async for a in db.alerts.find(
        {"client_id": client_id, "device_ip": ip, "status": {"$in": ["active", "acknowledged"]}},
        {"_id": 0, "title": 1, "severity": 1, "source_type": 1, "created_at": 1}).sort("created_at", -1).limit(15)]
    poll = await db.device_poll_status.find_one({"client_id": client_id, "device_ip": ip}, {"_id": 0, "redfish": 1}) or {}
    rf = poll.get("redfish") or {}

    def trim(lst, n, keys):
        return [{k: x.get(k) for k in keys if x.get(k) is not None} for x in (lst or [])[:n] if isinstance(x, dict)]

    hw = {
        "model": ilo.get("server_model") or rf.get("server_model"),
        "serial": ilo.get("serial_number") or rf.get("serial_number"),
        "bios": ilo.get("bios_version") or rf.get("bios_version"),
        "ilo_firmware": ilo.get("ilo_firmware") or rf.get("ilo_firmware"),
        "health": ilo.get("health_status"),
        "power_watts": ilo.get("power_watts"),
        "power_state": ilo.get("power_state"),
        "temperatures": trim(ilo.get("temperatures"), 25, ("locale", "name", "value", "celsius", "condition", "health", "upper_critical")),
        "fans": trim(ilo.get("fans"), 12, ("locale", "name", "speed", "condition", "health")),
        "power_supplies": trim(ilo.get("power_supplies"), 4, ("name", "status", "health", "state", "model", "capacity_watts")),
        "storage": [
            {"controller": c.get("name") or c.get("model"), "status": c.get("status") or c.get("health"),
             "drives": trim(c.get("drives"), 24, ("location", "model", "capacity_gb", "media_type", "health", "status", "predicted_failure", "temperature", "power_on_hours", "life_left_pct", "wear_pct")),
             "logical_drives": trim(c.get("logical_drives"), 8, ("name", "raid", "status"))}
            for c in (ilo.get("storage_controllers") or rf.get("storage_controllers") or [])[:4] if isinstance(c, dict)
        ],
        "memory_dimms": trim(ilo.get("memory_modules") or rf.get("memory_dimms"), 24, ("locator", "name", "size_gb", "capacity_mb", "status", "health")),
        "nics": trim(ilo.get("network_interfaces") or rf.get("network_adapters"), 8, ("name", "model", "status", "health", "link", "speed_mbps")),
    }
    return {
        "server": {"name": md.get("name") or md.get("hostname") or ilo.get("device_name") or ip, "ip": ip,
                   "events_source": cache.get("source"), "events_fetched_at": cache.get("fetched_at")},
        "events": [{k: e.get(k) for k in ("created", "severity", "message", "class", "code", "count", "repaired", "action") if e.get(k) not in (None, "", False) or k in ("repaired",)} for e in events],
        "hardware": hw,
        "active_alerts": alerts,
        "analyzed_at": _now().isoformat(),
    }


def _events_hash(events: list) -> str:
    ids = sorted(f"{e.get('id')}:{e.get('repaired')}" for e in events)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    return json.loads(text)


async def run_analysis(client_id: str, ip: str, trigger: str = "manual", user: Optional[str] = None) -> dict:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY non configurata")
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    ctx = await _context(client_id, ip)
    if not ctx["events"] and not ctx["hardware"].get("model"):
        raise HTTPException(status_code=404, detail="Nessun evento IML/SEL né dati hardware disponibili per questo server")
    chat = LlmChat(api_key=api_key, session_id=f"ilo-ai-{client_id}-{ip}-{uuid.uuid4().hex[:8]}",
                   system_message=SYSTEM_PROMPT).with_model(*MODEL)
    prompt = ("Analizza questo server e rispondi con il JSON richiesto.\n\n"
              f"CONTESTO (JSON):\n{json.dumps(ctx, ensure_ascii=False, default=str)}")
    t0 = _now()
    try:
        raw = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:  # noqa: BLE001
        logger.error(f"ilo-ai LLM error {ip}: {e}")
        raise HTTPException(status_code=502, detail=f"Errore modello AI: {str(e)[:200]}")
    try:
        result = _parse_json(raw if isinstance(raw, str) else str(raw))
    except Exception:
        result = {"risk_level": "unknown", "headline": "Risposta AI non strutturata", "diagnosis": (raw if isinstance(raw, str) else str(raw))[:2000],
                  "patterns": [], "actions": [], "ignore": [], "watch": [], "confidence": 0}
    doc = {
        "id": str(uuid.uuid4()), "client_id": client_id, "device_ip": ip, "server_name": ctx["server"]["name"],
        "created_at": _now().isoformat(), "duration_s": round((_now() - t0).total_seconds(), 1),
        "model": f"{MODEL[0]}/{MODEL[1]}", "trigger": trigger, "requested_by": user,
        "events_count": len(ctx["events"]), "events_hash": _events_hash(ctx["events"]),
        "unrepaired": sum(1 for e in ctx["events"] if not e.get("repaired") and re.search(r"crit|warn|caution|fatal", str(e.get("severity") or ""), re.I)),
        "risk_level": str(result.get("risk_level") or "unknown").lower(), "result": result,
    }
    await db.ilo_ai_analyses.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.post("/ilo-ai-analysis/{device_ip}")
async def post_ilo_ai_analysis(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(device_ip, client_id)
    if not cid:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    return await run_analysis(cid, device_ip, "manual", current_user.get("email"))


@router.get("/ilo-ai-analysis/{device_ip}")
async def get_ilo_ai_analysis(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(device_ip, client_id)
    hist = [a async for a in db.ilo_ai_analyses.find(
        {"device_ip": device_ip, **({"client_id": cid} if cid else {})}, {"_id": 0}).sort("created_at", -1).limit(10)]
    return {"latest": hist[0] if hist else None, "history": hist}


async def maybe_auto_analyze(client_id: Optional[str], device_ip: str, new_events: list, prev_events: list) -> None:
    """Trigger automatico: nuovi eventi crit/warn NON riparati rispetto alla cache precedente."""
    if not client_id or not os.environ.get("EMERGENT_LLM_KEY"):
        return
    prev_ids = {str(e.get("id")) for e in (prev_events or [])}
    fresh = [e for e in new_events if str(e.get("id")) not in prev_ids and not e.get("repaired")
             and re.search(r"crit|warn|caution|fatal", str(e.get("severity") or ""), re.I)]
    if not fresh or not prev_events:  # prima popolazione della cache: niente analisi
        return
    key = f"{client_id}:{device_ip}"
    if key in _auto_running:
        return
    last = await db.ilo_ai_analyses.find_one({"client_id": client_id, "device_ip": device_ip, "trigger": "auto"},
                                            {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    if last and last.get("created_at", "") > (_now() - timedelta(hours=AUTO_DEBOUNCE_H)).isoformat():
        return
    _auto_running.add(key)

    async def _job():
        try:
            doc = await run_analysis(client_id, device_ip, "auto")
            if doc["risk_level"] in ("high", "critical"):
                from telegram_notifier import send_telegram_text
                r = doc["result"]
                acts = "\n".join(f"  {a.get('priority', '•')}. {a.get('action')}" for a in (r.get("actions") or [])[:3])
                text = (f"🧠 <b>Analisi AI iLO — {doc['server_name']}</b> ({device_ip})\n"
                        f"Rischio: <b>{doc['risk_level'].upper()}</b> · {len(fresh)} nuovi eventi hardware\n"
                        f"{r.get('headline', '')}\n\n{acts}")
                await send_telegram_text(db, text)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ilo-ai auto {device_ip}: {e}")
        finally:
            _auto_running.discard(key)

    asyncio.create_task(_job())
