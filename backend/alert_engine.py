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

CHECK_INTERVAL_SECONDS = 20  # v2026-06 SPEED: era 60. Rete di sicurezza; il down
                             # dei device VITALI e' comunque event-driven (agent_ws).

# v2026-06 SPEED — rilevazione RAPIDA dei device VITALI (switch/firewall/server).
# Quando il poll DIRETTO (ICMP/SNMP) di un device vitale fallisce per >=2 cicli
# consecutivi (~30s) ed e' FRESCO, l'evidenza L2 (FDB/ARP) del suo MAC — che
# altrimenti lo terrebbe "healthy" fino a 15 min — viene IGNORATA e l'alert
# scatta subito (bypassa il gate temporale vital_warn_minutes).
VITAL_L2_FRESH_SECONDS = 120   # il poll diretto deve essere recente per fidarsi
VITAL_FAST_FAILURES = 2        # 2 poll ICMP falliti consecutivi (~30s)

SEVERITY_RANK_LOCAL = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

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
    # Source-health gating (fusione multi-fonte)
    "datto_blackout_ratio": 0.6,         # >=60% device Datto offline insieme -> Datto inaffidabile
    "site_down_ratio": 0.8,              # >=80% device del sito irraggiungibili -> SITO GIU'/corrente
    # Rilevamento nuovi dispositivi da classificare
    "new_device_detection": True,
    "new_device_window_hours": 24,
    "auto_promote_infra": False,
    # Canali
    "channels": ["push", "telegram"],
    "notify_roles": ["admin", "operator"],
    "auto_recovery": True,
    # Telegram
    "telegram_enabled": True,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Soglia minima di severità per l'invio Telegram: "critical" (default) o "high"
    "telegram_min_severity": "critical",
    # Quiet hours: fuori orario gli alert NON "down" vengono accorpati in un
    # riepilogo inviato al termine della finestra. I veri down restano istantanei.
    "telegram_quiet_enabled": True,
    "telegram_quiet_start": "22:00",
    "telegram_quiet_end": "07:00",
    # Digest mattutino "Cosa è DOWN" (orario configurabile, Europe/Rome)
    "morning_digest_enabled": True,
    "morning_digest_time": "07:00",
}


_TG_SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0, "info": 0}


def _telegram_severity_ok(cfg: Dict[str, Any], severity: str) -> bool:
    """True se la severità dell'alert raggiunge la soglia minima Telegram configurata."""
    min_sev = (cfg.get("telegram_min_severity") or "critical").lower()
    return _TG_SEV_RANK.get(str(severity).lower(), 0) >= _TG_SEV_RANK.get(min_sev, 3)


# source_type che rappresentano un "vero down" → sempre istantanei anche in quiet hours
_TG_INSTANT_KEYWORDS = ("down", "offline", "blackout", "power", "isolat",
                        "situation", "reach", "liveness", "vital", "connector",
                        "external_monitor", "wan")


def _is_instant_source(source_type: str) -> bool:
    st = str(source_type or "").lower()
    return any(k in st for k in _TG_INSTANT_KEYWORDS)


def _in_quiet_hours(cfg: Dict[str, Any]) -> bool:
    """True se l'ora corrente (Europe/Rome) è dentro la finestra quiet-hours."""
    if not cfg.get("telegram_quiet_enabled"):
        return False
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Rome"))
    except Exception:
        now = datetime.now()
    def _p(s, d):
        try:
            h, m = str(s).split(":"); return int(h) * 60 + int(m)
        except Exception:
            return d
    start = _p(cfg.get("telegram_quiet_start"), 22 * 60)
    end = _p(cfg.get("telegram_quiet_end"), 7 * 60)
    cur = now.hour * 60 + now.minute
    return (start <= cur or cur < end) if start > end else (start <= cur < end)


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
    # Finestra di manutenzione attiva → nessuna notifica (push/telegram).
    try:
        from maintenance_gate import is_in_maintenance
        if await is_in_maintenance(db, alert_doc.get("client_id"),
                                   alert_doc.get("device_ip") or alert_doc.get("ip")):
            return
    except Exception:
        pass
    channels = cfg.get("channels") or ["push"]
    # Web push
    if "push" in channels:
        try:
            import webpush as wp
            await wp.notify_new_alert(db, alert_doc)
        except Exception as e:  # noqa: BLE001
            logger.debug("push dispatch failed: %s", e)
    # Telegram — via percorso unificato (soglia severità + quiet hours + queue)
    if "telegram" in channels and cfg.get("telegram_enabled"):
        try:
            await notify_alert_telegram(db, alert_doc)
        except Exception as e:  # noqa: BLE001
            logger.debug("telegram dispatch failed: %s", e)


