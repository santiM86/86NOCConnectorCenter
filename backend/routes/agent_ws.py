"""86NocAgent v4 — WebSocket endpoint and HTTP control plane.

This is the server side of the new native Go agent. It exposes:

  WS  /api/agent/ws                   — persistent agent <-> server channel
  POST /api/agents/register           — admin issues a registration token
  GET  /api/agents                    — list connected/known agents
  POST /api/agents/{agent_id}/command — send a server.command to an agent

The agent protocol is implemented in /app/noc-agent/pkg/proto/messages.go;
this module mirrors the Frame envelope and the type constants.

Persistence:
  - managed_agents (one doc per agent_id with last hello/heartbeat)
  - discovered_endpoints (bridged from agent.event kind=discovery_batch)
  - device_poll_status (bridged from agent.event kind=snmp_poll)

Anti-pattern note: we keep this MVP in a single in-process registry. When
we deploy >1 backend replica we'll move command pubsub onto Mongo change
streams or Redis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agent-v4"])

PROTOCOL_VERSION = 1

# ---- Frame envelope helpers --------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_frame(typ: str, payload: Any, *, seq: int, corr_id: str = "") -> Dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "type": typ,
        "seq": seq,
        "corr_id": corr_id,
        "sent_at": _now().isoformat(),
        "payload": payload,
    }


# ---- In-process agent registry ----------------------------------------------

class _Connection:
    """One live WebSocket session bound to an agent_id."""

    def __init__(self, agent_id: str, client_id: str, ws: WebSocket):
        self.agent_id = agent_id
        self.client_id = client_id
        self.ws = ws
        self.seq = 0
        self.connected_at = _now()
        self.pending: Dict[str, asyncio.Future] = {}

    async def send(self, frame: Dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(frame, default=str))

    async def send_command(self, name: str, args: Optional[Dict[str, Any]] = None,
                           timeout: float = 30.0) -> Dict[str, Any]:
        """Send a server.command and await the matching agent.reply.

        Returns the AgentReply payload dict. Raises asyncio.TimeoutError on no reply.
        """
        self.seq += 1
        corr_id = uuid.uuid4().hex
        frame = make_frame(
            "server.command",
            {"name": name, "args": args or {}},
            seq=self.seq,
            corr_id=corr_id,
        )
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending[corr_id] = fut
        try:
            await self.send(frame)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self.pending.pop(corr_id, None)


class _Registry:
    """Registry of currently connected agents, keyed by agent_id."""

    def __init__(self) -> None:
        self._conns: Dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    async def add(self, conn: _Connection) -> None:
        async with self._lock:
            old = self._conns.get(conn.agent_id)
            if old is not None and old is not conn:
                try:
                    await old.ws.close(code=status.WS_1008_POLICY_VIOLATION)
                except Exception:  # noqa: BLE001
                    pass
            self._conns[conn.agent_id] = conn

    async def remove(self, agent_id: str, conn: _Connection) -> None:
        async with self._lock:
            cur = self._conns.get(agent_id)
            if cur is conn:
                self._conns.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[_Connection]:
        return self._conns.get(agent_id)

    def list(self) -> List[_Connection]:
        return list(self._conns.values())


REGISTRY = _Registry()


# ---- Auth: registration tokens ----------------------------------------------
#
# The legacy connector uses HMAC + obfuscated paths. For v4 we keep it
# simpler: the admin generates a one-time-ish bearer that the agent stores
# in agent.yaml. The token document records the client_id binding so a
# stolen token cannot impersonate another tenant.

async def _validate_token(token: str, claimed_client_id: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    # 1. agent_tokens classico
    doc = await db.agent_tokens.find_one({"token": token, "revoked": {"$ne": True}}, {"_id": 0})
    if doc and doc.get("client_id") == claimed_client_id:
        return doc
    # 2. fallback: api_key del cliente (mostrata nella pagina Clienti)
    client = await db.clients.find_one({"api_key": token}, {"_id": 0, "client_id": 1})
    if client and client.get("client_id") == claimed_client_id:
        # Costruisci un doc compatibile con quello restituito da agent_tokens
        return {"token": token, "client_id": client["client_id"], "role": "master"}
    return None


# ---- WebSocket endpoint -----------------------------------------------------

@router.websocket("/agent/ws")
async def agent_ws(ws: WebSocket) -> None:
    """Bidirectional channel for 86NocAgent v4."""
    await ws.accept()

    # Read first frame: must be agent.hello
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="hello timeout")
        return
    try:
        first = json.loads(raw)
    except json.JSONDecodeError:
        await ws.close(code=status.WS_1003_UNSUPPORTED_DATA, reason="bad hello")
        return
    if first.get("type") != "agent.hello":
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="expected agent.hello")
        return
    hello = first.get("payload") or {}
    agent_id = hello.get("agent_id") or ""
    client_id = hello.get("client_id") or ""
    token = hello.get("token") or ""
    if not (agent_id and client_id and token):
        logger.warning("agent_ws: hello missing identity agent_id=%r client_id=%r has_token=%s",
                       agent_id, client_id, bool(token))
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="missing identity")
        return

    auth = await _validate_token(token, client_id)
    if auth is None:
        logger.warning("agent_ws: token rejected client_id=%s token_prefix=%s",
                       client_id, token[:8] if token else "")
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return

    logger.info("agent_ws: hello OK agent_id=%s client_id=%s host=%s",
                agent_id, client_id, hello.get("hostname"))

    # Persist hello snapshot
    now = _now()
    role_val = (hello.get("labels") or {}).get("role") or "master"
    await db.managed_agents.update_one(
        {"agent_id": agent_id},
        {
            "$set": {
                "agent_id": agent_id,
                "client_id": client_id,
                "hostname": hello.get("hostname"),
                "os": hello.get("os"),
                "arch": hello.get("arch"),
                "agent_version": hello.get("agent_version"),
                "ips": hello.get("ips") or [],
                "capabilities": hello.get("capabilities") or [],
                "labels": hello.get("labels") or {},
                "role": role_val,
                "boot_time": hello.get("boot_time"),
                "last_hello_at": now.isoformat(),
                "connected": True,
                "connected_at": now.isoformat(),
            },
            "$setOnInsert": {"first_seen_at": now.isoformat()},
        },
        upsert=True,
    )

    conn = _Connection(agent_id, client_id, ws)
    await REGISTRY.add(conn)

    # Send welcome
    welcome = {
        "accepted_at": now.isoformat(),
        "session_id": uuid.uuid4().hex,
        "config": {},  # no hot-pushed config yet; agent uses local YAML
    }
    conn.seq += 1
    try:
        await conn.send(make_frame("server.welcome", welcome, seq=conn.seq))
    except Exception:  # noqa: BLE001
        await REGISTRY.remove(agent_id, conn)
        return

    logger.info("agent v4 connected agent_id=%s client_id=%s host=%s ver=%s",
                agent_id, client_id, hello.get("hostname"), hello.get("agent_version"))

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_frame(conn, frame)
    finally:
        await REGISTRY.remove(agent_id, conn)
        await db.managed_agents.update_one(
            {"agent_id": agent_id},
            {"$set": {"connected": False, "disconnected_at": _now().isoformat()}},
        )
        logger.info("agent v4 disconnected agent_id=%s", agent_id)


async def _handle_frame(conn: _Connection, frame: Dict[str, Any]) -> None:
    typ = frame.get("type")
    payload = frame.get("payload") or {}
    corr_id = frame.get("corr_id") or ""

    if typ == "agent.heartbeat":
        await _on_heartbeat(conn, payload)
    elif typ == "agent.event":
        await _on_event(conn, payload)
    elif typ == "agent.reply":
        fut = conn.pending.pop(corr_id, None)
        if fut and not fut.done():
            fut.set_result(payload)
    elif typ == "agent.log":
        await _on_log(conn, payload)
    else:
        logger.debug("agent v4: unknown frame type=%s", typ)


async def _on_heartbeat(conn: _Connection, hb: Dict[str, Any]) -> None:
    await db.managed_agents.update_one(
        {"agent_id": conn.agent_id},
        {
            "$set": {
                "last_heartbeat_at": _now().isoformat(),
                "uptime_ns": hb.get("uptime_ns"),
                "goroutines": hb.get("goroutines"),
                "mem_alloc_bytes": hb.get("mem_alloc_bytes"),
                "cpu_percent": hb.get("cpu_percent"),
                "errors_last_5min": hb.get("errors_last_5min"),
                "modules_alive": hb.get("modules_alive") or [],
                "modules_stuck": hb.get("modules_stuck") or [],
                "last_scan_at": hb.get("last_scan_at"),
                "last_poll_at": hb.get("last_poll_at"),
            }
        },
    )


async def _on_event(conn: _Connection, evt: Dict[str, Any]) -> None:
    kind = evt.get("kind")
    data = evt.get("data")
    if kind == "discovery_batch" and isinstance(data, list):
        await _bridge_discovery(conn, data)
    elif kind == "snmp_poll" and isinstance(data, dict):
        await _bridge_snmp_poll(conn, data)
    elif kind == "module_stuck":
        logger.warning("agent v4 module_stuck agent_id=%s data=%s", conn.agent_id, data)
    elif kind == "crash_recovered":
        logger.warning("agent v4 crash_recovered agent_id=%s data=%s", conn.agent_id, data)


async def _bridge_discovery(conn: _Connection, batch: List[Dict[str, Any]]) -> None:
    """Map agent DiscoveredEndpoint[] into the existing discovered_endpoints
    collection so all UI pages keep working unchanged."""
    if not batch:
        return
    now_iso = _now().isoformat()
    ops = []
    for ep in batch:
        ip = ep.get("ip")
        if not ip:
            continue
        doc = {
            "client_id": conn.client_id,
            "agent_id": conn.agent_id,
            "ip": ip,
            "mac": (ep.get("mac") or "").lower() or None,
            "hostname": ep.get("hostname") or None,
            "vendor": ep.get("vendor") or None,
            "source": ep.get("source") or "agent_v4",
            "source_connector_mode": "agent_v4",
            "attributes": ep.get("attributes") or {},
            "last_seen_at": now_iso,
        }
        ops.append({
            "filter": {"client_id": conn.client_id, "ip": ip},
            "update": {"$set": doc, "$setOnInsert": {"first_seen_at": now_iso}},
        })
    # Bulk upsert (sequential to avoid burst write load)
    for op in ops:
        await db.discovered_endpoints.update_one(op["filter"], op["update"], upsert=True)


async def _bridge_snmp_poll(conn: _Connection, r: Dict[str, Any]) -> None:
    """Bridge SNMPPollResult into device_poll_status."""
    target = r.get("target")
    if not target:
        return
    now_iso = _now().isoformat()
    update = {
        "client_id": conn.client_id,
        "agent_id": conn.agent_id,
        "ip": target,
        "reachable": bool(r.get("reachable")),
        "latency_ns": r.get("latency_ns"),
        "sys_name": r.get("sys_name"),
        "sys_descr": r.get("sys_descr"),
        "sys_object_id": r.get("sys_object_id"),
        "uptime_ns": r.get("uptime_ns"),
        "error": r.get("error"),
        "last_poll_at": now_iso,
        "source": "agent_v4",
    }
    await db.device_poll_status.update_one(
        {"client_id": conn.client_id, "ip": target},
        {"$set": update, "$setOnInsert": {"first_poll_at": now_iso}},
        upsert=True,
    )


async def _on_log(conn: _Connection, log: Dict[str, Any]) -> None:
    # Cap insert volume — only persist warn/error
    level = (log.get("level") or "").lower()
    if level not in ("warn", "error"):
        return
    await db.agent_logs.insert_one({
        "agent_id": conn.agent_id,
        "client_id": conn.client_id,
        "ts": _now().isoformat(),
        "level": level,
        "module": log.get("module"),
        "msg": log.get("msg"),
        "fields": log.get("fields") or {},
    })


# ---- HTTP control plane -----------------------------------------------------

class RegisterRequest(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=128)
    label: Optional[str] = Field(None, max_length=128)


class RegisterResponse(BaseModel):
    client_id: str
    token: str
    backend_url: str
    issued_at: str


@router.post("/agents/register", response_model=RegisterResponse)
async def register_agent(req: RegisterRequest, current_user: dict = Depends(get_current_user)) -> RegisterResponse:
    """Issue a fresh agent bearer token. Stored in agent_tokens collection."""
    require_admin(current_user)
    token = secrets.token_urlsafe(32)
    issued_at = _now().isoformat()
    await db.agent_tokens.insert_one({
        "token": token,
        "client_id": req.client_id,
        "label": req.label or "",
        "issued_at": issued_at,
        "revoked": False,
    })
    # Best-effort: emit our public WS URL for convenience
    import os
    backend = os.environ.get("AGENT_PUBLIC_WS_URL", "").strip()
    return RegisterResponse(
        client_id=req.client_id,
        token=token,
        backend_url=backend or "wss://argus.86bit.it/api/agent/ws",
        issued_at=issued_at,
    )


@router.get("/agents")
async def list_agents(client_id: Optional[str] = None,
                     current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_admin(current_user)
    q: Dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    docs = await db.managed_agents.find(q, {"_id": 0}).to_list(length=500)
    live_ids = {c.agent_id for c in REGISTRY.list()}
    for d in docs:
        d["live"] = d.get("agent_id") in live_ids
    return {"agents": docs, "live_count": len(live_ids)}


class CommandRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    args: Optional[Dict[str, Any]] = None
    timeout: float = Field(30.0, ge=1.0, le=120.0)


@router.post("/agents/{agent_id}/command")
async def send_command(agent_id: str, req: CommandRequest,
                      current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_admin(current_user)
    conn = REGISTRY.get(agent_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="agent not connected")
    try:
        reply = await conn.send_command(req.name, req.args, timeout=req.timeout)
    except asyncio.TimeoutError as e:
        raise HTTPException(status_code=504, detail="agent reply timeout") from e
    return {"agent_id": agent_id, "command": req.name, "reply": reply}


@router.get("/agents/{agent_id}/health")
async def agent_health(agent_id: str,
                      current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Return the persisted health snapshot of one agent (last heartbeat)."""
    require_admin(current_user)
    doc = await db.managed_agents.find_one({"agent_id": agent_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="agent unknown")
    # Compute staleness
    hb = doc.get("last_heartbeat_at")
    stale_minutes: Optional[float] = None
    if hb:
        try:
            stale_minutes = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            stale_minutes = None
    doc["live"] = REGISTRY.get(agent_id) is not None
    doc["heartbeat_age_minutes"] = stale_minutes
    return doc


# ---- Binary distribution -----------------------------------------------------
#
# The install script hits these endpoints to fetch the binaries with no
# extra infrastructure. Auth: a valid agent_token. Reusing the same token
# the agent will use after install keeps the bootstrap one-shot.

import os as _os
import pathlib as _pathlib
from fastapi.responses import FileResponse, PlainTextResponse

_AGENT_BUILD_DIR = _pathlib.Path(_os.environ.get(
    "NOCAGENT_BUILD_DIR", "/app/noc-agent/build/bin"
)).resolve()

# Directory che contiene `installer_gui.ps1.template`,
# `install.ps1.template`, `install.sh.template`, `Installa-86NocAgent.bat`.
# Su /app (preview/dev) coincide con `_AGENT_BUILD_DIR.parent`. Su
# /opt/argus/... in produzione il caller la sovrascrive via env.
_AGENT_TEMPLATE_DIR = _pathlib.Path(_os.environ.get(
    "NOCAGENT_TEMPLATE_DIR",
    str(_AGENT_BUILD_DIR.parent),
)).resolve()

# Path del file `argus.ico` standalone (servito agli installer Windows
# per gli shortcut menu Start). Default: cmd/nocui/argus.ico nel repo.
_AGENT_ICO_PATH = _pathlib.Path(_os.environ.get(
    "NOCAGENT_ICO_PATH",
    "/app/noc-agent/cmd/nocui/argus.ico",
)).resolve()

_ALLOWED_PLATFORMS = {"linux-amd64", "linux-arm64", "windows-amd64", "darwin-arm64"}
_ALLOWED_BINARIES = {
    "windows-amd64": {"nocagent.exe", "nocwatchdog.exe", "nocagent-ui.exe", "nocinstall.exe"},
    "linux-amd64": {"nocagent", "nocwatchdog"},
    "linux-arm64": {"nocagent", "nocwatchdog"},
    "darwin-arm64": {"nocagent", "nocwatchdog"},
}


async def _token_or_403(token: Optional[str]) -> str:
    """Validate an agent token presented as a query string. Returns client_id.

    Accetta indifferentemente:
      - un agent_token generato via `POST /api/agents/register`
      - la `api_key` univoca del cliente (mostrata nella pagina Clienti)

    Cosi' l'admin puo' configurare il connector usando direttamente
    l'API Key del cliente, senza dover prima generare un token agent
    separato.
    """
    if not token:
        raise HTTPException(status_code=401, detail="token required")
    # 1. Tentativo classico: token presente in agent_tokens.
    doc = await db.agent_tokens.find_one({"token": token, "revoked": {"$ne": True}}, {"_id": 0})
    if doc:
        return doc["client_id"]
    # 2. Fallback: api_key univoca del cliente. Lo schema di `clients`
    # e' nato con `id` (UUID) e solo successivamente ha aggiunto i
    # campi `client_id` (slug stabile) e `slug`. I clienti creati con
    # versioni vecchie del codice non hanno `client_id`: per non
    # rifiutare questi tenant facciamo cascade su slug -> id.
    client = await db.clients.find_one({"api_key": token},
                                       {"_id": 0, "client_id": 1, "slug": 1, "id": 1})
    if client:
        cid = client.get("client_id") or client.get("slug") or client.get("id")
        if cid:
            return str(cid)
    raise HTTPException(status_code=403, detail="invalid token")


@router.get("/agent/binary/{platform}/{name}")
async def download_binary(platform: str, name: str, token: Optional[str] = None) -> FileResponse:
    """Stream the requested agent binary. Auth via ?token=<agent_token>."""
    await _token_or_403(token)
    if platform not in _ALLOWED_PLATFORMS or name not in _ALLOWED_BINARIES.get(platform, set()):
        raise HTTPException(status_code=404, detail="unknown binary")
    path = (_AGENT_BUILD_DIR / platform / name).resolve()
    # Path traversal guard: must stay under the build dir
    try:
        path.relative_to(_AGENT_BUILD_DIR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    if not path.is_file():
        # Fallback URL: priorita' a BINARY_URLS_BASE (CDN esterno tipo
        # GitHub Releases), poi BINARY_FALLBACK_URL (mirror NOC Center).
        ext_base = _os.environ.get("BINARY_URLS_BASE", "").rstrip("/")
        if ext_base:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=f"{ext_base}/{name}", status_code=302)
        mirror_base = _os.environ.get("BINARY_FALLBACK_URL", "").rstrip("/")
        if mirror_base:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(
                url=f"{mirror_base}/api/agent/binary/{platform}/{name}?token={token}",
                status_code=302,
            )
        raise HTTPException(status_code=404, detail="binary not built")
    media = "application/vnd.microsoft.portable-executable" if name.endswith(".exe") else "application/octet-stream"
    return FileResponse(str(path), media_type=media, filename=name)


@router.get("/agent/install/manifest")
async def install_manifest(token: Optional[str] = None,
                          platform: Optional[str] = None,
                          role: Optional[str] = None,
                          runtime_backend: Optional[str] = None,
                          runtime_token: Optional[str] = None) -> Dict[str, Any]:
    """Return the install metadata: backend URL, binary URLs, sample yaml.

    `runtime_backend` (opt): WS finale del connector se diverso da
    AGENT_PUBLIC_WS_URL. `runtime_token` (opt): token da scrivere nel
    config_template se diverso dal token di bootstrap (caso d'uso:
    bootstrap su preview con api_key preview, ma WS persistente su
    argus.86bit.it con la sua api_key cliente locale, dato che le 2 DB
    sono separate). Se runtime_token non e' passato, usiamo il token
    di bootstrap.
    """
    client_id = await _token_or_403(token)
    public_ws = _os.environ.get("AGENT_PUBLIC_WS_URL", "wss://argus.86bit.it/api/agent/ws")
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    if role not in ("master", "scanner"):
        role = "master"
    effective_ws = public_ws
    if runtime_backend:
        rb = runtime_backend.rstrip("/")
        if rb.startswith("https://"):
            effective_ws = "wss://" + rb[len("https://"):] + "/api/agent/ws"
        elif rb.startswith("http://"):
            effective_ws = "ws://" + rb[len("http://"):] + "/api/agent/ws"
        elif rb.startswith(("ws://", "wss://")):
            effective_ws = rb if rb.endswith("/api/agent/ws") else rb + "/api/agent/ws"
    effective_token = runtime_token if runtime_token else token
    binaries = {}
    sha256 = {}
    if platform and platform in _ALLOWED_PLATFORMS:
        # Mirror esterno (es. GitHub Releases, S3, Cloudflare R2, OneDrive
        # direct link). Quando questa env e' settata, gli URL dei binari
        # nel manifest puntano direttamente al CDN esterno invece che a
        # /api/agent/binary/.../<file>?token=... del NOC Center. Cosi' il
        # NOC Center non deve avere i binari sul filesystem locale e
        # nemmeno fare proxy/redirect: il connector scarica direttamente
        # dal CDN. Formato: URL base senza filename, es:
        #   https://github.com/86bit/argus-noc/releases/download/v4.0.0
        # Il backend appende `/<filename>` per ogni .exe richiesto.
        ext_base = _os.environ.get("BINARY_URLS_BASE", "").rstrip("/")
        for name in _ALLOWED_BINARIES[platform]:
            if ext_base:
                binaries[name] = f"{ext_base}/{name}"
            else:
                binaries[name] = f"{public_http}/api/agent/binary/{platform}/{name}?token={token}"
            digest = _binary_sha256(platform, name)
            if digest:
                sha256[name] = digest
    return {
        "client_id": client_id,
        "role": role,
        "backend_ws": effective_ws,
        "binaries": binaries,
        "sha256": sha256,
        "config_template": _config_template(client_id, effective_token, effective_ws, role),
    }


def _binary_sha256(platform: str, name: str) -> str:
    """Return the hex sha256 digest of a built binary, or '' if missing.

    The hash is computed lazily and cached in-memory keyed by (platform,
    name, mtime) so we recompute only when the file is rebuilt.
    """
    try:
        import hashlib as _hashlib
        path = (_AGENT_BUILD_DIR / platform / name).resolve()
        path.relative_to(_AGENT_BUILD_DIR)
        if not path.is_file():
            return ""
        st = path.stat()
        cache_key = (platform, name, st.st_mtime_ns, st.st_size)
        cached = _BINARY_SHA_CACHE.get(cache_key)
        if cached:
            return cached
        h = _hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
        _BINARY_SHA_CACHE[cache_key] = digest
        return digest
    except Exception:
        return ""


_BINARY_SHA_CACHE: Dict[tuple, str] = {}


def _config_template(client_id: str, token: str, ws_url: str, role: str = "master") -> str:
    snmp_enabled = "true" if role == "master" else "false"
    return (
        f'client_id: "{client_id}"\n'
        f'token: "{token}"\n'
        f'role: "{role}"\n'
        f'backend:\n'
        f'  url: "{ws_url}"\n'
        f'heartbeat: 15s\n'
        f'discovery:\n  enabled: true\n  interval: 5m\n  arp: true\n  mdns: true\n'
        f'snmp:\n  enabled: {snmp_enabled}\n  interval: 60s\n  communities: ["public"]\n'
        f'watchdog:\n  enabled: true\n  stale_after: 90s\n'
        f'update:\n  enabled: false\n'
        f'labels:\n  role: "{role}"\n'
    )


def _fetch_template_from_mirror(filename: str) -> Optional[str]:
    """Scarica un file template (es. installer_gui.ps1.template) da un
    mirror remoto se l'env `WIZARD_TEMPLATE_FALLBACK_URL` e' settata.

    Usato come safety-net quando il backend e' deployato senza la
    cartella `noc-agent/build/` accanto (caso classico: deploy parziale
    su argus.86bit.it). Cosi' il wizard funziona comunque, scaricando
    al volo la template dal mirror noto. Cache in-process per evitare
    una richiesta HTTP per ogni download del wizard.
    """
    base = _os.environ.get("WIZARD_TEMPLATE_FALLBACK_URL", "").rstrip("/")
    if not base:
        return None
    cache = getattr(_fetch_template_from_mirror, "_cache", {})
    if filename in cache:
        return cache[filename]
    try:
        import urllib.request as _ureq
        url = f"{base}/api/__static-templates__/{filename}"
        with _ureq.urlopen(url, timeout=15) as r:
            body = r.read().decode("utf-8")
    except Exception:
        return None
    cache[filename] = body
    setattr(_fetch_template_from_mirror, "_cache", cache)
    return body


def _read_template_or_fallback(filename: str) -> str:
    """Legge un template dalla cartella locale; se mancante, ritenta sul
    mirror remoto (env). Ritorna il contenuto raw del file (placeholder
    `__BACKEND_URL__` / `__TOKEN__` non sostituiti).
    """
    p = _AGENT_TEMPLATE_DIR / filename
    if p.is_file():
        return p.read_text(encoding="utf-8")
    body = _fetch_template_from_mirror(filename)
    if body is not None:
        return body
    raise HTTPException(status_code=500, detail=f"{filename.split('.')[0]} template missing")


@router.get("/__static-templates__/{filename}", response_class=PlainTextResponse, include_in_schema=False)
async def _serve_static_template(filename: str) -> PlainTextResponse:
    """Serve template raw (no token replacement) per il fallback mirror.

    Whitelist sui nomi per evitare path traversal. Endpoint pubblico
    cosi' altri NOC Center possono usare questo come mirror se il
    proprio /opt/argus/noc-agent/build/ non ha tutti i template
    (cfr. WIZARD_TEMPLATE_FALLBACK_URL env).
    """
    allowed = {"installer_gui.ps1.template",
               "install.ps1.template",
               "install.sh.template"}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="template not found")
    p = _AGENT_TEMPLATE_DIR / filename
    if not p.is_file():
        raise HTTPException(status_code=404, detail="template not deployed")
    return PlainTextResponse(p.read_text(encoding="utf-8"),
                             media_type="text/plain; charset=utf-8")



