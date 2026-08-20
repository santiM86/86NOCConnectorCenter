"""
Correlazione OUTAGE ISP esterni — "il guasto è diffuso o è solo la tua sede?".

Quando il Blame Engine attribuisce la colpa a un ISP/carrier, questo modulo
interroga fonti pubbliche per capire se il guasto è DIFFUSO (outage del carrier
a livello ASN/nazionale) oppure ISOLATO (solo la linea/sede del cliente).

Fonti programmatiche (gratuite):
- IODA (Georgia Tech) — /v2/outages/alerts per ASN e per Paese. Nessuna chiave.
- RIPEstat — as-overview: l'ASN sta ancora annunciando rotte BGP? Nessuna chiave.
- Cloudflare Radar — /radar/annotations/outages (OPZIONALE, richiede token free
  in env CLOUDFLARE_RADAR_TOKEN).

Fonti crowdsourced (Downdetector/OutageReport) NON hanno API pubblica affidabile
→ vengono fornite come LINK cliccabili pre-compilati per l'operatore rilevato.
"""
import os
import re
import time
import logging
from typing import Optional

logger = logging.getLogger("isp_outage")

IODA_BASE = "https://api.ioda.inetintel.cc.gatech.edu/v2"
RIPESTAT_BASE = "https://stat.ripe.net/data"
CF_BASE = "https://api.cloudflare.com/client/v4/radar/annotations/outages"

# Mappa keyword operatore → slug Downdetector.it (crowdsourced, no API)
_DD_SLUGS = {
    "telecom italia": "tim", "tim": "tim", "ibsnaz": "tim",
    "vodafone": "vodafone", "fastweb": "fastweb",
    "wind": "windtre", "windtre": "windtre", "wind tre": "windtre",
    "iliad": "iliad", "sky": "sky-wifi", "open fiber": "open-fiber",
    "openfiber": "open-fiber", "tiscali": "tiscali", "eolo": "eolo",
    "linkem": "linkem", "aruba": "aruba", "irideos": "irideos",
}


def _asn_num(asn) -> Optional[int]:
    if asn is None:
        return None
    m = re.search(r"(\d+)", str(asn))
    return int(m.group(1)) if m else None


def _external_links(isp_name: Optional[str], country_code: Optional[str], asn: Optional[int]) -> list:
    links = []
    name = (isp_name or "").lower()
    slug = next((s for kw, s in _DD_SLUGS.items() if kw in name), None)
    if slug:
        links.append({"name": f"Downdetector — {isp_name}", "url": f"https://downdetector.it/stato/{slug}/"})
    else:
        q = (isp_name or "").replace(" ", "+")
        links.append({"name": "Downdetector Italia", "url": f"https://downdetector.it/cerca/?q={q}" if q else "https://downdetector.it/"})
    if asn:
        links.append({"name": "IODA (BGP/active probing)", "url": f"https://ioda.inetintel.cc.gatech.edu/asn/{asn}"})
    if (country_code or "").upper() == "IT":
        links.append({"name": "Open Fiber — Stato Rete", "url": "https://openfiber.it/stato-rete/"})
    links.append({"name": "OutageReport", "url": "https://outagereport.com/"})
    return links


async def _ioda_alerts(session, entity_type: str, entity_code: str, hours: int = 2) -> list:
    now = int(time.time())
    url = (f"{IODA_BASE}/outages/alerts?from={now - hours * 3600}&until={now}"
           f"&entityType={entity_type}&entityCode={entity_code}")
    try:
        async with session.get(url) as r:
            j = await r.json(content_type=None)
            return j.get("data") or []
    except Exception as e:  # noqa: BLE001
        logger.debug("IODA alerts %s/%s failed: %s", entity_type, entity_code, e)
        return []


async def _ripe_announced(session, asn: int) -> Optional[bool]:
    url = f"{RIPESTAT_BASE}/as-overview/data.json?resource=AS{asn}"
    try:
        async with session.get(url) as r:
            j = await r.json(content_type=None)
            return bool(j.get("data", {}).get("announced"))
    except Exception as e:  # noqa: BLE001
        logger.debug("RIPEstat as-overview AS%s failed: %s", asn, e)
        return None