async def notify_alert_telegram(db, alert_doc: Dict[str, Any]) -> bool:
    """Invio Telegram riutilizzabile per alert generati FUORI dal motore
    (C2, KEV, rogue, anomalie traffico, cambio IP). Rispetta la config globale:
    canale 'telegram' abilitato + severità high/critical. Idempotente per doc."""
    try:
        cfg = await get_config(db)
    except Exception:
        return False
    channels = cfg.get("channels") or ["push"]
    if "telegram" not in channels or not cfg.get("telegram_enabled"):
        return False
    # Finestra di manutenzione attiva → nessuna notifica Telegram, TRANNE i guasti
    # hardware fisici istantanei (alert_doc["instant"]=True): un disco/PSU guasto
    # non va soppresso nemmeno in manutenzione (coerente con insert_alert_if_emit force).
    _instant = bool(alert_doc.get("instant")) or _is_instant_source(alert_doc.get("source_type"))
    if not _instant:
        try:
            from maintenance_gate import is_in_maintenance
            if await is_in_maintenance(db, alert_doc.get("client_id"),
                                       alert_doc.get("device_ip") or alert_doc.get("ip")):
                return False
        except Exception:
            pass
    if not _telegram_severity_ok(cfg, alert_doc.get("severity")):
        return False
    # Quiet hours: accoda gli alert non-"down" per il riepilogo di fine finestra.
    # I guasti hardware fisici (instant) bypassano SEMPRE le quiet hours.
    if _in_quiet_hours(cfg) and not _instant:
        try:
            await db.telegram_quiet_queue.insert_one({
                "id": str(uuid.uuid4()),
                "title": alert_doc.get("title", "Alert"),
                "message": alert_doc.get("message", ""),
                "severity": alert_doc.get("severity", "critical"),
                "client_name": alert_doc.get("client_name"),
                "source_type": alert_doc.get("source_type"),
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "sent": False,
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("quiet-queue insert failed: %s", e)
        return "queued"
    try:
        from telegram_notifier import send_alert_telegram
        # Nome cliente SEMPRE presente: fallback dal DB se assente nell'alert_doc
        client_name = alert_doc.get("client_name")
        if not client_name and alert_doc.get("client_id"):
            try:
                c = await db.clients.find_one({"id": alert_doc["client_id"]}, {"_id": 0, "name": 1})
                client_name = (c or {}).get("name")
            except Exception:
                client_name = None
        await send_alert_telegram(
            db,
            title=alert_doc.get("title", "Alert"),
            message=alert_doc.get("message", ""),
            severity=alert_doc.get("severity", "high"),
            chat_id=cfg.get("telegram_chat_id") or None,
            token=cfg.get("telegram_bot_token") or None,
            client_name=client_name,
            device_name=alert_doc.get("device_name") or alert_doc.get("device_ip"),
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("notify_alert_telegram failed: %s", e)
        return False


async def telegram_quiet_digest_tick(db) -> dict:
    """Al termine delle quiet hours invia UN riepilogo degli alert accodati e svuota la coda."""
    try:
        cfg = await get_config(db)
    except Exception:
        return {"sent": 0}
    if _in_quiet_hours(cfg):
        return {"sent": 0, "reason": "still_quiet"}
    pending = await db.telegram_quiet_queue.find({"sent": False}, {"_id": 0}).to_list(500)
    if not pending:
        return {"sent": 0}
    if "telegram" in (cfg.get("channels") or []) and cfg.get("telegram_enabled"):
        _LABELS = {
            "kev_exposure": "KEV", "osint_c2": "C2", "traffic_anomaly": "anomalia traffico",
            "traffic": "anomalia traffico", "rogue": "dispositivo rogue",
            "new_devices_detected": "dispositivo rogue", "wan_public_ip_change": "cambio IP",
            "predictive_raid": "guasto imminente", "predictive_ups": "guasto imminente",
            "predictive_temp": "guasto imminente", "datto_sync_stale": "sync Datto",
        }
        def _label(st):
            st = str(st or "")
            if st in _LABELS:
                return _LABELS[st]
            if st.startswith("predictive"):
                return "guasto imminente"
            return st.replace("_", " ") or "alert"
        # raggruppa per cliente → {categoria: conteggio}
        by_client, by_sev = {}, {"critical": 0, "high": 0}
        for p in pending:
            by_sev[p.get("severity", "critical")] = by_sev.get(p.get("severity", "critical"), 0) + 1
            cli = p.get("client_name") or "—"
            cats = by_client.setdefault(cli, {})
            lbl = _label(p.get("source_type"))
            cats[lbl] = cats.get(lbl, 0) + 1
        lines = []
        for cli in sorted(by_client, key=lambda c: -sum(by_client[c].values()))[:60]:
            parts = ", ".join(f"{n} {lbl}" for lbl, n in sorted(by_client[cli].items(), key=lambda x: -x[1]))
            lines.append(f"• <b>{cli}</b>: {parts}")
        body = (f"🌙 <b>Riepilogo notturno ARGUS</b> — {len(pending)} alert accodati\n"
                f"({by_sev.get('critical', 0)} critici, {by_sev.get('high', 0)} alti) · {len(by_client)} clienti\n\n"
                + "\n".join(lines))
        try:
            from telegram_notifier import send_telegram_text
            await send_telegram_text(db, body, chat_id=cfg.get("telegram_chat_id") or None,
                                     token=cfg.get("telegram_bot_token") or None)
        except Exception as e:  # noqa: BLE001
            logger.debug("quiet digest send failed: %s", e)
    ids = [p["id"] for p in pending]
    await db.telegram_quiet_queue.update_many({"id": {"$in": ids}}, {"$set": {"sent": True}})
    logger.info(f"[telegram] quiet digest sent: {len(pending)} alerts")
    return {"sent": len(pending)}


async def hyperv_vm_state_tick(db) -> dict:
    """Host Hyper-V raggiungibile ma una VM che DOVREBBE essere accesa risulta spenta.
    'Dovrebbe essere accesa' = VM con toggle hyperv_alert_on_off attivo in CMDB.
    Confronto stato atteso (running) vs reale riportato dall'host."""
    def _running(vm):
        st = str(vm.get("state") or vm.get("status") or vm.get("vm_state") or "").strip().lower()
        return st in ("running", "on", "started", "2", "acceso")
    emitted = 0
    resolved = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    async for st in db.backup_status.find(
        {"hyperv_connected": True, "hyperv_vms.0": {"$exists": True}},
        {"_id": 0, "client_id": 1, "hyperv_vms": 1},
    ):
        cid = st.get("client_id")
        vms = st.get("hyperv_vms") or []
        off_names = {v.get("name") for v in vms if v.get("name") and not _running(v)}
        running_names = {v.get("name") for v in vms if v.get("name") and _running(v)}
        # VM "monitorate" (devono girare) = device con hyperv_alert_on_off attivo
        monitored = await db.managed_devices.find(
            {"client_id": cid, "hyperv_alert_on_off": True},
            {"_id": 0, "name": 1, "hyperv_vm_name": 1, "ip": 1},
        ).to_list(500)
        if not monitored:
            continue
        client = await db.clients.find_one({"id": cid}, {"_id": 0, "name": 1})
        cname = (client or {}).get("name") or cid
        for md in monitored:
            vm_name = md.get("hyperv_vm_name") or md.get("name")
            if not vm_name:
                continue
            dev_key = f"hypervvm:{cid}:{vm_name}"
            # AUTO-RESOLVE: la VM è tornata accesa → risolvi l'alert attivo
            if vm_name in running_names:
                r = await db.alerts.update_many(
                    {"client_id": cid, "source_type": "hyperv_vm_down",
                     "device_id": dev_key, "status": "active"},
                    {"$set": {"status": "resolved", "resolved_at": now_iso}},
                )
                resolved += r.modified_count
                continue
            if vm_name not in off_names:
                continue
            exists = await db.alerts.find_one(
                {"client_id": cid, "source_type": "hyperv_vm_down", "device_id": dev_key, "status": "active"},
                {"_id": 0, "id": 1},
            )
            if exists:
                continue
            alert_doc = {
                "id": str(uuid.uuid4()), "client_id": cid, "client_name": cname,
                "device_id": dev_key, "device_ip": "",
                "device_name": vm_name, "severity": "critical", "source_type": "hyperv_vm_down",
                "title": f"VM Hyper-V spenta: {vm_name}",
                "message": (f"L'host Hyper-V del cliente {cname} è raggiungibile ma la VM «{vm_name}», "
                            f"che dovrebbe essere accesa, risulta SPENTA. Verificare/avviare la VM."),
                "status": "active", "created_at": now_iso,
            }
            try:
                if await insert_alert_if_emit(db, alert_doc):
                    await notify_alert_telegram(db, alert_doc)
                    emitted += 1
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[hyperv-vm] emit failed {cid}/{vm_name}: {e}")
    if emitted or resolved:
        logger.info(f"[hyperv-vm] emitted {emitted} VM-off alerts, resolved {resolved}")
    return {"emitted": emitted, "resolved": resolved}


async def run_backbone_watchdog(db, cfg_global: Dict[str, Any]) -> dict:
    """v2026-06: alert DEDICATO 'PROBLEMA DI DORSALE'. Quando uno switch è giù,
    controlla la porta DORSALE sul parent (verso quello switch): se è LINK DOWN
    o passa traffico ZERO → emette un alert SEPARATO dal down del singolo switch
    (source_type=corr_backbone_down). Auto-resolve quando la dorsale torna ok o
    lo switch torna su. Dedup per (client, switch)."""
    from routes.topology_diagram import compute_switch_cascade
    emitted = 0
    resolved = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    for client in clients:
        cid = client.get("id")
        cname = client.get("name") or cid
        try:
            casc = await compute_switch_cascade(cid)
        except Exception:
            continue
        cascade = casc.get("cascade", []) or []
        if not cascade:
            continue
        for node in cascade:
            up = node.get("uplink")
            sw_ip = node.get("ip")
            if not up or not sw_ip:
                continue
            dev_key = f"backbone:{cid}:{sw_ip}"
            md = await db.managed_devices.find_one(
                {"client_id": cid, "ip": sw_ip},
                {"_id": 0, "status": 1, "consecutive_ping_failures": 1, "name": 1})
            is_down = bool(md) and (
                md.get("status") == "offline"
                or int(md.get("consecutive_ping_failures") or 0) >= 2)
            parent_ip = up.get("to_ip")
            remote_port = up.get("remote_port")
            parent_name = up.get("to_name") or parent_ip
            sw_name = node.get("name") or (md or {}).get("name") or sw_ip

            async def _resolve():
                r = await db.alerts.update_many(
                    {"client_id": cid, "source_type": "corr_backbone_down",
                     "device_id": dev_key, "status": "active"},
                    {"$set": {"status": "resolved", "resolved_at": now_iso}})
                return r.modified_count

            if not is_down or not parent_ip or not remote_port:
                resolved += await _resolve()
                continue
            ports = await db.switch_ports.find(
                {"client_id": cid, "local_ip": parent_ip}, {"_id": 0}).to_list(2000)
            rp = str(remote_port).strip().lower()
            port = next((p for p in ports
                         if str(p.get("name") or "").strip().lower() == rp
                         or str(p.get("alias") or "").strip().lower() == rp), None)
            if not port:
                resolved += await _resolve()
                continue
            oper = port.get("oper")
            tk = ("rx_bps" in port) or ("tx_bps" in port)
            rx = int(port.get("rx_bps") or 0)
            tx = int(port.get("tx_bps") or 0)
            if oper != 1:
                reason = f"la porta dorsale {remote_port} su {parent_name} è LINK DOWN"
            elif tk and (rx + tx) == 0:
                reason = f"la porta dorsale {remote_port} su {parent_name} è UP ma con traffico a ZERO"
            else:
                resolved += await _resolve()  # dorsale ok → è solo lo switch giù
                continue
            exists = await db.alerts.find_one(
                {"client_id": cid, "source_type": "corr_backbone_down",
                 "device_id": dev_key, "status": "active"}, {"_id": 0, "id": 1})
            if exists:
                continue
            alert_doc = {
                "id": str(uuid.uuid4()), "client_id": cid, "client_name": cname,
                "device_id": dev_key, "device_ip": sw_ip, "device_name": sw_name,
                "severity": "critical", "source_type": "corr_backbone_down",
                "title": f"PROBLEMA DI DORSALE: {parent_name} → {sw_name}",
                "message": (f"Cliente {cname}: lo switch «{sw_name}» risulta giù e {reason} "
                            f"→ probabile guasto della DORSALE (cavo/SFP/uplink), non del solo switch. "
                            f"Verificare il link fisico verso {parent_name}."),
                "status": "active", "created_at": now_iso,
            }
            try:
                if await insert_alert_if_emit(db, alert_doc):
                    await notify_alert_telegram(db, alert_doc)
                    emitted += 1
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[backbone] emit failed {cid}/{sw_ip}: {e}")
    if emitted or resolved:
        logger.info(f"[backbone] emitted {emitted} backbone alerts, resolved {resolved}")
    return {"emitted": emitted, "resolved": resolved}




async def morning_status_digest(db) -> dict:
    """Riepilogo mattutino (07:00): elenca SOLO ciò che è DOWN (dispositivi vitali
    spenti, siti/WAN giù, guasti operatori). NIENTE alert 'critici' generici
    (backup, CVE, ecc.). Per ogni voce mostra da QUANDO è giù."""
    try:
        cfg = await get_config(db)
    except Exception:
        return {"sent": 0}
    if "telegram" not in (cfg.get("channels") or []) or not cfg.get("telegram_enabled"):
        return {"sent": 0, "reason": "telegram_off"}
    time_lbl = cfg.get("morning_digest_time") or "07:00"

    from zoneinfo import ZoneInfo
    from datetime import timedelta as _td
    _TZ = ZoneInfo("Europe/Rome")

    # Finestra "NOTTE": dall'ultima occorrenza dell'orario di inizio fascia silenziosa
    # (telegram_quiet_start, default 22:00) fino ad ora. Così al risveglio ricevi SOLO
    # ciò che è andato down durante la notte, non lo storico dei giorni precedenti.
    _now_loc = datetime.now(_TZ)
    try:
        _qh, _qm = str(cfg.get("telegram_quiet_start") or "22:00").split(":")
        _qh, _qm = int(_qh), int(_qm)
    except Exception:
        _qh, _qm = 22, 0
    _night = _now_loc.replace(hour=_qh, minute=_qm, second=0, microsecond=0)
    if _night > _now_loc:
        _night = _night - _td(days=1)
    night_start_iso = _night.astimezone(timezone.utc).isoformat()
    night_lbl = _night.strftime("%H:%M")

    def _down_since(created_at):
        """(orario HH:MM, durata leggibile) da un ISO/created_at, o (None, None)."""
        if not created_at:
            return None, None
        try:
            dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None, None
        now = datetime.now(timezone.utc)
        mins = max(0, int((now - dt).total_seconds() // 60))
        h, m = divmod(mins, 60)
        if h >= 48:
            d, hh = divmod(h, 24)
            dur = f"{d}g {hh}h"
        else:
            dur = (f"{h}h {m}m" if h else f"{m}m")
        loc = dt.astimezone(_TZ)
        now_loc = datetime.now(_TZ)
        when = loc.strftime("%H:%M") if loc.date() == now_loc.date() else loc.strftime("%d/%m %H:%M")
        return when, dur

    _DOWN_KW = ("down", "offline", "blackout", "power", "isolat", "vital",
                "liveness", "reach", "situation", "external_monitor", "isp_outage",
                "connector", "wan", "host_down", "agent")
    _EXCLUDE_KW = ("backup", "kev", "cve", "vuln", "datto_sync", "patch",
                   "cert", "disk", "license", "sync_stale")

    def _is_down_alert(a):
        st = (a.get("source_type") or "").lower()
        ti = (a.get("title") or "").lower()
        if any(x in st for x in _EXCLUDE_KW):
            return False
        return any(k in (st + " " + ti) for k in _DOWN_KW)

    active = await db.alerts.find(
        {"status": "active", "created_at": {"$gte": night_start_iso}},
        {"_id": 0, "client_id": 1, "client_name": 1, "source_type": 1, "title": 1,
         "device_name": 1, "device_ip": 1, "created_at": 1, "affected_clients": 1},
    ).to_list(3000)

    # SOLO down avvenuti DURANTE LA NOTTE (created_at nella finestra notturna)
    down = [a for a in active if _is_down_alert(a) and (a.get("created_at") or "") >= night_start_iso]
    # separa gli outage operatore (multi-cliente) dal resto
    operator_outages = [a for a in down if "isp_outage" in (a.get("source_type") or "").lower()]
    device_downs = [a for a in down if a not in operator_outages]

    # RIENTRATI nella notte: down-type risolti nella stessa finestra notturna
    resolved = await db.alerts.find(
        {"status": "resolved", "resolved_at": {"$gte": night_start_iso}},
        {"_id": 0, "client_id": 1, "client_name": 1, "source_type": 1, "title": 1,
         "device_name": 1, "device_ip": 1, "resolved_at": 1},
    ).to_list(2000)
    recovered = [a for a in resolved if _is_down_alert(a)]

    # risolvi nomi clienti (fix UUID) — include anche i rientrati
    cids = list({a.get("client_id") for a in (device_downs + recovered) if a.get("client_id")})
    cmap = {}
    if cids:
        for c in await db.clients.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1}).to_list(2000):
            cmap[c["id"]] = c.get("name")

    def _client_label(a):
        cid = a.get("client_id")
        return (cmap.get(cid) or a.get("client_name")
                or (f"Cliente {str(cid)[:8]}" if cid else "—"))

    def _item_label(a):
        nm = (a.get("device_name") or "").strip()
        if not nm:
            nm = (a.get("device_ip") or "").strip()
        if not nm:
            # ripulisci il titolo (es. "WAN Firewall: OFFLINE" → "WAN Firewall")
            t = (a.get("title") or "elemento").strip()
            for sep in (":", " — ", " - "):
                if sep in t:
                    t = t.split(sep)[0].strip()
            nm = t
        return nm

    # ---- Aggregazione per elemento (cliente, item): conta i flap notturni ----
    FLAP_MIN = 3  # >= 3 eventi nella notte = instabile (flapping)

    def _key(a):
        return (_client_label(a), _item_label(a))

    agg = {}
    for a in device_downs:
        e = agg.setdefault(_key(a), {"down": 0, "rec": 0, "first_down": None, "last_rec": None, "vital": False})
        e["down"] += 1
        ca = a.get("created_at") or ""
        if e["first_down"] is None or ca < e["first_down"]:
            e["first_down"] = ca
        if "vital" in (a.get("source_type") or "").lower():
            e["vital"] = True
    for a in recovered:
        e = agg.setdefault(_key(a), {"down": 0, "rec": 0, "first_down": None, "last_rec": None, "vital": False})
        e["rec"] += 1
        ra = a.get("resolved_at") or ""
        if e["last_rec"] is None or ra > e["last_rec"]:
            e["last_rec"] = ra

    still_down, unstable, recovered_stable = [], [], []
    for (cli, item), e in agg.items():
        total = e["down"] + e["rec"]
        currently_down = e["down"] > 0
        if total >= FLAP_MIN:
            unstable.append((cli, item, total, currently_down, e))
        elif currently_down:
            still_down.append((cli, item, e))
        else:
            recovered_stable.append((cli, item))

    total_down = len(device_downs)
    n_down = len(still_down) + len(operator_outages)
    n_unstable = len(unstable)
    n_rec = len(recovered_stable)
    rec_clients = len({c for (c, _i) in recovered_stable})

    if not still_down and not unstable and not operator_outages and not recovered_stable:
        body = (f"☀️ <b>Buongiorno · ARGUS</b> ({time_lbl}) — notte dalle {night_lbl}\n"
                "Tutto tranquillo, nessun evento nella notte. ✅")
    else:
        # TL;DR in cima per lettura in 5 secondi
        tldr = []
        if n_down:
            tldr.append(f"🔴 {n_down} ancora giù")
        if n_unstable:
            tldr.append(f"⚠️ {n_unstable} instabile" + ("" if n_unstable == 1 else "/i"))
        if n_rec:
            tldr.append(f"✅ {n_rec} rientrati")
        lines = [f"☀️ <b>Buongiorno · ARGUS</b> ({time_lbl}) — notte dalle {night_lbl}",
                 " · ".join(tldr) if tldr else "Nessun problema in corso ✅"]

        # 🔴 ANCORA GIÙ ADESSO (azionabile: i tecnici ci lavorano appena arrivati)
        if still_down or operator_outages:
            lines.append(f"\n🔴 <b>ANCORA GIÙ ADESSO ({len(still_down) + len(operator_outages)})</b>")
            for (cli, item, e) in sorted(still_down, key=lambda x: str(x[2].get("first_down") or "")):
                hhmm, dur = _down_since(e.get("first_down"))
                since = f" · giù da {hhmm} ({dur})" if hhmm else ""
                vital = " 🔴 <b>vitale</b>" if e.get("vital") else ""
                lines.append(f"• <b>{cli}</b> — {item}{since}{vital}")
            for a in operator_outages:
                hhmm, dur = _down_since(a.get("created_at"))
                since = f" · da {hhmm} ({dur})" if hhmm else ""
                who = (a.get("title") or "Operatore").replace("OUTAGE OPERATORE", "").strip()
                aff = a.get("affected_clients") or []
                names = ", ".join(c.get("name", "?") for c in aff[:6]) if aff else ""
                lines.append(f"• 🌐 <b>{who}</b>{since}" + (f" · clienti: {names}" if names else ""))

        # ⚠️ INSTABILI (flapping): UNA riga per dispositivo, con il conteggio
        if unstable:
            lines.append(f"\n⚠️ <b>INSTABILI stanotte ({len(unstable)})</b>")
            for (cli, item, total, currently_down, e) in sorted(unstable, key=lambda x: -x[2]):
                state = "🔴 ora giù" if currently_down else "✅ ora OK"
                lines.append(f"• <b>{cli}</b> — {item}: {total} disconnessioni · {state}")

        # ✅ Rientrati stabili: solo il numero (niente muro di testo)
        if recovered_stable:
            lines.append(f"\n✅ <b>Rientrati stabili: {n_rec}</b> ({rec_clients} client{'e' if rec_clients == 1 else 'i'})")

        body = "\n".join(lines)

    try:
        from telegram_notifier import send_telegram_text
        await send_telegram_text(db, body, chat_id=cfg.get("telegram_chat_id") or None,
                                 token=cfg.get("telegram_bot_token") or None)
    except Exception as e:  # noqa: BLE001
        logger.debug("morning digest send failed: %s", e)
        return {"sent": 0, "error": str(e)[:120]}
    logger.info(f"[telegram] morning digest sent: down={n_down} unstable={n_unstable} recovered={n_rec}")
    return {"sent": 1, "still_down": len(still_down), "unstable": n_unstable,
            "operator_outages": len(operator_outages), "recovered_stable": n_rec}


async def morning_digest_tick(db) -> dict:
    """Tick ogni minuto: invia il digest mattutino UNA volta al giorno all'orario
    configurato (morning_digest_time, Europe/Rome). Robusto a riavvii e a cambi
    d'orario. Finestra di consegna: da orario a orario+90min."""
    try:
        cfg = await get_config(db)
    except Exception:
        return {"sent": 0}
    if not cfg.get("morning_digest_enabled", True):
        return {"sent": 0, "reason": "disabled"}
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Rome")
    now = datetime.now(tz)
    try:
        hh, mm = str(cfg.get("morning_digest_time") or "07:00").split(":")
        hh, mm = int(hh), int(mm)
    except Exception:
        hh, mm = 7, 0
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < scheduled:
        return {"sent": 0, "reason": "before_time"}
    today = now.date().isoformat()
    marker = await db.alert_engine_config.find_one({"_id": "morning_digest_marker"})
    if marker and marker.get("last_sent_date") == today:
        return {"sent": 0, "reason": "already_sent"}
    # oltre la finestra (riavvio a metà giornata): segna come fatto, non inviare
    if (now - scheduled).total_seconds() > 90 * 60:
        await db.alert_engine_config.update_one(
            {"_id": "morning_digest_marker"},
            {"$set": {"last_sent_date": today, "skipped": True, "at": now.isoformat()}}, upsert=True)
        return {"sent": 0, "reason": "out_of_window"}
    res = await morning_status_digest(db)
    await db.alert_engine_config.update_one(
        {"_id": "morning_digest_marker"},
        {"$set": {"last_sent_date": today, "skipped": False, "at": now.isoformat()}}, upsert=True)
    return res




def _is_vendor_like_name(n: str) -> bool:
    """True se il 'nome' è una stringa vendor/OS SNMP poco parlante (non un hostname)."""
    if not n:
        return True
    low = n.strip().lower()
    generic = ("hardware manufacturer", "manufacturer", "microsoft corporation",
               "microsoft windows", "unknown", "generic", "n/a", "sconosciuto",
               "linux", "vmware", "windows")
    if any(g in low for g in generic):
        return True
    # "Hardware Manufacturer/Microsoft" o simili: vendor+os separati da / senza spazi utili
    return "/" in n and not any(c.isdigit() for c in n) and len(n.split()) <= 3


def _best_device_name(md: Dict[str, Any], ip: str) -> str:
    """Sceglie il nome più PARLANTE del dispositivo: hostname/sysName/DNS reali,
    poi il name CMDB se non è una stringa vendor, altrimenti l'IP (più identificante
    di 'Hardware Manufacturer/Microsoft')."""
    for k in ("hostname", "datto_hostname", "sys_name", "netbios_name", "dns_name"):
        v = md.get(k)
        if v and str(v).strip():
            return str(v).strip()
    name = (md.get("name") or md.get("device_name") or "").strip()
    if name and not _is_vendor_like_name(name):
        return name
    if ip:
        # se abbiamo solo un nome vendor, mostra IP (+ vendor tra parentesi se utile)
        return f"{ip} ({name})" if name else ip
    return name or "Sconosciuto"


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


async def _emit_recovery_notice(db, cfg, rec: Dict[str, Any]) -> None:
    """Una notifica di RIPRISTINO (device/server/connettore/sync tornato OK) e'
    un evento POSITIVO: va NOTIFICATA (Telegram/WebPush) ma salvata come
    'resolved' (voce di storico/timeline), MAI come alert attivo. Evita che si
    accumulino falsi alert "ripristinato" che restano appesi come attivi."""
    rec["status"] = "resolved"
    rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await _dispatch_notification(db, cfg, rec)
    except Exception:
        pass
    await db.alerts.insert_one(dict(rec))



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


def _vital_direct_down(md: Dict[str, Any], pd: Optional[Dict[str, Any]], now: datetime) -> bool:
    """True se un device VITALE risulta giu' dal suo poll DIRETTO (ICMP/SNMP)
    in modo sostenuto e FRESCO: >= VITAL_FAST_FAILURES fallimenti consecutivi
    e ultimo poll entro VITAL_L2_FRESH_SECONDS. In tal caso l'evidenza L2
    (FDB/ARP stantia del suo MAC) NON deve piu' tenerlo 'healthy'."""
    if not pd or pd.get("reachable"):
        return False
    last = pd.get("last_ping_at") or pd.get("last_poll")
    lp = _parse_dt(last)
    if not lp or (now - lp).total_seconds() > VITAL_L2_FRESH_SECONDS:
        return False  # poll non fresco → non forziamo (evita falsi da dati vecchi)
    try:
        consec = int(md.get("consecutive_ping_failures") or 0)
    except (TypeError, ValueError):
        consec = 0
    return consec >= VITAL_FAST_FAILURES


async def run_vital_watchdog(db, cfg_global: Dict[str, Any]) -> int:
    """Correlation-based watchdog: incrocia PING+DATTO+L2+WAN+iLO per dedurre
    la causa reale ed evitare falsi positivi. Con soppressione topologica
    (sito isolato / switch down -> un solo alert, figli soppressi)."""
    import correlation_engine as ce
    now = datetime.now(timezone.utc)

    families = list(ce.SERVER_TYPES | ce.FIREWALL_TYPES | ce.SWITCH_TYPES)
    targets = await db.managed_devices.find(
        {"$or": [{"is_vital": True}, {"device_type": {"$in": families}}, {"hyperv_alert_on_off": True}]},
        {"_id": 0, "client_id": 1, "ip": 1, "ip_address": 1, "name": 1, "device_name": 1,
         "device_type": 1, "mac": 1, "mac_address": 1, "hostname": 1, "serial": 1,
         "sys_name": 1, "dns_name": 1, "netbios_name": 1, "datto_hostname": 1,
         "datto_uid": 1, "source": 1, "is_vital": 1, "hyperv_alert_on_off": 1,
         "consecutive_ping_failures": 1},
    ).to_list(10000)
    if not targets:
        return 0

    ctx = await ce.build_context(db, cfg_global)

    # poll records best-per-ip
    ips = [t.get("ip") for t in targets if t.get("ip")]
    poll_by_ip: dict = {}
    if ips:
        grouped: dict = {}
        async for r in db.device_poll_status.find({"device_ip": {"$in": ips}}, {"_id": 0}):
            grouped.setdefault(r.get("device_ip"), []).append(r)
        for ip, lst in grouped.items():
            poll_by_ip[ip] = await _best_poll_record(lst)

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    client_names = {c.get("id"): c.get("name") for c in clients}

    # PASS 1 — segnali + verdetto preliminare
    items = []  # (md, family, signals, verdict)
    down_count_by_client: dict = {}
    unreachable_by_client: dict = {}  # ping fail AND no L2 -> irraggiungibile "vero"
    for md in targets:
        cid = md.get("client_id"); ip = md.get("ip") or md.get("ip_address")
        if not cid or not ip:
            continue
        fam = ce.device_family(md)
        s = ce.gather_signals(md, poll_by_ip.get(ip), ctx)
        # v2026-06 SPEED: per i device VITALI/infrastruttura con down DIRETTO
        # confermato (>=2 poll falliti, fresco) ignoriamo l'evidenza L2 stantia
        # e marchiamo la conferma rapida → l'alert bypassa il gate temporale.
        if fam in ("switch", "firewall", "server") or md.get("is_vital"):
            if _vital_direct_down(md, poll_by_ip.get(ip), now):
                s["l2_alive"] = False
                s["_fast_confirmed"] = True
        if fam == "server":
            v = ce.verdict_server(s, None)
            # iLO probe SOLO se down + Datto offline + credenziali iLO presenti
            if not v["up"] and s.get("datto") == "offline":
                try:
                    from security import security_manager
                    from deps import redfish_poller
                    ilo = await ce.resolve_ilo_power(db, security_manager, redfish_poller, ip)
                    if ilo:
                        v = ce.verdict_server(s, ilo)
                except Exception:
                    pass
        elif fam == "firewall":
            v = ce.verdict_firewall(s, majority_down=False)  # rifinito in pass 2
        elif fam == "switch":
            v = ce.verdict_switch(s, children_all_down=False, has_children=False)
        else:
            v = ce.verdict_generic(s)
        if not v["up"] and v["alertable"]:
            down_count_by_client[cid] = down_count_by_client.get(cid, 0) + 1
        if s.get("ping") is not True and not s.get("l2_alive"):
            unreachable_by_client[cid] = unreachable_by_client.get(cid, 0) + 1
        items.append([md, fam, s, v])

    total_by_client: dict = {}
    for md, *_ in items:
        total_by_client[md["client_id"]] = total_by_client.get(md["client_id"], 0) + 1

    site_down_ratio = float(cfg_global.get("site_down_ratio", 0.8))

    # PASS 2 — rifinitura firewall/switch + soppressione topologica + cause globali
    isolated_clients = set()
    down_switch_ips = set()
    # Rilevamento SITO GIU'/assenza corrente basato su segnali AFFIDABILI:
    #  - "site_power_down": connettore on-site NON raggiunge piu' il cloud E il
    #    probe WAN ESTERNO (cloud-side, sempre fresco) vede l'internet del
    #    cliente GIU' → outage totale (mancanza corrente o WAN a monte giu').
    #  - "site_down": connettore ancora vivo ma la quasi totalita' dei device
    #    e' irraggiungibile → isolamento di rete interno.
    site_outage_clients: dict = {}  # cid -> kind
    for cid, total in total_by_client.items():
        if total < 3:
            continue
        sh = (ctx.get("source_health") or {}).get(cid) or {}
        connector_up = sh.get("connector_reliable", True)
        internet_up = sh.get("internet_up")
        ratio = unreachable_by_client.get(cid, 0) / max(total, 1)
        if (not connector_up) and internet_up is False:
            site_outage_clients[cid] = "site_power_down"
        elif connector_up and ratio >= site_down_ratio:
            site_outage_clients[cid] = "site_down"

    for it in items:
        md, fam, s, v = it
        cid = md["client_id"]
        if fam == "firewall" and not v["up"]:
            down = down_count_by_client.get(cid, 0)
            total = max(total_by_client.get(cid, 1), 1)
            majority = down >= max(2, int(total * 0.5))
            it[3] = ce.verdict_firewall(s, majority_down=majority)
            if it[3]["root_cause"] == "site_isolated":
                isolated_clients.add(cid)
        elif fam == "switch" and not v["up"]:
            sw_ip = md.get("ip") or md.get("ip_address")
            children = [x for x in items
                        if ctx["child_to_switch"].get(x[0].get("ip") or x[0].get("ip_address")) == sw_ip]
            has_children = len(children) > 0
            children_all_down = has_children and all(not c[3]["up"] for c in children)
            it[3] = ce.verdict_switch(s, children_all_down=children_all_down, has_children=has_children)
            if it[3]["root_cause"] == "switch_down":
                down_switch_ips.add(sw_ip)

    # Applica la causa globale di outage: promuove il verdetto piu' rappresentativo
    # (firewall se presente, altrimenti il primo device down) e sopprime i figli.
    for cid, kind in site_outage_clients.items():
        isolated_clients.add(cid)
        anchor = None
        for it in items:
            if it[0]["client_id"] != cid or it[3]["up"]:
                continue
            if it[1] == "firewall":
                anchor = it
                break
            if anchor is None:
                anchor = it
        if anchor is None:
            continue
        if kind == "site_power_down":
            confirmed, ups_detail = await _ups_power_loss(db, cid)
            if confirmed:
                timeline = await _blackout_timeline(db, cid, datetime.now(timezone.utc))
                anchor[3] = ce._V(False, True, "critical", 99, "site_power_down",
                    "SITO TOTALMENTE GIU' con MANCANZA DI CORRENTE CONFERMATA "
                    f"({ups_detail} poco prima del blackout). Firewall/gateway, connettore "
                    "on-site e la quasi totalita' dei device irraggiungibili." + timeline)
                anchor[3]["power_confirmed"] = True
            else:
                anchor[3] = ce._V(False, True, "critical", 96, "site_power_down",
                    "Firewall/gateway, connettore on-site e la quasi totalita' dei device "
                    "irraggiungibili contemporaneamente → SITO TOTALMENTE GIU' "
                    "(possibile MANCANZA DI CORRENTE o guasto WAN a monte).")
        else:
            anchor[3] = ce._V(False, True, "critical", 95, "site_isolated",
                "La quasi totalita' dei device del sito e' irraggiungibile → SITO ISOLATO "
                "(guasto di rete/uplink). Un solo alert aggregato, dispositivi figli soppressi.")

    site_anchor_md_ids = set()
    for cid in site_outage_clients:
        for it in items:
            if it[0]["client_id"] == cid and it[3].get("root_cause") in ("site_power_down", "site_isolated"):
                site_anchor_md_ids.add(id(it[0]))

    def _is_suppressed(md, fam):
        cid = md["client_id"]; ip = md.get("ip") or md.get("ip_address")
        # L'anchor dell'outage di sito NON va mai soppresso (e' l'unico alert emesso)
        if id(md) in site_anchor_md_ids:
            return False
        if cid in isolated_clients and fam != "firewall":
            return True
        parent_sw = ctx["child_to_switch"].get(ip)
        if parent_sw and parent_sw in down_switch_ips and md.get("device_type", "").lower() not in ce.SWITCH_TYPES:
            return True
        return False

    # +N IMPATTI: per ogni alert "padre" (switch down / sito isolato) raccogli la
    # lista dei device figli soppressi, cosi' l'alert riporta l'impatto reale.
    impacts_by_anchor: dict = {}
    for it in items:
        md_a, fam_a, _s_a, v_a = it
        rc = v_a.get("root_cause")
        if rc == "switch_down":
            sw_ip = md_a.get("ip") or md_a.get("ip_address")
            kids = []
            for x in items:
                xip = x[0].get("ip") or x[0].get("ip_address")
                if xip and xip != sw_ip and ctx["child_to_switch"].get(xip) == sw_ip:
                    kids.append({"name": _best_device_name(x[0], xip), "ip": xip})
            if kids:
                impacts_by_anchor[id(md_a)] = kids
        elif rc in ("site_isolated", "site_power_down"):
            cid_a = md_a["client_id"]
            kids = []
            for x in items:
                if x[0]["client_id"] != cid_a or id(x[0]) == id(md_a):
                    continue
                xip = x[0].get("ip") or x[0].get("ip_address")
                if x[1] != "firewall":
                    kids.append({"name": _best_device_name(x[0], xip), "ip": xip})
            if kids:
                impacts_by_anchor[id(md_a)] = kids

    warn_min = float(cfg_global.get("vital_warn_minutes", 3))
    actions = 0

    for md, fam, s, v in items:
        cid = md["client_id"]; ip = md.get("ip")
        dev_name = _best_device_name(md, ip)
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        dev_type = md.get("device_type") or fam
        cfg = await _resolve_client_config(db, cfg_global, cid)
        state = await db.vital_offline_state.find_one({"client_id": cid, "ip": ip})

        # UP → risolvi eventuale stato "down" + recovery
        if v["up"]:
            if state:
                aid = state.get("alert_id")
                if aid:
                    await db.alerts.update_one({"id": aid},
                        {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
                if state.get("level", 0) >= 1 and cfg.get("auto_recovery"):
                    rec = _mk_alert(cid, cname, dev_name, ip, dev_type, "low",
                        "device_recovery", f"ONLINE (ripristinato): {dev_name}",
                        f"'{dev_name}' ({ip}) del cliente {cname} e' tornato raggiungibile.")
                    await _emit_recovery_notice(db, cfg, rec)
                    actions += 1
                await db.vital_offline_state.delete_one({"client_id": cid, "ip": ip})

            # Alert INFORMATIVO (up ma anomalo, es. agent Datto KO): dedup, no escalation
            info_src = f"corr_{v['root_cause']}"
            existing_info = await db.alerts.find_one(
                {"client_id": cid, "device_ip": ip, "source_type": info_src, "status": "active"})
            if v["alertable"] and not _is_suppressed(md, fam):
                if not existing_info:
                    alert = _mk_alert(cid, cname, dev_name, ip, dev_type, v["severity"], info_src,
                        f"Info: {dev_name} — {v['root_cause'].replace('_',' ').upper()}",
                        f"Cliente {cname}: {v['reasoning']} (confidenza {v['confidence']}%)")
                    await insert_alert_if_emit(db, alert)
                    await _dispatch_notification(db, cfg, alert)
                    actions += 1
            else:
                # non piu' anomalo → risolvi eventuali info corr_* attivi del device
                await db.alerts.update_many(
                    {"client_id": cid, "device_ip": ip,
                     "source_type": {"$regex": "^corr_"}, "status": "active"},
                    {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
            continue

        if not v["alertable"]:
            continue

        # Soppressione topologica: non creare alert figli
        if _is_suppressed(md, fam):
            continue

        # DOWN alertable — gestione stato + gate temporale/confidenza
        if not state:
            await db.vital_offline_state.insert_one({
                "client_id": cid, "ip": ip, "device_name": dev_name,
                "first_offline_at": now.isoformat(), "level": 0,
                "alert_id": None, "severity": None, "root_cause": v["root_cause"]})
            state = {"first_offline_at": now.isoformat(), "level": 0,
                     "alert_id": None, "severity": None}
        first_off = _parse_dt(state.get("first_offline_at")) or now
        elapsed_min = (now - first_off).total_seconds() / 60.0
        should_fire = v["confidence"] >= 90 or elapsed_min >= warn_min or bool(s.get("_fast_confirmed"))
        if not should_fire:
            continue

        sev = v["severity"]
        prev_sev = state.get("severity")
        reasoning = f"{v['reasoning']} (confidenza {v['confidence']}%)"
        source_type = f"corr_{v['root_cause']}"
        title_map = {
            "critical": f"CRITICO: {dev_name}",
            "high": f"ALERT: {dev_name}",
            "medium": f"Attenzione: {dev_name}",
            "low": f"Info: {dev_name}",
        }
        title = f"{title_map.get(sev, dev_name)} — {v['root_cause'].replace('_',' ').upper()}"

        # +N IMPATTI: arricchisci il titolo/messaggio dell'alert padre con i figli soppressi.
        _impacts = impacts_by_anchor.get(id(md)) or []
        _impact_msg = ""
        if _impacts:
            n = len(_impacts)
            title += f" · {n} dispositivi a valle impattati"
            _names = ", ".join(d["name"] for d in _impacts[:12])
            if n > 12:
                _names += f" (+{n - 12} altri)"
            _impact_msg = f" — {n} dispositivi a valle impattati: {_names}"

        if state.get("level", 0) == 0:
            alert = _mk_alert(cid, cname, dev_name, ip, dev_type, sev, source_type, title,
                              f"Cliente {cname}: {reasoning}{_impact_msg}")
            if _impacts:
                alert["impacted_count"] = len(_impacts)
                alert["impacted_devices"] = _impacts[:50]
            from alert_enrichment import enrich_alert
            await enrich_alert(db, alert)
            await insert_alert_if_emit(db, alert)
            await _dispatch_notification(db, cfg, alert)
            await db.vital_offline_state.update_one({"client_id": cid, "ip": ip},
                {"$set": {"level": 1, "alert_id": alert["id"], "severity": sev,
                          "root_cause": v["root_cause"]}})
            actions += 1
            logger.warning("[corr] %s %s (%s) client=%s conf=%s", sev, v["root_cause"], ip, cname, v["confidence"])
        elif prev_sev and SEVERITY_RANK_LOCAL.get(sev, 0) > SEVERITY_RANK_LOCAL.get(prev_sev, 0):
            aid = state.get("alert_id")
            if aid:
                await db.alerts.update_one({"id": aid},
                    {"$set": {"severity": sev, "title": title, "message": f"ESCALATION — {reasoning}"}})
                alert = await db.alerts.find_one({"id": aid}, {"_id": 0})
                if alert:
                    await _dispatch_notification(db, cfg, alert)
            await db.vital_offline_state.update_one({"client_id": cid, "ip": ip},
                {"$set": {"severity": sev, "root_cause": v["root_cause"]}})
            actions += 1
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

    # Source-health per cliente (internet_up + datto_reliable/blackout di massa).
    # Serve al gating "100%" sui server SOLO-Datto (parte B): un server e'
    # colpevole con certezza SOLO se la linea internet del sito e' UP e non c'e'
    # un blackout di massa (= altri device del sito ancora online). Cosi' un
    # outage di linea/sito non genera falsi "server offline" sul singolo device.
    try:
        import correlation_engine as ce
        _ctx = await ce.build_context(db, cfg_global)
        source_health = _ctx.get("source_health") or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("datto watchdog: build_context fallito, gating disattivato: %s", e)
        source_health = {}

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
                # Il ripristino e' un evento POSITIVO: notificato ma salvato come
                # 'resolved' (storico), mai come alert attivo (no duplicati).
                await _emit_recovery_notice(db, cfg, rec)
            actions += 1

    # --- B) Server Datto offline oltre soglia ---
    servers = await db.datto_devices.find(
        {"$or": [{"device_type": {"$regex": "server", "$options": "i"}},
                 {"is_server": True}]},
        {"_id": 0, "client_id": 1, "uid": 1, "name": 1, "ip": 1, "ip_list": 1,
         "online": 1, "datto_last_seen": 1, "device_type": 1},
    ).to_list(20000)

    for dev in servers:
        cid = dev.get("client_id")
        uid = dev.get("uid")
        if not cid or not uid:
            continue
        if dev.get("online") is None:
            continue  # sync non ha ancora popolato lo stato online
        # Se il server Datto e' anche un managed_device -> lo gestisce il
        # correlation watchdog (con incrocio ping/L2/iLO). Evita doppioni.
        dev_ips = [dev.get("ip")] + (dev.get("ip_list") or [])
        dev_ips = [x for x in dev_ips if x]
        if dev_ips and await db.managed_devices.count_documents(
            {"client_id": cid, "ip": {"$in": dev_ips}}
        ):
            continue
        cfg = await _resolve_client_config(db, cfg_global, cid)
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        name = dev.get("name") or uid
        state = await db.datto_offline_state.find_one({"client_id": cid, "uid": uid})
        online = bool(dev.get("online"))

        if not online:
            # --- GATING 100% (evidence fusion sui server SOLO-Datto) ---
            # Emetti l'alert "server offline" SOLO con prove positive che sia
            # un problema del SINGOLO device e non della linea/sito:
            #  (a) linea internet del sito NON provata giu' (altrimenti e' un
            #      problema ISP/sito -> lo gestisce il watchdog firewall/vitali);
            #  (b) sorgente Datto affidabile (no blackout di massa: se >=60% dei
            #      device Datto sono offline insieme, gli "altri device" NON sono
            #      online -> problema di rete/portale, segnale non attendibile).
            # Nota: se non abbiamo prove (internet_up=None) NON blocchiamo, per
            # non perdere alert sui clienti privi di sonda WAN.
            sh = source_health.get(cid) or {}
            if sh.get("internet_up") is False:
                logger.info("[datto] gating: %s offline ma linea internet GIU' client=%s -> sospeso (problema linea/sito)", name, cname)
                continue
            if sh.get("datto_reliable") is False:
                logger.info("[datto] gating: %s offline ma Datto inaffidabile (%s) client=%s -> sospeso (blackout/altri device offline)", name, sh.get("datto_reason"), cname)
                continue

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
                    await _emit_recovery_notice(db, cfg, rec)
                    actions += 1
                await db.datto_offline_state.delete_one({"client_id": cid, "uid": uid})
    return actions


# ---------------------------------------------------------------------------
# Watchdog 3 — Nuovi dispositivi rilevati da classificare
# ---------------------------------------------------------------------------

async def run_new_device_watchdog(db, cfg_global: Dict[str, Any]) -> int:
    if not cfg_global.get("new_device_detection", True):
        return 0
    now = datetime.now(timezone.utc)
    window_h = float(cfg_global.get("new_device_window_hours", 24))
    since = (now - timedelta(hours=window_h)).isoformat()
    actions = 0

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    client_names = {c.get("id"): c.get("name") for c in clients}

    INFRA_KW = ("server", "firewall", "router", "switch", "nas", "ups", "ilo", "storage", "gateway")

    docs = await db.managed_devices.find(
        {"$and": [
            {"$or": [{"is_vital": None}, {"is_vital": {"$exists": False}}]},
            {"created_at": {"$gte": since}},
        ]},
        {"_id": 0, "client_id": 1, "ip": 1, "name": 1, "device_type": 1},
    ).to_list(20000)
    by_client: dict = {}
    for d in docs:
        by_client.setdefault(d.get("client_id"), []).append(d)

    active = db.alerts.find({"source_type": "new_devices_detected", "status": "active"},
                            {"_id": 0, "id": 1, "client_id": 1})
    active_by_client = {a["client_id"]: a async for a in active}

    for cid, lst in by_client.items():
        if not cid:
            continue
        cfg = await _resolve_client_config(db, cfg_global, cid)
        cname = client_names.get(cid) or (cid[:8] if cid else "")

        # AUTO-PROMOTE: l'infrastruttura scoperta diventa vitale automaticamente
        if cfg.get("auto_promote_infra"):
            promoted = []
            for d in list(lst):
                dt = (d.get("device_type") or "").lower()
                if d.get("ip") and any(k in dt for k in INFRA_KW):
                    await db.managed_devices.update_many(
                        {"client_id": cid, "ip": d["ip"]},
                        {"$set": {"is_vital": True, "is_vital_reason": "auto-promote infra",
                                  "is_vital_set_by": "alert-engine", "is_vital_set_at": now.isoformat()}})
                    promoted.append(d.get("name") or d.get("ip"))
                    lst.remove(d)
            if promoted:
                try:
                    from alert_filter import invalidate_silence_cache
                    invalidate_silence_cache(client_id=cid)
                except Exception:
                    pass
                al = _mk_alert(cid, cname, "Discovery", "", "discovery", "low", "auto_promoted_vital",
                    f"⭐ {len(promoted)} dispositivi promossi a Vitali su {cname}",
                    f"Auto-promozione infrastruttura: {', '.join(promoted[:6])}"
                    f"{'…' if len(promoted) > 6 else ''} ora monitorati come Vitali.")
                await insert_alert_if_emit(db, al)
                await _dispatch_notification(db, cfg, al)
                actions += 1
                logger.info("[auto-promote] %s infra->vital client=%s", len(promoted), cname)

        # Restanti device non classificati → alert di triage
        n = len(lst)
        existing = active_by_client.get(cid)
        if n > 0:
            sample = ", ".join([(d.get("name") or d.get("ip")) for d in lst if (d.get("name") or d.get("ip"))][:5])
            msg = (f"Rilevati {n} nuovi dispositivi da classificare sul cliente {cname}"
                   + (f": {sample}{'…' if n > 5 else ''}." if sample else ".")
                   + " Vai in Panoramica → Classifica ora per agganciare quelli vitali.")
            if not existing:
                alert = _mk_alert(cid, cname, "Discovery", "", "discovery", "medium",
                                  "new_devices_detected", f"🆕 {n} nuovi dispositivi su {cname}", msg)
                await insert_alert_if_emit(db, alert)
                await _dispatch_notification(db, cfg, alert)
                actions += 1
                logger.info("[new-device] %s nuovi su client=%s", n, cname)
            else:
                await db.alerts.update_one({"id": existing["id"]}, {"$set": {"message": msg}})
        elif existing:
            await db.alerts.update_one({"id": existing["id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
            actions += 1

    # Risolvi gli alert dei clienti che non hanno più device da classificare
    for cid, a in active_by_client.items():
        if cid not in by_client:
            await db.alerts.update_one({"id": a["id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
            actions += 1
    return actions



# ---------------------------------------------------------------------------
# Watchdog 4 — SITO GIU' / blackout (agent offline + WAN offline)
# ---------------------------------------------------------------------------

async def _ups_power_loss(db, client_id: str, minutes: int = 20):
    """Ritorna (confirmed: bool, detail: str): True se un UPS del cliente
    risulta 'su batteria' (rete elettrica assente) in una finestra recente.
    Serve a PROMUOVERE un blackout a "MANCANZA CORRENTE CONFERMATA".

    Proxy sui dati raccolti (metric_history: ups_charge_pct/ups_runtime_min):
    su rete utility la carica resta ~100%; se scende sotto ~95% (o l'autonomia
    e' finita/bassa) l'UPS sta erogando da batteria = corrente assente.
    Gated dietro un blackout gia' confermato (agent+WAN giu'), quindi robusto.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    # 1) Evento PRE-BLACKOUT persistente (registrato da predictive.py quando l'UPS
    #    e' passato su batteria). Sopravvive allo spegnimento dell'UPS stesso:
    #    conferma la mancanza corrente in TEMPO REALE dal primo secondo del down.
    try:
        ev = await db.pre_blackout_events.find_one(
            {"client_id": client_id, "last_seen_at": {"$gte": cutoff}},
            sort=[("last_seen_at", -1)],
        )
        if ev:
            return True, ev.get("detail") or f"UPS {ev.get('device_ip','')} su batteria poco prima del down"
    except Exception:  # noqa: BLE001
        pass
    # 2) Fallback: ultimi valori grezzi da metric_history (ups_charge_pct/runtime).
    q = {"client_id": client_id,
         "metric": {"$in": ["ups_charge_pct", "ups_runtime_min"]},
         "ts": {"$gte": cutoff}}
    latest_charge: Dict[str, float] = {}
    latest_runtime: Dict[str, float] = {}
    try:
        async for d in db.metric_history.find(
            q, {"_id": 0, "device_ip": 1, "metric": 1, "value": 1, "ts": 1}
        ).sort("ts", 1):
            ip = d.get("device_ip"); v = d.get("value")
            if not ip or not isinstance(v, (int, float)):
                continue
            if d.get("metric") == "ups_charge_pct":
                latest_charge[ip] = float(v)
            else:
                latest_runtime[ip] = float(v)
    except Exception:  # noqa: BLE001
        return False, ""
    for ip, charge in latest_charge.items():
        if charge < 95:
            det = f"UPS {ip} su batteria (carica {charge:.0f}%"
            rt = latest_runtime.get(ip)
            det += f", autonomia ~{rt:.0f} min)" if rt is not None else ")"
            return True, det
    for ip, rt in latest_runtime.items():
        if rt <= 30:
            return True, f"UPS {ip} su batteria (autonomia residua ~{rt:.0f} min)"
    return False, ""


def _fmt_local(dt) -> str:
    """Formatta un datetime UTC in ora locale IT (HH:MM)."""
    if not isinstance(dt, datetime):
        return "?"
    try:
        from zoneinfo import ZoneInfo
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return dt.strftime("%H:%M")


def _fmt_duration(seconds: float) -> str:
    """Durata leggibile: '1h 47m', '12m', '2g 3h'."""
    s = int(max(0, seconds))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f"{d}g {h}h" if h else f"{d}g"
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{m}m" if m else "meno di 1m"


def _parse_iso(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            return None
    return None


async def _blackout_timeline(db, client_id: str, down_at: datetime, minutes: int = 30) -> str:
    """Cronologia dell'evento: 'HH:MM UPS su batteria → HH:MM sito giu':
    MANCANZA CORRENTE CONFERMATA'. Vuoto se non c'e' un evento pre-blackout."""
    cutoff = down_at - timedelta(minutes=minutes)
    try:
        ev = await db.pre_blackout_events.find_one(
            {"client_id": client_id, "last_seen_at": {"$gte": cutoff}},
            sort=[("last_seen_at", -1)],
        )
    except Exception:  # noqa: BLE001
        ev = None
    if not ev:
        return ""
    since = ev.get("on_battery_since") or ev.get("last_seen_at")
    charge = ev.get("charge")
    rt = ev.get("runtime_min")
    extra = ""
    if charge is not None:
        extra = f" (carica {charge:.0f}%"
        extra += f", autonomia ~{rt:.0f} min)" if rt is not None else ")"
    return (f"\n\n📖 Cronologia evento:\n"
            f"• {_fmt_local(since)} — UPS passato su batteria{extra}\n"
            f"• {_fmt_local(down_at)} — SITO GIÙ: MANCANZA DI CORRENTE CONFERMATA")


async def run_site_blackout_watchdog(db, cfg_global: Dict[str, Any]) -> int:
    """Emette UN alert critico per cliente quando l'agent on-site e' offline E
    la sonda WAN esterna del Center vede l'internet GIU' (blackout confermato da
    due sorgenti indipendenti). Non dipende dal numero di device (a differenza
    del correlation watchdog), cosi' scatta anche sui clienti piccoli.

    Dedup: se il correlation watchdog ha gia' emesso un alert di sito
    (corr_site_power_down / corr_site_isolated) attivo per il cliente, NON
    duplichiamo (quello e' piu' ricco). Auto-recovery alla ripresa.
    """
    now = datetime.now(timezone.utc)
    actions = 0
    blackout = await lr.build_blackout_clients(db)

    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    client_names = {c.get("id"): c.get("name") for c in clients}

    # 1) Emissione per i clienti attualmente in blackout
    for cid in blackout:
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        cfg = await _resolve_client_config(db, cfg_global, cid)
        # Start DUREVOLE: registra started_at UNA sola volta; sopravvive a
        # qualsiasi path (corr o watchdog) per calcolare la durata alla ripresa.
        confirmed, ups_detail = await _ups_power_loss(db, cid)
        set_fields = {"client_id": cid, "last_seen_at": now.isoformat()}
        if confirmed:
            set_fields["power_confirmed"] = True
        await db.site_blackout_state.update_one(
            {"client_id": cid},
            {"$set": set_fields, "$setOnInsert": {"started_at": now.isoformat()}},
            upsert=True,
        )
        # Dedup contro l'alert correlation di sito (piu' ricco) gia' attivo
        corr_active = await db.alerts.find_one({
            "client_id": cid, "status": "active",
            "source_type": {"$in": ["corr_site_power_down", "corr_site_isolated"]},
        })
        state = await db.site_blackout_state.find_one({"client_id": cid})
        if corr_active:
            # corr gestisce l'alert visibile: se avevamo un nostro alert autonomo
            # chiudilo, MA mantieni lo state (started_at) per la durata a recovery.
            if state and state.get("alert_id"):
                await db.alerts.update_one({"id": state["alert_id"]},
                    {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
                await db.site_blackout_state.update_one({"client_id": cid},
                    {"$unset": {"alert_id": ""}, "$set": {"via": "corr"}})
            else:
                await db.site_blackout_state.update_one({"client_id": cid},
                    {"$set": {"via": "corr"}})
            continue
        if state and state.get("alert_id"):
            continue  # gia' emesso (last_seen aggiornato sopra)
        if confirmed:
            timeline = await _blackout_timeline(db, cid, now)
            title = f"SITO GIU' — MANCANZA CORRENTE CONFERMATA: {cname}"
            body = (f"Il sito del cliente {cname} risulta TOTALMENTE GIU' e la mancanza di "
                    f"CORRENTE e' CONFERMATA: {ups_detail} rilevato poco prima del blackout. "
                    f"L'agent on-site non risponde e la sonda WAN esterna vede l'internet "
                    f"irraggiungibile. Tutti i dispositivi del sito sono offline." + timeline)
        else:
            title = f"SITO GIU' / possibile BLACKOUT: {cname}"
            body = (f"Il sito del cliente {cname} risulta TOTALMENTE GIU': l'agent on-site "
                    f"non risponde piu' (nessun heartbeat) E la sonda WAN esterna del Center "
                    f"vede l'internet del cliente irraggiungibile. Due sorgenti indipendenti "
                    f"concordi -> probabile MANCANZA DI CORRENTE o guasto WAN a monte. "
                    f"Tutti i dispositivi del sito sono da considerarsi offline.")
        alert = _mk_alert(
            cid, cname, "Sito", "", "site", "critical", "site_blackout", title, body,
        )
        if confirmed:
            alert["power_confirmed"] = True
        from alert_enrichment import enrich_alert
        await enrich_alert(db, alert)
        await insert_alert_if_emit(db, alert)
        await _dispatch_notification(db, cfg, alert)
        await db.site_blackout_state.update_one(
            {"client_id": cid},
            {"$set": {"alert_id": alert["id"], "via": "watchdog"}},
        )
        actions += 1
        logger.warning("[site-blackout] SITO GIU' client=%s", cname)

    # 2) Recovery: clienti che avevano un blackout ma NON sono piu' in blackout
    async for state in db.site_blackout_state.find({}):
        cid = state.get("client_id")
        if not cid or cid in blackout:
            continue
        cname = client_names.get(cid) or (cid[:8] if cid else "")
        cfg = await _resolve_client_config(db, cfg_global, cid)
        # Durata totale del disservizio
        started = _parse_iso(state.get("started_at") or state.get("first_at"))
        dur = _fmt_duration((now - started).total_seconds()) if started else None
        power = bool(state.get("power_confirmed"))
        # Risolvi l'alert del watchdog (se presente) e gli eventuali alert corr di sito
        if state.get("alert_id"):
            await db.alerts.update_one({"id": state["alert_id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
        await db.alerts.update_many(
            {"client_id": cid, "status": "active",
             "source_type": {"$in": ["corr_site_power_down", "corr_site_isolated"]}},
            {"$set": {"status": "resolved", "resolved_at": now.isoformat()}})
        if cfg.get("auto_recovery"):
            if power:
                title = f"⚡ Corrente RIPRISTINATA: {cname}"
                msg = (f"La corrente elettrica presso {cname} e' tornata: sito di nuovo "
                       f"operativo. Corrente assente per {dur}." if dur else
                       f"La corrente elettrica presso {cname} e' tornata: sito operativo.")
            else:
                title = f"Sito RIPRISTINATO: {cname}"
                msg = (f"Il sito del cliente {cname} e' tornato raggiungibile "
                       f"(agent on-site + WAN operativi). Disservizio durato {dur}." if dur else
                       f"Il sito del cliente {cname} e' tornato raggiungibile. Blackout rientrato.")
            rec = _mk_alert(cid, cname, "Sito", "", "site", "low",
                            "site_blackout_recovery", title, msg)
            if dur:
                rec["outage_duration"] = dur
            await _emit_recovery_notice(db, cfg, rec)
        await db.site_blackout_state.delete_one({"client_id": cid})
        actions += 1
        logger.info("[site-blackout] recovery client=%s durata=%s power=%s", cname, dur, power)

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
        self._last_switch_persist: float = 0.0

    async def run_once(self) -> Dict[str, Any]:
        cfg = await get_config(self.db)
        if not cfg.get("enabled"):
            self.last_run = {"skipped": True, "at": datetime.now(timezone.utc).isoformat()}
            return self.last_run
        # Persistenza mappa switch_ip (FDB SNMP) ogni ~10 min per UI/topology
        import time as _t
        if _t.time() - self._last_switch_persist > 600:
            try:
                import correlation_engine as ce
                await ce.persist_switch_links(self.db)
            except Exception as e:  # noqa: BLE001
                logger.debug("switch link persist skip: %s", e)
            self._last_switch_persist = _t.time()
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
        try:
            await run_site_blackout_watchdog(self.db, cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning("site-blackout watchdog error: %s", e, exc_info=True)
        try:
            from routes.external_monitor import run_site_down_autotrace
            await run_site_down_autotrace(self.db)
        except Exception as e:  # noqa: BLE001
            logger.warning("site-down autotrace error: %s", e, exc_info=True)
        try:
            await run_new_device_watchdog(self.db, cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning("new-device watchdog error: %s", e, exc_info=True)
        try:
            await hyperv_vm_state_tick(self.db)
        except Exception as e:  # noqa: BLE001
            logger.warning("hyperv-vm watchdog error: %s", e, exc_info=True)
        try:
            await run_backbone_watchdog(self.db, cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning("backbone watchdog error: %s", e, exc_info=True)
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