@router.get("/agent/install/wizard-bundle.zip")
async def wizard_bundle(token: Optional[str] = None) -> FileResponse:
    """Download a ZIP containing installer_gui.ps1 (PowerShell GUI wizard).

    The user double-clicks the .vbs which silently launches the GUI wizard
    with the token already baked in. No console window, no PowerShell skill
    required from the on-site technician.
    """
    await _token_or_403(token)
    bundle = _build_wizard_bundle(token)
    return FileResponse(bundle, media_type="application/zip", filename="86NocAgent-Installer.zip")


@router.get("/agent/install/argus.ico")
async def install_argus_ico() -> FileResponse:
    """Serve the Argus tray icon (multi-size .ico). Public endpoint — the
    installer fetches this so shortcuts can point to a stable file path
    instead of an embedded EXE icon (which Windows aggressively caches by
    path and may not refresh on update)."""
    path = _AGENT_ICO_PATH
    if not path.is_file():
        mirror_base = _os.environ.get("BINARY_FALLBACK_URL", "").rstrip("/")
        if mirror_base:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=f"{mirror_base}/api/agent/install/argus.ico", status_code=302)
        raise HTTPException(status_code=404, detail="icon missing")
    return FileResponse(str(path), media_type="image/vnd.microsoft.icon", filename="argus.ico")


