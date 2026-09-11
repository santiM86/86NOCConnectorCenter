"""
ARGUS Center — WireGuard VPN Module
====================================
Sicurezza "military-grade" per accesso remoto on-demand ai dispositivi del cliente
attraverso il connector ARGUS, tramite tunnel WireGuard isolato per-tenant.

Architettura:
- Server WireGuard sullo stesso host del Center (o VPS dedicato).
- Ogni cliente ha un'interfaccia wg dedicata (es. wg-tenant-<client_id_short>) →
  isolamento di rete completo, zero leak cross-tenant.
- Connector genera coppia chiavi al primo avvio, registra pubkey al Center,
  riceve config (IP, peer pubkey server, endpoint) e crea il tunnel.
- Tunnel ON-DEMAND: il connector NON tiene su il tunnel sempre. Quando l'admin
  clicca "Connetti" nel Center, viene creata una `wireguard_session` (TTL 30 min),
  il connector vede il flag e lancia `wg-quick up tunnel`. Quando l'admin clicca
  "Disconnetti" o scade TTL, il connector lancia `wg-quick down`.
- Multi-tenant strict: il routing del Center forwarda solo verso la subnet del
  cliente attivo, regole iptables per-cliente.

Endpoints:
- POST /api/admin/wireguard/peer/register-public-key  — connector registra pubkey
- GET  /api/connector/wireguard/config                — connector legge sua config
- GET  /api/connector/wireguard/session               — connector long-poll session
- POST /api/admin/wireguard/session/start             — admin avvia tunnel
- POST /api/admin/wireguard/session/{id}/stop         — admin chiude tunnel
- GET  /api/admin/wireguard/peers                     — admin lista peer
- POST /api/admin/wireguard/peer/{client_id}/rotate   — admin ruota chiavi

NOTE: questo modulo gestisce SOLO il piano dati (DB schema + API).
Il setup runtime di WireGuard server (wg-quick, iptables, IP forwarding) è
fornito separatamente da `scripts/setup-wireguard-server.sh`.
"""
import ipaddress
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin, validate_api_key

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(tags=["wireguard"])

# ============================================================
# Configuration (env vars)
# ============================================================
# Subnet pool da cui assegnare IP ai peer connector. /24 per cliente di default.
WG_POOL_BASE = os.environ.get("WG_POOL_BASE", "10.86.0.0/16")
WG_SERVER_PUBKEY = os.environ.get("WG_SERVER_PUBKEY", "")  # pubkey server (impostata da setup script)
WG_SERVER_ENDPOINT = os.environ.get("WG_SERVER_ENDPOINT", "")  # es. argus.86bit.it:51820
WG_SESSION_TTL_MIN = int(os.environ.get("WG_SESSION_TTL_MIN", "30"))


# ============================================================
# Pydantic models
# ============================================================
class PeerRegisterPublicKey(BaseModel):
    public_key: str = Field(..., min_length=43, max_length=44, description="WireGuard public key base64")


class SessionStart(BaseModel):
    client_id: str
    ttl_minutes: Optional[int] = None
    target_device_ip: Optional[str] = None  # se fornito, audit info per log
    reason: Optional[str] = ""
    # v3.5.19: se True, l'AllowedIPs del tunnel sarà ristretta SOLO agli IP dei
    # device registrati nel connector per quel cliente. Default False = backward compat.
    restrict_to_registered_devices: Optional[bool] = False


# ============================================================
# Helpers
# ============================================================
def _is_valid_wg_pubkey(key: str) -> bool:
    """WireGuard pubkey base64 = 32 bytes raw → 44 chars b64 (con padding =)."""
    if not key or not isinstance(key, str):
        return False
    key = key.strip()
    if len(key) != 44 or not key.endswith("="):
        return False
    try:
        import base64
        raw = base64.b64decode(key, validate=True)
        return len(raw) == 32
    except Exception:
        return False


