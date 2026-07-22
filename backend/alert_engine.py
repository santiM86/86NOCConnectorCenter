"""
Alert Engine proattivo — Argus Center
=====================================
Watchdog dedicati per essere SEMPRE proattivi sul cliente:

1. VitalDeviceWatchdog — rileva quando un dispositivo VITALE
   (`managed_devices.is_vital=True`) resta offline oltre le soglie
   configurate ed escala Warning → Critical. Usa `liveness_resolver`
   (stessa sorgente di verita' della UI) per evitare falsi positivi
   (evidence FDB/ARP, debounce anti-flap, blackout connector = "stale").

2. DattoWatchdog — rileva quando:
   - un SERVER Datto RMM risulta offline (disconnesso dal cloud) oltre
     N ore;
   - il sync Datto stesso e' fermo da troppo tempo (portale/engine giu').

Notifiche: Web Push (VAPID, ai ruoli configurati) + Telegram.
Auto-recovery: alla ripresa invia una notifica "tornato ONLINE".

Config: `alert_engine_config` (doc `_id="global"` + eventuali override
per client_id). Stato offline persistito in `vital_offline_state` e
`datto_offline_state` per calcolare la durata ed evitare alert duplicati.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from alert_filter import insert_alert_if_emit
import liveness_resolver as lr

logger = logging.getLogger("alert_engine")

CHECK_INTERVAL_SECONDS = 60

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    # Dispositivi vitali offline
    "vital_warn_minutes": 3,
    "vital_crit_minutes": 10,
    # Datto RMM
    "datto_enabled": True,
    "datto_server_offline_hours": 1,     # server Datto offline > 1h -> high
    "datto_server_crit_hours": 2,        # > 2h -> critical
    "datto_sync_stale_minutes": 30,      # sync fermo > 30min -> alert engine giu'
    # Canali
    "channels": ["push", "telegram"],
    "notify_roles": ["admin", "operator"],
    "auto_recovery": True,
    # Telegram
    "telegram_enabled": True,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}


async def get_config(db) -> Dict[str, Any]:
    doc = await db.alert_engine_config.find_one({"_id": "global"})
    cfg = dict(DEFAULT_CONFIG)
    if doc:
        for k in DEFAULT_CONFIG:
            if k in doc and doc[k] is not None:
                cfg[k] = doc[k]
    return cfg


async def save_config(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    allowed = set(DEFAULT_CONFIG.keys())
    update = {k: v for k, v in patch.items() if k in allowed}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.alert_engine_config.update_one({"_id": "global"}, {"$set": update}, upsert=True)
    return await get_config(db)


async def _resolve_client_config(db, cfg_global: Dict[str, Any], client_id: str) -> Dict[str, Any]:
    """Merge config globale con eventuale override per cliente."""
    merged = dict(cfg_global)
    ov = await db.alert_engine_config.find_one({"_id": f"client:{client_id}"})
    if ov and ov.get("override_enabled"):
        for k in DEFAULT_CONFIG:
            if k in ov and ov[k] is not None:
                merged[k] = ov[k]
    return merged


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, (int, float)):
        # epoch (secondi o ms)
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Notifica multi-canale
# ---------------------------------------------------------------------------

async def _dispatch_notification(db, cfg: Dict[str, Any], alert_doc: Dict[str, Any]) -> None:
    channels = cfg.get("channels") or ["push"]
    # Web push
    if "push" in channels:
        try:
            import webpush as wp
            await wp.notify_new_alert(db, alert_doc)
        except Exception as e:  # noqa: BLE001
            logger.debug("push dispatch failed: %s", e)
    # Telegram
    if "telegram" in channels and cfg.get("telegram_enabled"):
        try:
            from telegram_notifier import send_alert_telegram
            await send_alert_telegram(
                db,
                title=alert_doc.get("title", "Alert"),
                message=alert_doc.get("message", ""),
                severity=alert_doc.get("severity", "high"),
                chat_id=cfg.get("telegram_chat_id") or None,
                token=cfg.get("telegram_bot_token") or None,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("telegram dispatch failed: %s", e)


def _mk_alert(client_id: str, client_name: str, device_name: str, device_ip: str,
              device_type: str, severity: str, source_type: str,
              title: str, message: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "client_name": client_name,
        "device_id": "",
        "device_ip": device_ip or "",
        "device_name": device_name or "",
        "device_type": device_type or "",
        "severity": severity,
        "source_type": source_type,
        "title": title,
        "message": message,
        "status": "active",
        "raw_data": "",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Watchdog 1 — dispositivi vitali offline
# ---------------------------------------------------------------------------

async def _best_poll_record(records: list) -> Optional[dict]:
    """Sceglie il record device_poll_status migliore: reachable vince, poi
    il piu' recente (last_ping_at/last_poll)."""
    if not records:
        return None
    def key(pd):
        reach = 1 if pd.get("reachable") else 0
        ts = pd.get("last_ping_at") or pd.get("last_poll") or ""
        return (reach, str(ts))
    return sorted(records, key=key, reverse=True)[0]


