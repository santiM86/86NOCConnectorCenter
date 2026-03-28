"""Authentication routes: login, register, 2FA, refresh tokens."""
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
import jwt
import base64
from datetime import datetime, timezone

from database import db
from models import UserCreate, UserLogin, TwoFactorSetup, TwoFactorVerify
from security import security_manager
from audit import AuditAction
from deps import (
    security, limiter, audit_logger, security_hardening,
    JWT_SECRET, JWT_ALGORITHM,
    create_token, get_current_user, auto_ban_check,
    create_refresh_token, store_refresh_token, check_nosql_injection,
)
import uuid

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, user: UserCreate):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        await audit_logger.log(
            AuditAction.REGISTER, user_email=user.email,
            ip_address=request.client.host if request.client else None,
            success=False, details={"reason": "Email already registered"}
        )
        raise HTTPException(status_code=400, detail="Email already registered")

    user_count = await db.users.count_documents({})
    role = "admin" if user_count == 0 else "operator"

    user_doc = {
        "id": str(uuid.uuid4()), "email": user.email, "name": user.name,
        "password_hash": security_manager.hash_password(user.password),
        "role": role, "two_factor_enabled": False, "totp_secret": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    await audit_logger.log(
        AuditAction.REGISTER, user_id=user_doc["id"], user_email=user_doc["email"],
        ip_address=request.client.host if request.client else None
    )
    token = create_token(user_doc["id"], user_doc["email"])
    return {
        "token": token,
        "user": {"id": user_doc["id"], "email": user_doc["email"], "name": user_doc["name"], "role": user_doc["role"], "two_factor_enabled": False}
    }


@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, credentials: UserLogin):
    client_ip = request.client.host if request.client else "unknown"

    try:
        is_locked = await security_hardening.is_account_locked(credentials.email)
        if is_locked:
            await audit_logger.log(
                AuditAction.LOGIN_FAILED, user_email=credentials.email,
                ip_address=client_ip, success=False,
                details={"reason": "Account locked"}, severity="critical"
            )
            raise HTTPException(status_code=423, detail="Account bloccato per troppi tentativi. Riprova tra 30 minuti.")
    except HTTPException:
        raise
    except Exception:
        pass

    check_nosql_injection({"email": credentials.email})
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})

    if not user:
        await audit_logger.log(
            AuditAction.LOGIN_FAILED, user_email=credentials.email,
            ip_address=client_ip, success=False,
            details={"reason": "User not found"}, severity="warning"
        )
        try: await security_hardening.record_failed_login(credentials.email, client_ip)
        except Exception: pass
        try: await auto_ban_check(client_ip)
        except Exception: pass
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not security_manager.verify_password(credentials.password, user["password_hash"]):
        await audit_logger.log(
            AuditAction.LOGIN_FAILED, user_id=user["id"], user_email=credentials.email,
            ip_address=client_ip, success=False,
            details={"reason": "Invalid password"}, severity="warning"
        )
        try: await security_hardening.record_failed_login(credentials.email, client_ip)
        except Exception: pass
        try: await auto_ban_check(client_ip)
        except Exception: pass
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try: await security_hardening.clear_failed_logins(credentials.email)
    except Exception: pass

    if security_manager.needs_rehash(user["password_hash"]):
        new_hash = security_manager.hash_password(credentials.password)
        await db.users.update_one({"id": user["id"]}, {"$set": {"password_hash": new_hash}})

    requires_2fa = user.get("two_factor_enabled", False)
    await audit_logger.log(
        AuditAction.LOGIN_SUCCESS, user_id=user["id"], user_email=user["email"],
        ip_address=request.client.host if request.client else None,
        details={"requires_2fa": requires_2fa}
    )

    token = create_token(user["id"], user["email"], requires_2fa=requires_2fa)
    refresh_token = create_refresh_token(user["id"])
    await store_refresh_token(user["id"], refresh_token, client_ip)

    return {
        "token": token, "refresh_token": refresh_token, "requires_2fa": requires_2fa,
        "user": {
            "id": user["id"], "email": user["email"], "name": user["name"],
            "role": user["role"], "two_factor_enabled": user.get("two_factor_enabled", False)
        }
    }


