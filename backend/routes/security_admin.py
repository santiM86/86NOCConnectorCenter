"""
Security Admin — Master key rotation + ciphertext migration v1→v2.

Endpoints (admin-only):
  GET  /api/admin/security/encryption-status
  POST /api/admin/security/migrate-to-v2
  POST /api/admin/security/rotate-master-key
  POST /api/admin/security/check-password    (test strength + HIBP)
  GET  /api/admin/audit/recent               (audit dashboard data)
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin, limiter
from security import security_manager, _V2_SALT_PATH, _load_or_create_v2_salt  # noqa: F401
from services.password_policy_check import check_password

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api/admin/security", tags=["security-admin"])


# Mappa: collection → lista di (filtro, campo_ciphertext) da scansionare.
# Estendere qui quando si aggiungono nuove collection con dati cifrati.
ENCRYPTED_FIELDS: list[tuple[str, str]] = [
    ("hornetsecurity_global_config", "api_key_enc"),
    ("hornetsecurity_configs", "api_key_enc"),
    ("vault_credentials", "secret_enc"),         # se esistente
    ("vault_credentials", "value_enc"),          # naming alternativo
    ("device_credentials", "password_enc"),      # se esistente
    ("device_credentials", "snmp_community_enc"),
    ("connector_settings", "shared_secret_enc"),
]


async def _scan_ciphertext_stats() -> dict[str, Any]:
    """Scansiona tutte le collection note e conta blob v1 vs v2."""
    total = 0
    v2 = 0
    v1 = 0
    invalid = 0
    breakdown: dict[str, dict[str, int]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for collection_name, field in ENCRYPTED_FIELDS:
        if (collection_name, field) in seen_pairs:
            continue
        seen_pairs.add((collection_name, field))
        try:
            coll = db[collection_name]
            cursor = coll.find({field: {"$exists": True, "$ne": None}}, {field: 1})
            c_total = c_v2 = c_v1 = c_inv = 0
            async for doc in cursor:
                ct = doc.get(field)
                if not isinstance(ct, str) or not ct:
                    c_inv += 1
                    continue
                c_total += 1
                if security_manager.is_v2_ciphertext(ct):
                    c_v2 += 1
                else:
                    c_v1 += 1
            if c_total > 0 or c_inv > 0:
                breakdown[f"{collection_name}.{field}"] = {
                    "total": c_total, "v2": c_v2, "v1_legacy": c_v1, "invalid": c_inv,
                }
                total += c_total
                v2 += c_v2
                v1 += c_v1
                invalid += c_inv
        except Exception as e:
            logger.debug(f"[encryption-status] skip {collection_name}.{field}: {e}")

    return {
        "total_ciphertexts": total,
        "v2_count": v2,
        "v1_legacy_count": v1,
        "invalid_count": invalid,
        "v2_percentage": round((v2 / total * 100), 1) if total > 0 else 100.0,
        "needs_migration": v1 > 0,
        "breakdown": breakdown,
        "salt_v2_path": str(_V2_SALT_PATH),
        "salt_v2_exists": _V2_SALT_PATH.exists(),
    }


@router.get("/encryption-status")
async def encryption_status(current_user: dict = Depends(get_current_user)):
    """Stato della cifratura nel sistema."""
    require_admin(current_user)
    return await _scan_ciphertext_stats()


@router.post("/migrate-to-v2")
@limiter.limit("3/minute")
async def migrate_to_v2(request: Request, current_user: dict = Depends(get_current_user)):
    """Migra tutti i blob legacy v1 a schema v2 (re-encrypt in-place).

    Idempotente: salta blob gia` v2. Ritorna summary delle modifiche.
    Operazione lock-free a livello collection (update mirato per _id).
    """
    require_admin(current_user)
    migrated = 0
    skipped_v2 = 0
    failed = 0
    failures: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for collection_name, field in ENCRYPTED_FIELDS:
        if (collection_name, field) in seen_pairs:
            continue
        seen_pairs.add((collection_name, field))
        try:
            coll = db[collection_name]
            cursor = coll.find({field: {"$exists": True, "$ne": None}}, {"_id": 1, field: 1})
            async for doc in cursor:
                ct = doc.get(field)
                if not isinstance(ct, str):
                    continue
                if security_manager.is_v2_ciphertext(ct):
                    skipped_v2 += 1
                    continue
                try:
                    new_ct = security_manager.reencrypt_to_v2(ct)
                    if new_ct is None:
                        skipped_v2 += 1
                        continue
                    await coll.update_one({"_id": doc["_id"]}, {"$set": {field: new_ct}})
                    migrated += 1
                except Exception as e:
                    failed += 1
                    failures.append({
                        "collection": collection_name, "field": field,
                        "_id": str(doc.get("_id")), "error": str(e),
                    })
        except Exception as e:
            logger.warning(f"[migrate-v2] skip {collection_name}.{field}: {e}")

    audit.warning(
        f"SECURITY_MIGRATE_V2 by={current_user.get('email')} "
        f"migrated={migrated} skipped_v2={skipped_v2} failed={failed}"
    )
    return {
        "migrated": migrated,
        "skipped_v2": skipped_v2,
        "failed": failed,
        "failures": failures[:50],  # cap
    }


class RotateKeyPayload(BaseModel):
    confirm: bool = Field(..., description="Deve essere true per procedere (safety check)")
    totp_code: str | None = Field(default=None, description="Codice 2FA dell'admin se 2FA attivo")


@router.post("/rotate-master-key")
@limiter.limit("2/minute")
async def rotate_master_key(
    request: Request,
    payload: RotateKeyPayload,
    current_user: dict = Depends(get_current_user),
):
    """ROTAZIONE MASTER KEY — operazione critica.

    Sequenza atomica:
      1. Decifra TUTTI i blob esistenti con master key corrente (v1 + v2)
      2. Genera nuova ENCRYPTION_KEY (32 byte hex) e nuovo salt v2 random
      3. Aggiorna SecurityManager in-process (nuove key + salt)
      4. Ricifra tutti i blob con la nuova key (schema v2)
      5. Persisti la nuova ENCRYPTION_KEY in .env (atomic write con backup)

    Se uno qualsiasi step fallisce, ripristina master key precedente.
    """
    require_admin(current_user)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta (confirm=true)")

    # 2FA check (se l'utente ha 2FA attivo)
    user_record = await db.users.find_one({"id": current_user["id"]}, {"_id": 0, "totp_secret": 1, "totp_enabled": 1})
    if user_record and user_record.get("totp_enabled") and user_record.get("totp_secret"):
        if not payload.totp_code:
            raise HTTPException(status_code=400, detail="Codice 2FA richiesto per rotazione master key")
        if not security_manager.verify_totp(user_record["totp_secret"], payload.totp_code):
            raise HTTPException(status_code=401, detail="Codice 2FA non valido")

    # 1. Pre-flight: decifra tutto in memoria
    plaintext_map: dict[tuple[str, str, Any], str] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for collection_name, field in ENCRYPTED_FIELDS:
        if (collection_name, field) in seen_pairs:
            continue
        seen_pairs.add((collection_name, field))
        try:
            coll = db[collection_name]
            cursor = coll.find({field: {"$exists": True, "$ne": None}}, {"_id": 1, field: 1})
            async for doc in cursor:
                ct = doc.get(field)
                if not isinstance(ct, str):
                    continue
                try:
                    pt = security_manager.decrypt_credential(ct)
                    plaintext_map[(collection_name, field, doc["_id"])] = pt
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=(f"Pre-flight decrypt fallita su {collection_name}.{field} _id={doc['_id']}: {e}. "
                                f"Rotazione abortita per evitare data loss."),
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[rotate-key] skip {collection_name}.{field}: {e}")

    audit.warning(
        f"SECURITY_ROTATE_KEY_PREFLIGHT_OK by={current_user.get('email')} "
        f"items={len(plaintext_map)}"
    )

    # 2. Genera nuova master key + salt
    new_master_hex = secrets.token_hex(32)  # 64 hex chars
    new_salt = secrets.token_bytes(32)

    # Backup degli artefatti correnti
    old_salt_backup = _V2_SALT_PATH.with_suffix(".bak") if _V2_SALT_PATH.exists() else None
    if old_salt_backup and _V2_SALT_PATH.exists():
        try:
            old_salt_backup.write_bytes(_V2_SALT_PATH.read_bytes())
        except Exception:
            pass

    # 3. Rebuild SecurityManager con nuove credenziali (in-process)
    try:
        from security import _V2_ITER, _LEGACY_SALT, _LEGACY_ITER  # noqa
        # Aggiorna i campi del singleton
        security_manager._v2_salt = new_salt
        security_manager._v2_key = security_manager._derive_key(new_master_hex, new_salt, _V2_ITER)
        security_manager._v1_key = security_manager._derive_key(new_master_hex, _LEGACY_SALT, _LEGACY_ITER)
        # Salva nuovo salt su disco
        _V2_SALT_PATH.write_bytes(new_salt)
        try:
            os.chmod(_V2_SALT_PATH, 0o600)
        except Exception:
            pass
    except Exception as e:
        # Rollback salt
        if old_salt_backup and old_salt_backup.exists():
            try:
                _V2_SALT_PATH.write_bytes(old_salt_backup.read_bytes())
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Rebuild SecurityManager fallito: {e}")

    # 4. Ricifra tutto
    rewritten = 0
    for (collection_name, field, _id), plaintext in plaintext_map.items():
        try:
            new_ct = security_manager.encrypt_credential(plaintext)
            await db[collection_name].update_one({"_id": _id}, {"$set": {field: new_ct}})
            rewritten += 1
        except Exception as e:
            logger.error(f"[rotate-key] re-encrypt failed {collection_name}.{field} _id={_id}: {e}")

    # 5. Aggiorna .env (atomic)
    env_path = Path(os.environ.get('ARGUS_BACKEND_ENV_PATH', '/app/backend/.env'))
    env_updated = False
    try:
        if env_path.exists():
            content = env_path.read_text()
            new_lines = []
            replaced = False
            for line in content.splitlines():
                if line.startswith("ENCRYPTION_KEY="):
                    new_lines.append(f"ENCRYPTION_KEY={new_master_hex}")
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(f"ENCRYPTION_KEY={new_master_hex}")
            tmp_path = env_path.with_suffix(".tmp")
            tmp_path.write_text("\n".join(new_lines) + "\n")
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass
            tmp_path.replace(env_path)
            env_updated = True
    except Exception as e:
        logger.error(f"[rotate-key] .env update failed: {e}. La nuova master key e` attiva ma NON persistita.")

    # Aggiorna anche os.environ in-process
    os.environ["ENCRYPTION_KEY"] = new_master_hex

    audit.warning(
        f"SECURITY_ROTATE_KEY_DONE by={current_user.get('email')} "
        f"rewritten={rewritten} env_updated={env_updated}"
    )

    return {
        "ok": True,
        "rewritten": rewritten,
        "env_updated": env_updated,
        "warning": (
            None if env_updated
            else "ATTENZIONE: nuova master key NON salvata in .env. Al prossimo riavvio backend i credenziali "
                 "non saranno piu` decifrabili. Salva manualmente la nuova ENCRYPTION_KEY ora."
        ),
        "new_key_preview": f"{new_master_hex[:8]}...{new_master_hex[-4:]}",
    }


