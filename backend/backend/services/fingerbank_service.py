"""
Fingerbank API integration (https://api.fingerbank.org/)

Identifica device sconosciuti combinando MAC address con DHCP fingerprint /
user-agents. Ritorna `device_name` (string) e `score` (0-100, confidence).

API key salvata cifrata (AES-256-GCM) in `db.settings.fingerbank_api_key`.
Risultati cacheati in `db.fingerbank_cache` (TTL 30gg per non riconsumare quota
gratuita 250 query/giorno).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from database import db
from security import security_manager

logger = logging.getLogger(__name__)

FINGERBANK_API_BASE = "https://api.fingerbank.org/api/v2"
SETTINGS_KEY = "fingerbank_api_key"
CACHE_TTL_DAYS = 30


# ==================== KEY MANAGEMENT ====================

async def set_api_key(plaintext_key: str) -> None:
    """Cifra e salva la API key Fingerbank in db.settings."""
    if not plaintext_key or not isinstance(plaintext_key, str):
        raise ValueError("API key non valida")
    encrypted = security_manager.encrypt_credential(plaintext_key.strip())
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {
            "key": SETTINGS_KEY,
            "value": encrypted,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    logger.info("Fingerbank API key updated (encrypted, AES-256-GCM)")


async def get_api_key() -> Optional[str]:
    """Ritorna la API key in chiaro (decifrata) o None se non configurata."""
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    if not doc or not doc.get("value"):
        return None
    try:
        return security_manager.decrypt_credential(doc["value"])
    except Exception as e:
        logger.error(f"Fingerbank key decrypt failed: {e}")
        return None


async def is_configured() -> bool:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    return bool(doc and doc.get("value"))


async def get_status() -> dict:
    """Ritorna stato configurazione (senza esporre la key in chiaro)."""
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1, "updated_at": 1})
    if not doc or not doc.get("value"):
        return {"configured": False, "updated_at": None, "masked_key": None}
    # Mostra solo gli ultimi 4 char della key (masked) per conferma visiva
    try:
        clear = security_manager.decrypt_credential(doc["value"])
        masked = "•" * max(0, len(clear) - 4) + clear[-4:] if clear else None
    except Exception:
        masked = "(decrypt error)"
    return {
        "configured": True,
        "updated_at": doc.get("updated_at"),
        "masked_key": masked,
    }


async def delete_api_key() -> bool:
    res = await db.settings.delete_one({"key": SETTINGS_KEY})
    return res.deleted_count > 0


# ==================== INTERROGATE API ====================

async def interrogate(
    mac: str,
    dhcp_fingerprint: Optional[str] = None,
    dhcp_vendor: Optional[str] = None,
    user_agents: Optional[list[str]] = None,
) -> Optional[dict]:
    """Chiama Fingerbank /combinations/interrogate.

    Ritorna dict con:
      - device_name: string (es. "HP LaserJet")
      - device_id: int
      - score: 0-100 confidence
      - source: "fingerbank"
    Oppure None se: API key non configurata, no match (404), errore.

    Risultati cacheati per 30gg in db.fingerbank_cache su chiave (mac normalizzato).
    """
    if not mac:
        return None
    norm_mac = _normalize_mac(mac)
    if not norm_mac:
        return None

    # 1) cache hit
    cached = await _cache_get(norm_mac)
    if cached is not None:
        return cached  # puo' essere {} (negative cache) -> ritorno None
    # 2) API call
    api_key = await get_api_key()
    if not api_key:
        return None
    payload = {"mac": norm_mac}
    if dhcp_fingerprint:
        payload["dhcp_fingerprint"] = dhcp_fingerprint
    if dhcp_vendor:
        payload["dhcp_vendor"] = dhcp_vendor
    if user_agents:
        payload["user_agents"] = user_agents
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ARGUS-NOC/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.request(
                "GET",
                f"{FINGERBANK_API_BASE}/combinations/interrogate",
                json=payload,
                headers=headers,
            )
        if r.status_code == 404:
            await _cache_set(norm_mac, None)  # negative cache
            return None
        if r.status_code == 401:
            logger.warning("Fingerbank: API key invalida o revocata")
            return None
        if r.status_code == 429:
            logger.warning("Fingerbank: rate limit raggiunto (250 query/giorno gratuito)")
            return None
        r.raise_for_status()
        data = r.json() or {}
        result = {
            "device_name": data.get("device_name") or data.get("device", {}).get("name"),
            "device_id": data.get("device_id") or data.get("device", {}).get("id"),
            "score": data.get("score"),
            "source": "fingerbank",
        }
        if not result["device_name"]:
            await _cache_set(norm_mac, None)
            return None
        await _cache_set(norm_mac, result)
        return result
    except Exception as e:
        logger.warning(f"Fingerbank interrogate failed for {norm_mac}: {e}")
        return None


# ==================== UTILS ====================

def _normalize_mac(mac: str) -> str:
    if not mac:
        return ""
    cleaned = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(cleaned) != 12:
        return ""
    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


async def _cache_get(mac: str):
    doc = await db.fingerbank_cache.find_one({"mac": mac}, {"_id": 0})
    if not doc:
        return None
    cached_at = doc.get("cached_at")
    if cached_at:
        try:
            ts = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - ts > timedelta(days=CACHE_TTL_DAYS):
                return None  # expired
        except Exception:
            pass
    # negative cache (no match) -> doc with result=None
    if doc.get("result") is None:
        return None
    return doc["result"]


async def _cache_set(mac: str, result: Optional[dict]) -> None:
    await db.fingerbank_cache.update_one(
        {"mac": mac},
        {"$set": {
            "mac": mac,
            "result": result,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
