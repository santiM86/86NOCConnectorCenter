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
from alert_filter import insert_alert_if_emit
import uuid

logger = logging.getLogger("external_monitor")


async def _auto_trace_on_wan_down(alert_id: str, client_id: str, public_ip: str, label: str) -> None:
    """v2026-06: alla caduta della WAN esegue un net_trace automatico verso l'IP
    pubblico del cliente (via sonda live) e lo ALLEGA all'alert (campo net_trace +
    riepilogo nel messaggio). Non blocca il ciclo di probe (gira in background)."""
    if not public_ip:
        return
    try:
        from routes.agent_ws import run_net_trace_via_probe
        res = await run_net_trace_via_probe(public_ip, client_id=client_id, mode="icmp")
    except Exception as e:  # noqa: BLE001
        logger.debug("auto-trace run failed for %s: %s", label, e)
        return
    if not res:
        logger.info("[auto-trace] nessuna sonda live disponibile per %s (%s)", label, public_ip)
        return
    hops = res.get("hops") or []
    reached = bool(res.get("reached"))
    tool = res.get("tool") or "?"
    # Arricchimento geo/ASN + verdetto automatico "di chi è la colpa"
    verdict = None
    try:
        from fault_attribution import attribute_fault
        hops = await _enrich_hops_geo(hops)
        verdict = attribute_fault(hops, reached, target=public_ip, is_client_target=True)
    except Exception as e:  # noqa: BLE001
        logger.debug("fault attribution failed: %s", e)
    last_ok, first_break = None, None
    for h in hops:
        if h.get("timeout") or (h.get("loss_pct") or 0) >= 100:
            if first_break is None:
                first_break = h.get("hop")
        else:
            last_ok = f"{h.get('hop')}. {h.get('ip') or h.get('host') or '?'}"
    lines = [f"🧭 Trace automatico ({tool}, {len(hops)} hop, {'raggiunta' if reached else 'NON raggiunta'})"]
    if last_ok:
        lines.append(f"Ultimo hop che risponde: {last_ok}")
    if first_break is not None and not reached:
        lines.append(f"Interruzione dall'hop {first_break} in poi → guasto a monte di quel punto")
    # Confronto con la BASELINE (trace "buono" di riferimento) per questa WAN
    baseline_diff = None
    try:
        bl = await db.wan_trace_baseline.find_one(
            {"client_id": client_id, "public_ip": public_ip}, {"_id": 0})
        if bl and bl.get("hops"):
            baseline_diff = _baseline_diff(bl.get("hops") or [], hops)
            if baseline_diff and baseline_diff.get("text"):
                lines.append("\U0001F4CD " + baseline_diff["text"]
                             + f" (baseline del {(bl.get('captured_at') or '')[:10]})")
    except Exception as e:  # noqa: BLE001
        logger.debug("baseline diff failed: %s", e)
    if verdict and verdict.get("blame") and verdict.get("blame") != "OK":
        lines.append(f"⚖️ COLPA: {verdict['blame']} — {verdict.get('verdict', '')}")
        # Correlazione outage ISP esterno (IODA/RIPEstat)
        try:
            from isp_outage import check_isp_outage
            asn = verdict.get("asn")
            isp_name = verdict.get("asn_name") or verdict.get("isp")
            country = None
            for h in reversed(hops):
                g = h.get("geo") or {}
                if g.get("country_code"):
                    country = g.get("country_code"); break
            if asn or country:
                ext = await check_isp_outage(asn=asn, isp_name=isp_name, country_code=country)
                verdict["external_outage"] = ext
                if ext.get("summary"):
                    lines.append(ext["summary"])
        except Exception as e:  # noqa: BLE001
            logger.debug("wan-down external outage correlation failed: %s", e)
    summary = "\n".join(lines)
    try:
        await db.alerts.update_one(
            {"id": alert_id},
            [{"$set": {
                "net_trace": {



                    "target": public_ip, "tool": tool, "reached": reached, "hops": hops,
                    "probe_agent_id": res.get("_probe_agent_id"),
                    "baseline_diff": baseline_diff,
                    "verdict": verdict,
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                },
                "message": {"$concat": [{"$ifNull": ["$message", ""]}, "\n\n", summary]},
            }}],
        )
        logger.info("[auto-trace] allegato all'alert %s (%s, %d hop, reached=%s)",
                    alert_id, tool, len(hops), reached)
    except Exception as e:  # noqa: BLE001
        logger.warning("auto-trace: update alert failed: %s", e)

def _hop_ip(h: dict) -> Optional[str]:
    if not h or h.get("timeout") or (h.get("loss_pct") or 0) >= 100:
        return None
    return h.get("ip") or h.get("host") or None


def _baseline_diff(baseline_hops: list, current_hops: list) -> Optional[dict]:
    """Confronta il trace corrente con la baseline e individua il PRIMO hop in cui
    il percorso è cambiato/interrotto. Ritorna {hop, kind, text, baseline_ip,
    current_ip} o None se identici."""
    bmap = {h.get("hop"): h for h in baseline_hops if h.get("hop") is not None}
    cmap = {h.get("hop"): h for h in current_hops if h.get("hop") is not None}
    max_hop = max([*bmap.keys(), *cmap.keys()], default=0)
    for n in range(1, max_hop + 1):
        b_ip = _hop_ip(bmap.get(n))
        c_ip = _hop_ip(cmap.get(n))
        if b_ip and not c_ip:
            return {"hop": n, "kind": "break", "baseline_ip": b_ip, "current_ip": None,
                    "text": f"Percorso INTERROTTO all'hop {n}: nel riferimento rispondeva {b_ip}, ora nessuna risposta → guasto tra l'hop {n-1} e l'hop {n}"}
        if b_ip and c_ip and b_ip != c_ip:
            return {"hop": n, "kind": "changed", "baseline_ip": b_ip, "current_ip": c_ip,
                    "text": f"Percorso CAMBIATO dall'hop {n}: era {b_ip} → ora {c_ip} (possibile reroute/failover a monte)"}
    return None


_baseline_last_capture_mono = 0.0
_BASELINE_MIN_GAP_S = 25.0          # al massimo una cattura ogni ~25s (globale)
_BASELINE_REFRESH_HOURS = 24        # rinnova la baseline se più vecchia di 24h


