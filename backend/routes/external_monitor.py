"""
External WAN Monitor - Monitoraggio esterno connettività clienti.
Ping ICMP + TCP Port Check verso IP pubblici di firewall e router.
Diagnosi automatica: problema ISP vs firewall vs router.
"""
import asyncio
import logging
import time
import socket
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from database import db
from deps import get_current_user, require_admin, audit_logger, check_nosql_injection, sanitize_string
from audit import AuditAction
import uuid

logger = logging.getLogger("external_monitor")
router = APIRouter(prefix="/api/external-monitor", tags=["external-monitor"])

# ==================== MODELS ====================

class WanTarget(BaseModel):
    client_id: str
    label: str  # "Firewall Zyxel", "Router Vodafone", etc.
    device_type: str  # "firewall" or "router"
    public_ip: str
    gateway_ip: Optional[str] = None  # Gateway ISP per diagnosi linea
    check_ports: list = [443]  # TCP ports to check
    check_ping: bool = False  # ICMP Echo (ping) check
    enabled: bool = True


class WanTargetUpdate(BaseModel):
    label: Optional[str] = None
    public_ip: Optional[str] = None
    gateway_ip: Optional[str] = None
    check_ports: Optional[list] = None
    check_ping: Optional[bool] = None
    enabled: Optional[bool] = None


class TestConnectionRequest(BaseModel):
    public_ip: str
    gateway_ip: Optional[str] = None
    check_ports: list = [443]
    check_ping: bool = False


# ==================== PROBE FUNCTIONS ====================

async def ping_host(ip: str, count: int = 3, timeout: int = 3) -> dict:
    """Ping ICMP verso un host usando SOCK_DGRAM (non richiede root/capabilities)."""
    import struct as _struct
    import os as _os

    successes = 0
    total_latency = 0.0

    for seq in range(count):
        try:
            loop = asyncio.get_event_loop()
            ok, latency = await asyncio.wait_for(
                loop.run_in_executor(None, _ping_once, ip, seq + 1, timeout),
                timeout=timeout + 1,
            )
            if ok:
                successes += 1
                total_latency += latency
        except (asyncio.TimeoutError, Exception):
            pass

    reachable = successes > 0
    packet_loss = round(((count - successes) / count) * 100, 1)
    avg_latency = round(total_latency / successes, 1) if successes > 0 else None

    return {
        "reachable": reachable,
        "latency_ms": avg_latency,
        "packet_loss_pct": packet_loss,
    }


def _ping_once(ip: str, seq: int, timeout: int = 3):
    """Single ICMP Echo Request using SOCK_DGRAM (unprivileged)."""
    import struct as _struct
    import os as _os

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
        s.settimeout(timeout)
        icmp_id = _os.getpid() & 0xFFFF

        # Build ICMP Echo Request: type=8, code=0
        header = _struct.pack('!BBHHH', 8, 0, 0, icmp_id, seq)
        data = b'ARGUS-NOC-PING!!'  # 16 bytes payload

        # Calculate checksum
        packet = header + data
        chk = 0
        for i in range(0, len(packet), 2):
            w = packet[i] + (packet[i + 1] << 8) if i + 1 < len(packet) else packet[i]
            chk += w
        chk = (chk >> 16) + (chk & 0xFFFF)
        chk = ~chk & 0xFFFF

        header = _struct.pack('!BBHHH', 8, 0, chk, icmp_id, seq)
        packet = header + data

        start = time.monotonic()
        s.sendto(packet, (ip, 0))
        s.recvfrom(1024)
        elapsed = round((time.monotonic() - start) * 1000, 1)
        s.close()
        return True, elapsed
    except socket.timeout:
        try:
            s.close()
        except Exception:
            pass
        return False, 0
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        return False, 0