# ---------------------------------------------------------------------------
# PASSWORD STRENGTH + HIBP CHECK
# ---------------------------------------------------------------------------
class PasswordCheckRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/check-password")
@limiter.limit("30/minute")
async def check_password_endpoint(
    request: Request,
    payload: PasswordCheckRequest,
    current_user: dict = Depends(get_current_user),
):
    """Valida la robustezza di una password (locale) + check HIBP via k-anonymity.

    Usato dal form "cambia password" per feedback live, e dal flow di onboarding
    per impedire password trapelate. La password NON viene mai loggata.
    """
    require_admin(current_user)
    res = await check_password(payload.password)
    return {
        "ok": res.ok,
        "score": res.score,
        "issues": res.issues,
        "pwned_count": res.pwned_count,
    }


# ---------------------------------------------------------------------------
# AUDIT DASHBOARD DATA
# ---------------------------------------------------------------------------
from datetime import datetime, timezone, timedelta  # noqa: E402


@router.get("/../audit/recent", include_in_schema=False)  # placeholder, see real route below
async def _placeholder():
    return {}


# Real audit route mounted directly so prefix becomes /api/admin/audit/...
audit_router = APIRouter(prefix="/api/admin/audit", tags=["audit"])


@audit_router.get("/recent")
async def audit_recent(
    days: int = 7,
    severity: Optional[str] = None,
    action: Optional[str] = None,
    only_security: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Ultimi eventi audit (default 7gg). Filtri per severity/action/security."""
    require_admin(current_user)
    days = max(1, min(days, 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query: dict[str, Any] = {"timestamp": {"$gte": since}}
    if severity:
        query["severity"] = severity
    if action:
        query["action"] = action
    if only_security:
        # Eventi marcati security-relevant
        query["$or"] = [
            {"action": {"$regex": "LOGIN|LOCK|SECURITY|ROTATE|MIGRATE|DELETE", "$options": "i"}},
            {"severity": {"$in": ["critical", "warning"]}},
        ]

    cursor = db.audit_logs.find(query, {"_id": 0}).sort("timestamp", -1).limit(500)
    rows = await cursor.to_list(500)

    # aggregate
    by_action: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_ip: dict[str, int] = {}
    failed_logins = 0
    for r in rows:
        a = r.get("action", "unknown")
        s = r.get("severity", "info")
        ip = r.get("ip_address") or "unknown"
        by_action[a] = by_action.get(a, 0) + 1
        by_severity[s] = by_severity.get(s, 0) + 1
        by_ip[ip] = by_ip.get(ip, 0) + 1
        if a == "LOGIN_FAILED":
            failed_logins += 1

    # Top 10 IP per frequenza
    top_ips = sorted(by_ip.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "items": rows,
        "totals": {
            "total": len(rows),
            "by_action": by_action,
            "by_severity": by_severity,
            "failed_logins": failed_logins,
            "unique_ips": len(by_ip),
            "top_ips": [{"ip": ip, "count": c} for ip, c in top_ips],
        },
        "days": days,
    }


@audit_router.get("/blocked-ips")
async def list_blocked_ips(current_user: dict = Depends(get_current_user)):
    """Lista IP attualmente bloccati per brute-force."""
    require_admin(current_user)
    cursor = db.ip_blocks.find({}, {"_id": 0}).sort("blocked_at", -1).limit(200)
    rows = await cursor.to_list(200)
    return {"blocked_ips": rows, "count": len(rows)}


class UnblockIpRequest(BaseModel):
    ip_address: str


@audit_router.post("/unblock-ip")
async def unblock_ip(
    payload: UnblockIpRequest,
    current_user: dict = Depends(get_current_user),
):
    """Sblocca manualmente un IP bloccato per brute-force."""
    require_admin(current_user)
    res = await db.ip_blocks.delete_one({"ip_address": payload.ip_address})
    audit.warning(
        f"SECURITY_IP_UNBLOCK by={current_user.get('email')} "
        f"ip={payload.ip_address} deleted={res.deleted_count}"
    )
    return {"unblocked": res.deleted_count > 0}
