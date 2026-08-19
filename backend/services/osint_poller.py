"""
OSINT scheduler ticks
=====================
Due job APScheduler (registrati in server.py):

1) osint_feeds_tick (ogni 5 min): rinfresca i feed globali rispettando la
   cadenza di ciascuno (threat_intel + cisa_kev).

2) osint_exposure_tick (ogni 30 min): per ogni IP pubblico monitorato
   (`wan_targets`) interroga Shodan InternetDB (keyless), salva l'esposizione
   in `osint_exposure` e — se emergono CVE presenti nel catalogo CISA KEV
   (attivamente sfruttate) — genera un alert PER-TENANT (client_id del target).

Comportamento scelto: ENRICHMENT + ALERT automatici (nessun blocco automatico).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from alert_filter import insert_alert_if_emit
from services import osint_service as osint

logger = logging.getLogger("osint.poller")

# quanti target processare per tick (rate-friendly: InternetDB refresh settimanale)
EXPOSURE_BATCH = 15
EXPOSURE_REFRESH_H = 168  # 7 giorni


async def osint_feeds_tick() -> None:
    try:
        res = await osint.refresh_all_feeds(force=False)
        changed = {k: v for k, v in res.items() if v is not None}
        if changed:
            logger.info(f"[osint-feeds] refreshed: {changed}")
    except Exception as e:
        logger.exception(f"[osint-feeds] tick failed: {e}")


def _needs_scan(doc: dict | None, now: datetime) -> bool:
    if not doc or not doc.get("last_scan"):
        return True
    try:
        last = datetime.fromisoformat(str(doc["last_scan"]).replace("Z", "+00:00"))
        return (now - last).total_seconds() / 3600.0 >= EXPOSURE_REFRESH_H
    except Exception:
        return True


async def osint_exposure_tick() -> None:
    try:
        now = datetime.now(timezone.utc)
        targets = await db.wan_targets.find(
            {"public_ip": {"$nin": [None, ""]}}, {"_id": 0}
        ).to_list(1000)

        processed = 0
        for t in targets:
            if processed >= EXPOSURE_BATCH:
                break
            ip = t.get("public_ip")
            if not ip or not osint._is_public_ip(ip):
                continue
            existing = await db.osint_exposure.find_one({"target_id": t.get("id")}, {"_id": 0})
            if not _needs_scan(existing, now):
                continue

            idb = await osint._internetdb(ip)
            if not isinstance(idb, dict) or idb.get("error"):
                continue
            processed += 1

            vulns = idb.get("vulns", []) or []
            kev_hits = await osint._kev_hits(vulns)
            client_id = t.get("client_id")

            doc = {
                "target_id": t.get("id"),
                "client_id": client_id,
                "public_ip": ip,
                "label": t.get("label"),
                "ports": idb.get("ports", []),
                "vulns": vulns,
                "kev_hits": [k.get("cve_id") for k in kev_hits],
                "kev_count": len(kev_hits),
                "hostnames": idb.get("hostnames", []),
                "tags": idb.get("tags", []),
                "last_scan": now.isoformat(),
            }
            await db.osint_exposure.update_one(
                {"target_id": t.get("id")}, {"$set": doc}, upsert=True
            )

            # Alert per-tenant se ci sono CVE attivamente sfruttate esposte
            if kev_hits and client_id:
                cve_list = ", ".join(sorted(k.get("cve_id") for k in kev_hits if k.get("cve_id"))[:6])
                await _emit_exposure_alert(client_id, ip, t.get("label") or ip, kev_hits, cve_list)
            elif client_id:
                # Esposizione rientrata: risolvi eventuali alert OSINT attivi per questo IP
                await _resolve_exposure_alert(client_id, ip)

        if processed:
            logger.info(f"[osint-exposure] scanned {processed} public IP(s)")
    except Exception as e:
        logger.exception(f"[osint-exposure] tick failed: {e}")


async def _emit_exposure_alert(client_id: str, ip: str, label: str,
                               kev_hits: list[dict], cve_list: str) -> None:
    """Crea (con dedup) un alert OSINT per esposizione di CVE KEV su IP pubblico."""
    title = f"OSINT: CVE sfruttate esposte su {label}"
    # Dedup: se esiste già un alert attivo con stesso client/ip/title, aggiorna soltanto
    existing = await db.alerts.find_one(
        {"client_id": client_id, "device_ip": ip, "title": title, "status": "active"},
        {"_id": 0, "id": 1},
    )
    ransomware = any(str(k.get("ransomware", "")).lower() == "known" for k in kev_hits)
    msg = (f"L'IP pubblico {ip} espone {len(kev_hits)} CVE presenti nel catalogo "
           f"CISA KEV (attivamente sfruttate): {cve_list}. "
           f"{'⚠️ Usate in campagne ransomware note. ' if ransomware else ''}"
           f"Fonte: Shodan InternetDB + CISA KEV.")
    if existing:
        await db.alerts.update_one(
            {"id": existing["id"]},
            {"$set": {"message": msg, "last_seen_at": datetime.now(timezone.utc).isoformat(),
                      "raw_data": ", ".join(k.get("cve_id") for k in kev_hits)}},
        )
        return
    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "device_id": None,
        "device_ip": ip,
        "device_name": label,
        "device_type": "firewall",
        "severity": "high",
        "source_type": "osint",
        "title": title,
        "message": msg,
        "raw_data": ", ".join(k.get("cve_id") for k in kev_hits),
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await insert_alert_if_emit(db, alert_doc)
    logger.info(f"[osint-exposure] alert generato client={client_id} ip={ip} kev={len(kev_hits)}")


async def _resolve_exposure_alert(client_id: str, ip: str) -> None:
    """Risolve gli alert OSINT-exposure attivi quando l'IP non espone più CVE KEV."""
    now = datetime.now(timezone.utc).isoformat()
    res = await db.alerts.update_many(
        {"client_id": client_id, "device_ip": ip, "source_type": "osint", "status": "active"},
        {"$set": {"status": "resolved", "resolved_at": now,
                  "resolution_note": "Esposizione CVE KEV non più rilevata (OSINT auto-resolve)."}},
    )
    if res.modified_count:
        logger.info(f"[osint-exposure] auto-resolved {res.modified_count} alert client={client_id} ip={ip}")