async def _trigger_embedded_sync_best_effort() -> None:
    """Se il runtime WireGuard embedded e` attivo, forza una riconciliazione
    peer immediata cosi` la modifica DB (session start/stop) si traduce in
    azione sul tunnel entro pochi millisecondi invece dei 5s del loop.
    Best-effort: any error e` swallowed (il sync loop fara` comunque catch-up)."""
    try:
        from wireguard_embedded import wg_manager
        if wg_manager.process and wg_manager.process.poll() is None:
            await wg_manager._reconcile_peers(db)
    except Exception as e:
        logger.debug(f"WG embedded sync trigger skipped: {e}")


async def _allocate_peer_ip(client_id: str) -> str:
    """Assegna un IP libero dalla pool /16 al peer.
    Strategia: usa client_id hash → IP deterministico. Se collide, scan sequenziale."""
    pool = ipaddress.ip_network(WG_POOL_BASE, strict=False)
    used = set()
    async for p in db.wireguard_peers.find({}, {"_id": 0, "tunnel_ip": 1}):
        if p.get("tunnel_ip"):
            used.add(p["tunnel_ip"])
    # Skip .0 e .1 (network + server)
    skip = {str(pool.network_address), str(pool.network_address + 1)}
    for host in pool.hosts():
        ip = str(host)
        if ip in skip or ip in used:
            continue
        return ip
    raise HTTPException(status_code=507, detail="WireGuard pool esaurita")