@router.get("/agent/install/exe")
async def install_exe(token: Optional[str] = None) -> FileResponse:
    """Stream nocinstall.exe alone. The technician must run with
    `--token <T> --backend <URL>` or place a nocinstall.cfg next to it.
    """
    await _token_or_403(token)
    path = (_AGENT_BUILD_DIR / "windows-amd64" / "nocinstall.exe").resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="installer not built")
    return FileResponse(str(path),
                        media_type="application/vnd.microsoft.portable-executable",
                        filename="nocinstall.exe")


@router.get("/admin/sync-argus.sh", response_class=PlainTextResponse, include_in_schema=False)
async def serve_sync_script() -> PlainTextResponse:
    """Serve sync-argus.sh via API path (bypassa SPA fallback / proxy).

    Risolve il caso in cui scaricare /downloads/sync-argus.sh ritorna
    l'index.html del frontend (cache di rete intermedi, Cloudflare,
    proxy aziendali). Path sotto /api e' garantito andare al backend.
    """
    candidates = [
        _pathlib.Path("/app/frontend/public/downloads/sync-argus.sh"),
        _pathlib.Path("/opt/argus/frontend/public/downloads/sync-argus.sh"),
    ]
    for p in candidates:
        if p.is_file():
            return PlainTextResponse(p.read_text(),
                                     media_type="text/x-shellscript")
    raise HTTPException(status_code=404, detail="sync script not found")


