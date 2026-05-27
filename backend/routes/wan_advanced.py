"""
WAN Advanced — Funzionalità Fase 2:
- Multi-ISP failover detection
- Cloud SaaS reachability (M365, Google, AWS)
- MTR/Traceroute on-demand
- Alert rules configurabili per target (latency / loss threshold)
- Grafici storici 7d/30d bucket-aggregated
"""
import asyncio
import logging
import socket
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import db
from deps import get_current_user, require_admin
import aiohttp

logger = logging.getLogger("wan_advanced")
router = APIRouter(prefix="/api/external-monitor", tags=["wan-advanced"])


# ==================== MULTI-ISP FAILOVER ====================

@router.get("/multi-isp/{client_id}")
async def multi_isp_status(client_id: str, current_user: dict = Depends(get_current_user)):
    """Rileva configurazioni multi-ISP per il cliente:
    - Conta i target distinti per gateway_ip (proxy del numero di linee).
    - Per ogni linea ritorna stato corrente + last successful probe.
    - Detection di failover: se uno e' DOWN e l'altro UP nelle ultime 24h.
    """
    targets = await db.wan_targets.find({"client_id": client_id, "enabled": True}, {"_id": 0}).to_list(50)
    if not targets:
        return {"client_id": client_id, "isps": [], "failover_events": [], "multi_isp": False}

    # Raggruppa per gateway_ip (linea ISP)
    by_gw = {}
    for t in targets:
        gw = t.get("gateway_ip") or "no_gateway"
        by_gw.setdefault(gw, []).append(t)

    results = await db.wan_probe_results.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(100)
    res_map = {r["target_id"]: r for r in results}

    isps = []
    for gw, ts in by_gw.items():
        if gw == "no_gateway":
            continue
        # Stato attuale: gateway reachable?
        gw_status = None
        gw_latency = None
        for t in ts:
            r = res_map.get(t["id"])
            if r and r.get("gateway_ping"):
                gw_status = r["gateway_ping"].get("reachable")
                gw_latency = r["gateway_ping"].get("latency_ms")
                break
        isps.append({
            "gateway_ip": gw,
            "target_ids": [t["id"] for t in ts],
            "target_labels": [t["label"] for t in ts],
            "reachable": gw_status,
            "latency_ms": gw_latency,
        })

    # Failover events ultime 24h: trova transitions reachable -> down e viceversa
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    failover_events = []
    if len(isps) >= 2:
        # carica history e cerca cambi di stato per gateway_reachable
        target_ids = [t for isp in isps for t in isp["target_ids"]]
        hist = await db.wan_probe_history.find(
            {"target_id": {"$in": target_ids}, "timestamp": {"$gte": cutoff}},
            {"_id": 0, "target_id": 1, "gateway_reachable": 1, "timestamp": 1},
        ).sort("timestamp", 1).to_list(5000)
        last_state = {}
        for h in hist:
            tid = h["target_id"]
            gr = h.get("gateway_reachable")
            if gr is None:
                continue
            prev = last_state.get(tid)
            if prev is not None and prev != gr:
                failover_events.append({
                    "target_id": tid,
                    "timestamp": h["timestamp"],
                    "transition": "up" if gr else "down",
                })
            last_state[tid] = gr

    return {
        "client_id": client_id,
        "multi_isp": len(isps) >= 2,
        "isp_count": len(isps),
        "isps": isps,
        "failover_events": failover_events[-20:],
    }


# ==================== CLOUD SAAS REACHABILITY ====================

# Endpoint critici per ogni cliente MSP italiano
SAAS_TARGETS = [
    {"name": "Microsoft 365", "host": "outlook.office365.com", "icon": "microsoft"},
    {"name": "Microsoft Teams", "host": "teams.microsoft.com", "icon": "microsoft"},
    {"name": "Google Workspace", "host": "mail.google.com", "icon": "google"},
    {"name": "Google Drive", "host": "drive.google.com", "icon": "google"},
    {"name": "AWS Console", "host": "console.aws.amazon.com", "icon": "aws"},
    {"name": "Azure Portal", "host": "portal.azure.com", "icon": "azure"},
    {"name": "Cloudflare", "host": "1.1.1.1", "icon": "cloudflare"},
    {"name": "GitHub", "host": "github.com", "icon": "github"},
]


async def _probe_saas(target: dict, timeout: float = 4.0) -> dict:
    """Probe TCP 443 + DNS resolve + RTT measurement."""
    host = target["host"]
    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
        if not infos:
            return {**target, "ok": False, "latency_ms": None, "error": "DNS no result"}
        ip = infos[0][4][0]
        dns_ms = round((time.monotonic() - t0) * 1000, 1)

        # TCP connect
        t1 = time.monotonic()
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, 443), timeout=timeout)
        tcp_ms = round((time.monotonic() - t1) * 1000, 1)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {
            **target,
            "ok": True,
            "ip": ip,
            "dns_ms": dns_ms,
            "tcp_ms": tcp_ms,
            "latency_ms": tcp_ms,
        }
    except asyncio.TimeoutError:
        return {**target, "ok": False, "latency_ms": None, "error": "timeout"}
    except Exception as e:
        return {**target, "ok": False, "latency_ms": None, "error": str(e)[:80]}


