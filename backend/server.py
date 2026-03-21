from fastapi import FastAPI, APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import jwt
import bcrypt
import asyncio
import json

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'noc-alert-secret-key-2024')
JWT_ALGORITHM = "HS256"

# Create the main app
app = FastAPI(title="NOC Alert Command Center API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

security = HTTPBearer()

# WebSocket connection manager
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

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: str
    password: str
    name: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    role: str = "operator"

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
    created_at: str

class DeviceCreate(BaseModel):
    client_id: str
    name: str
    device_type: str  # backup, firewall, switch, ilo
    ip_address: str
    hostname: Optional[str] = ""
    location: Optional[str] = ""

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
    created_at: str

class AlertCreate(BaseModel):
    client_id: str
    device_id: str
    severity: str  # critical, high, medium, low
    source_type: str  # snmp, syslog, api
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

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc).timestamp() + 86400  # 24 hours
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register")
async def register(user: UserCreate):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": user.email,
        "name": user.name,
        "password_hash": hash_password(user.password),
        "role": "operator",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    token = create_token(user_doc["id"], user_doc["email"])
    return {"token": token, "user": {"id": user_doc["id"], "email": user_doc["email"], "name": user_doc["name"], "role": user_doc["role"]}}

@api_router.post("/auth/login")
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"], user["email"])
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]}}

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "name": current_user["name"], "role": current_user["role"]}

# ==================== CLIENT ROUTES ====================

@api_router.post("/clients", response_model=ClientResponse)
async def create_client(client: ClientCreate, current_user: dict = Depends(get_current_user)):
    client_doc = {
        "id": str(uuid.uuid4()),
        "name": client.name,
        "description": client.description or "",
        "contact_email": client.contact_email or "",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.clients.insert_one(client_doc)
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
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.devices.insert_one(device_doc)
    return DeviceResponse(**device_doc, client_name=client["name"])

@api_router.get("/devices", response_model=List[DeviceResponse])
async def get_devices(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id
    
    devices = await db.devices.find(query, {"_id": 0}).to_list(1000)
    
    # Enrich with client names
    client_ids = list(set(d["client_id"] for d in devices))
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    client_map = {c["id"]: c["name"] for c in clients}
    
    for d in devices:
        d["client_name"] = client_map.get(d["client_id"], "")
    
    return [DeviceResponse(**d) for d in devices]

@api_router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    client = await db.clients.find_one({"id": device["client_id"]}, {"_id": 0})
    device["client_name"] = client["name"] if client else ""
    return DeviceResponse(**device)

@api_router.delete("/devices/{device_id}")
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
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
    await db.alerts.insert_one(alert_doc)
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"] if device else "",
        device_type=device["device_type"] if device else "",
        ip_address=device["ip_address"] if device else ""
    )
    
    # Broadcast to WebSocket clients
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
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
    
    # Enrich with device and client info
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
    
    # Broadcast update
    updated_alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    await manager.broadcast({"type": "alert_updated", "alert": updated_alert})
    
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
    # Get alerts from last N hours grouped by hour
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    alerts = await db.alerts.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "created_at": 1, "severity": 1}
    ).to_list(10000)
    
    # Group by hour
    from collections import defaultdict
    hourly_data = defaultdict(lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0})
    
    for alert in alerts:
        hour = alert["created_at"][:13] + ":00"  # Extract YYYY-MM-DDTHH:00
        hourly_data[hour][alert["severity"]] += 1
    
    # Sort and return
    sorted_hours = sorted(hourly_data.keys())
    return [{"hour": h, **hourly_data[h]} for h in sorted_hours]

# ==================== WEBHOOK/SYSLOG/SNMP INGESTION ====================

class SyslogMessage(BaseModel):
    client_id: str
    device_ip: str
    facility: Optional[int] = 1
    severity_level: Optional[int] = 5
    message: str
    timestamp: Optional[str] = None

class SNMPTrap(BaseModel):
    client_id: str
    device_ip: str
    oid: str
    value: str
    trap_type: Optional[str] = "generic"

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
async def ingest_syslog(msg: SyslogMessage):
    # Find device by IP
    device = await db.devices.find_one({"ip_address": msg.device_ip, "client_id": msg.client_id}, {"_id": 0})
    
    if not device:
        # Auto-create device
        device = {
            "id": str(uuid.uuid4()),
            "client_id": msg.client_id,
            "name": f"Auto-{msg.device_ip}",
            "device_type": "unknown",
            "ip_address": msg.device_ip,
            "hostname": "",
            "location": "",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    
    severity = map_syslog_severity(msg.severity_level)
    
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": msg.client_id,
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
    
    client = await db.clients.find_one({"id": msg.client_id}, {"_id": 0})
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"],
        device_type=device["device_type"],
        ip_address=device["ip_address"]
    )
    
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
    return {"status": "ok", "alert_id": alert_doc["id"]}

@api_router.post("/ingest/snmp")
async def ingest_snmp(trap: SNMPTrap):
    device = await db.devices.find_one({"ip_address": trap.device_ip, "client_id": trap.client_id}, {"_id": 0})
    
    if not device:
        device = {
            "id": str(uuid.uuid4()),
            "client_id": trap.client_id,
            "name": f"Auto-{trap.device_ip}",
            "device_type": "switch",
            "ip_address": trap.device_ip,
            "hostname": "",
            "location": "",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    
    severity = map_snmp_severity(trap.trap_type, trap.oid)
    
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": trap.client_id,
        "device_id": device["id"],
        "severity": severity,
        "source_type": "snmp",
        "title": f"SNMP Trap: {trap.trap_type}",
        "message": f"OID: {trap.oid} | Value: {trap.value}",
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
    
    client = await db.clients.find_one({"id": trap.client_id}, {"_id": 0})
    
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"],
        device_type=device["device_type"],
        ip_address=device["ip_address"]
    )
    
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    
    return {"status": "ok", "alert_id": alert_doc["id"]}

# ==================== WEBSOCKET ====================

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle any client messages if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ==================== ROOT ROUTES ====================

@api_router.get("/")
async def root():
    return {"message": "NOC Alert Command Center API", "version": "1.0.0"}

@api_router.get("/health")
async def health():
    return {"status": "healthy"}

# Include router
app.include_router(api_router)

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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
