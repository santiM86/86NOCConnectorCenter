"""
Web Console ENTERPRISE features v1
- Quick Access: recent + favorites + live sessions
- Connection audit per device
- Session Recording (opt-in)
- Session Share link (read-only, temporaneo)

Schema collections:
- web_console_history     : ogni session aperta (user, device, started_at, ended_at, requests_count, recorded)
- web_console_favorites   : preferiti per utente (user_email, device_ip, client_id, pinned_at)
- web_console_recordings  : body snapshot per ogni request se session has recording=True (TTL 30d)
- web_console_shares      : share token → session read-only (TTL custom)
"""
from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel
from typing import Optional
import uuid
import logging
import base64
import hashlib
import os
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["web_console_enterprise"])
audit = logging.getLogger("audit")

SHARE_TTL_MIN_DEFAULT = 15
SHARE_TTL_MIN_MAX = 60
RECORDING_TTL_DAYS = 30


# ====================== MODELS ======================
class FavoriteToggleRequest(BaseModel):
    device_ip: str
    client_id: Optional[str] = None


class RecordingStartRequest(BaseModel):
    enabled: bool = True


class ShareCreateRequest(BaseModel):
    ttl_minutes: int = SHARE_TTL_MIN_DEFAULT
    password: Optional[str] = None  # Opzionale: proteggi il link con password


class ShareValidateRequest(BaseModel):
    password: Optional[str] = None


# ====================== HELPERS ======================
def _hash_password(raw: str) -> str:
    salt = os.environ.get("SECRET_KEY", "argus-share-salt")[:32]
    return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()


async def _upsert_history_entry(session_id: str, user_email: str, client_id: str,
                                 device_ip: str, port: int, recorded: bool) -> None:
    """Crea record history all'apertura della console."""
    now = datetime.now(timezone.utc)
    await db.web_console_history.insert_one({
        "session_id": session_id,
        "user_email": user_email,
        "client_id": client_id,
        "device_ip": device_ip,
        "port": port,
        "started_at": now,
        "ended_at": None,
        "requests_count": 0,
        "recorded": recorded,
        "last_path": "/",
    })


# ====================== RECENT ======================
@router.get("/web-console/recent")
async def get_recent_sessions(limit: int = 10, current_user: dict = Depends(get_current_user)):
    """Ultime N sessioni Web Console dell'utente corrente, de-duplicate per device."""
    user_email = current_user.get("email", "")
    limit = max(1, min(limit, 50))
    seen = set()
    rows = []
    cursor = db.web_console_history.find(
        {"user_email": user_email},
        {"_id": 0, "session_id": 1, "device_ip": 1, "port": 1, "client_id": 1,
         "started_at": 1, "ended_at": 1, "requests_count": 1, "recorded": 1}
    ).sort("started_at", -1).limit(limit * 5)
    async for r in cursor:
        key = (r.get("device_ip"), r.get("port"))
        if key in seen:
            continue
        seen.add(key)
        # Lookup device name for better UX
        md = await db.managed_devices.find_one(
            {"ip": r.get("device_ip")}, {"_id": 0, "name": 1, "device_type": 1}
        )
        r["device_name"] = (md or {}).get("name")
        r["device_type"] = (md or {}).get("device_type")
        # Lookup client name
        cl = await db.clients.find_one({"id": r.get("client_id")}, {"_id": 0, "name": 1})
        r["client_name"] = (cl or {}).get("name")
        rows.append(r)
        if len(rows) >= limit:
            break
    return {"items": rows}


# ====================== FAVORITES ======================
@router.get("/web-console/favorites")
async def list_favorites(current_user: dict = Depends(get_current_user)):
    user_email = current_user.get("email", "")
    cursor = db.web_console_favorites.find(
        {"user_email": user_email}, {"_id": 0}
    ).sort("pinned_at", -1)
    items = []
    async for r in cursor:
        md = await db.managed_devices.find_one(
            {"ip": r.get("device_ip")}, {"_id": 0, "name": 1, "device_type": 1, "web_console_port": 1, "client_id": 1}
        )
        if not md:
            continue  # Device rimosso
        cl = await db.clients.find_one({"id": md.get("client_id")}, {"_id": 0, "name": 1})
        r["device_name"] = md.get("name")
        r["device_type"] = md.get("device_type")
        r["port"] = md.get("web_console_port") or r.get("port") or 443
        r["client_id"] = md.get("client_id")
        r["client_name"] = (cl or {}).get("name")
        items.append(r)
    return {"items": items}