async def _maybe_capture_baseline(target_id: str, client_id: str, public_ip: str) -> None:
    """Cattura/rinnova la baseline (trace 'buono') quando la WAN è ONLINE, se manca
    o è più vecchia di 24h. Throttle globale per non sovraccaricare la sonda."""
    global _baseline_last_capture_mono
    if not public_ip:
        return
    import time as _t
    existing = await db.wan_trace_baseline.find_one(
        {"client_id": client_id, "public_ip": public_ip}, {"_id": 0, "captured_at": 1})
    if existing:
        cap = existing.get("captured_at") or ""
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cap)
            if age < timedelta(hours=_BASELINE_REFRESH_HOURS):
                return
        except Exception:
            pass
    now_mono = _t.monotonic()
    if now_mono - _baseline_last_capture_mono < _BASELINE_MIN_GAP_S:
        return
    _baseline_last_capture_mono = now_mono
    try:
        from routes.agent_ws import run_net_trace_via_probe
        res = await run_net_trace_via_probe(public_ip, client_id=client_id, mode="icmp")
    except Exception as e:  # noqa: BLE001
        logger.debug("baseline capture run failed for %s: %s", public_ip, e)
        return
    if not res or not (res.get("hops")):
        return
    await db.wan_trace_baseline.update_one(
        {"client_id": client_id, "public_ip": public_ip},
        {"$set": {
            "client_id": client_id, "target_id": target_id, "public_ip": public_ip,
            "tool": res.get("tool"), "reached": bool(res.get("reached")),
            "hops": res.get("hops"), "captured_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    logger.info("[baseline] trace di riferimento salvato per %s (%d hop)",
                public_ip, len(res.get("hops") or []))


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
    # Linea di BACKUP (opzionale) — monitorata solo in raggiungibilita' (ICMP +
    # gateway ISP), niente TCP. Serve a rilevare failover e doppio-down.
    backup_label: Optional[str] = None
    backup_public_ip: Optional[str] = None
    backup_gateway_ip: Optional[str] = None
    backup_enabled: bool = False
    # Collegamento manuale a un firewall Zyxel Nebula (dedup + arricchimento).
    linked_nebula_dev_id: Optional[str] = None
    linked_nebula_site_id: Optional[str] = None


class WanTargetUpdate(BaseModel):
    # v3.8.29: aggiunti client_id, device_type per consentire riassegnamento target
    # senza dover ricreare (utile per agganciare target orfani al cliente corretto).
    client_id: Optional[str] = None
    label: Optional[str] = None
    device_type: Optional[str] = None
    public_ip: Optional[str] = None
    gateway_ip: Optional[str] = None
    check_ports: Optional[list] = None
    check_ping: Optional[bool] = None
    enabled: Optional[bool] = None
    backup_label: Optional[str] = None
    backup_public_ip: Optional[str] = None
    backup_gateway_ip: Optional[str] = None
    backup_enabled: Optional[bool] = None
    # "" o dev_id: collega/scollega manualmente un firewall Nebula
    linked_nebula_dev_id: Optional[str] = None
    linked_nebula_site_id: Optional[str] = None


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


async def check_tcp_port(ip: str, port: int, timeout: int = 8) -> dict:
    """
    TCP probe con stati distinti (RFC 793 / nmap-like).

    Stati possibili:
      - "open"        → connect OK (SYN/ACK ricevuto)
      - "closed"      → RST esplicito (porta non in ascolto)
      - "filtered"    → timeout (firewall droppa silente, geo-IP, IPS)
      - "unreachable" → routing/network error (ENETUNREACH/EHOSTUNREACH)
      - "error"       → altro errore (DNS, SSL handshake, ecc.)

    v2026-02-13: prima ritornava sempre `open: False` per qualunque errore,
    causando falso "CLOSED" rosso quando in realta' il firewall del
    cliente droppa silenziosamente i probe (es. Zyxel USG con
    whitelist geo-IP/source: le connessioni accepted da IP autorizzati
    funzionano, ma il probe da Argus arriva da rete diversa → drop →
    timeout → falso closed). UI deve mostrare "FILTERED" giallo, NON
    "CLOSED" rosso.

    v2026-02-14:
      - Forzato IPv4 (AF_INET): nel container K8s lo stack IPv6 non e'
        sempre routable, evita falsi `unreachable` quando getaddrinfo
        ritorna AAAA prima di A.
      - Timeout default 6s → 8s: alcuni Zyxel/Fortinet WAN ad alto
        carico rispondono al SYN dopo 5-7s.
      - Aggiunto error_detail per debugging UI.
      - Risoluzione DNS esplicita: cosi' un host non risolto
        ritorna "error" con detail "DNS resolution failed" invece
        di un generico OSError fuorviante.
    """
    start = time.monotonic()
    last_exc_kind = None
    last_detail = None
    _ = start  # reserved per future telemetry (overall probe duration)

    # Esplicita risoluzione DNS in IPv4 (forziamo AF_INET).
    # Se ip e' gia' un literal IPv4, getaddrinfo lo ritorna immediato.
    target_ip = ip
    try:
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(ip, port, family=socket.AF_INET, type=socket.SOCK_STREAM),
            timeout=4,
        )
        if infos:
            target_ip = infos[0][4][0]
    except (socket.gaierror, asyncio.TimeoutError, OSError) as e:
        return {
            "port": port,
            "open": False,
            "status": "error",
            "response_ms": None,
            "error_detail": f"DNS resolution failed: {e}",
        }

    for attempt in range(2):  # 1 retry su timeout
        try:
            attempt_start = time.monotonic()
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(target_ip, port),
                timeout=timeout,
            )
            elapsed = round((time.monotonic() - attempt_start) * 1000, 1)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {
                "port": port,
                "open": True,
                "status": "open",
                "response_ms": elapsed,
                "resolved_ip": target_ip if target_ip != ip else None,
            }
        except asyncio.TimeoutError:
            last_exc_kind = "filtered"
            last_detail = f"TCP SYN timeout dopo {timeout}s (probabile firewall drop / geo-IP filter)"
            if attempt == 0:
                continue  # retry
        except ConnectionRefusedError:
            last_exc_kind = "closed"
            last_detail = "RST esplicito (porta non in ascolto sul server)"
            break
        except OSError as e:
            errno = getattr(e, "errno", None)
            # ENETUNREACH=101, EHOSTUNREACH=113, ECONNRESET=104
            if errno in (101, 113):
                last_exc_kind = "unreachable"
                last_detail = f"Network/host unreachable (errno={errno})"
            elif errno == 104:
                last_exc_kind = "closed"
                last_detail = "ECONNRESET (server ha chiuso bruscamente)"
            else:
                last_exc_kind = "error"
                last_detail = f"OSError errno={errno}: {e}"
            break
        except Exception as e:
            last_exc_kind = "error"
            last_detail = f"{type(e).__name__}: {e}"
            break

    return {
        "port": port,
        "open": False,
        "status": last_exc_kind or "error",
        "response_ms": None,
        "error_detail": last_detail,
        "resolved_ip": target_ip if target_ip != ip else None,
    }


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
    # v2026-02-14: distingui "filtered" (firewall drop silente) da "closed" reale.
    # Se nessuna porta open ma almeno una filtered → status filtered (non offline rosso).
    any_port_filtered = any(p.get("status") == "filtered" for p in port_checks) if port_checks else False
    any_port_closed = any(p.get("status") == "closed" for p in port_checks) if port_checks else False

    if use_ping and not ports:
        # Ping-only mode: status depends entirely on ping
        status = "online" if ping_result["reachable"] else "offline"
    elif ping_result["reachable"] and (any_port_open or not ports):
        status = "online"
    elif ping_result["reachable"] and ports and not any_port_open:
        # v2026-02-14-bis: se il ping risponde dal nostro IP, il device e' VIVO
        # e raggiungibile. Anche se la porta TCP risulta filtered o closed, lo
        # STATO GLOBALE resta ONLINE verde. Il dettaglio sulla porta (giallo
        # filtered / rosso closed) e' visibile a livello di porta singola, ma
        # non deve degradare il device che e' chiaramente raggiungibile.
        # Eccezione: se TUTTE le porte sono `closed` (RST esplicito) E nessuna
        # filtered, allora il device sta dicendo esplicitamente "il servizio non
        # c'e' piu'" → degraded (giallo, servizio davvero spento).
        if any_port_filtered or any_port_open:
            status = "online"  # firewall drop volontario, device vivo
        elif any_port_closed:
            status = "degraded"  # servizio spento ma device raggiungibile
        else:
            status = "online"
    elif not ping_result["reachable"] and any_port_open:
        status = "online"  # ICMP blocked but TCP works
    elif not ping_result["reachable"] and any_port_filtered and not any_port_closed:
        # No ping + tutto filtered: il device potrebbe esistere ma il firewall
        # blocca completamente i nostri probe. Lasciamo "filtered" giallo per
        # invitare l'operatore a verificare la whitelist.
        status = "filtered"
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

    # ---- Linea di BACKUP (opzionale): solo raggiungibilita' ICMP + gateway ----
    backup_ip = (target.get("backup_public_ip") or "").strip()
    backup_enabled = target.get("backup_enabled", False)
    if backup_ip and backup_enabled:
        b_gateway = (target.get("backup_gateway_ip") or "").strip() or None
        b_tasks = [ping_host(backup_ip)]
        if b_gateway:
            b_tasks.append(ping_host(b_gateway))
        b_res = await asyncio.gather(*b_tasks, return_exceptions=True)
        b_ping = b_res[0] if isinstance(b_res[0], dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}
        b_gw_ping = None
        if b_gateway and len(b_res) > 1:
            b_gw_ping = b_res[1] if isinstance(b_res[1], dict) else {"reachable": False, "latency_ms": None, "packet_loss_pct": 100}
        backup_status = "online" if b_ping.get("reachable") else "offline"
        result["backup"] = {
            "label": target.get("backup_label") or "Backup",
            "public_ip": backup_ip,
            "status": backup_status,
            "ping": b_ping,
            "gateway_ip": b_gateway,
            "gateway_ping": b_gw_ping,
        }

    # ---- Stato combinato linea primaria/backup (per failover detection) ----
    primary_reachable = ping_result.get("reachable") or any_port_open or (status in ("online", "degraded", "filtered"))
    if backup_ip and backup_enabled:
        backup_reachable = bool(result.get("backup", {}).get("ping", {}).get("reachable"))
        if primary_reachable:
            result["line_state"] = "ok"
        elif backup_reachable:
            result["line_state"] = "failover"
        else:
            result["line_state"] = "isolated"
    else:
        result["line_state"] = "no_backup"

    return result