@router.get("/saas-reachability/{client_id}")
async def saas_reachability(client_id: str, current_user: dict = Depends(get_current_user)):
    """Verifica raggiungibilità servizi cloud critici (M365, Google, AWS, Azure...).
    Esegue probe TCP 443 + DNS resolve in parallelo. Salva snapshot in DB.
    """
    # Verifica esistenza cliente (best-effort)
    cli = await db.clients.find_one({"id": client_id}, {"_id": 0, "id": 1, "name": 1})
    results = await asyncio.gather(*[_probe_saas(t) for t in SAAS_TARGETS], return_exceptions=True)
    cleaned = []
    for r in results:
        if isinstance(r, Exception):
            cleaned.append({"name": "?", "ok": False, "error": str(r)[:80]})
        else:
            cleaned.append(r)
    healthy = sum(1 for r in cleaned if r.get("ok"))
    snapshot = {
        "client_id": client_id,
        "client_name": cli.get("name") if cli else None,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"healthy": healthy, "total": len(cleaned), "all_ok": healthy == len(cleaned)},
        "services": cleaned,
    }
    # Salva ultimo snapshot
    await db.wan_saas_snapshots.update_one(
        {"client_id": client_id},
        {"$set": snapshot},
        upsert=True,
    )
    return snapshot


# ==================== TRACEROUTE ====================

async def _traceroute_async(target: str, max_hops: int = 20, timeout: int = 3) -> list:
    """Esegue traceroute via subprocess (cross-platform).
    Su Linux/macOS usa `traceroute`, su Windows `tracert`.
    """
    import shutil
    cmd_name = "traceroute" if shutil.which("traceroute") else "tracert"
    if not shutil.which(cmd_name):
        return [{"error": f"{cmd_name} non installato"}]
    args = [cmd_name]
    if cmd_name == "traceroute":
        args += ["-n", "-w", str(timeout), "-q", "1", "-m", str(max_hops), target]
    else:
        args += ["-d", "-w", str(timeout * 1000), "-h", str(max_hops), target]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=max_hops * 4)
        except asyncio.TimeoutError:
            proc.kill()
            return [{"error": "traceroute timeout"}]
        text = stdout.decode("utf-8", errors="ignore")
        hops = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # parse: "1  10.0.0.1  1.234 ms" or "  1     1 ms     1 ms     1 ms  10.0.0.1"
            parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            hop_num = int(parts[0])
            # Trova IP e RTT nel resto della riga
            ip = None
            rtt = None
            for p in parts[1:]:
                # IPv4 literal?
                if p.count(".") == 3 and all(s.replace("*", "").isdigit() or s == "" for s in p.split(".")):
                    ip = p
                # RTT ms?
                try:
                    f = float(p)
                    if 0 < f < 10000 and rtt is None:
                        rtt = f
                except ValueError:
                    pass
            hops.append({"hop": hop_num, "ip": ip, "rtt_ms": rtt, "raw": line[:200]})
            if len(hops) >= max_hops:
                break
        return hops
    except Exception as e:
        return [{"error": str(e)[:200]}]