@router.post("/auth/verify-2fa")
@limiter.limit("5/minute")
async def verify_2fa(request: Request, verify: TwoFactorVerify, credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.get("totp_secret"):
            raise HTTPException(status_code=400, detail="2FA not configured")
        if security_manager.verify_totp(user["totp_secret"], verify.code):
            await audit_logger.log(
                AuditAction.TWO_FA_VERIFIED, user_id=user["id"], user_email=user["email"],
                ip_address=request.client.host if request.client else None
            )
            token = create_token(user["id"], user["email"], requires_2fa=False)
            return {"token": token, "verified": True}
        else:
            await audit_logger.log(
                AuditAction.TWO_FA_FAILED, user_id=user["id"], user_email=user["email"],
                ip_address=request.client.host if request.client else None,
                success=False, severity="warning"
            )
            raise HTTPException(status_code=401, detail="Invalid 2FA code")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/auth/refresh")
@limiter.limit("5/minute")
async def refresh_access_token(request: Request):
    body = await request.json()
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token required")
    token_doc = await db.refresh_tokens.find_one({"token": refresh_token, "revoked": False}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")
    if token_doc.get("expires_at", "") < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=401, detail="Refresh token expired")
    user = await db.users.find_one({"id": token_doc["user_id"]}, {"_id": 0, "password_hash": 0, "totp_secret": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    await db.refresh_tokens.update_one({"token": refresh_token}, {"$set": {"revoked": True}})
    new_refresh = create_refresh_token(user["id"])
    await store_refresh_token(user["id"], new_refresh, request.client.host if request.client else "unknown")
    new_access = create_token(user["id"], user["email"])
    await audit_logger.log(
        AuditAction.LOGIN_SUCCESS, user_id=user["id"], user_email=user["email"],
        ip_address=request.client.host if request.client else None,
        details={"method": "refresh_token"}
    )
    return {
        "token": new_access, "refresh_token": new_refresh,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]}
    }


@router.post("/auth/logout")
async def logout(request: Request, current_user: dict = Depends(get_current_user)):
    await db.refresh_tokens.update_many({"user_id": current_user["id"]}, {"$set": {"revoked": True}})
    await audit_logger.log(
        AuditAction.LOGOUT, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=request.client.host if request.client else None
    )
    return {"status": "ok"}


@router.post("/auth/setup-2fa")
async def setup_2fa(setup: TwoFactorSetup, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    if not security_manager.verify_password(setup.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    secret = security_manager.generate_totp_secret()
    totp_uri = security_manager.get_totp_uri(secret, user["email"])
    qr_code = security_manager.generate_qr_code(totp_uri)
    await db.users.update_one({"id": user["id"]}, {"$set": {"totp_secret_pending": secret}})
    return {"secret": secret, "qr_code": base64.b64encode(qr_code).decode('utf-8'), "uri": totp_uri}


@router.post("/auth/confirm-2fa")
async def confirm_2fa(verify: TwoFactorVerify, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    pending_secret = user.get("totp_secret_pending")
    if not pending_secret:
        raise HTTPException(status_code=400, detail="No 2FA setup in progress")
    if security_manager.verify_totp(pending_secret, verify.code):
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"totp_secret": pending_secret, "two_factor_enabled": True}, "$unset": {"totp_secret_pending": ""}}
        )
        await audit_logger.log(AuditAction.TWO_FA_ENABLED, user_id=user["id"], user_email=user["email"], ip_address=current_user.get("_request_ip"))
        return {"enabled": True, "message": "2FA enabled successfully"}
    else:
        raise HTTPException(status_code=401, detail="Invalid verification code")


@router.post("/auth/disable-2fa")
async def disable_2fa(setup: TwoFactorSetup, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    if not security_manager.verify_password(setup.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"two_factor_enabled": False}, "$unset": {"totp_secret": "", "totp_secret_pending": ""}}
    )
    await audit_logger.log(AuditAction.TWO_FA_DISABLED, user_id=user["id"], user_email=user["email"], ip_address=current_user.get("_request_ip"))
    return {"disabled": True, "message": "2FA disabled"}


@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"], "email": current_user["email"],
        "name": current_user["name"], "role": current_user["role"],
        "two_factor_enabled": current_user.get("two_factor_enabled", False)
    }


# Need to import HTTPException at module level
from fastapi import HTTPException
