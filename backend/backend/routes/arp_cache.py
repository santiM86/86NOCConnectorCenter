"""
ARP cache cross-device — popolazione dalla ARP table dei router/switch.

Il connector periodicamente walka `ipNetToMediaPhysAddress` sui device che
hanno access ai neighbor (tipicamente router e switch layer-3). Ogni entry
diventa un doc in `db.arp_cache` con TTL 24h.

Poi quando l'utente apre la scheda info-card di un IP qualsiasi, se il MAC
non è disponibile via self-SNMP, fa lookup qui.
"""
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import logging

from database import db
from middleware.connector_security import verify_connector_request
from deps import get_current_user
from fastapi import Depends

router = APIRouter(prefix="/api", tags=["arp-cache"])
logger = logging.getLogger(__name__)

_idx_done = False


async def ensure_arp_idx():
    global _idx_done
    if _idx_done:
        return
    try:
        await db.arp_cache.create_index([("ip", 1)])
        await db.arp_cache.create_index([("mac", 1)])
        await db.arp_cache.create_index([("client_id", 1), ("ip", 1)])
        await db.arp_cache.create_index(
            [("last_seen", 1)],
            expireAfterSeconds=60 * 60 * 24 * 7,  # TTL 7 days
        )
        _idx_done = True
    except Exception as e:
        logger.warning(f"ARP cache index setup error: {e}")


@router.post("/connector/arp-batch")
async def ingest_arp_batch(request: Request, payload: dict):
    """Connector invia batch di entries ARP table raccolte da router/switch.
    payload: {
      source_device_ip: "10.0.0.1",
      entries: [{ip: "10.0.0.5", mac: "00:11:22:33:44:55"}, ...]
    }
    """
    await ensure_arp_idx()
    connector = await verify_connector_request(request)
    client_id = connector.get("client_id") or connector.get("id")
    source_ip = payload.get("source_device_ip") or payload.get("source_ip")
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="entries must be a list")

    now = datetime.now(timezone.utc)
    ops = []
    saved = 0
    for e in entries:
        ip = (e.get("ip") or "").strip()
        mac = (e.get("mac") or "").strip().upper()
        if not ip or not mac:
            continue
        # Normalize MAC to XX:XX:XX:XX:XX:XX
        mac_clean = mac.replace("-", ":").replace(".", ":")
        if len(mac_clean.replace(":", "")) == 12 and ":" not in mac_clean:
            mac_clean = ":".join(mac_clean[i : i + 2] for i in range(0, 12, 2))
        ops.append(
            {
                "client_id": client_id,
                "ip": ip,
                "mac": mac_clean.upper(),
                "source_device_ip": source_ip,
                "last_seen": now,
            }
        )
        saved += 1

    if ops:
        # upsert one-by-one on (client_id, ip)
        for op in ops:
            await db.arp_cache.update_one(
                {"client_id": op["client_id"], "ip": op["ip"]},
                {"$set": op},
                upsert=True,
            )

    return {"status": "ok", "saved": saved}


@router.get("/arp-cache")
async def list_arp_cache(
    client_id: Optional[str] = None,
    ip: Optional[str] = None,
    mac: Optional[str] = None,
    limit: int = 500,
    current_user: dict = Depends(get_current_user),
):
    """Elenco entries ARP con filtri (per debug / visibility)."""
    q = {}
    if client_id:
        q["client_id"] = client_id
    if ip:
        q["ip"] = ip
    if mac:
        q["mac"] = mac.upper()
    items = []
    async for doc in db.arp_cache.find(q, {"_id": 0}).sort("last_seen", -1).limit(limit):
        if isinstance(doc.get("last_seen"), datetime):
            doc["last_seen"] = doc["last_seen"].isoformat()
        items.append(doc)
    return {"count": len(items), "items": items}


@router.get("/arp-cache/by-ip/{ip}")
async def lookup_mac_by_ip(ip: str, current_user: dict = Depends(get_current_user)):
    """Lookup MAC for an IP across all ARP sources."""
    doc = await db.arp_cache.find_one({"ip": ip}, {"_id": 0}, sort=[("last_seen", -1)])
    if not doc:
        return {"ip": ip, "mac": None, "source_device_ip": None}
    if isinstance(doc.get("last_seen"), datetime):
        doc["last_seen"] = doc["last_seen"].isoformat()
    return doc
