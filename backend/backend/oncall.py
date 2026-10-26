"""
On-Call Rotation — instrada le notifiche push al personale di turno.

Schema (single document in db.oncall_config):
{
  "rotation_enabled": bool,
  "timezone": "Europe/Rome",
  "slots": [
    {
      "id": "uuid",
      "day_of_week": 0..6,        # Mon=0 ... Sun=6 (ISO)
      "start": "08:00",           # inclusive
      "end": "18:00",             # exclusive; if start>end -> overnight slot ending next day
      "user_id": "<user uuid>",
      "user_email": "mail@x.y",
      "label": ""                 # optional
    }, ...
  ]
}
"""
from __future__ import annotations
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _parse_hhmm(s: str) -> Optional[dtime]:
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


async def get_config(db) -> Dict[str, Any]:
    doc = await db.oncall_config.find_one({"_id": "singleton"}, {"_id": 0})
    if not doc:
        return {"rotation_enabled": False, "timezone": "Europe/Rome", "slots": []}
    doc.setdefault("rotation_enabled", False)
    doc.setdefault("timezone", "Europe/Rome")
    doc.setdefault("slots", [])
    return doc


async def save_config(db, config: Dict[str, Any]) -> None:
    await db.oncall_config.update_one(
        {"_id": "singleton"},
        {"$set": config},
        upsert=True,
    )


def _now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _slot_matches(slot: Dict[str, Any], now: datetime) -> bool:
    dow = int(slot.get("day_of_week", 0))
    start = _parse_hhmm(slot.get("start", "00:00"))
    end = _parse_hhmm(slot.get("end", "00:00"))
    if start is None or end is None:
        return False

    current_dow = now.weekday()  # Mon=0..Sun=6
    current_t = now.time().replace(second=0, microsecond=0)

    if start <= end:
        # same-day slot
        return current_dow == dow and start <= current_t < end
    # overnight slot: active on `dow` from start..23:59 OR on `dow+1` from 00:00..end
    yesterday_dow = (current_dow - 1) % 7
    if current_dow == dow and current_t >= start:
        return True
    if yesterday_dow == dow and current_t < end:
        return True
    return False


async def get_on_call_user_ids(db, now: Optional[datetime] = None) -> List[str]:
    """Return list of user_ids on call at `now` (or now in configured tz).
    Returns [] when rotation is disabled or no slot matches -> caller falls back
    to the default behaviour (notify all admins+operators)."""
    cfg = await get_config(db)
    if not cfg.get("rotation_enabled"):
        return []

    tz_name = cfg.get("timezone") or "Europe/Rome"
    ref = now or _now_in_tz(tz_name)

    matched: List[str] = []
    for slot in cfg.get("slots", []):
        if _slot_matches(slot, ref):
            uid = slot.get("user_id")
            if uid and uid not in matched:
                matched.append(uid)
    return matched


async def get_current_on_call(db) -> Dict[str, Any]:
    """Return human-readable info for the UI banner."""
    cfg = await get_config(db)
    tz_name = cfg.get("timezone") or "Europe/Rome"
    ref = _now_in_tz(tz_name)

    active: List[Dict[str, Any]] = []
    for slot in cfg.get("slots", []):
        if _slot_matches(slot, ref):
            active.append(slot)

    return {
        "rotation_enabled": bool(cfg.get("rotation_enabled")),
        "timezone": tz_name,
        "now": ref.strftime("%Y-%m-%d %H:%M"),
        "active_slots": active,
    }
