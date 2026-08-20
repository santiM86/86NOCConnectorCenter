"""
Alert Filter — Per-device alert silencing
=========================================
Gating helper centrale per evitare la creazione di alert quando il device
target ha `alerts_silenced=true` in `managed_devices`.

Use case principale: stampanti / device "best-effort" che vanno regolarmente
offline (sera/weekend) ma per cui non vogliamo generare alert ne' push.

API:
    if await should_emit_alert(db, client_id, device_ip):
        await db.alerts.insert_one(alert_doc)
"""
from typing import Optional


# Cache locale TTL 30s per ridurre query a ogni alert (le scritte sul flag
# sono rare — toggle manuale dall'admin). Se cambia il flag, max 30s di
# delay prima che gli alert riprendano/smettano. Buon trade-off perf/UX.
import time

_SILENCE_CACHE: dict[tuple, tuple[bool, float]] = {}
_CACHE_TTL = 30.0

# v2026-06-23 SCHEDULED DOWNTIME (stile Nagios): cache separata per lo stato
# "in finestra di manutenzione". Le finestre stanno in db.maintenance_windows
# (CRUD in routes/advanced_features.py) ma PRIMA non venivano mai consultate
# dal motore di alert → si creavano ma non sopprimevano nulla. Ora is_device_
# silenced le controlla con priorita' massima (la manutenzione programmata
# sopprime TUTTO, anche i device vitali — come lo "scheduled downtime" Nagios).
_MAINT_CACHE: dict[str, tuple[list, float]] = {}
_MAINT_TTL = 20.0


async def get_active_maintenance_windows(db, client_id):
    """Ritorna la lista delle finestre di manutenzione ATTIVE adesso per il
    cliente (suppress_alerts=True, start<=now<=end). Cache 20s per client."""
    if not client_id:
        return []
    now_t = time.time()
    cached = _MAINT_CACHE.get(client_id)
    if cached and (now_t - cached[1]) < _MAINT_TTL:
        return cached[0]
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    windows = []
    try:
        cursor = db.maintenance_windows.find({
            "client_id": client_id,
            "suppress_alerts": True,
            "start_time": {"$lte": now_iso},
            "end_time": {"$gte": now_iso},
        }, {"_id": 0})
        windows = await cursor.to_list(50)
    except Exception:
        windows = []
    _MAINT_CACHE[client_id] = (windows, now_t)
    return windows


async def is_in_maintenance(db, client_id, device_ip) -> bool:
    """True se il device (o l'intero cliente) e' dentro una finestra di
    manutenzione attiva. Una finestra con device_ips vuoto = TUTTO il cliente;
    altrimenti vale solo per gli IP elencati."""
    if not client_id:
        return False
    for w in await get_active_maintenance_windows(db, client_id):
        ips = w.get("device_ips") or []
        if not ips:
            return True  # finestra a livello cliente → copre tutti i device
        if device_ip and device_ip in ips:
            return True
    return False


def invalidate_maintenance_cache(client_id=None) -> None:
    """Invalida la cache manutenzione dopo create/update/delete di una finestra."""
    if client_id is None:
        _MAINT_CACHE.clear()
    else:
        _MAINT_CACHE.pop(client_id, None)


# v2026-06-23 PARENT-CHILD DEPENDENCIES (stile Nagios "down vs unreachable").
# Se il PADRE di un device (lo switch/gateway a monte) e' OFFLINE, il device
# non e' "down per colpa sua" ma "UNREACHABLE" (irraggiungibile): non ha senso
# allertare su 50 device dietro uno switch morto → 1 solo alert (lo switch).
# Parent risolto da: 1) override manuale managed_devices.parent_ip,
# 2) auto da discovered_endpoints.switch_ip (FDB/MAC table).
_PARENT_CACHE: dict[tuple, tuple] = {}
_PARENT_TTL = 60.0


async def resolve_parent_ip(db, client_id, device_ip):
    """IP del device 'padre' (switch/gateway a monte) o None. Cache 60s."""
    if not client_id or not device_ip:
        return None
    key = (client_id, device_ip)
    cached = _PARENT_CACHE.get(key)
    if cached and (time.time() - cached[1]) < _PARENT_TTL:
        return cached[0]
    parent_ip = None
    try:
        md = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip},
            {"_id": 0, "parent_ip": 1, "parent_ip_auto": 1},
        )
        if md:
            # override manuale ha priorita'
            parent_ip = (md.get("parent_ip") or "").strip() or None
        if not parent_ip:
            ep = await db.discovered_endpoints.find_one(
                {"client_id": client_id, "ip": device_ip, "switch_ip": {"$nin": [None, "", device_ip]}},
                {"_id": 0, "switch_ip": 1},
            )
            if ep:
                parent_ip = ep.get("switch_ip") or None
    except Exception:
        parent_ip = None
    _PARENT_CACHE[key] = (parent_ip, time.time())
    return parent_ip


