"""Mobile Access — aggancio del telefono di un tecnico via QR SENZA password.

Modello (scelta utente 1a + 2a + 3a):
  - Ogni tecnico (user) genera dalla propria area un QR PERSONALE.
  - Il QR contiene un URL con un token OPACO a lunga durata, legato al suo user_id.
  - Il telefono apre l'URL una volta, salva il token in localStorage e resta
    "agganciato": accede a una vista di SOLO MONITORAGGIO (read-only) di tutte le
    aziende, senza reinserire la password.
  - Il token NON scade finche' non viene REVOCATO dal tecnico o da un admin.
  - A riposo salviamo solo l'hash SHA-256 del token (mai il valore in chiaro).

Sicurezza: token = secrets.token_urlsafe(32) (256 bit) => non brute-forzabile.
Scope read-only: gli endpoint /mobile/dashboard e /mobile/me NON permettono
alcuna azione di scrittura.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger("mobile_access")
router = APIRouter(prefix="/api/mobile", tags=["mobile-access"])


@router.get("/manifest")
async def mobile_manifest(t: str = ""):
    """Web App Manifest DEDICATO alla vista mobile passwordless.

    Perche': il manifest globale ha start_url="/" -> su iOS 16.4+ l'icona
    aggiunta alla Home riparte dalla root (console admin con password) e perde
    il token. Questo manifest imposta start_url="/m?t=<token>" e scope="/m",
    cosi' la web-app parte SEMPRE gia' autenticata sulla vista mobile.
    """
    tok = "".join(c for c in (t or "") if c.isalnum() or c in "-_")[:200]
    start = f"/m?t={tok}" if tok else "/m"
    manifest = {
        "short_name": "ARGUS Mobile",
        "name": "ARGUS Mobile — Monitoraggio",
        "description": "Vista mobile di monitoraggio in tempo reale (passwordless)",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
        "start_url": start,
        "scope": "/m",
        "display": "standalone",
        "theme_color": "#0a0a0f",
        "background_color": "#0a0a0f",
        "orientation": "any",
        "lang": "it",
    }
    return JSONResponse(manifest, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-store"})

COLLECTION = "mobile_access_tokens"


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_mobile_user(x_mobile_token: str | None = Header(default=None)):
    """Dependency: autentica una richiesta col token mobile (read-only)."""
    if not x_mobile_token:
        raise HTTPException(status_code=401, detail="Token mobile mancante")
    doc = await db[COLLECTION].find_one(
        {"token_hash": _hash(x_mobile_token), "revoked": {"$ne": True}}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=401, detail="Token mobile non valido o revocato")
    user = await db.users.find_one(
        {"id": doc["user_id"]}, {"_id": 0, "password_hash": 0, "totp_secret": 0}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    # last_used (best-effort, non blocca)
    try:
        await db[COLLECTION].update_one({"id": doc["id"]}, {"$set": {"last_used_at": _now_iso()}})
    except Exception:
        pass
    user["_mobile_scope"] = "read_only"
    user["_mobile_token_id"] = doc["id"]
    return user


# ==================== PAIRING (auth: utente loggato) ====================

@router.post("/pairing")
async def create_pairing(payload: dict | None = None,
                         current_user: dict = Depends(get_current_user)):
    """Crea un NUOVO token di accesso mobile per l'utente corrente.
    Ritorna il token IN CHIARO una sola volta (da mettere nel QR)."""
    label = ((payload or {}).get("device_label") or "").strip()[:60] or "Telefono"
    raw = secrets.token_urlsafe(32)
    tid = str(uuid.uuid4())
    doc = {
        "id": tid,
        "user_id": current_user["id"],
        "user_email": current_user.get("email", ""),
        "user_name": current_user.get("name", ""),
        "token_hash": _hash(raw),
        "device_label": label,
        "created_at": _now_iso(),
        "created_ip": current_user.get("_request_ip", ""),
        "last_used_at": None,
        "revoked": False,
    }
    await db[COLLECTION].insert_one(doc)
    return {"id": tid, "token": raw, "device_label": label, "created_at": doc["created_at"]}


@router.get("/pairing")
async def list_pairings(current_user: dict = Depends(get_current_user)):
    """Elenca i telefoni agganciati dell'utente corrente (senza token in chiaro)."""
    rows = await db[COLLECTION].find(
        {"user_id": current_user["id"], "revoked": {"$ne": True}},
        {"_id": 0, "token_hash": 0},
    ).sort("created_at", -1).to_list(100)
    return {"devices": rows}


@router.delete("/pairing/{token_id}")
async def revoke_pairing(token_id: str, current_user: dict = Depends(get_current_user)):
    """Revoca un token mobile. Un utente puo' revocare i propri; gli admin tutti."""
    q = {"id": token_id}
    if current_user.get("role") != "admin":
        q["user_id"] = current_user["id"]
    res = await db[COLLECTION].update_one(
        q, {"$set": {"revoked": True, "revoked_at": _now_iso(),
                     "revoked_by": current_user.get("email", "")}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Token non trovato o non tuo")
    return {"ok": True, "revoked": token_id}


@router.get("/pairing/all")
async def list_all_pairings(current_user: dict = Depends(get_current_user)):
    """(Admin) Tutti i telefoni agganciati di tutti i tecnici, per governance."""
    require_admin(current_user)
    rows = await db[COLLECTION].find(
        {"revoked": {"$ne": True}}, {"_id": 0, "token_hash": 0}
    ).sort("created_at", -1).to_list(500)
    return {"devices": rows}


# ==================== VISTA MOBILE (auth: token mobile, read-only) ====================

@router.get("/me")
async def mobile_me(mu: dict = Depends(get_mobile_user)):
    return {
        "name": mu.get("name") or mu.get("email") or "Tecnico",
        "email": mu.get("email", ""),
        "role": mu.get("role", ""),
    }


@router.get("/dashboard")
async def mobile_dashboard(mu: dict = Depends(get_mobile_user)):
    """Stessi dati aggregati della TV wallboard, ma gated dal token mobile."""
    from routes.tv_dashboard import tv_dashboard_data
    return await tv_dashboard_data()
