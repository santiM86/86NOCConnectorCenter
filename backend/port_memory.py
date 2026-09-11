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

LEARNING_DAYS = 7          # sotto questa anzianità → "learning" (regola attuale, nessun filtro)
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


async def record_ports(db, client_id: str, local_ip: str, ports: list) -> int:
    """Chiamata da store_switch_ports dopo ogni poll: aggiorna gli istogrammi per porta."""
    now = _now()
    now_iso = now.isoformat()
    b = _how(now)
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
        inc = {"samples": 1, f"how_total.{b}": 1}
        setv = {"name": p.get("name") or f"port{idx}", "updated_at": now_iso, "last_oper_up": up,
                "last_poe_w": poe_w, "last_speed_mbps": speed}
        if up:
            inc["up_samples"] = 1
            inc[f"how_up.{b}"] = 1
            setv["last_up_at"] = now_iso
            if poe_w > 0:
                inc["poe_samples"] = 1
                inc["poe_w_sum"] = poe_w
        else:
            setv["last_down_at"] = now_iso
        upd = {"$inc": inc, "$set": setv, "$setOnInsert": {"first_seen": now_iso}}
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
    stale = {m["idx"] async for m in db.port_memory.find(
        {"client_id": client_id, "local_ip": local_ip,
         "$or": [{"device_refreshed_at": {"$exists": False}}, {"device_refreshed_at": {"$lt": cutoff}}]},
        {"_id": 0, "idx": 1})}
    if not stale:
        return
    counts: dict = {}
    macs: dict = {}
    async for e in db.discovered_endpoints.find(
            {"client_id": client_id, "switch_ip": local_ip, "port": {"$in": list(stale)}},
            {"_id": 0, "port": 1, "mac": 1, "ip": 1}):
        try:
            pi = int(e.get("port"))
        except Exception:
            continue
        counts[pi] = counts.get(pi, 0) + 1
        if e.get("mac") and pi not in macs:
            macs[pi] = {"mac": str(e.get("mac")).upper(), "ip": e.get("ip") or ""}
    for pi in stale:
        setv = {"device_refreshed_at": now.isoformat()}
        d = macs.get(pi)
        if d and counts.get(pi, 0) <= 3:  # >3 MAC = uplink/trunk: non ha "un" device
            name = ""
            if d["ip"]:
                md = await db.managed_devices.find_one(
                    {"client_id": client_id, "$or": [{"ip": d["ip"]}, {"ip_address": d["ip"]}]}, {"_id": 0, "name": 1, "hostname": 1})
                name = (md or {}).get("name") or (md or {}).get("hostname") or ""
            setv["last_device"] = {"mac": d["mac"], "ip": d["ip"], "name": name, "seen_at": now.isoformat()}
        elif counts.get(pi, 0) > 3:
            setv["mac_count"] = counts[pi]
        await db.port_memory.update_one({"client_id": client_id, "local_ip": local_ip, "idx": pi}, {"$set": setv})


def classify(mem: Optional[dict], oper_up: bool, poe_w: float = 0.0, at: Optional[datetime] = None) -> dict:
    """→ {profile, verdict, label, up_ratio, days, reason, last_device, usual_speed_mbps, usual_poe_w}"""
    at = at or _now()
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


async def classify_port(db, client_id: str, local_ip: str, idx: int, oper_up: bool, poe_w: float = 0.0) -> dict:
    mem = await db.port_memory.find_one({"client_id": client_id, "local_ip": local_ip, "idx": int(idx)}, {"_id": 0})
    return classify(mem, oper_up, poe_w)


async def memory_for_switch(db, client_id: str, local_ip: str) -> dict:
    """{idx: classify(...)} usando l'ultimo stato noto salvato nel doc stesso."""
    out = {}
    async for m in db.port_memory.find({"client_id": client_id, "local_ip": local_ip}, {"_id": 0}):
        out[m["idx"]] = classify(m, bool(m.get("last_oper_up")), float(m.get("last_poe_w") or 0))
    return out
