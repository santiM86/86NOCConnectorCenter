"""
Maintenance Gate — enforcement centralizzato delle finestre di manutenzione.

Durante una finestra di manutenzione ATTIVA (per un cliente e, opzionalmente,
per specifici device) gli alert NON vengono creati e le notifiche (Telegram /
push) NON vengono inviate. Questo evita che parta l'allarme quando, per es., si
riavvia un firewall di notte o durante la finestra di backup.

Schema `db.maintenance_windows` (scritto da routes/advanced_features.py):
  - client_id       : str
  - start_time      : ISO datetime (UTC)
  - end_time        : ISO datetime (UTC)
  - device_ips      : list[str]  (vuoto/None = TUTTI i device del cliente)
  - suppress_alerts : bool
  - recurring       : bool
  - recurrence_type : "daily" | "weekly" (usa l'ORA di start/end; per weekly
                      anche il giorno della settimana di start_time)

Uso:
    from maintenance_gate import is_in_maintenance
    if await is_in_maintenance(db, client_id, device_ip):
        return  # skip alert / notifica
"""
from __future__ import annotations

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("maintenance_gate")

# Cache per-cliente delle finestre suppress_alerts (TTL breve: le finestre
# cambiano di rado, ma "Silenzia ora" deve avere effetto quasi immediato).
_CACHE: dict[str, tuple[list, float]] = {}
_CACHE_TTL = 15.0


def _parse(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _window_active_now(w: dict, now: datetime) -> bool:
    """True se la finestra e' attiva ADESSO (gestisce ricorrenza e midnight-wrap)."""
    start = _parse(w.get("start_time"))
    end = _parse(w.get("end_time"))
    if not start or not end:
        return False

    if not w.get("recurring"):
        return start <= now <= end

    rtype = (w.get("recurrence_type") or "daily").lower()
    # Durata della finestra (per gestire wrap oltre la mezzanotte)
    duration = end - start
    if duration.total_seconds() <= 0:
        return False

    # Candidati "start di oggi" e "start di ieri" alla stessa ora di start_time
    def _candidate(day_offset: int) -> datetime:
        base = (now + timedelta(days=day_offset)).replace(
            hour=start.hour, minute=start.minute, second=start.second,
            microsecond=0)
        return base

    for off in (0, -1):
        cand_start = _candidate(off)
        cand_end = cand_start + duration
        if not (cand_start <= now <= cand_end):
            continue
        if rtype == "weekly":
            # Il giorno di riferimento e' quello di INIZIO finestra.
            if cand_start.weekday() != start.weekday():
                continue
        return True
    return False


async def _load_windows(db, client_id: str) -> list:
    now = time.time()
    cached = _CACHE.get(client_id)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    try:
        windows = await db.maintenance_windows.find(
            {"client_id": client_id, "suppress_alerts": {"$ne": False}},
            {"_id": 0, "start_time": 1, "end_time": 1, "device_ips": 1,
             "recurring": 1, "recurrence_type": 1, "suppress_alerts": 1,
             "title": 1, "id": 1},
        ).to_list(200)
    except Exception:
        windows = []
    _CACHE[client_id] = (windows, now)
    return windows


async def is_in_maintenance(
    db, client_id: Optional[str], device_ip: Optional[str] = None
) -> bool:
    """True se il device (o l'intero cliente) e' in una finestra di manutenzione
    attiva con soppressione alert."""
    if not client_id:
        return False
    now = datetime.now(timezone.utc)
    for w in await _load_windows(db, client_id):
        if not _window_active_now(w, now):
            continue
        dips = w.get("device_ips") or []
        if not dips:
            return True  # finestra su tutto il cliente
        if device_ip and device_ip in dips:
            return True
    return False


async def active_window_for(
    db, client_id: Optional[str], device_ip: Optional[str] = None
) -> Optional[dict]:
    """Ritorna la finestra attiva che copre il device (per logging/UI), o None."""
    if not client_id:
        return None
    now = datetime.now(timezone.utc)
    for w in await _load_windows(db, client_id):
        if not _window_active_now(w, now):
            continue
        dips = w.get("device_ips") or []
        if not dips or (device_ip and device_ip in dips):
            return w
    return None


def invalidate_cache(client_id: Optional[str] = None) -> None:
    if client_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(client_id, None)
