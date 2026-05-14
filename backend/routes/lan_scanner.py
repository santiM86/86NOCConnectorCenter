"""LAN Scanner — endpoint REST per scansione on-demand via WS comando.

Architettura:
  1. UI Web (frontend React) chiama POST /api/lan-scans → genera scan_id,
     persiste il run su Mongo, invia comando `lan_scan` all'agent via WS.
  2. Agent Go esegue scan ICMP+ARP+NBNS e streamma risultati via
     agent.event { kind: lan_scan_result | progress | done }.
  3. agent_ws._on_event bridge intercetta questi eventi e li appende al
     documento Mongo lan_scan_runs.{scan_id}.
  4. UI polla GET /api/lan-scans/{scan_id} ogni 1s e aggiorna la tabella
     live finché lo stato passa a "done" (o "error" / "cancelled").

Collection MongoDB: lan_scan_runs
  {
    _id: ObjectId,
    scan_id: str (uuid hex),         # indice unique
    agent_id: str,
    client_id: str,
    cidr: str,
    status: "running" | "done" | "cancelled" | "error",
    started_at: ISO datetime,
    ended_at: ISO datetime | None,
    progress: { done, total, found },
    error: str | None,
    results: [ { ip, mac, hostname, vendor, status, rtt_ms }, ... ],
    initiated_by: str (user_id)
  }
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lan-scans", tags=["lan-scanner"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Pydantic models ----------------------------------------------------

class StartScanRequest(BaseModel):
    agent_id: str = Field(..., description="agent_id del Connector da usare")
    cidr: Optional[str] = Field(None, description="CIDR target (vuoto = subnet locale agent)")


class ScanResult(BaseModel):
    ip: str
    mac: Optional[str] = None
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    status: str
    rtt_ms: int = -1
    # Fingerbank enrichment (best-effort, popolato asincronamente)
    device_name: Optional[str] = None
    device_score: Optional[int] = None
    # mDNS / HTTP banner enrichment dall'agent
    mdns_name: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    http_server: Optional[str] = None


class ScanRun(BaseModel):
    scan_id: str
    agent_id: str
    client_id: Optional[str] = None
    cidr: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    progress: Dict[str, int] = Field(default_factory=lambda: {"done": 0, "total": 0, "found": 0})
    error: Optional[str] = None
    results: List[ScanResult] = Field(default_factory=list)


# ---- Helpers ------------------------------------------------------------

def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


# ---- Endpoints ----------------------------------------------------------

@router.post("", response_model=ScanRun, status_code=status.HTTP_202_ACCEPTED)
async def start_scan(req: StartScanRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Avvia uno scan LAN on-demand sull'agent indicato.

    Ritorna immediatamente con scan_id e status="running"; l'UI polla
    GET /api/lan-scans/{scan_id} per i risultati live.
    """
    # Lazy import per evitare cicli — agent_ws importa anche cose pesanti.
    from routes.agent_ws import REGISTRY  # noqa: F401

    conn = REGISTRY.get(req.agent_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Agent {req.agent_id} non connesso",
        )

    # Recupera client_id dell'agent (utile per filtri UI).
    agent_doc = await db.managed_agents.find_one(
        {"agent_id": req.agent_id}, {"_id": 0, "client_id": 1}
    )
    client_id = (agent_doc or {}).get("client_id")

    scan_id = uuid.uuid4().hex
    cidr = (req.cidr or "").strip()

    doc = {
        "scan_id": scan_id,
        "agent_id": req.agent_id,
        "client_id": client_id,
        "cidr": cidr,
        "status": "running",
        "started_at": _now().isoformat(),
        "ended_at": None,
        "progress": {"done": 0, "total": 0, "found": 0},
        "error": None,
        "results": [],
        "initiated_by": user.get("id") or user.get("email") or "system",
    }
    await db.lan_scan_runs.insert_one(doc)

    # Invia comando all'agent. Risposta è ACK immediato; lo scan
    # vero gira in goroutine e streamma via agent.event.
    try:
        reply = await conn.send_command("lan_scan", {"scan_id": scan_id, "cidr": cidr}, timeout=8.0)
        # L'agent può rispondere con cidr aggiornato (auto-detect).
        if isinstance(reply, dict) and reply.get("cidr"):
            cidr = str(reply["cidr"])
            await db.lan_scan_runs.update_one(
                {"scan_id": scan_id}, {"$set": {"cidr": cidr}}
            )
    except asyncio.TimeoutError:
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id},
            {"$set": {"status": "error", "error": "agent non risponde (timeout 8s)", "ended_at": _now().isoformat()}},
        )
        raise HTTPException(status_code=504, detail="Agent non risponde (timeout)")
    except Exception as e:
        logger.exception("start_scan failed agent=%s", req.agent_id)
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id},
            {"$set": {"status": "error", "error": str(e), "ended_at": _now().isoformat()}},
        )
        raise HTTPException(status_code=500, detail=str(e))

    doc["cidr"] = cidr
    return ScanRun(**_strip_id(doc))


