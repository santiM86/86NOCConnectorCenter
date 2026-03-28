"""Redfish direct polling, power control, and Wake-on-LAN routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
import asyncio
import uuid
import logging
from datetime import datetime, timezone

from database import db
from security import security_manager
from audit import AuditAction
from deps import get_current_user, audit_logger, redfish_poller, validate_api_key

router = APIRouter(prefix="/api", tags=["redfish"])


@router.post("/redfish/test-connection")
async def redfish_test_connection(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    url = body.get("url", "").rstrip("/")
    username = body.get("username", "")
    password = body.get("password", "")
    if not url or not username:
        raise HTTPException(status_code=400, detail="URL e username obbligatori")
    result = await redfish_poller.test_connection(url, username, password)
    return result


@router.put("/vault/credentials/{cred_id}/direct-poll")
async def set_direct_poll(cred_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    update = {}
    if "direct_poll" in body: update["direct_poll"] = bool(body["direct_poll"])
    if "external_url" in body: update["external_url"] = body["external_url"]
    if not update:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")
    result = await db.device_credentials.update_one({"id": cred_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Credenziale non trovata")
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "direct_poll_config", "cred_id": cred_id, **update}, severity="info"
    )
    return {"status": "ok"}


@router.get("/redfish/failover-status")
async def get_failover_status(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    return await redfish_poller.get_failover_status()


@router.post("/redfish/poll-now")
async def trigger_direct_poll(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    asyncio.create_task(redfish_poller.poll_cycle())
    return {"status": "ok", "message": "Polling Redfish avviato"}


# ==================== POWER CONTROL & WAKE-ON-LAN ====================

@router.post("/devices/{device_ip}/power-action")
async def device_power_action(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    action = body.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="Campo 'action' obbligatorio")
    cred = await db.device_credentials.find_one({"device_ip": device_ip, "credential_type": "ilo"}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Nessuna credenziale iLO trovata per questo dispositivo")
    external_url = cred.get("external_url")
    if not external_url:
        raise HTTPException(status_code=400, detail="URL esterna iLO non configurata. Configurala nel Vault per il polling diretto.")
    try:
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Errore decifratura credenziali")
    result = await redfish_poller.power_action(external_url.rstrip("/"), username, password, action)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "power_control", "device_ip": device_ip, "power_action": action, "result": result.get("success")},
        severity="critical"
    )
    return result


@router.get("/devices/{device_ip}/power-state")
async def device_power_state(device_ip: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    cred = await db.device_credentials.find_one({"device_ip": device_ip, "credential_type": "ilo"}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Nessuna credenziale iLO")
    external_url = cred.get("external_url")
    if not external_url:
        raise HTTPException(status_code=400, detail="URL esterna iLO non configurata")
    try:
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Errore decifratura credenziali")
    return await redfish_poller.get_power_state(external_url.rstrip("/"), username, password)


@router.post("/devices/{device_ip}/wake-on-lan")
async def device_wake_on_lan(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    mac_address = body.get("mac_address", "").strip().upper()
    if not mac_address or len(mac_address.replace(":", "").replace("-", "")) != 12:
        raise HTTPException(status_code=400, detail="Indirizzo MAC non valido (formato: AA:BB:CC:DD:EE:FF)")
    await db.pending_commands.insert_one({
        "id": str(uuid.uuid4()), "type": "wake_on_lan",
        "target_ip": device_ip, "mac_address": mac_address,
        "requested_by": current_user.get("email"), "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "wake_on_lan", "device_ip": device_ip, "mac": mac_address}, severity="warning"
    )
    return {"status": "ok", "message": f"Comando WoL per {mac_address} accodato. Verra' eseguito dal connettore al prossimo heartbeat (~60s)."}


@router.get("/connector/pending-commands")
async def connector_get_pending_commands(request: Request):
    await validate_api_key(request)
    commands = await db.pending_commands.find({"status": "pending"}, {"_id": 0}).sort("created_at", 1).to_list(50)
    if commands:
        cmd_ids = [c["id"] for c in commands]
        await db.pending_commands.update_many(
            {"id": {"$in": cmd_ids}},
            {"$set": {"status": "dispatched", "dispatched_at": datetime.now(timezone.utc).isoformat()}}
        )
    return commands
