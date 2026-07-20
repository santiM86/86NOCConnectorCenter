"""
Syslog & SNMP Trap ingestion — receives events pushed by the connector.

Il connector apre UDP 514 (syslog) e UDP 162 (snmp-trap) localmente.
Ogni pacchetto ricevuto viene batchato e POSTato qui ogni 30s.

Collections:
  syslog_events:  {device_ip, facility, severity, host, message, ts}  TTL 14 giorni
  snmp_traps:     {device_ip, community, trap_oid, varbinds, raw_b64, ts}  TTL 14 giorni
"""
from fastapi import APIRouter, HTTPException, Header, Request
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import re
import uuid
import logging

from database import db
from middleware.connector_security import verify_connector_request

router = APIRouter(prefix="/api/connector", tags=["syslog-trap"])
logger = logging.getLogger(__name__)

TTL_DAYS = 14
SYSLOG_SEVERITY_LABELS = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]
SYSLOG_FACILITY_LABELS = ["kernel", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
                          "uucp", "cron", "authpriv", "ftp", "ntp", "security", "console", "cron2",
                          "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7"]

ALERT_PATTERNS = [
    (re.compile(r"authentication\s*(fail|error|denied)", re.I), "high", "Authentication Failure"),
    (re.compile(r"login\s*(fail|failed)", re.I), "high", "Login Failure"),
    (re.compile(r"link\s*down|interface.*down", re.I), "high", "Link Down"),
    (re.compile(r"link\s*up|interface.*up", re.I), "info", "Link Up"),
    (re.compile(r"configuration\s*change|config\s*saved", re.I), "info", "Config Changed"),
    (re.compile(r"power\s*(supply|outage|loss|fail)", re.I), "critical", "Power Issue"),
    (re.compile(r"temperature.*(high|critical|overheat)", re.I), "critical", "Overheat"),
    (re.compile(r"fan\s*(fail|fault)", re.I), "high", "Fan Fault"),
    (re.compile(r"panic|crash|kernel.*oops", re.I), "critical", "System Crash"),
    (re.compile(r"disk\s*(fail|error|smart)", re.I), "high", "Disk Issue"),
    (re.compile(r"memory\s*(error|ecc|fail)", re.I), "critical", "Memory Error"),
]


async def _ensure_indexes():
    try:
        await db.syslog_events.create_index("ts", expireAfterSeconds=TTL_DAYS * 86400)
        await db.syslog_events.create_index([("device_ip", 1), ("ts", -1)])
        await db.snmp_traps.create_index("ts", expireAfterSeconds=TTL_DAYS * 86400)
        await db.snmp_traps.create_index([("device_ip", 1), ("ts", -1)])
    except Exception:
        pass


