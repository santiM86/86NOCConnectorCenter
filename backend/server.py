"""
NOC Alert Command Center - Main Server
Enterprise-grade security with AES-256-GCM, Argon2id, 2FA, Rate Limiting, and Audit Logging
"""
from fastapi import FastAPI, APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, status, Request, Response, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
import logging
import shutil
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import asyncio
import json
import base64

# Local imports
from security import security_manager
from audit import AuditLogger, AuditAction
from notifications import NotificationService, NotificationChannel, NotificationPriority
from redfish import RedfishPoller
from correlation import AlertCorrelationManager
from maintenance import MaintenanceManager
from sla import SLAManager
from security_hardening import SecurityHardening

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'noc-alert-command-center-secret-key-2024')
JWT_ALGORITHM = "HS256"

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize services
audit_logger = AuditLogger(db)
notification_service = NotificationService(db)
redfish_poller = RedfishPoller(db, notification_service)
redfish_poller.set_security_manager(security_manager)
correlation_manager = AlertCorrelationManager(db)
maintenance_manager = MaintenanceManager(db)
sla_manager = SLAManager(db, notification_service)
security_hardening = SecurityHardening(db)

# Create the main app
app = FastAPI(
    title="NOC Alert Command Center API",
    description="Enterprise-grade alert management system with military-grade security",
    version="2.0.0"
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

security = HTTPBearer()

# ==================== WEBSOCKET MANAGER ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# ==================== VERSION COMPARISON ====================

def parse_version(version_str: str):
    """Parse version string like '1.7.0' into tuple (1, 7, 0) for comparison."""
    try:
        parts = version_str.strip().lstrip("v").split(".")
        return tuple(int(p) for p in parts)
    except:
        return (0, 0, 0)

def is_newer_version(published: str, current: str) -> bool:
    """Returns True if published version is strictly newer than current."""
    return parse_version(published) > parse_version(current)

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TwoFactorSetup(BaseModel):
    password: str

class TwoFactorVerify(BaseModel):
    code: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    role: str = "operator"
    two_factor_enabled: bool = False

class ClientCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    contact_email: Optional[str] = ""

class ClientResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    description: str
    contact_email: str
    api_key: Optional[str] = ""
    created_at: str

class DeviceCreate(BaseModel):
    client_id: str
    name: str
    device_type: str
    ip_address: str
    hostname: Optional[str] = ""
    location: Optional[str] = ""
    redfish_enabled: Optional[bool] = False

class DeviceCredentials(BaseModel):
    username: str
    password: str

class DeviceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: str
    client_name: Optional[str] = ""
    name: str
    device_type: str
    ip_address: str
    hostname: str
    location: str
    status: str = "active"
    redfish_enabled: bool = False
    has_credentials: bool = False
    last_poll: Optional[str] = None
    health_status: Optional[str] = None
    created_at: str

class AlertCreate(BaseModel):
    client_id: str
    device_id: str
    severity: str
    source_type: str
    title: str
    message: str
    raw_data: Optional[str] = ""

class AlertResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: str
    client_name: Optional[str] = ""
    device_id: str
    device_name: Optional[str] = ""
    device_type: Optional[str] = ""
    ip_address: Optional[str] = ""
    severity: str
    source_type: str
    title: str
    message: str
    raw_data: str
    status: str = "active"
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str

class AlertUpdate(BaseModel):
    status: Optional[str] = None
    acknowledged_by: Optional[str] = None

class NotificationSettingsUpdate(BaseModel):
    email_enabled: bool = True
    push_enabled: bool = True
    webhook_teams: Optional[str] = None
    webhook_slack: Optional[str] = None
    webhook_telegram: Optional[str] = None
    webhook_generic: Optional[str] = None

class RedfishTestRequest(BaseModel):
    ip_address: str
    username: str
    password: str

# ==================== AUTH HELPERS ====================

def create_token(user_id: str, email: str, requires_2fa: bool = False) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "requires_2fa": requires_2fa,
        "exp": datetime.now(timezone.utc).timestamp() + 86400
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Check if 2FA is required but not completed
        if payload.get("requires_2fa"):
            raise HTTPException(status_code=403, detail="2FA verification required")
        
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0, "password_hash": 0, "totp_secret": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Add request info for audit logging
        user["_request_ip"] = request.client.host if request.client else "unknown"
        user["_user_agent"] = request.headers.get("user-agent", "unknown")
        
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, user: UserCreate):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        await audit_logger.log(
            AuditAction.REGISTER,
            user_email=user.email,
            ip_address=request.client.host if request.client else None,
            success=False,
            details={"reason": "Email already registered"}
        )
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # First user becomes admin
    user_count = await db.users.count_documents({})
    role = "admin" if user_count == 0 else "operator"
    
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": user.email,
        "name": user.name,
        "password_hash": security_manager.hash_password(user.password),
        "role": role,
        "two_factor_enabled": False,
        "totp_secret": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    await audit_logger.log(
        AuditAction.REGISTER,
        user_id=user_doc["id"],
        user_email=user_doc["email"],
        ip_address=request.client.host if request.client else None
    )
    
    token = create_token(user_doc["id"], user_doc["email"])
    return {
        "token": token,
        "user": {
            "id": user_doc["id"],
            "email": user_doc["email"],
            "name": user_doc["name"],
            "role": user_doc["role"],
            "two_factor_enabled": False
        }
    }