# ============================================================
# CONNECTOR-FACING ENDPOINTS (X-API-Key auth)
# ============================================================
@router.post("/api/connector/wireguard/register-public-key")
async def connector_register_pubkey(payload: PeerRegisterPublicKey, request: Request):
    """Il connector registra la propria pubkey WireGuard.
    Idempotent: se pubkey identica → no-op. Se cambiata → ruota IP+config.

    v3.5.20 HARDENING: ad ogni nuova registrazione genera un Pre-Shared Key (PSK)
    32-byte random associato al peer. Il PSK è additivo alla normale crittografia
    (ChaCha20-Poly1305 + Curve25519): se in futuro Curve25519 viene rotto da
    computer quantistici, il PSK preserva la confidenzialità ("post-quantum bridge").
    Standard NSA CSfC (Commercial Solutions for Classified) per dati classified.
    """
    client_data = await validate_api_key(request)
    client_id = client_data["id"]

    if not _is_valid_wg_pubkey(payload.public_key):
        raise HTTPException(status_code=400, detail="Public key WireGuard non valida (formato base64 32-byte richiesto)")

    existing = await db.wireguard_peers.find_one({"client_id": client_id}, {"_id": 0})
    if existing and existing.get("public_key") == payload.public_key:
        # Idempotente: stessa pubkey → ritorna config esistente (incluso PSK persistente)
        return {
            "status": "unchanged",
            "tunnel_ip": existing["tunnel_ip"],
            "server_public_key": WG_SERVER_PUBKEY or "(server-not-configured)",
            "server_endpoint": WG_SERVER_ENDPOINT or "(server-not-configured)",
            "allowed_ips": existing.get("allowed_ips", "10.86.0.0/16"),
            "preshared_key": existing.get("preshared_key", ""),
        }

    # Genera PSK 32-byte random (uguale formato wg.exe genpsk)
    import base64 as _b64
    psk = _b64.b64encode(secrets.token_bytes(32)).decode()

    if existing:
        # Pubkey cambiata → mantieni stesso tunnel_ip ma RUOTA anche il PSK
        # (paranoia: se la pubkey cambia, assumiamo possible compromise)
        new_doc = dict(existing)
        new_doc["public_key"] = payload.public_key
        new_doc["preshared_key"] = psk
        new_doc["public_key_rotated_at"] = datetime.now(timezone.utc).isoformat()
        await db.wireguard_peers.update_one({"client_id": client_id}, {"$set": new_doc})
        audit.warning(f"WG_PEER_KEY_ROTATED client_id={client_id} (pubkey + PSK rotated)")
        return {
            "status": "rotated",
            "tunnel_ip": existing["tunnel_ip"],
            "server_public_key": WG_SERVER_PUBKEY or "(server-not-configured)",
            "server_endpoint": WG_SERVER_ENDPOINT or "(server-not-configured)",
            "allowed_ips": existing.get("allowed_ips", "10.86.0.0/16"),
            "preshared_key": psk,
        }

    # Nuovo peer: alloca IP, genera PSK, salva
    tunnel_ip = await _allocate_peer_ip(client_id)
    doc = {
        "id": uuid.uuid4().hex,
        "client_id": client_id,
        "client_name": client_data.get("name", ""),
        "public_key": payload.public_key,
        "preshared_key": psk,
        "tunnel_ip": tunnel_ip,
        "allowed_ips": "10.86.0.0/16",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_rotation_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    await db.wireguard_peers.insert_one(doc)
    audit.info(f"WG_PEER_REGISTERED client_id={client_id} tunnel_ip={tunnel_ip} psk_generated=true")
    return {
        "status": "created",
        "tunnel_ip": tunnel_ip,
        "server_public_key": WG_SERVER_PUBKEY or "(server-not-configured)",
        "server_endpoint": WG_SERVER_ENDPOINT or "(server-not-configured)",
        "allowed_ips": doc["allowed_ips"],
        "preshared_key": psk,
    }


@router.get("/api/connector/wireguard/config")
async def connector_get_config(request: Request):
    """Il connector richiede la sua config WireGuard.
    Ritorna 404 se peer non registrato (connector deve registrare prima)."""
    client_data = await validate_api_key(request)
    peer = await db.wireguard_peers.find_one({"client_id": client_data["id"]}, {"_id": 0})
    if not peer:
        raise HTTPException(status_code=404, detail="Peer non registrato. Esegui prima register-public-key.")
    return {
        "tunnel_ip": peer["tunnel_ip"],
        "server_public_key": WG_SERVER_PUBKEY or "(server-not-configured)",
        "server_endpoint": WG_SERVER_ENDPOINT or "(server-not-configured)",
        "allowed_ips": peer.get("allowed_ips", "10.86.0.0/16"),
        "preshared_key": peer.get("preshared_key", ""),
        "active": peer.get("active", True),
        "interface_name": f"wg-{client_data['id'][:8]}",
        "last_rotation_at": peer.get("last_rotation_at", peer.get("created_at", "")),
    }


@router.get("/api/connector/wireguard/session")
async def connector_poll_session(request: Request):
    """Long-poll endpoint per il connector: ritorna se c'è una session attiva
    o il flag 'pending start/stop' per il tunnel WireGuard.
    Polling ogni ~5s dal connector quando configurato."""
    client_data = await validate_api_key(request)
    cid = client_data["id"]
    now = datetime.now(timezone.utc)

    # Mark scaduti
    await db.wireguard_sessions.update_many(
        {"client_id": cid, "status": "active", "expires_at": {"$lt": now.isoformat()}},
        {"$set": {"status": "expired", "ended_at": now.isoformat()}},
    )

    active = await db.wireguard_sessions.find_one(
        {"client_id": cid, "status": "active"}, {"_id": 0}, sort=[("started_at", -1)]
    )
    if active:
        return {
            "tunnel_required": True,
            "session_id": active["id"],
            "expires_at": active["expires_at"],
            "started_by": active.get("started_by", ""),
            "target_device_ip": active.get("target_device_ip", ""),
            "allowed_device_ips": active.get("allowed_device_ips", []),
            "restrict_mode": active.get("restrict_mode", False),
            # v3.5.21: PSK ephemeral generato per questa sessione. Il connector lo usa
            # nel .conf WireGuard al posto del PSK statico del peer. Materiale crittografico
            # fresco per ogni connessione.
            "ephemeral_psk": active.get("ephemeral_psk", ""),
        }
    return {"tunnel_required": False}


# ============================================================
# ADMIN-FACING ENDPOINTS (JWT auth)
# ============================================================
@router.get("/api/admin/wireguard/peers")
async def admin_list_peers(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cursor = db.wireguard_peers.find({}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=500)
    return {"items": items, "count": len(items)}


@router.get("/api/admin/wireguard/server-status")
async def admin_server_status(current_user: dict = Depends(get_current_user)):
    """Ritorna lo stato della config server WireGuard (env var presenti?)."""
    require_admin(current_user)
    return {
        "server_pubkey_configured": bool(WG_SERVER_PUBKEY),
        "server_endpoint_configured": bool(WG_SERVER_ENDPOINT),
        "server_endpoint": WG_SERVER_ENDPOINT if WG_SERVER_ENDPOINT else "",
        "pool_base": WG_POOL_BASE,
        "session_ttl_minutes": WG_SESSION_TTL_MIN,
        "ready": bool(WG_SERVER_PUBKEY and WG_SERVER_ENDPOINT),
    }


@router.get("/api/admin/wireguard/embedded/status")
async def admin_embedded_status(current_user: dict = Depends(get_current_user)):
    """[POC v1] Stato del runtime WireGuard embedded (`wireguard-go` userspace
    bundlato dentro il backend). Risponde a "il Center sta gestendo da solo
    il server WG, senza che io abbia installato nulla?".

    Ritorna:
    - environment.binary_present: i binari sono nel repo?
    - environment.tun_device_available: /dev/net/tun esiste?
    - environment.cap_net_admin: il backend gira con CAP_NET_ADMIN?
    - environment.ready_to_start: tutti i prerequisiti soddisfatti?
    - environment.missing_prerequisites: lista esatta dei requisiti mancanti
    - running, pid, started_at: stato del subprocess
    - last_error: motivo se non e` partito
    - public_key: pubkey server (se gia` derivata)

    Quando `enabled=true` ma `running=false` con `missing_prerequisites` popolato,
    indica al sysadmin esattamente cosa configurare sull'host (di solito basta
    una capability oppure il device TUN nel container)."""
    require_admin(current_user)
    try:
        from wireguard_embedded import wg_manager
    except Exception as e:
        return {
            "enabled": False,
            "running": False,
            "last_error": f"manager import failed: {e}",
        }
    status = wg_manager.status()
    # Se il subprocess e` vivo, prova a leggere lo stato live via UAPI
    if status.get("running"):
        try:
            uapi = await wg_manager.get_uapi_state()
            status["uapi"] = uapi
        except Exception as e:
            status["uapi"] = {"available": False, "reason": str(e)}
    return status


@router.post("/api/admin/wireguard/embedded/start")
async def admin_embedded_start(current_user: dict = Depends(get_current_user)):
    """[POC v1] Avvia (o re-avvia) il runtime embedded. Idempotent: se gia`
    running, ritorna lo status corrente senza side-effect.

    NB: se i prerequisiti host non sono soddisfatti (TUN, CAP_NET_ADMIN), la
    chiamata NON solleva — torna status con `running=false` e `last_error`
    descrittivo. Cosi` la UI puo` mostrare il motivo invece di un 500."""
    require_admin(current_user)
    try:
        from wireguard_embedded import wg_manager
        return await wg_manager.start()
    except Exception as e:
        logger.error(f"Embedded WG start error: {e}")
        return {"enabled": False, "running": False, "last_error": str(e)}


@router.post("/api/admin/wireguard/embedded/stop")
async def admin_embedded_stop(current_user: dict = Depends(get_current_user)):
    """[POC v1] Stop pulito del runtime embedded."""
    require_admin(current_user)
    try:
        from wireguard_embedded import wg_manager
        return await wg_manager.stop()
    except Exception as e:
        logger.error(f"Embedded WG stop error: {e}")
        return {"enabled": False, "running": False, "last_error": str(e)}


@router.post("/api/admin/wireguard/embedded/sync-now")
async def admin_embedded_sync_now(current_user: dict = Depends(get_current_user)):
    """[Fase 2] Forza una riconciliazione peer immediata invece di aspettare
    il prossimo tick del loop (5s). Utile dopo una session start/stop per
    feedback istantaneo nell'UI."""
    require_admin(current_user)
    try:
        from wireguard_embedded import wg_manager
        from database import db as _db
        await wg_manager._reconcile_peers(_db)
        return wg_manager.status().get("peer_sync", {})
    except Exception as e:
        logger.error(f"Embedded WG sync-now error: {e}")
        return {"error": str(e)}


@router.get("/api/admin/wireguard/embedded/server-pubkey")
async def admin_embedded_pubkey(current_user: dict = Depends(get_current_user)):
    """[Fase 2] Ritorna pubkey + endpoint del server WireGuard embedded.
    Usato dal connector per costruire il proprio .conf WireGuard.

    Se il manager non ha ancora generato la chiave (es. non lanciato),
    la genera al volo via `_ensure_keys()` cosi` la pubkey e` immediatamente
    disponibile anche in modalita` "preview/dry-run"."""
    require_admin(current_user)
    try:
        from wireguard_embedded import wg_manager
        if not wg_manager._public_key_b64:
            wg_manager._ensure_keys()
        return {
            "public_key": wg_manager._public_key_b64 or "",
            "endpoint": os.environ.get("WG_SERVER_ENDPOINT", ""),
            "listen_port": int(os.environ.get("WG_EMBEDDED_LISTEN_PORT", "51820")),
            "interface": os.environ.get("WG_EMBEDDED_INTERFACE", "wg-argus"),
            "tunnel_cidr": os.environ.get("WG_EMBEDDED_TUNNEL_CIDR", "10.86.0.1/16"),
        }
    except Exception as e:
        logger.error(f"Embedded WG pubkey error: {e}")
        return {"public_key": "", "error": str(e)}


@router.post("/api/admin/wireguard/session/start")
async def admin_start_session(payload: SessionStart, request: Request, current_user: dict = Depends(get_current_user)):
    """Avvia una sessione VPN on-demand: il connector del cliente attiverà
    il tunnel al prossimo poll (~entro 5 secondi).

    v3.5.19: se restrict_to_registered_devices=True, calcola la lista degli IP
    dei device registrati nel connector per quel cliente e la include nella
    sessione come `allowed_device_ips` (lista /32). Il connector userà questa
    lista come AllowedIPs nel proprio .conf WireGuard, garantendo che il tunnel
    NON apra accesso all'intera rete del cliente — solo agli IP target legittimi.
    """
    require_admin(current_user)

    peer = await db.wireguard_peers.find_one({"client_id": payload.client_id, "active": True}, {"_id": 0})
    if not peer:
        raise HTTPException(status_code=404, detail="Peer WireGuard non registrato per questo cliente")

    # Chiudi eventuali sessioni precedenti dello stesso cliente
    now = datetime.now(timezone.utc)
    await db.wireguard_sessions.update_many(
        {"client_id": payload.client_id, "status": "active"},
        {"$set": {"status": "superseded", "ended_at": now.isoformat()}},
    )

    ttl = payload.ttl_minutes or WG_SESSION_TTL_MIN
    if ttl < 1 or ttl > 240:
        raise HTTPException(status_code=400, detail="TTL deve essere tra 1 e 240 minuti")

    # v3.5.20: build allowed_device_ips se restrict mode attivo
    allowed_device_ips = []
    if payload.restrict_to_registered_devices:
        cursor = db.managed_devices.find(
            {"client_id": payload.client_id, "monitor_type": {"$ne": "external"}},
            {"_id": 0, "ip": 1, "ip_address": 1},
        )
        async for d in cursor:
            ip = d.get("ip") or d.get("ip_address")
            if ip:
                allowed_device_ips.append(f"{ip}/32")
        if not allowed_device_ips:
            raise HTTPException(
                status_code=422,
                detail="Nessun device registrato nel connector per questo cliente: la VPN ristretta non avrebbe target accessibili.",
            )
        if payload.target_device_ip and f"{payload.target_device_ip}/32" not in allowed_device_ips:
            raise HTTPException(
                status_code=422,
                detail=f"Il device target {payload.target_device_ip} non è registrato nel connector di questo cliente. Per sicurezza la VPN ristretta consente solo device monitorati.",
            )

    # v3.5.21: EPHEMERAL PSK per sessione. Ogni nuova sessione genera un Pre-Shared Key
    # secondario UNICO che si applica solo a quella sessione e viene distrutto alla
    # chiusura. Anche se un attaccante intercetta o ruba il PSK statico del peer, ha
    # accesso solo per la durata di una singola sessione (max 30 min default).
    # Sicurezza max: ogni connessione ha materiale crittografico fresco.
    import base64 as _b64
    ephemeral_psk = _b64.b64encode(secrets.token_bytes(32)).decode()

    session = {
        "id": uuid.uuid4().hex,
        "client_id": payload.client_id,
        "client_name": peer.get("client_name", ""),
        "tunnel_ip": peer["tunnel_ip"],
        "target_device_ip": payload.target_device_ip or "",
        "reason": payload.reason or "",
        "started_at": now.isoformat(),
        "started_by": current_user.get("name", "admin"),
        "started_by_user_id": current_user.get("id", ""),
        "expires_at": (now + timedelta(minutes=ttl)).isoformat(),
        "status": "active",
        "restrict_mode": bool(payload.restrict_to_registered_devices),
        "allowed_device_ips": allowed_device_ips,
        "ephemeral_psk": ephemeral_psk,
    }
    await db.wireguard_sessions.insert_one(session)
    audit.info(
        f"WG_SESSION_START by={current_user.get('name')} client_id={payload.client_id} "
        f"target={payload.target_device_ip} ttl={ttl}min reason={payload.reason} "
        f"restrict={payload.restrict_to_registered_devices} allowed_ips={len(allowed_device_ips)} ephemeral_psk=true"
    )
    # Sync immediato col runtime embedded se presente
    await _trigger_embedded_sync_best_effort()
    return {k: v for k, v in session.items() if k != "_id"}


@router.post("/api/admin/wireguard/session/stop-by-target")
async def admin_stop_session_by_target(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """v3.5.21: chiude sessioni VPN attive che corrispondono a (client_id, target_device_ip).
    Chiamato dal frontend quando l'admin chiude il pannello Web Console — garantisce che
    la VPN si chiuda IMMEDIATAMENTE invece di aspettare TTL 30 min.
    Body: {"client_id": "...", "target_device_ip": "..."}
    """
    require_admin(current_user)
    body = await request.json()
    client_id = body.get("client_id", "")
    target = body.get("target_device_ip", "")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")
    now = datetime.now(timezone.utc)
    query = {"client_id": client_id, "status": "active"}
    if target:
        query["target_device_ip"] = target
    res = await db.wireguard_sessions.update_many(
        query,
        {"$set": {"status": "stopped", "ended_at": now.isoformat(), "stopped_by": current_user.get("name", "admin"), "stopped_reason": "web_console_closed"}},
    )
    if res.modified_count > 0:
        audit.info(f"WG_SESSION_STOP by={current_user.get('name')} client_id={client_id} target={target} reason=web_console_closed count={res.modified_count}")
    await _trigger_embedded_sync_best_effort()
    return {"status": "ok", "stopped_count": res.modified_count}


@router.post("/api/admin/wireguard/session/{session_id}/stop")
async def admin_stop_session(session_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    now = datetime.now(timezone.utc)
    res = await db.wireguard_sessions.update_one(
        {"id": session_id, "status": "active"},
        {"$set": {"status": "stopped", "ended_at": now.isoformat(), "stopped_by": current_user.get("name", "admin")}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Sessione non trovata o già chiusa")
    audit.info(f"WG_SESSION_STOP by={current_user.get('name')} session_id={session_id}")
    await _trigger_embedded_sync_best_effort()
    return {"status": "stopped", "id": session_id}


@router.get("/api/admin/wireguard/sessions")
async def admin_list_sessions(client_id: Optional[str] = None, limit: int = 50, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    query = {}
    if client_id:
        query["client_id"] = client_id
    cursor = db.wireguard_sessions.find(query, {"_id": 0}).sort("started_at", -1).limit(min(limit, 500))
    items = await cursor.to_list(length=limit)
    return {"items": items, "count": len(items)}


@router.post("/api/admin/wireguard/peer/{client_id}/disable")
async def admin_disable_peer(client_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.wireguard_peers.update_one(
        {"client_id": client_id},
        {"$set": {"active": False, "disabled_at": datetime.now(timezone.utc).isoformat(), "disabled_by": current_user.get("name", "admin")}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Peer non trovato")
    audit.warning(f"WG_PEER_DISABLED by={current_user.get('name')} client_id={client_id}")
    return {"status": "disabled", "client_id": client_id}


@router.post("/api/admin/wireguard/peer/{client_id}/force-key-rotation")
async def admin_force_key_rotation(client_id: str, current_user: dict = Depends(get_current_user)):
    """Forza la rotazione delle chiavi (pubkey + PSK) per il peer indicato.
    Il connector al prossimo poll rileverà il `force_rotation_pending` e
    rigenererà la coppia chiavi locale + ri-registrerà la nuova pubkey.

    Use case: chiave sospetta di compromissione, audit periodico, scheduled rotation.
    """
    require_admin(current_user)
    peer = await db.wireguard_peers.find_one({"client_id": client_id}, {"_id": 0})
    if not peer:
        raise HTTPException(status_code=404, detail="Peer non trovato")
    await db.wireguard_peers.update_one(
        {"client_id": client_id},
        {"$set": {
            "force_rotation_pending": True,
            "force_rotation_requested_at": datetime.now(timezone.utc).isoformat(),
            "force_rotation_requested_by": current_user.get("name", "admin"),
        }},
    )
    audit.warning(f"WG_FORCE_ROTATION by={current_user.get('name')} client_id={client_id}")
    return {"status": "rotation_pending", "client_id": client_id, "message": "Il connector ruoterà le chiavi al prossimo polling cycle (~5 min max)"}


@router.get("/api/connector/wireguard/rotation-pending")
async def connector_check_rotation(request: Request):
    """Il connector chiama questo endpoint nel polling loop per verificare
    se l'admin ha richiesto una key rotation forzata. Se True, il connector
    rigenera coppia chiavi e ri-registra. Idempotent: il flag viene resettato
    al register-public-key successivo (perché la pubkey diversa lo invalida)."""
    client_data = await validate_api_key(request)
    peer = await db.wireguard_peers.find_one({"client_id": client_data["id"]}, {"_id": 0, "force_rotation_pending": 1})
    return {"rotation_pending": bool(peer and peer.get("force_rotation_pending"))}


@router.post("/api/admin/wireguard/peer/{client_id}/clear-rotation-flag")
async def admin_clear_rotation_flag(client_id: str, current_user: dict = Depends(get_current_user)):
    """Pulisce il flag rotation_pending dopo che il connector ha completato la rotazione."""
    require_admin(current_user)
    await db.wireguard_peers.update_one(
        {"client_id": client_id},
        {"$set": {"force_rotation_pending": False, "last_rotation_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "cleared"}
