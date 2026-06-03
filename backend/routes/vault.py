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
    # When filtering by client, include also global credentials (no client_id)
    # so they are always visible from any client's perspective (admin tooling).
    if client_id:
        query = {"$or": [
            {"client_id": client_id},
            {"client_id": None},
            {"client_id": ""},
            {"client_id": {"$exists": False}},
        ]}
    else:
        query = {}
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
        "connector_only": getattr(cred, 'connector_only', False) or False,
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
    if cred.connector_only is not None: update_data["connector_only"] = bool(cred.connector_only)
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


# v2026-06-02: Health check vault — utile per diagnosticare il problema
# "[errore decifratura]" osservato in PROD dopo restart container che ha
# rigenerato /app/backend/data/encryption_salt.bin. Le credenziali con
# salt vecchio NON sono piu' recuperabili (per design AES-GCM) e vanno
# ricreate.
@router.get("/admin/vault-health-check")
async def vault_health_check(current_user: dict = Depends(get_current_user)):
    """Verifica decifratura di TUTTE le credenziali nel vault.

    Returns:
      - total: numero totale credenziali in DB
      - decryptable: quante sono decifrabili con la chiave/salt corrente
      - corrupted: lista credenziali NON decifrabili (id, device_name,
                   device_ip, client_id, created_at) da ricreare
      - encryption_status: snapshot di chiave / salt attivi (no segreti)
      - suggestion: testo human-readable con prossima azione
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

    creds = await db.device_credentials.find({}, {"_id": 0}).to_list(2000)
    decryptable = 0
    corrupted: list[dict] = []
    for c in creds:
        try:
            _ = security_manager.decrypt_credential(c["username_enc"])
            _ = security_manager.decrypt_credential(c["password_enc"])
            decryptable += 1
        except Exception as e:
            corrupted.append({
                "id": c.get("id"),
                "device_name": c.get("device_name"),
                "device_ip": c.get("device_ip"),
                "credential_type": c.get("credential_type"),
                "client_id": c.get("client_id"),
                "created_at": c.get("created_at"),
                "created_by": c.get("created_by"),
                "error": str(e)[:120],
            })

    # Snapshot chiave/salt (zero leak di segreti)
    import os
    from pathlib import Path
    salt_path = Path(os.environ.get('ARGUS_DATA_DIR', '/app/backend/data')) / "encryption_salt.bin"
    salt_exists = salt_path.exists()
    salt_size = salt_path.stat().st_size if salt_exists else 0
    salt_mtime = None
    if salt_exists:
        from datetime import datetime, timezone
        salt_mtime = datetime.fromtimestamp(
            salt_path.stat().st_mtime, tz=timezone.utc).isoformat()

    enc_status = {
        "encryption_key_set": bool(os.environ.get("ENCRYPTION_KEY")),
        "salt_file_path": str(salt_path),
        "salt_file_exists": salt_exists,
        "salt_file_size_bytes": salt_size,
        "salt_file_mtime_utc": salt_mtime,
    }

    if corrupted:
        suggestion = (
            f"🔴 {len(corrupted)} credenziali NON decifrabili: vanno "
            f"ELIMINATE e RICREATE. Le credenziali AES-256-GCM con salt "
            f"vecchio NON sono recuperabili (è un design di sicurezza). "
            f"Causa più probabile: il file '{salt_path}' è stato rigenerato "
            f"durante un restart container senza volume persistente. "
            f"FIX permanente: monta /app/backend/data/ come volume "
            f"persistente nel tuo docker-compose / k8s manifest."
        )
    else:
        suggestion = "✅ Tutte le credenziali sono decifrabili. Vault healthy."

    return {
        "total": len(creds),
        "decryptable": decryptable,
        "corrupted_count": len(corrupted),
        "corrupted": corrupted,
        "encryption_status": enc_status,
        "suggestion": suggestion,
    }


@router.delete("/admin/vault-purge-corrupted")
async def purge_corrupted_credentials(current_user: dict = Depends(get_current_user)):
    """Elimina in batch tutte le credenziali non decifrabili (post conferma).

    Da usare DOPO aver visto l'output di /admin/vault-health-check ed
    essersi resi conto che le credenziali corrotte vanno ricreate. Pulisce
    il DB in modo sicuro (audit log per ciascuna).
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

    creds = await db.device_credentials.find({}, {"_id": 0}).to_list(2000)
    purged_ids: list[str] = []
    for c in creds:
        try:
            security_manager.decrypt_credential(c["username_enc"])
            security_manager.decrypt_credential(c["password_enc"])
        except Exception:
            purged_ids.append(c.get("id"))

    if purged_ids:
        await db.device_credentials.delete_many({"id": {"$in": purged_ids}})
        await audit_logger.log(
            AuditAction.SUSPICIOUS_ACTIVITY,
            user_id=current_user.get("id"), user_email=current_user.get("email"),
            details={
                "action": "vault_purge_corrupted",
                "purged_count": len(purged_ids),
                "purged_ids": purged_ids,
            },
            severity="warning",
        )

    return {
        "status": "ok",
        "purged_count": len(purged_ids),
        "purged_ids": purged_ids,
        "message": (f"Eliminate {len(purged_ids)} credenziali non decifrabili. "
                    f"Vanno ricreate manualmente con 'Aggiungi Credenziale'."),
    }
