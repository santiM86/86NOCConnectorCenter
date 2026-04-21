"""Redfish direct polling, power control, and Wake-on-LAN routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta

from database import db
from security import security_manager
from audit import AuditAction
from deps import get_current_user, audit_logger, redfish_poller, validate_api_key

router = APIRouter(prefix="/api", tags=["redfish"])


@router.post("/redfish/test-connection")
async def redfish_test_connection(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    url = body.get("url", "").rstrip("/")
    username = body.get("username", "")
    password = body.get("password", "")
    if not url or not username:
        raise HTTPException(status_code=400, detail="URL e username obbligatori")
    result = await redfish_poller.test_connection(url, username, password)
    return result


@router.put("/vault/credentials/{cred_id}/direct-poll")
async def set_direct_poll(cred_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    update = {}
    if "direct_poll" in body: update["direct_poll"] = bool(body["direct_poll"])
    if "external_url" in body: update["external_url"] = body["external_url"]
    if not update:
        raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")
    result = await db.device_credentials.update_one({"id": cred_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Credenziale non trovata")
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "direct_poll_config", "cred_id": cred_id, **update}, severity="info"
    )
    return {"status": "ok"}


@router.get("/redfish/failover-status")
async def get_failover_status(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    return await redfish_poller.get_failover_status()


@router.get("/redfish/channel-health-matrix")
async def channel_health_matrix(current_user: dict = Depends(get_current_user)):
    """Matrice iLO health per Dashboard Channel Health: direct + connector + overall.
    Aggregates: device_credentials (iLO only) × ilo_channel_health × device_poll_status × connector_status.
    """
    if current_user.get("role") not in ["admin", "superadmin", "operator"]:
        raise HTTPException(status_code=403, detail="Accesso negato")

    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(minutes=5)).isoformat()
    direct_cutoff = (now - timedelta(minutes=3)).isoformat()

    ilo_creds = await db.device_credentials.find(
        {"credential_type": "ilo"},
        {"_id": 0, "device_ip": 1, "device_name": 1, "external_url": 1, "connector_only": 1, "client_id": 1, "id": 1}
    ).to_list(500)

    # Prefetch clients map
    client_ids = list({c["client_id"] for c in ilo_creds if c.get("client_id")})
    clients_map = {}
    if client_ids:
        cl_docs = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        clients_map = {c["id"]: c["name"] for c in cl_docs}

    result = []
    stats = {"total": 0, "both_ok": 0, "direct_only": 0, "connector_only": 0, "both_down": 0, "n_a": 0}
    for c in ilo_creds:
        device_ip = c.get("device_ip")
        if not device_ip:
            continue
        stats["total"] += 1

        # Direct channel
        health = await db.ilo_channel_health.find_one({"device_ip": device_ip}, {"_id": 0})
        direct_status = "n_a"
        direct_detail = None
        if c.get("external_url") and not c.get("connector_only"):
            if health:
                failures = int(health.get("direct_consecutive_failures") or 0)
                last_success = health.get("direct_last_success")
                if failures == 0 and last_success and last_success >= direct_cutoff:
                    direct_status = "ok"
                elif failures >= 3:
                    direct_status = "down"
                elif failures >= 1:
                    direct_status = "degraded"
                else:
                    direct_status = "unknown"
                direct_detail = {
                    "last_success": last_success,
                    "last_failure": health.get("direct_last_failure"),
                    "consecutive_failures": failures,
                    "last_error": health.get("direct_last_error"),
                }
            else:
                direct_status = "unknown"  # not yet polled
        else:
            direct_status = "disabled"

        # Connector channel
        connector_status = "n_a"
        connector_detail = None
        dps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})
        if dps:
            last_update = dps.get("last_update")
            connector_detail = {"last_update": last_update, "client_id": dps.get("client_id")}
            if last_update and str(last_update) > stale_cutoff:
                connector_status = "ok"
            elif last_update:
                connector_status = "stale"
            else:
                connector_status = "unknown"
        else:
            connector_status = "unknown"

        # Check connector heartbeat
        if c.get("client_id"):
            conn_heartbeat = await db.connector_status.find_one({"client_id": c["client_id"]}, {"_id": 0, "last_seen": 1, "hostname": 1})
            if conn_heartbeat:
                if connector_detail is None: connector_detail = {}
                connector_detail["connector_host"] = conn_heartbeat.get("hostname")
                last_seen = conn_heartbeat.get("last_seen")
                if last_seen and str(last_seen) < stale_cutoff and connector_status not in ("ok",):
                    connector_status = "down"

        # Overall
        if direct_status == "ok" and connector_status == "ok":
            overall = "both_ok"
        elif direct_status == "ok":
            overall = "direct_only"
        elif connector_status == "ok":
            overall = "connector_only"
        elif direct_status in ("down", "degraded") and connector_status in ("down", "stale"):
            overall = "both_down"
        else:
            overall = "n_a"
        stats[overall] = stats.get(overall, 0) + 1

        result.append({
            "device_ip": device_ip,
            "device_name": c.get("device_name") or device_ip,
            "client_id": c.get("client_id"),
            "client_name": clients_map.get(c.get("client_id"), ""),
            "external_url": c.get("external_url"),
            "connector_only": bool(c.get("connector_only")),
            "direct": {"status": direct_status, **(direct_detail or {})},
            "connector": {"status": connector_status, **(connector_detail or {})},
            "overall": overall,
        })

    # Sort: both_down first, then connector_only/direct_only (degraded), then ok
    sort_order = {"both_down": 0, "direct_only": 1, "connector_only": 2, "n_a": 3, "both_ok": 4}
    result.sort(key=lambda x: (sort_order.get(x["overall"], 9), x["device_name"]))
    return {"stats": stats, "items": result, "generated_at": now.isoformat()}



@router.post("/redfish/poll-now")
async def trigger_direct_poll(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    asyncio.create_task(redfish_poller.poll_cycle())
    return {"status": "ok", "message": "Polling Redfish avviato"}


@router.get("/redfish/metrics/{device_ip}")
async def get_redfish_metrics(
    device_ip: str, minutes: int = 60,
    current_user: dict = Depends(get_current_user)
):
    """Timeline metriche iLO per grafici real-time enterprise.
    Ritorna temperatures[], fans[], power_watts, health per ogni snapshot nelle ultime N minuti.
    Default 60 min; max 24h.
    """
    if current_user.get("role") not in ["admin", "superadmin", "operator", "viewer"]:
        raise HTTPException(status_code=403, detail="Accesso negato")
    minutes = max(1, min(minutes, 1440))
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    # Prendi ultimi 500 snapshot (upper bound)
    cursor = db.ilo_telemetry.find(
        {"device_ip": device_ip, "timestamp": {"$gte": since}},
        {"_id": 0}
    ).sort("timestamp", 1).limit(500)
    snapshots = []
    async for doc in cursor:
        ts = doc.get("timestamp")
        if isinstance(ts, datetime):
            # Forza UTC+Z per evitare parse JS come local time (bug "2h fa")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            doc["timestamp"] = ts.isoformat().replace("+00:00", "Z")
        snapshots.append(doc)

    # Latest snapshot "wide" (con tutti i sensori)
    latest = await db.ilo_telemetry.find_one(
        {"device_ip": device_ip},
        {"_id": 0},
        sort=[("timestamp", -1)]
    )
    if latest and isinstance(latest.get("timestamp"), datetime):
        ts = latest["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        latest["timestamp"] = ts.isoformat().replace("+00:00", "Z")
    # Server-side age_seconds to avoid JS TZ interpretation bugs ("2h fa")
    if latest and latest.get("timestamp"):
        try:
            ts_dt = datetime.fromisoformat(latest["timestamp"].replace("Z", "+00:00"))
            latest["age_seconds"] = int((datetime.now(timezone.utc) - ts_dt).total_seconds())
        except Exception:
            latest["age_seconds"] = None

    # Costruzione serie time-series per charting veloce
    series = {
        "power_watts": [],
        "max_temperature": [],
        "avg_temperature": [],
    }
    sensor_series = {}  # keyed by sensor name
    for s in snapshots:
        ts = s["timestamp"]
        if s.get("power_watts") is not None:
            series["power_watts"].append({"t": ts, "v": s["power_watts"]})
        temps = [t["celsius"] for t in (s.get("temperatures") or []) if t.get("celsius") is not None]
        if temps:
            series["max_temperature"].append({"t": ts, "v": max(temps)})
            series["avg_temperature"].append({"t": ts, "v": round(sum(temps) / len(temps), 1)})
        for t in s.get("temperatures") or []:
            name = t.get("name") or "unknown"
            if name not in sensor_series:
                sensor_series[name] = []
            if t.get("celsius") is not None:
                sensor_series[name].append({"t": ts, "v": t["celsius"]})

    return {
        "device_ip": device_ip,
        "snapshots_count": len(snapshots),
        "time_range_minutes": minutes,
        "latest": latest,
        "series": series,
        "per_sensor_temperatures": sensor_series,
    }


@router.get("/redfish/metrics/{device_ip}/live")
async def get_redfish_live(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Ultimo snapshot disponibile (latest frame). Ideale per poll rapido dalla UI ogni 10-15s."""
    if current_user.get("role") not in ["admin", "superadmin", "operator", "viewer"]:
        raise HTTPException(status_code=403, detail="Accesso negato")
    latest = await db.ilo_telemetry.find_one(
        {"device_ip": device_ip},
        {"_id": 0},
        sort=[("timestamp", -1)]
    )
    if not latest:
        raise HTTPException(status_code=404, detail="Nessuna telemetria disponibile per questo device")
    if isinstance(latest.get("timestamp"), datetime):
        ts = latest["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        latest["timestamp"] = ts.isoformat().replace("+00:00", "Z")
    # Age in seconds (utile per UI "ultimo update X sec fa")
    try:
        ts_dt = datetime.fromisoformat(latest["timestamp"].replace("Z", "+00:00"))
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        latest["age_seconds"] = int((datetime.now(timezone.utc) - ts_dt).total_seconds())
    except Exception:
        latest["age_seconds"] = None
    return latest


@router.get("/redfish/sensor-timeline/{device_ip}")
async def sensor_timeline(device_ip: str, sensor: str, hours: int = 24,
                           current_user: dict = Depends(get_current_user)):
    """Timeline di UN singolo sensore termico o ventola nelle ultime N ore.
    Query param:
      - sensor: nome grezzo del sensore (es. "53-CPU1 DigIO")
      - hours: finestra temporale (default 24, max 168 = 7 giorni)
    Ritorna serie temporale [{ts, value, health}].
    """
    hours = max(1, min(hours, 168))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    cursor = db.ilo_telemetry.find(
        {"device_ip": device_ip, "timestamp": {"$gte": since}},
        {"_id": 0, "timestamp": 1, "temperatures": 1, "fans": 1}
    ).sort("timestamp", 1)
    points = []
    min_v = None
    max_v = None
    avg_sum = 0.0
    count = 0
    sensor_lower = sensor.lower().strip()
    sensor_type = "temperature"  # default
    async for doc in cursor:
        ts = doc.get("timestamp")
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_str = ts.isoformat().replace("+00:00", "Z")
        else:
            ts_str = str(ts)
        # Find matching sensor in temperatures[] first, then fans[]
        value = None
        health = None
        stale = False
        for t in (doc.get("temperatures") or []):
            if (t.get("name") or "").lower() == sensor_lower:
                value = t.get("celsius")
                health = t.get("health")
                stale = bool(t.get("stale"))
                sensor_type = "temperature"
                break
        if value is None:
            for f in (doc.get("fans") or []):
                if (f.get("name") or "").lower() == sensor_lower:
                    value = f.get("rpm_percent")
                    health = f.get("health")
                    stale = bool(f.get("stale"))
                    sensor_type = "fan"
                    break
        if value is None:
            continue
        points.append({"ts": ts_str, "value": value, "health": health, "stale": stale})
        if min_v is None or value < min_v: min_v = value
        if max_v is None or value > max_v: max_v = value
        avg_sum += value
        count += 1

    stats = {
        "min": min_v,
        "max": max_v,
        "avg": round(avg_sum / count, 1) if count else None,
        "samples": count,
        "window_hours": hours,
        "sensor_type": sensor_type,
    }
    return {
        "device_ip": device_ip,
        "sensor": sensor,
        "stats": stats,
        "points": points,
    }



@router.get("/redfish/raw/{device_ip}")
async def redfish_raw_probe(device_ip: str, path: str = "/redfish/v1/Chassis/1/Thermal/",
                              current_user: dict = Depends(get_current_user)):
    """Debug: esegue GET diretto su un URI Redfish arbitrario e ritorna il JSON raw.
    Utile per diagnosticare perche' Temperatures/Fans/NIC non vengono letti.
    Usa le credenziali del Vault e il transport diretto (external_url o device_ip).
    Restringere a admin/operator.
    """
    if current_user.get("role") not in ["admin", "superadmin", "operator"]:
        raise HTTPException(status_code=403, detail="Accesso negato")
    # Find iLO credential for device
    cred = await db.device_credentials.find_one({"device_ip": device_ip, "credential_type": {"$in": ["ilo", "redfish"]}}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Credenziale iLO non trovata in Vault per questo device")
    try:
        from security import SecurityManager
        sm = SecurityManager()
        username = sm.decrypt_credential(cred["username_enc"])
        password = sm.decrypt_credential(cred["password_enc"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decrypt failed: {e}")
    import httpx as _httpx
    port = cred.get("port") or 443
    base_url = cred.get("external_url", "").rstrip("/") or f"https://{device_ip}:{port}"
    target = path if path.startswith("/") else f"/{path}"
    url = f"{base_url}{target}"
    try:
        async with _httpx.AsyncClient(verify=False, timeout=15.0) as client:
            r = await client.get(url, auth=(username, password))
            data = {}
            try:
                data = r.json()
            except Exception:
                data = {"_raw_text": r.text[:4000]}
            return {
                "url": url,
                "status_code": r.status_code,
                "content_type": r.headers.get("content-type"),
                "body": data,
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Redfish GET error: {e}")



@router.get("/redfish/diagnose/{device_ip}")
async def redfish_diagnose(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Spiega passo-passo perche' un iLO non e' pollato live. Check:
    1. Device esiste in managed_devices / device_poll_status?
    2. Credenziale iLO nel Vault?
    3. direct_poll + external_url impostati?
    4. Connector assegnato e online?
    5. Ultimo poll (direct cloud o via connector)?
    6. Device class rilevata SNMP?
    """
    if current_user.get("role") not in ["admin", "superadmin", "operator"]:
        raise HTTPException(status_code=403, detail="Solo admin/operator")

    diagnosis = {
        "device_ip": device_ip,
        "checks": [],
        "current_poll_source": None,
        "last_successful_poll": None,
        "recommendation": None,
    }

    def add(step: str, status: str, detail: str, fix: str = None):
        diagnosis["checks"].append({"step": step, "status": status, "detail": detail, "fix": fix})

    # 1. Device registration
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0})
    ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})
    if md:
        add("1. Device registration", "ok", f"Device in managed_devices (type={md.get('device_type','?')}, client={md.get('client_id')})")
    elif ps:
        add("1. Device registration", "warn", f"Device esiste SOLO in device_poll_status (discovery auto). Considera di aggiungerlo a managed_devices.",
             fix="Vai nella pagina Devices e registra esplicitamente questo device con device_type='ilo'")
    else:
        add("1. Device registration", "error", "Device NON registrato: il connector non lo pollerà mai.",
             fix="Aggiungi il device in Devices → New device, imposta device_type='ilo'")
        diagnosis["recommendation"] = "Aggiungi il device in ARGUS prima di qualunque altra cosa"
        return diagnosis

    client_id = (md or ps).get("client_id")
    device_type = (md or {}).get("device_type") or (ps or {}).get("device_type")
    device_class = (ps or {}).get("device_class") if ps else None

    if device_type == "ilo":
        add("1b. Device type", "ok", "device_type=ilo (connector triggererà Redfish)")
    elif device_class == "hpe-ilo":
        add("1b. Device type", "ok", f"device_type={device_type or '?'}, ma device_class=hpe-ilo (auto-detectato via SNMP)")
    else:
        add("1b. Device type", "warn", f"device_type={device_type or '?'}, device_class={device_class or '?'}. Serve device_type=ilo o device_class=hpe-ilo",
             fix="Imposta device_type='ilo' nella scheda device")

    # 2. Credentials
    cred = await db.device_credentials.find_one(
        {"device_ip": device_ip},
        {"_id": 0, "id": 1, "credential_type": 1, "external_url": 1, "direct_poll": 1, "client_id": 1}
    )
    if not cred:
        add("2. Credenziale Vault", "error", "Nessuna credenziale nel Vault per questo device.",
             fix="Vault → New Credential → device_ip={ip}, credential_type=ilo, inserisci user/password iLO".replace("{ip}", device_ip))
        diagnosis["recommendation"] = "Aggiungi credenziale iLO nel Vault"
        return diagnosis
    if cred.get("credential_type") not in ("ilo", "redfish"):
        add("2. Credenziale Vault", "error", f"Credenziale esiste ma credential_type={cred.get('credential_type')} (deve essere 'ilo' o 'redfish').",
             fix="Vault → edit credenziale → cambia credential_type a 'ilo'")
    else:
        add("2. Credenziale Vault", "ok", f"Credenziale iLO presente (cred_id={cred.get('id','?')[:8]}...)")

    # 3. Direct poll config
    direct = cred.get("direct_poll", False)
    ext_url = cred.get("external_url")
    if direct and ext_url:
        add("3. Direct poll cloud", "ok", f"direct_poll=True, external_url={ext_url}. Il cloud ARGUS polla direttamente.")
        diagnosis["current_poll_source"] = "REDFISH_DIRECT (cloud)"
    elif direct and not ext_url:
        add("3. Direct poll cloud", "error", "direct_poll=True ma external_url mancante. Il poll diretto non può partire.",
             fix="Inserisci external_url (es. https://ilo.cliente.com:443) OPPURE setta direct_poll=False per usare il Connector LAN")
    else:
        add("3. Direct poll cloud", "info", "direct_poll=False → usa il Connector LAN (consigliato se iLO è in rete privata)")
        diagnosis["current_poll_source"] = "CONNECTOR_LAN"

    # 4. Connector
    connector = await db.connectors.find_one(
        {"client_id": client_id, "status": "active"},
        {"_id": 0, "id": 1, "hostname": 1, "last_seen": 1, "status": 1, "version": 1}
    ) if client_id else None
    if diagnosis["current_poll_source"] == "CONNECTOR_LAN":
        if not connector:
            add("4. Connector assegnato", "error", f"Nessun Connector attivo per client_id={client_id}.",
                 fix="Installa/attiva un Connector sul cliente")
        else:
            last_seen = connector.get("last_seen")
            if isinstance(last_seen, datetime):
                elapsed = (datetime.now(timezone.utc) - (last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen)).total_seconds()
            elif isinstance(last_seen, str):
                try:
                    ls = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    elapsed = (datetime.now(timezone.utc) - ls).total_seconds()
                except Exception:
                    elapsed = 9999
            else:
                elapsed = 9999
            if elapsed < 120:
                add("4. Connector online", "ok", f"Connector {connector.get('hostname','?')} v{connector.get('version','?')} visto {int(elapsed)}s fa")
            else:
                add("4. Connector online", "error", f"Connector {connector.get('hostname','?')} NON heartbeat da {int(elapsed)}s (soglia 120s).",
                     fix="Verifica il servizio '86NocConnector' sul server del cliente")

    # 5. Ultimo poll
    latest = await db.ilo_status.find_one({"device_ip": device_ip}, {"_id": 0, "timestamp": 1, "redfish_ok": 1, "source": 1, "power_watts": 1})
    if latest:
        ts = latest.get("timestamp")
        if isinstance(ts, datetime):
            elapsed = (datetime.now(timezone.utc) - (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts)).total_seconds()
        elif isinstance(ts, str):
            try:
                tp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - tp).total_seconds()
            except Exception:
                elapsed = 9999
        else:
            elapsed = 9999
        diagnosis["last_successful_poll"] = {"at": latest.get("timestamp"), "elapsed_seconds": int(elapsed), "source": latest.get("source"), "redfish_ok": latest.get("redfish_ok"), "power_watts": latest.get("power_watts")}
        if elapsed < 600:
            add("5. Ultimo poll Redfish", "ok", f"{int(elapsed)}s fa, source={latest.get('source')}, ok={latest.get('redfish_ok')}")
        else:
            add("5. Ultimo poll Redfish", "error", f"Ultimo poll {int(elapsed)}s fa ({int(elapsed/60)}min). Il poll si è fermato.",
                 fix="Vedi check 3-4 per capire da dove dovrebbe arrivare il poll")
    else:
        add("5. Ultimo poll Redfish", "error", "Nessun poll Redfish MAI registrato per questo device.",
             fix="Fai partire un poll manuale: POST /api/redfish/poll-now (solo direct) oppure force connector tick")

    # 6. Consiglio finale
    if not diagnosis.get("recommendation"):
        errors = [c for c in diagnosis["checks"] if c["status"] == "error"]
        warnings = [c for c in diagnosis["checks"] if c["status"] == "warn"]
        if errors:
            diagnosis["recommendation"] = f"Risolvi i {len(errors)} errori critici in ordine. Il primo fix da applicare: {errors[0].get('fix') or errors[0].get('detail')}"
        elif warnings:
            diagnosis["recommendation"] = "Configurazione funzionante ma con warning. " + (warnings[0].get('fix') or warnings[0].get('detail'))
        else:
            diagnosis["recommendation"] = "Tutto OK. Se i dati non sono freschi, forza un poll manuale."

    return diagnosis



# ==================== POWER CONTROL & WAKE-ON-LAN ====================

@router.post("/devices/{device_ip}/power-action")
async def device_power_action(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    action = body.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="Campo 'action' obbligatorio")
    cred = await db.device_credentials.find_one({"device_ip": device_ip, "credential_type": "ilo"}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Nessuna credenziale iLO trovata per questo dispositivo")
    external_url = cred.get("external_url")
    if not external_url:
        raise HTTPException(status_code=400, detail="URL esterna iLO non configurata. Configurala nel Vault per il polling diretto.")
    try:
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Errore decifratura credenziali")
    result = await redfish_poller.power_action(external_url.rstrip("/"), username, password, action)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "power_control", "device_ip": device_ip, "power_action": action, "result": result.get("success")},
        severity="critical"
    )
    return result


@router.get("/devices/{device_ip}/power-state")
async def device_power_state(device_ip: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    cred = await db.device_credentials.find_one({"device_ip": device_ip, "credential_type": "ilo"}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Nessuna credenziale iLO")
    external_url = cred.get("external_url")
    if not external_url:
        raise HTTPException(status_code=400, detail="URL esterna iLO non configurata")
    try:
        username = security_manager.decrypt_credential(cred["username_enc"])
        password = security_manager.decrypt_credential(cred["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Errore decifratura credenziali")
    return await redfish_poller.get_power_state(external_url.rstrip("/"), username, password)


@router.post("/devices/{device_ip}/wake-on-lan")
async def device_wake_on_lan(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    body = await request.json()
    mac_address = body.get("mac_address", "").strip().upper()
    if not mac_address or len(mac_address.replace(":", "").replace("-", "")) != 12:
        raise HTTPException(status_code=400, detail="Indirizzo MAC non valido (formato: AA:BB:CC:DD:EE:FF)")
    await db.pending_commands.insert_one({
        "id": str(uuid.uuid4()), "type": "wake_on_lan",
        "target_ip": device_ip, "mac_address": mac_address,
        "requested_by": current_user.get("email"), "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "wake_on_lan", "device_ip": device_ip, "mac": mac_address}, severity="warning"
    )
    return {"status": "ok", "message": f"Comando WoL per {mac_address} accodato. Verra' eseguito dal connettore al prossimo heartbeat (~60s)."}


@router.get("/connector/pending-commands")
async def connector_get_pending_commands(request: Request):
    await validate_api_key(request)
    commands = await db.pending_commands.find({"status": "pending"}, {"_id": 0}).sort("created_at", 1).to_list(50)
    if commands:
        cmd_ids = [c["id"] for c in commands]
        await db.pending_commands.update_many(
            {"id": {"$in": cmd_ids}},
            {"$set": {"status": "dispatched", "dispatched_at": datetime.now(timezone.utc).isoformat()}}
        )
    return commands