@router.get("/admin/argus-deploy-latest.tar.gz", include_in_schema=False)
async def serve_deploy_bundle() -> FileResponse:
    """Serve il bundle deploy via API path. Stessa ragione di sync-argus.sh:
    il path /api/* va dritto al backend, no SPA fallback / proxy.
    """
    candidates = [
        _pathlib.Path("/app/frontend/public/downloads/argus-deploy-latest.tar.gz"),
        _pathlib.Path("/opt/argus/frontend/public/downloads/argus-deploy-latest.tar.gz"),
    ]
    for p in candidates:
        if p.is_file():
            return FileResponse(str(p),
                                media_type="application/gzip",
                                filename="argus-deploy-latest.tar.gz")
    raise HTTPException(status_code=404, detail="deploy bundle not found")


@router.get("/admin/argus-binaries.zip", include_in_schema=False)
async def serve_binaries_zip() -> FileResponse:
    """Serve l'archivio con tutti i binari Windows + argus.ico + SHA256SUMS.

    Comodo per uploadare in una sola volta una GitHub Release: l'utente
    fa `curl -o pkg.zip <url>` + `unzip pkg.zip` + drag&drop su release.
    """
    candidates = [
        _pathlib.Path("/app/frontend/public/downloads/argus-binaries-v4.0.0.zip"),
    ]
    for p in candidates:
        if p.is_file():
            return FileResponse(str(p),
                                media_type="application/zip",
                                filename="argus-binaries-v4.0.0.zip")
    raise HTTPException(status_code=404, detail="binaries zip not found")


