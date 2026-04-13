"""SOC AI Correlation powered by Gemini - Intelligent alert analysis and recommendations."""
import os
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from database import db
from deps import get_current_user
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("soc_ai")
router = APIRouter(prefix="/api/ai", tags=["soc-ai"])

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


async def get_client_context(client_id: str) -> dict:
    """Build a comprehensive context about the client's network for AI analysis."""
    devices = await db.device_poll_status.find({"client_id": client_id}, {"_id": 0}).to_list(500)
    alerts = await db.alerts.find(
        {"client_id": client_id, "resolved": {"$ne": True}}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    backup = await db.backup_status.find_one({"client_id": client_id}, {"_id": 0})

    # Active maintenance
    now = datetime.now(timezone.utc).isoformat()
    maint = await db.maintenance_windows.find_one({
        "client_id": client_id, "start_time": {"$lte": now}, "end_time": {"$gte": now},
    }, {"_id": 0})

    # Thresholds
    thresholds = await db.alert_thresholds.find_one({"client_id": client_id}, {"_id": 0})

    # Recent resolved alerts (last 24h)
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_resolved = await db.alerts.find(
        {"client_id": client_id, "resolved": True, "resolved_at": {"$gte": cutoff_24h}},
        {"_id": 0}
    ).to_list(20)

    online = [d for d in devices if d.get("reachable")]
    offline = [d for d in devices if not d.get("reachable")]

    return {
        "total_devices": len(devices),
        "online": len(online),
        "offline": len(offline),
        "devices": [{
            "name": d.get("device_name", d.get("device_ip", "")),
            "ip": d.get("device_ip", ""),
            "reachable": d.get("reachable", False),
            "ping_ms": d.get("ping_ms"),
            "device_type": d.get("device_type", ""),
            "open_ports": d.get("open_ports", []),
        } for d in devices[:30]],
        "active_alerts": [{
            "severity": a.get("severity", ""),
            "title": a.get("title", ""),
            "device_name": a.get("device_name", ""),
            "device_ip": a.get("device_ip", ""),
            "created_at": a.get("created_at", ""),
            "source": a.get("source", ""),
        } for a in alerts[:20]],
        "active_alert_count": len(alerts),
        "recent_resolved_count": len(recent_resolved),
        "backup_summary": backup.get("summary", {}) if backup else None,
        "backup_failed_vms": [v.get("vm_name") for v in (backup or {}).get("vms", []) if v.get("backup_status") in ("failed", "missing")],
        "maintenance_active": bool(maint),
        "maintenance_title": maint.get("title") if maint else None,
        "custom_thresholds": bool(thresholds),
    }


@router.post("/analyze/{client_id}")
async def ai_analyze(client_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Run AI-powered analysis on the client's network state."""
    if not GEMINI_KEY:
        raise HTTPException(status_code=500, detail="Chiave API Gemini non configurata")

    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    user_question = body.get("question", "")

    context = await get_client_context(client_id)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "api_key": 0})
    client_name = client.get("name", client_id) if client else client_id

    system_message = f"""Sei un analista SOC (Security Operations Center) esperto di 86BIT.
Analizzi la rete del cliente "{client_name}" e fornisci raccomandazioni operative in italiano.

REGOLE:
- Rispondi SEMPRE in italiano
- Sii conciso e operativo, come un tecnico NOC esperto
- Prioritizza i problemi per impatto sul business
- Suggerisci azioni concrete e specifiche
- Se non ci sono problemi, dillo chiaramente
- Usa un tono professionale ma comprensibile
- Se c'e' manutenzione attiva, menzionalo
- Considera le correlazioni: dispositivi offline sulla stessa subnet, pattern temporali, impatto cascade

FORMATO RISPOSTA (JSON):
{{
  "overall_status": "critico|attenzione|stabile|ottimo",
  "risk_score": 0-100,
  "summary": "Riepilogo in 2-3 frasi della situazione",
  "correlations": [
    {{
      "title": "Titolo correlazione",
      "severity": "critical|high|medium|low",
      "description": "Descrizione dettagliata",
      "affected_devices": ["device1", "device2"],
      "recommendation": "Azione consigliata",
      "confidence": 0-100
    }}
  ],
  "recommendations": [
    {{
      "priority": "immediata|breve_termine|pianificata",
      "action": "Azione specifica da eseguire",
      "reason": "Motivazione"
    }}
  ],
  "patterns_detected": ["pattern1", "pattern2"]
}}"""

    context_text = f"""STATO ATTUALE RETE:
- Dispositivi totali: {context['total_devices']} (Online: {context['online']}, Offline: {context['offline']})
- Alert attivi: {context['active_alert_count']}
- Alert risolti ultime 24h: {context['recent_resolved_count']}
- Manutenzione: {'ATTIVA - ' + (context['maintenance_title'] or '') if context['maintenance_active'] else 'Nessuna'}
- Backup: {json.dumps(context['backup_summary']) if context['backup_summary'] else 'Dati non disponibili'}
- VM con backup fallito: {', '.join(context['backup_failed_vms']) if context['backup_failed_vms'] else 'Nessuna'}

DISPOSITIVI:
{json.dumps(context['devices'], indent=2)}

ALERT ATTIVI:
{json.dumps(context['active_alerts'], indent=2)}"""

    user_text = context_text
    if user_question:
        user_text += f"\n\nDOMANDA OPERATORE: {user_question}"
    else:
        user_text += "\n\nAnalizza la situazione attuale della rete e fornisci correlazioni, raccomandazioni e pattern rilevati."

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        session_id = f"soc-{client_id}-{uuid.uuid4().hex[:8]}"
        chat = LlmChat(
            api_key=GEMINI_KEY,
            session_id=session_id,
            system_message=system_message
        )
        chat.with_model("gemini", "gemini-2.5-flash")

        user_message = UserMessage(text=user_text)
        response_text = await chat.send_message(user_message)

        # Parse JSON response
        try:
            # Clean response (remove markdown code blocks if present)
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

            ai_result = json.loads(cleaned)
        except json.JSONDecodeError:
            ai_result = {
                "overall_status": "stabile",
                "risk_score": 50,
                "summary": response_text[:500],
                "correlations": [],
                "recommendations": [],
                "patterns_detected": [],
                "raw_response": True,
            }

        # Store analysis in DB
        analysis_doc = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context_snapshot": {
                "total_devices": context["total_devices"],
                "online": context["online"],
                "offline": context["offline"],
                "active_alerts": context["active_alert_count"],
            },
            "question": user_question,
            "result": ai_result,
            "analyzed_by": current_user.get("email", "system"),
        }
        await db.ai_analyses.insert_one(analysis_doc)

        return {
            "status": "ok",
            "analysis": ai_result,
            "analysis_id": analysis_doc["id"],
            "timestamp": analysis_doc["timestamp"],
        }

    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        raise HTTPException(status_code=500, detail=f"Errore nell'analisi AI: {str(e)}")


@router.get("/history/{client_id}")
async def ai_analysis_history(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get history of AI analyses for a client."""
    analyses = await db.ai_analyses.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("timestamp", -1).to_list(20)
    return analyses


@router.post("/ask/{client_id}")
async def ai_ask(client_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Ask a specific question about the client's network to the AI."""
    body = await request.json()
    question = body.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Domanda richiesta")

    # Reuse the analyze endpoint with a question
    from starlette.datastructures import Headers
    return await ai_analyze(client_id, request, current_user)
