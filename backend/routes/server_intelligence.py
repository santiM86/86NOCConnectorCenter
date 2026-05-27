"""
Server Intelligence Hub — Argus Center
======================================
Funzionalita' avanzate per la gestione server fisici e virtuali:

- FASE 1: iLO/Redfish auto-discovery + bulk credentials + IML/SEL events
- FASE 2: Hyper-V cluster & VM intelligence (via agent Go WMI collector)
- FASE 3: VMware vSphere/ESXi (via REST API vCenter)
- FASE 4: Server Health Score & Hardware Lifecycle Forecast

Endpoint base: /api/servers/
"""
import asyncio
import logging
import socket
import ssl
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import httpx

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger("server_intel")
router = APIRouter(prefix="/api/servers", tags=["server-intelligence"])

# ============================================================================
# FASE 1 — Auto-discovery vendor + credenziali default OEM
# ============================================================================

# Credenziali default per i principali vendor server.
# IMPORTANT: usato SOLO se l'utente abilita esplicitamente "Try default" (audit).
# Le aziende le cambiano sempre in produzione, ma molti server da poco riconfigurati
# le hanno ancora.
DEFAULT_OEM_CREDENTIALS = [
    # HP / HPE iLO
    {"vendor": "HP", "username": "Administrator", "password": "admin", "note": "HP iLO factory"},
    {"vendor": "HP", "username": "admin", "password": "admin", "note": "HP iLO older models"},
    # Dell iDRAC
    {"vendor": "Dell", "username": "root", "password": "calvin", "note": "Dell iDRAC factory (pre 14G)"},
    {"vendor": "Dell", "username": "root", "password": "Cal#NoMore", "note": "Dell iDRAC 14G+"},
    {"vendor": "Dell", "username": "admin", "password": "admin", "note": "Dell PowerEdge OME"},
    # Lenovo XCC
    {"vendor": "Lenovo", "username": "USERID", "password": "PASSW0RD", "note": "Lenovo XCC factory (cero in 'PASSW0RD')"},
    {"vendor": "Lenovo", "username": "admin", "password": "admin", "note": "Lenovo IMM/XCC"},
    # Fujitsu iRMC
    {"vendor": "Fujitsu", "username": "admin", "password": "admin", "note": "Fujitsu iRMC factory"},
    # Supermicro IPMI
    {"vendor": "Supermicro", "username": "ADMIN", "password": "ADMIN", "note": "Supermicro IPMI factory"},
    {"vendor": "Supermicro", "username": "ADMIN", "password": "Welcome1", "note": "Supermicro X11+"},
    # Cisco UCS / IMC
    {"vendor": "Cisco", "username": "admin", "password": "password", "note": "Cisco IMC factory"},
    # Generic
    {"vendor": "Generic", "username": "admin", "password": "password", "note": "Generic"},
    {"vendor": "Generic", "username": "admin", "password": "admin", "note": "Generic"},
]


async def _probe_redfish_vendor(ip: str, port: int = 443, timeout: float = 5.0) -> dict:
    """Probe anonimo a /redfish/v1/ — i server espongono Vendor/Product
    SENZA autenticazione. Usato per identificare l'OEM prima di tentare credenziali.

    Ritorna: {ok, vendor, product, redfish_version, service_tag, ...}
    """
    out = {"ip": ip, "ok": False, "vendor": None, "product": None}
    try:
        async with httpx.AsyncClient(verify=False, timeout=timeout) as cli:
            # /redfish/v1/ — il root e' anonymous per spec DMTF
            r = await cli.get(f"https://{ip}:{port}/redfish/v1/")
            if r.status_code in (200, 401):
                # 401 = serve auth ma vendor info nel JSON spesso disponibile
                try:
                    data = r.json()
                    out["redfish_version"] = data.get("RedfishVersion")
                    oem = data.get("Oem", {}) or {}
                    out["vendor"] = (
                        data.get("Vendor")
                        or list(oem.keys())[0] if oem else None
                    )
                    out["product"] = data.get("Product") or data.get("Name")
                    out["ok"] = True
                except Exception:
                    # Body non parsabile (auth required) ma server iLO esiste
                    out["ok"] = True
                    # Server header puo' dare hint sul vendor
                    srv = r.headers.get("Server", "")
                    if "HP" in srv or "HPE" in srv or "iLO" in srv:
                        out["vendor"] = "HP"
                    elif "iDRAC" in srv or "Dell" in srv:
                        out["vendor"] = "Dell"
                    elif "Supermicro" in srv:
                        out["vendor"] = "Supermicro"
                    elif "Lenovo" in srv or "XCC" in srv:
                        out["vendor"] = "Lenovo"
                    elif "Fujitsu" in srv or "iRMC" in srv:
                        out["vendor"] = "Fujitsu"
            return out
    except (httpx.ConnectError, httpx.TimeoutException, ssl.SSLError, socket.gaierror) as e:
        out["error"] = type(e).__name__
        return out
    except Exception as e:
        out["error"] = str(e)[:120]
        return out


