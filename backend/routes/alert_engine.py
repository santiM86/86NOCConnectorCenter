"""API di configurazione dell'Alert Engine proattivo (vitali offline + Datto)."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import get_current_user, require_admin

import alert_engine as ae
import telegram_notifier as tg

logger = logging.getLogger("alert_engine_routes")
router = APIRouter(prefix="/api/alert-engine", tags=["alert-engine"])


def _mask_token(cfg: dict) -> dict:
    out = dict(cfg)
    tok = out.get("telegram_bot_token") or ""
    if tok:
        out["telegram_bot_token_set"] = True
        out["telegram_bot_token"] = tok[:6] + "…" + tok[-4:] if len(tok) > 12 else "***"
    else:
        out["telegram_bot_token_set"] = False
        out["telegram_bot_token"] = ""
    return out


@router.get("/config")
async def get_engine_config(current_user: dict = Depends(get_current_user)):
    cfg = await ae.get_config(db)
    return _mask_token(cfg)


@router.put("/config")
async def update_engine_config(patch: dict, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    # Non sovrascrivere il token con il valore mascherato quando invariato
    if "telegram_bot_token" in patch:
        val = (patch.get("telegram_bot_token") or "").strip()
        if not val or "…" in val or val == "***":
            patch.pop("telegram_bot_token", None)
    cfg = await ae.save_config(db, patch)
    logger.info("alert-engine config updated by %s", current_user.get("email"))
    return _mask_token(cfg)


@router.get("/config/{client_id}")
async def get_client_override(client_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.alert_engine_config.find_one({"_id": f"client:{client_id}"}, {"_id": 0})
    return doc or {"override_enabled": False}


@router.put("/config/{client_id}")
async def set_client_override(client_id: str, patch: dict, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    allowed = set(ae.DEFAULT_CONFIG.keys()) | {"override_enabled"}
    update = {k: v for k, v in patch.items() if k in allowed}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.alert_engine_config.update_one({"_id": f"client:{client_id}"}, {"$set": update}, upsert=True)
    doc = await db.alert_engine_config.find_one({"_id": f"client:{client_id}"}, {"_id": 0})
    return doc


@router.get("/status")
async def engine_status(current_user: dict = Depends(get_current_user)):
    rt = await db.alert_engine_config.find_one({"_id": "__runtime"}, {"_id": 0}) or {}
    vital_open = await db.vital_offline_state.count_documents({})
    datto_open = await db.datto_offline_state.count_documents({})
    return {"last_run": rt, "vital_offline_tracked": vital_open, "datto_offline_tracked": datto_open}


@router.post("/run-now")
async def run_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    engine = ae.AlertEngine(db)
    result = await engine.run_once()
    return {"ok": True, "result": result}


@router.get("/match-coverage")
async def match_coverage(current_user: dict = Depends(get_current_user)):
    """Trasparenza affidabilita': per ogni cliente mostra quanti device Datto
    sono agganciati (matched) vs ciechi, i match a bassa confidenza da rivedere,
    e lo stato di affidabilita' delle sorgenti (source-health)."""
    import correlation_engine as ce
    cfg = await ae.get_config(db)
    ctx = await ce.build_context(db, cfg)
    health = ctx.get("source_health") or {}

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    names = {c.get("id"): c.get("name") for c in clients}

    # Aggregati Datto per cliente
    datto_by_client: dict = {}
    async for d in db.datto_devices.find(
        {}, {"_id": 0, "client_id": 1, "matched": 1, "online": 1, "is_server": 1}
    ):
        cid = d.get("client_id")
        if not cid:
            continue
        a = datto_by_client.setdefault(cid, {"total": 0, "matched": 0, "unmatched": 0,
                                             "servers": 0, "servers_matched": 0})
        a["total"] += 1
        if d.get("matched"):
            a["matched"] += 1
        else:
            a["unmatched"] += 1
        if d.get("is_server"):
            a["servers"] += 1
            if d.get("matched"):
                a["servers_matched"] += 1

    # Match a bassa confidenza (solo hostname/ip) per cliente
    lowconf_by_client: dict = {}
    async for md in db.managed_devices.find(
        {"datto_uid": {"$exists": True}},
        {"_id": 0, "client_id": 1, "datto_match_confidence": 1}
    ):
        if (md.get("datto_match_confidence") or 100) < 90:
            cid = md.get("client_id")
            lowconf_by_client[cid] = lowconf_by_client.get(cid, 0) + 1

    out = []
    for cid in set(datto_by_client) | set(health):
        a = datto_by_client.get(cid, {"total": 0, "matched": 0, "unmatched": 0,
                                      "servers": 0, "servers_matched": 0})
        sh = health.get(cid, {})
        total = a["total"]
        out.append({
            "client_id": cid,
            "client_name": names.get(cid) or (cid[:8] if cid else ""),
            "datto_total": total,
            "datto_matched": a["matched"],
            "datto_unmatched": a["unmatched"],
            "match_rate": round(a["matched"] / total * 100, 1) if total else None,
            "servers_total": a["servers"],
            "servers_matched": a["servers_matched"],
            "low_confidence_matches": lowconf_by_client.get(cid, 0),
            "connector_reliable": sh.get("connector_reliable"),
            "datto_reliable": sh.get("datto_reliable"),
            "datto_reason": sh.get("datto_reason"),
            "internet_up": sh.get("internet_up"),
        })
    out.sort(key=lambda x: (x["match_rate"] if x["match_rate"] is not None else 101))
    return {"clients": out}


@router.post("/telegram/test")
async def telegram_test(body: dict = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    body = body or {}
    res = await tg.send_telegram_text(
        db,
        text="\u2705 <b>Test Argus Alert Engine</b>\n\nSe leggi questo messaggio, le notifiche Telegram sono configurate correttamente.",
        chat_id=body.get("chat_id"),
        token=body.get("token"),
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error") or res.get("detail") or "Invio fallito")
    return res


@router.get("/telegram/detect-chats")
async def telegram_detect(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await tg.detect_chats(db)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error") or res.get("detail") or "getUpdates fallito")
    return res