# ==================== C2 CORRELATION (syslog/firewall -> IOC) ====================

C2_LOOKBACK_MIN = 15        # finestra alla prima esecuzione / fallback
C2_MAX_EVENTS = 5000        # cap eventi per tick


async def _scan_nebula_firewalls(agg: dict, now: datetime) -> int:
    """Estrae gli IP (src/dst) dagli event-log dei firewall Zyxel Nebula online
    e li confronta con gli IOC, aggiungendo i match all'aggregato C2 condiviso.
    Fonte 'live' che non richiede syslog configurato lato cliente."""
    try:
        from routes.zyxel_nebula import _nebula_request
    except Exception:
        return 0
    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - 3 * 60 * 1000  # ultimi 3 min (tick ogni 2 min)
    fws = await db.zyxel_devices.find(
        {"device_type": "firewall", "online_status": "ONLINE"},
        {"_id": 0, "dev_id": 1, "site_id": 1, "client_id": 1, "name": 1, "model": 1, "public_ip": 1},
    ).to_list(300)
    scanned = 0
    for fw in fws:
        if not fw.get("site_id") or not fw.get("dev_id"):
            continue
        try:
            logs = await _nebula_request(
                "POST", f"/{fw['site_id']}/gw/{fw['dev_id']}/event-logs",
                json={"startTimestamp": start_ms, "endTimestamp": end_ms},
            )
        except Exception as e:
            logger.debug(f"[osint-c2] nebula event-logs dev={fw.get('dev_id')}: {e}")
            continue
        if not isinstance(logs, list) or not logs:
            continue
        logs = logs[:8000]  # cap per firewall/tick
        scanned += len(logs)
        ips = set()
        for x in logs:
            for k in ("srcIpv4", "dstIpv4"):
                v = x.get(k)
                if v:
                    ips.add(v)
        if not ips:
            continue
        mm = await osint.match_ips_against_iocs(list(ips))
        if not mm:
            continue
        cid = fw.get("client_id")
        for bad_ip, hits in mm.items():
            entry = agg.setdefault((cid, bad_ip), {
                "client_id": cid, "bad_ip": bad_ip, "hits": hits,
                "firewalls": set(), "sample": f"Nebula event-log {fw.get('model') or ''}".strip(),
                "host": fw.get("name"),
            })
            entry["firewalls"].add(fw.get("public_ip") or fw.get("name") or fw["dev_id"])
    return scanned


