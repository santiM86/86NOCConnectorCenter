"""
Syslog Anomaly — rilevamento brute-force e port-scan dai syslog gia' ingeriti.

Il parsing per-riga (routes/syslog_trap.py) allerta sul SINGOLO evento (es. un
login fallito). Questo servizio fa CORRELAZIONE su finestra temporale:
  - BRUTE-FORCE: N+ fallimenti di autenticazione/login dallo stesso device in
    una finestra breve → 1 alert aggregato (non uno per riga).
  - PORT-SCAN: molte porte di destinazione DISTINTE viste su log di
    deny/drop/blocked dello stesso device → 1 alert.

Config (db.settings key "syslog_anomaly_config"):
  enabled, window_min, bruteforce_threshold, portscan_threshold
Alert: source_type = "syslog_bruteforce" / "syslog_portscan" (dedup per finestra).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("syslog_anomaly")

SETTINGS_KEY = "syslog_anomaly_config"
DEFAULT_CONFIG = {
    "enabled": True,
    "window_min": 10,
    "bruteforce_threshold": 5,
    "portscan_threshold": 15,
}

_AUTH_FAIL = re.compile(
    r"(authentication\s*(fail|failure|error|denied)|"
    r"login\s*(fail|failed|invalid)|failed\s+password|"
    r"invalid\s+user|auth(entication)?\s+rejected|access\s+denied)", re.I)
_DENY = re.compile(r"(deny|denied|drop|dropped|block(ed)?|reject(ed)?)", re.I)
# porta di destinazione in vari formati: DPT=443 / dport 443 / dst port 443 / port 443
_DPORT = re.compile(r"(?:DPT=|dport[= ]|dst\s*port\s*|(?<![a-z])port\s*)(\d{1,5})", re.I)


async def get_config() -> dict:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    cfg = dict(DEFAULT_CONFIG)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


async def set_config(patch: dict) -> dict:
    cfg = await get_config()
    for k in DEFAULT_CONFIG:
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"key": SETTINGS_KEY, "value": cfg,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return cfg


async def _emit(client_id, device_ip, host, severity, source_type, title, msg, window_min, extra=None):
    """Emette un alert deduplicato sulla finestra corrente (evita flood)."""
    dedup = f"{source_type}:{client_id}:{device_ip}"
    win_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_min)).isoformat()
    existing = await db.alerts.find_one(
        {"dedup_key": dedup, "status": "active", "created_at": {"$gte": win_cutoff}},
        {"_id": 0, "id": 1})
    if existing:
        await db.alerts.update_one({"id": existing["id"]}, {"$set": {"message": msg}})
        return False
    alert = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "device_ip": device_ip,
        "device_name": host or device_ip,
        "device_type": "network",
        "severity": severity,
        "source_type": source_type,
        "dedup_key": dedup,
        "title": title,
        "message": msg,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if await insert_alert_if_emit(db, alert):
        try:
            from alert_engine import notify_alert_telegram
            await notify_alert_telegram(db, alert)
        except Exception:
            pass
        return True
    return False


async def scan_all() -> dict:
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"skipped": True}
    window_min = int(cfg["window_min"])
    bf_th = int(cfg["bruteforce_threshold"])
    ps_th = int(cfg["portscan_threshold"])
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_min)

    # (client_id, device_ip) -> {"auth": int, "ports": set, "host": str}
    agg: dict = {}
    try:
        cursor = db.syslog_events.find(
            {"ts": {"$gte": cutoff}},
            {"_id": 0, "client_id": 1, "device_ip": 1, "message": 1, "host": 1},
        ).limit(20000)
        async for ev in cursor:
            key = (ev.get("client_id"), ev.get("device_ip") or "unknown")
            e = agg.setdefault(key, {"auth": 0, "ports": set(), "host": None})
            if ev.get("host") and not e["host"]:
                e["host"] = ev["host"]
            m = ev.get("message") or ""
            if _AUTH_FAIL.search(m):
                e["auth"] += 1
            if _DENY.search(m):
                for pm in _DPORT.finditer(m):
                    try:
                        p = int(pm.group(1))
                        if 0 < p <= 65535:
                            e["ports"].add(p)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("syslog scan failed: %s", e)
        return {"error": str(e)}

    client_names = {c["id"]: c["name"] for c in
                    await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)}

    bf = 0
    ps = 0
    for (cid, ip), e in agg.items():
        cname = client_names.get(cid, "")
        if e["auth"] >= bf_th:
            ok = await _emit(
                cid, ip, e["host"], "high", "syslog_bruteforce",
                f"Possibile brute-force: {e['host'] or ip}",
                (f"Cliente {cname}: {e['auth']} tentativi di autenticazione/login FALLITI da "
                 f"'{e['host'] or ip}' ({ip}) negli ultimi {window_min} min. Possibile attacco "
                 f"brute-force in corso. Verifica l'origine e blocca se necessario."),
                window_min)
            bf += 1 if ok else 0
        if len(e["ports"]) >= ps_th:
            ok = await _emit(
                cid, ip, e["host"], "high", "syslog_portscan",
                f"Possibile port-scan: {e['host'] or ip}",
                (f"Cliente {cname}: rilevate connessioni bloccate verso {len(e['ports'])} porte "
                 f"DISTINTE da/su '{e['host'] or ip}' ({ip}) negli ultimi {window_min} min "
                 f"(es. {', '.join(str(p) for p in sorted(e['ports'])[:12])}...). Possibile "
                 f"scansione porte / ricognizione."),
                window_min)
            ps += 1 if ok else 0

    if bf or ps:
        logger.info("[syslog-anomaly] bruteforce=%s portscan=%s (win=%smin)", bf, ps, window_min)
    return {"bruteforce": bf, "portscan": ps, "groups": len(agg)}
