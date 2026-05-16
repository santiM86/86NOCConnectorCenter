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

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
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
    # NB: alcuni documenti legacy hanno solo `id`, altri hanno `client_id`.
    client = await db.clients.find_one({"api_key": token}, {"_id": 0, "client_id": 1, "id": 1})
    if client:
        resolved_cid = client.get("client_id") or client.get("id")
        if resolved_cid == claimed_client_id:
            return {"token": token, "client_id": resolved_cid, "role": "master"}
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

    # Send welcome (includes SNMP targets pulled from managed_devices for
    # this tenant so the agent can self-poll without needing a separate
    # legacy Connector Master).
    welcome = {
        "accepted_at": now.isoformat(),
        "session_id": uuid.uuid4().hex,
        "config": await _build_poller_config(client_id),
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
    # GUARD: any exception here would propagate up to _handle_frame and
    # drop the agent's WS connection (crash-loop). All bridges write to
    # Mongo so transient errors (DuplicateKey, network blip, schema
    # validation) are normal — log them, keep the session alive.
    try:
        if kind == "discovery_batch" and isinstance(data, list):
            await _bridge_discovery(conn, data)
        elif kind == "snmp_poll" and isinstance(data, dict):
            await _bridge_snmp_poll(conn, data)
        elif kind == "ping_poll" and isinstance(data, dict):
            await _bridge_ping_poll(conn, data)
        elif kind in ("lan_scan_result", "lan_scan_progress", "lan_scan_done") and isinstance(data, dict):
            # Lazy import per evitare cicli (lan_scanner.py importa
            # questo modulo per REGISTRY).
            from routes.lan_scanner import bridge_lan_scan_event
            await bridge_lan_scan_event(kind, data)
        elif kind == "module_stuck":
            logger.warning("agent v4 module_stuck agent_id=%s data=%s", conn.agent_id, data)
        elif kind == "crash_recovered":
            logger.warning("agent v4 crash_recovered agent_id=%s data=%s", conn.agent_id, data)
    except Exception as e:
        logger.warning("_on_event(%s) bridge crashed agent=%s err=%s", kind, conn.agent_id, e)


async def _bridge_discovery(conn: _Connection, batch: List[Dict[str, Any]]) -> None:
    """Map agent DiscoveredEndpoint[] into the existing discovered_endpoints
    collection so all UI pages keep working unchanged.

    OUI vendor lookup (offline) is applied here so the Auto-Discovery UI shows
    the manufacturer label next to each MAC, matching the behaviour of the
    legacy /lan-scan connector flow.
    """
    if not batch:
        return
    # Lazy import to avoid circular dependencies at module load time.
    try:
        from routes.oui_lookup import lookup_oui
    except Exception:  # pragma: no cover - degraded mode
        lookup_oui = lambda m: ""  # noqa: E731
    now_iso = _now().isoformat()
    ops = []
    for ep in batch:
        ip = ep.get("ip")
        if not ip:
            continue
        mac = (ep.get("mac") or "").lower() or None
        vendor_hint = ep.get("vendor") or None
        oui_vendor = lookup_oui(mac) if mac else ""
        doc = {
            "client_id": conn.client_id,
            "agent_id": conn.agent_id,
            "ip": ip,
            "mac": mac,
            "hostname": ep.get("hostname") or None,
            "vendor": vendor_hint or (oui_vendor or None),
            "source": ep.get("source") or "agent_v4",
            "source_connector_mode": "agent_v4",
            "attributes": ep.get("attributes") or {},
            "last_seen_at": now_iso,
        }
        # Populate the legacy `*_scanner` fields read by the Auto-Discovery
        # UI so agent_v4 endpoints display vendor/hostname like scanner ones.
        if oui_vendor:
            doc["vendor_scanner"] = oui_vendor
        if ep.get("hostname"):
            doc["hostname_scanner"] = ep["hostname"]
        ops.append({
            "filter": {"client_id": conn.client_id, "ip": ip},
            "update": {"$set": doc, "$setOnInsert": {"first_seen_at": now_iso}},
        })
    # Bulk upsert (sequential to avoid burst write load)
    for op in ops:
        await db.discovered_endpoints.update_one(op["filter"], op["update"], upsert=True)


async def _bridge_ping_poll(conn: _Connection, r: Dict[str, Any]) -> None:
    """Bridge a PingPollResult into managed_devices.status.

    Uses a 3-consecutive-failure threshold to flip a device to "offline"
    so a single dropped ICMP probe (Wi-Fi blip, switch CPU spike, host
    firewall hiccup) does not flap the UI.

    Counters are kept on `managed_devices.consecutive_ping_failures` so
    they survive backend restarts without needing a separate store.

    All writes are wrapped in try/except so a single Mongo error (e.g.
    a unique-index conflict or schema validation) cannot crash the WS
    bridge — the agent stays connected and the next ping_poll retries.
    """
    target = r.get("target")
    if not target:
        return
    reachable = bool(r.get("reachable"))
    now_iso = _now().isoformat()
    latency_ns = r.get("latency_ns") or 0
    try:
        latency_ms = float(latency_ns) / 1e6 if latency_ns else None
    except Exception:
        latency_ms = None
    loss_pct = r.get("loss_pct")

    # Update raw poll-status doc — best-effort, errors logged but never
    # propagated (a stale row here doesn't justify dropping the WS).
    # NOTE: la collection device_poll_status ha un indice unique su
    # (client_id, device_ip). Il campo si chiama "device_ip", NON "ip".
    try:
        await db.device_poll_status.update_one(
            {"client_id": conn.client_id, "agent_id": conn.agent_id, "device_ip": target},
            {
                "$set": {
                    "ping_reachable": reachable,
                    "ping_latency_ms": latency_ms,
                    "ping_loss_pct": loss_pct,
                    "ping_error": r.get("error"),
                    "last_ping_at": now_iso,
                    # FRONTEND COMPAT: la pagina dispositivi (ClientOverviewPage)
                    # e overview.py leggono `reachable` + `last_poll` (legacy,
                    # senza `_at`) per popolare la colonna "Ultimo Poll" e per
                    # derivare lo status del device. Il Connector v4 in origine
                    # scriveva solo i campi ping_*/_at "nuovi" → la colonna
                    # restava vuota anche con un dispositivo che rispondeva.
                    # Scriviamo entrambi i nomi: cosi' la UI vecchia funziona
                    # e quella nuova continua a leggere i campi `_at`/`ping_*`.
                    "reachable": reachable,
                    "last_poll": now_iso,
                    "source": "agent_v4",
                },
                "$setOnInsert": {
                    "client_id": conn.client_id,
                    "agent_id": conn.agent_id,
                    "device_ip": target,
                    "first_poll_at": now_iso,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning("ping_poll: device_poll_status upsert failed ip=%s err=%s", target, e)

    # Reconcile managed_devices.status with the 3-failure threshold.
    try:
        cursor = db.managed_devices.find(
            {"client_id": conn.client_id, "ip": target},
            {"_id": 0, "id": 1, "status": 1, "consecutive_ping_failures": 1},
        )
        failure_threshold = 3
        async for dev in cursor:
            prev_failures = int(dev.get("consecutive_ping_failures") or 0)
            prev_status = dev.get("status")
            update: Dict[str, Any] = {
                "last_poll_at": now_iso,
                "last_poll_source": "agent_v4",
                "last_ping_at": now_iso,
                "ping_latency_ms": latency_ms,
            }
            if reachable:
                update["status"] = "online"
                update["consecutive_ping_failures"] = 0
                update["last_seen_at"] = now_iso
                update["degraded"] = False
            else:
                new_failures = prev_failures + 1
                update["consecutive_ping_failures"] = new_failures
                if new_failures >= failure_threshold:
                    update["status"] = "offline"
                else:
                    update["status"] = prev_status or "online"
                    update["degraded"] = True
            # Use the unique `id` if present, otherwise match by (client_id, ip)
            # so devices indexed only by _id (no `id` field) are still handled.
            dev_id = dev.get("id")
            flt: Dict[str, Any] = {"client_id": conn.client_id, "ip": target}
            if dev_id:
                flt["id"] = dev_id
            try:
                await db.managed_devices.update_one(flt, {"$set": update})
            except Exception as e:
                logger.warning("ping_poll: managed_devices update failed ip=%s err=%s", target, e)
    except Exception as e:
        logger.warning("ping_poll: managed_devices reconcile failed ip=%s err=%s", target, e)


async def _bridge_snmp_poll(conn: _Connection, r: Dict[str, Any]) -> None:
    """Bridge SNMPPollResult into device_poll_status AND into managed_devices.

    Updates `managed_devices.status` ("online"/"offline") + `last_poll_at`
    so that the UI Dispositivi page shows live status driven by the
    self-polling agent v4 (no legacy Connector Master required).
    """
    target = r.get("target")
    if not target:
        return
    now_iso = _now().isoformat()
    reachable = bool(r.get("reachable"))
    # NOTE: collection device_poll_status indice unique su
    # (client_id, device_ip). Il campo si chiama "device_ip" NON "ip".
    snmp_set = {
        "agent_id": conn.agent_id,
        "reachable": reachable,
        "latency_ns": r.get("latency_ns"),
        "sys_name": r.get("sys_name"),
        "sys_descr": r.get("sys_descr"),
        "sys_object_id": r.get("sys_object_id"),
        "uptime_ns": r.get("uptime_ns"),
        "error": r.get("error"),
        "last_poll_at": now_iso,
        # FRONTEND COMPAT: vedi nota in _bridge_ping_poll. Scriviamo anche
        # last_poll (legacy, senza `_at`) cosi' overview.py / ClientOverviewPage
        # popolano la colonna "Ultimo Poll" anche per i target SNMP del Go Agent
        # v4 (prima restava vuota perche' il campo letto era last_poll vs scritto
        # last_poll_at).
        "last_poll": now_iso,
        "source": "agent_v4",
    }
    try:
        await db.device_poll_status.update_one(
            {"client_id": conn.client_id, "device_ip": target},
            {
                "$set": snmp_set,
                "$setOnInsert": {
                    "client_id": conn.client_id,
                    "device_ip": target,
                    "first_poll_at": now_iso,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning("snmp_poll: device_poll_status upsert failed ip=%s err=%s", target, e)
    # Reflect live status in managed_devices so dashboards refresh in
    # real time. Only update fields that the UI cares about.
    md_set = {
        "status": "online" if reachable else "offline",
        "last_poll_at": now_iso,
        "last_poll_source": "agent_v4",
    }
    if r.get("sys_name"):
        md_set["sys_name"] = r["sys_name"]
    if r.get("sys_descr"):
        md_set["sys_descr"] = r["sys_descr"]
    try:
        await db.managed_devices.update_many(
            {"client_id": conn.client_id, "ip": target},
            {"$set": md_set},
        )
    except Exception as e:
        logger.warning("snmp_poll: managed_devices update failed ip=%s err=%s", target, e)


async def _build_poller_config(client_id: str) -> Dict[str, Any]:
    """Build poller config for one tenant.

    Two blocks are emitted:
      - `snmp.targets[]`  → list of devices with an explicit community
        (or a default `public`) used for sysName / sysDescr polling.
      - `ping.targets[]`  → list of *every* enabled managed device,
        regardless of SNMP capability. This is the heartbeat signal
        that drives UP/DOWN status on the dashboard and replaces the
        legacy PowerShell Connector polling loop.

    The returned shape matches the JSON tags expected by the Go agent
    in cmd/agent/main.go::OnWelcome.

    Behaviour:
      - Devices flagged `disabled` or with no `ip` are skipped.
      - Empty target lists still return a valid (disabled) block so the
        agent doesn't crash on first welcome.
    """
    snmp_targets: List[Dict[str, Any]] = []
    ping_targets: List[Dict[str, Any]] = []
    try:
        cursor = db.managed_devices.find(
            {"client_id": client_id, "ip": {"$ne": None, "$exists": True}},
            {"_id": 0, "ip": 1, "name": 1, "community": 1, "snmp_community": 1,
             "snmp_version": 1, "snmp_port": 1, "device_type": 1, "monitor_type": 1,
             "enabled": 1, "disabled": 1},
        )
        async for d in cursor:
            if d.get("disabled") is True or d.get("enabled") is False:
                continue
            ip = d.get("ip")
            if not ip:
                continue
            name = d.get("name") or ip
            # Every enabled device gets ping-polled (cheap, no auth).
            ping_targets.append({"ip": ip, "name": name})

            # SNMP-polled only when an explicit community is set OR the
            # device is classified as a network appliance/printer (we
            # try `public` by default for those).
            community = d.get("community") or d.get("snmp_community")
            monitor_type = (d.get("monitor_type") or "").lower()
            dev_type = (d.get("device_type") or "").lower()
            snmp_eligible = bool(community) or monitor_type == "snmp" or dev_type in (
                "switch", "firewall", "router", "ap", "printer", "ups", "network",
            )
            if snmp_eligible:
                snmp_targets.append({
                    "ip": ip,
                    "name": name,
                    "community": community or "public",
                    "profile": d.get("device_type") or "generic",
                    "snmp_version": d.get("snmp_version") or "v2c",
                    "snmp_port": int(d.get("snmp_port") or 161),
                })
    except Exception as e:  # pragma: no cover - degraded mode
        logger.warning("agent_ws: _build_poller_config error client_id=%s err=%s", client_id, e)

    return {
        "snmp": {
            "enabled": len(snmp_targets) > 0,
            "interval": "60s",
            "communities": ["public"],
            "timeout": "2s",
            "retries": 1,
            "targets": snmp_targets,
        },
        "ping": {
            "enabled": len(ping_targets) > 0,
            "interval": "60s",
            "timeout": "2s",
            "count": 1,
            "targets": ping_targets,
        },
    }


async def push_config_to_client(client_id: str) -> int:
    """Hot-push a refreshed poller config to every live agent of this tenant.

    Called after a device is approved / added / removed so the agent
    starts (or stops) polling it within seconds instead of waiting for
    the next service restart.

    Returns the number of agents successfully notified.
    """
    cfg = await _build_poller_config(client_id)
    payload = {
        "accepted_at": _now().isoformat(),
        "config": cfg,
        "reason": "device_assignment_changed",
    }
    sent = 0
    for c in REGISTRY.list():
        if c.client_id != client_id:
            continue
        try:
            c.seq += 1
            # Re-use server.welcome so the existing OnWelcome hot-swap
            # path in the agent applies the new targets immediately —
            # zero new code on the agent side.
            await c.send(make_frame("server.welcome", payload, seq=c.seq))
            sent += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("push_config_to_client: send failed agent=%s err=%s", c.agent_id, e)
    logger.info("push_config_to_client: client_id=%s notified=%d targets_snmp=%d targets_ping=%d",
                client_id, sent, len(cfg["snmp"]["targets"]), len(cfg["ping"]["targets"]))
    return sent


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


# --------------------------------------------------------------------------- #
#  POST /api/agent/scan-report
#
#  Endpoint per la TRAY UI (`nocagent-ui.exe` / `ArgusDesktop.exe`) per
#  inviare immediatamente i risultati di una scansione manuale al Center,
#  senza dover attendere il prossimo ciclo di discovery dell'agent
#  (default 5m). Lo abbiamo aggiunto su esplicita richiesta dell'utente:
#  "voglio un pulsante che quando finisce scan passi subito i dati al
#  center".
#
#  Auth: lo stesso `token` agent presente in `agent.yaml` (campo top-level)
#  passato come `?token=...` o header `Authorization: Bearer ...`.
#
#  Riusa la pipeline di `POST /api/connector/lan-scan`: gli endpoint
#  vengono salvati in `discovered_endpoints` E auto-censiti in
#  `managed_devices` (v3.8.15 workflow).
# --------------------------------------------------------------------------- #
class ScanReportEndpoint(BaseModel):
    ip: str
    mac: Optional[str] = None
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    rtt_ms: Optional[float] = None
    discovered_via: str = "ui_scan"   # default per distinguere scan manuali
    sys_descr: Optional[str] = None


class ScanReportRequest(BaseModel):
    client_id: str
    subnet: str
    endpoints: list[ScanReportEndpoint] = []


@router.post("/agent/scan-report")
async def agent_scan_report(req: ScanReportRequest, request: Request) -> Dict[str, Any]:
    # Estrai token sia da query (?token=) sia da header Authorization
    token = request.query_params.get("token", "")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing token")

    # Valida il token come fa la WS hello (agent_tokens o api_key cliente)
    auth_doc = await _validate_token(token, req.client_id)
    if not auth_doc:
        raise HTTPException(status_code=401, detail="invalid token or client_id")

    now_iso = _now().isoformat()
    stored = 0
    auto_managed = 0
    managed_ips = {
        d["ip"]
        async for d in db.managed_devices.find(
            {"client_id": req.client_id}, {"_id": 0, "ip": 1}
        )
        if d.get("ip")
    }

    for ep in req.endpoints:
        if not ep.ip:
            continue
        mac_norm = (ep.mac or "").lower().replace("-", ":").strip()
        update: Dict[str, Any] = {
            "client_id": req.client_id,
            "ip": ep.ip,
            "last_seen_at": now_iso,
            "last_seen_via": ep.discovered_via,
            "last_seen_subnet": req.subnet,
            "source": "ui_scan_button",
        }
        if mac_norm and len(mac_norm.replace(":", "")) == 12:
            update["mac"] = mac_norm
        if ep.hostname:
            update["hostname_scanner"] = ep.hostname
        if ep.vendor:
            update["vendor_scanner"] = ep.vendor
        if ep.sys_descr:
            update["sys_descr_scanner"] = ep.sys_descr

        # Upsert su (client_id, ip) cosi' funziona anche per device senza MAC
        await db.discovered_endpoints.update_one(
            {"client_id": req.client_id, "ip": ep.ip},
            {"$set": update},
            upsert=True,
        )
        stored += 1

        # Auto-censimento in managed_devices: se l'IP non e' gia' gestito,
        # creiamo un device "ping" con il nome scoperto. L'admin puo'
        # promuoverlo a SNMP successivamente.
        if ep.ip not in managed_ips:
            display_name = ep.hostname or ep.vendor or ep.ip
            await db.managed_devices.update_one(
                {"client_id": req.client_id, "ip": ep.ip},
                {"$setOnInsert": {
                    "client_id": req.client_id,
                    "ip": ep.ip,
                    "name": display_name,
                    "monitor_type": "ping",
                    "source": "ui_scan_button",
                    "status": "PENDING",
                    "created_at": now_iso,
                }},
                upsert=True,
            )
            auto_managed += 1
            managed_ips.add(ep.ip)

    logger.info(
        f"[UI-SCAN] client={req.client_id} subnet={req.subnet} stored={stored} "
        f"auto_managed={auto_managed} via=ui_scan_button"
    )
    return {
        "status": "ok",
        "client_id": req.client_id,
        "subnet": req.subnet,
        "endpoints_stored": stored,
        "devices_auto_added": auto_managed,
        "received_at": now_iso,
    }


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
        # client_name (nome leggibile cliente, es. "86BIT_Office") usato
        # dall'installer ps1 per popolare il titolo della tray UI desktop
        # senza richiedere all'utente di passarlo come parametro -ClientName.
        # Best-effort: se il cliente non e' nel DB (caso anomalo) ritorna
        # stringa vuota e l'installer fa fallback su client_id UUID.
        "client_name": await _resolve_client_label(client_id),
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
    mirror remoto.

    Prova in ordine:
      1) `TEMPLATE_URLS_BASE` (CDN dedicato ai template, raro);
      2) `BINARY_URLS_BASE` (GitHub Release: i template sono caricati
         come asset accanto ai .exe — vedi installer_gui.ps1.template);
      3) `WIZARD_TEMPLATE_FALLBACK_URL` (mirror NOC Center via
         /api/__static-templates__/<filename>).

    Usato come safety-net quando il backend e' deployato senza la
    cartella `noc-agent/build/` accanto (caso classico: deploy parziale
    su argus.86bit.it). Cache in-process per evitare una richiesta HTTP
    per ogni download del wizard.
    """
    cache = getattr(_fetch_template_from_mirror, "_cache", {})
    if filename in cache:
        return cache[filename]

    candidates: list[str] = []
    tpl_base = _os.environ.get("TEMPLATE_URLS_BASE", "").rstrip("/")
    if tpl_base:
        candidates.append(f"{tpl_base}/{filename}")
    bin_base = _os.environ.get("BINARY_URLS_BASE", "").rstrip("/")
    if bin_base:
        candidates.append(f"{bin_base}/{filename}")
    mirror = _os.environ.get("WIZARD_TEMPLATE_FALLBACK_URL", "").rstrip("/")
    if mirror:
        candidates.append(f"{mirror}/api/__static-templates__/{filename}")

    if not candidates:
        return None

    import urllib.request as _ureq
    headers = {"User-Agent": "argus-noc-center/1.0"}
    for url in candidates:
        try:
            req = _ureq.Request(url, headers=headers)
            with _ureq.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8")
        except Exception:
            continue
        cache[filename] = body
        setattr(_fetch_template_from_mirror, "_cache", cache)
        return body
    return None


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
    client_id = await _token_or_403(token)
    bundle = await _build_wizard_bundle(token)
    # Filename personalizzato col nome del cliente: cosi' i tecnici che
    # scaricano installer per piu' clienti non confondono i ZIP nella
    # cartella Download. Ricavo il nome dal client_id risolto sopra.
    client_label = await _resolve_client_label(client_id)
    # Includo SEMPRE la versione corrente del Connector v4 nel filename cosi'
    # il tecnico vede a colpo d'occhio quale build sta installando e i
    # download multipli non si sovrascrivono come "(1).zip" / "(2).zip" senza
    # contesto. Es: 86NocAgent-Installer-86BITOffice-v4.6.0.zip
    ver_label = await _resolve_latest_agent_version_safe()
    fname = f"86NocAgent-Installer-{client_label}-{ver_label}.zip"
    return FileResponse(bundle, media_type="application/zip", filename=fname)


# Cache in-process per la latest release GitHub. TTL breve (5 minuti) per
# evitare di stressare l'API di GitHub (60 req/h unauth) ad ogni download.
_AGENT_LATEST_CACHE: Dict[str, Any] = {"version": None, "expires_at": None}


async def _resolve_latest_agent_version_safe() -> str:
    """Ritorna il tag della latest GitHub Release per il Go Agent v4 in
    formato `vMAJ.MIN.PATCH` (es. ``v4.6.0``). Best-effort:

    1. Cache 5 min in memoria.
    2. Env var ``AGENT_LATEST_VERSION`` (override manuale per deploy
       offline / repo privati).
    3. GitHub API `releases/latest` su ``AGENT_GITHUB_REPO``
       (default ``santiM86/86NOCConnectorCenter``).
    4. Fallback ``"latest"`` se tutto fallisce (cosi' il filename resta
       sano anche senza connettivita').
    """
    import os as _os
    now = _now()
    cached = _AGENT_LATEST_CACHE.get("version")
    exp = _AGENT_LATEST_CACHE.get("expires_at")
    if cached and exp and now < exp:
        return cached
    override = (_os.environ.get("AGENT_LATEST_VERSION") or "").strip()
    if override:
        ver = override if override.startswith("v") else f"v{override}"
        _AGENT_LATEST_CACHE["version"] = ver
        _AGENT_LATEST_CACHE["expires_at"] = now + timedelta(minutes=5)
        return ver
    repo = (_os.environ.get("AGENT_GITHUB_REPO") or "santiM86/86NOCConnectorCenter").strip()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"User-Agent": "86NocCenter-installer", "Accept": "application/vnd.github.v3+json"}
    gh_token = (_os.environ.get("AGENT_GITHUB_TOKEN") or "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    try:
        import urllib.request as _ureq
        req = _ureq.Request(url, headers=headers)
        # GitHub API e' bloccante; eseguo in thread executor per non
        # bloccare l'event loop FastAPI.
        loop = asyncio.get_running_loop()
        def _fetch():
            with _ureq.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8"))
        rel = await loop.run_in_executor(None, _fetch)
        tag = (rel.get("tag_name") or "").strip()
        if tag:
            ver = tag if tag.startswith("v") else f"v{tag}"
            _AGENT_LATEST_CACHE["version"] = ver
            _AGENT_LATEST_CACHE["expires_at"] = now + timedelta(minutes=5)
            return ver
    except Exception as e:  # noqa: BLE001
        logger.warning("agent latest-version lookup failed: %s", e)
    # Cache anche il fallback per evitare hammering quando GitHub e' down.
    _AGENT_LATEST_CACHE["version"] = "latest"
    _AGENT_LATEST_CACHE["expires_at"] = now + timedelta(minutes=2)
    return "latest"


@router.get("/agent/latest-version")
async def agent_latest_version() -> Dict[str, str]:
    """Espone la versione corrente del Connector Go Agent v4 disponibile per
    download. Usata dalla UI del Center per:

      - mostrare ``v4.6.0`` sul bottone "Installer" per ciascun cliente
      - confronto con ``managed_agents.agent_version`` per evidenziare i
        connettori "outdated" (badge giallo)
    """
    ver = await _resolve_latest_agent_version_safe()
    return {"version": ver}


def _normalize_ver(v: Optional[str]) -> str:
    """Normalizza una version string per confronto (rimuove 'v', spazi, +metadata).
    Esempi: 'v4.10.3' -> '4.10.3', '4.0.0-dev+4755a03' -> '4.0.0'.
    """
    if not v:
        return ""
    v = v.strip().lstrip("vV")
    # tronca al primo '+' (build metadata semver) ed elimina '-dev/-beta'
    for sep in ("+", "-"):
        i = v.find(sep)
        if i >= 0:
            v = v[:i]
    return v


@router.get("/agents/upgrade-status")
async def agents_upgrade_status(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Ritorna lista agent con versione obsoleta rispetto alla latest.

    Output:
      {
        "latest": "v4.10.3",
        "total_agents": 42,
        "live_agents": 35,
        "outdated_count": 7,
        "outdated": [
           {"agent_id":..., "hostname":..., "client_id":..., "client_name":...,
            "current_version":..., "live": true/false},
           ...
        ]
      }
    """
    latest_raw = await _resolve_latest_agent_version_safe()
    latest_n = _normalize_ver(latest_raw)
    live_agent_ids = {c.agent_id for c in REGISTRY.list()}

    # Cache client_id -> name in batch
    client_ids: set[str] = set()
    cursor = db.managed_agents.find(
        {}, {"_id": 0, "agent_id": 1, "hostname": 1, "client_id": 1,
             "agent_version": 1, "last_seen_at": 1}
    )
    docs: List[Dict[str, Any]] = []
    async for d in cursor:
        docs.append(d)
        if d.get("client_id"):
            client_ids.add(d["client_id"])
    name_by_id: Dict[str, str] = {}
    if client_ids:
        async for c in db.clients.find(
            {"id": {"$in": list(client_ids)}}, {"_id": 0, "id": 1, "name": 1}
        ):
            name_by_id[c["id"]] = c.get("name") or c["id"][:8]

    outdated: List[Dict[str, Any]] = []
    for d in docs:
        cur_n = _normalize_ver(d.get("agent_version"))
        if not cur_n or not latest_n:
            continue
        if cur_n == latest_n:
            continue
        outdated.append({
            "agent_id": d.get("agent_id"),
            "hostname": d.get("hostname") or "",
            "client_id": d.get("client_id") or "",
            "client_name": name_by_id.get(d.get("client_id") or "", ""),
            "current_version": d.get("agent_version") or "",
            "last_seen_at": d.get("last_seen_at"),
            "live": d.get("agent_id") in live_agent_ids,
        })
    return {
        "latest": latest_raw,
        "total_agents": len(docs),
        "live_agents": len(live_agent_ids),
        "outdated_count": len(outdated),
        "outdated": outdated,
    }


@router.post("/agents/bulk-update")
async def agents_bulk_update(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Invia comando `update` agli agent indicati.

    Body:
      {
        "agent_ids": [...],          # opzionale: subset specifico
        "only_outdated": true,       # opzionale: filtra solo obsoleti vs latest
        "version": "v4.10.3"         # opzionale: target (default latest)
      }

    Se né agent_ids né only_outdated sono passati, ritorna 400.
    """
    agent_ids = payload.get("agent_ids") or []
    only_outdated = bool(payload.get("only_outdated"))
    target_version = (payload.get("version") or "").strip()

    if not agent_ids and not only_outdated:
        raise HTTPException(status_code=400, detail="Specifica agent_ids o only_outdated=true")
    require_admin(user)

    if not target_version:
        target_version = await _resolve_latest_agent_version_safe()
    target_n = _normalize_ver(target_version)

    # Se only_outdated, calcola la lista
    if only_outdated:
        async for d in db.managed_agents.find(
            {}, {"_id": 0, "agent_id": 1, "agent_version": 1}
        ):
            cur_n = _normalize_ver(d.get("agent_version"))
            if cur_n and target_n and cur_n != target_n:
                if d.get("agent_id") and d["agent_id"] not in agent_ids:
                    agent_ids.append(d["agent_id"])

    sent: List[str] = []
    failed: List[Dict[str, str]] = []
    for aid in agent_ids:
        conn = REGISTRY.get(aid)
        if conn is None:
            failed.append({"agent_id": aid, "reason": "agent non connesso"})
            continue
        try:
            await conn.send_command("update", {"version": target_version}, timeout=10.0)
            sent.append(aid)
        except Exception as e:
            failed.append({"agent_id": aid, "reason": str(e)[:160]})

    return {
        "target_version": target_version,
        "sent_count": len(sent),
        "sent": sent,
        "failed_count": len(failed),
        "failed": failed,
        "initiated_by": user.get("email") or user.get("id") or "system",
    }


async def _resolve_client_label(client_id: str) -> str:
    """Return a filesystem-safe label per il cliente da usare nei
    nomi file scaricabili. Ordine di preferenza: name -> slug -> id.
    """
    if not client_id:
        return "client"
    try:
        c = await db.clients.find_one(
            {"$or": [{"client_id": client_id}, {"slug": client_id}, {"id": client_id}]},
            {"_id": 0, "name": 1, "slug": 1, "client_id": 1},
        )
    except Exception:
        c = None
    label = ""
    if c:
        label = (c.get("name") or c.get("slug") or c.get("client_id") or "").strip()
    if not label:
        label = client_id
    # Sanitize per filename: solo [A-Za-z0-9._-], spazi -> underscore.
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in label)
    safe = safe.strip("._-") or "client"
    return safe[:40]


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
    client_id = await _token_or_403(token)
    bundle = _build_exe_bundle(token)
    client_label = await _resolve_client_label(client_id)
    ver_label = await _resolve_latest_agent_version_safe()
    return FileResponse(bundle, media_type="application/zip",
                        filename=f"86NocAgent-Setup-{client_label}-{ver_label}.zip")


@router.get("/agent/install/setup.exe")
async def setup_exe(token: Optional[str] = None) -> FileResponse:
    """Single-file Windows installer: 86NocAgent-Setup.exe.

    7-Zip Setup Deluxe SFX che embedda nocagent + nocwatchdog + nocagent-ui +
    argus.ico + il wizard PS1 (tutto firmato col token del cliente). L'utente
    fa SOLO doppio-click sul .exe: il wizard 7-step parte (Welcome ->
    master/scanner -> URL+token (precompilati ma editabili) -> dispositivi
    SNMP -> riepilogo -> install -> done).

    Identico a un installer Inno Setup / NSIS: zero estrazioni, zero PS in
    chiaro, zero dipendenze di rete per il bootstrap (i binari sono dentro).
    """
    client_id = await _token_or_403(token)
    setup_path = _build_setup_exe(token)
    client_label = await _resolve_client_label(client_id)
    ver_label = await _resolve_latest_agent_version_safe()
    return FileResponse(setup_path, media_type="application/vnd.microsoft.portable-executable",
                        filename=f"86NocAgent-Setup-{client_label}-{ver_label}.exe")


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
        return PlainTextResponse(await _render_wizard_ps1(token), media_type="text/plain; charset=utf-8")
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


async def _render_wizard_ps1(token: str) -> str:
    public_http = _os.environ.get("AGENT_PUBLIC_HTTP_URL", "https://argus.86bit.it")
    body = _read_template_or_fallback("installer_gui.ps1.template")
    # FIX v4.10.3: sostituiamo anche __VERSION__ con la latest release
    # risolta da GitHub. Senza questo il template cade sul default
    # hardcoded `$Version = "4.0.0"` (riga 73) e il PS1 scarica binari
    # v4.0.0 invece dell'ultima release disponibile. Era la causa del
    # bug reportato dall'utente: pulsante "Installer (latest)" che
    # installava sempre v4.0.0-dev.
    ver_label = await _resolve_latest_agent_version_safe()
    # Rimuovi prefisso "v" perche' il template usa il formato semver
    # nudo "4.10.2" come default di $Version.
    ver_naked = ver_label.lstrip("v") if ver_label and ver_label != "latest" else "4.0.0"
    return (body
            .replace("__BACKEND_URL__", public_http)
            .replace("__TOKEN__", token)
            .replace("__VERSION__", ver_naked))


async def _build_wizard_bundle(token: str) -> str:
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

    ps1_body = await _render_wizard_ps1(token)
    # Il launcher .bat e' embedded nel codice (15 righe, ~740 bytes): cosi'
    # il wizard funziona anche su deploy minimali (solo backend) senza
    # richiedere il file `Installa-86NocAgent.bat` sul filesystem prod.
    bat_body = (
        "@echo off\r\n"
        "REM ============================================================\r\n"
        "REM 86NocAgent v4 - Wizard installazione (avvio nascosto)\r\n"
        "REM ============================================================\r\n"
        "REM Lancia il wizard PowerShell senza mostrare ne' la console\r\n"
        "REM nera del .bat (chiusa subito) ne' la finestra blu di PS\r\n"
        "REM (lanciata in -WindowStyle Hidden). Il wizard grafico viene\r\n"
        "REM mostrato solo dopo la conferma UAC.\r\n"
        "REM\r\n"
        "REM Tasto destro -> \"Esegui come amministratore\" oppure semplice\r\n"
        "REM doppio-click (la auto-elevazione e' integrata nello script).\r\n"
        "REM ============================================================\r\n"
        "start \"\" powershell.exe -NoProfile -ExecutionPolicy Bypass "
        "-WindowStyle Hidden -File \"%~dp0installer_gui.ps1\"\r\n"
        "exit /b\r\n"
    )

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as z:
        z.writestr("Installa-86NocAgent.bat", bat_body)
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