@router.get("/agent/install/exe-bundle.zip")
async def exe_bundle(token: Optional[str] = None) -> FileResponse:
    """ZIP with nocinstall.exe + pre-populated nocinstall.cfg + LEGGIMI.

    This is the recommended download for the on-site technician on Windows
    boxes with enterprise AV: a single .exe + one config file, no scripts at
    all. The technician double-clicks nocinstall.exe and just clicks through.
    """
    await _token_or_403(token)
    bundle = _build_exe_bundle(token)
    return FileResponse(bundle, media_type="application/zip",
                        filename="Argus-Connector-Setup.zip")


@router.get("/agent/install/setup.exe")
async def setup_exe(token: Optional[str] = None) -> FileResponse:
    """Single-file Windows installer: Argus-Setup.exe.

    7-Zip Setup Deluxe SFX che embedda nocagent + nocwatchdog + nocagent-ui +
    argus.ico + il wizard PS1 (tutto firmato col token del cliente). L'utente
    fa SOLO doppio-click sul .exe: il wizard 7-step parte (Welcome ->
    master/scanner -> URL+token (precompilati ma editabili) -> dispositivi
    SNMP -> riepilogo -> install -> done).

    Identico a un installer Inno Setup / NSIS: zero estrazioni, zero PS in
    chiaro, zero dipendenze di rete per il bootstrap (i binari sono dentro).
    """
    await _token_or_403(token)
    setup_path = _build_setup_exe(token)
    return FileResponse(setup_path, media_type="application/vnd.microsoft.portable-executable",
                        filename="Argus-Setup.exe")


@router.get("/agent/install/{platform}.{ext}", response_class=PlainTextResponse)
async def install_script(platform: str, ext: str, token: Optional[str] = None) -> PlainTextResponse:
    """Serve the install script for a platform inlined with the token.

    Usage:
      Windows CLI : iwr -UseBasicParsing https://argus.86bit.it/api/agent/install/windows.ps1?token=XXX | iex
      Windows GUI : .../api/agent/install/wizard.ps1?token=XXX  (download + esegui)
      Linux       : curl -fsSL https://argus.86bit.it/api/agent/install/linux.sh?token=XXX | sudo bash
    """
    await _token_or_403(token)
    if platform == "windows" and ext == "ps1":
        return PlainTextResponse(_render_windows_ps1(token), media_type="text/plain; charset=utf-8")
    if platform == "linux" and ext == "sh":
        return PlainTextResponse(_render_linux_sh(token), media_type="text/plain; charset=utf-8")
    if platform == "wizard" and ext == "ps1":
        return PlainTextResponse(_render_wizard_ps1(token), media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="unknown installer")


def _render_windows_ps1(token: str) -> str:
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    body = _read_template_or_fallback("install.ps1.template")
    return (body
            .replace("__BACKEND_URL__", public_http)
            .replace("__TOKEN__", token))


def _render_linux_sh(token: str) -> str:
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    body = _read_template_or_fallback("install.sh.template")
    return (body
            .replace("__BACKEND_URL__", public_http)
            .replace("__TOKEN__", token))