@router.post("/web-console/favorites/toggle")
async def toggle_favorite(req: FavoriteToggleRequest, current_user: dict = Depends(get_current_user)):
    user_email = current_user.get("email", "")
    existing = await db.web_console_favorites.find_one({
        "user_email": user_email, "device_ip": req.device_ip
    })
    if existing:
        await db.web_console_favorites.delete_one({"_id": existing["_id"]})
        audit.info(f"[AUDIT] web_console_favorite_remove | user={user_email} | device={req.device_ip}")
        return {"pinned": False}
    md = await db.managed_devices.find_one(
        {"ip": req.device_ip}, {"_id": 0, "client_id": 1, "web_console_port": 1, "name": 1}
    )
    if not md:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.web_console_favorites.insert_one({
        "user_email": user_email,
        "device_ip": req.device_ip,
        "client_id": md.get("client_id"),
        "port": md.get("web_console_port") or 443,
        "device_name": md.get("name"),
        "pinned_at": datetime.now(timezone.utc),
    })
    audit.info(f"[AUDIT] web_console_favorite_add | user={user_email} | device={req.device_ip}")
    return {"pinned": True}


# ====================== LIVE SESSIONS ======================
@router.get("/web-console/live-sessions")
async def list_live_sessions(current_user: dict = Depends(get_current_user)):
    """Sessioni aperte ADESSO da qualsiasi utente (solo admin/operator).
    Utile per vedere 'chi sta facendo cosa' in tempo reale."""
    role = current_user.get("role", "")
    if role not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    now = datetime.now(timezone.utc)
    cursor = db.web_console_tokens.find(
        {"expires_at": {"$gt": now}},
        {"_id": 0, "session_id": 1, "user_email": 1, "device_ip": 1, "port": 1,
         "client_id": 1, "created_at": 1, "expires_at": 1}
    ).sort("created_at", -1).limit(50)
    items = []
    async for r in cursor:
        md = await db.managed_devices.find_one(
            {"ip": r.get("device_ip")}, {"_id": 0, "name": 1, "device_type": 1}
        )
        r["device_name"] = (md or {}).get("name")
        r["device_type"] = (md or {}).get("device_type")
        cl = await db.clients.find_one({"id": r.get("client_id")}, {"_id": 0, "name": 1})
        r["client_name"] = (cl or {}).get("name")
        items.append(r)
    return {"items": items}


# ====================== AUDIT PER DEVICE ======================
@router.get("/web-console/history/device/{device_ip}")
async def device_console_history(device_ip: str, limit: int = 50,
                                  current_user: dict = Depends(get_current_user)):
    """Chi ha aperto la Web Console di questo device, quando, per quanto, e se registrato."""
    role = current_user.get("role", "")
    if role == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    limit = max(1, min(limit, 200))
    cursor = db.web_console_history.find(
        {"device_ip": device_ip},
        {"_id": 0}
    ).sort("started_at", -1).limit(limit)
    items = []
    async for r in cursor:
        started = r.get("started_at")
        ended = r.get("ended_at")
        duration_s = None
        if started:
            end_ref = ended or datetime.now(timezone.utc)
            if isinstance(started, str):
                started = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if isinstance(end_ref, str):
                end_ref = datetime.fromisoformat(end_ref.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if isinstance(end_ref, datetime) and end_ref.tzinfo is None:
                end_ref = end_ref.replace(tzinfo=timezone.utc)
            try:
                duration_s = int((end_ref - started).total_seconds())
            except Exception:
                duration_s = None
        r["duration_seconds"] = duration_s
        items.append(r)
    return {"items": items}


# ====================== RECORDING ======================
@router.post("/web-console/recording/{session_id}/toggle")
async def toggle_recording(session_id: str, req: RecordingStartRequest,
                            current_user: dict = Depends(get_current_user)):
    user_email = current_user.get("email", "")
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id, "user_email": user_email}, {"_id": 0}
    )
    if not tok:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.web_console_tokens.update_one(
        {"session_id": session_id},
        {"$set": {"recording": bool(req.enabled)}}
    )
    await db.web_console_history.update_many(
        {"session_id": session_id},
        {"$set": {"recorded": bool(req.enabled)}}
    )
    audit.info(f"[AUDIT] web_console_recording_toggle | user={user_email} | session={session_id} | enabled={req.enabled}")
    return {"recording": bool(req.enabled)}