@router.post("/probe-vendor")
async def probe_vendor(payload: dict, current_user: dict = Depends(get_current_user)):
    """Probe anonimo (no auth) /redfish/v1/ per identificare vendor server.
    Body: {ips: [list of IPs]} oppure {ip: str}
    """
    require_admin(current_user)
    ips = payload.get("ips") or ([payload.get("ip")] if payload.get("ip") else [])
    ips = [i for i in ips if i]
    if not ips:
        raise HTTPException(status_code=400, detail="ips/ip mancanti")
    if len(ips) > 50:
        raise HTTPException(status_code=400, detail="max 50 IP per probe")
    results = await asyncio.gather(*[_probe_redfish_vendor(ip) for ip in ips], return_exceptions=True)
    cleaned = []
    for r in results:
        if isinstance(r, Exception):
            cleaned.append({"ip": "?", "ok": False, "error": str(r)[:80]})
        else:
            cleaned.append(r)
    return {"probes": cleaned, "ok_count": sum(1 for r in cleaned if r.get("ok"))}


async def _try_credential(ip: str, username: str, password: str, port: int = 443, timeout: float = 6.0) -> dict:
    """Tenta una credenziale specifica contro /redfish/v1/Systems/. Ritorna OK
    se la response e' 200 (autenticato).
    """
    try:
        async with httpx.AsyncClient(verify=False, timeout=timeout) as cli:
            r = await cli.get(
                f"https://{ip}:{port}/redfish/v1/Systems/",
                auth=(username, password),
            )
            return {"ok": r.status_code == 200, "status": r.status_code, "username": username}
    except Exception as e:
        return {"ok": False, "username": username, "error": str(e)[:80]}


@router.post("/try-default-credentials")
async def try_default_credentials(payload: dict, current_user: dict = Depends(get_current_user)):
    """Tenta credenziali OEM di default per identificare server con cred mai cambiate.
    Body: {ip: str, vendor?: str ("HP"/"Dell"/...)}
    Ritorna la prima credenziale che funziona.
    AUDIT: ogni tentativo viene loggato.
    """
    require_admin(current_user)
    ip = (payload.get("ip") or "").strip()
    vendor_hint = (payload.get("vendor") or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="ip mancante")

    # Filtra credenziali per vendor se hint disponibile
    creds = DEFAULT_OEM_CREDENTIALS
    if vendor_hint:
        vh = vendor_hint.lower()
        prefer = [c for c in creds if c["vendor"].lower() == vh or c["vendor"] == "Generic"]
        if prefer:
            creds = prefer

    logger.info(f"try-default-creds ip={ip} vendor_hint={vendor_hint} by={current_user.get('email')} tries={len(creds)}")
    for c in creds:
        r = await _try_credential(ip, c["username"], c["password"])
        if r.get("ok"):
            logger.warning(
                f"DEFAULT-CRED-FOUND ip={ip} vendor={c['vendor']} "
                f"user={c['username']} note='{c['note']}' (server has factory credentials!)"
            )
            return {
                "ok": True,
                "ip": ip,
                "vendor": c["vendor"],
                "username": c["username"],
                "password": c["password"],  # ritornato SOLO per autocomplete bulk-credentials
                "note": c["note"],
                "security_warning": (
                    "ATTENZIONE: questo server risponde a credenziali OEM di default. "
                    "Cambiare immediatamente la password dopo la configurazione in Argus."
                ),
            }

    return {"ok": False, "ip": ip, "tried": len(creds), "message": "Nessuna credenziale di default ha funzionato"}


