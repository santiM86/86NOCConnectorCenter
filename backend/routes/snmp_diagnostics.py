"""Diagnostica SNMP per device stale.

Endpoint admin per identificare PERCHE' un device specifico non riceve
polling SNMP fresco, e forzare un poll immediato.

Caso d'uso tipico: lo Switch 10.10.41.221 (cliente Zitac) mostra
"ULTIMO POLL: 06/05/2026" mentre l'agent ZITACSRV e' online. Causa:
subnet-aware dispatching scarta il target perche' l'agent_ip e'
in una subnet diversa dal device → 0 SNMP targets nella poller_config.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List
import asyncio
import ipaddress

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user
from routes.agent_ws import REGISTRY, _agent_subnet_from_ip, _ip_in_subnet

router = APIRouter(prefix="/api/admin", tags=["admin", "diagnostics"])


def _age_seconds(ts: Any) -> float | None:
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
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


@router.get("/snmp-diagnosis/{client_id}/{device_ip}")
async def snmp_diagnosis(client_id: str, device_ip: str,
                         current_user: dict = Depends(get_current_user)):
    """Diagnosi: PERCHE' questo device non riceve polling SNMP fresco?

    Restituisce:
      - device: managed_devices + device_poll_status (last_poll, ecc.)
      - agents: tutti gli agent del cliente con agent_ip, subnet, role,
                online, e SE il device cade nella loro subnet
      - dispatch_analysis: chi DOVREBBE pollare questo device e perche'
                (subnet match, master fallback, ecc.)
      - diagnosis: stringa human-readable con root cause + suggerimento fix
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    md = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip},
        {"_id": 0, "ip": 1, "name": 1, "device_type": 1, "monitor_type": 1,
         "community": 1, "snmp_community": 1, "snmp_version": 1,
         "enabled": 1, "disabled": 1}
    )
    pd = await db.device_poll_status.find_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"_id": 0, "last_poll": 1, "last_reachable_at": 1, "reachable": 1,
         "sys_name": 1, "sys_descr": 1}
    )

    # Lista agent del cliente (online + offline)
    agents_db = await db.managed_agents.find(
        {"client_id": client_id},
        {"_id": 0, "agent_id": 1, "hostname": 1, "role": 1, "agent_ip": 1,
         "last_heartbeat_at": 1, "last_seen_at": 1, "connected": 1}
    ).to_list(50)

    online_agent_ids = {c.agent_id for c in REGISTRY.list()
                        if c.client_id == client_id}

    agents_info: List[Dict[str, Any]] = []
    eligible: List[Dict[str, Any]] = []
    other_subnets: List[str] = []
    master_agent = None

    for a in agents_db:
        agent_ip = a.get("agent_ip")
        subnet = _agent_subnet_from_ip(agent_ip) if agent_ip else None
        role = (a.get("role") or "master").lower()
        is_online = a.get("agent_id") in online_agent_ids
        if subnet:
            other_subnets.append(subnet)
        in_subnet = _ip_in_subnet(device_ip, subnet) if subnet else False
        info = {
            "agent_id": a.get("agent_id"),
            "hostname": a.get("hostname"),
            "role": role,
            "agent_ip": agent_ip,
            "subnet": subnet,
            "online": is_online,
            "device_ip_in_subnet": in_subnet,
            "last_heartbeat_at": a.get("last_heartbeat_at"),
        }
        agents_info.append(info)
        if role == "master":
            master_agent = info
        if is_online and in_subnet:
            eligible.append(info)

    # Logica dispatcher REPLICATA da agent_ws._build_poller_config
    # 1) Se almeno un agent online ha device_ip in subnet → lui polla
    # 2) Altrimenti il MASTER del cliente prende il target come orfano
    dispatch_winner = None
    dispatch_reason = None
    if eligible:
        # Preferenza: master tra gli eligible, altrimenti il primo
        master_eligible = [e for e in eligible if e["role"] == "master"]
        dispatch_winner = master_eligible[0] if master_eligible else eligible[0]
        dispatch_reason = (
            f"Agent {dispatch_winner['hostname']} ha agent_ip "
            f"{dispatch_winner['agent_ip']} (subnet {dispatch_winner['subnet']}) "
            f"che contiene il device {device_ip} → SUBNET MATCH"
        )
    else:
        # Nessun agent online la cui subnet contenga device_ip.
        # Il master raccoglie gli orfani solo se ESISTE ed e' online.
        if master_agent and master_agent.get("online"):
            # Verifica che il target NON sia coperto da un'altra subnet
            # (regola della logica originale)
            covered = any(
                _ip_in_subnet(device_ip, s) for s in other_subnets
                if s != master_agent.get("subnet")
            )
            if not covered:
                dispatch_winner = master_agent
                dispatch_reason = (
                    f"Master {master_agent['hostname']} prende il target "
                    f"come ORFANO (nessun altro agent online con subnet "
                    f"matchante {device_ip})"
                )

    # Diagnosi finale
    issues: List[str] = []
    suggestions: List[str] = []

    if not md:
        return {
            "device_ip": device_ip, "client_id": client_id,
            "diagnosis": "🔴 Device non presente in managed_devices per questo client",
        }

    if md.get("disabled") is True or md.get("enabled") is False:
        issues.append("⚠️ Device disabilitato (managed_devices.enabled=False o disabled=True)")
        suggestions.append("Abilita il device dalla UI di gestione")

    age = _age_seconds(pd.get("last_poll") if pd else None)
    if age is None:
        issues.append("🔴 Mai un poll SNMP registrato (device_poll_status assente)")
    elif age > 600:
        issues.append(f"🟠 Ultimo poll SNMP {int(age/60)} minuti fa (>10min stale)")

    if not eligible and not dispatch_winner:
        issues.append(
            "🔴 NESSUN AGENT ONLINE ha una subnet che contiene questo device, "
            "e non c'e' un master online che possa fungere da fallback orfano"
        )
        # Suggerisci promozione a master o installazione agent nella subnet
        target_subnet = str(ipaddress.IPv4Network(f"{device_ip}/24", strict=False))
        offline_in_subnet = [a for a in agents_info
                             if a.get("subnet") and
                             _ip_in_subnet(device_ip, a["subnet"]) and
                             not a["online"]]
        if offline_in_subnet:
            suggestions.append(
                f"💡 Un agent nella subnet corretta esiste ma e' OFFLINE: "
                f"{', '.join(a['hostname'] for a in offline_in_subnet)}. "
                f"Verifica perche' non e' connesso (heartbeat, processo, rete)."
            )
        else:
            suggestions.append(
                f"💡 Installa un agent in subnet {target_subnet}, OPPURE "
                f"promuovi un agent esistente a role='master' "
                f"(via /api/admin/agents/{{agent_id}}/role)"
            )

    if not pd or not pd.get("sys_name"):
        suggestions.append(
            "💡 sys_name SNMP non popolato: verifica che la community SNMP "
            "configurata sul device sia corretta (UI Credenziali) e che "
            "le ACL SNMP del device permettano l'IP del connector."
        )

    diagnosis = " | ".join(issues) if issues else "✅ Pipeline OK"

    return {
        "device_ip": device_ip,
        "client_id": client_id,
        "device": md,
        "poll_status": pd,
        "last_poll_age_seconds": age,
        "agents": agents_info,
        "dispatch_winner": dispatch_winner,
        "dispatch_reason": dispatch_reason,
        "issues": issues,
        "suggestions": suggestions,
        "diagnosis": diagnosis,
    }


