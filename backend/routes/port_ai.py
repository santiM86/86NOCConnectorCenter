"""AI (GPT-5.4 via Universal Key) sulle abitudini porte switch.

- POST/GET /api/devices/{ip}/switch-ports/{idx}/ai-explain?client_id=  → spiega UNA porta (down/anomala): diagnosi + azione
- POST/GET /api/devices/{ip}/switch-ports/ai-audit?client_id=          → audit di TUTTO lo switch: porte da disabilitare,
  pattern sospetti, etichette mancanti, flap. On-demand, salvato in `port_ai_analyses`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user, require_admin
from port_memory import classify, is_italian_holiday, schedule_summary, _parse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devices", tags=["port-ai"])
MODEL = ("openai", "gpt-5.4")

EXPLAIN_PROMPT = """Sei un network engineer senior di un NOC di un MSP italiano. Ricevi i dati di UNA porta di uno switch: stato attuale,
abitudini storiche (istogramma ora/giorno della settimana), dispositivo collegato di solito, PoE, eventi flap recenti, stato agente RMM
del PC collegato, festività. Devi dire al tecnico se il "link down" è un guasto o uno spegnimento voluto dal cliente e cosa fare.
Regole: rispondi SOLO con JSON valido in italiano; non inventare dati; cita orari, giorni, percentuali e nomi presenti nei dati.
Schema:
{
 "verdict": "spento_dal_cliente|guasto_probabile|standby|inutilizzata|incerto|attiva",
 "headline": "una frase (max 110 caratteri)",
 "explanation": "3-6 frasi: cosa dicono le abitudini, il PoE, il device collegato, Datto, i flap",
 "actions": [{"priority": 1, "action": "...", "why": "...", "when": "subito|entro oggi|prossima visita|nessuna"}],
 "suggest_reclassify": null | "habitual" | "anomalous",
 "reclassify_reason": "perché la statistica andrebbe corretta, se applicabile",
 "confidence": 0-100
}"""

AUDIT_PROMPT = """Sei un network engineer senior di un NOC di un MSP italiano. Ricevi il quadro completo delle porte di uno switch con
abitudini storiche, dispositivi collegati, PoE, velocità, flap 7 giorni, etichette. Produci un audit con consigli concreti:
sicurezza (porte mai usate da disabilitare, attività notturne/festive anomale su porte ufficio, dispositivi sconosciuti), igiene
(porte senza descrizione, velocità 100M su porte gigabit → cavo/negoziazione), affidabilità (flap frequenti, PoE instabile),
capacità (porte libere, uplink saturi). Regole: SOLO JSON valido in italiano; non inventare; cita numeri porta e dati reali.
Schema:
{
 "score": 0-100,
 "headline": "una frase (max 120 caratteri)",
 "summary": "3-6 frasi sullo stato dello switch",
 "findings": [{"type": "security|hygiene|reliability|capacity|anomaly", "severity": "info|low|medium|high",
               "ports": [1,2], "title": "...", "detail": "...", "action": "..."}],
 "disable_candidates": [numeri porta mai usate da 30+ giorni],
 "label_missing": [numeri porta attive senza descrizione utile],
 "confidence": 0-100
}"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), re.S)
    return json.loads(m.group(0) if m else text)


def _mem_view(m: Optional[dict], sp: Optional[dict], hol: Optional[str]) -> dict:
    sp = sp or {}
    oper_up = int(sp.get("oper", 0) or 0) == 1
    poe_w = float(sp.get("poe_watt", 0) or 0)
    habit = classify(m, oper_up, poe_w, holiday=hol)
    return {
        "idx": sp.get("idx") if sp.get("idx") is not None else (m or {}).get("idx"),
        "name": sp.get("name") or (m or {}).get("name"), "descr": sp.get("descr") or sp.get("alias") or "",
        "oper": "up" if oper_up else "down", "admin_down": int(sp.get("admin", 1) or 1) == 2,
        "speed_mbps": sp.get("speed_mbps"), "poe_w_now": poe_w, "rx_bps": sp.get("rx_bps"), "tx_bps": sp.get("tx_bps"),
        "habit": {k: habit.get(k) for k in ("profile_label", "verdict", "label", "reason", "up_ratio", "days", "usual_speed_mbps", "usual_poe_w", "slot_up_ratio")},
        "schedule_up_hours": schedule_summary(m), "last_device": (m or {}).get("last_device"), "mac_count": (m or {}).get("mac_count"),
        "last_up_at": (m or {}).get("last_up_at"), "last_down_at": (m or {}).get("last_down_at"),
    }