def _render_wizard_ps1(token: str) -> str:
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    body = _read_template_or_fallback("installer_gui.ps1.template")
    return (body
            .replace("__BACKEND_URL__", public_http)
            .replace("__TOKEN__", token))


def _build_wizard_bundle(token: str) -> str:
    """Materialise the wizard ZIP on disk and return its path.

    Note: starting from sprint 1.6 we **do not ship a .vbs launcher** anymore
    because enterprise AV (CrowdStrike, SentinelOne, ESET, Sophos InterceptX)
    flag .vbs by default and email gateways strip it. The technician opens
    the .ps1 directly via right-click -> Run with PowerShell as Administrator.
    For a fully script-free experience use /api/agent/install/exe (the native
    Go installer with embedded GUI).
    """
    import io as _io
    import zipfile as _zipfile
    import tempfile as _tempfile

    out_dir = _pathlib.Path(_tempfile.gettempdir()) / "86nocagent_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in token if c.isalnum() or c in "-_")[:32]
    out = out_dir / f"86NocAgent-Installer-{safe}.zip"
    if out.is_file():
        out.unlink()  # rebuild — content/template may have changed

    ps1_body = _render_wizard_ps1(token)
    bat_path = _AGENT_TEMPLATE_DIR / "Installa-86NocAgent.bat"
    if not bat_path.is_file():
        raise HTTPException(status_code=500, detail="bat launcher missing")

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as z:
        z.writestr("Installa-86NocAgent.bat", bat_path.read_text(encoding="utf-8"))
        z.writestr("installer_gui.ps1", ps1_body)
        z.writestr("LEGGIMI.txt",
                   "86NocAgent v4.0 - Wizard installazione\r\n"
                   "============================================\r\n\r\n"
                   "PROCEDURA SEMPLICE (consigliata):\r\n"
                   "  1. Estrai questo zip in una cartella (es. Desktop)\r\n"
                   "  2. Tasto destro su 'Installa-86NocAgent.bat'\r\n"
                   "  3. Seleziona 'Esegui come amministratore'\r\n"
                   "  4. Si apre il wizard grafico a 5 step\r\n"
                   "  5. Segui i passaggi (URL+Token sono gia' precompilati)\r\n\r\n"
                   "ALTERNATIVA (senza GUI, console-only):\r\n"
                   "  Apri PowerShell come amministratore e incolla:\r\n"
                   "    iex(iwr -UseBasicParsing 'URL_INSTALLER_PS1')\r\n\r\n"
                   "ALTERNATIVA (single-binary, preferita su AV enterprise):\r\n"
                   "  Scarica 86NocAgent-Installer-EXE.zip da:\r\n"
                   "  /api/agent/install/exe-bundle.zip?token=...\r\n"
                   "  Doppio-click su nocinstall.exe, niente script.\r\n\r\n"
                   "Token e URL sono gia' precompilati in tutti gli installer.\r\n")
    out.write_bytes(buf.getvalue())
    return str(out)


def _build_exe_bundle(token: str) -> str:
    """Build a ZIP with nocinstall.exe + sidecar config + readme."""
    import io as _io
    import zipfile as _zipfile
    import tempfile as _tempfile

    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    out_dir = _pathlib.Path(_tempfile.gettempdir()) / "86nocagent_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in token if c.isalnum() or c in "-_")[:32]
    out = out_dir / f"Argus-Connector-Setup-{safe}.zip"
    if out.is_file():
        out.unlink()

    exe_path = _AGENT_BUILD_DIR / "windows-amd64" / "nocinstall.exe"
    if not exe_path.is_file():
        raise HTTPException(status_code=500, detail="nocinstall.exe not built")

    sidecar = (
        f"# Argus Connector — config installer (auto-generato)\n"
        f"# Non toccare. Lascia questo file accanto a nocinstall.exe.\n"
        f"TOKEN={token}\n"
        f"BACKEND={public_http}\n"
    )
    leggimi = (
        "ARGUS Connector — Installer\r\n"
        "==========================================\r\n\r\n"
        "INSTALLAZIONE IN 3 STEP:\r\n\r\n"
        "  1. Estrai questo ZIP in una cartella (es. Desktop)\r\n"
        "  2. Doppio-click su 'nocinstall.exe'\r\n"
        "  3. Accetta il prompt UAC -> attendi 'Installazione completata'\r\n\r\n"
        "Fatto. Niente PowerShell, niente wizard, niente da configurare.\r\n"
        "URL NOC Center e API Key sono gia' precompilati nel file .cfg.\r\n\r\n"
        "------------------------------------------\r\n"
        "Disinstallazione (PowerShell admin):\r\n"
        "  Stop-Service 86NocAgent,86NocWatchdog -Force\r\n"
        "  sc.exe delete 86NocAgent ; sc.exe delete 86NocWatchdog\r\n"
        "  Remove-Item -Recurse -Force \"$env:ProgramFiles\\86NocAgent\",\"$env:ProgramData\\86NocAgent\"\r\n\r\n"
        "Avanzato (CLI silent):\r\n"
        "  nocinstall.exe --token <T> --backend <URL> --silent\r\n"
    )

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as z:
        z.write(str(exe_path), arcname="nocinstall.exe")
        z.writestr("nocinstall.cfg", sidecar)
        z.writestr("LEGGIMI.txt", leggimi)
    out.write_bytes(buf.getvalue())
    return str(out)