@router.get("/web-console/recording/{session_id}")
async def get_recording_timeline(session_id: str, current_user: dict = Depends(get_current_user)):
    """Timeline navigabile della sessione registrata."""
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id},
        {"_id": 0, "user_email": 1, "device_ip": 1, "port": 1, "created_at": 1, "recording": 1}
    )
    if not tok:
        # Cerca anche in history (sessione chiusa)
        hist = await db.web_console_history.find_one({"session_id": session_id}, {"_id": 0})
        if not hist:
            raise HTTPException(status_code=404, detail="Session not found")
        tok = hist

    if tok.get("user_email") != current_user.get("email") and current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Not session owner")

    cursor = db.web_proxy_requests.find(
        {"session_id": session_id},
        {"_id": 0, "request_id": 1, "path": 1, "method": 1, "created_at": 1, "status": 1, "response": 1}
    ).sort("created_at", 1).limit(500)
    timeline = []
    async for r in cursor:
        resp = r.get("response") or {}
        rh = resp.get("response_headers") or {}
        timeline.append({
            "request_id": (r.get("request_id") or "")[:8],
            "path": r.get("path"),
            "method": r.get("method"),
            "at": r.get("created_at"),
            "http_status": resp.get("status_code"),
            "content_type": resp.get("content_type") or rh.get("Content-Type"),
            "body_size": len(base64.b64decode(resp["body_b64"])) if resp.get("body_b64") else len(resp.get("body") or ""),
        })
    return {"session": tok, "timeline": timeline}


# ====================== SESSION SHARE ======================
@router.post("/web-console/share/{session_id}")
async def create_share_link(session_id: str, req: ShareCreateRequest,
                             current_user: dict = Depends(get_current_user)):
    """Genera un share-token temporaneo (read-only) per far vedere la console a terzi
    senza richiedere login ad ARGUS. TTL 15 min default, max 60 min."""
    user_email = current_user.get("email", "")
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id, "user_email": user_email}, {"_id": 0}
    )
    if not tok:
        raise HTTPException(status_code=404, detail="Session not found")
    ttl = max(1, min(req.ttl_minutes, SHARE_TTL_MIN_MAX))
    now = datetime.now(timezone.utc)
    share_token = str(uuid.uuid4())
    await db.web_console_shares.insert_one({
        "share_token": share_token,
        "session_id": session_id,
        "device_ip": tok["device_ip"],
        "port": tok["port"],
        "shared_by": user_email,
        "created_at": now,
        "expires_at": now + timedelta(minutes=ttl),
        "password_hash": _hash_password(req.password) if req.password else None,
        "views_count": 0,
        "read_only": True,
    })
    audit.info(f"[AUDIT] web_console_share_create | user={user_email} | session={session_id} | ttl_min={ttl} | protected={bool(req.password)}")
    return {
        "share_token": share_token,
        "share_url": f"/web-console/shared/{share_token}",
        "expires_in_seconds": ttl * 60,
        "password_protected": bool(req.password),
    }


@router.post("/web-console/shared/{share_token}/validate")
async def validate_share_access(share_token: str, req: ShareValidateRequest):
    """Endpoint pubblico: valida un share-token e ritorna l'iframe_url del proxy LIVE.
    Nessun auth required (bypass get_current_user) — il capability e' il token stesso."""
    now = datetime.now(timezone.utc)
    share = await db.web_console_shares.find_one({"share_token": share_token}, {"_id": 0})
    if not share:
        raise HTTPException(status_code=404, detail="Share non trovato o scaduto")
    exp = share.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    if isinstance(exp, datetime) and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp < now:
        raise HTTPException(status_code=410, detail="Share scaduto")
    if share.get("password_hash"):
        if not req.password or _hash_password(req.password) != share["password_hash"]:
            raise HTTPException(status_code=401, detail="Password errata")
    await db.web_console_shares.update_one(
        {"share_token": share_token},
        {"$inc": {"views_count": 1}}
    )
    audit.info(f"[AUDIT] web_console_share_view | token={share_token[:8]}... | session={share['session_id']} | views={share.get('views_count',0)+1}")
    return {
        "iframe_url": f"/api/web-proxy/live/{share['session_id']}/{share['device_ip']}/{share['port']}/",
        "device_ip": share["device_ip"],
        "port": share["port"],
        "shared_by": share["shared_by"],
        "read_only": share.get("read_only", True),
        "expires_at": share["expires_at"].isoformat() if isinstance(share["expires_at"], datetime) else share["expires_at"],
    }


@router.delete("/web-console/share/{share_token}")
async def revoke_share(share_token: str, current_user: dict = Depends(get_current_user)):
    user_email = current_user.get("email", "")
    res = await db.web_console_shares.delete_one({
        "share_token": share_token, "shared_by": user_email
    })
    if res.deleted_count == 0 and current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=404, detail="Share non trovato")
    if res.deleted_count == 0:
        # Admin può revocare anche share di altri
        await db.web_console_shares.delete_one({"share_token": share_token})
    audit.info(f"[AUDIT] web_console_share_revoke | user={user_email} | token={share_token[:8]}...")
    return {"revoked": True}