async def _flaps(client_id: str, ip: str, idx: Optional[int], days: int = 7, limit: int = 60) -> list:
    q = {"client_id": client_id, "local_ip": ip, "ts": {"$gte": (_now() - timedelta(days=days)).isoformat()}}
    if idx is not None:
        q["idx"] = idx
    return [{"ts": e.get("ts"), "idx": e.get("idx"), "kind": e.get("kind"), "from": e.get("from"), "to": e.get("to")}
            async for e in db.port_flap_events.find(q, {"_id": 0}).sort("ts", -1).limit(limit)]


async def _switch(client_id: str, ip: str) -> dict:
    md = await db.managed_devices.find_one({"client_id": client_id, "$or": [{"ip": ip}, {"ip_address": ip}]},
                                           {"_id": 0, "name": 1, "hostname": 1, "device_name": 1, "device_type": 1, "vendor": 1, "model": 1}) or {}
    cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1}) or {}
    return {"ip": ip, "name": md.get("name") or md.get("device_name") or md.get("hostname") or ip,
            "type": md.get("device_type"), "vendor": md.get("vendor"), "model": md.get("model"), "client": cl.get("name")}


async def _port_context(client_id: str, ip: str, idx: int) -> dict:
    hol = is_italian_holiday()
    m = await db.port_memory.find_one({"client_id": client_id, "local_ip": ip, "idx": idx}, {"_id": 0})
    sp = await db.switch_ports.find_one({"client_id": client_id, "local_ip": ip, "idx": idx}, {"_id": 0})
    if not m and not sp:
        raise HTTPException(status_code=404, detail="Porta non trovata (nessun poll SNMP né memoria)")
    port = _mem_view(m, sp, hol)
    datto = None
    dev_ip = ((m or {}).get("last_device") or {}).get("ip")
    if dev_ip:
        try:
            from shutdown_diagnosis import _datto_signal
            _sig, datto = await _datto_signal(db, client_id, dev_ip, _parse((m or {}).get("last_down_at")))
            datto = {"signal": _sig, "title": datto.get("title"), "text": datto.get("text")}
        except Exception as e:  # noqa: BLE001
            logger.debug(f"port-ai datto {dev_ip}: {e}")
    pname = port.get("name") or ""
    alerts = [a async for a in db.alerts.find(
        {"client_id": client_id, "device_ip": ip, "status": {"$in": ["active", "acknowledged"]},
         "$or": [{"message": {"$regex": re.escape(pname)}}, {"title": {"$regex": re.escape(pname)}}, {"dedup_key": {"$regex": f":{idx}$"}}]},
        {"_id": 0, "title": 1, "severity": 1, "created_at": 1, "source_type": 1}).limit(10)] if pname else []
    loc = _now() + timedelta(hours=2 if 3 < _now().month < 11 else 1)
    return {"switch": await _switch(client_id, ip), "port": port, "flaps_7d": await _flaps(client_id, ip, idx),
            "datto_rmm_of_last_device": datto, "active_alerts_on_port": alerts,
            "now": {"local": loc.strftime("%A %d/%m/%Y %H:%M"), "holiday": hol, "weekend": loc.weekday() >= 5}}