def _build_setup_exe(token: str) -> str:
    """Build a single self-extracting Argus-Setup.exe (Windows x64).

    Layout: [7-Zip Setup Deluxe SFX] + [config.txt] + [payload.7z]

    Il payload contiene tutti i file Windows necessari (nocagent.exe,
    nocwatchdog.exe, nocagent-ui.exe, argus.ico, installer_gui.ps1,
    Lancia.bat). Quando l'utente fa doppio-click, lo stub SFX:
      1. Chiede UAC se serve (configurato in config.txt)
      2. Estrae il payload in %TEMP%\\Argus-Setup-XXXX
      3. Esegue `Lancia.bat` che parte il wizard PowerShell
      4. Il wizard mostra master/scanner + URL+token + dispositivi SNMP
      5. Al termine il SFX cancella la temp dir

    Cosi' l'utente vede UN SOLO .exe come ogni installer Inno Setup,
    ma sotto il cofano abbiamo lo stesso wizard e nessuna dipendenza
    di rete (i binari sono gia' embedded).
    """
    import io as _io
    import zipfile as _zipfile  # noqa: F401
    import tempfile as _tempfile
    import subprocess as _sp
    import shutil as _shutil

    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    out_dir = _pathlib.Path(_tempfile.gettempdir()) / "86nocagent_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in token if c.isalnum() or c in "-_")[:32]
    out = out_dir / f"Argus-Setup-{safe}.exe"
    if out.is_file() and out.stat().st_mtime > (_pathlib.Path(__file__).stat().st_mtime):
        return str(out)
    out.unlink(missing_ok=True)

    # 1) Verifica presenza tutti i sorgenti Windows
    bin_dir = _AGENT_BUILD_DIR / "windows-amd64"
    sfx_path = _AGENT_TEMPLATE_DIR.parent / "build" / "sfx" / "7zsd_LZMA_x64.sfx"
    # fallback path (in repo originale)
    if not sfx_path.is_file():
        sfx_path = _pathlib.Path("/app/noc-agent/build/sfx/7zsd_LZMA_x64.sfx")
    template = _AGENT_TEMPLATE_DIR / "installer_gui.ps1.template"
    ico_path = _AGENT_ICO_PATH

    required = {
        "nocagent.exe":      bin_dir / "nocagent.exe",
        "nocwatchdog.exe":   bin_dir / "nocwatchdog.exe",
        "nocagent-ui.exe":   bin_dir / "nocagent-ui.exe",
        "argus.ico":         ico_path,
        "installer_gui.ps1": template,
        "sfx_stub":          sfx_path,
    }
    missing = [k for k, p in required.items() if not p.is_file()]
    if missing:
        raise HTTPException(status_code=500, detail=f"setup.exe assets missing: {missing}")

    # 2) Stage dir con tutti i file da archiviare nel payload .7z
    work = _pathlib.Path(_tempfile.mkdtemp(prefix="argus-setup-"))
    try:
        for name in ("nocagent.exe", "nocwatchdog.exe", "nocagent-ui.exe"):
            _shutil.copy2(required[name], work / name)
        _shutil.copy2(required["argus.ico"], work / "argus.ico")

        # Wizard PS1 con placeholder sostituiti
        ps1_body = template.read_text(encoding="utf-8")
        ps1_body = (ps1_body
                    .replace("__BACKEND_URL__", public_http)
                    .replace("__TOKEN__", token))
        (work / "installer_gui.ps1").write_text(ps1_body, encoding="utf-8")

        # Launcher: .bat che lancia il wizard PS1 (PSScriptRoot punta
        # automaticamente alla temp dir SFX). Necessario perche' il SFX
        # esegue un comando, non uno script PS1 direttamente.
        launcher = (
            "@echo off\r\n"
            "REM Argus Setup launcher — eseguito da 7zsd_LZMA_x64.sfx\r\n"
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -STA "
            "-File \"%~dp0installer_gui.ps1\"\r\n"
            "exit /b %errorlevel%\r\n"
        )
        (work / "Lancia.bat").write_text(launcher)

        # 3) Crea payload.7z con LZMA compression
        payload = work / "payload.7z"
        cmd = [
            "/usr/bin/7z", "a", "-t7z", "-mx=7", "-mmt=on",
            str(payload),
            str(work / "nocagent.exe"),
            str(work / "nocwatchdog.exe"),
            str(work / "nocagent-ui.exe"),
            str(work / "argus.ico"),
            str(work / "installer_gui.ps1"),
            str(work / "Lancia.bat"),
        ]
        r = _sp.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail=f"7z build failed: {r.stderr[:300]}")

        # 4) Config SFX: comando da eseguire dopo l'estrazione + UAC
        # Sintassi: https://github.com/chrislake/7zsfxmm
        sfx_config = (
            ";!@Install@!UTF-8!\r\n"
            f'Title="Argus Connector — Setup"\r\n'
            f'BeginPrompt="Installa il connector ARGUS NOC su questo PC?"\r\n'
            'Progress="yes"\r\n'
            'GUIMode="0"\r\n'                    # 0 = mostra prompt + progress
            'InstallPath="%%T\\\\Argus-Setup"\r\n'  # estrai in %TEMP%\Argus-Setup
            'OverwriteMode="2"\r\n'              # overwrite senza chiedere
            'RunProgram="hidcon:\\"%%T\\\\Argus-Setup\\\\Lancia.bat\\""\r\n'
            ';!@InstallEnd@!\r\n'
        )
        cfg_file = work / "config.txt"
        # 7zSD vuole UTF-8 con BOM
        cfg_file.write_bytes("\ufeff".encode("utf-8") + sfx_config.encode("utf-8"))

        # 5) Concatenazione finale: stub + config + payload
        with out.open("wb") as f:
            f.write(required["sfx_stub"].read_bytes())
            f.write(cfg_file.read_bytes())
            f.write(payload.read_bytes())
        return str(out)
    finally:
        _shutil.rmtree(work, ignore_errors=True)



# ============================================================================
# SELF endpoints — auth via agent token (used by Connector Console PS1)
# ============================================================================

async def _connector_by_token(token: Optional[str]) -> _Connection:
    """Validate an agent bearer token and return the live WS connection
    of *some* agent of that tenant currently online (preferring master).

    Raises HTTPException 401 on invalid token, 404 if no agent online.

    Accetta sia `agent_tokens.token` (token v4 emesso da /agents/register)
    sia `clients.api_key` legacy: il resolver e' lo stesso di
    `_token_or_403` per evitare disallineamenti tra endpoints di auth.
    """
    # _token_or_403 raises 401 on missing, 403 on invalid: lo riusiamo
    # per garantire identica semantica di auth tra install/manifest e
    # self/snmp/test. Preserviamo lo status 401 per coerenza con il
    # contratto preesistente di _connector_by_token (l'agent UI mostra
    # "401: invalid token" all'utente).
    try:
        client_id = await _token_or_403(token)
    except HTTPException as e:
        raise HTTPException(status_code=401, detail=e.detail) from e
    candidates: List[_Connection] = [
        c for c in REGISTRY.list() if c.client_id == client_id
    ]
    if not candidates:
        raise HTTPException(status_code=404, detail="no agent connected for this client")
    # Prefer agent with master role (looked up from DB)
    for c in candidates:
        ag = await db.managed_agents.find_one({"agent_id": c.agent_id}, {"_id": 0, "role": 1})
        if ag and ag.get("role") == "master":
            return c
    return candidates[0]


class SnmpTestRequest(BaseModel):
    ip: str
    community: Optional[str] = "public"
    port: Optional[int] = 161
    version: Optional[str] = "v2c"


@router.post("/agent/self/snmp/test")
async def self_snmp_test(req: SnmpTestRequest, token: Optional[str] = None) -> Dict[str, Any]:
    """Trigger a real SNMP GET (sysDescr, sysName, sysUpTime, sysObjectID)
    on the requested device, executed by the live agent of this tenant.

    Auth: ?token=<agent_token>. Returns the SNMPPollResult from the agent.
    """
    conn = await _connector_by_token(token)
    args = {"ip": req.ip, "community": req.community or "public"}
    try:
        reply = await conn.send_command("force_snmp_poll", args, timeout=15.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="agent reply timeout")
    return {
        "agent_id": conn.agent_id,
        "client_id": conn.client_id,
        "ip": req.ip,
        "reply": reply,
    }


