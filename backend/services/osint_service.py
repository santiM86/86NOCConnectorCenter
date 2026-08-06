"""
OSINT / Threat Intelligence service
===================================
Fonti Open Source Intelligence integrate in ARGUS per arricchire alert,
CMDB ed External Monitor. I FEED sono GLOBALI (condivisi tra tutti i tenant):
scaricati una sola volta e persistiti senza `client_id`. I MATCH/alert generati
restano invece legati al `client_id` del target (isolamento multi-tenant).

Provider (v1):
  - abuse.ch Feodo Tracker  -> IP botnet C2            (KEYLESS)
  - Spamhaus DROP           -> CIDR ostili high-conf   (KEYLESS)
  - FireHOL Level 1         -> CIDR aggregati          (KEYLESS)
  - CISA KEV                -> CVE attivamente sfruttate(KEYLESS)
  - Shodan InternetDB       -> porte/CVE IP pubblici    (KEYLESS)
  - abuse.ch ThreatFox      -> IOC malware/C2           (Auth-Key)
  - AbuseIPDB               -> reputazione IP           (API key)
  - GreyNoise Community     -> scanner/noise            (API key)
  - NVD                     -> dettagli CVE             (opzionale key)

Chiavi salvate cifrate (AES-256-GCM) in db.settings come `osint_<provider>_api_key`.
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from pymongo import UpdateOne

from database import db
from security import security_manager

logger = logging.getLogger("osint")

# Provider che richiedono una API key
KEYED_PROVIDERS = ("abusech", "abuseipdb", "greynoise", "nvd")
SETTINGS_PREFIX = "osint_"
SETTINGS_SUFFIX = "_api_key"

_TIMEOUT = httpx.Timeout(20.0, connect=6.0)
_UA = "ARGUS-NOC-OSINT/1.0"

# Cadenza di refresh (minuti) per ciascun feed globale
FEED_INTERVALS = {
    "feodo": 15,
    "threatfox": 60,
    "spamhaus_drop": 360,
    "firehol_level1": 360,
    "cisa_kev": 1440,
}

# TTL cache lookup per-IP (ore)
IP_CACHE_TTL_H = {"abuseipdb": 24, "greynoise": 168, "internetdb": 168}


# ==================== KEY MANAGEMENT ====================

def _settings_key(provider: str) -> str:
    return f"{SETTINGS_PREFIX}{provider}{SETTINGS_SUFFIX}"


async def set_api_key(provider: str, plaintext_key: str) -> None:
    if provider not in KEYED_PROVIDERS:
        raise ValueError(f"Provider non valido: {provider}")
    if not plaintext_key or len(plaintext_key.strip()) < 6:
        raise ValueError("API key non valida (min 6 caratteri)")
    encrypted = security_manager.encrypt_credential(plaintext_key.strip())
    await db.settings.update_one(
        {"key": _settings_key(provider)},
        {"$set": {
            "key": _settings_key(provider),
            "value": encrypted,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    logger.info(f"OSINT: API key '{provider}' aggiornata (cifrata)")


async def get_api_key(provider: str) -> Optional[str]:
    doc = await db.settings.find_one({"key": _settings_key(provider)}, {"_id": 0, "value": 1})
    if not doc or not doc.get("value"):
        return None
    try:
        return security_manager.decrypt_credential(doc["value"])
    except Exception as e:
        logger.error(f"OSINT: decrypt key '{provider}' fallito: {e}")
        return None


async def delete_api_key(provider: str) -> bool:
    res = await db.settings.delete_one({"key": _settings_key(provider)})
    return res.deleted_count > 0


async def keys_status() -> dict:
    out = {}
    for p in KEYED_PROVIDERS:
        doc = await db.settings.find_one({"key": _settings_key(p)}, {"_id": 0, "value": 1, "updated_at": 1})
        if doc and doc.get("value"):
            try:
                clear = security_manager.decrypt_credential(doc["value"])
                masked = "•" * max(0, len(clear) - 4) + clear[-4:] if clear else None
            except Exception:
                masked = "(decrypt error)"
            out[p] = {"configured": True, "masked_key": masked, "updated_at": doc.get("updated_at")}
        else:
            out[p] = {"configured": False, "masked_key": None, "updated_at": None}
    return out


# ==================== HTTP HELPERS ====================

async def _get_json(url: str, *, headers: dict | None = None, params: dict | None = None,
                    method: str = "GET", json: dict | None = None):
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = await c.request(method, url, headers=h, params=params, json=json)
        r.raise_for_status()
        return r.json()


async def _get_text_lines(url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=6.0), follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": _UA})
        r.raise_for_status()
        out = []
        for line in r.text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(";"):
                continue
            out.append(s.split(";")[0].strip())
        return out


def _is_public_ip(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (obj.is_private or obj.is_loopback or obj.is_reserved
                or obj.is_link_local or obj.is_multicast or obj.is_unspecified)


# ==================== FEED REFRESH (GLOBAL) ====================

async def _record_run(source: str, status: str, count: int = 0, error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.osint_feed_runs.update_one(
        {"source": source},
        {"$set": {
            "source": source, "status": status, "count": count,
            "error": error, "finished_at": now,
        }},
        upsert=True,
    )


async def _should_run(source: str, interval_min: int, force: bool) -> bool:
    if force:
        return True
    doc = await db.osint_feed_runs.find_one({"source": source}, {"_id": 0, "finished_at": 1, "status": 1})
    if not doc or not doc.get("finished_at"):
        return True
    try:
        last = datetime.fromisoformat(str(doc["finished_at"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last).total_seconds() / 60.0 >= interval_min
    except Exception:
        return True


async def _upsert_iocs(source: str, kind: str, indicators: list[str], meta: dict | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    ops = []
    seen = set()
    for ind in indicators:
        ind = (ind or "").strip()
        if not ind or ind in seen:
            continue
        seen.add(ind)
        setdoc = {"source": source, "indicator": ind, "kind": kind, "last_seen": now}
        if meta:
            setdoc.update(meta)
        ops.append(UpdateOne(
            {"source": source, "indicator": ind},
            {"$set": setdoc, "$setOnInsert": {"first_seen": now}},
            upsert=True,
        ))
    if ops:
        await db.threat_intel.bulk_write(ops, ordered=False)
    return len(seen)


async def refresh_feodo(force=False) -> Optional[int]:
    if not await _should_run("feodo", FEED_INTERVALS["feodo"], force):
        return None
    try:
        data = await _get_json("https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.json")
        ips = [row.get("ip_address") for row in data if isinstance(row, dict) and row.get("ip_address")]
        n = await _upsert_iocs("feodo", "ipv4", ips, {"threat": "botnet_c2"})
        await _record_run("feodo", "success", n)
        return n
    except Exception as e:
        await _record_run("feodo", "failed", 0, str(e)[:300])
        logger.warning(f"OSINT feodo refresh failed: {e}")
        return None


async def refresh_spamhaus_drop(force=False) -> Optional[int]:
    if not await _should_run("spamhaus_drop", FEED_INTERVALS["spamhaus_drop"], force):
        return None
    try:
        cidrs = await _get_text_lines("https://www.spamhaus.org/drop/drop.txt")
        valid = []
        for c in cidrs:
            try:
                ipaddress.ip_network(c, strict=False)
                valid.append(c)
            except ValueError:
                continue
        n = await _upsert_iocs("spamhaus_drop", "cidr", valid, {"threat": "hostile_net"})
        await _record_run("spamhaus_drop", "success", n)
        return n
    except Exception as e:
        await _record_run("spamhaus_drop", "failed", 0, str(e)[:300])
        logger.warning(f"OSINT spamhaus refresh failed: {e}")
        return None


async def refresh_firehol(force=False) -> Optional[int]:
    if not await _should_run("firehol_level1", FEED_INTERVALS["firehol_level1"], force):
        return None
    try:
        entries = await _get_text_lines("https://iplists.firehol.org/files/firehol_level1.netset")
        valid = []
        for c in entries:
            try:
                ipaddress.ip_network(c, strict=False)
                valid.append(c)
            except ValueError:
                continue
        n = await _upsert_iocs("firehol_level1", "cidr", valid, {"threat": "aggregate_blocklist"})
        await _record_run("firehol_level1", "success", n)
        return n
    except Exception as e:
        await _record_run("firehol_level1", "failed", 0, str(e)[:300])
        logger.warning(f"OSINT firehol refresh failed: {e}")
        return None


async def refresh_threatfox(force=False) -> Optional[int]:
    key = await get_api_key("abusech")
    if not key:
        return None  # richiede Auth-Key: skip finché non configurata
    if not await _should_run("threatfox", FEED_INTERVALS["threatfox"], force):
        return None
    try:
        data = await _get_json(
            "https://threatfox-api.abuse.ch/api/v1/",
            method="POST", headers={"Auth-Key": key},
            json={"query": "get_iocs", "days": 1},
        )
        rows = data.get("data") or [] if isinstance(data, dict) else []
        ip_iocs = []
        for row in rows:
            ioc = row.get("ioc", "")
            itype = row.get("ioc_type", "")
            if itype in ("ip:port", "ip") and ioc:
                ip_iocs.append(ioc.split(":")[0])
        n = await _upsert_iocs("threatfox", "ipv4", ip_iocs, {"threat": "malware_c2"})
        await _record_run("threatfox", "success", n)
        return n
    except Exception as e:
        await _record_run("threatfox", "failed", 0, str(e)[:300])
        logger.warning(f"OSINT threatfox refresh failed: {e}")
        return None


async def refresh_cisa_kev(force=False) -> Optional[int]:
    if not await _should_run("cisa_kev", FEED_INTERVALS["cisa_kev"], force):
        return None
    try:
        data = await _get_json(
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
        )
        vulns = data.get("vulnerabilities") or [] if isinstance(data, dict) else []
        now = datetime.now(timezone.utc).isoformat()
        ops = []
        for v in vulns:
            cve = v.get("cveID")
            if not cve:
                continue
            ops.append(UpdateOne(
                {"cve_id": cve},
                {"$set": {
                    "cve_id": cve,
                    "vendor": v.get("vendorProject"),
                    "product": v.get("product"),
                    "name": v.get("vulnerabilityName"),
                    "date_added": v.get("dateAdded"),
                    "due_date": v.get("dueDate"),
                    "ransomware": v.get("knownRansomwareCampaignUse"),
                    "notes": v.get("notes"),
                    "updated_at": now,
                }},
                upsert=True,
            ))
        if ops:
            await db.cisa_kev.bulk_write(ops, ordered=False)
        await _record_run("cisa_kev", "success", len(ops))
        return len(ops)
    except Exception as e:
        await _record_run("cisa_kev", "failed", 0, str(e)[:300])
        logger.warning(f"OSINT cisa_kev refresh failed: {e}")
        return None


async def refresh_all_feeds(force=False) -> dict:
    return {
        "feodo": await refresh_feodo(force),
        "spamhaus_drop": await refresh_spamhaus_drop(force),
        "firehol_level1": await refresh_firehol(force),
        "threatfox": await refresh_threatfox(force),
        "cisa_kev": await refresh_cisa_kev(force),
    }


# ==================== LOOKUP (on-demand, per IP) ====================

async def _cache_get(ip: str, provider: str):
    doc = await db.osint_ip_cache.find_one({"ip": ip, "provider": provider}, {"_id": 0})
    if not doc:
        return None
    exp = doc.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return None
        except Exception:
            return None
    return doc.get("data")


async def _cache_set(ip: str, provider: str, data) -> None:
    ttl_h = IP_CACHE_TTL_H.get(provider, 24)
    now = datetime.now(timezone.utc)
    await db.osint_ip_cache.update_one(
        {"ip": ip, "provider": provider},
        {"$set": {
            "ip": ip, "provider": provider, "data": data,
            "cached_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=ttl_h)).isoformat(),
        }},
        upsert=True,
    )


async def _local_ioc_match(ip: str) -> list[dict]:
    """Match dell'IP contro IOC esatti + CIDR presenti in threat_intel."""
    matches = []
    async for d in db.threat_intel.find({"indicator": ip}, {"_id": 0}):
        matches.append({"source": d["source"], "indicator": d["indicator"],
                        "kind": d.get("kind"), "threat": d.get("threat")})
    # CIDR match (set piccolo: solo spamhaus/firehol)
    try:
        ip_obj = ipaddress.ip_address(ip)
        async for d in db.threat_intel.find({"kind": "cidr"}, {"_id": 0, "indicator": 1, "source": 1, "threat": 1}):
            try:
                if ip_obj in ipaddress.ip_network(d["indicator"], strict=False):
                    matches.append({"source": d["source"], "indicator": d["indicator"],
                                    "kind": "cidr", "threat": d.get("threat")})
            except ValueError:
                continue
    except ValueError:
        pass
    return matches


