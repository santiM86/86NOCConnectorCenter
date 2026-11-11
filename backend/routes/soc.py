"""API SOC: indagine AI incidenti, rischio utenti (UEBA), dashboard direzione (rischio, tempi, NIS2/GDPR)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user
from incident_engine import correlate, investigate
from ueba import user_risk

router = APIRouter(prefix="/api", tags=["soc"])
SEV_W = {"critical": 15, "high": 8, "medium": 3, "low": 1}


@router.post("/incidents/{incident_id}/investigate")
async def incident_investigate(incident_id: str, current_user: dict = Depends(get_current_user)):
    try:
        return await investigate(incident_id, current_user.get("email") or "utente")
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Errore modello AI: {str(e)[:200]}")


@router.post("/incidents/correlate-now")
async def incidents_correlate_now(current_user: dict = Depends(get_current_user)):
    return {"created": await correlate()}


@router.get("/ueba/users")
async def ueba_users(client_id: Optional[str] = None, days: int = 30, current_user: dict = Depends(get_current_user)):
    rows = await user_risk(client_id, days)
    names = {c["id"]: c.get("name") async for c in db.clients.find({}, {"_id": 0, "id": 1, "name": 1})}
    for r in rows:
        r["client_name"] = names.get(r["client_id"], r["client_id"])
        p = await db.ueba_profiles.find_one({"client_id": r["client_id"], "user": r["user"]}, {"_id": 0, "total": 1, "hosts": 1, "first_seen": 1})
        r["profile"] = {"logons": (p or {}).get("total", 0), "hosts": len((p or {}).get("hosts") or {}), "since": (p or {}).get("first_seen")}
    return rows[:200]


def _minutes(a: str, b: str) -> Optional[float]:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60
    except Exception:
        return None


async def _compliance(client_id: Optional[str], since7: str, active: list, mtta: Optional[float]) -> list[dict]:
    q = {"client_id": client_id} if client_id else {}
    monitored = await db.device_poll_status.count_documents(q)
    seclog = await db.security_events.count_documents({**q, "ts": {"$gte": since7}})
    stale_inc = await db.incidents.count_documents({**q, "status": {"$in": ["open", "investigating"]},
                                                    "created_at": {"$lt": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()}})
    cert = [a for a in active if "cert" in (a.get("source_type") or "")]
    expo = [a for a in active if any(k in (a.get("source_type") or "") for k in ("shodan", "osint", "exposed"))]
    crit = [a for a in active if a.get("severity") == "critical"]

    def item(key, label, norm, ok, warn=False, detail=""):
        return {"key": key, "label": label, "norm": norm, "status": "ok" if ok else ("warn" if warn else "ko"), "detail": detail}
    return [
        item("monitoring", "Monitoraggio continuo di reti e sistemi", "NIS2 art. 21.2(b)", monitored > 0, detail=f"{monitored} dispositivi monitorati"),
        item("admin_log", "Registro accessi Amministratori di Sistema", "GDPR · Provv. Garante AdS 2008", seclog > 0,
             detail=f"{seclog} eventi negli ultimi 7 giorni" if seclog else "nessun evento: installare Agent ≥4.31 sui server Windows"),
        item("anomaly", "Rilevamento accessi anomali (UEBA)", "NIS2 art. 21.2(i)", seclog > 0, detail="profili utente appresi dal registro accessi"),
        item("incidents", "Gestione incidenti entro 7 giorni", "NIS2 art. 23", stale_inc == 0, warn=stale_inc <= 2,
             detail=f"{stale_inc} incidenti aperti da oltre 7 giorni" if stale_inc else "nessun incidente in sospeso"),
        item("response", "Presa in carico alert < 60 min", "NIS2 art. 21.2(b)", mtta is not None and mtta <= 60, warn=mtta is not None and mtta <= 240,
             detail=f"tempo medio {round(mtta)} min" if mtta is not None else "nessun alert preso in carico nel periodo"),
        item("certs", "Certificati SSL esposti validi", "NIS2 art. 21.2(h)", not cert, warn=len(cert) <= 1, detail=f"{len(cert)} certificati in scadenza" if cert else "tutti validi"),
        item("exposure", "Esposizione Internet sotto controllo", "NIS2 art. 21.2(e)", not expo, warn=len(expo) <= 2, detail=f"{len(expo)} servizi esposti a rischio" if expo else "nessun servizio a rischio"),
        item("critical", "Nessun problema critico aperto", "NIS2 art. 21.2(c)", not crit, warn=len(crit) <= 1, detail=f"{len(crit)} alert critici attivi" if crit else "nessuno"),
    ]


@router.get("/executive/summary")
async def executive_summary(client_id: Optional[str] = None, days: int = 30, current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    q = {"client_id": client_id} if client_id else {}
    active = await db.alerts.find({**q, "status": "active"}, {"_id": 0, "severity": 1, "source_type": 1}).to_list(20000)
    period = await db.alerts.find({**q, "created_at": {"$gte": since}},
                                  {"_id": 0, "severity": 1, "created_at": 1, "acknowledged_at": 1, "resolved_at": 1}).to_list(20000)
    by_sev = {s: sum(1 for a in period if a.get("severity") == s) for s in ("critical", "high", "medium", "low")}
    acks = [m for m in (_minutes(a["created_at"], a["acknowledged_at"]) for a in period if a.get("acknowledged_at") and a.get("created_at")) if m is not None and m >= 0]
    ress = [m for m in (_minutes(a["created_at"], a["resolved_at"]) for a in period if a.get("resolved_at") and a.get("created_at")) if m is not None and m >= 0]
    mtta = sum(acks) / len(acks) if acks else None
    mttr = sum(ress) / len(ress) if ress else None
    users = await user_risk(client_id, days)
    alert_risk = min(60, sum(SEV_W.get(a.get("severity") or "low", 1) for a in active) / 2)
    user_r = min(25, (users[0]["score"] / 4) if users else 0)
    comp = await _compliance(client_id, (now - timedelta(days=7)).isoformat(), active, mtta)
    comp_ok = sum(1 for c in comp if c["status"] == "ok")
    comp_score = round(100 * (comp_ok + 0.5 * sum(1 for c in comp if c["status"] == "warn")) / len(comp))
    risk = round(min(100, alert_risk + user_r + (100 - comp_score) * 0.15))
    inc_q = {**q, "created_at": {"$gte": since}}
    return {
        "client_id": client_id, "days": days, "generated_at": now.isoformat(),
        "risk_score": risk, "risk_level": "alto" if risk >= 60 else "medio" if risk >= 30 else "basso",
        "active_alerts": len(active), "alerts_period": len(period), "alerts_by_severity": by_sev,
        "incidents_period": await db.incidents.count_documents(inc_q),
        "incidents_open": await db.incidents.count_documents({**q, "status": {"$in": ["open", "investigating"]}}),
        "incidents_auto": await db.incidents.count_documents({**inc_q, "source": "auto_correlation"}),
        "mtta_min": round(mtta, 1) if mtta is not None else None, "mttr_min": round(mttr, 1) if mttr is not None else None,
        "top_risky_users": users[:5], "compliance": comp, "compliance_score": comp_score,
    }
