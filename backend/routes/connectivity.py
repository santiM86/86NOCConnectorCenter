"""
Connettivita' per-device — "Spark".

Storico ping time-series per singolo dispositivo + report di connettivita'
con statistiche (uptime, latenza avg/min/max/p95, jitter, packet loss,
n. disconnessioni, MTTR, finestre di down) + test on-demand.

Collection: `device_ping_history` (TTL 30gg, 1 doc per ciclo di ping).
Ingestita da agent_ws._bridge_ping_poll ad ogni PingPollResult.
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
from typing import Optional
import statistics
import asyncio

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["connectivity"])

PING_TTL_DAYS = 30

# Soglie default (rese configurabili in futuro). Vedi ask_human 2026-07-29.
LAT_WARN_MS = 30.0
LAT_CRIT_MS = 100.0
LOSS_WARN_PCT = 2.0
LOSS_CRIT_PCT = 10.0

_PERIOD_MAP = {
    # period: (hours, bucket_seconds)
    "1h": (1, 60),
    "6h": (6, 300),
    "24h": (24, 900),
    "7d": (168, 3600),
    "30d": (720, 14400),
}


async def ensure_index():
    """TTL su `ts` (30gg) + indice composito. Idempotente."""
    try:
        await db.device_ping_history.create_index("ts", expireAfterSeconds=PING_TTL_DAYS * 86400)
        await db.device_ping_history.create_index([("client_id", 1), ("device_ip", 1), ("ts", -1)])
    except Exception:
        pass


async def record_ping(client_id: str, device_ip: str, reachable: bool,
                      latency_ms, loss_pct) -> None:
    """Append 1 punto allo storico ping. Best-effort (mai solleva)."""
    if not client_id or not device_ip:
        return
    try:
        doc = {
            "client_id": client_id,
            "device_ip": device_ip,
            "ts": datetime.now(timezone.utc),  # BSON date → TTL funziona
            "up": 1 if reachable else 0,
        }
        if latency_ms is not None:
            try:
                doc["latency_ms"] = float(latency_ms)
            except (TypeError, ValueError):
                pass
        if loss_pct is not None:
            try:
                doc["loss_pct"] = float(loss_pct)
            except (TypeError, ValueError):
                pass
        await db.device_ping_history.insert_one(doc)
    except Exception:
        pass


def _severity(uptime_pct, avg_lat, avg_loss) -> str:
    if uptime_pct is not None and uptime_pct < 95:
        return "crit"
    if avg_loss is not None and avg_loss >= LOSS_CRIT_PCT:
        return "crit"
    if avg_lat is not None and avg_lat >= LAT_CRIT_MS:
        return "crit"
    if (avg_loss is not None and avg_loss >= LOSS_WARN_PCT) or \
       (avg_lat is not None and avg_lat >= LAT_WARN_MS) or \
       (uptime_pct is not None and uptime_pct < 99.5):
        return "warn"
    return "ok"


def _iso_utc(dt) -> str:
    """ISO string tz-aware (UTC). I datetime letti da Mongo sono naive → li
    forziamo a UTC per coerenza con series[].ts (evita sfasamento orario UI)."""
    if dt is None:
        return None
    if hasattr(dt, "tzinfo"):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


@router.get("/devices/by-ip/{device_ip}/connectivity-report")
async def connectivity_report(
    device_ip: str,
    period: str = "24h",
    client_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Report di connettivita' aggregato dallo storico ping.

    period: 1h | 6h | 24h | 7d | 30d
    client_id: scope multi-tenant (evita mix di IP privati fra clienti).
    """
    # v2026-07-29 MULTI-TENANT: client_id OBBLIGATORIO. IP privati (192.168.x,
    # 10.x) collidono tra clienti diversi: senza scope si aggregherebbe lo
    # storico ping di piu' tenant → leak cross-tenant. Il frontend lo passa
    # sempre.
    client_id = (client_id or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id e' obbligatorio")

    if period not in _PERIOD_MAP:
        period = "24h"
    hours, bucket_sec = _PERIOD_MAP[period]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = {"device_ip": device_ip, "client_id": client_id, "ts": {"$gte": cutoff}}

    # Streaming: statistiche + buckets + eventi di down, senza tenere tutto in RAM.
    total = 0
    up_count = 0
    latencies = []          # per p95/jitter (cap prudente)
    cur_lat = None          # latenza dell'ultimo campione online (PingPlotter "Cur")
    loss_sum = 0.0
    loss_cnt = 0
    loss_max = None
    buckets: dict = {}

    prev_up = None
    down_start = None
    down_windows = []       # {start, end, duration_min}
    disconnections = 0

    cursor = db.device_ping_history.find(
        q, {"_id": 0, "ts": 1, "up": 1, "latency_ms": 1, "loss_pct": 1}
    ).sort("ts", 1)

    async for d in cursor:
        total += 1
        ts = d.get("ts")
        up = int(d.get("up") or 0)
        lat = d.get("latency_ms")
        loss = d.get("loss_pct")

        if up:
            up_count += 1
            if lat is not None:
                cur_lat = float(lat)
                if len(latencies) < 60000:
                    latencies.append(float(lat))
        if loss is not None:
            loss_sum += float(loss)
            loss_cnt += 1
            loss_max = float(loss) if loss_max is None else max(loss_max, float(loss))

        # Eventi di disconnessione (transizioni up→down) + finestre di down
        if prev_up == 1 and up == 0:
            disconnections += 1
            down_start = ts
        elif prev_up == 0 and up == 1 and down_start is not None:
            try:
                dur = (ts - down_start).total_seconds() / 60.0
            except Exception:
                dur = None
            down_windows.append({
                "start": _iso_utc(down_start),
                "end": _iso_utc(ts),
                "duration_min": round(dur, 1) if dur is not None else None,
            })
            down_start = None
        prev_up = up

        # Buckets per i grafici
        if hasattr(ts, "timestamp"):
            epoch_ms = int(ts.timestamp() * 1000)
            bkey = epoch_ms - (epoch_ms % (bucket_sec * 1000))
            b = buckets.setdefault(bkey, {"lat_sum": 0.0, "lat_cnt": 0, "loss_sum": 0.0, "loss_cnt": 0, "up": 0, "cnt": 0})
            b["cnt"] += 1
            b["up"] += up
            if up and lat is not None:
                b["lat_sum"] += float(lat)
                b["lat_cnt"] += 1
            if loss is not None:
                b["loss_sum"] += float(loss)
                b["loss_cnt"] += 1

    currently_down = (prev_up == 0)
    # Finestra di down ancora aperta a fine periodo
    if down_start is not None:
        down_windows.append({
            "start": _iso_utc(down_start),
            "end": None,
            "duration_min": None,
            "ongoing": True,
        })

    uptime_pct = round((up_count / total) * 100, 2) if total else None
    avg_lat = round(statistics.fmean(latencies), 1) if latencies else None
    min_lat = round(min(latencies), 1) if latencies else None
    max_lat = round(max(latencies), 1) if latencies else None
    jitter = round(statistics.pstdev(latencies), 1) if len(latencies) > 1 else 0.0
    p95_lat = None
    if latencies:
        s = sorted(latencies)
        p95_lat = round(s[min(len(s) - 1, int(0.95 * (len(s) - 1)))], 1)
    avg_loss = round(loss_sum / loss_cnt, 2) if loss_cnt else None

    # MTTR = durata media delle finestre di down RISOLTE
    resolved = [w["duration_min"] for w in down_windows if w.get("duration_min") is not None]
    mttr_min = round(statistics.fmean(resolved), 1) if resolved else None

    # PingPlotter-style: distribuzione latenza per fascia (verde/giallo/rosso)
    dist = {"good": 0, "warn": 0, "crit": 0}
    for v in latencies:
        if v < LAT_WARN_MS:
            dist["good"] += 1
        elif v < LAT_CRIT_MS:
            dist["warn"] += 1
        else:
            dist["crit"] += 1
    ld = len(latencies)
    distribution = {
        "good_pct": round(dist["good"] / ld * 100, 1) if ld else None,
        "warn_pct": round(dist["warn"] / ld * 100, 1) if ld else None,
        "crit_pct": round(dist["crit"] / ld * 100, 1) if ld else None,
    }

    # KPI disconnessioni: downtime totale + interruzione piu' lunga.
    # Include la finestra ancora aperta (ongoing) stimata fino ad ora.
    now_dt = datetime.now(timezone.utc)
    downtime_durations = list(resolved)
    for w in down_windows:
        if w.get("ongoing") and w.get("start"):
            try:
                st = datetime.fromisoformat(w["start"])
                downtime_durations.append((now_dt - st).total_seconds() / 60.0)
            except Exception:
                pass
    total_downtime_min = round(sum(downtime_durations), 1) if downtime_durations else 0.0
    longest_outage_min = round(max(downtime_durations), 1) if downtime_durations else 0.0

    series = []
    for bkey in sorted(buckets.keys()):
        b = buckets[bkey]
        series.append({
            "ts": datetime.fromtimestamp(bkey / 1000, tz=timezone.utc).isoformat(),
            "latency_avg": round(b["lat_sum"] / b["lat_cnt"], 1) if b["lat_cnt"] else None,
            "loss_avg": round(b["loss_sum"] / b["loss_cnt"], 2) if b["loss_cnt"] else None,
            "up_ratio": round(b["up"] / b["cnt"], 3) if b["cnt"] else None,
        })
    series = series[-500:]

    return {
        "device_ip": device_ip,
        "client_id": client_id,
        "period": period,
        "samples": total,
        "samples_up": up_count,
        "uptime_pct": uptime_pct,
        "currently_down": currently_down if total else None,
        "latency": {
            "cur": round(cur_lat, 1) if cur_lat is not None else None,
            "avg": avg_lat, "min": min_lat, "max": max_lat, "p95": p95_lat, "jitter": jitter,
        },
        "latency_distribution": distribution,
        "loss": {"avg": avg_loss, "max": round(loss_max, 2) if loss_max is not None else None},
        "disconnections": disconnections,
        "mttr_min": mttr_min,
        "total_downtime_min": total_downtime_min,
        "longest_outage_min": longest_outage_min,
        "down_windows": down_windows[-50:],
        "severity": _severity(uptime_pct, avg_lat, avg_loss),
        "thresholds": {
            "latency_warn_ms": LAT_WARN_MS, "latency_crit_ms": LAT_CRIT_MS,
            "loss_warn_pct": LOSS_WARN_PCT, "loss_crit_pct": LOSS_CRIT_PCT,
        },
        "series": series,
    }


@router.post("/devices/by-ip/{device_ip}/connectivity-test")
async def connectivity_test(
    device_ip: str,
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Test di connettivita' ON-DEMAND: esegue una raffica di N ping via
    l'agent v4 master LIVE del cliente e ritorna stat immediate (min/avg/max
    latenza, jitter, packet loss). Ogni campione viene salvato nello storico.

    Body: {"client_id": str, "count"?: int (default 10, max 20)}
    """
    from routes.agent_ws import REGISTRY  # import locale: evita ciclo

    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id e' obbligatorio")
    count = int(payload.get("count") or 10)
    count = max(3, min(count, 20))

    three_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    master = await db.managed_agents.find_one(
        {"client_id": client_id, "role": "master",
         "$or": [
             {"last_heartbeat_at": {"$gte": three_min_ago}},
             {"last_seen_at": {"$gte": three_min_ago}},
         ]},
        {"_id": 0, "agent_id": 1, "hostname": 1},
    )
    # Fallback: qualunque agent live del cliente (anche scanner) se manca master
    if not master:
        master = await db.managed_agents.find_one(
            {"client_id": client_id,
             "$or": [
                 {"last_heartbeat_at": {"$gte": three_min_ago}},
                 {"last_seen_at": {"$gte": three_min_ago}},
             ]},
            {"_id": 0, "agent_id": 1, "hostname": 1},
        )
    if not master:
        raise HTTPException(status_code=404, detail="Nessun agent v4 LIVE per questo cliente")

    conn = REGISTRY.get(master["agent_id"])
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Agent {master.get('hostname')} non connesso al WS")

    packets = []
    latencies = []
    reachable_count = 0
    # Budget globale ~20s per stare sotto il timeout ingress/proxy anche nel
    # caso peggiore (device che non risponde). Se scade, ritorniamo i pacchetti
    # gia' raccolti.
    import time as _time
    deadline = _time.monotonic() + 20.0
    sent = 0
    for i in range(count):
        if _time.monotonic() >= deadline:
            break
        sent += 1
        try:
            reply = await conn.send_command("force_ping_poll", {"ip": device_ip}, timeout=3.0)
            reachable = bool(reply.get("reachable") or reply.get("Reachable"))
            lat = reply.get("latency_ms") or reply.get("Latency")
            if lat is None:
                lat_ns = reply.get("latency_ns") or reply.get("LatencyNs")
                lat = (float(lat_ns) / 1e6) if lat_ns else None
            loss = reply.get("loss_pct")
            method = reply.get("method") or reply.get("Method") or "?"
            err = reply.get("error") or reply.get("Error")
        except asyncio.TimeoutError:
            reachable, lat, loss, method, err = False, None, None, "?", "WS timeout"
        except Exception as e:
            reachable, lat, loss, method, err = False, None, None, "?", str(e)[:120]

        if reachable:
            reachable_count += 1
            if lat is not None:
                try:
                    latencies.append(float(lat))
                except (TypeError, ValueError):
                    pass
        packets.append({"seq": i + 1, "reachable": reachable,
                        "latency_ms": round(float(lat), 1) if lat is not None else None,
                        "method": method, "error": err})
        # salva nello storico
        await record_ping(client_id, device_ip, reachable, lat, loss)
        await asyncio.sleep(0.1)

    loss_pct = round((sent - reachable_count) / sent * 100, 1) if sent else 100.0
    stats = {
        "sent": sent,
        "received": reachable_count,
        "loss_pct": loss_pct,
        "min_ms": round(min(latencies), 1) if latencies else None,
        "avg_ms": round(statistics.fmean(latencies), 1) if latencies else None,
        "max_ms": round(max(latencies), 1) if latencies else None,
        "jitter_ms": round(statistics.pstdev(latencies), 1) if len(latencies) > 1 else 0.0,
    }
    return {
        "ok": True,
        "device_ip": device_ip,
        "agent": master,
        "stats": stats,
        "packets": packets,
    }