async def get_dependency_state(db, client_id, device_ip):
    """Ritorna (parent_ip, parent_name, parent_status). parent_status puo'
    essere 'online'/'offline'/None (parent sconosciuto)."""
    parent_ip = await resolve_parent_ip(db, client_id, device_ip)
    if not parent_ip or parent_ip == device_ip:
        return None, None, None
    try:
        p = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": parent_ip},
            {"_id": 0, "name": 1, "device_name": 1, "status": 1},
        )
    except Exception:
        p = None
    if not p:
        return parent_ip, None, None
    return parent_ip, (p.get("name") or p.get("device_name") or parent_ip), p.get("status")


async def is_dependency_unreachable(db, client_id, device_ip) -> bool:
    """True se il PADRE del device e' OFFLINE → device irraggiungibile
    (dependency). Gli alert vanno soppressi (Nagios "unreachable host")."""
    _, _, parent_status = await get_dependency_state(db, client_id, device_ip)
    return parent_status == "offline"


def invalidate_parent_cache(client_id=None, device_ip=None) -> None:
    if client_id is None:
        _PARENT_CACHE.clear()
    else:
        _PARENT_CACHE.pop((client_id, device_ip), None)


async def is_device_silenced(db, client_id: Optional[str], device_ip: Optional[str]) -> bool:
    """True se il device deve essere silenziato dal motore di alert.

    Silenziato significa: NON inviare alert.
    Logica unificata (v2026-02-28):
      - `alerts_silenced=True`           → silenziato (override esplicito di
                                           maintenance / finestra silenziata)
      - `is_vital=False`                 → silenziato (device "best-effort":
                                           monitorato ma NON allerta di default)
      - `is_vital=True` (anche con alerts_silenced=True) → NON silenziato
        (i device vitali NON possono essere silenziati per evitare missed alert
        critici — `is_vital` ha precedenza).
      - default (entrambi i campi assenti) → NON silenziato (backward compat:
        ogni device storico genera alert come prima del fix v2026-02-28).
    """
    if not client_id or not device_ip:
        return False
    # v2026-06-23 SCHEDULED DOWNTIME ha priorita' massima (Nagios-style):
    # se il device o il cliente sono in manutenzione, NESSUN alert — neanche
    # per i device vitali (stai lavorando tu su quel device, non e' un fault).
    # NON cacheato nel _SILENCE_CACHE perche' time-sensitive ai boundary.
    if await is_in_maintenance(db, client_id, device_ip):
        return True
    # v2026-06-23 PARENT DEPENDENCY: se il padre (switch/gateway a monte) e'
    # OFFLINE, questo device e' UNREACHABLE (non down per colpa sua) → niente
    # alert (Nagios sopprime le notifiche per host unreachable). Evita le
    # tempeste di alert quando muore uno switch con 50 device a valle.
    if await is_dependency_unreachable(db, client_id, device_ip):
        return True
    key = (client_id, device_ip)
    now = time.time()
    cached = _SILENCE_CACHE.get(key)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    try:
        doc = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip},
            {"_id": 0, "alerts_silenced": 1, "is_vital": 1},
        )
        if not doc:
            silenced = False
        else:
            # Vital ha precedenza: i device vitali NON si silenziano.
            if doc.get("is_vital") is True:
                silenced = False
            elif doc.get("alerts_silenced") is True:
                silenced = True
            elif doc.get("is_vital") is False:
                silenced = True
            else:
                silenced = False
    except Exception:
        silenced = False
    _SILENCE_CACHE[key] = (silenced, now)
    return silenced


async def should_emit_alert(db, client_id: Optional[str], device_ip: Optional[str]) -> bool:
    """Inverso semantico di is_device_silenced — comodo per leggere il codice
    chiamante: `if await should_emit_alert(...): await db.alerts.insert_one(...)`."""
    return not await is_device_silenced(db, client_id, device_ip)


def invalidate_silence_cache(client_id: Optional[str] = None, device_ip: Optional[str] = None) -> None:
    """Invalida la cache dopo toggle del flag. Se entrambi None, svuota tutto."""
    if client_id is None and device_ip is None:
        _SILENCE_CACHE.clear()
        return
    if client_id and device_ip:
        _SILENCE_CACHE.pop((client_id, device_ip), None)
        return
    # Invalida tutte le entry di un cliente
    keys_to_drop = [k for k in _SILENCE_CACHE if k[0] == client_id]
    for k in keys_to_drop:
        _SILENCE_CACHE.pop(k, None)


async def insert_alert_if_emit(db, alert_doc: dict) -> bool:
    """Wrapper drop-in per `db.alerts.insert_one(alert_doc)` che skippa l'insert
    se il device target ha alerts_silenced=true. Estrae client_id e device_ip
    dal documento alert. Restituisce True se inserito, False se silenziato.

    Convenzione campi alert_doc:
      - client_id: id del cliente (managed_devices.client_id)
      - device_ip OPPURE ip: indirizzo target del device

    Per alert non legati a un device specifico (es. backup-job globale,
    system-wide), passare client_id ma niente device_ip -> non silenziato.
    """
    cid = alert_doc.get("client_id")
    ip = alert_doc.get("device_ip") or alert_doc.get("ip")
    if cid and ip:
        if await is_device_silenced(db, cid, ip):
            return False
    await db.alerts.insert_one(alert_doc)
    return True
