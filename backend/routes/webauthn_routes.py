"""Passkey (WebAuthn / FIDO2) — login passwordless + registrazione.

- Login PASSWORDLESS: la passkey sostituisce la password (credenziali discoverable).
- Il 2FA TOTP resta come fallback (login classico password+TOTP ancora attivo).
- Registrazione passkey: richiede una sessione JWT valida (l'utente si logga col
  metodo classico e poi aggiunge la passkey dalle impostazioni).
Le passkey sono legate al dominio (rpId): registri sul dominio dove le userai.
"""
import base64
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from database import db
from deps import (
    get_current_user, create_token, create_refresh_token, store_refresh_token,
)

router = APIRouter(prefix="/api/auth/webauthn", tags=["webauthn"])

# Solo origini allowlisted → rpId fisso per dominio (mai derivato dal client).
RP_CONFIG = {
    "https://argus.86bit.it": {"rp_id": "argus.86bit.it", "rp_name": "ARGUS NOC"},
    "https://noc-alert-hub-2.preview.emergentagent.com": {
        "rp_id": "noc-alert-hub-2.preview.emergentagent.com", "rp_name": "ARGUS NOC (preview)"},
    "http://localhost:3000": {"rp_id": "localhost", "rp_name": "ARGUS (local)"},
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _ceremony_config(request: Request):
    # L'ingress preview RISCRIVE l'header Origin sull'host interno del cluster
    # (es. ...cluster-12.preview.emergentcf.cloud) mentre l'host pubblico reale
    # arriva in x-forwarded-host. WebAuthn richiede che rpId/origin combacino con
    # il dominio EFFETTIVO della pagina nel browser, quindi ricostruiamo l'origine
    # pubblica da più header e la validiamo contro l'allowlist RP_CONFIG.
    candidates = []
    xfh = request.headers.get("x-forwarded-host")
    if xfh:
        host = xfh.split(",")[0].strip()
        proto = (request.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
        candidates.append(f"{proto}://{host}")
    origin = request.headers.get("origin")
    if origin:
        candidates.append(origin)
    host = request.headers.get("host")
    if host:
        candidates.append(f"https://{host}")
        candidates.append(f"http://{host}")
    for cand in candidates:
        cfg = RP_CONFIG.get(cand)
        if cfg:
            return cand, cfg
    raise HTTPException(400, "Origine WebAuthn non approvata")


async def _save_challenge(kind, challenge, origin, cfg, user_id=None):
    token = secrets.token_urlsafe(32)
    await db.webauthn_challenges.insert_one({
        "_id": token, "kind": kind, "user_id": user_id,
        "challenge": _b64(challenge), "rp_id": cfg["rp_id"], "origin": origin,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    })
    return token


async def _consume_challenge(token, kind, origin, cfg):
    doc = await db.webauthn_challenges.find_one_and_delete({
        "_id": token, "kind": kind, "origin": origin, "rp_id": cfg["rp_id"],
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not doc:
        raise HTTPException(400, "Cerimonia non valida, scaduta o ripetuta")
    return _unb64(doc["challenge"]), doc.get("user_id")


@router.post("/register/begin")
async def register_begin(request: Request, current_user: dict = Depends(get_current_user)):
    origin, cfg = _ceremony_config(request)
    user_id = current_user["id"]
    existing = []
    async for c in db.webauthn_credentials.find(
        {"user_id": user_id, "rp_id": cfg["rp_id"]}, {"credential_id": 1}):
        existing.append({"id": _unb64(c["credential_id"]), "type": "public-key"})
    challenge = secrets.token_bytes(32)
    options = generate_registration_options(
        rp_id=cfg["rp_id"], rp_name=cfg["rp_name"],
        user_id=user_id.encode("utf-8")[:64],
        user_name=current_user.get("email", user_id),
        user_display_name=current_user.get("name", user_id),
        challenge=challenge,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=existing,
        supported_pub_key_algs=[COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256],
    )
    token = await _save_challenge("register", challenge, origin, cfg, user_id)
    return {"ceremony_token": token, "publicKey": json.loads(options_to_json(options))}


@router.post("/register/complete")
async def register_complete(request: Request, body: dict, current_user: dict = Depends(get_current_user)):
    origin, cfg = _ceremony_config(request)
    user_id = current_user["id"]
    challenge, challenge_user = await _consume_challenge(body["ceremony_token"], "register", origin, cfg)
    if challenge_user != user_id:
        raise HTTPException(403, "Utente della cerimonia non corrispondente")
    v = verify_registration_response(
        credential=body["credential"], expected_challenge=challenge,
        expected_rp_id=cfg["rp_id"], expected_origin=origin, require_user_verification=True,
    )
    await db.webauthn_credentials.insert_one({
        "credential_id": _b64(v.credential_id), "user_id": user_id,
        "public_key": _b64(v.credential_public_key), "sign_count": v.sign_count,
        "transports": body["credential"].get("response", {}).get("transports", []),
        "device_type": str(v.credential_device_type), "backed_up": v.credential_backed_up,
        "label": body.get("label") or "Passkey", "rp_id": cfg["rp_id"], "origin": origin,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.users.update_one({"id": user_id}, {"$set": {"passkey_enabled": True}})
    return {"ok": True}


@router.get("/credentials")
async def list_credentials(request: Request, current_user: dict = Depends(get_current_user)):
    creds = []
    async for c in db.webauthn_credentials.find({"user_id": current_user["id"]}, {"_id": 0, "public_key": 0}):
        creds.append(c)
    return {"credentials": creds}


@router.delete("/credentials/{credential_id}")
async def delete_credential(credential_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.webauthn_credentials.delete_one(
        {"credential_id": credential_id, "user_id": current_user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Passkey non trovata")
    remaining = await db.webauthn_credentials.count_documents({"user_id": current_user["id"]})
    if remaining == 0:
        await db.users.update_one({"id": current_user["id"]}, {"$set": {"passkey_enabled": False}})
    return {"ok": True, "remaining": remaining}


@router.get("/admin/users")
async def admin_list_passkey_users(current_user: dict = Depends(get_current_user)):
    """Zona Admin: elenco utenti con conteggio passkey registrate."""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Solo amministratori")
    users = await db.users.find({}, {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1}).to_list(1000)
    out = []
    for u in users:
        n = await db.webauthn_credentials.count_documents({"user_id": u["id"]})
        out.append({**u, "passkey_count": n})
    return {"users": out}


@router.post("/admin/reset/{user_id}")
async def admin_reset_passkeys(user_id: str, current_user: dict = Depends(get_current_user)):
    """Zona Admin: azzera TUTTE le passkey di un utente (es. chiave persa/rubata).
    L'utente torna a poter accedere con password + TOTP di fallback."""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Solo amministratori")
    r = await db.webauthn_credentials.delete_many({"user_id": user_id})
    await db.users.update_one({"id": user_id}, {"$set": {"passkey_enabled": False}})
    return {"ok": True, "deleted": r.deleted_count}


@router.post("/authenticate/begin")
async def authenticate_begin(request: Request, body: dict = None):
    origin, cfg = _ceremony_config(request)
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=cfg["rp_id"], challenge=challenge,
        allow_credentials=None,  # discoverable passkey (passwordless)
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    token = await _save_challenge("authenticate", challenge, origin, cfg)
    return {"ceremony_token": token, "publicKey": json.loads(options_to_json(options))}


@router.post("/authenticate/complete")
async def authenticate_complete(request: Request, body: dict):
    origin, cfg = _ceremony_config(request)
    challenge, _ = await _consume_challenge(body["ceremony_token"], "authenticate", origin, cfg)
    credential = body["credential"]
    stored = await db.webauthn_credentials.find_one(
        {"credential_id": credential["id"], "rp_id": cfg["rp_id"]})
    if not stored:
        raise HTTPException(401, "Credenziale sconosciuta")
    v = verify_authentication_response(
        credential=credential, expected_challenge=challenge,
        expected_rp_id=cfg["rp_id"], expected_origin=origin,
        credential_public_key=_unb64(stored["public_key"]),
        credential_current_sign_count=stored["sign_count"], require_user_verification=True,
    )
    await db.webauthn_credentials.update_one(
        {"_id": stored["_id"]}, {"$set": {"sign_count": v.new_sign_count}})
    user = await db.users.find_one({"id": stored["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(401, "Utente non trovato")
    ip = request.client.host if request.client else "unknown"
    # Sessione completa passwordless (2FA non richiesto: la passkey è forte già di suo)
    token = create_token(user["id"], user["email"], requires_2fa=False)
    refresh = create_refresh_token(user["id"])
    await store_refresh_token(user["id"], refresh, ip)
    return {
        "token": token, "refresh_token": refresh,
        "user": {"id": user["id"], "email": user["email"], "name": user.get("name"),
                 "role": user.get("role"), "two_factor_enabled": user.get("two_factor_enabled", False)},
    }
