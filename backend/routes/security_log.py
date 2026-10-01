"""API Registro accessi Amministratori di Sistema: /api/seclog/*"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security_log import EVENT_MAP, get_admins, ingest_security_events, retention_months, verify_chain

router = APIRouter(prefix="/api/seclog", tags=["security-log"])
CATEGORIES = sorted({v[0] for v in EVENT_MAP.values()})


def _scope(current_user: dict, client_id: Optional[str]) -> dict:
    if current_user.get("role") != "admin":
        return {"client_id": current_user.get("client_id")}
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id obbligatorio")
    return {"client_id": client_id}


@router.get("/events")
async def list_events(client_id: Optional[str] = None, host: Optional[str] = None, user: Optional[str] = None,
                      category: Optional[str] = None, admin_only: bool = False, hours: int = 24, q: Optional[str] = None,
                      limit: int = 200, skip: int = 0, current_user: dict = Depends(get_current_user)):
    f = _scope(current_user, client_id)
    f["ts"] = {"$gte": (datetime.now(timezone.utc) - timedelta(hours=min(hours, 24 * 400))).isoformat()}
    if host:
        f["host"] = host
    if user:
        f["user"] = {"$regex": user, "$options": "i"}
    if category:
        f["category"] = {"$in": category.split(",")}
    if admin_only:
        f["is_admin"] = True
    if q:
        f["$or"] = [{"user": {"$regex": q, "$options": "i"}}, {"src_ip": {"$regex": q, "$options": "i"}},
                    {"workstation": {"$regex": q, "$options": "i"}}, {"host": {"$regex": q, "$options": "i"}}]
    total = await db.security_events.count_documents(f)
    rows = await db.security_events.find(f, {"_id": 0, "expire_at": 0}).sort("ts", -1).skip(skip).limit(min(limit, 1000)).to_list(1000)
    return {"total": total, "events": rows, "categories": CATEGORIES}


@router.get("/stats")
async def stats(client_id: Optional[str] = None, hours: int = 24, current_user: dict = Depends(get_current_user)):
    f = _scope(current_user, client_id)
    cid = f["client_id"]
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    m = {"client_id": cid, "ts": {"$gte": since}}
    by_cat = {r["_id"]: r["n"] async for r in db.security_events.aggregate([{"$match": m}, {"$group": {"_id": "$category", "n": {"$sum": 1}}}])}
    top_users = [{"user": r["_id"], "n": r["n"]} async for r in db.security_events.aggregate(
        [{"$match": {**m, "category": {"$in": ["logon_success", "privileged_logon", "rdp_connect"]}}}, {"$group": {"_id": "$user", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 8}])]
    top_failed = [{"user": r["_id"], "n": r["n"]} async for r in db.security_events.aggregate(
        [{"$match": {**m, "category": "logon_failed"}}, {"$group": {"_id": "$user", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}, {"$limit": 8}])]
    hosts = [{"host": r["_id"], "n": r["n"], "last": r["last"]} async for r in db.security_events.aggregate(
        [{"$match": {"client_id": cid}}, {"$group": {"_id": "$host", "n": {"$sum": 1}, "last": {"$max": "$ts"}}}, {"$sort": {"last": -1}}])]
    state = await db.security_chain_state.find_one({"client_id": cid}, {"_id": 0})
    return {"by_category": by_cat, "top_users": top_users, "top_failed": top_failed, "hosts": hosts,
            "admin_events": await db.security_events.count_documents({**m, "is_admin": True}),
            "total_all_time": await db.security_events.count_documents({"client_id": cid}),
            "chain": state, "retention_months": await retention_months(cid), "admins": sorted(await get_admins(cid))}


@router.get("/verify")
async def verify(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    f = _scope(current_user, client_id)
    res = await verify_chain(f["client_id"])
    await db.security_chain_state.update_one({"client_id": f["client_id"]}, {"$set": {"last_verify_at": datetime.now(timezone.utc).isoformat(), "last_verify_ok": res["ok"]}}, upsert=True)
    return res


class AdminsIn(BaseModel):
    users: list[str] = Field(default_factory=list)


@router.put("/admins/{client_id}")
async def set_admins(client_id: str, body: AdminsIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    users = sorted({u.strip() for u in body.users if u.strip()})
    await db.security_admins.update_one({"client_id": client_id}, {"$set": {"users": users, "updated_at": datetime.now(timezone.utc).isoformat(), "by": current_user.get("email")}}, upsert=True)
    lowered = [u.lower() for u in users]
    await db.security_events.update_many({"client_id": client_id, "event_id": {"$ne": 4672}}, [{"$set": {"is_admin": {"$in": [{"$toLower": "$user"}, lowered]}}}])
    return {"ok": True, "users": users}


class SettingsIn(BaseModel):
    retention_months: int = Field(ge=6, le=120)


@router.put("/settings/{client_id}")
async def set_settings(client_id: str, body: SettingsIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.security_log_settings.update_one({"client_id": client_id}, {"$set": {"retention_months": body.retention_months}}, upsert=True)
    if client_id != "global":
        await db.security_events.update_many({"client_id": client_id}, [{"$set": {"expire_at": {"$dateAdd": {"startDate": {"$toDate": "$ts"}, "unit": "day", "amount": 30 * body.retention_months}}}}])
    return {"ok": True, "retention_months": body.retention_months}


class IngestIn(BaseModel):
    client_id: str
    host: str
    events: list[dict]


@router.post("/ingest-manual")
async def ingest_manual(body: IngestIn, current_user: dict = Depends(get_current_user)):
    """Ingest manuale (test/import CSV) — stessa pipeline dell'agent."""
    require_admin(current_user)
    return await ingest_security_events(body.client_id, "manual", body.host, body.events)