@api_router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    
    if not user:
        await audit_logger.log(
            AuditAction.LOGIN_FAILED,
            user_email=credentials.email,
            ip_address=request.client.host if request.client else None,
            success=False,
            details={"reason": "User not found"},
            severity="warning"
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not security_manager.verify_password(credentials.password, user["password_hash"]):
        await audit_logger.log(
            AuditAction.LOGIN_FAILED,
            user_id=user["id"],
            user_email=credentials.email,
            ip_address=request.client.host if request.client else None,
            success=False,
            details={"reason": "Invalid password"},
            severity="warning"
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if password needs rehash (security upgrade)
    if security_manager.needs_rehash(user["password_hash"]):
        new_hash = security_manager.hash_password(credentials.password)
        await db.users.update_one({"id": user["id"]}, {"$set": {"password_hash": new_hash}})
    
    # Check if 2FA is enabled
    requires_2fa = user.get("two_factor_enabled", False)
    
    await audit_logger.log(
        AuditAction.LOGIN_SUCCESS,
        user_id=user["id"],
        user_email=user["email"],
        ip_address=request.client.host if request.client else None,
        details={"requires_2fa": requires_2fa}
    )
    
    token = create_token(user["id"], user["email"], requires_2fa=requires_2fa)
    
    return {
        "token": token,
        "requires_2fa": requires_2fa,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "two_factor_enabled": user.get("two_factor_enabled", False)
        }
    }

@api_router.post("/auth/verify-2fa")
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
                AuditAction.TWO_FA_VERIFIED,
                user_id=user["id"],
                user_email=user["email"],
                ip_address=request.client.host if request.client else None
            )
            
            # Issue new token without 2FA requirement
            token = create_token(user["id"], user["email"], requires_2fa=False)
            return {"token": token, "verified": True}
        else:
            await audit_logger.log(
                AuditAction.TWO_FA_FAILED,
                user_id=user["id"],
                user_email=user["email"],
                ip_address=request.client.host if request.client else None,
                success=False,
                severity="warning"
            )
            raise HTTPException(status_code=401, detail="Invalid 2FA code")
            
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@api_router.post("/auth/setup-2fa")
async def setup_2fa(setup: TwoFactorSetup, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    
    if not security_manager.verify_password(setup.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # Generate new TOTP secret
    secret = security_manager.generate_totp_secret()
    totp_uri = security_manager.get_totp_uri(secret, user["email"])
    qr_code = security_manager.generate_qr_code(totp_uri)
    
    # Temporarily store secret (not enabled until verified)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"totp_secret_pending": secret}}
    )
    
    return {
        "secret": secret,
        "qr_code": base64.b64encode(qr_code).decode('utf-8'),
        "uri": totp_uri
    }

@api_router.post("/auth/confirm-2fa")
async def confirm_2fa(verify: TwoFactorVerify, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    
    pending_secret = user.get("totp_secret_pending")
    if not pending_secret:
        raise HTTPException(status_code=400, detail="No 2FA setup in progress")
    
    if security_manager.verify_totp(pending_secret, verify.code):
        await db.users.update_one(
            {"id": user["id"]},
            {
                "$set": {
                    "totp_secret": pending_secret,
                    "two_factor_enabled": True
                },
                "$unset": {"totp_secret_pending": ""}
            }
        )
        
        await audit_logger.log(
            AuditAction.TWO_FA_ENABLED,
            user_id=user["id"],
            user_email=user["email"],
            ip_address=current_user.get("_request_ip")
        )
        
        return {"enabled": True, "message": "2FA enabled successfully"}
    else:
        raise HTTPException(status_code=401, detail="Invalid verification code")

@api_router.post("/auth/disable-2fa")
async def disable_2fa(setup: TwoFactorSetup, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    
    if not security_manager.verify_password(setup.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {"two_factor_enabled": False},
            "$unset": {"totp_secret": "", "totp_secret_pending": ""}
        }
    )
    
    await audit_logger.log(
        AuditAction.TWO_FA_DISABLED,
        user_id=user["id"],
        user_email=user["email"],
        ip_address=current_user.get("_request_ip")
    )
    
    return {"disabled": True, "message": "2FA disabled"}

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "role": current_user["role"],
        "two_factor_enabled": current_user.get("two_factor_enabled", False)
    }

# ==================== ADMIN USER MANAGEMENT ====================

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str
    role: str = "operator"

class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None

def require_admin(current_user: dict):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")

@api_router.get("/admin/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    users = await db.users.find({}, {"_id": 0, "password_hash": 0, "totp_secret": 0, "totp_secret_pending": 0}).to_list(500)
    return users

@api_router.post("/admin/users")
async def admin_create_user(user: AdminUserCreate, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email già registrata")
    
    if user.role not in ["admin", "operator", "viewer"]:
        raise HTTPException(status_code=400, detail="Ruolo non valido. Usa: admin, operator, viewer")
    
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": user.email,
        "name": user.name,
        "password_hash": security_manager.hash_password(user.password),
        "role": user.role,
        "two_factor_enabled": False,
        "totp_secret": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    await audit_logger.log(
        AuditAction.REGISTER,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"created_user": user.email, "role": user.role}
    )
    
    return {
        "id": user_doc["id"],
        "email": user_doc["email"],
        "name": user_doc["name"],
        "role": user_doc["role"],
        "two_factor_enabled": False,
        "created_at": user_doc["created_at"]
    }

@api_router.put("/admin/users/{user_id}")
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
        AuditAction.REGISTER,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"updated_user": target["email"], "changes": update_fields}
    )
    
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "totp_secret": 0, "totp_secret_pending": 0})
    return updated

@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso")
    
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    
    await db.users.delete_one({"id": user_id})
    
    await audit_logger.log(
        AuditAction.REGISTER,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"deleted_user": target["email"]}
    )
    
    return {"deleted": True}

@api_router.post("/admin/users/{user_id}/reset-2fa")
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
        AuditAction.TWO_FA_DISABLED,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"reset_2fa_for": target["email"]}
    )
    
    return {"reset": True}

@api_router.post("/admin/users/{user_id}/force-2fa")
async def admin_force_setup_2fa(user_id: str, current_user: dict = Depends(get_current_user)):
    """Generate a TOTP QR code for a user (admin action to help setup)."""
    require_admin(current_user)
    
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    
    secret = security_manager.generate_totp_secret()
    totp_uri = security_manager.get_totp_uri(secret, target["email"])
    qr_code = security_manager.generate_qr_code(totp_uri)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"totp_secret_pending": secret}}
    )
    
    return {
        "secret": secret,
        "qr_code": base64.b64encode(qr_code).decode('utf-8'),
        "uri": totp_uri,
        "user_email": target["email"]
    }

@api_router.post("/admin/users/{user_id}/confirm-2fa")
async def admin_confirm_2fa(user_id: str, verify: TwoFactorVerify, current_user: dict = Depends(get_current_user)):
    """Confirm 2FA setup for a user by verifying their code."""
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

# ==================== CLIENT ROUTES ====================

@api_router.post("/clients", response_model=ClientResponse)
async def create_client(client: ClientCreate, current_user: dict = Depends(get_current_user)):
    api_key = f"noc_{uuid.uuid4().hex}"
    client_doc = {
        "id": str(uuid.uuid4()),
        "name": client.name,
        "description": client.description or "",
        "contact_email": client.contact_email or "",
        "api_key": api_key,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.clients.insert_one(client_doc)
    
    await audit_logger.log(
        AuditAction.CREATE_CLIENT,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client",
        resource_id=client_doc["id"],
        details={"name": client.name}
    )
    
    return ClientResponse(**client_doc)

@api_router.get("/clients", response_model=List[ClientResponse])
async def get_clients(current_user: dict = Depends(get_current_user)):
    clients = await db.clients.find({}, {"_id": 0}).to_list(1000)
    return [ClientResponse(**c) for c in clients]

@api_router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, current_user: dict = Depends(get_current_user)):
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientResponse(**client)

