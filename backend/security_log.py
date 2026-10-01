"""Registro accessi Amministratori di Sistema (Garante Privacy 27/11/2008, GDPR art. 32, NIS2).

Eventi Windows (Security/System/TerminalServices) raccolti dall'Agent Go → `security_events`, con
catena hash SHA-256 per cliente (prev_hash → hash) che rende il registro inalterabile e verificabile
(`verify_chain`). Retention tramite TTL su `expire_at` (BSON date), default 12 mesi.
Collezioni: security_events, security_chain_state, security_admins (utenti AdS per cliente),
security_log_settings (retention per cliente).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import db

logger = logging.getLogger("security_log")
_LOCKS: dict[str, asyncio.Lock] = {}
DEFAULT_RETENTION_MONTHS = 12

# event_id → (categoria, severità base, etichetta)
EVENT_MAP: dict[int, tuple[str, str, str]] = {
    4624: ("logon_success", "info", "Accesso riuscito"),
    4625: ("logon_failed", "warning", "Accesso fallito"),
    4634: ("logoff", "info", "Disconnessione"),
    4647: ("logoff", "info", "Disconnessione utente"),
    4672: ("privileged_logon", "info", "Accesso con privilegi amministrativi"),
    4720: ("account_created", "high", "Account creato"),
    4722: ("account_enabled", "warning", "Account abilitato"),
    4724: ("password_reset", "warning", "Reset password da amministratore"),
    4725: ("account_disabled", "warning", "Account disabilitato"),
    4726: ("account_deleted", "high", "Account eliminato"),
    4728: ("group_change", "high", "Utente aggiunto a gruppo globale"),
    4732: ("group_change", "high", "Utente aggiunto a gruppo locale (es. Administrators)"),
    4733: ("group_change", "warning", "Utente rimosso da gruppo locale"),
    4756: ("group_change", "high", "Utente aggiunto a gruppo universale"),
    4740: ("lockout", "warning", "Account bloccato (lockout)"),
    4767: ("lockout", "info", "Account sbloccato"),
    1102: ("log_cleared", "critical", "Registro Security CANCELLATO"),
    104: ("log_cleared", "critical", "Registro eventi cancellato"),
    6005: ("power_on", "info", "Avvio sistema"),
    6006: ("power_off", "info", "Arresto sistema"),
    1074: ("power_off", "info", "Arresto/riavvio richiesto"),
    41: ("power_crash", "warning", "Spegnimento improvviso (crash/alimentazione)"),
    6008: ("power_crash", "warning", "Arresto imprevisto"),
    1149: ("rdp_connect", "info", "Connessione RDP"),
    21: ("rdp_session", "info", "Sessione RDP avviata"),
    24: ("rdp_session", "info", "Sessione RDP disconnessa"),
    25: ("rdp_session", "info", "Sessione RDP riconnessa"),
}
LOGON_TYPES = {2: "Interattivo", 3: "Rete", 4: "Batch", 5: "Servizio", 7: "Sblocco", 8: "Rete (chiaro)",
               9: "Nuove credenziali", 10: "RDP / Remoto", 11: "Cache"}
_SYSTEM_ACCOUNTS = {"system", "anonymous logon", "local service", "network service", "-", ""}


def _lock(client_id: str) -> asyncio.Lock:
    if client_id not in _LOCKS:
        _LOCKS[client_id] = asyncio.Lock()
    return _LOCKS[client_id]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def event_hash(prev_hash: str, doc: dict) -> str:
    payload = {k: doc.get(k) for k in ("client_id", "host", "log", "record_id", "event_id", "ts", "user", "domain",
                                        "logon_type", "src_ip", "workstation", "subject_user", "target_user", "seq")}
    return hashlib.sha256((prev_hash + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()


def _noise(ev: dict) -> bool:
    user = (ev.get("user") or "").lower()
    if user.endswith("$") or user in _SYSTEM_ACCOUNTS or user.startswith(("dwm-", "umfd-")):
        return ev.get("event_id") not in (1102, 104, 6005, 6006, 1074, 41, 6008)
    return False


async def get_admins(client_id: str) -> set[str]:
    doc = await db.security_admins.find_one({"client_id": client_id}, {"_id": 0, "users": 1})
    return {u.lower() for u in (doc or {}).get("users", [])}


async def retention_months(client_id: str) -> int:
    doc = await db.security_log_settings.find_one({"client_id": client_id}, {"_id": 0, "retention_months": 1})
    if doc and doc.get("retention_months"):
        return int(doc["retention_months"])
    g = await db.security_log_settings.find_one({"client_id": "global"}, {"_id": 0, "retention_months": 1})
    return int((g or {}).get("retention_months") or DEFAULT_RETENTION_MONTHS)


def _normalize(client_id: str, agent_id: str, host: str, ev: dict) -> Optional[dict]:
    try:
        eid = int(ev.get("event_id") or ev.get("id") or 0)
    except (TypeError, ValueError):
        return None
    meta = EVENT_MAP.get(eid)
    if not meta:
        return None
    cat, sev, label = meta
    data = ev.get("data") or {}
    user = ev.get("user") or data.get("TargetUserName") or data.get("SubjectUserName") or data.get("User") or ""
    group_evt = eid in (4728, 4732, 4733, 4756)
    if group_evt:
        member = str(data.get("MemberName") or data.get("MemberSid") or "")
        member = member.split(",")[0].replace("CN=", "").strip() if member.startswith("CN=") else member
        user = member or user
    elif eid in (4720, 4722, 4724, 4725, 4726, 4740):
        user = data.get("TargetUserName") or user
    lt = ev.get("logon_type") if ev.get("logon_type") is not None else data.get("LogonType")
    try:
        lt = int(lt) if lt not in (None, "", "-") else None
    except (TypeError, ValueError):
        lt = None
    ts = ev.get("ts") or ev.get("time_created")
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "client_id": client_id, "agent_id": agent_id, "host": host or ev.get("host") or "",
        "log": ev.get("log") or "Security", "record_id": int(ev.get("record_id") or 0), "event_id": eid,
        "category": cat, "severity": sev, "label": label, "ts": str(ts or _now().isoformat()),
        "user": str(user), "domain": str(ev.get("domain") or data.get("TargetDomainName") or data.get("SubjectDomainName") or ""),
        "logon_type": lt, "logon_type_label": LOGON_TYPES.get(lt) if lt else None,
        "src_ip": str(ev.get("src_ip") or data.get("IpAddress") or data.get("ClientAddress") or data.get("Address") or "").replace("::ffff:", "") or None,
        "workstation": str(ev.get("workstation") or data.get("WorkstationName") or data.get("ClientName") or "") or None,
        "subject_user": str(data.get("SubjectUserName") or "") or None,
        "target_user": str(user if group_evt else (data.get("TargetUserName") or "")) or None,
        "group": str(data.get("TargetUserName") if group_evt else "") or None,
        "failure_reason": str(data.get("Status") or data.get("FailureReason") or "") or None,
        "message": str(ev.get("message") or "")[:400] or None,
    }
    if doc["src_ip"] in ("-", "127.0.0.1", "::1"):
        doc["src_ip"] = None
    return doc


async def ingest_security_events(client_id: str, agent_id: str, host: str, events: list[dict]) -> dict:
    if not client_id or not events:
        return {"stored": 0}
    admins = await get_admins(client_id)
    months = await retention_months(client_id)
    stored, skipped, new_docs = 0, 0, []
    async with _lock(client_id):
        state = await db.security_chain_state.find_one({"client_id": client_id}, {"_id": 0}) or {"client_id": client_id, "last_seq": 0, "last_hash": "GENESIS"}
        seq, prev = int(state["last_seq"]), state["last_hash"]
        for ev in events:
            doc = _normalize(client_id, agent_id, host, ev)
            if not doc or _noise(doc):
                skipped += 1
                continue
            if doc["record_id"] and await db.security_events.find_one(
                    {"client_id": client_id, "host": doc["host"], "log": doc["log"], "record_id": doc["record_id"]}, {"_id": 1}):
                skipped += 1
                continue
            seq += 1
            doc["seq"] = seq
            doc["is_admin"] = doc["event_id"] == 4672 or doc["user"].lower() in admins or (doc.get("subject_user") or "").lower() in admins
            doc["prev_hash"] = prev
            doc["hash"] = event_hash(prev, doc)
            try:
                tsd = datetime.fromisoformat(doc["ts"].replace("Z", "+00:00"))
            except ValueError:
                tsd = _now()
            doc["expire_at"] = tsd + timedelta(days=30 * months)
            doc["ingested_at"] = _now().isoformat()
            await db.security_events.insert_one(dict(doc))
            prev = doc["hash"]
            stored += 1
            new_docs.append(doc)
        await db.security_chain_state.update_one({"client_id": client_id}, {"$set": {"last_seq": seq, "last_hash": prev, "updated_at": _now().isoformat()}}, upsert=True)
    if new_docs:
        try:
            await _evaluate_alerts(client_id, host, new_docs)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"seclog alerts {client_id}: {e}")
    return {"stored": stored, "skipped": skipped, "last_seq": seq}


async def verify_chain(client_id: str, host: Optional[str] = None) -> dict:
    """Ricalcola la catena hash dell'intero registro cliente: ok=True se nessun evento è stato alterato/rimosso."""
    prev, n, last_seq = "GENESIS", 0, 0
    q = {"client_id": client_id}
    async for d in db.security_events.find(q, {"_id": 0}).sort("seq", 1):
        n += 1
        if d.get("seq") != last_seq + 1:
            return {"ok": False, "checked": n, "broken_at_seq": d.get("seq"), "reason": f"sequenza interrotta: atteso {last_seq + 1}, trovato {d.get('seq')} (evento rimosso?)"}
        if d.get("prev_hash") != prev or event_hash(prev, d) != d.get("hash"):
            return {"ok": False, "checked": n, "broken_at_seq": d.get("seq"), "reason": "hash non corrispondente: evento alterato"}
        prev, last_seq = d["hash"], d["seq"]
    state = await db.security_chain_state.find_one({"client_id": client_id}, {"_id": 0})
    tail_ok = not state or (state.get("last_hash") == prev and int(state.get("last_seq", 0)) == last_seq)
    return {"ok": tail_ok, "checked": n, "last_seq": last_seq, "last_hash": prev,
            "reason": None if tail_ok else "stato catena non coincide con l'ultimo evento (eventi in coda rimossi?)"}


