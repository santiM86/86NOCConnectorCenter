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


async def is_device_silenced(db, client_id: Optional[str], device_ip: Optional[str]) -> bool:
    """True se il device ha alerts_silenced=true. False altrimenti (incluso device
    sconosciuto, mancante client_id/ip, errore DB)."""
    if not client_id or not device_ip:
        return False
    key = (client_id, device_ip)
    now = time.time()
    cached = _SILENCE_CACHE.get(key)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    try:
        doc = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip, "alerts_silenced": True},
            {"_id": 0, "id": 1},
        )
        silenced = doc is not None
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
