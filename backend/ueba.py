"""UEBA: profilo comportamentale per utente (orari, host, origini) e deviazioni.

Collezione `ueba_profiles` {client_id, user, hours[24], hosts{host: n}, total, first_seen, last_seen, last_public: {ip, ts}}
Anomalie (source_type):
- ueba_unusual_hour   accesso in un'ora mai/quasi mai usata da quell'utente (profilo appreso)
- ueba_new_host       primo accesso dell'utente a un host mai usato (possibile movimento laterale)
- ueba_impossible     stesso utente da 2 IP pubblici diversi in < 30 min
- ueba_bruteforce_ok  >= 5 tentativi falliti e poi accesso riuscito in 15 min (password indovinata?)
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db

LEARN_MIN_EVENTS = 40
LEARN_MIN_DAYS = 7
RARE_HOUR_RATIO = 0.02
FAIL_THRESHOLD = 5


def _public(ip: Optional[str]) -> bool:
    try:
        return bool(ip) and ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _local_hour(ts_iso: str, tz: str) -> int:
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(ZoneInfo(tz or "Europe/Rome")).hour


async def evaluate_event(client_id: str, host: str, d: dict, tz: str, emit) -> None:
    """Chiamata per ogni accesso interattivo/RDP riuscito (d normalizzato dal registro AdS)."""
    user = (d.get("user") or "").lower()
    if not user or user.endswith("$"):
        return
    now = datetime.now(timezone.utc)
    prof = await db.ueba_profiles.find_one({"client_id": client_id, "user": user}, {"_id": 0}) or {}
    hours = prof.get("hours") or [0] * 24
    hosts = prof.get("hosts") or {}
    total = int(prof.get("total") or 0)
    first = prof.get("first_seen")
    learned = total >= LEARN_MIN_EVENTS and first and (now - datetime.fromisoformat(first)).days >= LEARN_MIN_DAYS
    try:
        hr = _local_hour(d["ts"], tz)
    except Exception:
        hr = None
    label = f"{d.get('domain') + chr(92) if d.get('domain') else ''}{d['user']}"
    if learned and hr is not None and hours[hr] / max(total, 1) < RARE_HOUR_RATIO:
        usual = sorted(range(24), key=lambda h: -hours[h])[:3]
        await emit(client_id, host, "medium", f"UEBA: orario insolito per {d['user']} su {host} ({hr:02d}:00)",
                   f"{label} accede di solito alle {', '.join(f'{h:02d}' for h in sorted(usual))}. Questo accesso alle {hr:02d}:00 "
                   f"è fuori dal suo comportamento abituale ({hours[hr]} accessi su {total} in quella fascia).", "ueba_unusual_hour")
    hkey = host.replace(".", "_")
    if learned and hkey not in hosts:
        await emit(client_id, host, "medium", f"UEBA: {d['user']} accede per la prima volta a {host}",
                   f"{label} non aveva mai effettuato accessi su {host} (host abituali: {', '.join(sorted(hosts)[:6]).replace('_', '.')}). "
                   f"Se non previsto può indicare un movimento laterale con credenziali rubate.", "ueba_new_host")
    src = d.get("src_ip")
    try:
        ev_t = datetime.fromisoformat(str(d.get("ts")).replace("Z", "+00:00"))
    except Exception:
        ev_t = now
    lp = prof.get("last_public") or {}
    if _public(src) and lp.get("ip") and lp["ip"] != src:
        try:
            gap = abs((ev_t - datetime.fromisoformat(lp["ts"])).total_seconds())
        except Exception:
            gap = 1e9
        if gap < 1800:
            await emit(client_id, host, "high", f"UEBA: accesso impossibile per {d['user']} (2 IP pubblici in {int(gap // 60)} min)",
                       f"{label} si è collegato da {lp['ip']} e poi da {src} a distanza di {int(gap // 60)} minuti. "
                       f"Due connessioni pubbliche diverse così ravvicinate indicano spesso credenziali usate da terzi.", "ueba_impossible")
    since = (now - timedelta(minutes=15)).isoformat()
    fails = await db.security_events.count_documents({"client_id": client_id, "category": "logon_failed", "ts": {"$gte": since},
                                                      "user": {"$regex": f"^{re.escape(d['user'])}$", "$options": "i"}})
    if fails >= FAIL_THRESHOLD:
        await emit(client_id, host, "high", f"UEBA: {d['user']} entra dopo {fails} tentativi falliti su {host}",
                   f"Negli ultimi 15 minuti {label} ha avuto {fails} accessi falliti e poi un accesso riuscito"
                   f"{' da ' + src if src else ''}. Possibile password indovinata (brute force): verificare e cambiare la password.", "ueba_bruteforce_ok")
    upd = {"$inc": {"total": 1, f"hosts.{hkey}": 1}, "$set": {"last_seen": now.isoformat()}, "$setOnInsert": {"first_seen": now.isoformat()}}
    if hr is not None:
        upd["$inc"][f"hours.{hr}"] = 1
        if not prof:
            upd["$setOnInsert"]["hours"] = [0] * 24
            upd["$inc"].pop(f"hours.{hr}")
    if _public(src):
        upd["$set"]["last_public"] = {"ip": src, "ts": ev_t.isoformat()}
    await db.ueba_profiles.update_one({"client_id": client_id, "user": user}, upd, upsert=True)
    if not prof and hr is not None:
        await db.ueba_profiles.update_one({"client_id": client_id, "user": user}, {"$inc": {f"hours.{hr}": 1}})


async def user_risk(client_id: Optional[str] = None, days: int = 30) -> list[dict]:
    """Punteggio di rischio per utente dalle anomalie UEBA/registro degli ultimi N giorni."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    weights = {"ueba_impossible": 30, "ueba_bruteforce_ok": 30, "ueba_new_host": 12, "ueba_unusual_hour": 8,
               "seclog_new_origin": 15, "seclog_after_hours": 5, "seclog_usb_insert": 4}
    q = {"source_type": {"$in": list(weights)}, "created_at": {"$gte": since}}
    if client_id:
        q["client_id"] = client_id
    agg: dict = {}
    async for a in db.alerts.find(q, {"_id": 0, "client_id": 1, "title": 1, "source_type": 1, "ueba_user": 1}):
        u = a.get("ueba_user") or ""
        if not u:
            continue
        k = (a["client_id"], u)
        r = agg.setdefault(k, {"client_id": a["client_id"], "user": u, "score": 0, "anomalies": 0, "types": {}})
        r["score"] = min(100, r["score"] + weights[a["source_type"]])
        r["anomalies"] += 1
        r["types"][a["source_type"]] = r["types"].get(a["source_type"], 0) + 1
    return sorted(agg.values(), key=lambda r: -r["score"])