@router.post("/traceroute")
async def run_traceroute(payload: dict, current_user: dict = Depends(get_current_user)):
    """Esegue un traceroute dal NOC verso `target` (IP o hostname).
    Body: {target: str, max_hops?: int}
    """
    require_admin(current_user)
    target = (payload.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target mancante")
    max_hops = min(max(payload.get("max_hops", 20), 5), 30)
    hops = await _traceroute_async(target, max_hops=max_hops)
    return {
        "target": target,
        "max_hops": max_hops,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "hop_count": len([h for h in hops if h.get("ip")]),
        "hops": hops,
    }


# ==================== ALERT RULES per TARGET ====================

class AlertRule(BaseModel):
    target_id: str
    enabled: bool = True
    latency_warn_ms: Optional[int] = None  # warning se latenza > N ms (3 cycli)
    latency_crit_ms: Optional[int] = None
    loss_warn_pct: Optional[float] = None
    loss_crit_pct: Optional[float] = None
    uptime_warn_pct: Optional[float] = None  # warning se uptime 24h < N%
    notify_email: Optional[str] = None
    notify_telegram_chat_id: Optional[str] = None


@router.get("/alert-rules/{target_id}")
async def get_alert_rules(target_id: str, current_user: dict = Depends(get_current_user)):
    """Recupera le regole alert configurate per un target WAN."""
    doc = await db.wan_alert_rules.find_one({"target_id": target_id}, {"_id": 0})
    if not doc:
        return {
            "target_id": target_id,
            "enabled": False,
            "latency_warn_ms": None, "latency_crit_ms": None,
            "loss_warn_pct": None, "loss_crit_pct": None,
            "uptime_warn_pct": None,
            "notify_email": None, "notify_telegram_chat_id": None,
        }
    return doc


@router.put("/alert-rules/{target_id}")
async def upsert_alert_rules(target_id: str, rule: AlertRule, current_user: dict = Depends(get_current_user)):
    """Crea/aggiorna le regole alert per un target."""
    require_admin(current_user)
    if rule.target_id != target_id:
        raise HTTPException(status_code=400, detail="target_id mismatch")
    # Verifica target esistente
    t = await db.wan_targets.find_one({"id": target_id}, {"_id": 0, "id": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Target non trovato")
    doc = rule.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_by"] = current_user.get("email")
    await db.wan_alert_rules.update_one({"target_id": target_id}, {"$set": doc}, upsert=True)
    return {"status": "ok", "rule": doc}


@router.delete("/alert-rules/{target_id}")
async def delete_alert_rules(target_id: str, current_user: dict = Depends(get_current_user)):
    """Rimuove le regole alert per un target."""
    require_admin(current_user)
    await db.wan_alert_rules.delete_one({"target_id": target_id})
    return {"status": "ok"}


# ==================== STORICO BUCKET (7d/30d aggregato) ====================

@router.get("/history-bucket/{target_id}")
async def history_bucket(
    target_id: str,
    days: int = 7,
    current_user: dict = Depends(get_current_user),
):
    """Storico aggregato in bucket per grafici 7d/30d.
    - 7d → bucket di 1 ora (168 punti)
    - 30d → bucket di 6 ore (120 punti)
    - 1d → bucket di 5 min (288 punti)
    Ogni bucket ritorna: avg_latency, avg_loss, uptime_pct, samples.
    """
    days = min(max(days, 1), 90)
    now_dt = datetime.now(timezone.utc)
    cutoff = (now_dt - timedelta(days=days)).isoformat()

    # Bucket size in seconds
    if days <= 1:
        bucket_sec = 300  # 5 min
    elif days <= 7:
        bucket_sec = 3600  # 1 ora
    else:
        bucket_sec = 6 * 3600  # 6 ore

    history = await db.wan_probe_history.find(
        {"target_id": target_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("timestamp", 1).to_list(50000)

    if not history:
        return {
            "target_id": target_id, "days": days, "bucket_sec": bucket_sec,
            "buckets": [], "total_samples": 0,
        }

    def _ts_epoch(h):
        try:
            return int(datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00")).timestamp())
        except Exception:
            return 0

    def _is_online(h):
        if "reachable" in h:
            return bool(h.get("reachable"))
        nested = (h.get("ping") or {}).get("reachable")
        if nested is not None:
            return bool(nested)
        status = (h.get("status") or "").lower()
        return status in ("online", "filtered", "degraded")

    def _lat(h):
        if "latency_ms" in h:
            return h.get("latency_ms")
        return (h.get("ping") or {}).get("latency_ms")

    def _loss(h):
        if "packet_loss_pct" in h:
            return h.get("packet_loss_pct")
        return (h.get("ping") or {}).get("packet_loss_pct")

    buckets = {}
    for h in history:
        ts = _ts_epoch(h)
        if ts == 0:
            continue
        b = (ts // bucket_sec) * bucket_sec
        d = buckets.setdefault(b, {"online": 0, "total": 0, "lat_sum": 0, "lat_n": 0, "loss_sum": 0, "loss_n": 0})
        d["total"] += 1
        if _is_online(h):
            d["online"] += 1
            lat = _lat(h)
            if lat is not None:
                d["lat_sum"] += lat
                d["lat_n"] += 1
        loss = _loss(h)
        if loss is not None:
            d["loss_sum"] += loss
            d["loss_n"] += 1

    out = []
    for b in sorted(buckets.keys()):
        d = buckets[b]
        out.append({
            "t": datetime.fromtimestamp(b, tz=timezone.utc).isoformat(),
            "avg_latency": round(d["lat_sum"] / d["lat_n"], 1) if d["lat_n"] else None,
            "avg_loss": round(d["loss_sum"] / d["loss_n"], 2) if d["loss_n"] else 0,
            "uptime_pct": round(d["online"] * 100 / d["total"], 1) if d["total"] else 0,
            "samples": d["total"],
        })

    return {
        "target_id": target_id, "days": days, "bucket_sec": bucket_sec,
        "buckets": out, "total_samples": len(history),
    }