@router.get("/{scan_id}", response_model=ScanRun)
async def get_scan(scan_id: str, _user: Dict[str, Any] = Depends(get_current_user)):
    doc = await db.lan_scan_runs.find_one({"scan_id": scan_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="scan_id non trovato")
    # Sanitize: rimuovi _id dai risultati nested (se presenti)
    for r in doc.get("results") or []:
        r.pop("_id", None)
    return ScanRun(**doc)


@router.delete("/{scan_id}")
async def cancel_scan(scan_id: str, _user: Dict[str, Any] = Depends(get_current_user)):
    """Cancella uno scan in corso (invia lan_scan_cancel all'agent)."""
    doc = await db.lan_scan_runs.find_one({"scan_id": scan_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="scan_id non trovato")
    if doc.get("status") != "running":
        return {"cancelled": False, "reason": f"status={doc.get('status')}"}

    from routes.agent_ws import REGISTRY  # lazy

    conn = REGISTRY.get(doc["agent_id"])
    if conn is None:
        # Agent disconnesso: marca solo lo stato.
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id},
            {"$set": {"status": "cancelled", "ended_at": _now().isoformat()}},
        )
        return {"cancelled": True, "reason": "agent disconnesso"}

    try:
        await conn.send_command("lan_scan_cancel", None, timeout=5.0)
    except Exception as e:
        logger.warning("lan_scan_cancel agent error: %s", e)

    await db.lan_scan_runs.update_one(
        {"scan_id": scan_id},
        {"$set": {"status": "cancelled", "ended_at": _now().isoformat()}},
    )
    return {"cancelled": True}