@router.get("/agent/self/health")
async def self_health(token: Optional[str] = None) -> Dict[str, Any]:
    """Health-check del canale connector→backend (la 'VPN' WebSocket).

    Auth: ?token=<agent_token | client.api_key>. Verifica che l'agent sia
    connesso e misura il round-trip-time inviando un comando 'ping' via WS.
    """
    # Stesso resolver multi-fonte degli altri endpoints self/* (token v4
    # da agent_tokens oppure api_key del cliente). Mappiamo 403 -> 401 per
    # mantenere la semantica originale di questa route.
    try:
        client_id = await _token_or_403(token)
    except HTTPException as e:
        raise HTTPException(status_code=401, detail=e.detail) from e
    candidates = [c for c in REGISTRY.list() if c.client_id == client_id]
    if not candidates:
        return {
            "connected": False,
            "client_id": client_id,
            "agents_online": 0,
            "rtt_ms": None,
            "detail": "no agent connected for this client",
        }
    # Use first connection for RTT ping
    conn = candidates[0]
    rtt_ms: Optional[float] = None
    error: Optional[str] = None
    t0 = _now().timestamp()
    try:
        await conn.send_command("ping", None, timeout=5.0)
        rtt_ms = (_now().timestamp() - t0) * 1000.0
    except asyncio.TimeoutError:
        error = "ping timeout"
    except Exception as e:  # noqa: BLE001
        error = str(e)
    ag_doc = await db.managed_agents.find_one({"agent_id": conn.agent_id}, {"_id": 0})
    return {
        "connected": True,
        "client_id": client_id,
        "agent_id": conn.agent_id,
        "agents_online": len(candidates),
        "rtt_ms": rtt_ms,
        "error": error,
        "hostname": (ag_doc or {}).get("hostname"),
        "agent_version": (ag_doc or {}).get("agent_version"),
        "last_heartbeat_at": (ag_doc or {}).get("last_heartbeat_at"),
        "connected_at": conn.connected_at.isoformat(),
    }


# ============================================================================
# OTA self-update — Ed25519 signed manifest
# ============================================================================
#
# Flow lato agent (cmd/agent → internal/update/updater.go):
#   1. Periodic GET /api/agent/update/manifest?platform=<p>&token=<t>
#   2. JSON response: { version, os, arch, url, sha256, signature }
#   3. Agent verifica sig con la public key in agent.yaml (update.public_key)
#   4. Download binary, ricalcola sha256, atomic-rename, exit(0) → watchdog respawn
#
# Keypair: generata lazily al primo accesso e persistita su Mongo
# (collection `agent_signing_key`, singleton doc id="default"). La chiave
# privata non lascia mai il backend; la public key è esposta da
# `/api/agent/update/public-key` (no auth, hex string).
#
# Per attivare l'OTA su un cliente esistente, modificare il suo agent.yaml:
#   update:
#     enabled: true
#     manifest_url: "https://argus.86bit.it/api/agent/update/manifest?platform=windows-amd64&token=<TOKEN>"
#     check_interval: 1h
#     public_key: "<hex pubkey from /api/agent/update/public-key>"

import hashlib as _hashlib_ota
from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519
from cryptography.hazmat.primitives import serialization as _ser


_signing_keys_cache: Dict[str, Any] = {}


async def _get_signing_keys() -> Dict[str, bytes]:
    """Return {priv: bytes32, pub: bytes32}. Lazy create + persist on first call."""
    if "priv" in _signing_keys_cache:
        return _signing_keys_cache
    doc = await db.agent_signing_key.find_one({"_id": "default"})
    if not doc:
        sk = _ed25519.Ed25519PrivateKey.generate()
        priv_raw = sk.private_bytes(
            encoding=_ser.Encoding.Raw,
            format=_ser.PrivateFormat.Raw,
            encryption_algorithm=_ser.NoEncryption(),
        )
        pub_raw = sk.public_key().public_bytes(
            encoding=_ser.Encoding.Raw, format=_ser.PublicFormat.Raw
        )
        await db.agent_signing_key.insert_one({
            "_id": "default",
            "priv_hex": priv_raw.hex(),
            "pub_hex": pub_raw.hex(),
            "created_at": _now().isoformat(),
        })
    else:
        priv_raw = bytes.fromhex(doc["priv_hex"])
        pub_raw = bytes.fromhex(doc["pub_hex"])
    _signing_keys_cache["priv"] = priv_raw
    _signing_keys_cache["pub"] = pub_raw
    return _signing_keys_cache


@router.get("/agent/update/public-key", response_class=PlainTextResponse)
async def update_public_key() -> PlainTextResponse:
    """Return the Ed25519 public key (hex) used to sign OTA manifests.

    Public endpoint (no auth): the public key is meant to be read once and
    pinned into each agent's agent.yaml under `update.public_key`.
    """
    keys = await _get_signing_keys()
    return PlainTextResponse(keys["pub"].hex(), media_type="text/plain; charset=utf-8")


@router.get("/agent/update/manifest")
async def update_manifest(token: Optional[str] = None,
                          platform: Optional[str] = None) -> Dict[str, Any]:
    """Return a signed update manifest for the requested platform.

    Schema (matches /app/noc-agent/internal/update/updater.go::Manifest):
      { version, os, arch, url, sha256, signature }

    `version` is the build ID injected in the binary (`-X main.Version=...`).
    The agent compares it to its own `Version` and skips the update when
    equal. The signature is ed25519(privkey, sha256_raw_bytes).
    """
    await _token_or_403(token)
    if not platform or platform not in _ALLOWED_PLATFORMS:
        raise HTTPException(status_code=400, detail="platform required")
    bin_name = "nocagent.exe" if platform.startswith("windows") else "nocagent"
    path = (_AGENT_BUILD_DIR / platform / bin_name).resolve()
    try:
        path.relative_to(_AGENT_BUILD_DIR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    if not path.is_file():
        raise HTTPException(status_code=404, detail="binary not built")
    digest = _hashlib_ota.sha256(path.read_bytes()).digest()
    keys = await _get_signing_keys()
    sk = _ed25519.Ed25519PrivateKey.from_private_bytes(keys["priv"])
    sig = sk.sign(digest)
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    os_part, arch_part = platform.split("-", 1)
    # Inject the build version by reading it from the binary string table
    # would require parsing PE/ELF; cheaper: keep a sidecar version.txt next
    # to the binary on every build. Fallback to mtime-based pseudo-version.
    version_path = path.with_suffix(".version")
    if version_path.is_file():
        version = version_path.read_text().strip()
    else:
        st = path.stat()
        version = f"build-{int(st.st_mtime)}"
    return {
        "version": version,
        "os": os_part,
        "arch": arch_part,
        "url": f"{public_http}/api/agent/binary/{platform}/{bin_name}?token={token}",
        "sha256": digest.hex(),
        "signature": sig.hex(),
    }