async def _get_cf_token() -> Optional[str]:
    """Token Cloudflare Radar: prima da DB (cifrato), poi da env."""
    try:
        from database import db
        from security import security_manager
        doc = await db.settings.find_one({"key": "cloudflare_radar_token"}, {"_id": 0, "value": 1})
        if doc and doc.get("value"):
            try:
                return security_manager.decrypt_credential(doc["value"])
            except Exception as e:  # noqa: BLE001
                logger.debug("cloudflare token decrypt failed: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.debug("cloudflare token DB lookup failed: %s", e)
    return os.environ.get("CLOUDFLARE_RADAR_TOKEN")


async def _cf_outages(session, asn: Optional[int], country_code: Optional[str]) -> list:
    token = await _get_cf_token()
    if not token:
        return []
    params = "dateRange=1d&limit=20"
    if asn:
        params += f"&asn={asn}"
    if country_code:
        params += f"&location={country_code.upper()}"
    try:
        async with session.get(f"{CF_BASE}?{params}",
                               headers={"Authorization": f"Bearer {token}"}) as r:
            j = await r.json(content_type=None)
            return (j.get("result") or {}).get("annotations") or []
    except Exception as e:  # noqa: BLE001
        logger.debug("Cloudflare Radar outages failed: %s", e)
        return []


async def check_isp_outage(asn=None, isp_name: Optional[str] = None,
                           country_code: Optional[str] = None) -> dict:
    """Ritorna un verdetto di correlazione outage esterno.

    {widespread: bool, national: bool, bgp_withdrawn: bool, asn, isp_name,
     country, signals: [str], summary: str, sources: [str], external_links: [..]}"""
    import aiohttp
    asn_n = _asn_num(asn)
    signals, sources = [], []
    widespread = national = bgp_withdrawn = False

    timeout = aiohttp.ClientTimeout(total=9)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            import asyncio
            tasks = {}
            if asn_n:
                tasks["ioda_asn"] = _ioda_alerts(s, "asn", str(asn_n))
                tasks["ripe"] = _ripe_announced(s, asn_n)
            if country_code:
                tasks["ioda_country"] = _ioda_alerts(s, "country", country_code.upper())
            tasks["cf"] = _cf_outages(s, asn_n, country_code)
            keys = list(tasks.keys())
            res = await asyncio.gather(*tasks.values(), return_exceptions=True)
            out = {k: (v if not isinstance(v, Exception) else None) for k, v in zip(keys, res)}
    except Exception as e:  # noqa: BLE001
        logger.debug("check_isp_outage session failed: %s", e)
        out = {}

    if out.get("ioda_asn"):
        widespread = True
        signals.append(f"IODA: rilevato outage attivo sull'operatore AS{asn_n} ({len(out['ioda_asn'])} evento/i)")
        sources.append("IODA")
    if out.get("ioda_country"):
        national = True
        signals.append(f"IODA: outage rilevato a livello nazionale ({country_code}) — {len(out['ioda_country'])} evento/i")
        sources.append("IODA")
    ripe = out.get("ripe")
    if ripe is False:
        bgp_withdrawn = widespread = True
        signals.append(f"RIPEstat: AS{asn_n} NON annuncia più rotte BGP → operatore offline a livello globale")
        sources.append("RIPEstat")
    elif ripe is True:
        signals.append(f"RIPEstat: AS{asn_n} annuncia regolarmente le rotte BGP (nessun crollo di routing)")
        sources.append("RIPEstat")
    if out.get("cf"):
        widespread = True
        signals.append(f"Cloudflare Radar: {len(out['cf'])} outage annotato nell'ultima 24h")
        sources.append("Cloudflare Radar")

    if widespread or national:
        summary = ("🌐 GUASTO DIFFUSO CONFERMATO: l'interruzione è rilevata anche da fonti pubbliche "
                   "esterne → NON è un problema della singola sede, ma un outage dell'operatore"
                   + (" a livello nazionale." if national else "."))
    elif ripe is True and asn_n:
        summary = ("✅ Nessun outage diffuso rilevato dalle fonti esterne (IODA/RIPEstat): l'operatore è "
                   "operativo altrove → il guasto è probabilmente ISOLATO alla linea/sede del cliente.")
    else:
        summary = "Correlazione outage esterno non conclusiva (dati insufficienti sull'operatore)."

    return {
        "widespread": widespread, "national": national, "bgp_withdrawn": bgp_withdrawn,
        "asn": f"AS{asn_n}" if asn_n else None, "isp_name": isp_name, "country": country_code,
        "signals": signals, "summary": summary,
        "sources": sorted(set(sources)),
        "external_links": _external_links(isp_name, country_code, asn_n),
        "checked_at": int(time.time()),
    }
