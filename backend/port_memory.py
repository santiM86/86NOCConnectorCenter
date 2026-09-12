"""Memoria porte switch: abitudini per porta (istogramma ora-della-settimana), ultimo
device collegato, velocità/PoE abituali → classifica un LINK DOWN come abituale,
anomalo, standby PoE, inutilizzato o "in apprendimento".

Doc `port_memory` (uno per porta): {client_id, local_ip, idx, name, first_seen, samples,
up_samples, how_up[168], how_total[168], usual_speed_mbps, usual_poe_w, poe_samples,
last_up_at, last_down_at, last_device{mac, ip, name, seen_at}, updated_at}
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("port_memory")

LEARNING_DAYS = 7          # default; configurabile (alert_engine_config.port_memory_learning_days) via refresh_learning_days()
_LD_CACHE = {"at": None}


async def refresh_learning_days(db) -> int:
    """Legge la configurazione (cache 60s) e aggiorna LEARNING_DAYS."""
    global LEARNING_DAYS
    now = _now()
    if _LD_CACHE["at"] and (now - _LD_CACHE["at"]).total_seconds() < 60:
        return LEARNING_DAYS
    cfg = await db.alert_engine_config.find_one({"_id": "global"}, {"port_memory_learning_days": 1})
    try:
        v = int((cfg or {}).get("port_memory_learning_days") or 7)
        LEARNING_DAYS = min(max(v, 1), 60)
    except (TypeError, ValueError):
        LEARNING_DAYS = 7
    _LD_CACHE["at"] = now
    return LEARNING_DAYS
ALWAYS_ON_RATIO = 0.95
SPORADIC_RATIO = 0.12   # <~20h/settimana → uso occasionale (un PC 8-18 lun-ven è ~30%)
DEVICE_REFRESH_MIN = 15
POE_STANDBY_MIN_W = 0.5

PROFILE_LABELS = {
    "learning": "In apprendimento", "always_on": "Sempre attiva", "scheduled": "A orario",
    "sporadic": "Saltuaria", "unused": "Mai usata",
}
VERDICT_LABELS = {
    "habitual": "Abituale", "anomalous": "Anomalo", "standby_poe": "Standby PoE",
    "unused": "Inutilizzata", "learning": "In apprendimento", "up": "Attiva",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(v) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _local(d: datetime) -> datetime:
    y = d.year

    def last_sunday(month):
        dt = datetime(y, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        return dt - timedelta(days=(dt.weekday() + 1) % 7)
    dst = last_sunday(3).replace(hour=1) <= d < last_sunday(10).replace(hour=1)
    return d + timedelta(hours=2 if dst else 1)


def _how(d: datetime) -> int:
    loc = _local(d)
    return loc.weekday() * 24 + loc.hour


FIXED_HOLIDAYS = {
    (1, 1): "Capodanno", (1, 6): "Epifania", (4, 25): "Festa della Liberazione", (5, 1): "Festa dei Lavoratori",
    (6, 2): "Festa della Repubblica", (8, 15): "Ferragosto", (11, 1): "Ognissanti", (12, 8): "Immacolata",
    (12, 25): "Natale", (12, 26): "Santo Stefano",
}


def _easter(y: int):
    a, b, c = y % 19, y // 100, y % 100
    d, e, f, g = b // 4, b % 4, (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(y, month, day, tzinfo=timezone.utc).date()


def is_italian_holiday(d: Optional[datetime] = None) -> Optional[str]:
    """Nome della festività nazionale italiana (ora locale) oppure None."""
    loc = _local(d or _now()).date()
    name = FIXED_HOLIDAYS.get((loc.month, loc.day))
    if name:
        return name
    if loc == _easter(loc.year) + timedelta(days=1):
        return "Lunedì dell'Angelo"
    return None


DAY_LABELS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]


def schedule_summary(mem: Optional[dict]) -> dict:
    """{Lun: "08-18", Mar: "08-18, 20-22", Sab: "—"} dalle ore con up ratio ≥ 50%."""
    if not mem:
        return {}
    how_up = mem.get("how_up") or {}
    how_total = mem.get("how_total") or {}
    out = {}
    for d in range(7):
        hours = []
        for h in range(24):
            k = str(d * 24 + h)
            t = int(how_total.get(k) or 0)
            if t and int(how_up.get(k) or 0) / t >= 0.5:
                hours.append(h)
        ranges, start = [], None
        for h in range(25):
            if h in hours and start is None:
                start = h
            elif h not in hours and start is not None:
                ranges.append(f"{start:02d}-{h:02d}")
                start = None
        out[DAY_LABELS[d]] = ", ".join(ranges) if ranges else "—"
    return out


async def record_ports(db, client_id: str, local_ip: str, ports: list) -> int:
    """Chiamata da store_switch_ports dopo ogni poll: aggiorna gli istogrammi per porta."""
    now = _now()
    await refresh_learning_days(db)
    now_iso = now.isoformat()
    b = _how(now)
    holiday = is_italian_holiday(now)  # festivo: non insegna abitudini (giornata non rappresentativa)
    n = 0
    for p in ports:
        try:
            idx = int(p.get("idx"))
        except Exception:
            continue
        if int(p.get("admin", 1) or 1) == 2:
            continue  # admin-down: scelta dell'amministratore, non abitudine
        up = int(p.get("oper", 0) or 0) == 1
        speed = int(p.get("speed_mbps", 0) or 0)
        poe_w = float(p.get("poe_watt", 0) or 0)
        q = {"client_id": client_id, "local_ip": local_ip, "idx": idx}
        inc = {} if holiday else {"samples": 1, f"how_total.{b}": 1}
        setv = {"name": p.get("name") or f"port{idx}", "updated_at": now_iso, "last_oper_up": up,
                "last_poe_w": poe_w, "last_speed_mbps": speed}
        if up:
            if not holiday:
                inc["up_samples"] = 1
                inc[f"how_up.{b}"] = 1
            setv["last_up_at"] = now_iso
            if poe_w > 0:
                inc["poe_samples"] = 1
                inc["poe_w_sum"] = poe_w
        else:
            setv["last_down_at"] = now_iso
        upd = {"$set": setv, "$setOnInsert": {"first_seen": now_iso}}
        if inc:
            upd["$inc"] = inc
        if up and speed > 0:
            upd["$max"] = {"usual_speed_mbps": speed}
        await db.port_memory.update_one(q, upd, upsert=True)
        n += 1
    # aggiorna "ultimo device" (FDB) solo per porte UP, max ogni 15 min
    try:
        await _refresh_devices(db, client_id, local_ip, [p for p in ports if int(p.get("oper", 0) or 0) == 1], now)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"port_memory refresh devices {local_ip}: {e}")
    return n


async def _refresh_devices(db, client_id: str, local_ip: str, up_ports: list, now: datetime) -> None:
    if not up_ports:
        return
    cutoff = (now - timedelta(minutes=DEVICE_REFRESH_MIN)).isoformat()
    stale_docs = {m["idx"]: m async for m in db.port_memory.find(
        {"client_id": client_id, "local_ip": local_ip,
         "$or": [{"device_refreshed_at": {"$exists": False}}, {"device_refreshed_at": {"$lt": cutoff}}]},
        {"_id": 0, "idx": 1, "last_device": 1, "first_seen": 1, "name": 1, "authorized_devices": 1})}
    stale = set(stale_docs)
    if not stale:
        return
    counts: dict = {}
    macs: dict = {}
    async for e in db.discovered_endpoints.find(
            {"client_id": client_id, "switch_ip": local_ip, "port": {"$in": list(stale)}},
            {"_id": 0, "port": 1, "mac": 1, "ip": 1, "hostname": 1, "datto_name": 1}):
        try:
            pi = int(e.get("port"))
        except Exception:
            continue
        counts[pi] = counts.get(pi, 0) + 1
        if e.get("mac") and pi not in macs:
            macs[pi] = {"mac": str(e.get("mac")).upper(), "ip": e.get("ip") or "", "hostname": e.get("hostname") or e.get("datto_name") or ""}
    for pi in stale:
        setv = {"device_refreshed_at": now.isoformat()}
        d = macs.get(pi)
        if d and counts.get(pi, 0) <= 3:  # >3 MAC = uplink/trunk: non ha "un" device
            name = d.get("hostname") or ""
            if d["ip"]:
                md = await db.managed_devices.find_one(
                    {"client_id": client_id, "$or": [{"ip": d["ip"]}, {"ip_address": d["ip"]}]}, {"_id": 0, "name": 1, "hostname": 1})
                name = (md or {}).get("name") or (md or {}).get("hostname") or name
            setv["last_device"] = {"mac": d["mac"], "ip": d["ip"], "name": name, "seen_at": now.isoformat()}
            old = (stale_docs.get(pi) or {}).get("last_device") or {}
            first = _parse((stale_docs.get(pi) or {}).get("first_seen"))
            known = first is not None and (now - first).total_seconds() >= LEARNING_DAYS * 86400
            authorized = {a.get("mac") for a in ((stale_docs.get(pi) or {}).get("authorized_devices") or [])}
            if old.get("mac") and old["mac"] != d["mac"] and known and d["mac"] not in authorized:
                setv["prev_device"] = old
                setv["device_changed_at"] = now.isoformat()
                await _emit_device_change(db, client_id, local_ip, pi, (stale_docs.get(pi) or {}).get("name") or f"port{pi}", old, setv["last_device"])
        elif counts.get(pi, 0) > 3:
            setv["mac_count"] = counts[pi]
        await db.port_memory.update_one({"client_id": client_id, "local_ip": local_ip, "idx": pi}, {"$set": setv})


def classify(mem: Optional[dict], oper_up: bool, poe_w: float = 0.0, at: Optional[datetime] = None,
             holiday: Optional[str] = None) -> dict:
    """→ {profile, verdict, label, up_ratio, days, reason, last_device, usual_speed_mbps, usual_poe_w}"""
    at = at or _now()
    out = _classify(mem, oper_up, poe_w, at, holiday)
    ch = _parse((mem or {}).get("device_changed_at"))
    if ch and (at - ch) <= timedelta(days=7):
        out["device_changed_at"] = ch.isoformat()
        out["prev_device"] = mem.get("prev_device")
    if (mem or {}).get("authorized_devices"):
        out["authorized_devices"] = mem["authorized_devices"]
    return out


def _classify(mem: Optional[dict], oper_up: bool, poe_w: float, at: datetime, holiday: Optional[str]) -> dict:
    if not mem:
        return {"profile": "learning", "verdict": "up" if oper_up else "learning", "label": VERDICT_LABELS["up" if oper_up else "learning"],
                "up_ratio": None, "days": 0, "reason": "Nessuno storico per questa porta."}
    first = _parse(mem.get("first_seen")) or at
    days = max(0.0, (at - first).total_seconds() / 86400)
    samples = int(mem.get("samples") or 0)
    ups = int(mem.get("up_samples") or 0)
    ratio = ups / samples if samples else 0.0
    poe_samples = int(mem.get("poe_samples") or 0)
    usual_poe = round(float(mem.get("poe_w_sum") or 0) / poe_samples, 1) if poe_samples else 0.0
    base = {"up_ratio": round(ratio, 3), "days": round(days, 1), "last_device": mem.get("last_device"),
            "usual_speed_mbps": mem.get("usual_speed_mbps"), "usual_poe_w": usual_poe,
            "learning_days_left": max(0, round(LEARNING_DAYS - days, 1))}
    if days < LEARNING_DAYS or samples < 50:
        profile = "learning"
    elif ratio == 0:
        profile = "unused"
    elif ratio >= ALWAYS_ON_RATIO:
        profile = "always_on"
    elif ratio < SPORADIC_RATIO:
        profile = "sporadic"
    else:
        profile = "scheduled"
    base["profile"] = profile
    base["profile_label"] = PROFILE_LABELS[profile]
    if oper_up:
        return {**base, "verdict": "up", "label": VERDICT_LABELS["up"], "reason": f"Porta attiva ({PROFILE_LABELS[profile].lower()}, up {int(ratio * 100)}% del tempo)."}
    if poe_w >= POE_STANDBY_MIN_W and usual_poe > 0:
        return {**base, "verdict": "standby_poe", "label": VERDICT_LABELS["standby_poe"],
                "reason": f"Link giù ma il PoE assorbe {poe_w:.1f} W (di solito {usual_poe} W): dispositivo alimentato in standby, non guasto."}
    if profile == "learning":
        return {**base, "verdict": "learning", "label": VERDICT_LABELS["learning"],
                "reason": f"Storico di {days:.0f} giorni (servono {LEARNING_DAYS}): non ancora classificabile."}
    if profile == "unused":
        return {**base, "verdict": "unused", "label": VERDICT_LABELS["unused"], "reason": f"Mai vista attiva in {days:.0f} giorni."}
    if profile == "sporadic":
        return {**base, "verdict": "habitual", "label": VERDICT_LABELS["habitual"],
                "reason": f"Porta saltuaria: attiva solo il {int(ratio * 100)}% del tempo (laptop/uso occasionale)."}
    if holiday and profile == "scheduled":
        return {**base, "verdict": "habitual", "label": VERDICT_LABELS["habitual"], "holiday": holiday,
                "reason": f"Oggi è festivo ({holiday}): porta a orario d'ufficio giù come atteso, azienda chiusa."}
    if profile == "always_on":
        return {**base, "verdict": "anomalous", "label": VERDICT_LABELS["anomalous"],
                "reason": f"Porta sempre attiva (up {int(ratio * 100)}% in {days:.0f} giorni) ora giù: probabile guasto device/cavo/alimentazione."}
    # scheduled: guardo l'abitudine in QUESTA ora della settimana (±1h)
    b = _how(at)
    how_up = mem.get("how_up") or {}
    how_total = mem.get("how_total") or {}
    u = t = 0
    for off in (-1, 0, 1):
        k = str((b + off) % 168)
        u += int(how_up.get(k) or 0)
        t += int(how_total.get(k) or 0)
    slot_ratio = u / t if t else ratio
    loc = _local(at)
    when = loc.strftime("%a %H:%M")
    if slot_ratio < 0.5:
        return {**base, "verdict": "habitual", "label": VERDICT_LABELS["habitual"], "slot_up_ratio": round(slot_ratio, 2),
                "reason": f"A quest'ora ({when}) la porta è di solito giù ({int((1 - slot_ratio) * 100)}% dei casi): dispositivo spento dal cliente."}
    return {**base, "verdict": "anomalous", "label": VERDICT_LABELS["anomalous"], "slot_up_ratio": round(slot_ratio, 2),
            "reason": f"A quest'ora ({when}) la porta è di solito attiva ({int(slot_ratio * 100)}% dei casi): down fuori dallo schema abituale."}


async def _emit_device_change(db, client_id: str, local_ip: str, idx: int, pname: str, old: dict, new: dict) -> None:
    """Alert 'dispositivo cambiato sulla porta': il MAC abituale è stato sostituito da un altro."""
    try:
        from alert_engine import _mk_alert
        from alert_filter import insert_alert_if_emit
        sw = await db.managed_devices.find_one({"client_id": client_id, "$or": [{"ip": local_ip}, {"ip_address": local_ip}]},
                                               {"_id": 0, "name": 1, "device_name": 1, "hostname": 1})
        sw_name = (sw or {}).get("name") or (sw or {}).get("device_name") or (sw or {}).get("hostname") or local_ip
        cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
        o = old.get("name") or old.get("ip") or old.get("mac")
        n = new.get("name") or new.get("ip") or new.get("mac")
        alert = _mk_alert(client_id, (cl or {}).get("name") or client_id, sw_name, local_ip, "switch", "medium", "port_device_change",
                          f"Dispositivo cambiato su {sw_name} · {pname}",
                          f"Sulla porta {pname} di {sw_name} il dispositivo abituale {o} ({old.get('mac')}) è stato sostituito da {n} ({new.get('mac')}). "
                          "Verifica che sia un cambio autorizzato (nuovo PC, spostamento cavo) e non un dispositivo estraneo.")
        alert["dedup_key"] = f"{client_id}:{local_ip}:port_device_change:{idx}:{new.get('mac')}"
        alert["raw_data"] = {"idx": idx, "port_name": pname, "prev_device": old, "new_device": new}
        await insert_alert_if_emit(db, alert)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"port_memory device change alert {local_ip}:{idx}: {e}")


async def memory_summary(db, client_id: str, local_ip: str) -> dict:
    """{ports, since_days, samples, learning} per mostrare all'utente che la memoria sta registrando."""
    await refresh_learning_days(db)
    docs = await db.port_memory.find({"client_id": client_id, "local_ip": local_ip},
                                     {"_id": 0, "first_seen": 1, "samples": 1, "updated_at": 1, "device_changed_at": 1}).to_list(2000)
    if not docs:
        return {"ports": 0, "since_days": 0, "samples": 0, "learning": True, "last_update": None, "changed_7d": 0, "learning_days": LEARNING_DAYS}
    firsts = [_parse(d.get("first_seen")) for d in docs if _parse(d.get("first_seen"))]
    since = (_now() - min(firsts)).total_seconds() / 86400 if firsts else 0
    upd = max((d.get("updated_at") or "" for d in docs), default=None)
    cutoff = (_now() - timedelta(days=7)).isoformat()
    return {"ports": len(docs), "since_days": round(since, 1), "samples": max(int(d.get("samples") or 0) for d in docs),
            "learning": since < LEARNING_DAYS, "last_update": upd or None, "learning_days": LEARNING_DAYS,
            "changed_7d": sum(1 for d in docs if (d.get("device_changed_at") or "") >= cutoff)}


async def classify_port(db, client_id: str, local_ip: str, idx: int, oper_up: bool, poe_w: float = 0.0) -> dict:
    await refresh_learning_days(db)
    mem = await db.port_memory.find_one({"client_id": client_id, "local_ip": local_ip, "idx": int(idx)}, {"_id": 0})
    return classify(mem, oper_up, poe_w, holiday=is_italian_holiday())


async def memory_for_switch(db, client_id: str, local_ip: str) -> dict:
    """{idx: classify(...)} usando l'ultimo stato noto salvato nel doc stesso."""
    out = {}
    await refresh_learning_days(db)
    hol = is_italian_holiday()
    async for m in db.port_memory.find({"client_id": client_id, "local_ip": local_ip}, {"_id": 0}):
        out[m["idx"]] = classify(m, bool(m.get("last_oper_up")), float(m.get("last_poe_w") or 0), holiday=hol)
    return out
