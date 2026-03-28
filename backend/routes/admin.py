"""Admin user management routes."""
from fastapi import APIRouter, Depends, HTTPException
import uuid
import base64
from datetime import datetime, timezone

from database import db
from models import AdminUserCreate, AdminUserUpdate, TwoFactorVerify
from security import security_manager
from audit import AuditAction
from deps import get_current_user, require_admin, audit_logger

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    users = await db.users.find({}, {"_id": 0, "password_hash": 0, "totp_secret": 0, "totp_secret_pending": 0}).to_list(500)
    return users


@router.post("/admin/users")
async def admin_create_user(user: AdminUserCreate, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email gia' registrata")
    if user.role not in ["admin", "operator", "viewer"]:
        raise HTTPException(status_code=400, detail="Ruolo non valido. Usa: admin, operator, viewer")
    user_doc = {
        "id": str(uuid.uuid4()), "email": user.email, "name": user.name,
        "password_hash": security_manager.hash_password(user.password),
        "role": user.role, "two_factor_enabled": False, "totp_secret": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    await audit_logger.log(
        AuditAction.REGISTER, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"created_user": user.email, "role": user.role}
    )
    return {
        "id": user_doc["id"], "email": user_doc["email"], "name": user_doc["name"],
        "role": user_doc["role"], "two_factor_enabled": False, "created_at": user_doc["created_at"]
    }


@router.put("/admin/users/{user_id}")
async def admin_update_user(user_id: str, update: AdminUserUpdate, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    update_fields = {}
    if update.name is not None:
        update_fields["name"] = update.name
    if update.role is not None:
        if update.role not in ["admin", "operator", "viewer"]:
            raise HTTPException(status_code=400, detail="Ruolo non valido")
        update_fields["role"] = update.role
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")
    await db.users.update_one({"id": user_id}, {"$set": update_fields})
    await audit_logger.log(
        AuditAction.REGISTER, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"updated_user": target["email"], "changes": update_fields}
    )
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "totp_secret": 0, "totp_secret_pending": 0})
    return updated


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso")
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    await db.users.delete_one({"id": user_id})
    await audit_logger.log(
        AuditAction.REGISTER, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"deleted_user": target["email"]}
    )
    return {"deleted": True}


@router.post("/admin/users/{user_id}/reset-2fa")
async def admin_reset_2fa(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"two_factor_enabled": False}, "$unset": {"totp_secret": "", "totp_secret_pending": ""}}
    )
    await audit_logger.log(
        AuditAction.TWO_FA_DISABLED, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"reset_2fa_for": target["email"]}
    )
    return {"reset": True}


@router.post("/admin/users/{user_id}/force-2fa")
async def admin_force_setup_2fa(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    secret = security_manager.generate_totp_secret()
    totp_uri = security_manager.get_totp_uri(secret, target["email"])
    qr_code = security_manager.generate_qr_code(totp_uri)
    await db.users.update_one({"id": user_id}, {"$set": {"totp_secret_pending": secret}})
    return {
        "secret": secret, "qr_code": base64.b64encode(qr_code).decode('utf-8'),
        "uri": totp_uri, "user_email": target["email"]
    }


@router.post("/admin/users/{user_id}/confirm-2fa")
async def admin_confirm_2fa(user_id: str, verify: TwoFactorVerify, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    pending_secret = target.get("totp_secret_pending")
    if not pending_secret:
        raise HTTPException(status_code=400, detail="Nessun setup 2FA in corso per questo utente")
    if security_manager.verify_totp(pending_secret, verify.code):
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"totp_secret": pending_secret, "two_factor_enabled": True}, "$unset": {"totp_secret_pending": ""}}
        )
        return {"enabled": True}
    else:
        raise HTTPException(status_code=401, detail="Codice non valido")