async def run_vital_watchdog(db, cfg_global: Dict[str, Any]) -> int:
    now = datetime.now(timezone.utc)
    vitals = await db.managed_devices.find(
        {"is_vital": True},
        {"_id": 0, "client_id": 1, "ip": 1, "name": 1, "device_name": 1,
         "device_type": 1, "mac": 1, "source": 1},
    ).to_list(5000)
    if not vitals:
        return 0

    # Mappe evidence + connector-down (una volta per ciclo, tutti i clienti)
    ip_ev, mac_ev = await lr.build_evidence_maps(db, client_id=None)
    offline_clients = await lr.build_clients_without_online_agent(db)

    # Poll records per gli IP vitali
    vital_ips = [v.get("ip") for v in vitals if v.get("ip")]
    poll_by_ip: dict = {}
    if vital_ips:
        recs = await db.device_poll_status.find(
            {"device_ip": {"$in": vital_ips}}, {"_id": 0},
        ).to_list(20000)
        grouped: dict = {}
        for r in recs:
            grouped.setdefault(r.get("device_ip"), []).append(r)
        for ip, lst in grouped.items():
            poll_by_ip[ip] = await _best_poll_record(lst)

    # Nomi clienti
    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    client_names = {c.get("id"): c.get("name") for c in clients}

    actions = 0
    for v in vitals:
        cid = v.get("client_id")
        ip = v.get("ip")
        if not cid or not ip:
            continue
        pd = poll_by_ip.get(ip)
        status, _ev = lr.compute_status(pd, v, ip_ev, mac_ev, offline_clients)
        is_down = status == "offline"  # "stale"/"pending"/"online" NON allertano

        state = await db.vital_offline_state.find_one({"client_id": cid, "ip": ip})
        cfg = await _resolve_client_config(db, cfg_global, cid)
        dev_name = v.get("name") or v.get("device_name") or ip
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        dev_type = v.get("device_type") or "device"

        if is_down:
            if not state:
                await db.vital_offline_state.insert_one({
                    "client_id": cid, "ip": ip, "device_name": dev_name,
                    "first_offline_at": now.isoformat(), "level": 0, "alert_id": None,
                })
                state = {"first_offline_at": now.isoformat(), "level": 0, "alert_id": None}
            first_off = _parse_dt(state.get("first_offline_at")) or now
            elapsed_min = (now - first_off).total_seconds() / 60.0
            level = int(state.get("level") or 0)
            warn_min = float(cfg.get("vital_warn_minutes", 3))
            crit_min = float(cfg.get("vital_crit_minutes", 10))

            if level < 1 and elapsed_min >= warn_min:
                alert = _mk_alert(
                    cid, cname, dev_name, ip, dev_type, "high", "vital_device_offline",
                    f"DISPOSITIVO VITALE OFFLINE: {dev_name}",
                    (f"Il dispositivo vitale '{dev_name}' ({ip}) del cliente {cname} "
                     f"e' OFFLINE da {int(elapsed_min)} minuti. Verifica immediata consigliata."),
                )
                await insert_alert_if_emit(db, alert)
                await _dispatch_notification(db, cfg, alert)
                await db.vital_offline_state.update_one(
                    {"client_id": cid, "ip": ip},
                    {"$set": {"level": 1, "alert_id": alert["id"], "warned_at": now.isoformat()}},
                )
                actions += 1
                logger.warning("[vital] OFFLINE warn: %s (%s) client=%s", dev_name, ip, cname)

            elif level < 2 and elapsed_min >= crit_min:
                # Escala l'alert esistente a critical + re-notifica
                aid = state.get("alert_id")
                if aid:
                    await db.alerts.update_one(
                        {"id": aid},
                        {"$set": {"severity": "critical",
                                  "message": (f"ESCALATION: il dispositivo vitale '{dev_name}' ({ip}) "
                                              f"del cliente {cname} e' OFFLINE da {int(elapsed_min)} minuti.")}},
                    )
                    alert = await db.alerts.find_one({"id": aid}, {"_id": 0})
                else:
                    alert = _mk_alert(
                        cid, cname, dev_name, ip, dev_type, "critical", "vital_device_offline",
                        f"DISPOSITIVO VITALE OFFLINE (CRITICO): {dev_name}",
                        (f"Il dispositivo vitale '{dev_name}' ({ip}) del cliente {cname} "
                         f"e' OFFLINE da {int(elapsed_min)} minuti."),
                    )
                    await insert_alert_if_emit(db, alert)
                if alert:
                    await _dispatch_notification(db, cfg, alert)
                await db.vital_offline_state.update_one(
                    {"client_id": cid, "ip": ip},
                    {"$set": {"level": 2, "escalated_at": now.isoformat(),
                              "alert_id": (alert or {}).get("id")}},
                )
                actions += 1
                logger.warning("[vital] OFFLINE CRIT: %s (%s) client=%s", dev_name, ip, cname)
        else:
            # Tornato online / stale-uncertain: risolvi eventuale stato
            if state:
                aid = state.get("alert_id")
                if aid:
                    await db.alerts.update_one(
                        {"id": aid},
                        {"$set": {"status": "resolved", "resolved_at": now.isoformat()}},
                    )
                if state.get("level", 0) >= 1 and cfg.get("auto_recovery") and status == "online":
                    rec = _mk_alert(
                        cid, cname, dev_name, ip, dev_type, "low", "vital_device_recovery",
                        f"Dispositivo vitale ONLINE (ripristinato): {dev_name}",
                        f"Il dispositivo vitale '{dev_name}' ({ip}) del cliente {cname} e' tornato ONLINE.",
                    )
                    await insert_alert_if_emit(db, rec)
                    await _dispatch_notification(db, cfg, rec)
                    actions += 1
                    logger.info("[vital] RECOVERY: %s (%s) client=%s", dev_name, ip, cname)
                if status == "online":
                    await db.vital_offline_state.delete_one({"client_id": cid, "ip": ip})
    return actions