@api_router.delete("/clients/{client_id}")
async def delete_client(client_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.clients.delete_one({"id": client_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    
    await audit_logger.log(
        AuditAction.DELETE_CLIENT,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client",
        resource_id=client_id
    )
    
    return {"message": "Client deleted"}

# ==================== DEVICE ROUTES ====================

@api_router.post("/devices", response_model=DeviceResponse)
async def create_device(device: DeviceCreate, current_user: dict = Depends(get_current_user)):
    client = await db.clients.find_one({"id": device.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    device_doc = {
        "id": str(uuid.uuid4()),
        "client_id": device.client_id,
        "name": device.name,
        "device_type": device.device_type,
        "ip_address": device.ip_address,
        "hostname": device.hostname or "",
        "location": device.location or "",
        "status": "active",
        "redfish_enabled": device.redfish_enabled or False,
        "last_poll": None,
        "health_status": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.devices.insert_one(device_doc)
    
    await audit_logger.log(
        AuditAction.CREATE_DEVICE,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device",
        resource_id=device_doc["id"],
        details={"name": device.name, "type": device.device_type}
    )
    
    return DeviceResponse(**device_doc, client_name=client["name"], has_credentials=False)

@api_router.get("/devices", response_model=List[DeviceResponse])
async def get_devices(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id
    
    devices = await db.devices.find(query, {"_id": 0}).to_list(1000)
    
    client_ids = list(set(d["client_id"] for d in devices))
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    client_map = {c["id"]: c["name"] for c in clients}
    
    # Check which devices have credentials
    device_ids = [d["id"] for d in devices]
    creds = await db.device_credentials.find({"device_id": {"$in": device_ids}}, {"_id": 0, "device_id": 1}).to_list(1000)
    cred_device_ids = {c["device_id"] for c in creds}
    
    result = []
    for d in devices:
        d["client_name"] = client_map.get(d["client_id"], "")
        d["has_credentials"] = d["id"] in cred_device_ids
        result.append(DeviceResponse(**d))
    
    return result

@api_router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    client = await db.clients.find_one({"id": device["client_id"]}, {"_id": 0})
    device["client_name"] = client["name"] if client else ""
    
    cred = await db.device_credentials.find_one({"device_id": device_id})
    device["has_credentials"] = cred is not None
    
    return DeviceResponse(**device)

@api_router.post("/devices/{device_id}/credentials")
async def set_device_credentials(
    device_id: str,
    credentials: DeviceCredentials,
    current_user: dict = Depends(get_current_user)
):
    """Store encrypted credentials for a device (iLO, etc.)."""
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Encrypt credentials using AES-256-GCM
    encrypted_username = security_manager.encrypt_credential(credentials.username)
    encrypted_password = security_manager.encrypt_credential(credentials.password)
    
    await db.device_credentials.update_one(
        {"device_id": device_id},
        {
            "$set": {
                "device_id": device_id,
                "username_encrypted": encrypted_username,
                "password_encrypted": encrypted_password,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": current_user["id"]
            }
        },
        upsert=True
    )
    
    await audit_logger.log(
        AuditAction.STORE_CREDENTIAL,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential",
        resource_id=device_id,
        details={"device_name": device["name"]}
    )
    
    return {"message": "Credentials stored securely"}

@api_router.delete("/devices/{device_id}/credentials")
async def delete_device_credentials(device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.device_credentials.delete_one({"device_id": device_id})
    
    await audit_logger.log(
        AuditAction.DELETE_CREDENTIAL,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential",
        resource_id=device_id
    )
    
    return {"message": "Credentials deleted"}

@api_router.post("/devices/{device_id}/test-redfish")
async def test_device_redfish(device_id: str, current_user: dict = Depends(get_current_user)):
    """Test Redfish connection using stored credentials."""
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    cred = await db.device_credentials.find_one({"device_id": device_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=400, detail="No credentials stored")
    
    try:
        username = security_manager.decrypt_credential(cred["username_encrypted"])
        password = security_manager.decrypt_credential(cred["password_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials")
    
    result = await redfish_poller.test_connection(device["ip_address"], username, password)
    return result

@api_router.post("/devices/test-redfish")
async def test_redfish_connection(test: RedfishTestRequest, current_user: dict = Depends(get_current_user)):
    """Test Redfish connection with provided credentials."""
    result = await redfish_poller.test_connection(test.ip_address, test.username, test.password)
    return result

@api_router.delete("/devices/{device_id}")
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Also delete credentials
    await db.device_credentials.delete_one({"device_id": device_id})
    
    await audit_logger.log(
        AuditAction.DELETE_DEVICE,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device",
        resource_id=device_id
    )
    
    return {"message": "Device deleted"}

# ==================== ALERT ROUTES ====================

@api_router.post("/alerts", response_model=AlertResponse)
async def create_alert(alert: AlertCreate, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": alert.device_id}, {"_id": 0})
    client = await db.clients.find_one({"id": alert.client_id}, {"_id": 0})
    
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": alert.client_id,
        "device_id": alert.device_id,
        "severity": alert.severity,
        "source_type": alert.source_type,
        "title": alert.title,
        "message": alert.message,
        "raw_data": alert.raw_data or "",
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Check for maintenance window
    in_maintenance, maint_window = await maintenance_manager.is_in_maintenance(
        alert.client_id, alert.device_id, alert.severity
    )
    if in_maintenance:
        alert_doc["suppressed_by_maintenance"] = True
        alert_doc["maintenance_window_id"] = maint_window["id"]
    
    # Prepare alert with deduplication key
    alert_doc = await correlation_manager.prepare_alert_for_storage(alert_doc)
    
    # Check for duplicate
    is_duplicate, original_id = await correlation_manager.check_duplicate(alert_doc)
    if is_duplicate:
        return AlertResponse(
            **alert_doc,
            id=original_id,
            client_name=client["name"] if client else "",
            device_name=device["name"] if device else "",
            device_type=device["device_type"] if device else "",
            ip_address=device["ip_address"] if device else ""
        )
    
    # Check for alert storm
    is_storm, storm_count = await correlation_manager.check_alert_storm(alert.client_id, alert.device_id)
    if is_storm:
        alert_doc["in_storm"] = True
    
    await db.alerts.insert_one(alert_doc)
    
    # Check for correlation
    correlation_id = await correlation_manager.correlate_alerts(alert_doc)
    if correlation_id:
        alert_doc["correlation_group_id"] = correlation_id
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"] if device else "",
        device_type=device["device_type"] if device else "",
        ip_address=device["ip_address"] if device else ""
    )
    
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
    # Send notifications for high-priority alerts (unless in maintenance)
    if alert.severity in ["critical", "high"] and not in_maintenance:
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert.title,
            message=alert.message,
            priority=NotificationPriority.CRITICAL if alert.severity == "critical" else NotificationPriority.HIGH,
            alert_id=alert_doc["id"],
            data={"device": device["name"] if device else "", "client": client["name"] if client else ""}
        )
    
    await audit_logger.log(
        AuditAction.CREATE_ALERT,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="alert",
        resource_id=alert_doc["id"],
        details={"severity": alert.severity, "title": alert.title}
    )
    
    return response

@api_router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    client_id: Optional[str] = None,
    device_type: Optional[str] = None,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    query = {}
    if status:
        query["status"] = status
    if severity:
        query["severity"] = severity
    if client_id:
        query["client_id"] = client_id
    
    alerts = await db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    
    device_ids = list(set(a["device_id"] for a in alerts))
    client_ids = list(set(a["client_id"] for a in alerts))
    
    devices = await db.devices.find({"id": {"$in": device_ids}}, {"_id": 0}).to_list(1000)
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    
    device_map = {d["id"]: d for d in devices}
    client_map = {c["id"]: c["name"] for c in clients}
    
    result = []
    for a in alerts:
        device = device_map.get(a["device_id"], {})
        if device_type and device.get("device_type") != device_type:
            continue
        a["client_name"] = client_map.get(a["client_id"], "")
        a["device_name"] = device.get("name", "")
        a["device_type"] = device.get("device_type", "")
        a["ip_address"] = device.get("ip_address", "")
        result.append(AlertResponse(**a))
    
    return result

@api_router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    device = await db.devices.find_one({"id": alert["device_id"]}, {"_id": 0})
    client = await db.clients.find_one({"id": alert["client_id"]}, {"_id": 0})
    
    alert["client_name"] = client["name"] if client else ""
    alert["device_name"] = device["name"] if device else ""
    alert["device_type"] = device["device_type"] if device else ""
    alert["ip_address"] = device["ip_address"] if device else ""
    
    return AlertResponse(**alert)

@api_router.patch("/alerts/{alert_id}")
async def update_alert(alert_id: str, update: AlertUpdate, current_user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    update_data = {}
    if update.status:
        update_data["status"] = update.status
        if update.status == "acknowledged":
            update_data["acknowledged_by"] = current_user["name"]
            update_data["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        elif update.status == "resolved":
            update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.alerts.update_one({"id": alert_id}, {"$set": update_data})
    
    updated_alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    await manager.broadcast({"type": "alert_updated", "alert": updated_alert})
    
    await audit_logger.log(
        AuditAction.UPDATE_ALERT,
        user_id=current_user["id"],
        user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="alert",
        resource_id=alert_id,
        details={"new_status": update.status}
    )
    
    return {"message": "Alert updated"}

# ==================== STATS ROUTES ====================

@api_router.get("/stats/summary")
async def get_stats_summary(current_user: dict = Depends(get_current_user)):
    pipeline = [
        {"$match": {"status": "active"}},
        {"$group": {"_id": "$severity", "count": {"$sum": 1}}}
    ]
    severity_counts = await db.alerts.aggregate(pipeline).to_list(10)
    
    counts = {s["_id"]: s["count"] for s in severity_counts}
    
    total_active = sum(counts.values())
    total_clients = await db.clients.count_documents({})
    total_devices = await db.devices.count_documents({})
    
    return {
        "critical": counts.get("critical", 0),
        "high": counts.get("high", 0),
        "medium": counts.get("medium", 0),
        "low": counts.get("low", 0),
        "total_active": total_active,
        "total_clients": total_clients,
        "total_devices": total_devices
    }

@api_router.get("/stats/trends")
async def get_alert_trends(hours: int = 24, current_user: dict = Depends(get_current_user)):
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    alerts = await db.alerts.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "created_at": 1, "severity": 1}
    ).to_list(10000)
    
    from collections import defaultdict
    hourly_data = defaultdict(lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0})
    
    for alert in alerts:
        hour = alert["created_at"][:13] + ":00"
        hourly_data[hour][alert["severity"]] += 1
    
    sorted_hours = sorted(hourly_data.keys())
    return [{"hour": h, **hourly_data[h]} for h in sorted_hours]

# ==================== AUDIT ROUTES ====================

@api_router.get("/audit/logs")
async def get_audit_logs(
    hours: int = 24,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """Get recent audit logs (admin only)."""
    if current_user.get("role") != "admin":
        # For now, allow all authenticated users
        pass
    
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    logs = await db.audit_logs.find(
        {"timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(limit)
    
    return logs

@api_router.get("/audit/security-events")
async def get_security_events(hours: int = 24, current_user: dict = Depends(get_current_user)):
    """Get security-related events."""
    events = await audit_logger.get_security_events(hours=hours)
    return events

# ==================== SETTINGS ROUTES ====================

@api_router.get("/settings/notifications")
async def get_notification_settings(current_user: dict = Depends(get_current_user)):
    settings = await db.settings.find({"key": {"$regex": "^(email_|push_|webhook_)"}}, {"_id": 0}).to_list(100)
    return {s["key"]: s["value"] for s in settings}

@api_router.post("/settings/notifications")
async def update_notification_settings(
    settings: NotificationSettingsUpdate,
    current_user: dict = Depends(get_current_user)
):
    updates = [
        {"key": "email_enabled", "value": settings.email_enabled},
        {"key": "push_enabled", "value": settings.push_enabled},
    ]
    
    if settings.webhook_teams:
        updates.append({"key": "webhook_teams", "value": settings.webhook_teams})
    if settings.webhook_slack:
        updates.append({"key": "webhook_slack", "value": settings.webhook_slack})
    if settings.webhook_telegram:
        updates.append({"key": "webhook_telegram", "value": settings.webhook_telegram})
    if settings.webhook_generic:
        updates.append({"key": "webhook_generic", "value": settings.webhook_generic})
    
    for update in updates:
        await db.settings.update_one(
            {"key": update["key"]},
            {"$set": update},
            upsert=True
        )
    
    return {"message": "Settings updated"}

@api_router.get("/settings/redfish")
async def get_redfish_settings(current_user: dict = Depends(get_current_user)):
    setting = await db.settings.find_one({"key": "redfish_poll_interval"}, {"_id": 0})
    return {
        "poll_interval_minutes": setting.get("value", 5) if setting else 5,
        "enabled": True
    }

@api_router.post("/settings/redfish")
async def update_redfish_settings(
    poll_interval: int = 5,
    current_user: dict = Depends(get_current_user)
):
    await db.settings.update_one(
        {"key": "redfish_poll_interval"},
        {"$set": {"key": "redfish_poll_interval", "value": poll_interval}},
        upsert=True
    )
    return {"message": "Redfish settings updated"}

# ==================== WEBHOOK/SYSLOG/SNMP INGESTION ====================

async def validate_api_key(request: Request) -> dict:
    """Validate API key from X-API-Key header and return the client."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    client = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return client

class SyslogMessage(BaseModel):
    device_ip: str
    facility: Optional[int] = 1
    severity_level: Optional[int] = 5
    message: str
    timestamp: Optional[str] = None

class SNMPTrap(BaseModel):
    device_ip: str
    oid: str
    value: str
    trap_type: Optional[str] = "generic"
    device_name: Optional[str] = None
    severity: Optional[str] = None

class ConnectorHeartbeat(BaseModel):
    connector_version: str
    hostname: str
    uptime_seconds: int
    traps_received: int
    syslogs_received: int

def map_syslog_severity(level: int) -> str:
    if level <= 2:
        return "critical"
    elif level <= 4:
        return "high"
    elif level <= 5:
        return "medium"
    return "low"

def map_snmp_severity(trap_type: str, oid: str) -> str:
    critical_oids = ["linkDown", "coldStart", "authenticationFailure"]
    if any(c in oid or c in trap_type for c in critical_oids):
        return "critical"
    elif "warning" in trap_type.lower() or "down" in oid.lower():
        return "high"
    return "medium"

@api_router.post("/ingest/syslog")
@limiter.limit("100/minute")
async def ingest_syslog(request: Request, msg: SyslogMessage):
    # Support both API key auth (connector) and JWT auth
    client_data = None
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        # Fallback: require client_id in body for backwards compat
        body = await request.json()
        cid = body.get("client_id")
        if cid:
            client_data = await db.clients.find_one({"id": cid}, {"_id": 0})
    
    if not client_data:
        raise HTTPException(status_code=400, detail="Valid API key or client_id required")
    
    client_id = client_data["id"]
    device = await db.devices.find_one({"ip_address": msg.device_ip, "client_id": client_id}, {"_id": 0})
    
    if not device:
        device = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "name": f"Auto-{msg.device_ip}",
            "device_type": "unknown",
            "ip_address": msg.device_ip,
            "hostname": "",
            "location": "",
            "status": "active",
            "redfish_enabled": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    
    severity = map_syslog_severity(msg.severity_level)
    
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "device_id": device["id"],
        "severity": severity,
        "source_type": "syslog",
        "title": f"Syslog: Facility {msg.facility} - Level {msg.severity_level}",
        "message": msg.message[:500],
        "raw_data": json.dumps({
            "facility": msg.facility,
            "severity_level": msg.severity_level,
            "message": msg.message,
            "timestamp": msg.timestamp or datetime.now(timezone.utc).isoformat()
        }, indent=2),
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.alerts.insert_one(alert_doc)
    
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"],
        device_type=device["device_type"],
        ip_address=device["ip_address"]
    )
    
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
    # Send notifications for critical alerts
    if severity == "critical":
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert_doc["title"],
            message=alert_doc["message"],
            priority=NotificationPriority.CRITICAL,
            alert_id=alert_doc["id"]
        )
    
    return {"status": "ok", "alert_id": alert_doc["id"]}

@api_router.post("/ingest/snmp")
@limiter.limit("100/minute")
async def ingest_snmp(request: Request, trap: SNMPTrap):
    # Support both API key auth (connector) and JWT auth
    client_data = None
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        body = await request.json()
        cid = body.get("client_id")
        if cid:
            client_data = await db.clients.find_one({"id": cid}, {"_id": 0})
    
    if not client_data:
        raise HTTPException(status_code=400, detail="Valid API key or client_id required")
    
    client_id = client_data["id"]
    device = await db.devices.find_one({"ip_address": trap.device_ip, "client_id": client_id}, {"_id": 0})
    
    if not device:
        device = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "name": trap.device_name if trap.device_name else f"Auto-{trap.device_ip}",
            "device_type": "switch",
            "ip_address": trap.device_ip,
            "hostname": "",
            "location": "",
            "status": "active",
            "redfish_enabled": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    
    severity = trap.severity if trap.severity else map_snmp_severity(trap.trap_type, trap.oid)
    
    # Better title for polling events
    title_map = {
        "linkDown": "Porta DOWN",
        "linkUp": "Porta UP (ripristinata)",
        "deviceDown": "Dispositivo NON RAGGIUNGIBILE",
        "deviceUp": "Dispositivo ONLINE",
    }
    title = title_map.get(trap.trap_type, f"SNMP: {trap.trap_type}")
    device_label = trap.device_name if trap.device_name else device["name"]
    
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "device_id": device["id"],
        "severity": severity,
        "source_type": "snmp",
        "title": f"{title} - {device_label}",
        "message": trap.value,
        "raw_data": json.dumps({
            "oid": trap.oid,
            "value": trap.value,
            "trap_type": trap.trap_type,
            "device_ip": trap.device_ip,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, indent=2),
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.alerts.insert_one(alert_doc)
    
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"],
        device_type=device["device_type"],
        ip_address=device["ip_address"]
    )
    
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
    if severity == "critical":
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert_doc["title"],
            message=alert_doc["message"],
            priority=NotificationPriority.CRITICAL,
            alert_id=alert_doc["id"]
        )
    
    return {"status": "ok", "alert_id": alert_doc["id"]}

# ==================== CONNECTOR ENDPOINTS ====================

@api_router.post("/connector/heartbeat")
async def connector_heartbeat(request: Request, heartbeat: ConnectorHeartbeat):
    """Receive heartbeat from NOC Connector agents."""
    client_data = await validate_api_key(request)
    
    # Check if force_update flag is set for this connector
    existing = await db.connector_status.find_one({"client_id": client_data["id"]}, {"_id": 0})
    force_update = existing.get("force_update", False) if existing else False
    
    await db.connector_status.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "client_id": client_data["id"],
            "client_name": client_data["name"],
            "connector_version": heartbeat.connector_version,
            "hostname": heartbeat.hostname,
            "connector_ip": request.client.host if request.client else "unknown",
            "uptime_seconds": heartbeat.uptime_seconds,
            "traps_received": heartbeat.traps_received,
            "syslogs_received": heartbeat.syslogs_received,
            "last_seen": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    # Clear update_status if update is completed and connector restarted with new version
    if existing and existing.get("update_status"):
        update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
        if update_info:
            # If connector version matches or exceeds the published version, update is done
            if not is_newer_version(update_info["version"], heartbeat.connector_version):
                await db.connector_status.update_one(
                    {"client_id": client_data["id"]},
                    {"$unset": {"update_status": "", "force_update": ""}}
                )
    
    response = {"status": "ok"}
    
    # If force_update is flagged, include update info and clear the flag
    if force_update:
        update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
        if update_info and is_newer_version(update_info["version"], heartbeat.connector_version):
            response["force_update"] = True
            response["latest_version"] = update_info["version"]
            response["download_url"] = f"/api/connector/download/{update_info['filename']}"
            response["changelog"] = update_info.get("changelog", "")
            # Clear force_update flag
            await db.connector_status.update_one(
                {"client_id": client_data["id"]},
                {"$set": {"force_update": False}}
            )
    
    return response

@api_router.get("/connector/status")
async def get_connector_status(current_user: dict = Depends(get_current_user)):
    """Get status of all connected NOC Connectors."""
    connectors = await db.connector_status.find({}, {"_id": 0}).to_list(100)
    return connectors

@api_router.delete("/connector/status/{hostname}")
async def delete_connector_status(hostname: str, current_user: dict = Depends(get_current_user)):
    """Delete a connector from the status list."""
    result = await db.connector_status.delete_one({"hostname": hostname})
    if result.deleted_count == 0:
        # Try by client_name
        result = await db.connector_status.delete_one({"client_name": hostname})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"status": "ok"}

@api_router.post("/connector/{client_id}/force-update")
async def force_connector_update(client_id: str, current_user: dict = Depends(get_current_user)):
    """Flag a connector for immediate update at next heartbeat."""
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0})
    if not connector:
        raise HTTPException(status_code=404, detail="Connector non trovato")
    
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        raise HTTPException(status_code=400, detail="Nessun aggiornamento disponibile")
    
    if not is_newer_version(update_info["version"], connector.get("connector_version", "0.0.0")):
        raise HTTPException(status_code=400, detail="Il connector e' gia' alla versione piu' recente")
    
    await db.connector_status.update_one(
        {"client_id": client_id},
        {"$set": {"force_update": True}}
    )
    
    return {
        "status": "ok",
        "message": f"Aggiornamento forzato per {connector.get('hostname', client_id)}. Verra' applicato al prossimo heartbeat (~60s).",
        "target_version": update_info["version"]
    }

# ==================== CONNECTOR AUTO-UPDATE ====================

CONNECTOR_STORAGE = Path("/app/connector_updates")
CONNECTOR_STORAGE.mkdir(exist_ok=True)

@api_router.get("/connector/update-check")
async def connector_update_check(request: Request):
    """Check if a new connector version is available. Called by connectors via API key."""
    api_key = request.headers.get("X-API-Key")
    client_data = None
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")

    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        return {"update_available": False, "latest_version": "1.0.0"}

    # Check connector's current version to avoid downgrade
    current_version = "0.0.0"
    if client_data:
        connector = await db.connector_status.find_one({"client_id": client_data["id"]}, {"_id": 0})
        if connector:
            current_version = connector.get("connector_version", "0.0.0")

    published_version = update_info["version"]
    update_needed = is_newer_version(published_version, current_version)

    return {
        "update_available": update_needed,
        "latest_version": published_version,
        "download_url": f"/api/connector/download/{update_info['filename']}",
        "changelog": update_info.get("changelog", ""),
        "published_at": update_info.get("published_at", ""),
        "file_size": update_info.get("file_size", 0)
    }

@api_router.get("/connector/download/{filename}")
async def connector_download(filename: str, request: Request):
    """Download the latest connector ZIP. Authenticated via API key."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")

    filepath = CONNECTOR_STORAGE / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/zip"
    )

@api_router.post("/connector/upload-update")
async def upload_connector_update(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload a new connector version (admin only)."""
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files accepted")

    # Read version from form or generate
    body = await request.form()
    version = body.get("version", "")
    changelog = body.get("changelog", "")

    if not version:
        raise HTTPException(status_code=400, detail="Version is required")

    # Save file
    safe_filename = f"86NocConnector_v{version}.zip"
    filepath = CONNECTOR_STORAGE / safe_filename
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Deactivate previous updates
    await db.connector_updates.update_many({}, {"$set": {"active": False}})

    # Save update record
    update_doc = {
        "version": version,
        "filename": safe_filename,
        "changelog": changelog,
        "file_size": len(content),
        "active": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": current_user.get("name", "admin")
    }
    await db.connector_updates.insert_one(update_doc)

    # Also copy to frontend public for web download
    public_path = Path("/app/frontend/public/86NocConnector.zip")
    shutil.copy2(filepath, public_path)

    return {
        "status": "ok",
        "version": version,
        "filename": safe_filename,
        "connectors_will_update": "I connettori si aggiorneranno automaticamente entro 6 ore"
    }

@api_router.get("/connector/update-info")
async def get_connector_update_info(current_user: dict = Depends(get_current_user)):
    """Get current update info for admin dashboard."""
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    total_connectors = await db.connector_status.count_documents({})
    if update_info:
        # Count connectors already on latest version or newer
        all_connectors = await db.connector_status.find({}, {"_id": 0, "connector_version": 1}).to_list(500)
        updated = sum(1 for c in all_connectors if not is_newer_version(update_info["version"], c.get("connector_version", "0.0.0")))
        update_info["total_connectors"] = total_connectors
        update_info["updated_connectors"] = updated
        update_info["pending_connectors"] = total_connectors - updated
    return update_info or {"version": "1.0.0", "total_connectors": total_connectors, "updated_connectors": 0, "pending_connectors": 0}

@api_router.post("/connector/update-progress")
async def connector_update_progress(request: Request):
    """Connector reports its update progress (downloading, installing, etc.)."""
    client_data = await validate_api_key(request)
    body = await request.json()
    progress = body.get("progress", 0)
    status = body.get("status", "unknown")
    message = body.get("message", "")
    
    await db.connector_status.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "update_progress": progress,
            "update_status": status,
            "update_message": message
        }}
    )
    return {"status": "ok"}

# ==================== CONNECTOR DEVICE MANAGEMENT ====================

class DeviceStatusReport(BaseModel):
    device_ip: str
    device_name: str
    community: str = "public"
    reachable: bool
    ports: Optional[list] = []
    sys_descr: Optional[str] = ""
    sys_uptime: Optional[str] = ""
    poll_timestamp: str

class PollingReport(BaseModel):
    devices: list[DeviceStatusReport]

class ManagedDevice(BaseModel):
    ip: str
    community: str = "public"
    name: str
    monitor_type: str = "snmp"  # snmp, ping, http
    http_port: Optional[int] = 80

@api_router.post("/connector/device-report")
async def connector_device_report(request: Request):
    """Connector sends full device status report after each polling cycle."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
    if not client_data:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()
    client_id = client_data["id"]
    hostname = body.get("hostname", "unknown")
    devices = body.get("devices", [])

    now_iso = datetime.now(timezone.utc).isoformat()
    for dev in devices:
        doc = {
            "client_id": client_id,
            "connector_hostname": hostname,
            "device_ip": dev["device_ip"],
            "device_name": dev["device_name"],
            "reachable": dev["reachable"],
            "monitor_type": dev.get("monitor_type", "snmp"),
            "ports": dev.get("ports", []),
            "sys_descr": dev.get("sys_descr", ""),
            "sys_uptime": dev.get("sys_uptime", ""),
            "http_status": dev.get("http_status", None),
            "ping_ms": dev.get("ping_ms", None),
            "cpu_usage": dev.get("cpu_usage", None),
            "memory_usage": dev.get("memory_usage", None),
            "temperature": dev.get("temperature", None),
            "device_class": dev.get("device_class", "generic"),
            "hardware": dev.get("hardware", None),
            "last_poll": dev.get("poll_timestamp", now_iso),
            "updated_at": now_iso
        }
        await db.device_poll_status.update_one(
            {"client_id": client_id, "device_ip": dev["device_ip"]},
            {"$set": doc},
            upsert=True
        )

        # Store historical metrics for trending (keep last 288 = 24h at 5min intervals)
        if dev.get("cpu_usage") is not None or dev.get("temperature") is not None:
            metric_doc = {
                "client_id": client_id,
                "device_ip": dev["device_ip"],
                "timestamp": now_iso,
                "cpu_usage": dev.get("cpu_usage"),
                "memory_usage": dev.get("memory_usage"),
                "temperature": dev.get("temperature"),
            }
            await db.device_metrics_history.insert_one(metric_doc)
            # Cleanup old metrics (keep last 24h)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            await db.device_metrics_history.delete_many({
                "client_id": client_id,
                "device_ip": dev["device_ip"],
                "timestamp": {"$lt": cutoff}
            })

    return {"status": "ok", "devices_updated": len(devices)}

@api_router.get("/connector/device-poll-status")
async def get_device_poll_status(current_user: dict = Depends(get_current_user)):
    """Get latest polling status for all monitored devices."""
    statuses = await db.device_poll_status.find({}, {"_id": 0}).to_list(500)
    return statuses

@api_router.get("/connector/device-metrics/{device_ip}")
async def get_device_metrics_history(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Get historical metrics (CPU, Memory, Temperature) for a device - last 24h."""
    metrics = await db.device_metrics_history.find(
        {"device_ip": device_ip},
        {"_id": 0, "timestamp": 1, "cpu_usage": 1, "memory_usage": 1, "temperature": 1}
    ).sort("timestamp", 1).to_list(500)
    return metrics


@api_router.delete("/connector/device-poll-status/{device_ip}")
async def delete_device_poll_status(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Delete a monitored device from poll status AND managed devices list."""
    await db.device_poll_status.delete_many({"device_ip": device_ip})
    await db.managed_devices.delete_many({"ip": device_ip})
    return {"status": "ok"}

@api_router.put("/connector/device-poll-status/{device_ip}/monitor-type")
async def update_device_monitor_type(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Change the monitor type of an existing device."""
    body = await request.json()
    monitor_type = body.get("monitor_type", "snmp")
    http_port = body.get("http_port", 80)
    
    await db.managed_devices.update_many(
        {"ip": device_ip},
        {"$set": {"monitor_type": monitor_type, "http_port": http_port, "community": "" if monitor_type != "snmp" else "public"}}
    )
    await db.device_poll_status.update_many(
        {"device_ip": device_ip},
        {"$set": {"monitor_type": monitor_type}}
    )
    return {"status": "ok"}

@api_router.get("/connector/{client_id}/managed-devices")
async def get_managed_devices(client_id: str, request: Request):
    """Get device list for a connector (called by connector or admin)."""
    # Allow both API key auth and JWT auth
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
        client_id = client_data["id"]

    devices = await db.managed_devices.find({"client_id": client_id}, {"_id": 0}).to_list(200)
    return devices

@api_router.post("/connector/{client_id}/managed-devices")
async def add_managed_device(client_id: str, device: ManagedDevice, current_user: dict = Depends(get_current_user)):
    """Add a device to monitor for a specific connector/client."""
    doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "ip": device.ip,
        "community": device.community,
        "name": device.name,
        "monitor_type": device.monitor_type,
        "http_port": device.http_port,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("name", "admin")
    }
    await db.managed_devices.insert_one(doc)
    return {"status": "ok", "device": {k: v for k, v in doc.items() if k != "_id"}}

@api_router.delete("/connector/{client_id}/managed-devices/{device_id}")
async def remove_managed_device(client_id: str, device_id: str, current_user: dict = Depends(get_current_user)):
    """Remove a monitored device."""
    result = await db.managed_devices.delete_one({"id": device_id, "client_id": client_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    # Also remove poll status
    await db.device_poll_status.delete_one({"client_id": client_id, "device_ip": device_id})
    return {"status": "ok"}

@api_router.get("/connector/fetch-devices")
async def connector_fetch_devices(request: Request):
    """Connector fetches its device list from the NOC (for centralized management)."""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
    if not client_data:
        raise HTTPException(status_code=401, detail="Invalid API key")

    devices = await db.managed_devices.find({"client_id": client_data["id"]}, {"_id": 0}).to_list(200)
    return [{"ip": d["ip"], "community": d.get("community", "public"), "name": d["name"], "monitor_type": d.get("monitor_type", "snmp"), "http_port": d.get("http_port", 80)} for d in devices]

@api_router.post("/clients/{client_id}/regenerate-key")
async def regenerate_client_api_key(client_id: str, current_user: dict = Depends(get_current_user)):
    """Regenerate API key for a client."""
    new_key = f"noc_{uuid.uuid4().hex}"
    result = await db.clients.update_one({"id": client_id}, {"$set": {"api_key": new_key}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"api_key": new_key}

# ==================== WEBSOCKET ====================

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ==================== NETWORK DISCOVERY ====================

@api_router.post("/connector/start-discovery")
async def start_network_discovery(request: Request, current_user: dict = Depends(get_current_user)):
    """Trigger a network discovery scan on a connector."""
    body = await request.json()
    client_id = body.get("client_id")
    subnet = body.get("subnet", "")
    
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")
    
    await db.discovery_requests.update_one(
        {"client_id": client_id},
        {"$set": {
            "client_id": client_id,
            "subnet": subnet,
            "status": "pending",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": current_user.get("name", "admin")
        }},
        upsert=True
    )
    return {"status": "ok", "message": "Discovery scan requested"}

@api_router.get("/connector/discovery-check")
async def check_discovery_request(request: Request):
    """Connector checks if a discovery scan has been requested."""
    client_data = await validate_api_key(request)
    req = await db.discovery_requests.find_one(
        {"client_id": client_data["id"], "status": "pending"}, {"_id": 0}
    )
    if req:
        await db.discovery_requests.update_one(
            {"client_id": client_data["id"]},
            {"$set": {"status": "in_progress"}}
        )
        return {"scan_requested": True, "subnet": req.get("subnet", "")}
    return {"scan_requested": False}

@api_router.post("/connector/discovery-results")
async def submit_discovery_results(request: Request):
    """Connector submits discovery scan results."""
    client_data = await validate_api_key(request)
    body = await request.json()
    devices = body.get("devices", [])
    
    # Get existing managed devices to mark them
    managed = await db.managed_devices.find(
        {"client_id": client_data["id"]}, {"_id": 0, "ip": 1}
    ).to_list(500)
    managed_ips = {d["ip"] for d in managed}
    
    # Store results
    await db.discovery_results.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "client_id": client_data["id"],
            "devices": devices,
            "managed_ips": list(managed_ips),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "device_count": len(devices)
        }},
        upsert=True
    )
    
    await db.discovery_requests.update_one(
        {"client_id": client_data["id"]},
        {"$set": {"status": "completed"}}
    )
    
    return {"status": "ok", "devices_found": len(devices)}

@api_router.get("/connector/discovery-results/{client_id}")
async def get_discovery_results(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get latest discovery results for a client."""
    results = await db.discovery_results.find_one(
        {"client_id": client_id}, {"_id": 0}
    )
    if not results:
        return {"devices": [], "scanned_at": None}
    
    # Update managed_ips in real-time
    managed = await db.managed_devices.find(
        {"client_id": client_id}, {"_id": 0, "ip": 1}
    ).to_list(500)
    results["managed_ips"] = [d["ip"] for d in managed]
    
    return results

@api_router.get("/connector/discovery-status/{client_id}")
async def get_discovery_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get current discovery scan status."""
    req = await db.discovery_requests.find_one(
        {"client_id": client_id}, {"_id": 0}
    )
    if not req:
        return {"status": "none"}
    return {"status": req.get("status", "none"), "requested_at": req.get("requested_at")}

# ==================== WEB CONSOLE PROXY ====================

@api_router.post("/connector/web-proxy/request")
async def create_web_proxy_request(request: Request, current_user: dict = Depends(get_current_user)):
    """Create a web proxy request to access a device's web console through the connector."""
    # Only admin and operator can use web proxy
    if current_user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    body = await request.json()
    client_id = body.get("client_id")
    device_ip = body.get("device_ip")
    port = body.get("port", 80)
    path = body.get("path", "/")
    method = body.get("method", "GET")
    
    if not client_id or not device_ip:
        raise HTTPException(status_code=400, detail="client_id and device_ip required")
    
    # Security: verify device is in managed_devices for this client
    device = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip}, {"_id": 0}
    )
    if not device:
        # Also check device_poll_status
        poll = await db.device_poll_status.find_one(
            {"client_id": client_id, "device_ip": device_ip}, {"_id": 0}
        )
        if not poll:
            raise HTTPException(status_code=403, detail="Device not authorized for this client")
    
    request_id = str(uuid.uuid4())
    
    await db.web_proxy_requests.insert_one({
        "request_id": request_id,
        "client_id": client_id,
        "device_ip": device_ip,
        "port": port,
        "path": path,
        "method": method,
        "status": "pending",
        "requested_by": current_user.get("email", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "response": None
    })
    
    # Audit log - use logging module directly since AuditLogger.log is async
    logging.getLogger("audit").info(
        f"[AUDIT] web_proxy_request | User: {current_user.get('email')} | "
        f"Device: {device_ip}:{port}{path} | Client: {client_id}"
    )
    
    return {"request_id": request_id, "status": "pending"}

@api_router.get("/connector/web-proxy/pending")
async def get_pending_web_proxy_requests(request: Request):
    """Connector polls for pending web proxy requests."""
    client_data = await validate_api_key(request)
    
    requests_list = await db.web_proxy_requests.find(
        {"client_id": client_data["id"], "status": "pending"},
        {"_id": 0}
    ).sort("created_at", 1).to_list(5)
    
    # Mark as in_progress
    for req in requests_list:
        await db.web_proxy_requests.update_one(
            {"request_id": req["request_id"]},
            {"$set": {"status": "in_progress"}}
        )
    
    return {"requests": requests_list}

@api_router.post("/connector/web-proxy/response")
async def submit_web_proxy_response(request: Request):
    """Connector submits the web proxy response."""
    client_data = await validate_api_key(request)
    body = await request.json()
    request_id = body.get("request_id")
    
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id required")
    
    await db.web_proxy_requests.update_one(
        {"request_id": request_id, "client_id": client_data["id"]},
        {"$set": {
            "status": "completed",
            "response": {
                "status_code": body.get("status_code", 0),
                "content_type": body.get("content_type", "text/html"),
                "body": body.get("body", ""),
                "title": body.get("title", ""),
                "error": body.get("error", None)
            },
            "completed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"status": "ok"}

@api_router.get("/connector/web-proxy/response/{request_id}")
async def get_web_proxy_response(request_id: str, current_user: dict = Depends(get_current_user)):
    """Frontend polls for the web proxy response."""
    doc = await db.web_proxy_requests.find_one(
        {"request_id": request_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Auto-cleanup: delete requests older than 5 minutes
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    await db.web_proxy_requests.delete_many({"created_at": {"$lt": cutoff}, "status": "completed"})
    
    return {
        "request_id": doc["request_id"],
        "status": doc["status"],
        "response": doc.get("response"),
        "device_ip": doc.get("device_ip"),
        "port": doc.get("port"),
        "path": doc.get("path")
    }

# ==================== ROOT ROUTES ====================

@api_router.get("/")
async def root():
    return {
        "message": "NOC Alert Command Center API",
        "version": "2.0.0",
        "security": "Enterprise-grade (AES-256-GCM, Argon2id, 2FA)"
    }

@api_router.get("/health")
async def health():
    return {"status": "healthy"}

# Include router
app.include_router(api_router)

# Include enterprise routes
from enterprise_routes import create_enterprise_router
enterprise_router = create_enterprise_router(db, get_current_user, audit_logger)
app.include_router(enterprise_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    """Start background services on application startup."""
    # Start Redfish polling scheduler
    try:
        setting = await db.settings.find_one({"key": "redfish_poll_interval"})
        interval = setting.get("value", 5) if setting else 5
        await redfish_poller.start_scheduler(interval_minutes=interval)
        logger.info("Redfish polling scheduler started")
    except Exception as e:
        logger.error(f"Failed to start Redfish scheduler: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    redfish_poller.stop_scheduler()
    client.close()