async def osint_c2_tick() -> dict:
    """Scansiona i syslog_events recenti, estrae gli IP dai messaggi firewall e
    li confronta con gli IOC. Se un dispositivo cliente ha comunicato con un IP
    malevolo noto (C2/blocklist), genera un alert CRITICO per-tenant.

    Ritorna un riepilogo (utile anche per il trigger manuale via API)."""
    try:
        now = datetime.now(timezone.utc)
        # Determina la finestra: dall'ultimo scan (osint_feed_runs source=c2_scan)
        run = await db.osint_feed_runs.find_one({"source": "c2_scan"}, {"_id": 0, "cursor_ts": 1})
        since = None
        if run and run.get("cursor_ts"):
            try:
                since = datetime.fromisoformat(str(run["cursor_ts"]).replace("Z", "+00:00"))
            except Exception:
                since = None
        if since is None:
            since = now - timedelta(minutes=C2_LOOKBACK_MIN)

        query = {"ts": {"$gt": since}}
        events = await db.syslog_events.find(
            query, {"_id": 0, "client_id": 1, "device_ip": 1, "message": 1, "raw": 1, "ts": 1, "host": 1}
        ).sort("ts", 1).to_list(C2_MAX_EVENTS)

        scanned = len(events)
        matches_found = 0
        alerts = 0
        max_ts = since

        # Aggrega per (client_id, matched_ip) per evitare flood
        agg: dict[tuple, dict] = {}
        for ev in events:
            ts = ev.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts > max_ts:
                    max_ts = ts
            text = f"{ev.get('message', '')} {ev.get('raw', '')}"
            ips = osint.extract_ips(text)
            if not ips:
                continue
            mm = await osint.match_ips_against_iocs(ips)
            if not mm:
                continue
            cid = ev.get("client_id")
            fw_ip = ev.get("device_ip") or "unknown"
            for bad_ip, hits in mm.items():
                matches_found += 1
                key = (cid, bad_ip)
                entry = agg.setdefault(key, {
                    "client_id": cid, "bad_ip": bad_ip, "hits": hits,
                    "firewalls": set(), "sample": str(ev.get("message", ""))[:200],
                    "host": ev.get("host"),
                })
                entry["firewalls"].add(fw_ip)

        # Fonte aggiuntiva LIVE: event-log dei firewall Zyxel Nebula
        nebula_scanned = await _scan_nebula_firewalls(agg, now)
        scanned += nebula_scanned

        for (cid, bad_ip), entry in agg.items():
            if not cid:
                continue
            created = await _emit_c2_alert(entry)
            if created:
                alerts += 1

        # Persisti cursore
        await db.osint_feed_runs.update_one(
            {"source": "c2_scan"},
            {"$set": {
                "source": "c2_scan", "status": "success",
                "count": matches_found, "error": None,
                "finished_at": now.isoformat(),
                "cursor_ts": max_ts.isoformat(),
            }},
            upsert=True,
        )
        if scanned or matches_found:
            logger.info(f"[osint-c2] scanned={scanned} matches={matches_found} alerts={alerts}")
        return {"scanned": scanned, "matches": matches_found, "alerts": alerts,
                "window_since": since.isoformat()}
    except Exception as e:
        logger.exception(f"[osint-c2] tick failed: {e}")
        return {"error": str(e)[:200]}