async def _emit(client_id: str, host: str, severity: str, title: str, message: str, source_type: str, user: str = "") -> None:
    if await db.alerts.find_one({"client_id": client_id, "title": title, "status": "active"}, {"_id": 1}):
        return
    from alert_filter import insert_alert_if_emit
    alert = {"id": str(uuid.uuid4()), "client_id": client_id, "device_ip": host, "device_name": host, "device_type": "server",
             "severity": severity, "source_type": source_type, "title": title, "message": message, "status": "active",
             "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": _now().isoformat(),
             "instant": severity == "critical", "force_telegram": severity in ("critical", "high")}
    if await insert_alert_if_emit(db, alert):
        try:
            from alert_engine import notify_alert_telegram
            await notify_alert_telegram(db, alert)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"seclog telegram: {e}")
        try:
            import webpush as _wp
            await _wp.notify_new_alert(db, alert)
        except Exception:  # noqa: BLE001
            pass


async def _evaluate_alerts(client_id: str, host: str, docs: list[dict]) -> None:
    for d in docs:
        h = d.get("host") or host
        if d["category"] == "log_cleared":
            await _emit(client_id, h, "critical", f"REGISTRO EVENTI CANCELLATO su {h}",
                        f"L'utente {d.get('subject_user') or d.get('user') or '?'} ha cancellato il registro {d['log']} su {h} (Event {d['event_id']}). "
                        f"Possibile copertura tracce: verificare subito.", "seclog_log_cleared")
        elif d["category"] == "account_created":
            await _emit(client_id, h, "high", f"Nuovo account {d['user']} creato su {h}",
                        f"Account '{d['user']}' creato da {d.get('subject_user') or '?'} su {h}. Se non previsto, possibile persistenza di un attaccante.", "seclog_account_created")
        elif d["category"] == "group_change" and d["event_id"] in (4728, 4732, 4756):
            grp = (d.get("group") or "").lower()
            if any(k in grp for k in ("admin", "amministrator", "domain admins", "enterprise")):
                await _emit(client_id, h, "high", f"Utente aggiunto a gruppo amministrativo su {h}: {d.get('target_user') or d['user']}",
                            f"{d.get('subject_user') or '?'} ha aggiunto {d.get('target_user') or d['user']} al gruppo '{d.get('group')}' su {h}.", "seclog_admin_group_add")
        elif d["category"] == "lockout":
            if d["event_id"] == 4740:
                await _emit(client_id, h, "medium", f"Account bloccato: {d['user']} su {h}",
                            f"L'account {d['user']} è stato bloccato per troppi tentativi falliti (origine {d.get('workstation') or d.get('src_ip') or '?'}).", "seclog_lockout")
    # brute force: ≥10 accessi falliti in 5 minuti sullo stesso host (per utente o per IP sorgente)
    failed = [d for d in docs if d["category"] == "logon_failed"]
    if failed:
        since = (_now() - timedelta(minutes=5)).isoformat()
        rows = await db.security_events.find({"client_id": client_id, "host": host, "category": "logon_failed", "ts": {"$gte": since}},
                                             {"_id": 0, "user": 1, "src_ip": 1}).to_list(2000)
        by_user: dict[str, int] = {}
        by_ip: dict[str, int] = {}
        for r in rows:
            by_user[r.get("user") or "?"] = by_user.get(r.get("user") or "?", 0) + 1
            if r.get("src_ip"):
                by_ip[r["src_ip"]] = by_ip.get(r["src_ip"], 0) + 1
        for u, n in by_user.items():
            if n >= 10:
                await _emit(client_id, host, "high", f"Brute-force su {host}: {n} accessi falliti per {u}",
                            f"{n} tentativi di accesso falliti in 5 minuti per l'utente '{u}' su {host}. Origini: {', '.join(sorted(by_ip)[:5]) or 'locale'}.", "seclog_bruteforce")
        for ip, n in by_ip.items():
            if n >= 10:
                await _emit(client_id, host, "high", f"Brute-force su {host} da {ip}: {n} accessi falliti",
                            f"{n} tentativi falliti in 5 minuti da {ip} verso {host} (utenti: {', '.join(sorted(by_user)[:5])}).", "seclog_bruteforce")


async def ensure_indexes() -> None:
    await db.security_events.create_index([("client_id", 1), ("seq", 1)], unique=True)
    await db.security_events.create_index([("client_id", 1), ("host", 1), ("log", 1), ("record_id", 1)])
    await db.security_events.create_index([("client_id", 1), ("ts", -1)])
    await db.security_events.create_index([("client_id", 1), ("category", 1), ("ts", -1)])
    await db.security_events.create_index([("client_id", 1), ("user", 1)])
    await db.security_events.create_index("expire_at", expireAfterSeconds=0)
    await db.security_chain_state.create_index("client_id", unique=True)