async def check_tcp_port(ip: str, port: int, timeout: int = 3) -> dict:
    """Check TCP port connectivity."""
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        elapsed = round((time.monotonic() - start) * 1000, 1)
        writer.close()
        await writer.wait_closed()
        return {"port": port, "open": True, "response_ms": elapsed}
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return {"port": port, "open": False, "response_ms": None}
    except Exception:
        return {"port": port, "open": False, "response_ms": None}


async def probe_target(target: dict) -> dict:
    """Esegue tutti i check su un target WAN."""
    ip = target["public_ip"]
    ports = target.get("check_ports", [443])
    gateway_ip = target.get("gateway_ip")
    use_ping = target.get("check_ping", False)

    # Filter out non-numeric ports (legacy "icmp" entries)
    ports = [p for p in ports if isinstance(p, int) and p > 0]

    # Ping target + gateway in parallel
    tasks = [ping_host(ip)]
    if gateway_ip:
        tasks.append(ping_host(gateway_ip))

    ping_results = await asyncio.gather(*tasks, return_exceptions=True)
    ping_result = ping_results[0] if isinstance(ping_results[0], dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}
    gateway_ping = None
    if gateway_ip and len(ping_results) > 1:
        gateway_ping = ping_results[1] if isinstance(ping_results[1], dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}

    # TCP port checks (in parallel) — skip if no ports configured
    port_checks = []
    if ports:
        port_tasks = [check_tcp_port(ip, p) for p in ports]
        port_results = await asyncio.gather(*port_tasks, return_exceptions=True)
        for r in port_results:
            if isinstance(r, dict):
                port_checks.append(r)
            else:
                port_checks.append({"port": 0, "open": False, "response_ms": None})

    # Determine status
    any_port_open = any(p["open"] for p in port_checks) if port_checks else False

    if use_ping and not ports:
        # Ping-only mode: status depends entirely on ping
        status = "online" if ping_result["reachable"] else "offline"
    elif ping_result["reachable"] and (any_port_open or not ports):
        status = "online"
    elif ping_result["reachable"] and ports and not any_port_open:
        status = "degraded"  # Ping OK but services down
    elif not ping_result["reachable"] and any_port_open:
        status = "online"  # ICMP blocked but TCP works
    else:
        status = "offline"

    result = {
        "target_id": target["id"],
        "client_id": target["client_id"],
        "label": target["label"],
        "device_type": target["device_type"],
        "public_ip": ip,
        "status": status,
        "ping": ping_result,
        "ports": port_checks,
        "check_ping": use_ping,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if gateway_ip:
        result["gateway_ip"] = gateway_ip
        result["gateway_ping"] = gateway_ping
    return result


async def diagnose_client(client_id: str, results: list) -> dict:
    """Diagnosi automatica per un cliente basata sui risultati dei probe."""
    fw_results = [r for r in results if r["device_type"] == "firewall"]
    rt_results = [r for r in results if r["device_type"] == "router"]

    fw_online = any(r["status"] in ("online", "degraded") for r in fw_results) if fw_results else None
    rt_online = any(r["status"] in ("online", "degraded") for r in rt_results) if rt_results else None
    fw_reachable = any(r["ping"]["reachable"] or any(p.get("open") for p in r.get("ports", [])) for r in fw_results) if fw_results else None
    rt_reachable = any(r["ping"]["reachable"] or any(p.get("open") for p in r.get("ports", [])) for r in rt_results) if rt_results else None

    # Check gateway ISP status (from any target that has it)
    gateway_reachable = None
    gateway_ip = None
    for r in results:
        gw = r.get("gateway_ping")
        if gw is not None:
            gateway_ip = r.get("gateway_ip")
            if gw.get("reachable"):
                gateway_reachable = True
                break
            else:
                gateway_reachable = False

    # Diagnosi avanzata con gateway
    if fw_online and rt_online:
        diagnosis = "ok"
        diagnosis_text = "Connettivita' OK — Firewall e Router raggiungibili"
    elif fw_online is None and rt_online:
        diagnosis = "ok"
        diagnosis_text = "Connettivita' OK — Router raggiungibile"
    elif fw_online and rt_online is None:
        diagnosis = "ok"
        diagnosis_text = "Connettivita' OK — Firewall raggiungibile"
    elif not fw_reachable and not rt_reachable:
        if gateway_reachable is True:
            diagnosis = "router_down"
            diagnosis_text = f"ROUTER/FIREWALL DOWN — Linea ISP OK (gateway {gateway_ip} risponde) ma dispositivi non raggiungibili"
        elif gateway_reachable is False:
            diagnosis = "isp_down"
            diagnosis_text = f"LINEA ISP GIU' — Gateway ISP {gateway_ip} non risponde. Problema del provider"
        else:
            diagnosis = "isp_down"
            diagnosis_text = "LINEA INTERNET GIU' — Ne' Firewall ne' Router raggiungibili. Probabile problema ISP"
    elif not fw_reachable and rt_reachable:
        diagnosis = "firewall_down"
        diagnosis_text = "FIREWALL NON RAGGIUNGIBILE — Router OK. Problema sul Firewall"
    elif fw_reachable and not rt_reachable:
        diagnosis = "router_down"
        diagnosis_text = "ROUTER NON RAGGIUNGIBILE — Firewall OK. Problema sul Router"
    elif fw_reachable and not fw_online:
        diagnosis = "firewall_degraded"
        diagnosis_text = "FIREWALL DEGRADATO — Raggiungibile ma servizi non rispondono"
    elif rt_reachable and not rt_online:
        diagnosis = "router_degraded"
        diagnosis_text = "ROUTER DEGRADATO — Raggiungibile ma servizi non rispondono"
    else:
        diagnosis = "unknown"
        diagnosis_text = "Stato indeterminato — Controllare manualmente"

    result = {
        "client_id": client_id,
        "diagnosis": diagnosis,
        "diagnosis_text": diagnosis_text,
        "firewall_status": fw_results[0]["status"] if fw_results else "not_configured",
        "router_status": rt_results[0]["status"] if rt_results else "not_configured",
    }
    if gateway_reachable is not None:
        result["gateway_status"] = "online" if gateway_reachable else "offline"
        result["gateway_ip"] = gateway_ip
    return result


# ==================== BACKGROUND PROBE TASK ====================

_probe_task = None
_probe_running = False


async def run_probe_cycle():
    """Esegue un ciclo completo di probe su tutti i target attivi."""
    global _probe_running
    if _probe_running:
        return
    _probe_running = True
    try:
        targets = await db.wan_targets.find({"enabled": True}, {"_id": 0}).to_list(500)
        if not targets:
            return

        # Probe all targets in parallel (max 20 concurrent)
        semaphore = asyncio.Semaphore(20)

        async def bounded_probe(t):
            async with semaphore:
                return await probe_target(t)

        results = await asyncio.gather(*[bounded_probe(t) for t in targets], return_exceptions=True)

        # Store results and check for status changes
        now_iso = datetime.now(timezone.utc).isoformat()
        client_results = {}

        for r in results:
            if isinstance(r, Exception):
                continue
            tid = r["target_id"]
            cid = r["client_id"]
            if cid not in client_results:
                client_results[cid] = []
            client_results[cid].append(r)

            # Get previous status
            prev = await db.wan_probe_results.find_one({"target_id": tid}, {"_id": 0, "status": 1})
            prev_status = prev["status"] if prev else None

            # Store current result
            await db.wan_probe_results.update_one(
                {"target_id": tid},
                {"$set": r},
                upsert=True,
            )

            # Store history point (every 5 min only to save space)
            await db.wan_probe_history.insert_one({
                "target_id": tid,
                "client_id": cid,
                "status": r["status"],
                "latency_ms": r["ping"]["latency_ms"],
                "packet_loss_pct": r["ping"]["packet_loss_pct"],
                "timestamp": now_iso,
            })

            # Alert on status change
            if prev_status and prev_status != r["status"]:
                severity = "critical" if r["status"] == "offline" else "high" if r["status"] == "degraded" else "low"
                if r["status"] == "offline" or r["status"] == "degraded":
                    _ext_alert = {
                        "id": str(uuid.uuid4()),
                        "client_id": cid,
                        "device_id": tid,
                        "severity": severity,
                        "source_type": "external_monitor",
                        "title": f"WAN {r['label']}: {r['status'].upper()}",
                        "message": f"{r['label']} ({r['public_ip']}) non raggiungibile dall'esterno. Latenza: {r['ping']['latency_ms']}ms, Loss: {r['ping']['packet_loss_pct']}%",
                        "status": "active",
                        "created_at": now_iso,
                    }
                    await db.alerts.insert_one(_ext_alert)
                    try:
                        import webpush as _wp
                        await _wp.notify_new_alert(db, _ext_alert)
                    except Exception:
                        pass
                elif r["status"] == "online" and prev_status in ("offline", "degraded"):
                    # Auto-resolve previous alert
                    await db.alerts.update_many(
                        {"device_id": tid, "source_type": "external_monitor", "status": "active"},
                        {"$set": {"status": "resolved", "resolved_at": now_iso}},
                    )

        # Store per-client diagnosis
        for cid, res_list in client_results.items():
            diag = await diagnose_client(cid, res_list)
            await db.wan_client_diagnosis.update_one(
                {"client_id": cid},
                {"$set": {**diag, "updated_at": now_iso, "results": res_list}},
                upsert=True,
            )

    except Exception as e:
        logger.error(f"Probe cycle error: {e}")
    finally:
        _probe_running = False


async def start_probe_scheduler():
    """Avvia il ciclo di probe ogni 60 secondi con lock distribuito."""
    from middleware.task_coordinator import coordinator
    coordinator.schedule("wan_probe", run_probe_cycle, 60)
    logger.info("External WAN probe scheduler registered (interval: 60s)")


# ==================== API ENDPOINTS ====================

@router.on_event("startup")
async def startup():
    await start_probe_scheduler()


@router.get("/targets")
async def list_targets(client_id: str = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id
    targets = await db.wan_targets.find(query, {"_id": 0}).to_list(500)
    return {"targets": targets}


@router.post("/targets")
async def create_target(target: WanTarget, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    doc = {
        "id": str(uuid.uuid4()),
        **target.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user["email"],
    }
    await db.wan_targets.insert_one(doc)
    await audit_logger.log(
        AuditAction.CREATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        resource_type="wan_target", resource_id=doc["id"],
        details={"label": target.label, "ip": target.public_ip, "type": target.device_type},
    )
    return {"status": "ok", "target": {k: v for k, v in doc.items() if k != "_id"}}


@router.put("/targets/{target_id}")
async def update_target(target_id: str, update: WanTargetUpdate, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")
    result = await db.wan_targets.update_one({"id": target_id}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Target non trovato")
    return {"status": "ok"}


@router.delete("/targets/{target_id}")
async def delete_target(target_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.wan_targets.delete_one({"id": target_id})
    await db.wan_probe_results.delete_many({"target_id": target_id})
    return {"status": "ok"}


@router.get("/status")
async def get_all_status(current_user: dict = Depends(get_current_user)):
    """Stato attuale di tutti i target con diagnosi per cliente."""
    results = await db.wan_probe_results.find({}, {"_id": 0}).to_list(500)
    diagnoses = await db.wan_client_diagnosis.find({}, {"_id": 0}).to_list(100)

    # Enrich with client names
    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
    cmap = {c["id"]: c["name"] for c in clients}
    for d in diagnoses:
        d["client_name"] = cmap.get(d["client_id"], d["client_id"])
    for r in results:
        r["client_name"] = cmap.get(r["client_id"], r["client_id"])

    return {"results": results, "diagnoses": diagnoses}


@router.get("/status/{client_id}")
async def get_client_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Stato WAN per un singolo cliente."""
    results = await db.wan_probe_results.find({"client_id": client_id}, {"_id": 0}).to_list(50)
    diagnosis = await db.wan_client_diagnosis.find_one({"client_id": client_id}, {"_id": 0})
    return {"results": results, "diagnosis": diagnosis}


@router.post("/probe-now")
async def probe_now(current_user: dict = Depends(get_current_user)):
    """Forza un ciclo di probe immediato."""
    require_admin(current_user)
    asyncio.create_task(run_probe_cycle())
    return {"status": "ok", "message": "Probe avviato"}


@router.post("/test-connection")
async def test_connection(req: TestConnectionRequest, current_user: dict = Depends(get_current_user)):
    """Test rapido TCP + Ping su IP, porte e gateway ISP, senza salvare."""
    ip = req.public_ip.strip()
    ports = [p for p in req.check_ports if isinstance(p, int) and p > 0] if req.check_ports else []
    gateway_ip = req.gateway_ip.strip() if req.gateway_ip else None
    use_ping = req.check_ping

    # Build parallel tasks
    tasks = []
    # Ping target if check_ping enabled
    if use_ping:
        tasks.append(("ping", ping_host(ip, count=3, timeout=3)))
    # TCP port checks
    for p in ports:
        tasks.append(("tcp", check_tcp_port(ip, p, timeout=5)))
    # Gateway ping
    if gateway_ip:
        tasks.append(("gateway", ping_host(gateway_ip, count=2, timeout=3)))

    task_results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    ping_result = None
    port_checks = []
    gateway_result = None

    for i, (task_type, _) in enumerate(tasks):
        r = task_results[i]
        if task_type == "ping":
            ping_result = r if isinstance(r, dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}
        elif task_type == "tcp":
            if isinstance(r, dict):
                port_checks.append(r)
            else:
                port_checks.append({"port": 0, "open": False, "response_ms": None})
        elif task_type == "gateway":
            gateway_result = r if isinstance(r, dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}

    any_open = any(p["open"] for p in port_checks) if port_checks else False
    ping_ok = ping_result["reachable"] if ping_result else None
    gw_ok = gateway_result["reachable"] if gateway_result else None

    # Determine reachability
    reachable = any_open or (ping_ok is True)

    # Build summary
    parts = []
    if ping_result:
        parts.append(f"Ping ICMP: {'OK ({0}ms)'.format(ping_result.get('latency_ms', '?')) if ping_ok else 'NON RISPONDE'}")
    if gateway_result:
        parts.append(f"Gateway ISP: {'OK' if gw_ok else 'NON RAGGIUNGIBILE'}")
    if port_checks:
        parts.append(f"Porte: {sum(1 for p in port_checks if p['open'])}/{len(port_checks)} aperte")

    if reachable:
        summary = "Raggiungibile — " + ", ".join(parts)
    elif not reachable and gw_ok:
        summary = "Linea OK ma dispositivo non raggiungibile — " + ", ".join(parts)
    elif not reachable and gw_ok is False:
        summary = "Linea ISP down — " + ", ".join(parts)
    else:
        summary = "Non raggiungibile — " + ", ".join(parts)

    result = {
        "ip": ip,
        "ports": port_checks,
        "reachable": reachable,
        "summary": summary,
    }
    if ping_result:
        result["ping"] = ping_result
    if gateway_result:
        result["gateway"] = {
            "ip": gateway_ip,
            "reachable": gw_ok,
            "latency_ms": gateway_result.get("latency_ms"),
            "packet_loss_pct": gateway_result.get("packet_loss_pct"),
        }
    return result


@router.get("/history/{target_id}")
async def get_probe_history(target_id: str, hours: int = 24, current_user: dict = Depends(get_current_user)):
    """Storico latenza/loss per un target."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    history = await db.wan_probe_history.find(
        {"target_id": target_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)
    return {"history": history}
