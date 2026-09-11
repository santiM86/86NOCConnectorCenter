"""Diagnosi spegnimento: un PC offline è stato spento volutamente o è crashato?

Prove (tutte passive, nessun pacchetto verso il PC):
  1. Porta dello switch a cui è collegato (FDB → switch/porta; stato+velocità porta):
       DOWN            → spento senza WoL o cavo scollegato
       UP a 10/100 Mbps (baseline 1G) → spento con NIC in standby (spegnimento pulito)
       UP a piena velocità ma nessuna risposta → acceso ma bloccato/crash (o firewall)
  2. Orario abituale: storico dei down (device_status_events + alert offline) → il down
     è avvenuto in una fascia in cui il PC va giù di solito? Fallback: orario lavorativo.
  3. Datto RMM: agente online adesso? ultimo contatto coerente con l'ora dello spegnimento?

`record_status_transitions_tick` (cron 60s) alimenta lo storico e la baseline velocità porta.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MIN_HISTORY_EVENTS = 5
DOWN_DEBOUNCE_MIN = 3
BUSINESS_HOURS = (7, 19)  # fallback quando lo storico è insufficiente


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:  # epoch (secondi o ms) — Datto lastSeen
        f = float(v)
        if f > 1e12:
            f /= 1000
        return datetime.fromtimestamp(f, tz=timezone.utc)
    except Exception:
        return None


def _norm_mac(m) -> str:
    return re.sub(r"[^0-9A-F]", "", str(m or "").upper())


def _fmt_dt(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------
# Cron: registra le transizioni up/down + baseline velocità porta
# ---------------------------------------------------------------------------
async def record_status_transitions_tick(db) -> dict:
    now = _now()
    now_iso = now.isoformat()
    cur = db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "device_ip": 1, "reachable": 1, "unreachable_since": 1,
             "last_reachable_at": 1, "last_poll": 1, "last_poll_at": 1, "primary_mac": 1, "device_macs": 1})
    states = {}
    async for s in db.device_status_state.find({}, {"_id": 0}):
        states[(s.get("client_id"), s.get("device_ip"))] = s
    flips = 0
    baselines = 0
    async for pd in cur:
        cid, ip = pd.get("client_id"), pd.get("device_ip")
        if not cid or not ip or pd.get("reachable") is None:
            continue
        reachable = bool(pd.get("reachable"))
        st = states.get((cid, ip))
        if reachable:
            upd: dict = {"reachable": True, "last_seen_up_at": now_iso, "updated_at": now_iso}
            # baseline velocità porta mentre il PC è acceso (refresh max ogni 15 min per device)
            last_bl = _parse((st or {}).get("baseline_at"))
            port = None
            if not last_bl or (now - last_bl) > timedelta(minutes=15):
                port = await find_switch_port(db, cid, ip, pd.get("primary_mac") or _first_mac(pd.get("device_macs")))
                upd["baseline_at"] = now_iso
            if port and port.get("oper") == "up" and (port.get("speed_mbps") or 0) > 0:
                upd["usual_speed_mbps"] = max(int(port["speed_mbps"]), int((st or {}).get("usual_speed_mbps") or 0))
                upd["port_ref"] = {"switch_ip": port["switch_ip"], "port": port["port"], "name": port.get("name")}
                baselines += 1
            if st is None or st.get("reachable") is False:
                if st is not None:
                    since = _parse(st.get("since"))
                    await db.device_status_events.insert_one({
                        "client_id": cid, "device_ip": ip, "event": "up", "at": now_iso,
                        "duration_s": int((now - since).total_seconds()) if since else None})
                    flips += 1
                upd["since"] = now_iso
            await db.device_status_state.update_one({"client_id": cid, "device_ip": ip}, {"$set": upd}, upsert=True)
        else:
            down_at = _parse(pd.get("unreachable_since")) or _parse(pd.get("last_reachable_at")) or now
            if (now - down_at) < timedelta(minutes=DOWN_DEBOUNCE_MIN):
                continue  # anti-flap: aspettiamo che il down sia confermato
            if st is None or st.get("reachable") is not False:
                up_since = _parse((st or {}).get("since"))
                await db.device_status_events.insert_one({
                    "client_id": cid, "device_ip": ip, "event": "down", "at": down_at.isoformat(),
                    "duration_s": int((down_at - up_since).total_seconds()) if up_since else None})
                flips += 1
                await db.device_status_state.update_one(
                    {"client_id": cid, "device_ip": ip},
                    {"$set": {"reachable": False, "since": down_at.isoformat(), "updated_at": now_iso}}, upsert=True)
    return {"flips": flips, "baselines": baselines}


def _first_mac(macs) -> Optional[str]:
    if isinstance(macs, list) and macs:
        f = macs[0]
        return f.get("mac") if isinstance(f, dict) else f
    return None


# ---------------------------------------------------------------------------
# Prova 1 — porta switch
# ---------------------------------------------------------------------------
async def _device_mac(db, client_id: str, ip: str, hint: Optional[str]) -> Optional[str]:
    if hint:
        return _norm_mac(hint)
    md = await db.managed_devices.find_one(
        {"client_id": client_id, "$or": [{"ip": ip}, {"ip_address": ip}]}, {"_id": 0, "mac": 1, "primary_mac": 1})
    for k in ("primary_mac", "mac"):
        if md and md.get(k):
            return _norm_mac(md[k])
    arp = await db.arp_cache.find_one({"client_id": client_id, "ip": ip}, {"_id": 0, "mac": 1}, sort=[("last_seen", -1)])
    if arp and arp.get("mac"):
        return _norm_mac(arp["mac"])
    ep = await db.discovered_endpoints.find_one(
        {"client_id": client_id, "ip": ip, "mac": {"$nin": [None, ""]}}, {"_id": 0, "mac": 1})
    return _norm_mac(ep["mac"]) if ep else None


async def find_switch_port(db, client_id: str, ip: str, mac_hint: Optional[str] = None) -> Optional[dict]:
    """Ritorna {switch_ip, port, name, oper, speed_mbps, admin, updated_at, mac_count} o None.
    Tra più porte candidate sceglie quella con meno MAC (le porte con molti MAC sono uplink)."""
    cands = [e async for e in db.discovered_endpoints.find(
        {"client_id": client_id, "ip": ip, "switch_ip": {"$nin": [None, ""]}, "port": {"$ne": None}},
        {"_id": 0, "switch_ip": 1, "port": 1, "mac": 1})]
    mac = await _device_mac(db, client_id, ip, mac_hint)
    if not cands and mac:
        async for e in db.discovered_endpoints.find(
                {"client_id": client_id, "switch_ip": {"$nin": [None, ""]}, "port": {"$ne": None}, "mac": {"$nin": [None, ""]}},
                {"_id": 0, "switch_ip": 1, "port": 1, "mac": 1}):
            if _norm_mac(e.get("mac")) == mac:
                cands.append(e)
    if not cands:
        return None
    best = None
    for c in cands:
        try:
            port_idx = int(c["port"])
        except Exception:
            continue
        mac_count = await db.discovered_endpoints.count_documents(
            {"client_id": client_id, "switch_ip": c["switch_ip"], "port": c["port"]})
        if best is None or mac_count < best[0]:
            best = (mac_count, c["switch_ip"], port_idx)
    if not best:
        return None
    mac_count, sw_ip, port_idx = best
    pdoc = await db.switch_ports.find_one(
        {"client_id": client_id, "local_ip": sw_ip, "idx": port_idx}, {"_id": 0}, sort=[("updated_at", -1)])
    oper = (pdoc or {}).get("oper")
    if oper is not None:  # ifOperStatus può arrivare come int (1=up, 2=down) o stringa
        oper = "up" if str(oper).lower() in ("1", "up") else "down"
    sw = await db.managed_devices.find_one(
        {"client_id": client_id, "$or": [{"ip": sw_ip}, {"ip_address": sw_ip}]}, {"_id": 0, "name": 1, "hostname": 1})
    return {
        "switch_ip": sw_ip, "switch_name": (sw or {}).get("name") or (sw or {}).get("hostname") or sw_ip,
        "port": port_idx, "name": (pdoc or {}).get("name") or f"port {port_idx}",
        "oper": oper, "admin": (pdoc or {}).get("admin"),
        "speed_mbps": (pdoc or {}).get("speed_mbps"), "updated_at": (pdoc or {}).get("updated_at"),
        "mac_count": mac_count, "has_port_data": pdoc is not None,
    }


def _port_signal(port: Optional[dict], usual_speed: Optional[int]) -> tuple[str, dict]:
    """→ (signal, evidence). signal ∈ down | low_speed | up_full | up_unknown_speed | unknown"""
    if not port:
        return "unknown", {"kind": "port", "level": "na", "title": "Porta switch",
                           "text": "Nessuna porta switch associata (FDB non disponibile per questo MAC)."}
    where = f"{port['switch_name']} · {port['name']}"
    if not port.get("has_port_data"):
        return "unknown", {"kind": "port", "level": "na", "title": "Porta switch", "where": where,
                           "text": "Porta individuata ma stato/velocità non ancora letti via SNMP."}
    speed = port.get("speed_mbps") or 0
    if port.get("oper") != "up":
        return "down", {"kind": "port", "level": "warn", "title": "Porta switch: LINK DOWN", "where": where,
                        "text": "La porta non ha link: PC spento senza Wake-on-LAN, oppure cavo scollegato."}
    if usual_speed and speed and speed < usual_speed:
        return "low_speed", {"kind": "port", "level": "ok", "title": f"Porta switch: UP a {_fmt_speed(speed)} (di solito {_fmt_speed(usual_speed)})",
                             "where": where,
                             "text": "La scheda di rete è in standby a bassa velocità: tipico di un PC spento correttamente (WoL attivo)."}
    if speed and speed <= 100 and not usual_speed:
        return "low_speed", {"kind": "port", "level": "ok", "title": f"Porta switch: UP a {_fmt_speed(speed)}", "where": where,
                             "text": "Link a bassa velocità senza baseline: compatibile con NIC in standby (PC spento)."}
    if speed:
        return "up_full", {"kind": "port", "level": "crit", "title": f"Porta switch: UP a {_fmt_speed(speed)} ma il PC non risponde",
                           "where": where,
                           "text": "Link attivo a piena velocità: il PC è alimentato e acceso ma non risponde → probabile blocco/crash del sistema operativo (o firewall che blocca ICMP)."}
    return "up_unknown_speed", {"kind": "port", "level": "info", "title": "Porta switch: UP (velocità n/d)", "where": where,
                                "text": "La porta ha link ma la velocità non è nota: PC alimentato (acceso o in standby)."}


def _fmt_speed(mbps: int) -> str:
    return f"{mbps / 1000:g} Gbps" if mbps >= 1000 else f"{mbps} Mbps"


# ---------------------------------------------------------------------------
# Prova 2 — orario abituale
# ---------------------------------------------------------------------------
async def _down_history(db, client_id: str, ip: str, days: int = 90) -> list[datetime]:
    cutoff = (_now() - timedelta(days=days)).isoformat()
    downs: list[datetime] = []
    async for e in db.device_status_events.find(
            {"client_id": client_id, "device_ip": ip, "event": "down", "at": {"$gte": cutoff}}, {"_id": 0, "at": 1}):
        d = _parse(e.get("at"))
        if d:
            downs.append(d)
    # Storico pregresso: alert offline del device (created_at = inizio down)
    async for a in db.alerts.find(
            {"client_id": client_id, "device_ip": ip, "created_at": {"$gte": cutoff},
             "$or": [{"source_type": {"$in": ["vital_device_offline", "device_offline", "host_down"]}},
                     {"title": {"$regex": "offline|non raggiungibile|down", "$options": "i"}}]},
            {"_id": 0, "created_at": 1}):
        d = _parse(a.get("created_at"))
        if d:
            downs.append(d)
    # dedup su finestra 10 min
    downs.sort()
    out: list[datetime] = []
    for d in downs:
        if not out or (d - out[-1]) > timedelta(minutes=10):
            out.append(d)
    return out


def _local(d: datetime) -> datetime:
    # orario Italia (CET/CEST) approssimato: UTC+1 / UTC+2 in base al DST europeo
    y = d.year
    # ultima domenica di marzo / ottobre
    def last_sunday(month):
        dt = datetime(y, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        return dt - timedelta(days=(dt.weekday() + 1) % 7)
    dst = last_sunday(3).replace(hour=1) <= d < last_sunday(10).replace(hour=1)
    return d + timedelta(hours=2 if dst else 1)


def _schedule_signal(downs: list[datetime], offline_since: Optional[datetime]) -> tuple[str, dict, dict]:
    """→ (signal, evidence, summary). signal ∈ usual | unusual | unknown"""
    if not offline_since:
        return "unknown", {"kind": "schedule", "level": "na", "title": "Orario abituale",
                           "text": "Ora di inizio offline non disponibile."}, {}
    loc = _local(offline_since)
    weekend = loc.weekday() >= 5
    when = loc.strftime("%a %d/%m %H:%M")
    if len(downs) >= MIN_HISTORY_EVENTS:
        same_kind = [_local(d) for d in downs if (_local(d).weekday() >= 5) == weekend]
        hours = Counter(x.hour for x in same_kind)
        near = sum(1 for x in same_kind if min(abs(x.hour - loc.hour), 24 - abs(x.hour - loc.hour)) <= 1)
        ratio = near / len(same_kind) if same_kind else 0
        top = [f"{h:02d}:00" for h, _ in hours.most_common(2)]
        summary = {"events": len(downs), "days": 90, "typical_hours": top,
                   "kind": "weekend" if weekend else "weekday", "match_ratio": round(ratio, 2)}
        if same_kind and ratio >= 0.3:
            return "usual", {"kind": "schedule", "level": "ok", "title": f"Spento in orario abituale ({when})",
                             "text": f"Negli ultimi 90 giorni il PC è andato giù {len(downs)} volte; il {int(ratio * 100)}% dei casi "
                                     f"{'nel weekend' if weekend else 'nei giorni lavorativi'} è intorno alle {', '.join(top)}. Coerente con uno spegnimento di routine."}, summary
        return "unusual", {"kind": "schedule", "level": "warn", "title": f"Orario anomalo ({when})",
                           "text": f"Di solito questo PC va giù intorno alle {', '.join(top) or 'n/d'}; questo down è fuori dallo schema abituale."}, summary
    # fallback orario lavorativo
    summary = {"events": len(downs), "days": 90, "typical_hours": [], "fallback": "business_hours"}
    in_business = (not weekend) and BUSINESS_HOURS[0] <= loc.hour < BUSINESS_HOURS[1]
    if in_business:
        return "unusual", {"kind": "schedule", "level": "warn", "title": f"Caduto in orario lavorativo ({when})",
                           "text": f"Storico insufficiente ({len(downs)}/{MIN_HISTORY_EVENTS} spegnimenti registrati): uso la fascia lavorativa "
                                   f"{BUSINESS_HOURS[0]:02d}-{BUSINESS_HOURS[1]:02d}. Un down a quest'ora è inatteso."}, summary
    return "usual", {"kind": "schedule", "level": "ok", "title": f"Spento fuori orario lavorativo ({when})",
                     "text": f"Storico insufficiente ({len(downs)}/{MIN_HISTORY_EVENTS} spegnimenti registrati): uso la fascia lavorativa "
                             f"{BUSINESS_HOURS[0]:02d}-{BUSINESS_HOURS[1]:02d}. Spegnimento serale/notturno o nel weekend: plausibilmente voluto."}, summary


# ---------------------------------------------------------------------------
# Prova 3 — Datto RMM
# ---------------------------------------------------------------------------
async def _datto_signal(db, client_id: str, ip: str, offline_since: Optional[datetime]) -> tuple[str, dict]:
    """→ signal ∈ online_now | last_seen_matches | last_seen_earlier | unknown"""
    md = await db.managed_devices.find_one(
        {"client_id": client_id, "$or": [{"ip": ip}, {"ip_address": ip}]}, {"_id": 0, "datto_uid": 1, "datto_name": 1})
    uid = (md or {}).get("datto_uid")
    dd = None
    if uid:
        dd = await db.datto_devices.find_one({"uid": uid}, {"_id": 0, "online": 1, "datto_last_seen": 1, "fetched_at": 1, "name": 1})
    if not dd:
        dd = await db.datto_devices.find_one(
            {"client_id": client_id, "$or": [{"ip": ip}, {"ip_list": ip}]},
            {"_id": 0, "online": 1, "datto_last_seen": 1, "fetched_at": 1, "name": 1})
    if not dd:
        return "unknown", {"kind": "datto", "level": "na", "title": "Datto RMM",
                           "text": "Nessun agente Datto associato a questo dispositivo."}
    last_seen = _parse(dd.get("datto_last_seen"))
    fetched = _parse(dd.get("fetched_at"))
    name = dd.get("name") or (md or {}).get("datto_name") or ""
    sync_note = f" (sync Datto: {_local(fetched).strftime('%d/%m %H:%M')})" if fetched else ""
    if dd.get("online") and fetched and (_now() - fetched) < timedelta(minutes=30):
        return "online_now", {"kind": "datto", "level": "crit", "title": f"Datto: agente ONLINE su {name}",
                              "text": "L'agente Datto RMM risponde: il PC è acceso e connesso a Internet. Se non risponde al ping è un firewall/ICMP bloccato o un problema di rete locale, non uno spegnimento." + sync_note}
    if last_seen and offline_since:
        delta = abs((last_seen - offline_since).total_seconds())
        ls = _local(last_seen).strftime("%d/%m %H:%M")
        if delta <= 15 * 60:
            return "last_seen_matches", {"kind": "datto", "level": "info", "title": f"Datto: ultimo contatto {ls}",
                                         "text": "L'agente Datto ha smesso di rispondere nello stesso momento in cui è sparito il ping: il sistema operativo era vivo fino a quel momento e si è fermato tutto insieme (spegnimento o blocco totale)." + sync_note}
        if last_seen > offline_since:
            return "seen_after", {"kind": "datto", "level": "warn", "title": f"Datto: visto DOPO l'offline ({ls})",
                                  "text": "Datto ha avuto contatto con il PC dopo l'inizio dell'offline: il PC è (o è stato) acceso ma non raggiungibile dalla nostra rete di monitoraggio." + sync_note}
        return "last_seen_earlier", {"kind": "datto", "level": "info", "title": f"Datto: ultimo contatto {ls}",
                                     "text": "L'agente Datto era già silente prima del ping perso: servizio agente fermo o PC in sospensione prima dello spegnimento." + sync_note}
    return "unknown", {"kind": "datto", "level": "na", "title": f"Datto: {name}",
                       "text": "Agente associato ma nessun dato lastSeen utile." + sync_note}


# ---------------------------------------------------------------------------
# Verdetto
# ---------------------------------------------------------------------------
VERDICTS = {
    "online": ("Online", "Il dispositivo risponde: nessuna diagnosi necessaria."),
    "reachable_elsewhere": ("Acceso ma non raggiungibile", "Il PC è acceso (lo vede Datto) ma non risponde al monitoraggio: firewall, ICMP bloccato o problema di rete locale."),
    "intentional": ("Spento volutamente", "Le prove indicano uno spegnimento regolare da parte dell'utente."),
    "crash": ("Guasto / bloccato", "Il PC risulta alimentato ma non risponde: probabile crash, freeze o blocco del sistema operativo."),
    "disconnected": ("Spento o scollegato", "Nessun link sulla porta: PC spento senza WoL oppure cavo/alimentazione scollegati."),
    "unknown": ("Non determinabile", "Prove insufficienti: manca la porta switch e lo storico è scarso."),
}


def _combine(port_sig: str, sched_sig: str, datto_sig: str) -> tuple[str, int]:
    if datto_sig in ("online_now", "seen_after"):
        return "reachable_elsewhere", 90 if datto_sig == "online_now" else 70
    sched_bonus = {"usual": 10, "unusual": -10, "unknown": 0}[sched_sig]
    if port_sig == "low_speed":
        return "intentional", min(95, 85 + sched_bonus)
    if port_sig == "up_full":
        conf = 75 - sched_bonus  # orario anomalo rafforza il crash
        if datto_sig == "last_seen_matches":
            conf += 5
        return "crash", min(95, conf)
    if port_sig == "down":
        if sched_sig == "usual":
            return "intentional", 70
        if sched_sig == "unusual":
            return "disconnected", 60
        return "disconnected", 55
    if port_sig == "up_unknown_speed":
        return ("intentional", 55) if sched_sig == "usual" else ("crash", 50)
    # nessuna porta
    if sched_sig == "usual":
        return "intentional", 55
    if sched_sig == "unusual":
        return "crash", 45
    return "unknown", 0


async def diagnose(db, client_id: str, ip: str) -> dict:
    pd = await db.device_poll_status.find_one(
        {"client_id": client_id, "device_ip": ip},
        {"_id": 0, "reachable": 1, "unreachable_since": 1, "last_reachable_at": 1, "primary_mac": 1, "device_macs": 1}) or {}
    st = await db.device_status_state.find_one({"client_id": client_id, "device_ip": ip}, {"_id": 0}) or {}
    offline_since = _parse(pd.get("unreachable_since")) or (_parse(st.get("since")) if st.get("reachable") is False else None) \
        or _parse(pd.get("last_reachable_at"))
    base = {"device_ip": ip, "client_id": client_id, "offline_since": _fmt_dt(offline_since),
            "computed_at": _now().isoformat()}
    if pd.get("reachable") is True:
        return {**base, "verdict": "online", "confidence": 100, "label": VERDICTS["online"][0],
                "summary": VERDICTS["online"][1], "evidence": []}

    port = await find_switch_port(db, client_id, ip, pd.get("primary_mac") or _first_mac(pd.get("device_macs")))
    port_sig, port_ev = _port_signal(port, st.get("usual_speed_mbps"))
    downs = await _down_history(db, client_id, ip)
    sched_sig, sched_ev, history = _schedule_signal(downs, offline_since)
    # Memoria porte: se lo storico del device è scarso ma la PORTA ha abitudini apprese, usale
    if port and history.get("fallback") == "business_hours":
        try:
            from port_memory import classify_port
            habit = await classify_port(db, client_id, port["switch_ip"], port["port"], False)
            if habit.get("verdict") in ("habitual", "anomalous"):
                sched_sig = "usual" if habit["verdict"] == "habitual" else "unusual"
                sched_ev = {"kind": "schedule", "level": "ok" if sched_sig == "usual" else "warn",
                            "title": f"Abitudine porta switch: {habit.get('label')}", "where": f"{port['switch_name']} · {port['name']}",
                            "text": habit.get("reason", "")}
                history = {**history, "source": "port_memory", "profile": habit.get("profile")}
        except Exception:  # noqa: BLE001
            pass
    datto_sig, datto_ev = await _datto_signal(db, client_id, ip, offline_since)
    verdict, conf = _combine(port_sig, sched_sig, datto_sig)
    label, summary = VERDICTS[verdict]
    return {
        **base, "verdict": verdict, "confidence": conf, "label": label, "summary": summary,
        "signals": {"port": port_sig, "schedule": sched_sig, "datto": datto_sig},
        "evidence": [port_ev, sched_ev, datto_ev],
        "port": port, "history": history,
    }
