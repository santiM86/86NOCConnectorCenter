"""
ARGUS Center — IP Allowlist Module
===================================
Sistema di sicurezza per consentire l'accesso al Center solo da IP/CIDR autorizzati.

Logica:
- Se la collezione `allowed_ips` e' VUOTA → tutto aperto (evita lock-out durante setup)
- Se popolata → solo IP/CIDR in lista possono accedere a rotte sensibili
- Bypass automatico per:
  * /api/health (healthcheck pubblico)
  * /api/connector/* con X-API-Key valido (i connector vengono da IP cliente
    non controllabili, gia' autenticati via API key)
  * Static assets (downloads pubblici)
  * Localhost / IP interno (per debug)

Uso: middleware FastAPI installato in server.py
"""
import ipaddress
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api/admin/security", tags=["security_allowlist"])


# ============================================================
# Pydantic models
# ============================================================
class AllowedIPCreate(BaseModel):
    cidr: str = Field(..., max_length=64, description="IP singolo (1.2.3.4) o range CIDR (1.2.3.0/24)")
    description: str = Field("", max_length=256)
    enabled: bool = True


class AllowedIPUpdate(BaseModel):
    cidr: Optional[str] = Field(None, max_length=64)
    description: Optional[str] = Field(None, max_length=256)
    enabled: Optional[bool] = None


# ============================================================
# Helpers
# ============================================================
def _normalize_cidr(value: str) -> str:
    """Valida e normalizza IP/CIDR. Solleva ValueError se invalido.
    - '1.2.3.4' → '1.2.3.4/32'
    - '1.2.3.0/24' → '1.2.3.0/24'
    - '::1' → '::1/128'
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("CIDR vuoto")
    if "/" not in value:
        # IP singolo: aggiungi /32 (IPv4) o /128 (IPv6)
        ip = ipaddress.ip_address(value)
        suffix = "/32" if ip.version == 4 else "/128"
        value = f"{value}{suffix}"
    net = ipaddress.ip_network(value, strict=False)
    return str(net)


def _client_ip(request: Request) -> str:
    """Estrae l'IP client gestendo proxy/load balancer (X-Forwarded-For)."""
    # Trust X-Forwarded-For solo se viene da localhost/proxy interno
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # Prendi il PRIMO IP (client originale, non il proxy chain)
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return ""


async def _get_active_allowlist() -> list[dict]:
    cursor = db.allowed_ips.find({"enabled": True}, {"_id": 0})
    return await cursor.to_list(length=1000)


async def is_ip_allowed(client_ip: str) -> tuple[bool, str]:
    """Verifica se un IP è in allowlist.
    Returns (allowed, reason)
    - (True, "empty_list") se la lista è vuota
    - (True, "match:<cidr>") se l'IP match qualche range
    - (False, "not_in_allowlist") se non match
    - (True, "loopback") se IP locale
    - (True, "invalid_ip") se IP non parsable (fail-open su edge cases per evitare lock-out)
    """
    if not client_ip:
        return True, "no_client_ip"
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return True, "invalid_ip"

    if addr.is_loopback or addr.is_link_local:
        return True, "loopback"

    entries = await _get_active_allowlist()
    if not entries:
        return True, "empty_list"

    for e in entries:
        try:
            net = ipaddress.ip_network(e["cidr"], strict=False)
            if addr in net:
                return True, f"match:{e['cidr']}"
        except (KeyError, ValueError):
            continue

    return False, "not_in_allowlist"


