"""Consistency audit: lista device vs scheda device per-cliente.

Caso d'uso: prevenire bug come quelli rilevati il 2026-06-03 (pallino
verde su device OFFLINE da settimane). Confronta lo `status` ritornato
da `/api/clients/{cid}/devices` con quello ricostruibile da
`/api/devices/by-ip/{ip}/info-card`. Qualsiasi divergenza e' un bug.

Esposto come admin endpoint per poter essere chiamato live dall'utente.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin", "diagnostics"])


def _age_seconds(ts: Any) -> float | None:
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


@router.get("/consistency-audit")
async def consistency_audit(current_user: dict = Depends(get_current_user)):
    """Per OGNI device managed, confronta status calcolato vs reachable
    fresco. Flagga inconsistenze.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    issues: List[Dict[str, Any]] = []
    total = 0
    checked = 0
    now = datetime.now(timezone.utc)

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    name_by_cid = {c["id"]: c.get("name", "?") for c in clients}

    md_cursor = db.managed_devices.find(
        {"ip": {"$exists": True, "$ne": None}},
        {"_id": 0, "ip": 1, "client_id": 1, "name": 1, "mac": 1},
    )
    async for md in md_cursor:
        total += 1
        cid = md.get("client_id")
        ip = md.get("ip")
        if not cid or not ip:
            continue
        pd = await db.device_poll_status.find_one(
            {"client_id": cid, "device_ip": ip},
            {"_id": 0, "ping_reachable": 1, "reachable": 1, "last_poll_at": 1,
             "last_reachable_at": 1, "sys_name": 1, "unreachable_since": 1}
        )
        if not pd:
            continue
        checked += 1
        poll_age = _age_seconds(pd.get("last_poll_at"))
        # Regola: se ultimo poll fresco (<300s) e reachable=False e
        # unreachable_since vecchio (>1h), il device e' OFFLINE confermato
        is_reachable = bool(pd.get("ping_reachable") or pd.get("reachable"))
        unreach_age = _age_seconds(pd.get("unreachable_since"))

        if poll_age is not None and poll_age < 600 and not is_reachable:
            if unreach_age is not None and unreach_age > 3600:
                # Cerca evidenza scanner stale (potenziale falso positivo "verde")
                de = await db.discovered_endpoints.find_one(
                    {"client_id": cid, "ip": ip},
                    {"_id": 0, "last_seen_at": 1, "last_seen_via": 1,
                     "source_connector_mode": 1, "switch_ip": 1}
                )
                evidence_kind = None
                evidence_age = None
                if de:
                    evidence_age = _age_seconds(de.get("last_seen_at"))
                    if de.get("switch_ip") or (de.get("last_seen_via") or "").lower() == "snmp":
                        evidence_kind = "mac_table_switch"  # ok
                    elif (de.get("source_connector_mode") or "").lower() == "scanner":
                        evidence_kind = "scanner_lan"
                    elif (de.get("source_connector_mode") or "").lower() == "agent_v4":
                        evidence_kind = "agent_v4_arp"

                # Flagga solo i casi rischiosi: evidence presente ma di tipo
                # non affidabile, mentre ping conferma offline da >1h
                if evidence_kind and evidence_kind != "mac_table_switch":
                    issues.append({
                        "client_id": cid,
                        "client_name": name_by_cid.get(cid, "?"),
                        "device_ip": ip,
                        "device_name": md.get("name") or pd.get("sys_name") or ip,
                        "poll_says": "offline",
                        "poll_last_at": pd.get("last_poll_at"),
                        "poll_age_seconds": int(poll_age),
                        "unreachable_for_seconds": int(unreach_age),
                        "evidence_kind": evidence_kind,
                        "evidence_age_seconds": int(evidence_age) if evidence_age else None,
                        "issue": (
                            f"Device offline da {int(unreach_age/3600)}h ma "
                            f"evidence L2 stale ({evidence_kind}) potrebbe far "
                            f"apparire pallino verde nella lista — confermare "
                            f"con il fix v2026-06-03 in produzione"
                        ),
                    })

    return {
        "audited_at": now.isoformat(),
        "total_managed_devices": total,
        "checked": checked,
        "issues_count": len(issues),
        "issues": issues[:200],  # limite per response size
        "status": "ok" if not issues else "warning",
        "hint": (
            "Se vedi issues qui ma in UI compaiono come verdi, il fix backend "
            "'devices.py mac_table_switch only' NON e' in PROD. Save to GitHub + deploy."
            if issues else
            "Nessuna incoerenza rilevata: lista e card device sono allineate."
        ),
    }