async def diagnose_client(client_id: str, results: list) -> dict:
    """Diagnosi automatica per un cliente basata sui risultati dei probe."""
    fw_results = [r for r in results if r["device_type"] == "firewall"]
    rt_results = [r for r in results if r["device_type"] == "router"]

    # v2026-02-14: "filtered" e' uno stato valido di raggiungibilita' (device risponde
    # ma il firewall droppa silente i probe). Lo trattiamo come "online" per il calcolo
    # del raggiungibile, ma lo segnaliamo separatamente per la diagnosi.
    _online_states = ("online", "degraded", "filtered")
    fw_online = any(r["status"] in _online_states for r in fw_results) if fw_results else None
    rt_online = any(r["status"] in _online_states for r in rt_results) if rt_results else None
    fw_reachable = any(r["ping"]["reachable"] or any(p.get("open") for p in r.get("ports", [])) or r["status"] == "filtered" for r in fw_results) if fw_results else None
    rt_reachable = any(r["ping"]["reachable"] or any(p.get("open") for p in r.get("ports", [])) or r["status"] == "filtered" for r in rt_results) if rt_results else None

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
        wan_just_down_clients = set()  # clienti con un target appena passato a offline

        for r in results:
            if isinstance(r, Exception):
                continue
            tid = r["target_id"]
            cid = r["client_id"]
            if cid not in client_results:
                client_results[cid] = []
            client_results[cid].append(r)

            # Get previous status
            prev = await db.wan_probe_results.find_one({"target_id": tid}, {"_id": 0, "status": 1, "line_state": 1})
            prev_status = prev["status"] if prev else None
            prev_line_state = prev.get("line_state") if prev else None
            # v2026-06: cattura/rinnova la BASELINE (trace di riferimento) a WAN sana
            if r["status"] == "online" and r.get("public_ip"):
                asyncio.create_task(_maybe_capture_baseline(tid, cid, r.get("public_ip")))

            # Store current result
            await db.wan_probe_results.update_one(
                {"target_id": tid},
                {"$set": r},
                upsert=True,
            )

            # Store history point (every probe cycle, ~60s)
            # v2026-03-01: aggiunto `reachable` flat + `jitter_ms` per insights.
            ping_doc = r.get("ping", {}) or {}
            await db.wan_probe_history.insert_one({
                "target_id": tid,
                "client_id": cid,
                "status": r["status"],
                "reachable": bool(ping_doc.get("reachable")),
                "latency_ms": ping_doc.get("latency_ms"),
                "packet_loss_pct": ping_doc.get("packet_loss_pct"),
                "gateway_reachable": (r.get("gateway_ping") or {}).get("reachable") if r.get("gateway_ping") else None,
                "gateway_latency_ms": (r.get("gateway_ping") or {}).get("latency_ms") if r.get("gateway_ping") else None,
                "timestamp": now_iso,
            })

            # Public IP / ASN change detection
            try:
                await _detect_public_ip_change(tid, cid, r.get("public_ip"))
            except Exception as e:
                logger.debug(f"public_ip change detection failed for {tid}: {e}")

            # Alert on status change
            if prev_status and prev_status != r["status"]:
                severity = "critical" if r["status"] == "offline" else "high" if r["status"] == "degraded" else "low"
                if r["status"] == "offline" or r["status"] == "degraded":
                    if r["status"] == "offline" and prev_status in ("online", "degraded", "filtered"):
                        # transizione WAN → offline: candidato blackout (verifica agent dopo)
                        wan_just_down_clients.add(cid)
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
                    await insert_alert_if_emit(db, _ext_alert)
                    # v2026-06: trace automatico verso l'IP pubblico, allegato all'alert
                    if r["status"] == "offline" and prev_status in ("online", "degraded", "filtered"):
                        asyncio.create_task(_auto_trace_on_wan_down(
                            _ext_alert["id"], cid, r.get("public_ip"), r.get("label") or "WAN"))
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

            # ---- Alert FAILOVER / cliente ISOLATO (linea backup) ----
            line_state = r.get("line_state", "no_backup")
            if line_state in ("failover", "isolated") and line_state != prev_line_state:
                backup = r.get("backup", {}) or {}
                if line_state == "failover":
                    _line_alert = {
                        "id": str(uuid.uuid4()),
                        "client_id": cid,
                        "device_id": f"{tid}:line",
                        "severity": "high",
                        "source_type": "external_monitor_line",
                        "title": f"WAN {r['label']}: FAILOVER attivo",
                        "message": (
                            f"Linea PRIMARIA giu' ({r['public_ip']}). "
                            f"Backup OPERATIVO ({backup.get('public_ip','?')}). "
                            f"Il cliente e' online tramite linea di backup."
                        ),
                        "status": "active",
                        "created_at": now_iso,
                    }
                else:  # isolated
                    _line_alert = {
                        "id": str(uuid.uuid4()),
                        "client_id": cid,
                        "device_id": f"{tid}:line",
                        "severity": "critical",
                        "source_type": "external_monitor_line",
                        "title": f"WAN {r['label']}: CLIENTE ISOLATO",
                        "message": (
                            f"ENTRAMBE le linee giu' — primaria ({r['public_ip']}) "
                            f"e backup ({backup.get('public_ip','?')}) non raggiungibili. "
                            f"Cliente completamente offline."
                        ),
                        "status": "active",
                        "created_at": now_iso,
                    }
                await insert_alert_if_emit(db, _line_alert)
                try:
                    import webpush as _wp
                    await _wp.notify_new_alert(db, _line_alert)
                except Exception:
                    pass
            elif line_state == "ok" and prev_line_state in ("failover", "isolated"):
                # Linea primaria ripristinata → risolvi gli alert di linea
                await db.alerts.update_many(
                    {"device_id": f"{tid}:line", "source_type": "external_monitor_line", "status": "active"},
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
            # Confronto IP pubblico REALE (egress rilevato dagli agent) vs atteso
            try:
                expected_ips = {r.get("public_ip") for r in res_list if r.get("public_ip")}
                await _detect_wan_ip_change(cid, expected_ips)
            except Exception as e:
                logger.debug(f"detected wan ip change failed for {cid}: {e}")

        # v2026-06 SPEED: rilevazione blackout QUASI-LIVE. Se in questo ciclo la
        # WAN di un cliente e' appena passata a offline, non aspettiamo il tick da
        # 60s dell'Alert Engine: eseguiamo subito il watchdog blackout (che conferma
        # in modo indipendente agent-giu' + WAN-giu' e fa dedup/auto-recovery da solo).
        if wan_just_down_clients:
            try:
                import alert_engine as _ae
                cfg = await _ae.get_config(db)
                await _ae.run_site_blackout_watchdog(db, cfg)
                logger.info("[wan-probe] blackout watchdog triggered (event-driven) for %d client(s)", len(wan_just_down_clients))
            except Exception as e:  # noqa: BLE001
                logger.debug(f"event-driven blackout watchdog skipped: {e}")

    except Exception as e:
        logger.error(f"Probe cycle error: {e}")
    finally:
        _probe_running = False


async def start_probe_scheduler():
    """Avvia il ciclo di probe ogni 30 secondi con lock distribuito."""
    from middleware.task_coordinator import coordinator
    coordinator.schedule("wan_probe", run_probe_cycle, 30)
    # Early-warning: sorveglia gli outage DIFFUSI degli operatori dei clienti
    # (IODA/RIPEstat/Cloudflare) ogni 5 minuti e avvisa PRIMA che cada la linea.
    coordinator.schedule("isp_outage_watch", run_isp_outage_watch, 300)
    logger.info("External WAN probe scheduler registered (interval: 30s) + ISP outage watch (300s)")


_isp_watch_running = False


async def run_isp_outage_watch():
    """Rileva outage DIFFUSI sugli operatori (ASN) che servono i clienti e invia
    un alert Telegram PROATTIVO prima che la singola linea cada. Idempotente per
    ASN (stato in db.isp_outage_state) con auto-recovery."""
    global _isp_watch_running
    if _isp_watch_running:
        return
    _isp_watch_running = True
    try:
        from isp_outage import check_isp_outage, _asn_num
        targets = await db.wan_targets.find({"enabled": True}, {"_id": 0}).to_list(500)
        if not targets:
            return
        # 1) Raggruppa i clienti per ASN dell'operatore (via geo dell'IP pubblico)
        carriers: dict = {}
        for t in targets:
            ip = t.get("public_ip")
            cid = t.get("client_id")
            if not ip or not cid:
                continue
            try:
                geo = await _geoip_cached(ip)
            except Exception:
                geo = None
            asn = (geo or {}).get("asn")
            if not asn or _asn_num(asn) is None:
                continue
            key = f"AS{_asn_num(asn)}"
            entry = carriers.setdefault(key, {
                "asn": key, "isp_name": (geo or {}).get("asn_name") or (geo or {}).get("isp"),
                "country": (geo or {}).get("country_code"), "clients": {},
            })
            if cid not in entry["clients"]:
                c = await db.clients.find_one({"id": cid}, {"_id": 0, "name": 1})
                entry["clients"][cid] = {
                    "client_id": cid, "name": (c or {}).get("name") or cid,
                    "public_ip": ip, "label": t.get("label"),
                }
        if not carriers:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        # 2) Per ogni ASN: correla outage esterno + gestisci stato/alert/recovery
        for key, entry in carriers.items():
            try:
                ext = await check_isp_outage(asn=key, isp_name=entry["isp_name"],
                                             country_code=entry["country"])
            except Exception as e:  # noqa: BLE001
                logger.debug("isp_outage_watch check failed %s: %s", key, e)
                continue
            state = await db.isp_outage_state.find_one({"asn": key}, {"_id": 0})
            active = bool(state and state.get("active"))
            clients = list(entry["clients"].values())
            names = ", ".join(c["name"] for c in clients)
            if ext.get("widespread") and not active:
                # NUOVO outage diffuso → alert proattivo
                alert_id = str(uuid.uuid4())
                sev = "critical" if ext.get("bgp_withdrawn") or ext.get("national") else "high"
                title = f"OUTAGE OPERATORE {entry['isp_name'] or key} ({key})"
                msg = (f"⚠️ Guasto DIFFUSO rilevato sull'operatore {entry['isp_name'] or key} ({key}).\n"
                       f"{ext.get('summary', '')}\n"
                       f"Clienti potenzialmente impattati ({len(clients)}): {names}.\n"
                       f"➡️ Le linee di questi clienti potrebbero cadere a breve.")
                if ext.get("signals"):
                    msg += "\n\nSegnali: " + " | ".join(ext["signals"])
                dd = next((l["url"] for l in ext.get("external_links", []) if "downdetector" in l["url"].lower()), None)
                if dd:
                    msg += f"\nDowndetector: {dd}"
                alert_doc = {
                    "id": alert_id, "client_id": None, "severity": sev,
                    "source_type": "isp_outage_watch",
                    "title": title, "message": msg, "status": "active",
                    "created_at": now_iso, "isp_outage": ext,
                    "affected_clients": clients,
                }
                await insert_alert_if_emit(db, alert_doc)
                try:
                    from alert_engine import notify_alert_telegram
                    tg_doc = dict(alert_doc)
                    tg_doc["client_name"] = f"{entry['isp_name'] or key} — {len(clients)} clienti"
                    await notify_alert_telegram(db, tg_doc)
                except Exception as e:  # noqa: BLE001
                    logger.debug("isp_outage_watch telegram failed %s: %s", key, e)
                await db.isp_outage_state.update_one(
                    {"asn": key},
                    {"$set": {"asn": key, "isp_name": entry["isp_name"], "country": entry["country"],
                              "active": True, "alert_id": alert_id, "sources": ext.get("sources"),
                              "clients": clients, "first_seen": now_iso, "last_seen": now_iso}},
                    upsert=True)
                logger.warning("[isp-outage] NUOVO outage diffuso %s (%s) — %d clienti",
                               key, entry["isp_name"], len(clients))
            elif ext.get("widespread") and active:
                await db.isp_outage_state.update_one({"asn": key}, {"$set": {"last_seen": now_iso}})
            elif not ext.get("widespread") and active:
                # RECOVERY: outage rientrato
                await db.alerts.update_many(
                    {"source_type": "isp_outage_watch", "status": "active",
                     "isp_outage.asn": key},
                    {"$set": {"status": "resolved", "resolved_at": now_iso}})
                await db.isp_outage_state.update_one(
                    {"asn": key}, {"$set": {"active": False, "resolved_at": now_iso}})
                try:
                    from alert_engine import notify_alert_telegram
                    await notify_alert_telegram(db, {
                        "id": str(uuid.uuid4()), "client_id": None, "severity": "low",
                        "source_type": "isp_outage_watch",
                        "title": f"RIENTRO OUTAGE {entry['isp_name'] or key} ({key})",
                        "message": (f"✅ L'outage diffuso sull'operatore {entry['isp_name'] or key} ({key}) "
                                    f"risulta RIENTRATO dalle fonti esterne."),
                        "client_name": f"{entry['isp_name'] or key}",
                        "created_at": now_iso,
                    })
                except Exception:
                    pass
                logger.info("[isp-outage] outage %s rientrato", key)
        active_cnt = await db.isp_outage_state.count_documents({"active": True})
        logger.info("[isp-outage] watch completato: %d operatori controllati, %d outage diffusi attivi",
                    len(carriers), active_cnt)
    except Exception as e:  # noqa: BLE001
        logger.error("isp_outage_watch cycle error: %s", e)
    finally:
        _isp_watch_running = False


# ==================== API ENDPOINTS ====================

@router.on_event("startup")
async def startup():
    await start_probe_scheduler()


async def _attach_nebula(targets: list) -> list:
    """Arricchisce i target WAN collegati manualmente a un firewall Zyxel Nebula
    con i dati del dispositivo (modello, S/N, stato online, porte, metriche)."""
    dev_ids = [t.get("linked_nebula_dev_id") for t in targets if t.get("linked_nebula_dev_id")]
    if not dev_ids:
        return targets
    docs = await db.zyxel_devices.find(
        {"dev_id": {"$in": dev_ids}, "device_type": "firewall"},
        {"_id": 0, "dev_id": 1, "name": 1, "model": 1, "sn": 1, "mac": 1,
         "site_name": 1, "site_id": 1, "online_status": 1, "cpu_usage": 1,
         "mem_usage": 1, "sessions": 1, "ports": 1, "public_ip": 1, "firmware": 1},
    ).to_list(200)
    by_id = {d["dev_id"]: d for d in docs}
    for t in targets:
        d = by_id.get(t.get("linked_nebula_dev_id"))
        if not d:
            continue
        ports = d.get("ports") or []
        t["nebula"] = {
            "dev_id": d["dev_id"], "name": d.get("name"), "model": d.get("model"),
            "sn": d.get("sn"), "mac": d.get("mac"),
            "site_name": d.get("site_name") or d.get("site_id"),
            "online_status": d.get("online_status"),
            "cpu_usage": d.get("cpu_usage"), "mem_usage": d.get("mem_usage"),
            "sessions": d.get("sessions"), "mgmt_ip": d.get("public_ip"),
            "firmware": d.get("firmware"),
            "ports_total": len(ports),
            "ports_up": sum(1 for p in ports if p.get("status") == "up"),
        }
    return targets


@router.get("/targets")
async def list_targets(client_id: str = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id
    targets = await db.wan_targets.find(query, {"_id": 0}).to_list(500)
    targets = await _attach_nebula(targets)
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
    # Validate device_type if present
    if "device_type" in fields and fields["device_type"] not in ("firewall", "router"):
        raise HTTPException(status_code=400, detail="device_type deve essere 'firewall' o 'router'")
    # Validate client_id existence if reassigning
    if "client_id" in fields:
        cli = await db.clients.find_one({"id": fields["client_id"]}, {"_id": 0, "id": 1})
        if not cli:
            raise HTTPException(status_code=400, detail="Cliente non trovato")
    result = await db.wan_targets.update_one({"id": target_id}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Target non trovato")
    # If client_id changed, propagate to existing probe results so the per-client view picks them up immediately
    if "client_id" in fields:
        await db.wan_probe_results.update_many(
            {"target_id": target_id}, {"$set": {"client_id": fields["client_id"]}}
        )
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
    targets = await db.wan_targets.find({}, {"_id": 0}).to_list(500)
    results = await db.wan_probe_results.find({}, {"_id": 0}).to_list(500)
    diagnoses = await db.wan_client_diagnosis.find({}, {"_id": 0}).to_list(100)

    # Enrich with client names
    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
    cmap = {c["id"]: c["name"] for c in clients}
    for d in diagnoses:
        d["client_name"] = cmap.get(d["client_id"], d["client_id"])
    for r in results:
        r["client_name"] = cmap.get(r["client_id"], r["client_id"])
    for t in targets:
        t["client_name"] = cmap.get(t.get("client_id"), t.get("client_id"))
    targets = await _attach_nebula(targets)

    # v2026-02-14: include `targets` cosi' la WanTab di ClientOverviewPage
    # puo' filtrare per client_id (prima ricavava la lista solo da `results`
    # cosa che falliva quando il probe non aveva ancora girato — fix per
    # "WAN(0)" su Galvan nonostante il target fosse in DB).
    return {"targets": targets, "results": results, "diagnoses": diagnoses}


@router.get("/status/{client_id}")
async def get_client_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Stato WAN per un singolo cliente."""
    results = await db.wan_probe_results.find({"client_id": client_id}, {"_id": 0}).to_list(50)
    diagnosis = await db.wan_client_diagnosis.find_one({"client_id": client_id}, {"_id": 0})
    return {"results": results, "diagnosis": diagnosis}


class TcpProbeRequest(BaseModel):
    public_ip: Optional[str] = None
    client_id: Optional[str] = None
    port: int = 443
    count: int = 4


async def _resolve_detected_public_ip(client_id: str) -> Optional[dict]:
    """IP pubblico piu' recente rilevato dagli agent del cliente (WS source IP)."""
    doc = await db.managed_agents.find_one(
        {"client_id": client_id, "public_ip": {"$nin": [None, ""]}},
        {"_id": 0, "public_ip": 1, "public_ip_seen_at": 1, "hostname": 1},
        sort=[("public_ip_seen_at", -1)],
    )
    return doc or None


@router.get("/detected-public-ip/{client_id}")
async def detected_public_ip(client_id: str, current_user: dict = Depends(get_current_user)):
    """IP pubblico WAN auto-rilevato per un cliente (dalla connessione degli agent).

    Usato per pre-compilare il target nel Monitor WAN senza digitarlo a mano.
    """
    doc = await _resolve_detected_public_ip(client_id)
    if not doc:
        return {"public_ip": None}
    return {
        "public_ip": doc.get("public_ip"),
        "seen_at": doc.get("public_ip_seen_at"),
        "hostname": doc.get("hostname"),
    }


@router.post("/tcp-probe")
async def tcp_probe(req: TcpProbeRequest, current_user: dict = Depends(get_current_user)):
    """Sonda TCP "vista da fuori" verso l'IP pubblico del cliente.

    K8s blocca i socket raw ICMP/UDP: usiamo SOLO connessioni TCP
    (asyncio.open_connection) verso una porta (default 443), ripetute N volte,
    per misurare raggiungibilita', RTT medio e perdita. Un RST (porta chiusa) o
    un SYN/ACK (porta aperta) provano comunque che la WAN e' RAGGIUNGIBILE;
    timeout/unreachable = probabile linea giu' o packet loss.
    """
    require_admin(current_user)
    ip = (req.public_ip or "").strip()
    resolved_from = "manual"
    if not ip and req.client_id:
        doc = await _resolve_detected_public_ip(req.client_id)
        if doc:
            ip = (doc.get("public_ip") or "").strip()
            resolved_from = "auto-detected"
    if not ip:
        raise HTTPException(status_code=400, detail="Nessun IP pubblico (fornirlo o rilevarlo da un agent)")
    import ipaddress as _ip
    try:
        obj = _ip.ip_address(ip)
        if obj.is_private or obj.is_loopback or obj.is_reserved or obj.is_link_local:
            raise HTTPException(status_code=400, detail="L'IP non e' pubblico")
    except ValueError:
        raise HTTPException(status_code=400, detail="IP non valido")

    port = int(req.port or 443)
    count = min(max(int(req.count or 4), 1), 8)

    async def _connect_once() -> tuple:
        """(reachable, rtt_ms|None, status) con un singolo TCP connect breve.

        open  = SYN/ACK (porta aperta)   -> WAN raggiungibile
        closed= RST (ConnectionRefused)  -> WAN raggiungibile (host su, porta chiusa)
        filtered/down = timeout / errore rete -> perdita
        """
        t0 = time.monotonic()
        try:
            fut = asyncio.open_connection(ip, port)
            _, writer = await asyncio.wait_for(fut, timeout=3)
            rtt = round((time.monotonic() - t0) * 1000, 1)
            try:
                writer.close()
            except Exception:
                pass
            return True, rtt, "open"
        except asyncio.TimeoutError:
            return False, None, "filtered"
        except ConnectionRefusedError:
            return True, round((time.monotonic() - t0) * 1000, 1), "closed"
        except OSError:
            return False, None, "down"

    results = await asyncio.gather(*[_connect_once() for _ in range(count)])
    rtts = [r[1] for r in results if r[0] and r[1] is not None]
    reached = sum(1 for r in results if r[0])
    statuses = [r[2] for r in results]
    loss = round((count - reached) / count * 100, 1)
    avg = round(sum(rtts) / len(rtts), 1) if rtts else None
    if reached == 0:
        overall = "down"       # nessuna risposta TCP: WAN/ISP probabilmente giu'
    elif loss > 0:
        overall = "degraded"   # risposte parziali: packet loss / linea instabile
    else:
        overall = "ok"
    return {
        "public_ip": ip,
        "port": port,
        "count": count,
        "resolved_from": resolved_from,
        "reachable": reached > 0,
        "reached": reached,
        "packet_loss_pct": loss,
        "avg_rtt_ms": avg,
        "overall": overall,
        "statuses": statuses,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }



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
        tasks.append(("tcp", check_tcp_port(ip, p, timeout=8)))
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
    any_filtered = any(p.get("status") == "filtered" for p in port_checks) if port_checks else False
    ping_ok = ping_result["reachable"] if ping_result else None
    gw_ok = gateway_result["reachable"] if gateway_result else None

    # v2026-02-14-bis: se il ping risponde dal nostro IP, il device e' VIVO
    # e raggiungibile, anche se le porte TCP sono filtered (firewall drop
    # volontario). Il "reachable" globale deve riflettere il device, non la
    # singola porta.
    reachable = any_open or (ping_ok is True)

    # Build summary
    parts = []
    if ping_result:
        parts.append(f"Ping ICMP: {'OK ({0}ms)'.format(ping_result.get('latency_ms', '?')) if ping_ok else 'NON RISPONDE'}")
    if gateway_result:
        parts.append(f"Gateway ISP: {'OK' if gw_ok else 'NON RAGGIUNGIBILE'}")
    if port_checks:
        n_open = sum(1 for p in port_checks if p['open'])
        n_filtered = sum(1 for p in port_checks if p.get('status') == 'filtered')
        n_closed = sum(1 for p in port_checks if p.get('status') == 'closed')
        port_summary = f"Porte: {n_open}/{len(port_checks)} aperte"
        if n_filtered:
            port_summary += f", {n_filtered} filtered"
        if n_closed:
            port_summary += f", {n_closed} closed"
        parts.append(port_summary)

    if reachable and any_filtered and not any_open:
        # Device vivo (ping OK) ma porte tutte filtrate: messaggio positivo,
        # NON un warning. La porta puo' essere realmente aperta lato firewall
        # ma con whitelist sul nostro IP.
        summary = "Raggiungibile (ping OK) — porte filtrate dal firewall: " + ", ".join(parts)
    elif reachable:
        summary = "Raggiungibile — " + ", ".join(parts)
    elif any_filtered and not reachable:
        summary = "Filtrato dal firewall — Probabilmente vivo ma blocca probe esterni: " + ", ".join(parts)
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


@router.get("/insights/{target_id}")
async def get_target_insights(
    target_id: str, days: int = 30,
    current_user: dict = Depends(get_current_user),
):
    """Insight aggregati per target WAN: uptime %, jitter medio, sparkline 24h,
    SLA tracking, latenza min/max/avg/p95, periodi di down.

    v2026-02-14: clone delle metriche MSP enterprise (Datto, NinjaOne, Auvik).
    v2026-03-01: fix lettura history flat (era nested errata).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    history = await db.wan_probe_history.find(
        {"target_id": target_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("timestamp", 1).to_list(20000)

    def _is_online(h):
        # v2026-06: lo STATO ha priorità. "filtered"/"degraded"/"online" = firewall
        # RAGGIUNGIBILE (anche se droppa ICMP/TCP e reachable=False): NON è downtime.
        # Solo "offline" conta come giù ai fini SLA.
        status = (h.get("status") or "").lower()
        if status in ("online", "filtered", "degraded"):
            return True
        if status == "offline":
            return False
        # Nessuno stato salvato: fallback ai flag reachable
        if "reachable" in h:
            return bool(h.get("reachable"))
        nested = (h.get("ping") or {}).get("reachable")
        if nested is not None:
            return bool(nested)
        return False

    def _lat(h):
        if "latency_ms" in h:
            return h.get("latency_ms")
        return (h.get("ping") or {}).get("latency_ms")

    def _loss(h):
        if "packet_loss_pct" in h:
            return h.get("packet_loss_pct")
        return (h.get("ping") or {}).get("packet_loss_pct")

    if not history:
        return {
            "target_id": target_id, "days": days,
            "samples": 0, "uptime_pct": None, "sla_target": 99.9,
            "latency": {"avg": None, "min": None, "max": None, "p95": None, "jitter": None},
            "loss_pct_avg": None, "sparkline_24h": [], "down_periods": [],
            "uptime_today": None, "uptime_7d": None, "uptime_30d": None,
            "down_count": 0, "total_down_minutes": 0, "mttr_min": 0,
        }

    total = len(history)
    online = sum(1 for h in history if _is_online(h))
    uptime_pct = round(online * 100 / max(total, 1), 2)

    # Multi-window uptime: today, 7d, 30d
    now_dt = datetime.now(timezone.utc)
    cutoff_today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cutoff_7d = (now_dt - timedelta(days=7)).isoformat()
    cutoff_30d = (now_dt - timedelta(days=30)).isoformat()

    def _uptime_in(after_iso):
        bucket = [h for h in history if h.get("timestamp", "") >= after_iso]
        if not bucket:
            return None
        ok = sum(1 for h in bucket if _is_online(h))
        return round(ok * 100 / len(bucket), 2)

    uptime_today = _uptime_in(cutoff_today)
    uptime_7d = _uptime_in(cutoff_7d)
    uptime_30d = _uptime_in(cutoff_30d)

    # Latency stats
    latencies = [_lat(h) for h in history if _is_online(h) and _lat(h) is not None]
    latency_stats = {"avg": None, "min": None, "max": None, "p95": None, "jitter": None}
    if latencies:
        # Jitter PRIMA dell'ordinamento (deviazione tra sample consecutivi temporali)
        diffs = [abs(latencies[i] - latencies[i-1]) for i in range(1, len(latencies))]
        jitter = round(sum(diffs) / len(diffs), 1) if diffs else 0
        sorted_lat = sorted(latencies)
        avg = sum(sorted_lat) / len(sorted_lat)
        latency_stats = {
            "avg": round(avg, 1),
            "min": round(sorted_lat[0], 1),
            "max": round(sorted_lat[-1], 1),
            "p95": round(sorted_lat[min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)], 1),
            "jitter": jitter,
        }

    # Loss avg
    losses = [_loss(h) for h in history if _loss(h) is not None]
    loss_avg = round(sum(losses) / len(losses), 2) if losses else 0

    # Sparkline ultime 24h
    cutoff_24h = (now_dt - timedelta(hours=24)).isoformat()
    sparkline = []
    for h in history:
        if h.get("timestamp", "") < cutoff_24h:
            continue
        sparkline.append({
            "t": h.get("timestamp"),
            "latency": _lat(h),
            "loss": _loss(h),
            "online": _is_online(h),
        })

    # Down periods
    down_periods = []
    cur_start = None
    for h in history:
        ok = _is_online(h)
        ts = h.get("timestamp")
        if not ok and cur_start is None:
            cur_start = ts
        elif ok and cur_start is not None:
            try:
                d1 = datetime.fromisoformat(cur_start.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                duration_min = (d2 - d1).total_seconds() / 60.0
                if duration_min >= 1:
                    down_periods.append({
                        "start": cur_start, "end": ts,
                        "duration_min": round(duration_min, 1),
                    })
            except Exception:
                pass
            cur_start = None

    sla_target = 99.9
    n_down = len(down_periods)
    total_down_min = sum(p["duration_min"] for p in down_periods)

    return {
        "target_id": target_id,
        "days": days,
        "samples": total,
        "uptime_pct": uptime_pct,
        "uptime_today": uptime_today,
        "uptime_7d": uptime_7d,
        "uptime_30d": uptime_30d,
        "sla_target": sla_target,
        "sla_breach": uptime_pct < sla_target,
        "latency": latency_stats,
        "loss_pct_avg": loss_avg,
        "sparkline_24h": sparkline[-200:],
        "down_periods": down_periods[-10:],
        "down_count": n_down,
        "total_down_minutes": round(total_down_min, 1),
        "mttr_min": round(total_down_min / n_down, 1) if n_down else 0,
    }


# ==================== ADVANCED WAN INTELLIGENCE (v2026-03-01) ====================

async def _detect_public_ip_change(target_id: str, client_id: str, current_ip: str):
    """Rileva quando l'IP pubblico configurato per il target cambia (cambio ISP,
    fallover, riconfig DNS). Tiene storico in `wan_public_ip_changes`.
    """
    if not current_ip:
        return
    last = await db.wan_public_ip_changes.find_one(
        {"target_id": target_id},
        sort=[("changed_at", -1)],
        projection={"_id": 0},
    )
    if last and last.get("public_ip") == current_ip:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.wan_public_ip_changes.insert_one({
        "id": str(uuid.uuid4()),
        "target_id": target_id,
        "client_id": client_id,
        "public_ip": current_ip,
        "previous_ip": last.get("public_ip") if last else None,
        "changed_at": now_iso,
    })
    if last:
        # alert solo se NON e' il primo record (init)
        _alert = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_id": target_id,
            "severity": "high",
            "source_type": "wan_public_ip_change",
            "title": f"IP pubblico cambiato: {last.get('public_ip')} → {current_ip}",
            "message": f"L'IP pubblico del target WAN {target_id} e' cambiato. Probabile failover ISP, DHCP renew o riconfig manuale.",
            "status": "active",
            "created_at": now_iso,
        }
        try:
            await insert_alert_if_emit(db, _alert)
        except Exception:
            pass


async def _detect_wan_ip_change(client_id: str, expected_ips: set):
    """Confronta l'IP pubblico REALE del cliente (egress osservato dagli agent)
    con l'ultimo noto e con quelli attesi (target WAN configurati). Genera alert
    al cambio — utile per linee con IP dinamico e per rilevare failover ISP."""
    doc = await _resolve_detected_public_ip(client_id)
    detected = (doc or {}).get("public_ip")
    if not detected:
        return
    key = f"detected:{client_id}"
    last = await db.wan_public_ip_changes.find_one(
        {"target_id": key}, sort=[("changed_at", -1)], projection={"_id": 0},
    )
    if last and last.get("public_ip") == detected:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.wan_public_ip_changes.insert_one({
        "id": str(uuid.uuid4()),
        "target_id": key,
        "client_id": client_id,
        "public_ip": detected,
        "previous_ip": last.get("public_ip") if last else None,
        "detected": True,
        "changed_at": now_iso,
    })
    if last:  # niente alert al primo record (init)
        mismatch = bool(expected_ips) and detected not in expected_ips
        _alert = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_id": key,
            "severity": "high",
            "source_type": "wan_public_ip_change",
            "title": f"IP pubblico reale cambiato: {last.get('public_ip')} → {detected}",
            "message": (
                f"L'IP pubblico reale del cliente (rilevato dagli agent) è cambiato da "
                f"{last.get('public_ip')} a {detected}. Probabile IP dinamico rinnovato o failover ISP."
                + (f" NB: non corrisponde ad alcun IP atteso dei target WAN ({', '.join(sorted(x for x in expected_ips if x))})." if mismatch else "")
            ),
            "status": "active",
            "created_at": now_iso,
        }
        try:
            await insert_alert_if_emit(db, _alert)
            try:
                from alert_engine import notify_alert_telegram
                await notify_alert_telegram(db, _alert)
            except Exception:
                pass
        except Exception:
            pass


@router.get("/public-ip-history/{target_id}")
async def get_public_ip_history(target_id: str, limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Storico cambi IP pubblico del target."""
    hist = await db.wan_public_ip_changes.find(
        {"target_id": target_id}, {"_id": 0}
    ).sort("changed_at", -1).to_list(min(limit, 200))
    return {"target_id": target_id, "changes": hist, "count": len(hist)}


async def _fetch_geoip(ip: str) -> dict:
    """Lookup geo/ASN per un IP pubblico via ip-api.com (gratuito, 45 req/min)."""
    import aiohttp
    url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,asname,query"
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("status") == "success":
                    return {
                        "ip": ip,
                        "country": data.get("country"),
                        "country_code": data.get("countryCode"),
                        "region": data.get("regionName"),
                        "city": data.get("city"),
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "isp": data.get("isp"),
                        "org": data.get("org"),
                        "asn": data.get("as"),
                        "asn_name": data.get("asname"),
                    }
                return {"ip": ip, "error": data.get("message", "geoip lookup failed")}
    except Exception as e:
        return {"ip": ip, "error": str(e)}


@router.get("/geo-ip/{ip}")
async def get_geo_ip(ip: str, current_user: dict = Depends(get_current_user)):
    """Geo-IP + ISP/ASN lookup con cache TTL 30 giorni."""
    cached = await db.wan_geoip_cache.find_one({"ip": ip}, {"_id": 0})
    if cached and cached.get("cached_at"):
        try:
            cached_dt = datetime.fromisoformat(cached["cached_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - cached_dt) < timedelta(days=30):
                return {"cached": True, **{k: v for k, v in cached.items() if k != "cached_at"}}
        except Exception:
            pass
    info = await _fetch_geoip(ip)
    info["cached_at"] = datetime.now(timezone.utc).isoformat()
    await db.wan_geoip_cache.update_one({"ip": ip}, {"$set": info}, upsert=True)
    return {"cached": False, **{k: v for k, v in info.items() if k != "cached_at"}}


async def _geoip_cached(ip: str) -> dict:
    """Come get_geo_ip ma riusabile internamente (cache 30gg + fetch)."""
    cached = await db.wan_geoip_cache.find_one({"ip": ip}, {"_id": 0})
    if cached and cached.get("cached_at"):
        try:
            dt = datetime.fromisoformat(cached["cached_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - dt) < timedelta(days=30):
                return {k: v for k, v in cached.items() if k != "cached_at"}
        except Exception:
            pass
    info = await _fetch_geoip(ip)
    info["cached_at"] = datetime.now(timezone.utc).isoformat()
    await db.wan_geoip_cache.update_one({"ip": ip}, {"$set": info}, upsert=True)
    return {k: v for k, v in info.items() if k != "cached_at"}


async def _enrich_hops_geo(hops: list) -> list:
    """Arricchisce ogni hop pubblico con geo/ASN (campo `geo`)."""
    from fault_attribution import _is_private
    pub_ips = set()
    for h in (hops or []):
        ip = h.get("ip") or h.get("host")
        if ip and _is_private(ip) is False:
            pub_ips.add(ip)
    geo_map = {}
    for ip in pub_ips:
        try:
            geo_map[ip] = await _geoip_cached(ip)
        except Exception:
            geo_map[ip] = None
    for h in (hops or []):
        ip = h.get("ip") or h.get("host")
        if ip in geo_map:
            h["geo"] = geo_map[ip]
    return hops


class FaultDiagnoseRequest(BaseModel):
    client_id: str
    target: str                       # IP pubblico del cliente (destinazione principale)
    mode: str = "icmp"
    extra_anchors: Optional[list] = None  # default: 1.1.1.1, 8.8.8.8


@router.post("/fault-diagnose")
async def fault_diagnose(req: FaultDiagnoseRequest, current_user: dict = Depends(get_current_user)):
    """Kit prova disservizio ISP: esegue un traceroute multi-ancora via sonda
    (destinazione cliente + ancore pubbliche) e restituisce un VERDETTO automatico
    su "di chi è la colpa" (cliente / ISP-carrier / sito / sonda)."""
    from routes.agent_ws import run_net_trace_via_probe
    from fault_attribution import attribute_fault, combined_verdict

    target = (req.target or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target mancante")
    anchors = req.extra_anchors if req.extra_anchors is not None else ["1.1.1.1", "8.8.8.8"]
    plan = [(target, True)] + [(a, False) for a in anchors if a and a != target]

    async def _one(dst: str, is_client: bool):
        res = await run_net_trace_via_probe(dst, client_id=req.client_id, mode=req.mode)
        if not res:
            return None
        hops = await _enrich_hops_geo(res.get("hops") or [])
        reached = bool(res.get("reached"))
        verdict = attribute_fault(hops, reached, target=dst, is_client_target=is_client)
        return {
            "target": dst, "is_client": is_client, "tool": res.get("tool"),
            "reached": reached, "hops": hops, "verdict": verdict,
            "probe_agent_id": res.get("_probe_agent_id"),
            "probe_client_id": res.get("_probe_client_id"),
        }

    results = await asyncio.gather(*[_one(d, c) for d, c in plan])
    traces = [r for r in results if r]
    if not traces:
        raise HTTPException(status_code=503, detail="Nessuna sonda live disponibile per la diagnosi.")

    combined = combined_verdict(traces)
    # Correlazione OUTAGE ISP esterno (IODA/RIPEstat/Cloudflare) quando la colpa è
    # attribuita a un operatore o alla sede del cliente: conferma se diffuso o isolato.
    try:
        from isp_outage import check_isp_outage
        client_tr = next((t for t in traces if t.get("is_client")), traces[0])
        cv = client_tr.get("verdict") or {}
        asn = cv.get("asn")
        isp_name = cv.get("asn_name") or cv.get("isp")
        country = None
        for h in reversed(client_tr.get("hops") or []):
            g = h.get("geo") or {}
            if g.get("asn") and not asn:
                asn = g.get("asn"); isp_name = isp_name or g.get("asn_name") or g.get("isp")
            if g.get("country_code"):
                country = g.get("country_code"); break
        if not combined.get("blame") == "OK" and (asn or country):
            combined["external_outage"] = await check_isp_outage(asn=asn, isp_name=isp_name, country_code=country)
    except Exception as e:  # noqa: BLE001
        logger.debug("external outage correlation failed: %s", e)
    probe = next((t.get("probe_agent_id") for t in traces if t.get("probe_agent_id")), None)
    return {
        "target": target, "probe_agent_id": probe,
        "combined": combined, "traces": traces,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/outage-sources/status")
async def outage_sources_status(test: bool = True, current_user: dict = Depends(get_current_user)):
    """Stato delle fonti di correlazione OUTAGE ISP (IODA / RIPEstat / Cloudflare Radar).
    Con test=true esegue una verifica live rapida di ciascuna fonte."""
    import os as _os
    import aiohttp
    from isp_outage import _get_cf_token
    cf_tok = await _get_cf_token()
    cf_token = bool(cf_tok)
    cf_from_db = False
    try:
        _d = await db.settings.find_one({"key": "cloudflare_radar_token"}, {"_id": 0, "value": 1})
        cf_from_db = bool(_d and _d.get("value"))
    except Exception:
        cf_from_db = False
    cf_masked = ("…" + cf_tok[-4:]) if cf_tok and len(cf_tok) >= 4 else None
    if cf_token:
        cf_note = f"Token configurato ({'UI/DB' if cf_from_db else 'env'})" + (f" · {cf_masked}" if cf_masked else "")
    else:
        cf_note = "Token non configurato — inseriscilo qui sotto"
    sources = {
        "ioda": {"name": "IODA (Georgia Tech)", "kind": "BGP + active probing + darknet",
                 "requires_key": False, "enabled": True, "ok": None, "note": None},
        "ripestat": {"name": "RIPEstat (RIPE NCC)", "kind": "Stato annunci BGP dell'ASN",
                     "requires_key": False, "enabled": True, "ok": None, "note": None},
        "cloudflare": {"name": "Cloudflare Radar", "kind": "Annotazioni outage per ASN/Paese",
                       "requires_key": True, "enabled": cf_token, "ok": None,
                       "configured": cf_token, "source": ("db" if cf_from_db else ("env" if cf_token else None)),
                       "masked": cf_masked, "note": cf_note},
    }
    try:
        from downdetector import status_info as _dd_status
        dd_info = await _dd_status()
    except Exception:
        dd_info = {"configured": False, "source": None, "masked_client_id": None}
    sources["downdetector"] = {
        "name": "Downdetector Enterprise (Ookla)", "kind": "Segnalazioni utenti in tempo reale (crowdsourced)",
        "requires_key": True, "enabled": dd_info.get("configured", False), "ok": None,
        "configured": dd_info.get("configured", False), "source": dd_info.get("source"),
        "masked": dd_info.get("masked_client_id"),
        "note": (f"Credenziali configurate ({'UI/DB' if dd_info.get('source') == 'db' else 'env'})"
                 if dd_info.get("configured") else "A pagamento — inserisci Client ID + Secret qui sotto"),
    }
    if test:
        import time as _t
        now = int(_t.time())
        timeout = aiohttp.ClientTimeout(total=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                # IODA
                try:
                    async with s.get(f"https://api.ioda.inetintel.cc.gatech.edu/v2/outages/summary"
                                     f"?from={now-3600}&until={now}&entityType=asn&entityCode=3269") as r:
                        j = await r.json(content_type=None)
                        sources["ioda"]["ok"] = j.get("error") is None
                        sources["ioda"]["note"] = "Raggiungibile" if j.get("error") is None else str(j.get("error"))
                except Exception as e:  # noqa: BLE001
                    sources["ioda"]["ok"] = False; sources["ioda"]["note"] = str(e)
                # RIPEstat
                try:
                    async with s.get("https://stat.ripe.net/data/as-overview/data.json?resource=AS3269") as r:
                        j = await r.json(content_type=None)
                        ok = bool(j.get("data"))
                        sources["ripestat"]["ok"] = ok
                        sources["ripestat"]["note"] = "Raggiungibile" if ok else "Risposta inattesa"
                except Exception as e:  # noqa: BLE001
                    sources["ripestat"]["ok"] = False; sources["ripestat"]["note"] = str(e)
                # Cloudflare (solo se token presente)
                if cf_token:
                    try:
                        async with s.get("https://api.cloudflare.com/client/v4/radar/annotations/outages?limit=1&dateRange=7d&format=json",
                                         headers={"Authorization": f"Bearer {cf_tok}"}) as r:
                            j = await r.json(content_type=None)
                            ok = bool(j.get("success"))
                            sources["cloudflare"]["ok"] = ok
                            sources["cloudflare"]["note"] = "Token valido — API raggiungibile" if ok else (str(j.get("errors")) or "Token non valido")
                    except Exception as e:  # noqa: BLE001
                        sources["cloudflare"]["ok"] = False; sources["cloudflare"]["note"] = str(e)
        except Exception as e:  # noqa: BLE001
            logger.debug("outage-sources status test failed: %s", e)
        # Downdetector live test (client httpx separato)
        if sources["downdetector"]["configured"]:
            try:
                from downdetector import check_downdetector
                dd = await check_downdetector("Telecom Italia", "IT")
                sources["downdetector"]["ok"] = bool(dd.get("ok")) and dd.get("error") is None
                sources["downdetector"]["note"] = ("Credenziali valide — API raggiungibile"
                                                   if sources["downdetector"]["ok"]
                                                   else (dd.get("error") or "Errore autenticazione"))
            except Exception as e:  # noqa: BLE001
                sources["downdetector"]["ok"] = False; sources["downdetector"]["note"] = str(e)

    active = await db.isp_outage_state.count_documents({"active": True})
    last = await db.isp_outage_state.find_one({}, {"_id": 0, "last_seen": 1}, sort=[("last_seen", -1)])
    return {
        "sources": sources,
        "active_outages": active,
        "last_checked": (last or {}).get("last_seen"),
        "watch_interval_sec": 300,
    }


@router.post("/outage-sources/test")
async def outage_sources_test(asn: str = "AS3269", current_user: dict = Depends(get_current_user)):
    """Esegue una correlazione outage di prova su un ASN (default AS3269 Telecom
    Italia) per dimostrare dal vivo l'output combinato delle fonti."""
    from isp_outage import check_isp_outage
    country = None
    if asn and asn.upper().startswith("AS"):
        # geo dell'ASN non disponibile qui; lascia country a IODA/CF senza filtro Paese
        country = "IT"
    res = await check_isp_outage(asn=asn, isp_name=None, country_code=country)
    return res


class CloudflareTokenRequest(BaseModel):
    token: str


@router.put("/outage-sources/cloudflare-token")
async def set_cloudflare_token(req: CloudflareTokenRequest, current_user: dict = Depends(get_current_user)):
    """Salva (cifrato AES-256-GCM) il token Cloudflare Radar in db.settings."""
    require_admin(current_user)
    from security import security_manager
    tok = (req.token or "").strip()
    if len(tok) < 20:
        raise HTTPException(status_code=400, detail="Token non valido (troppo corto)")
    # test rapido di validità prima di salvare
    import aiohttp
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get("https://api.cloudflare.com/client/v4/radar/annotations/outages?limit=1&dateRange=7d&format=json",
                             headers={"Authorization": f"Bearer {tok}"}) as r:
                j = await r.json(content_type=None)
                if not j.get("success"):
                    raise HTTPException(status_code=400,
                                        detail="Token rifiutato da Cloudflare (verifica permesso Account > Radar > Read)")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Impossibile verificare il token: {e}")
    encrypted = security_manager.encrypt_credential(tok)
    await db.settings.update_one(
        {"key": "cloudflare_radar_token"},
        {"$set": {"key": "cloudflare_radar_token", "value": encrypted,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True, "masked": "…" + tok[-4:]}


@router.delete("/outage-sources/cloudflare-token")
async def delete_cloudflare_token(current_user: dict = Depends(get_current_user)):
    """Rimuove il token Cloudflare Radar dal DB (resta l'eventuale env)."""
    require_admin(current_user)
    await db.settings.delete_one({"key": "cloudflare_radar_token"})
    return {"ok": True}


class DowndetectorCredsRequest(BaseModel):
    client_id: str
    client_secret: str


@router.put("/outage-sources/downdetector-creds")
async def set_downdetector_creds(req: DowndetectorCredsRequest, current_user: dict = Depends(get_current_user)):
    """Salva (cifrate) le credenziali Downdetector Enterprise e le verifica."""
    require_admin(current_user)
    from security import security_manager
    cid = (req.client_id or "").strip()
    csec = (req.client_secret or "").strip()
    if len(cid) < 6 or len(csec) < 6:
        raise HTTPException(status_code=400, detail="Client ID / Secret non validi")
    # verifica: prova a ottenere un token OAuth2
    import httpx
    base = _os_env("DD_BASE_URL", "https://downdetectorapi.com/v2").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=12.0) as c:
            r = await c.post(f"{base}/tokens", params={"grant_type": "client_credentials"},
                             auth=(cid, csec), headers={"Accept": "application/json"})
            if r.status_code != 200 or not r.json().get("access_token"):
                raise HTTPException(status_code=400, detail="Credenziali rifiutate da Downdetector (verifica Client ID/Secret e piano attivo)")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Impossibile verificare le credenziali: {e}")
    await db.settings.update_one({"key": "downdetector_client_id"},
        {"$set": {"key": "downdetector_client_id", "value": security_manager.encrypt_credential(cid),
                  "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    await db.settings.update_one({"key": "downdetector_client_secret"},
        {"$set": {"key": "downdetector_client_secret", "value": security_manager.encrypt_credential(csec),
                  "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return {"ok": True, "masked_client_id": "…" + cid[-4:]}


@router.delete("/outage-sources/downdetector-creds")
async def delete_downdetector_creds(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.settings.delete_many({"key": {"$in": ["downdetector_client_id", "downdetector_client_secret"]}})
    return {"ok": True}


def _os_env(k, d=None):
    import os as _o
    return _o.environ.get(k, d)


async def _resolve_dns(server: str, hostname: str, timeout: float = 3.0) -> dict:
    """Esegue una query DNS A verso `server` per `hostname`. Misura latenza."""
    import struct as _struct
    import random as _random

    def _query():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            txid = _random.randint(0, 0xFFFF)
            # DNS header: id, flags=0x0100 (standard query rec), qdcount=1
            header = _struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
            # QNAME
            qname = b""
            for part in hostname.split("."):
                qname += bytes([len(part)]) + part.encode("ascii")
            qname += b"\x00"
            question = qname + _struct.pack(">HH", 1, 1)  # type A, class IN
            packet = header + question
            t0 = time.monotonic()
            s.sendto(packet, (server, 53))
            data, _ = s.recvfrom(512)
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            s.close()
            # parse simple: ancount in header at offset 6
            ancount = _struct.unpack(">H", data[6:8])[0]
            return {"server": server, "hostname": hostname, "ok": ancount > 0, "answers": ancount, "latency_ms": elapsed}
        except (socket.timeout, OSError) as e:
            return {"server": server, "hostname": hostname, "ok": False, "answers": 0, "latency_ms": None, "error": str(e)}

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _query), timeout=timeout + 1)
    except asyncio.TimeoutError:
        return {"server": server, "hostname": hostname, "ok": False, "answers": 0, "latency_ms": None, "error": "timeout"}


@router.get("/dns-health/{target_id}")
async def dns_health_check(target_id: str, current_user: dict = Depends(get_current_user)):
    """Salute DNS — test risoluzione su 8.8.8.8, 1.1.1.1, gateway ISP, 9.9.9.9.
    Misura latenza UDP DNS verso ciascun resolver.
    """
    target = await db.wan_targets.find_one({"id": target_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Target non trovato")

    servers = [
        {"name": "Google DNS", "ip": "8.8.8.8"},
        {"name": "Cloudflare", "ip": "1.1.1.1"},
        {"name": "Quad9", "ip": "9.9.9.9"},
    ]
    gw = target.get("gateway_ip")
    if gw:
        servers.insert(0, {"name": "Gateway ISP", "ip": gw})

    # query target: google.com (standard probe)
    hostnames = ["google.com", "microsoft.com"]
    results = []
    for srv in servers:
        per_hostname = []
        for host in hostnames:
            r = await _resolve_dns(srv["ip"], host)
            per_hostname.append(r)
        avg_lat = [x["latency_ms"] for x in per_hostname if x.get("latency_ms") is not None]
        all_ok = all(x.get("ok") for x in per_hostname)
        results.append({
            "name": srv["name"],
            "ip": srv["ip"],
            "ok": all_ok,
            "latency_ms": round(sum(avg_lat) / len(avg_lat), 1) if avg_lat else None,
            "queries": per_hostname,
        })
    healthy = sum(1 for r in results if r["ok"])
    return {
        "target_id": target_id,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"healthy_resolvers": healthy, "total_resolvers": len(results), "all_ok": healthy == len(results)},
        "resolvers": results,
    }


@router.post("/speedtest/{client_id}")
async def trigger_speedtest(client_id: str, current_user: dict = Depends(get_current_user)):
    """Trigger speedtest via primo agent v4 master LIVE del cliente.
    Salva il risultato (download Mbps, upload Mbps, ping ms, jitter ms, isp,
    server) in `wan_speedtest_history`.
    Richiede agent v4.18+ con comando WS `speedtest`.
    """
    require_admin(current_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    agent = await db.managed_agents.find_one(
        {
            "client_id": client_id,
            "$or": [
                {"last_heartbeat_at": {"$gte": cutoff}},
                {"last_seen_at": {"$gte": cutoff}},
            ],
            "labels.role": "master",
        },
        {"_id": 0, "agent_id": 1, "hostname": 1, "agent_version": 1, "version": 1},
    )
    if not agent:
        # fallback: qualsiasi master live
        agent = await db.managed_agents.find_one(
            {"client_id": client_id, "$or": [
                {"last_heartbeat_at": {"$gte": cutoff}},
                {"last_seen_at": {"$gte": cutoff}},
            ]},
            {"_id": 0, "agent_id": 1, "hostname": 1, "agent_version": 1, "version": 1},
        )
    if not agent:
        raise HTTPException(status_code=503, detail="Nessun agent v4 LIVE per questo cliente. Speedtest richiede un connector attivo.")

    agent_id = agent.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=500, detail="agent senza agent_id in DB (record corrotto)")
    agent_version = agent.get("agent_version") or agent.get("version")

    # Invio comando WS speedtest via REGISTRY
    try:
        from routes.agent_ws import REGISTRY
        conn = REGISTRY.get(agent_id)
        if conn is None:
            raise HTTPException(status_code=503, detail=f"Agent {agent.get('hostname')} non connesso al WS (id={agent_id[:8]}…)")
        cmd_id = str(uuid.uuid4())

        # async dispatch: traccia l'eventuale fallimento del send_command
        async def _dispatch_speedtest():
            try:
                reply = await conn.send_command("speedtest", {"command_id": cmd_id, "client_id": client_id}, timeout=90.0)
                logger.info(f"speedtest WS ack from {agent.get('hostname')}: {reply}")
            except Exception as exc:
                err = str(exc)
                logger.warning(f"speedtest WS dispatch failed for {agent.get('hostname')}: {err}")
                await db.wan_speedtest_history.update_one(
                    {"id": cmd_id},
                    {"$set": {
                        "status": "failed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "error": f"WS dispatch: {err[:200]}",
                    }},
                )

        asyncio.create_task(_dispatch_speedtest())
    except ImportError:
        raise HTTPException(status_code=500, detail="Modulo agent_ws non disponibile")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"speedtest dispatch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Errore invio comando: {e}")

    # Inserisce un record pending in storico — l'agent rispondera' via ws_reply
    pending = {
        "id": cmd_id,
        "client_id": client_id,
        "agent_id": agent_id,
        "agent_hostname": agent.get("hostname"),
        "agent_version": agent_version,
        "status": "running",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": current_user.get("email"),
    }
    await db.wan_speedtest_history.insert_one(pending)
    return {
        "status": "started",
        "command_id": cmd_id,
        "agent": {"id": agent_id, "hostname": agent.get("hostname"), "version": agent_version},
        "message": "Speedtest in corso. Il risultato apparira' entro 30-60s.",
    }


@router.get("/speedtest-history/{client_id}")
async def get_speedtest_history(client_id: str, limit: int = 20, current_user: dict = Depends(get_current_user)):
    """Storico speedtest del cliente (ultimi N)."""
    items = await db.wan_speedtest_history.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("requested_at", -1).to_list(min(limit, 100))
    return {"client_id": client_id, "history": items, "count": len(items)}


@router.post("/speedtest-result")
async def submit_speedtest_result(payload: dict, request: Request):
    """Endpoint callback chiamato DALL'AGENT per registrare il risultato di
    uno speedtest. Auth: Bearer token dell'agent (validato contro
    `agent_tokens`) — NON richiede JWT utente perche' il chiamante e' un
    binario Go installato dal cliente.

    Payload atteso:
      {command_id, client_id, agent_id, download_mbps, upload_mbps,
       ping_ms, jitter_ms, server, isp, error?}
    """
    # Estrai token dall'header Authorization
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token mancante")
    # Valida contro agent_tokens (token v4) o client api_keys
    tok_doc = await db.agent_tokens.find_one({"token": token, "revoked": {"$ne": True}}, {"_id": 0})
    if not tok_doc:
        # Fallback: api_key di un cliente (legacy)
        cli_doc = await db.clients.find_one({"api_key": token}, {"_id": 0, "id": 1})
        if not cli_doc:
            raise HTTPException(status_code=401, detail="Token non valido")

    cmd_id = payload.get("command_id")
    if not cmd_id:
        raise HTTPException(status_code=400, detail="command_id mancante")
    now_iso = datetime.now(timezone.utc).isoformat()
    update_fields = {
        "status": "failed" if payload.get("error") else "completed",
        "completed_at": now_iso,
        "download_mbps": payload.get("download_mbps"),
        "upload_mbps": payload.get("upload_mbps"),
        "ping_ms": payload.get("ping_ms"),
        "jitter_ms": payload.get("jitter_ms"),
        "server": payload.get("server"),
        "isp": payload.get("isp"),
        "error": payload.get("error"),
    }
    res = await db.wan_speedtest_history.update_one(
        {"id": cmd_id}, {"$set": update_fields}
    )
    if res.matched_count == 0:
        # crea record nuovo se non esiste (es. test manuale)
        await db.wan_speedtest_history.insert_one({
            "id": cmd_id,
            "client_id": payload.get("client_id"),
            "agent_id": payload.get("agent_id"),
            "requested_at": now_iso,
            **update_fields,
        })
    logger.info(f"speedtest-result accepted cmd_id={cmd_id} down={payload.get('download_mbps')} up={payload.get('upload_mbps')} err={payload.get('error')}")
    return {"status": "ok", "command_id": cmd_id}