@router.post("/snmp-poll-now/{client_id}/{device_ip}")
async def snmp_poll_now(client_id: str, device_ip: str,
                        current_user: dict = Depends(get_current_user)):
    """Forza UN poll SNMP immediato per il device tramite l'agent online
    del cliente (preferenza master). Bypassa la subnet-dispatch logic per
    debug: il comando viene inviato DIRETTAMENTE al primo agent online.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    md = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip},
        {"_id": 0, "community": 1, "snmp_community": 1}
    )
    if not md:
        raise HTTPException(status_code=404, detail="Device non trovato")
    community = md.get("community") or md.get("snmp_community") or "public"

    candidates = [c for c in REGISTRY.list() if c.client_id == client_id]
    if not candidates:
        raise HTTPException(
            status_code=503,
            detail="Nessun agent online per questo client. Verifica che il connector sia connesso."
        )
    # Preferenza master
    chosen = None
    for c in candidates:
        ag = await db.managed_agents.find_one({"agent_id": c.agent_id}, {"_id": 0, "role": 1})
        if ag and (ag.get("role") or "master").lower() == "master":
            chosen = c
            break
    if not chosen:
        chosen = candidates[0]

    try:
        reply = await chosen.send_command(
            "force_snmp_poll",
            {"ip": device_ip, "community": community},
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timeout (15s) aspettando reply agent")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore invio comando: {e!r}")

    return {
        "ok": True,
        "device_ip": device_ip,
        "client_id": client_id,
        "executed_by_agent": chosen.agent_id,
        "reply": reply,
    }


@router.get("/agent-registry/{client_id}")
async def agent_registry(client_id: str,
                         current_user: dict = Depends(get_current_user)):
    """Lista TUTTO cio' che il backend sa sugli agent di un cliente:
      - token emessi (con created_at, revoked)
      - record managed_agents (anche storici, offline)
      - hello recenti dal audit_log

    Usato per capire: l'agent e' mai stato registrato? Quale token usa?
    Quando si e' connesso l'ultima volta? Senza dover frugare in DB.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "id": 1, "name": 1})
    tokens = await db.agent_tokens.find(
        {"client_id": client_id},
        {"_id": 0, "token": 0},  # MAI ritornare il token raw
    ).to_list(50)
    # Maschera token_hash
    for t in tokens:
        if "token_hash" in t:
            t["token_hash"] = (t["token_hash"][:8] + "...") if t["token_hash"] else None
    agents = await db.managed_agents.find(
        {"client_id": client_id},
        {"_id": 0},
    ).to_list(50)
    # Audit log recenti (hello/install)
    audit_recent: List[Dict[str, Any]] = []
    try:
        audit_recent = await db.audit_log.find(
            {"client_id": client_id,
             "$or": [{"action": {"$regex": "agent"}},
                     {"event": {"$regex": "agent"}}]},
            {"_id": 0},
        ).sort("created_at", -1).limit(20).to_list(20)
    except Exception:
        pass

    online_ids = {c.agent_id for c in REGISTRY.list() if c.client_id == client_id}
    for a in agents:
        a["is_online_now"] = a.get("agent_id") in online_ids
        a["last_heartbeat_age_seconds"] = _age_seconds(
            a.get("last_heartbeat_at") or a.get("last_seen_at"))

    diagnosis = []
    if not client:
        diagnosis.append("🔴 Client non esiste in `clients` collection")
    if not tokens:
        diagnosis.append(
            "🔴 NESSUN TOKEN agent emesso per questo cliente. "
            "Vai a POST /api/agents/register e crea un token, poi reinstalla "
            "l'agent sul server con quel token nuovo."
        )
    elif not agents:
        diagnosis.append(
            f"🟠 {len(tokens)} token emessi ma NESSUN agent ha mai fatto "
            f"hello al backend. L'installer e' stato lanciato sul server "
            f"target? Verifica con `Get-Service 86NocAgent` e "
            f"`Get-Content C:\\ProgramData\\86NocAgent\\logs\\agent.log -Tail 50`."
        )
    elif not online_ids:
        ages = [(a.get("hostname"), a.get("last_heartbeat_age_seconds"))
                for a in agents]
        oldest_min = min((x[1] for x in ages if x[1] is not None), default=None)
        if oldest_min is not None:
            diagnosis.append(
                f"🟠 Agent registrato in passato ma offline da "
                f"{int(oldest_min/60)} minuti. Sul server vai a "
                f"`Restart-Service 86NocAgent` e controlla i log."
            )

    return {
        "client": client,
        "tokens_count": len(tokens),
        "tokens": tokens,
        "agents_count": len(agents),
        "agents": agents,
        "online_now": len(online_ids),
        "audit_recent": audit_recent,
        "diagnosis": diagnosis,
    }