@router.get("", response_model=List[ScanRun])
async def list_scans(
    agent_id: Optional[str] = None,
    client_id: Optional[str] = None,
    limit: int = 20,
    _user: Dict[str, Any] = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if agent_id:
        q["agent_id"] = agent_id
    if client_id:
        q["client_id"] = client_id
    limit = max(1, min(limit, 100))
    cur = db.lan_scan_runs.find(q, {"_id": 0}).sort("started_at", -1).limit(limit)
    out: List[ScanRun] = []
    async for doc in cur:
        for r in doc.get("results") or []:
            r.pop("_id", None)
        out.append(ScanRun(**doc))
    return out


@router.post("/{scan_id}/import")
async def import_to_client(
    scan_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Importa selezione di device dai risultati scan nei managed_devices
    del cliente. Body: {client_id, devices:[{ip,name,monitor_type,community,
    device_type}]}.

    Skip atomico se l'IP è già presente per quel client_id.
    """
    client_id = payload.get("client_id")
    devices_in = payload.get("devices") or []
    if not client_id or not isinstance(devices_in, list) or not devices_in:
        raise HTTPException(status_code=400, detail="client_id e devices richiesti")
    if not await db.clients.find_one({"id": client_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="client non trovato")
    if not await db.lan_scan_runs.find_one({"scan_id": scan_id}, {"_id": 0, "scan_id": 1}):
        raise HTTPException(status_code=404, detail="scan_id non trovato")

    imported: List[Dict[str, Any]] = []
    skipped: List[str] = []
    now_iso = _now().isoformat()
    for d in devices_in:
        ip = (d.get("ip") or "").strip()
        if not ip:
            continue
        # Skip se già presente per il cliente.
        existing = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": ip}, {"_id": 0, "id": 1}
        )
        if existing:
            skipped.append(ip)
            continue
        doc = {
            "id": uuid.uuid4().hex,
            "client_id": client_id,
            "ip": ip,
            "name": d.get("name") or d.get("hostname") or ip,
            "community": d.get("community") or "public",
            "monitor_type": d.get("monitor_type") or "ping",
            "device_type": d.get("device_type") or "generic",
            "http_port": d.get("http_port") or 80,
            "snmp_version": d.get("snmp_version") or "v2c",
            "created_at": now_iso,
            "created_by": user.get("email") or user.get("id") or "lan-scanner-import",
            "imported_from_scan": scan_id,
        }
        await db.managed_devices.insert_one(doc)
        # Pulisci blacklist se IP era stato eliminato prima.
        await db.deleted_devices.delete_many({"client_id": client_id, "device_ip": ip})
        imported.append({"ip": ip, "id": doc["id"], "name": doc["name"]})
    return {"imported": len(imported), "skipped": skipped, "items": imported}


# ---- Fingerbank enrichment (best-effort, asincrono) ---------------------

async def _enrich_fingerbank(scan_id: str, ip: str, mac: str) -> None:
    """Interroga Fingerbank con il MAC del device e aggiorna il documento
    `lan_scan_runs.results.$` con `device_name` + `device_score`.

    Best-effort: se la key non è configurata, no match, rate-limit (429) o
    qualsiasi altra failure, lascia il record com'è.

    Cap rispetto delle quote: la funzione `fingerbank_service.interrogate`
    già fa caching 30gg su MAC normalizzato, quindi richiamarla per device
    già visti non consuma quota gratuita (250 query/giorno).
    """
    try:
        from services import fingerbank_service
        if not await fingerbank_service.is_configured():
            return
        fb = await fingerbank_service.interrogate(mac=mac)
        if not fb or not fb.get("device_name"):
            return
        # Update inline del result nell'array. Usiamo arrayFilters per
        # essere atomici anche se nuovi result vengono pushati intanto.
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id, "results.ip": ip},
            {"$set": {
                "results.$.device_name": fb["device_name"],
                "results.$.device_score": fb.get("score"),
            }},
        )
    except Exception as e:
        logger.warning("fingerbank enrichment failed scan=%s ip=%s err=%s", scan_id, ip, e)


# ---- Bridge eventi (chiamato da agent_ws._on_event) ---------------------

async def bridge_lan_scan_event(kind: str, data: Dict[str, Any]) -> None:
    """Appendi/aggiorna lan_scan_runs in base agli eventi streaming agent.

    kind ∈ {"lan_scan_result", "lan_scan_progress", "lan_scan_done"}.
    """
    if not isinstance(data, dict):
        return
    scan_id = data.get("scan_id")
    if not scan_id:
        return

    if kind == "lan_scan_result":
        r = data.get("result") or {}
        if not isinstance(r, dict) or not r.get("ip"):
            return
        ip = r["ip"]
        existing = await db.lan_scan_runs.find_one(
            {"scan_id": scan_id, "results.ip": ip},
            {"_id": 0, "results.$": 1},
        )
        merged = r
        if existing and existing.get("results"):
            prev = existing["results"][0]
            merged = {
                "ip": ip,
                "mac": r.get("mac") or prev.get("mac"),
                "hostname": r.get("hostname") or prev.get("hostname"),
                "vendor": r.get("vendor") or prev.get("vendor"),
                "status": "alive" if "alive" in (r.get("status"), prev.get("status")) else r.get("status") or prev.get("status"),
                "rtt_ms": r.get("rtt_ms") if r.get("rtt_ms", -1) >= 0 else prev.get("rtt_ms", -1),
                # Conserva eventuale enrichment Fingerbank precedente
                "device_name": prev.get("device_name") or r.get("device_name"),
                "device_score": prev.get("device_score") or r.get("device_score"),
                # mDNS / HTTP banner: best of two
                "mdns_name": r.get("mdns_name") or prev.get("mdns_name"),
                "services": r.get("services") or prev.get("services") or [],
                "http_server": r.get("http_server") or prev.get("http_server"),
            }
            await db.lan_scan_runs.update_one(
                {"scan_id": scan_id},
                {"$pull": {"results": {"ip": ip}}},
            )
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id},
            {"$push": {"results": merged}},
        )
        # Schedula Fingerbank enrichment in background se MAC presente.
        if merged.get("mac") and not merged.get("device_name"):
            import asyncio as _aio  # lazy
            _aio.create_task(_enrich_fingerbank(scan_id, ip, merged["mac"]))

    elif kind == "lan_scan_progress":
        await db.lan_scan_runs.update_one(
            {"scan_id": scan_id},
            {
                "$set": {
                    "progress": {
                        "done": int(data.get("done") or 0),
                        "total": int(data.get("total") or 0),
                        "found": int(data.get("found") or 0),
                    }
                }
            },
        )

    elif kind == "lan_scan_done":
        upd: Dict[str, Any] = {
            "status": "error" if data.get("error") else "done",
            "ended_at": data.get("ended_at") or _now().isoformat(),
        }
        if data.get("error"):
            upd["error"] = str(data["error"])
        await db.lan_scan_runs.update_one({"scan_id": scan_id}, {"$set": upd})