async def _abuseipdb(ip: str):
    key = await get_api_key("abuseipdb")
    if not key:
        return None
    cached = await _cache_get(ip, "abuseipdb")
    if cached is not None:
        return cached
    try:
        data = await _get_json(
            "https://api.abuseipdb.com/api/v2/check",
            headers={"Key": key, "Accept": "application/json"},
            params={"ipAddress": ip, "maxAgeInDays": 90},
        )
        d = data.get("data", {}) if isinstance(data, dict) else {}
        res = {
            "abuse_confidence": d.get("abuseConfidenceScore"),
            "total_reports": d.get("totalReports"),
            "country": d.get("countryCode"),
            "isp": d.get("isp"),
            "domain": d.get("domain"),
            "usage_type": d.get("usageType"),
        }
        await _cache_set(ip, "abuseipdb", res)
        return res
    except Exception as e:
        logger.warning(f"OSINT abuseipdb {ip}: {e}")
        return {"error": str(e)[:120]}


async def _greynoise(ip: str):
    key = await get_api_key("greynoise")
    if not key:
        return None
    cached = await _cache_get(ip, "greynoise")
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"https://api.greynoise.io/v3/community/{ip}",
                            headers={"key": key, "User-Agent": _UA})
        if r.status_code == 404:
            res = {"noise": False, "riot": False, "classification": "unknown"}
            await _cache_set(ip, "greynoise", res)
            return res
        r.raise_for_status()
        d = r.json()
        res = {
            "noise": d.get("noise"), "riot": d.get("riot"),
            "classification": d.get("classification"), "name": d.get("name"),
            "last_seen": d.get("last_seen"),
        }
        await _cache_set(ip, "greynoise", res)
        return res
    except Exception as e:
        logger.warning(f"OSINT greynoise {ip}: {e}")
        return {"error": str(e)[:120]}