@router.post("/syslog-batch")
async def ingest_syslog_batch(
    request: Request,
    payload: dict,
):
    """Connector invia batch syslog events ogni 30s.
    payload: {hostname, events: [{device_ip, raw, received_at}]}
    Parse RFC 3164/5424 e salva in syslog_events. Genera alert per pattern noti.
    """
    connector = await verify_connector_request(request)
    client_id = connector.get("client_id") or connector.get("id")
    events = payload.get("events") or []
    if not events:
        return {"stored": 0}

    now = datetime.now(timezone.utc)
    docs = []
    alerts_to_create = []

    for ev in events[:2000]:  # safety cap
        raw = str(ev.get("raw", "")).strip()
        if not raw:
            continue
        device_ip = str(ev.get("device_ip", "")).strip() or "unknown"

        # Parse PRI header: <PRI>Msg
        severity = 6  # info default
        facility = 1
        msg = raw
        m = re.match(r"^<(\d+)>(.*)", raw)
        if m:
            pri = int(m.group(1))
            severity = pri & 7
            facility = pri >> 3
            msg = m.group(2).strip()

        # Try to parse host + timestamp (RFC 3164: "Mon DD HH:MM:SS host message")
        host = None
        host_match = re.match(r"^\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+(\S+)\s+(.*)", msg)
        if host_match:
            host = host_match.group(1)
            msg = host_match.group(2)

        docs.append({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_ip": device_ip,
            "host": host,
            "severity": severity,
            "severity_label": SYSLOG_SEVERITY_LABELS[severity] if severity < 8 else "unknown",
            "facility": facility,
            "facility_label": SYSLOG_FACILITY_LABELS[facility] if facility < len(SYSLOG_FACILITY_LABELS) else f"local{facility}",
            "message": msg[:2000],
            "raw": raw[:3000],
            "ts": now,
        })

        # Pattern-based alerting (only severity <= warning)
        if severity <= 4:
            for pat, alert_sev, title in ALERT_PATTERNS:
                if pat.search(msg):
                    alerts_to_create.append({
                        "id": str(uuid.uuid4()),
                        "client_id": client_id,
                        "device_ip": device_ip,
                        "device_name": host or device_ip,
                        "severity": alert_sev,
                        "title": f"Syslog: {title} ({host or device_ip})",
                        "message": f"[{SYSLOG_SEVERITY_LABELS[severity]}] {msg[:300]}",
                        "source_type": "syslog_pattern",
                        "status": "open",
                        "created_at": now.isoformat(),
                    })
                    break

    if docs:
        try:
            await db.syslog_events.insert_many(docs, ordered=False)
        except Exception as e:
            logger.warning(f"syslog insert_many fail: {e}")

    # Dedup alerts (prevent flood)
    if alerts_to_create:
        seen = set()
        dedup = []
        for a in alerts_to_create:
            key = (a["device_ip"], a["title"])
            if key not in seen:
                seen.add(key)
                dedup.append(a)
        if dedup:
            try:
                await db.alerts.insert_many(dedup, ordered=False)
            except Exception:
                pass

    return {"stored": len(docs), "alerts_created": len(set((a["device_ip"], a["title"]) for a in alerts_to_create))}


@router.post("/snmp-trap-batch")
async def ingest_trap_batch(
    request: Request,
    payload: dict,
):
    """Connector invia batch SNMP traps (raw UDP payload base64).
    payload: {hostname, traps: [{device_ip, raw_b64, community?, received_at}]}
    Salva in snmp_traps. Se ha parsed info (trap_oid, varbinds) li indicizza.
    """
    connector = await verify_connector_request(request)
    client_id = connector.get("client_id") or connector.get("id")
    traps = payload.get("traps") or []
    if not traps:
        return {"stored": 0}

    now = datetime.now(timezone.utc)
    docs = []

    for t in traps[:1000]:
        device_ip = str(t.get("device_ip", "")).strip() or "unknown"
        docs.append({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_ip": device_ip,
            "community": t.get("community"),
            "trap_oid": t.get("trap_oid"),
            "varbinds": t.get("varbinds"),
            "raw_b64": t.get("raw_b64", "")[:10000],
            "ts": now,
        })

    if docs:
        try:
            await db.snmp_traps.insert_many(docs, ordered=False)
        except Exception as e:
            logger.warning(f"snmp_traps insert_many fail: {e}")

    return {"stored": len(docs)}


# ---------- Read endpoints for frontend ----------
from deps import get_current_user
from fastapi import Depends


@router.get("/syslog")
async def list_syslog(
    device_ip: Optional[str] = None,
    severity_max: int = 7,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    q = {"severity": {"$lte": severity_max}}
    if device_ip:
        q["device_ip"] = device_ip
    cursor = db.syslog_events.find(q, {"_id": 0, "raw": 0}).sort("ts", -1).limit(min(limit, 500))
    items = [s async for s in cursor]
    for it in items:
        if isinstance(it.get("ts"), datetime):
            it["ts"] = it["ts"].isoformat()
    return {"count": len(items), "items": items}


@router.get("/snmp-traps")
async def list_traps(
    device_ip: Optional[str] = None,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    q = {}
    if device_ip:
        q["device_ip"] = device_ip
    cursor = db.snmp_traps.find(q, {"_id": 0, "raw_b64": 0}).sort("ts", -1).limit(min(limit, 500))
    items = [t async for t in cursor]
    for it in items:
        if isinstance(it.get("ts"), datetime):
            it["ts"] = it["ts"].isoformat()
    return {"count": len(items), "items": items}
