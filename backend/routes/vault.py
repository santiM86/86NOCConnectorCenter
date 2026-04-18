"""Credential Vault routes (AES-256-GCM)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import uuid
from datetime import datetime, timezone

from database import db
from models import CredentialCreate, CredentialUpdate
from security import security_manager
from audit import AuditAction
from deps import get_current_user, audit_logger, check_nosql_injection

router = APIRouter(prefix="/api", tags=["vault"])


async def _enrich_client_names(creds):
    """Attach client_name to each credential by resolving client_id against db.clients."""
    client_ids = list({c.get("client_id") for c in creds if c.get("client_id")})
    client_map = {}
    if client_ids:
        clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        client_map = {c["id"]: c["name"] for c in clients}
    for c in creds:
        c["client_name"] = client_map.get(c.get("client_id"), "")
    return creds


@router.get("/vault/credentials")
async def list_credentials(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo gli admin possono accedere al vault")
    query = {}
    if client_id:
        query["client_id"] = client_id
    creds = await db.device_credentials.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    for c in creds:
        c["password"] = "********"
        try: c["username"] = security_manager.decrypt_credential(c["username_enc"])
        except Exception: c["username"] = "[errore decifratura]"
        c.pop("username_enc", None)
        c.pop("password_enc", None)
    await _enrich_client_names(creds)
    return creds


@router.get("/vault/credentials/{cred_id}")
async def get_credential(cred_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo gli admin possono accedere al vault")
    cred = await db.device_credentials.find_one({"id": cred_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Credenziale non trovata")
    try:
        cred["username"] = security_manager.decrypt_credential(cred["username_enc"])
        cred["password"] = security_manager.decrypt_credential(cred["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Errore nella decifratura delle credenziali")
    cred.pop("username_enc", None)
    cred.pop("password_enc", None)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "credential_decrypted", "cred_id": cred_id, "device_ip": cred.get("device_ip")},
        severity="info"
    )
    return cred


@router.post("/vault/credentials")
async def create_credential(cred: CredentialCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo gli admin possono gestire il vault")
    check_nosql_injection(cred.model_dump())
    # Validate client_id if provided
    if cred.client_id:
        client = await db.clients.find_one({"id": cred.client_id}, {"_id": 0, "id": 1})
        if not client:
            raise HTTPException(status_code=404, detail="Cliente non trovato")
    cred_id = str(uuid.uuid4())
    doc = {
        "id": cred_id, "device_ip": cred.device_ip,
        "device_name": cred.device_name or cred.device_ip,
        "credential_type": cred.credential_type,
        "client_id": cred.client_id or None,
        "username_enc": security_manager.encrypt_credential(cred.username),
        "password_enc": security_manager.encrypt_credential(cred.password),
        "url": cred.url, "port": cred.port, "notes": cred.notes,
        "tags": cred.tags or [],
        "external_url": getattr(cred, 'external_url', None) or "",
        "direct_poll": False,
        "created_by": current_user.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.device_credentials.insert_one(doc)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "credential_created", "cred_id": cred_id, "device_ip": cred.device_ip, "type": cred.credential_type, "client_id": cred.client_id},
        severity="info"
    )
    return {"status": "ok", "id": cred_id, "message": "Credenziale salvata e cifrata con AES-256-GCM"}


@router.put("/vault/credentials/{cred_id}")
async def update_credential(cred_id: str, cred: CredentialUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo gli admin possono gestire il vault")
    existing = await db.device_credentials.find_one({"id": cred_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Credenziale non trovata")
    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if cred.device_name is not None: update_data["device_name"] = cred.device_name
    if cred.credential_type is not None: update_data["credential_type"] = cred.credential_type
    if cred.username is not None: update_data["username_enc"] = security_manager.encrypt_credential(cred.username)
    if cred.password is not None: update_data["password_enc"] = security_manager.encrypt_credential(cred.password)
    if cred.url is not None: update_data["url"] = cred.url
    if cred.port is not None: update_data["port"] = cred.port
    if cred.notes is not None: update_data["notes"] = cred.notes
    if cred.tags is not None: update_data["tags"] = cred.tags
    if cred.external_url is not None: update_data["external_url"] = cred.external_url
    if cred.client_id is not None:
        if cred.client_id:  # non-empty -> validate
            client = await db.clients.find_one({"id": cred.client_id}, {"_id": 0, "id": 1})
            if not client:
                raise HTTPException(status_code=404, detail="Cliente non trovato")
        update_data["client_id"] = cred.client_id or None
    await db.device_credentials.update_one({"id": cred_id}, {"$set": update_data})
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "credential_updated", "cred_id": cred_id}, severity="info"
    )
    return {"status": "ok", "message": "Credenziale aggiornata"}


@router.delete("/vault/credentials/{cred_id}")
async def delete_credential(cred_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo gli admin possono gestire il vault")
    result = await db.device_credentials.delete_one({"id": cred_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Credenziale non trovata")
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "credential_deleted", "cred_id": cred_id}, severity="warning"
    )
    return {"status": "ok", "message": "Credenziale eliminata"}
