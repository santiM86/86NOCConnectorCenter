"""Freshness audit endpoint: verifica che tutte le pipeline dati di
telemetria (heartbeat agent, SNMP poll, ping, WAN, discovery) ricevano
dati freschi entro le soglie concordate.

Esposto per uso interno (debug live, dashboard QA in produzione).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin", "diagnostics"])

# Soglie di freshness in secondi (allineate alla tabella SLA interna)
THRESHOLDS_S = {
    "agent_heartbeat": 300,        # 5 min  (HB nominale 15s)
    "connector_legacy": 120,        # 2 min  (PowerShell connector legacy)
    "snmp_poll": 600,               # 10 min (SNMP per device)
    "icmp_reachable": 300,          # 5 min  (ping)
    "discovery_seen": 900,          # 15 min (managed_devices)
    "wan_probe": 300,               # 5 min  (WAN probe centrale)
    "lan_scan": 1800,               # 30 min (scanner watchdog)
}

# Sorgenti device che NON hanno per definizione un last_seen_at "vivo"
# (sono device iniettati da seed o rinomina utente, non monitorati live)
_PENDING_SOURCES = {"datto-seed", "user_rename", "manual", "imported"}


def _parse_ts(ts: Any) -> datetime | None:
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            dt = ts
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _age_seconds(ts: Any, now: datetime) -> float | None:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds()


async def _audit_pipeline(collection: str, ts_field: str, threshold_s: int,
                          filter_q: Dict[str, Any] | None = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    proj = {"_id": 0, ts_field: 1, "client_id": 1}
    docs = await db[collection].find(filter_q or {}, proj).to_list(20000)
    fresh = stale = no_ts = 0
    oldest = 0.0
    by_client: Dict[str, Dict[str, int]] = {}
    for d in docs:
        cid = d.get("client_id") or "_global"
        by_client.setdefault(cid, {"fresh": 0, "stale": 0, "no_ts": 0})
        age = _age_seconds(d.get(ts_field), now)
        if age is None:
            no_ts += 1
            by_client[cid]["no_ts"] += 1
            continue
        if age <= threshold_s:
            fresh += 1
            by_client[cid]["fresh"] += 1
        else:
            stale += 1
            by_client[cid]["stale"] += 1
            if age > oldest:
                oldest = age
    total = fresh + stale + no_ts
    status = "ok"
    if total > 0:
        # Tutto stale = critico; >50% stale = warning; altrimenti ok
        if fresh == 0 and stale > 0:
            status = "critical"
        elif stale / total > 0.5:
            status = "warning"
    return {
        "collection": collection,
        "field": ts_field,
        "threshold_seconds": threshold_s,
        "total": total,
        "fresh": fresh,
        "stale": stale,
        "no_timestamp": no_ts,
        "oldest_stale_seconds": int(oldest) if oldest else 0,
        "status": status,
        "by_client": by_client,
    }


@router.get("/freshness-audit")
async def freshness_audit(current_user: dict = Depends(get_current_user)):
    """Restituisce lo stato di freshness di tutte le pipeline di telemetria.

    Permette di rilevare immediatamente se SNMP/ICMP/discovery/WAN/heartbeat
    non aggiornano i dati entro le soglie SLA concordate.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    now = datetime.now(timezone.utc)
    pipelines: List[Dict[str, Any]] = []

    pipelines.append({
        "name": "agent_heartbeat",
        "description": "Heartbeat Go Agent v4 (WebSocket)",
        **(await _audit_pipeline(
            "managed_agents", "last_heartbeat_at",
            THRESHOLDS_S["agent_heartbeat"]))
    })
    pipelines.append({
        "name": "connector_legacy",
        "description": "Heartbeat connector legacy (PowerShell)",
        **(await _audit_pipeline(
            "connector_status", "last_seen",
            THRESHOLDS_S["connector_legacy"]))
    })
    pipelines.append({
        "name": "lan_scan",
        "description": "Auto-discovery LAN scan (sub-thread Poll-LanEndpoints)",
        **(await _audit_pipeline(
            "connector_status", "last_lan_scan_at",
            THRESHOLDS_S["lan_scan"]))
    })
    pipelines.append({
        "name": "snmp_poll",
        "description": "SNMP polling per device (switch/firewall/printer)",
        **(await _audit_pipeline(
            "device_poll_status", "last_poll",
            THRESHOLDS_S["snmp_poll"]))
    })
    pipelines.append({
        "name": "icmp_reachable",
        "description": "ICMP / ping reachability per device",
        **(await _audit_pipeline(
            "device_poll_status", "last_reachable_at",
            THRESHOLDS_S["icmp_reachable"]))
    })
    # Per managed_devices escludiamo i source seed/rename: sono device
    # placeholder che per definizione non hanno last_seen_at fino al primo
    # discovery reale. Conteggiarli "stale" gonfierebbe i falsi positivi.
    pipelines.append({
        "name": "discovery_seen",
        "description": "Discovery ARP/mDNS/LLDP — managed_devices.last_seen_at",
        **(await _audit_pipeline(
            "managed_devices", "last_seen_at",
            THRESHOLDS_S["discovery_seen"],
            filter_q={"source": {"$nin": list(_PENDING_SOURCES)}}))
    })
    pipelines.append({
        "name": "wan_probe",
        "description": "Probe WAN centrale (FastAPI scheduler)",
        **(await _audit_pipeline(
            "wan_probe_results", "checked_at",
            THRESHOLDS_S["wan_probe"]))
    })

    # Stato globale: il peggiore tra le pipeline (escludendo collection vuote)
    severities = {"ok": 0, "warning": 1, "critical": 2}
    overall = "ok"
    for p in pipelines:
        if p["total"] == 0:
            continue
        if severities[p["status"]] > severities[overall]:
            overall = p["status"]

    # Arricchisci by_client con nome cliente leggibile
    client_docs = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    name_by_cid = {c["id"]: c.get("name", "?") for c in client_docs}

    # Costruisci una vista per-cliente compatta
    per_client_summary: Dict[str, Dict[str, Any]] = {}
    for p in pipelines:
        for cid, stats in p.get("by_client", {}).items():
            if cid == "_global":
                continue
            per_client_summary.setdefault(cid, {
                "client_id": cid,
                "client_name": name_by_cid.get(cid, "?"),
                "pipelines": {}
            })
            per_client_summary[cid]["pipelines"][p["name"]] = stats

    return {
        "audited_at": now.isoformat(),
        "overall_status": overall,
        "thresholds_seconds": THRESHOLDS_S,
        "pipelines": pipelines,
        "per_client": list(per_client_summary.values()),
    }
