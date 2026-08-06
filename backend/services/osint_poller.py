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
from datetime import datetime, timezone

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