@router.get("/report.pdf")
async def report_pdf(client_id: str, month: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    f = _scope(current_user, client_id)
    cid = f["client_id"]
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from routes.reports import BRAND_INDIGO, BRAND_RED, BRAND_GREEN, get_styles

    now = datetime.now(timezone.utc)
    if month:
        y, mth = (int(x) for x in month.split("-"))
    else:
        y, mth = now.year, now.month
    start = datetime(y, mth, 1, tzinfo=timezone.utc)
    end = datetime(y + (mth == 12), (mth % 12) + 1, 1, tzinfo=timezone.utc)
    client = await db.clients.find_one({"id": cid}, {"_id": 0, "name": 1}) or {}
    m = {"client_id": cid, "ts": {"$gte": start.isoformat(), "$lt": end.isoformat()}}
    rows = await db.security_events.find(m, {"_id": 0}).sort("ts", 1).to_list(20000)
    chain = await verify_chain(cid)
    admins = sorted(await get_admins(cid))
    styles = get_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title=f"Registro accessi AdS — {client.get('name', cid)} — {y}-{mth:02d}")
    story = [Paragraph(f"Registro accessi Amministratori di Sistema — {client.get('name', cid)}", styles["Title"]),
             Paragraph(f"Periodo: {start:%d/%m/%Y} – {(end - timedelta(days=1)):%d/%m/%Y} · generato il {now:%d/%m/%Y %H:%M} UTC · "
                       f"Provv. Garante 27/11/2008 · GDPR art. 32 · NIS2", styles["Normal"]), Spacer(1, 8)]
    integ = f"Integrità registro: {'VERIFICATA' if chain['ok'] else 'COMPROMESSA'} — {chain.get('checked', 0)} eventi in catena SHA-256, ultimo hash {str(chain.get('last_hash', ''))[:16]}…"
    story.append(Paragraph(f"<font color='{'#10b981' if chain['ok'] else '#ef4444'}'><b>{integ}</b></font>", styles["Normal"]))
    story.append(Paragraph(f"Amministratori di Sistema designati: {', '.join(admins) or 'nessuno configurato (usati i privilegi 4672)'}", styles["Normal"]))
    story.append(Spacer(1, 8))
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["label"]] = cats.get(r["label"], 0) + 1
    summ = [["Tipo evento", "Totale"]] + [[k, str(v)] for k, v in sorted(cats.items(), key=lambda x: -x[1])]
    t = Table(summ, colWidths=[12 * cm, 3 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BRAND_INDIGO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
    story += [Paragraph("Riepilogo", styles["Heading2"]), t, Spacer(1, 10)]
    adm = [r for r in rows if r.get("is_admin")]
    story.append(Paragraph(f"Accessi degli Amministratori di Sistema ({len(adm)})", styles["Heading2"]))
    hdr = ["Data/ora (UTC)", "Server", "Evento", "Utente", "Tipo", "Origine", "Seq/Hash"]
    data = [hdr] + [[r["ts"][:19].replace("T", " "), r["host"][:22], r["label"][:34], f"{r.get('domain') or ''}\\{r['user']}"[:30],
                     r.get("logon_type_label") or "", (r.get("src_ip") or r.get("workstation") or "")[:22], f"#{r['seq']} {r['hash'][:10]}"] for r in adm[:1500]]
    t2 = Table(data, colWidths=[3.4 * cm, 3.6 * cm, 5.2 * cm, 4.8 * cm, 2.4 * cm, 3.6 * cm, 3.4 * cm], repeatRows=1)
    t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BRAND_INDIGO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                            ("GRID", (0, 0), (-1, -1), 0.2, colors.lightgrey), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f5")])]))
    story.append(t2)
    sec = [r for r in rows if r["category"] in ("log_cleared", "account_created", "account_deleted", "group_change", "lockout", "password_reset")]
    if sec:
        story += [Spacer(1, 10), Paragraph(f"Eventi di sicurezza rilevanti ({len(sec)})", styles["Heading2"])]
        d3 = [hdr] + [[r["ts"][:19].replace("T", " "), r["host"][:22], r["label"][:34], (r.get("target_user") or r["user"])[:30], r.get("group") or "",
                       (r.get("subject_user") or "")[:22], f"#{r['seq']}"] for r in sec[:800]]
        t3 = Table(d3, colWidths=[3.4 * cm, 3.6 * cm, 5.2 * cm, 4.8 * cm, 2.4 * cm, 3.6 * cm, 3.4 * cm], repeatRows=1)
        t3.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BRAND_RED), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                                ("GRID", (0, 0), (-1, -1), 0.2, colors.lightgrey)]))
        story.append(t3)
    failed = len([r for r in rows if r["category"] == "logon_failed"])
    story += [Spacer(1, 8), Paragraph(f"Accessi falliti nel periodo: {failed} · eventi totali registrati: {len(rows)} · retention: {await retention_months(cid)} mesi", styles["Normal"]),
              Paragraph(f"<font color='{BRAND_GREEN.hexval() if hasattr(BRAND_GREEN, 'hexval') else '#10b981'}'>Documento generato automaticamente da ARGUS Center. Ogni evento è concatenato tramite hash SHA-256 (prev_hash → hash): l'alterazione o rimozione di un singolo evento invalida la verifica di integrità.</font>", styles["Normal"])]
    doc.build(story)
    buf.seek(0)
    fname = f"registro-ads-{(client.get('name') or cid).replace(' ', '_')}-{y}-{mth:02d}.pdf"
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