async def _switch_context(client_id: str, ip: str) -> dict:
    hol = is_italian_holiday()
    mems = {m["idx"]: m async for m in db.port_memory.find({"client_id": client_id, "local_ip": ip}, {"_id": 0})}
    sps = {int(s["idx"]): s async for s in db.switch_ports.find({"client_id": client_id, "local_ip": ip}, {"_id": 0}) if s.get("idx") is not None}
    if not mems and not sps:
        raise HTTPException(status_code=404, detail="Nessuna porta nota per questo switch")
    idxs = sorted(set(mems) | set(sps))
    phys = re.compile(r"^(null|loop|vlan|tunnel|inloop|register|aux|cpu|bridge|lag|po\d|trunk\d)", re.I)
    ports = []
    for i in idxs:
        v = _mem_view(mems.get(i), sps.get(i), hol)
        if phys.match(str(v.get("name") or "")):
            continue
        v.pop("rx_bps", None); v.pop("tx_bps", None)
        ports.append(v)
    flaps = await _flaps(client_id, ip, None, days=7, limit=400)
    per_port: dict = {}
    for f in flaps:
        per_port[f["idx"]] = per_port.get(f["idx"], 0) + 1
    loc = _now() + timedelta(hours=2 if 3 < _now().month < 11 else 1)
    return {"switch": await _switch(client_id, ip), "ports": ports, "flap_count_7d_by_port": per_port,
            "totals": {"ports": len(ports), "up": sum(1 for p in ports if p["oper"] == "up"),
                       "unused_30d": [p["idx"] for p in ports if p["habit"].get("verdict") == "unused" and (p["habit"].get("days") or 0) >= 30]},
            "now": {"local": loc.strftime("%A %d/%m/%Y %H:%M"), "holiday": hol}}


async def _run(kind: str, client_id: str, ip: str, idx: Optional[int], user: Optional[str]) -> dict:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY non configurata")
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    ctx = await (_port_context(client_id, ip, idx) if kind == "explain" else _switch_context(client_id, ip))
    chat = LlmChat(api_key=api_key, session_id=f"port-ai-{kind}-{client_id}-{ip}-{uuid.uuid4().hex[:8]}",
                   system_message=EXPLAIN_PROMPT if kind == "explain" else AUDIT_PROMPT).with_model(*MODEL)
    t0 = _now()
    try:
        raw = await chat.send_message(UserMessage(text=f"Analizza e rispondi con il JSON richiesto.\n\nDATI (JSON):\n{json.dumps(ctx, ensure_ascii=False, default=str)}"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"port-ai LLM error {ip}/{idx}: {e}")
        raise HTTPException(status_code=502, detail=f"Errore modello AI: {str(e)[:200]}")
    raw = raw if isinstance(raw, str) else str(raw)
    try:
        result = _parse_json(raw)
    except Exception:
        result = {"headline": "Risposta AI non strutturata", "explanation": raw[:2000], "summary": raw[:2000], "actions": [], "findings": [], "confidence": 0}
    doc = {"id": str(uuid.uuid4()), "kind": kind, "client_id": client_id, "device_ip": ip, "idx": idx,
           "switch_name": ctx["switch"]["name"], "port_name": (ctx.get("port") or {}).get("name"),
           "created_at": _now().isoformat(), "duration_s": round((_now() - t0).total_seconds(), 1),
           "model": f"{MODEL[0]}/{MODEL[1]}", "requested_by": user, "result": result,
           "ports_analyzed": len(ctx.get("ports") or []) if kind == "audit" else 1}
    await db.port_ai_analyses.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _cid(ip: str, client_id: Optional[str]) -> str:
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(ip, client_id)
    if not cid:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    return cid


async def _latest(kind: str, cid: str, ip: str, idx: Optional[int]) -> dict:
    hist = [a async for a in db.port_ai_analyses.find({"kind": kind, "client_id": cid, "device_ip": ip, "idx": idx}, {"_id": 0})
            .sort("created_at", -1).limit(5)]
    return {"latest": hist[0] if hist else None, "history": hist}


@router.post("/{device_ip}/switch-ports/ai-audit")
async def post_switch_ai_audit(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    return await _run("audit", await _cid(device_ip, client_id), device_ip, None, current_user.get("email"))


@router.get("/{device_ip}/switch-ports/ai-audit")
async def get_switch_ai_audit(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    return await _latest("audit", await _cid(device_ip, client_id), device_ip, None)


@router.post("/{device_ip}/switch-ports/{idx}/ai-explain")
async def post_port_ai_explain(device_ip: str, idx: int, client_id: str = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    return await _run("explain", await _cid(device_ip, client_id), device_ip, idx, current_user.get("email"))


@router.get("/{device_ip}/switch-ports/{idx}/ai-explain")
async def get_port_ai_explain(device_ip: str, idx: int, client_id: str = None, current_user: dict = Depends(get_current_user)):
    return await _latest("explain", await _cid(device_ip, client_id), device_ip, idx)