async def _internetdb(ip: str):
    cached = await _cache_get(ip, "internetdb")
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(f"https://internetdb.shodan.io/{ip}", headers={"User-Agent": _UA})
        if r.status_code == 404:
            res = {"ports": [], "vulns": [], "hostnames": [], "tags": []}
            await _cache_set(ip, "internetdb", res)
            return res
        r.raise_for_status()
        d = r.json()
        res = {
            "ports": d.get("ports", []), "vulns": d.get("vulns", []),
            "hostnames": d.get("hostnames", []), "tags": d.get("tags", []),
            "cpes": d.get("cpes", []),
        }
        await _cache_set(ip, "internetdb", res)
        return res
    except Exception as e:
        logger.warning(f"OSINT internetdb {ip}: {e}")
        return {"error": str(e)[:120]}


async def lookup_ip(ip: str) -> dict:
    """Arricchimento on-demand di un IP pubblico con tutte le fonti disponibili."""
    if not _is_public_ip(ip):
        raise ValueError("IP non valido o privato/riservato (solo IP pubblici)")
    local = await _local_ioc_match(ip)
    result = {
        "ip": ip,
        "local_matches": local,
        "malicious": len(local) > 0,
        "abuseipdb": await _abuseipdb(ip),
        "greynoise": await _greynoise(ip),
        "internetdb": await _internetdb(ip),
    }
    # KEV cross-ref sulle vulns InternetDB
    idb = result["internetdb"] or {}
    kev_hits = await _kev_hits(idb.get("vulns", []) if isinstance(idb, dict) else [])
    result["kev_hits"] = kev_hits
    return result