async def _emit_c2_alert(entry: dict) -> bool:
    """Crea (con dedup) un alert CRITICO di comunicazione con IP malevolo noto."""
    cid = entry["client_id"]
    bad_ip = entry["bad_ip"]
    hits = entry.get("hits", [])
    firewalls = sorted(entry.get("firewalls", set()))
    fw_repr = ", ".join(firewalls[:5]) or "n/d"
    sources = sorted({h.get("source") for h in hits if h.get("source")})
    threats = sorted({h.get("threat") for h in hits if h.get("threat")})
    src_repr = ", ".join(sources) or "feed OSINT"
    threat_repr = f" · tipo: {', '.join(threats)}" if threats else ""

    title = f"OSINT: comunicazione con IP malevolo noto {bad_ip}"
    now_iso = datetime.now(timezone.utc).isoformat()
    msg = (f"Un dispositivo del cliente ha comunicato con l'IP {bad_ip}, presente in "
           f"blocklist/IOC ({src_repr}){threat_repr}. Rilevato su firewall/host: {fw_repr}. "
           f"Verificare immediatamente il dispositivo interessato. Fonte: correlazione OSINT su syslog/event-log firewall.")

    existing = await db.alerts.find_one(
        {"client_id": cid, "source_type": "osint_c2", "raw_data": bad_ip, "status": "active"},
        {"_id": 0, "id": 1},
    )
    if existing:
        await db.alerts.update_one(
            {"id": existing["id"]},
            {"$set": {"message": msg, "last_seen_at": now_iso}},
        )
        return False

    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": cid,
        "device_id": None,
        "device_ip": firewalls[0] if firewalls else None,
        "device_name": entry.get("host") or (firewalls[0] if firewalls else bad_ip),
        "device_type": "firewall",
        "severity": "critical",
        "source_type": "osint_c2",
        "title": title,
        "message": msg,
        "raw_data": bad_ip,
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": now_iso,
    }
    await insert_alert_if_emit(db, alert_doc)
    logger.info(f"[osint-c2] ALERT client={cid} bad_ip={bad_ip} sources={src_repr}")
    await _notify_c2_alert(alert_doc)
    return True


async def _notify_c2_alert(alert_doc: dict) -> None:
    """Broadcast WS live + notifica push immediata per un nuovo alert C2."""
    # 1) WebSocket broadcast -> il feed alert si aggiorna in tempo reale
    try:
        from deps import manager
        client = await db.clients.find_one({"id": alert_doc.get("client_id")}, {"_id": 0, "name": 1})
        payload = dict(alert_doc)
        payload["client_name"] = client["name"] if client else ""
        payload["device_name"] = alert_doc.get("device_name") or ""
        payload["ip_address"] = alert_doc.get("device_ip") or ""
        await manager.broadcast({"type": "new_alert", "alert": payload})
    except Exception as e:
        logger.warning(f"[osint-c2] WS broadcast failed: {e}")
    # 2) Web push immediata
    try:
        import webpush as _wp
        await _wp.notify_new_alert(db, alert_doc)
    except Exception as e:
        logger.warning(f"[osint-c2] webpush failed: {e}")
    # 3) Notifica multi-canale (email + push) priorità critica
    try:
        from deps import notification_service
        from notifications import NotificationChannel, NotificationPriority
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert_doc["title"],
            message=alert_doc["message"],
            priority=NotificationPriority.CRITICAL,
            alert_id=alert_doc["id"],
            data={"source": "osint_c2", "bad_ip": alert_doc.get("raw_data"),
                  "client_id": alert_doc.get("client_id")},
        )
    except Exception as e:
        logger.warning(f"[osint-c2] notification_service failed: {e}")