# ============================================================
# Middleware
# ============================================================
# Path che bypassano sempre l'allowlist (necessari per il funzionamento del sistema)
ALLOWLIST_BYPASS_PREFIXES = (
    "/api/health",
    "/api/version",
    "/api/connector/",   # i connector vengono da IP cliente non prevedibili,
                          # ma sono autenticati via X-API-Key + HMAC
    "/api/auth/refresh",  # refresh token sempre permesso
    "/downloads/",        # ZIP pubblici
    "/static/",
    "/api/public/",
)


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Blocca richieste non in allowlist su rotte sensibili.

    Il filtro viene applicato SOLO a rotte /api/admin/* e /api/auth/login.
    Tutte le altre rotte sono libere (sono comunque protette da JWT/RBAC se
    richiedono autenticazione)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Bypass: rotte pubbliche / connector / static
        if any(path.startswith(p) for p in ALLOWLIST_BYPASS_PREFIXES):
            return await call_next(request)

        # Bypass: rotte non sensibili (lascia che l'auth JWT faccia il suo lavoro)
        # L'allowlist scatta SOLO su admin endpoints e login.
        if not (path.startswith("/api/admin/") or path == "/api/auth/login"):
            return await call_next(request)

        client_ip = _client_ip(request)
        allowed, reason = await is_ip_allowed(client_ip)
        if not allowed:
            audit.warning(f"IP_ALLOWLIST_DENY ip={client_ip} path={path} reason={reason}")
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Accesso negato: il tuo indirizzo IP non è autorizzato.",
                    "reason": "ip_not_in_allowlist",
                    "client_ip": client_ip,
                },
            )

        return await call_next(request)


# ============================================================
# Admin endpoints CRUD
# ============================================================
@router.get("/allowed-ips")
async def list_allowed_ips(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cursor = db.allowed_ips.find({}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=500)
    return {"items": items, "count": len(items)}


@router.post("/allowed-ips")
async def add_allowed_ip(payload: AllowedIPCreate, request: Request, force: bool = False, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        cidr = _normalize_cidr(payload.cidr)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"CIDR/IP non valido: {e}")

    existing = await db.allowed_ips.find_one({"cidr": cidr}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail=f"Già presente: {cidr}")

    # ANTI-LOCK-OUT: prima di abilitare un IP che NON include l'IP corrente
    # dell'admin, verifica che ci sia almeno un'altra regola attiva che lo include,
    # oppure richiedi force=true (conferma esplicita "so quello che faccio").
    admin_ip = _client_ip(request)
    if payload.enabled and not force:
        try:
            new_net = ipaddress.ip_network(cidr, strict=False)
            admin_addr = ipaddress.ip_address(admin_ip) if admin_ip else None
            covered_by_new = bool(admin_addr and admin_addr in new_net)
            covered_by_existing = False
            if not covered_by_new:
                # Cerca tra le regole esistenti enabled se almeno una include l'admin IP
                async for e in db.allowed_ips.find({"enabled": True}, {"_id": 0, "cidr": 1}):
                    try:
                        if admin_addr and admin_addr in ipaddress.ip_network(e["cidr"], strict=False):
                            covered_by_existing = True
                            break
                    except (KeyError, ValueError):
                        continue
            if admin_addr and not covered_by_new and not covered_by_existing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "lockout_risk",
                        "message": (
                            f"Salvataggio bloccato: la regola '{cidr}' NON include il tuo IP corrente {admin_ip} "
                            f"e nessuna altra regola attiva ti consentirebbe l'accesso. Salvarla ti escluderebbe dal sistema. "
                            f"Per forzare passa ?force=true (assicurati di poter accedere da un IP che corrisponde alla regola)."
                        ),
                        "your_ip": admin_ip,
                        "rule": cidr,
                    },
                )
        except HTTPException:
            raise
        except Exception:
            # Se il check fallisce per qualche motivo, NON blocca (fail-open per evitare false esclusioni)
            pass

    entry = {
        "id": __import__("uuid").uuid4().hex,
        "cidr": cidr,
        "description": payload.description or "",
        "enabled": payload.enabled,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("name", "admin"),
        "created_by_ip": admin_ip,
    }
    await db.allowed_ips.insert_one(entry)
    audit.info(f"IP_ALLOWLIST_ADD by={current_user.get('name')} cidr={cidr} desc={payload.description} force={force}")
    return {k: v for k, v in entry.items() if k != "_id"}


@router.patch("/allowed-ips/{ip_id}")
async def update_allowed_ip(ip_id: str, payload: AllowedIPUpdate, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    update = {}
    if payload.cidr is not None:
        try:
            update["cidr"] = _normalize_cidr(payload.cidr)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"CIDR non valido: {e}")
    if payload.description is not None:
        update["description"] = payload.description[:256]
    if payload.enabled is not None:
        update["enabled"] = bool(payload.enabled)
    if not update:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = current_user.get("name", "admin")
    res = await db.allowed_ips.update_one({"id": ip_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    audit.info(f"IP_ALLOWLIST_UPDATE by={current_user.get('name')} id={ip_id} fields={list(update.keys())}")
    doc = await db.allowed_ips.find_one({"id": ip_id}, {"_id": 0})
    return doc


@router.delete("/allowed-ips/{ip_id}")
async def delete_allowed_ip(ip_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.allowed_ips.delete_one({"id": ip_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    audit.info(f"IP_ALLOWLIST_DELETE by={current_user.get('name')} id={ip_id}")
    return {"status": "deleted", "id": ip_id}


@router.get("/allowed-ips/check")
async def check_my_ip(request: Request, current_user: dict = Depends(get_current_user)):
    """Endpoint diagnostico: ritorna l'IP corrente dell'admin e se è in allowlist.
    Utile per verificare prima di salvare nuove regole (evita lock-out)."""
    require_admin(current_user)
    ip = _client_ip(request)
    allowed, reason = await is_ip_allowed(ip)
    return {"client_ip": ip, "allowed": allowed, "reason": reason}