async def _kev_hits(cve_ids: list[str]) -> list[dict]:
    if not cve_ids:
        return []
    hits = []
    async for d in db.cisa_kev.find({"cve_id": {"$in": list(cve_ids)}}, {"_id": 0}):
        hits.append(d)
    return hits


# ==================== C2 CORRELATION (syslog/firewall IP -> IOC) ====================

import re as _re

_IPV4_RE = _re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")

# Cache in-memory delle reti CIDR ostili (refresh periodico) per match veloce.
_CIDR_CACHE: dict = {"nets": [], "at": None}
_CIDR_TTL_S = 300


def extract_ips(text: str) -> list[str]:
    """Estrae IPv4 validi e PUBBLICI da un testo (es. riga di log firewall)."""
    out = []
    seen = set()
    for m in _IPV4_RE.findall(text or ""):
        if m in seen:
            continue
        seen.add(m)
        try:
            octets = m.split(".")
            if all(0 <= int(o) <= 255 for o in octets) and _is_public_ip(m):
                out.append(m)
        except ValueError:
            continue
    return out


async def _get_cidr_nets() -> list[tuple]:
    """Ritorna [(network, source, threat)] delle CIDR ostili, con cache TTL."""
    now = datetime.now(timezone.utc)
    if _CIDR_CACHE["at"] and (now - _CIDR_CACHE["at"]).total_seconds() < _CIDR_TTL_S:
        return _CIDR_CACHE["nets"]
    nets = []
    async for d in db.threat_intel.find({"kind": "cidr"}, {"_id": 0, "indicator": 1, "source": 1, "threat": 1}):
        try:
            nets.append((ipaddress.ip_network(d["indicator"], strict=False), d["source"], d.get("threat")))
        except ValueError:
            continue
    _CIDR_CACHE["nets"] = nets
    _CIDR_CACHE["at"] = now
    return nets