# ---------------------------------------------------------------------------
# Watchdog 2 — Datto RMM (server offline + sync stale)
# ---------------------------------------------------------------------------

def _is_datto_server(dev: dict) -> bool:
    dt = (dev.get("device_type") or "").lower()
    return "server" in dt or "esxi" in dt or dev.get("is_server") is True


async def run_datto_watchdog(db, cfg_global: Dict[str, Any]) -> int:
    if not cfg_global.get("datto_enabled", True):
        return 0
    now = datetime.now(timezone.utc)
    actions = 0

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    client_names = {c.get("id"): c.get("name") for c in clients}

    # --- A) Sync stale per client link ---
    links = await db.datto_client_links.find({}, {"_id": 0}).to_list(2000)
    for link in links:
        cid = link.get("client_id")
        if not cid:
            continue
        cfg = await _resolve_client_config(db, cfg_global, cid)
        stale_min = float(cfg.get("datto_sync_stale_minutes", 30))
        last_sync = _parse_dt(link.get("last_sync_at"))
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        existing = await db.alerts.find_one(
            {"client_id": cid, "source_type": "datto_sync_stale", "status": "active"}
        )
        stale = last_sync is not None and (now - last_sync).total_seconds() / 60.0 > stale_min
        if stale and not existing:
            mins = int((now - last_sync).total_seconds() / 60.0)
            alert = _mk_alert(
                cid, cname, "Datto RMM Sync", "", "integration", "high", "datto_sync_stale",
                f"DATTO RMM: sync fermo per {cname}",
                (f"Il sync Datto RMM del cliente {cname} non si aggiorna da {mins} minuti "
                 f"(ultimo: {link.get('last_sync_at')}). Possibile perdita di connessione al portale Datto."),
            )
            await insert_alert_if_emit(db, alert)
            await _dispatch_notification(db, cfg, alert)
            actions += 1
            logger.warning("[datto] sync stale client=%s mins=%s", cname, mins)
        elif not stale and existing:
            await db.alerts.update_one(
                {"id": existing["id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat()}},
            )
            if cfg.get("auto_recovery"):
                rec = _mk_alert(
                    cid, cname, "Datto RMM Sync", "", "integration", "low", "datto_sync_recovery",
                    f"DATTO RMM: sync ripristinato per {cname}",
                    f"Il sync Datto RMM del cliente {cname} ha ripreso ad aggiornarsi.",
                )
                await insert_alert_if_emit(db, rec)
                await _dispatch_notification(db, cfg, rec)
            actions += 1

    # --- B) Server Datto offline oltre soglia ---
    servers = await db.datto_devices.find(
        {"$or": [{"device_type": {"$regex": "server", "$options": "i"}},
                 {"is_server": True}]},
        {"_id": 0, "client_id": 1, "uid": 1, "name": 1, "ip": 1,
         "online": 1, "datto_last_seen": 1, "device_type": 1},
    ).to_list(20000)

    for dev in servers:
        cid = dev.get("client_id")
        uid = dev.get("uid")
        if not cid or not uid:
            continue
        if dev.get("online") is None:
            continue  # sync non ha ancora popolato lo stato online
        cfg = await _resolve_client_config(db, cfg_global, cid)
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        name = dev.get("name") or uid
        state = await db.datto_offline_state.find_one({"client_id": cid, "uid": uid})
        online = bool(dev.get("online"))

        if not online:
            last_seen = _parse_dt(dev.get("datto_last_seen"))
            ref = last_seen or (_parse_dt((state or {}).get("first_offline_at")) if state else None) or now
            if not state:
                await db.datto_offline_state.insert_one({
                    "client_id": cid, "uid": uid, "name": name,
                    "first_offline_at": ref.isoformat(), "level": 0, "alert_id": None,
                })
                state = {"first_offline_at": ref.isoformat(), "level": 0, "alert_id": None}
            offline_hours = (now - ref).total_seconds() / 3600.0
            level = int(state.get("level") or 0)
            warn_h = float(cfg.get("datto_server_offline_hours", 1))
            crit_h = float(cfg.get("datto_server_crit_hours", 2))

            if level < 1 and offline_hours >= warn_h:
                alert = _mk_alert(
                    cid, cname, name, dev.get("ip") or "", "server", "high", "datto_server_offline",
                    f"SERVER DATTO OFFLINE: {name}",
                    (f"Il server '{name}' del cliente {cname} risulta disconnesso da Datto RMM "
                     f"da {offline_hours:.1f} ore. Verifica lo stato del server."),
                )
                await insert_alert_if_emit(db, alert)
                await _dispatch_notification(db, cfg, alert)
                await db.datto_offline_state.update_one(
                    {"client_id": cid, "uid": uid},
                    {"$set": {"level": 1, "alert_id": alert["id"]}},
                )
                actions += 1
                logger.warning("[datto] server offline warn: %s client=%s h=%.1f", name, cname, offline_hours)
            elif level < 2 and offline_hours >= crit_h:
                aid = state.get("alert_id")
                if aid:
                    await db.alerts.update_one(
                        {"id": aid},
                        {"$set": {"severity": "critical",
                                  "message": (f"ESCALATION: il server '{name}' del cliente {cname} "
                                              f"e' disconnesso da Datto da {offline_hours:.1f} ore.")}},
                    )
                    alert = await db.alerts.find_one({"id": aid}, {"_id": 0})
                else:
                    alert = _mk_alert(
                        cid, cname, name, dev.get("ip") or "", "server", "critical",
                        "datto_server_offline", f"SERVER DATTO OFFLINE (CRITICO): {name}",
                        f"Il server '{name}' del cliente {cname} e' disconnesso da Datto da {offline_hours:.1f} ore.",
                    )
                    await insert_alert_if_emit(db, alert)
                if alert:
                    await _dispatch_notification(db, cfg, alert)
                await db.datto_offline_state.update_one(
                    {"client_id": cid, "uid": uid},
                    {"$set": {"level": 2, "alert_id": (alert or {}).get("id")}},
                )
                actions += 1
        else:
            if state:
                aid = state.get("alert_id")
                if aid:
                    await db.alerts.update_one(
                        {"id": aid},
                        {"$set": {"status": "resolved", "resolved_at": now.isoformat()}},
                    )
                if state.get("level", 0) >= 1 and cfg.get("auto_recovery"):
                    rec = _mk_alert(
                        cid, cname, name, dev.get("ip") or "", "server", "low",
                        "datto_server_recovery", f"Server Datto ONLINE (ripristinato): {name}",
                        f"Il server '{name}' del cliente {cname} e' tornato online su Datto RMM.",
                    )
                    await insert_alert_if_emit(db, rec)
                    await _dispatch_notification(db, cfg, rec)
                    actions += 1
                await db.datto_offline_state.delete_one({"client_id": cid, "uid": uid})
    return actions


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class AlertEngine:
    def __init__(self, db):
        self.db = db
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.last_run: Dict[str, Any] = {}

    async def run_once(self) -> Dict[str, Any]:
        cfg = await get_config(self.db)
        if not cfg.get("enabled"):
            self.last_run = {"skipped": True, "at": datetime.now(timezone.utc).isoformat()}
            return self.last_run
        vital = 0
        datto = 0
        try:
            vital = await run_vital_watchdog(self.db, cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning("vital watchdog error: %s", e, exc_info=True)
        try:
            datto = await run_datto_watchdog(self.db, cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning("datto watchdog error: %s", e, exc_info=True)
        self.last_run = {
            "at": datetime.now(timezone.utc).isoformat(),
            "vital_actions": vital,
            "datto_actions": datto,
        }
        try:
            await self.db.alert_engine_config.update_one(
                {"_id": "__runtime"}, {"$set": {**self.last_run}}, upsert=True,
            )
        except Exception:
            pass
        return self.last_run

    async def _loop(self):
        logger.info("Alert Engine started (interval=%ss)", CHECK_INTERVAL_SECONDS)
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as e:  # noqa: BLE001
                logger.warning("alert engine loop error: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
