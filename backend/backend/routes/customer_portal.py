"""
Customer Portal — login sub-ridotto per cliente finale.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid
import hashlib
import os
import jwt
import logging

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/customer", tags=["customer_portal"])
audit = logging.getLogger("audit")

JWT_SECRET = os.environ.get("SECRET_KEY", "change-me-customer")
JWT_ALGO = "HS256"
JWT_EXPIRE_HOURS = 12


class CustomerLogin(BaseModel):
    email: str
    password: str


class CustomerUserCreate(BaseModel):
    email: str
    password: str
    client_id: str
    name: Optional[str] = None


def _hash_pwd(pwd: str) -> str:
    salt = JWT_SECRET[:16]
    return hashlib.sha256(f"{salt}:{pwd}".encode()).hexdigest()


def _make_token(user: dict) -> str:
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "client_id": user["client_id"],
        "role": "customer",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def _require_customer(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required")
    try:
        payload = jwt.decode(auth[7:], JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("role") != "customer":
            raise HTTPException(status_code=403, detail="Role customer richiesto")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token scaduto")
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalido")


@router.post("/login")
async def customer_login(req: CustomerLogin):
    user = await db.customer_users.find_one({"email": req.email.lower().strip()}, {"_id": 0})
    if not user or user.get("password_hash") != _hash_pwd(req.password):
        audit.info(f"[AUDIT] customer_login_fail | email={req.email}")
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    token = _make_token(user)
    audit.info(f"[AUDIT] customer_login_ok | email={req.email} | client_id={user['client_id']}")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"email": user["email"], "client_id": user["client_id"], "name": user.get("name")},
    }


@router.get("/dashboard")
async def customer_dashboard(request: Request):
    payload = await _require_customer(request)
    client_id = payload["client_id"]
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    devices_count = await db.managed_devices.count_documents({"client_id": client_id})
    alerts_active = await db.alerts.count_documents({"client_id": client_id, "status": "active"})
    alerts_critical = await db.alerts.count_documents({"client_id": client_id, "status": "active", "severity": "critical"})
    incidents_open = await db.incidents.count_documents({"client_id": client_id, "status": {"$in": ["open", "investigating", "identified", "in_progress"]}})
    recent_cursor = db.alerts.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "title": 1, "message": 1, "severity": 1, "status": 1,
         "device_ip": 1, "device_name": 1, "created_at": 1, "acknowledged_at": 1, "resolved_at": 1}
    ).sort("created_at", -1).limit(20)
    recent_alerts = [a async for a in recent_cursor]
    return {
        "client": client,
        "stats": {
            "devices": devices_count, "alerts_active": alerts_active,
            "alerts_critical": alerts_critical, "incidents_open": incidents_open,
        },
        "recent_alerts": recent_alerts,
    }


@router.get("/devices")
async def customer_devices(request: Request):
    payload = await _require_customer(request)
    cursor = db.managed_devices.find(
        {"client_id": payload["client_id"]},
        {"_id": 0, "id": 1, "ip": 1, "name": 1, "device_type": 1, "status": 1, "last_seen": 1}
    ).limit(200)
    return {"items": [d async for d in cursor]}


@router.get("/alerts")
async def customer_alerts(request: Request, status: Optional[str] = None, limit: int = 100):
    payload = await _require_customer(request)
    q = {"client_id": payload["client_id"]}
    if status:
        q["status"] = status
    cursor = db.alerts.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 500))
    return {"items": [a async for a in cursor]}


@router.get("/incidents")
async def customer_incidents(request: Request):
    payload = await _require_customer(request)
    cursor = db.incidents.find({"client_id": payload["client_id"]}, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"items": [i async for i in cursor]}


@router.post("/users")
async def create_customer_user(u: CustomerUserCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    client = await db.clients.find_one({"id": u.client_id}, {"_id": 0, "id": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    existing = await db.customer_users.find_one({"email": u.email.lower().strip()})
    if existing:
        raise HTTPException(status_code=409, detail="Email gia' esistente")
    doc = {
        "id": str(uuid.uuid4()),
        "email": u.email.lower().strip(),
        "name": u.name,
        "client_id": u.client_id,
        "password_hash": _hash_pwd(u.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("email"),
    }
    await db.customer_users.insert_one(doc)
    audit.info(f"[AUDIT] customer_user_create | by={current_user.get('email')} | email={u.email} | client_id={u.client_id}")
    return {"ok": True, "id": doc["id"]}


@router.get("/users")
async def list_customer_users(client_id: Optional[str] = None,
                               current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    q = {}
    if client_id:
        q["client_id"] = client_id
    cursor = db.customer_users.find(q, {"_id": 0, "password_hash": 0}).limit(500)
    return {"items": [u async for u in cursor]}


@router.delete("/users/{user_id}")
async def delete_customer_user(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.customer_users.delete_one({"id": user_id})
    return {"deleted": res.deleted_count > 0}