async def match_ips_against_iocs(ips: list[str]) -> dict[str, list[dict]]:
    """Match di una lista di IP contro gli IOC (indicatori esatti + CIDR).
    Ritorna {ip: [ {source, indicator, threat, kind}, ... ]} solo per gli IP con match."""
    result: dict[str, list[dict]] = {}
    uniq = [ip for ip in set(ips) if _is_public_ip(ip)]
    if not uniq:
        return result
    # 1) match esatto (indexed)
    async for d in db.threat_intel.find(
        {"indicator": {"$in": uniq}, "kind": {"$ne": "cidr"}}, {"_id": 0}
    ):
        result.setdefault(d["indicator"], []).append(
            {"source": d["source"], "indicator": d["indicator"],
             "threat": d.get("threat"), "kind": d.get("kind")})
    # 2) match CIDR
    nets = await _get_cidr_nets()
    if nets:
        for ip in uniq:
            try:
                ip_obj = ipaddress.ip_address(ip)
            except ValueError:
                continue
            for net, source, threat in nets:
                if ip_obj in net:
                    result.setdefault(ip, []).append(
                        {"source": source, "indicator": str(net), "threat": threat, "kind": "cidr"})
    return result


# ==================== STATUS ====================

async def get_status() -> dict:
    runs = {}
    async for d in db.osint_feed_runs.find({}, {"_id": 0}):
        runs[d["source"]] = d
    ioc_total = await db.threat_intel.count_documents({})
    kev_total = await db.cisa_kev.count_documents({})
    exposure_total = await db.osint_exposure.count_documents({})
    exposure_kev = await db.osint_exposure.count_documents({"kev_count": {"$gt": 0}})
    return {
        "feeds": runs,
        "ioc_total": ioc_total,
        "kev_total": kev_total,
        "exposure_total": exposure_total,
        "exposure_with_kev": exposure_kev,
        "keys": await keys_status(),
    }