class BulkCredPayload(BaseModel):
    client_id: str
    ips: List[str]
    username: str
    password: str
    port: int = 443
    label: Optional[str] = None
    direct_poll: bool = True


@router.post("/bulk-credentials")
async def bulk_credentials(payload: BulkCredPayload, current_user: dict = Depends(get_current_user)):
    """Applica la stessa credenziale iLO/Redfish a N server in 1 click.
    Crea/aggiorna i record in `vault_credentials` con cifratura.
    """
    require_admin(current_user)
    if not payload.ips:
        raise HTTPException(status_code=400, detail="ips vuota")
    if len(payload.ips) > 50:
        raise HTTPException(status_code=400, detail="max 50 IP per bulk")

    # Import locale gia' fatto a livello modulo
    sm = security_manager
    if not sm:
        raise HTTPException(status_code=500, detail="security_manager non disponibile")

    now_iso = datetime.now(timezone.utc).isoformat()
    ok_ips, fail_ips = [], []
    for ip in payload.ips:
        try:
            cred_id = uuid.uuid4().hex
            doc = {
                "id": cred_id,
                "client_id": payload.client_id,
                "device_ip": ip,
                "device_name": payload.label or ip,
                "port": payload.port,
                "username_enc": sm.encrypt_credential(payload.username),
                "password_enc": sm.encrypt_credential(payload.password),
                "direct_poll": payload.direct_poll,
                "created_by": current_user.get("email"),
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            # Upsert by (client_id, device_ip)
            await db.vault_credentials.update_one(
                {"client_id": payload.client_id, "device_ip": ip},
                {"$set": doc},
                upsert=True,
            )
            ok_ips.append(ip)
        except Exception as e:
            fail_ips.append({"ip": ip, "error": str(e)[:120]})

    logger.info(f"bulk-credentials client={payload.client_id} ok={len(ok_ips)} fail={len(fail_ips)} by={current_user.get('email')}")
    return {
        "ok": True,
        "applied_count": len(ok_ips),
        "failed_count": len(fail_ips),
        "applied_ips": ok_ips,
        "failed_ips": fail_ips,
    }


# ============================================================================
# FASE 1 — IML / SEL events (LogService Redfish)
# ============================================================================

@router.get("/ilo-events/{device_ip}")
async def get_ilo_events(device_ip: str, limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Recupera IML (HP) / SEL (Dell/Lenovo) events dal log service Redfish.
    Mostra eventi hardware (PSU failed, fan replaced, memory error, BIOS update, ecc.)
    """
    require_admin(current_user)
    cred = await db.vault_credentials.find_one({"device_ip": device_ip}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Credenziali iLO non trovate per questo server")

    try:
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decrypt failed: {e}")

    port = cred.get("port") or 443
    base_url = cred.get("external_url", "").rstrip("/") or f"https://{device_ip}:{port}"
    auth = (username, password)
    events: list = []
    log_paths = [
        # HP iLO
        "/redfish/v1/Managers/1/LogServices/IML/Entries/",
        "/redfish/v1/Managers/1/LogServices/IEL/Entries/",
        # Dell iDRAC
        "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries/",
        "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Lclog/Entries/",
        # Lenovo XCC
        "/redfish/v1/Systems/1/LogServices/ActiveLog/Entries/",
        "/redfish/v1/Managers/1/LogServices/StandardLog/Entries/",
    ]
    used_path = None
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as cli:
            for path in log_paths:
                try:
                    r = await cli.get(f"{base_url}{path}?$top={limit}", auth=auth)
                except Exception:
                    continue
                if r.status_code == 200:
                    data = r.json()
                    members = data.get("Members", [])
                    used_path = path
                    for m in members[:limit]:
                        events.append({
                            "id": m.get("Id"),
                            "severity": (m.get("Severity") or "").lower(),
                            "created": m.get("Created"),
                            "subject": m.get("Subject") or m.get("EntryCode"),
                            "message": m.get("Message", "")[:400],
                            "sensor": m.get("SensorType"),
                        })
                    break
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore fetch eventi: {e}")

    return {
        "device_ip": device_ip,
        "log_path": used_path,
        "total_events": len(events),
        "events": events,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# FASE 2 — Hyper-V intelligence (via agent Go WMI)
# ============================================================================

@router.get("/hyperv/{client_id}")
async def get_hyperv_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Ritorna l'ultimo snapshot Hyper-V raccolto dall'agent Go via WMI.
    Snapshot atteso in `hyperv_snapshots`:
      {client_id, agent_id, hostname, host_info, vms[], cluster, csv[], replicas[]}
    """
    snap = await db.hyperv_snapshots.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("collected_at", -1).to_list(20)
    return {"client_id": client_id, "hosts": snap, "count": len(snap)}


@router.post("/hyperv/poll-now/{client_id}")
async def trigger_hyperv_poll(client_id: str, current_user: dict = Depends(get_current_user)):
    """Invia comando WS 'hyperv_collect' agli agent Windows v4 LIVE del cliente.
    L'agent risponde con snapshot WMI Hyper-V.
    """
    require_admin(current_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    agents = await db.managed_agents.find(
        {
            "client_id": client_id,
            "$or": [
                {"last_heartbeat_at": {"$gte": cutoff}},
                {"last_seen_at": {"$gte": cutoff}},
            ],
            "platform": {"$regex": "windows", "$options": "i"},
        },
        {"_id": 0, "agent_id": 1, "hostname": 1, "agent_version": 1},
    ).to_list(20)
    if not agents:
        raise HTTPException(status_code=503, detail="Nessun agent Windows LIVE per questo cliente")

    try:
        from routes.agent_ws import REGISTRY
    except ImportError:
        raise HTTPException(status_code=500, detail="agent_ws non disponibile")

    sent = 0
    for ag in agents:
        conn = REGISTRY.get(ag["agent_id"])
        if not conn:
            continue
        cmd_id = uuid.uuid4().hex
        asyncio.create_task(conn.send_command(
            "hyperv_collect",
            {"command_id": cmd_id, "client_id": client_id},
            timeout=60.0,
        ))
        sent += 1
    return {"ok": True, "sent_to": sent, "agents": [a["hostname"] for a in agents]}


@router.post("/hyperv/snapshot")
async def submit_hyperv_snapshot(payload: dict, request: Request):
    """Endpoint callback agent: salva snapshot Hyper-V raccolto via WMI.
    Auth via Bearer agent_token (no JWT user).
    Payload atteso: {agent_id, client_id, hostname, host_info, vms[], cluster, csv[], replicas[]}
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token mancante")
    tok = await db.agent_tokens.find_one({"token": token, "revoked": {"$ne": True}}, {"_id": 0})
    if not tok:
        cli = await db.clients.find_one({"api_key": token}, {"_id": 0, "id": 1})
        if not cli:
            raise HTTPException(status_code=401, detail="Token non valido")

    doc = dict(payload)
    doc["collected_at"] = datetime.now(timezone.utc).isoformat()
    # 1 snapshot per host (idempotent)
    await db.hyperv_snapshots.update_one(
        {"agent_id": doc.get("agent_id"), "hostname": doc.get("hostname")},
        {"$set": doc},
        upsert=True,
    )
    logger.info(f"hyperv_snapshot from agent={doc.get('agent_id','?')[:8]} host={doc.get('hostname')} vms={len(doc.get('vms', []))}")
    return {"ok": True}


# ============================================================================
# FASE 3 — VMware vSphere intelligence (via vCenter REST API)
# ============================================================================

class VCenterConfig(BaseModel):
    client_id: str
    vcenter_host: str  # IP o FQDN del vCenter
    username: str
    password: str
    port: int = 443
    verify_ssl: bool = False


@router.post("/vcenter/configure")
async def configure_vcenter(cfg: VCenterConfig, current_user: dict = Depends(get_current_user)):
    """Salva credenziali vCenter per un cliente (cifrate)."""
    require_admin(current_user)
    try:
        doc = {
            "id": uuid.uuid4().hex,
            "client_id": cfg.client_id,
            "vcenter_host": cfg.vcenter_host,
            "port": cfg.port,
            "username_enc": security_manager.encrypt_credential(cfg.username),
            "password_enc": security_manager.encrypt_credential(cfg.password),
            "verify_ssl": cfg.verify_ssl,
            "created_by": current_user.get("email"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.vcenter_configs.update_one(
            {"client_id": cfg.client_id, "vcenter_host": cfg.vcenter_host},
            {"$set": doc},
            upsert=True,
        )
        return {"ok": True, "vcenter_host": cfg.vcenter_host}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _vcenter_login(cfg: dict) -> dict:
    """Login vCenter REST API e ritorna session token."""
    username = security_manager.decrypt_credential(cfg["username_enc"])
    password = security_manager.decrypt_credential(cfg["password_enc"])
    host = cfg["vcenter_host"]
    port = cfg.get("port", 443)
    verify = cfg.get("verify_ssl", False)
    async with httpx.AsyncClient(verify=verify, timeout=15.0) as cli:
        r = await cli.post(
            f"https://{host}:{port}/api/session",
            auth=(username, password),
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"vCenter login fallito: {r.status_code} {r.text[:200]}")
        token = r.json() if isinstance(r.json(), str) else (r.json() or {}).get("value")
        return {"token": token, "host": host, "port": port, "verify": verify}


@router.post("/vcenter/poll-now/{client_id}")
async def vcenter_poll_now(client_id: str, current_user: dict = Depends(get_current_user)):
    """Pull dati live da tutti i vCenter configurati per il cliente:
    hosts, VMs, datastores, clusters. Salva in `vcenter_snapshots`.
    """
    require_admin(current_user)
    configs = await db.vcenter_configs.find({"client_id": client_id}, {"_id": 0}).to_list(20)
    if not configs:
        raise HTTPException(status_code=404, detail="Nessun vCenter configurato per questo cliente")

    results = []
    for cfg in configs:
        try:
            sess = await _vcenter_login(cfg)
            token = sess["token"]
            host = sess["host"]
            port = sess["port"]
            verify = sess["verify"]
            headers = {"vmware-api-session-id": token}
            async with httpx.AsyncClient(verify=verify, timeout=30.0, headers=headers) as cli:
                # Hosts
                rh = await cli.get(f"https://{host}:{port}/api/vcenter/host")
                hosts = rh.json() if rh.status_code == 200 else []
                # VMs (max 1000)
                rv = await cli.get(f"https://{host}:{port}/api/vcenter/vm")
                vms = rv.json() if rv.status_code == 200 else []
                # Datastores
                rd = await cli.get(f"https://{host}:{port}/api/vcenter/datastore")
                ds = rd.json() if rd.status_code == 200 else []
                # Clusters
                rc = await cli.get(f"https://{host}:{port}/api/vcenter/cluster")
                clusters = rc.json() if rc.status_code == 200 else []
                # Logout (best effort)
                try:
                    await cli.delete(f"https://{host}:{port}/api/session")
                except Exception:
                    pass

            snap = {
                "id": uuid.uuid4().hex,
                "client_id": client_id,
                "vcenter_host": host,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "hosts": hosts[:200],
                "vms": vms[:1000],
                "datastores": ds[:200],
                "clusters": clusters[:50],
                "counts": {
                    "hosts": len(hosts), "vms": len(vms),
                    "datastores": len(ds), "clusters": len(clusters),
                },
            }
            await db.vcenter_snapshots.update_one(
                {"client_id": client_id, "vcenter_host": host},
                {"$set": snap},
                upsert=True,
            )
            results.append({"vcenter_host": host, "ok": True, **snap["counts"]})
        except HTTPException:
            raise
        except Exception as e:
            results.append({"vcenter_host": cfg.get("vcenter_host"), "ok": False, "error": str(e)[:200]})
    return {"client_id": client_id, "results": results}


@router.get("/vcenter/{client_id}")
async def get_vcenter_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Ritorna gli ultimi snapshot vCenter per il cliente."""
    snaps = await db.vcenter_snapshots.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("collected_at", -1).to_list(10)
    configs = await db.vcenter_configs.find(
        {"client_id": client_id}, {"_id": 0, "username_enc": 0, "password_enc": 0}
    ).to_list(20)
    return {"client_id": client_id, "snapshots": snaps, "configs": configs}


# ============================================================================
# FASE 4 — Server Health Score & Hardware Lifecycle Forecast
# ============================================================================

def _compute_health_score(server: dict) -> dict:
    """Calcola un Health Score 0-100 per un server iLO basato su:
    - Health status globale (40%)
    - Sensori temp/fan/PSU (25%)
    - Dischi (20%)
    - Memoria/CPU (10%)
    - Firmware outdated (5%)
    Ritorna {score, grade, components, recommendation}
    """
    score = 100
    components = {}

    # 1. Health globale (40 punti)
    hs = (server.get("health_status") or "").lower()
    hg = {"ok": 40, "warning": 25, "critical": 5, "unknown": 20}.get(hs, 20)
    components["global_health"] = {"score": hg, "max": 40, "value": hs}
    score = (score - 40) + hg

    # 2. Sensori (25 punti)
    sens_score = 25
    temps = server.get("temperatures") or []
    crit_temps = [t for t in temps if (t.get("value") or 0) > 80]
    warn_temps = [t for t in temps if 70 <= (t.get("value") or 0) <= 80]
    if crit_temps:
        sens_score -= 15
    elif warn_temps:
        sens_score -= 7
    fans = server.get("fans") or []
    bad_fans = [f for f in fans if (f.get("health") or "").lower() not in ("ok", "")]
    if bad_fans:
        sens_score -= 10
    psus = server.get("power_supplies") or []
    bad_psus = [p for p in psus if (p.get("status") or "").lower() not in ("ok", "")]
    if bad_psus:
        sens_score -= 10
    sens_score = max(sens_score, 0)
    components["sensors"] = {"score": sens_score, "max": 25, "temps_critical": len(crit_temps), "fans_bad": len(bad_fans), "psus_bad": len(bad_psus)}
    score = (score - 25) + sens_score

    # 3. Dischi (20 punti)
    drives_score = 20
    drives = []
    for ctrl in (server.get("storage_controllers") or []):
        drives.extend(ctrl.get("drives") or [])
    bad_drives = [d for d in drives if (d.get("health") or "").lower() not in ("ok", "") or d.get("failure_predicted")]
    if bad_drives:
        drives_score -= min(len(bad_drives) * 5, 20)
    components["drives"] = {"score": drives_score, "max": 20, "bad": len(bad_drives), "total": len(drives)}
    score = (score - 20) + drives_score

    # 4. Memoria/CPU (10 punti)
    mem_score = 10
    dimms = server.get("memory_dimms") or []
    bad_dimms = [d for d in dimms if (d.get("health") or "").lower() not in ("ok", "")]
    if bad_dimms:
        mem_score -= min(len(bad_dimms) * 3, 10)
    components["memory"] = {"score": mem_score, "max": 10, "bad": len(bad_dimms), "total": len(dimms)}
    score = (score - 10) + mem_score

    # 5. Firmware (5 punti)
    fw_score = 5
    fw_compl = server.get("firmware_compliance") or {}
    if fw_compl.get("outdated_count", 0) > 0:
        fw_score -= min(fw_compl["outdated_count"], 5)
    components["firmware"] = {"score": fw_score, "max": 5, "outdated": fw_compl.get("outdated_count", 0)}
    score = (score - 5) + fw_score

    score = max(min(round(score), 100), 0)
    grade = (
        "A" if score >= 90 else
        "B" if score >= 75 else
        "C" if score >= 60 else
        "D" if score >= 40 else "F"
    )
    reco = []
    if bad_drives:
        reco.append(f"Sostituire {len(bad_drives)} disco/dischi degradati")
    if bad_fans:
        reco.append(f"Verificare {len(bad_fans)} ventola/e")
    if bad_psus:
        reco.append(f"Controllare {len(bad_psus)} alimentatore/i")
    if crit_temps:
        reco.append(f"Temperatura critica su {len(crit_temps)} sensore/i")
    if fw_compl.get("outdated_count", 0) > 0:
        reco.append(f"Aggiornare firmware ({fw_compl['outdated_count']} obsoleti)")
    if not reco:
        reco.append("Server in salute, nessuna azione richiesta")

    return {
        "score": score,
        "grade": grade,
        "components": components,
        "recommendations": reco,
    }


@router.get("/health-score/{client_id}")
async def client_health_scores(client_id: str, current_user: dict = Depends(get_current_user)):
    """Ritorna Health Score per tutti i server iLO del cliente.
    Score: 0-100, Grade A-F.
    """
    # Reuse i dati telemetria gia' raccolti dal Redfish poller
    creds = await db.vault_credentials.find(
        {"client_id": client_id}, {"_id": 0, "device_ip": 1, "device_name": 1},
    ).to_list(200)

    scores = []
    for c in creds:
        ip = c.get("device_ip")
        if not ip:
            continue
        tel = await db.redfish_telemetry.find_one({"device_ip": ip}, {"_id": 0})
        if not tel:
            continue
        score = _compute_health_score(tel)
        scores.append({
            "device_ip": ip,
            "device_name": c.get("device_name") or ip,
            "server_model": tel.get("server_model"),
            "last_poll_at": tel.get("last_poll_at"),
            **score,
        })

    # Aggregati cliente
    if scores:
        avg = round(sum(s["score"] for s in scores) / len(scores))
        grade_dist = {}
        for s in scores:
            grade_dist[s["grade"]] = grade_dist.get(s["grade"], 0) + 1
    else:
        avg, grade_dist = None, {}

    return {
        "client_id": client_id,
        "servers": scores,
        "avg_score": avg,
        "grade_distribution": grade_dist,
        "total_servers": len(scores),
    }


@router.get("/lifecycle/{client_id}")
async def hardware_lifecycle(client_id: str, current_user: dict = Depends(get_current_user)):
    """Hardware Lifecycle Forecast: età server, warranty, sostituzione consigliata."""
    creds = await db.vault_credentials.find(
        {"client_id": client_id}, {"_id": 0, "device_ip": 1, "device_name": 1},
    ).to_list(200)

    out = []
    for c in creds:
        ip = c.get("device_ip")
        if not ip:
            continue
        tel = await db.redfish_telemetry.find_one({"device_ip": ip}, {"_id": 0})
        if not tel:
            continue
        # Estimate age from serial / first_seen
        first_seen = tel.get("first_polled_at") or tel.get("created_at")
        age_days = None
        if first_seen:
            try:
                d = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - d).days
            except Exception:
                pass
        model = tel.get("server_model") or "Unknown"
        # Euristica lifecycle: 5 anni = warning, 7+ = end of life
        rec = "OK"
        if age_days and age_days > 365 * 7:
            rec = "END_OF_LIFE — sostituire entro 6 mesi"
        elif age_days and age_days > 365 * 5:
            rec = "WARNING — pianificare sostituzione entro 1 anno"
        elif age_days and age_days > 365 * 3:
            rec = "OK — periodica revisione contratto manutenzione"

        out.append({
            "device_ip": ip,
            "device_name": c.get("device_name") or ip,
            "server_model": model,
            "serial_number": tel.get("serial_number"),
            "first_seen_at": first_seen,
            "age_days": age_days,
            "age_years": round(age_days / 365.0, 1) if age_days else None,
            "recommendation": rec,
            "bios_version": tel.get("bios_version"),
            "ilo_firmware": tel.get("ilo_firmware"),
        })

    return {"client_id": client_id, "servers": out, "total": len(out)}
