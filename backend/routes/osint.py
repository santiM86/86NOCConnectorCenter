"""OSINT / Threat Intelligence API routes."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from services import osint_service as osint

logger = logging.getLogger("osint.routes")

router = APIRouter(prefix="/api/osint", tags=["osint"])


class KeyRequest(BaseModel):
    api_key: str = Field(..., min_length=6, max_length=512)


@router.get("/status")
async def status(current_user: dict = Depends(get_current_user)):
    """Stato generale: feed, conteggi IOC/KEV/exposure, chiavi configurate.
    Sola lettura: accessibile a qualsiasi utente autenticato (admin/operator/viewer)."""
    return await osint.get_status()


@router.put("/keys/{provider}")
async def set_key(provider: str, payload: KeyRequest, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        await osint.set_api_key(provider, payload.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "keys": await osint.keys_status()}


@router.delete("/keys/{provider}")
async def delete_key(provider: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if provider not in osint.KEYED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider non valido")
    deleted = await osint.delete_api_key(provider)
    return {"ok": True, "deleted": deleted}


@router.post("/refresh")
async def refresh(current_user: dict = Depends(get_current_user)):
    """Forza il refresh immediato di tutti i feed globali."""
    require_admin(current_user)
    res = await osint.refresh_all_feeds(force=True)
    return {"ok": True, "results": res, "status": await osint.get_status()}


@router.get("/lookup/{ip}")
async def lookup(ip: str, current_user: dict = Depends(get_current_user)):
    """Arricchimento on-demand di un IP pubblico (IOC locali + AbuseIPDB + GreyNoise + InternetDB + KEV)."""
    try:
        return await osint.lookup_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/kev")
async def list_kev(
    q: Optional[str] = None, limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """Catalogo CISA KEV (CVE attivamente sfruttate), ricercabile."""
    query: dict = {}
    if q:
        query["$or"] = [
            {"cve_id": {"$regex": q, "$options": "i"}},
            {"vendor": {"$regex": q, "$options": "i"}},
            {"product": {"$regex": q, "$options": "i"}},
            {"name": {"$regex": q, "$options": "i"}},
            {"short_description": {"$regex": q, "$options": "i"}},
        ]
    items = await db.cisa_kev.find(query, {"_id": 0}).sort("date_added", -1).to_list(min(limit, 500))
    return {"total": len(items), "items": items}


_KEV_STOPWORDS = {
    "server", "system", "systems", "software", "router", "switch", "firewall",
    "series", "enterprise", "technologies", "technology", "networks", "network",
    "inc", "ltd", "corporation", "corp", "the", "and", "for", "products", "product",
    "manager", "service", "services", "cloud", "edition", "appliance", "gateway",
    "controller", "client", "agent", "core", "data", "access", "web", "management",
}


def _kev_norm(s):
    import re
    return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())


def _kev_tokens(s, min_len=4):
    return {t for t in _kev_norm(s).split() if len(t) >= min_len and t not in _KEV_STOPWORDS}


def _kev_categories(product_norm):
    """Categoria dispositivo per prodotti KEV 'generici' (es. 'Multiple Firewalls')."""
    cats = set()
    if "firewall" in product_norm:
        cats.add("firewall")
    if "router" in product_norm:
        cats.add("router")
    if "switch" in product_norm:
        cats.add("switch")
    if "gateway" in product_norm:
        cats.add("gateway")
    return cats


def _asset_category(device_type, model, vendor):
    blob = _kev_norm(f"{device_type} {model} {vendor}")
    if "firewall" in blob or any(w in blob for w in ("usg", "atp", "zywall", "flex", "fortigate", "palo", "sonicwall")):
        return "firewall"
    if "router" in blob:
        return "router"
    if "switch" in blob:
        return "switch"
    return None


async def _compute_kev_asset_exposure(client_id: Optional[str] = None):
    """Incrocia il catalogo CISA KEV con i vendor/modelli reali degli asset
    (firewall Zyxel Nebula + dispositivi gestiti/SNMP) per evidenziare quali
    clienti possiedono prodotti colpiti da una vulnerabilità attivamente sfruttata.
    Match conservativo: richiede corrispondenza sia sul vendor sia su un token
    significativo del prodotto."""
    # 1) KEV in memoria, indicizzato per token vendor
    kev = await db.cisa_kev.find(
        {}, {"_id": 0, "cve_id": 1, "vendor": 1, "product": 1, "name": 1,
             "short_description": 1, "required_action": 1, "due_date": 1, "ransomware": 1},
    ).to_list(3000)
    kev_by_vendor: dict = {}
    for k in kev:
        k["_ptoks"] = _kev_tokens(f"{k.get('product')} {k.get('name')}")
        k["_cats"] = _kev_categories(_kev_norm(k.get("product")))
        for vt in _kev_tokens(k.get("vendor"), min_len=3):
            kev_by_vendor.setdefault(vt, []).append(k)

    # 2) Asset con modello reale: Zyxel Nebula + managed_devices
    assets = []
    zq = {"device_type": "firewall"}
    mq = {"$or": [{"model": {"$nin": [None, ""]}}, {"vendor": {"$nin": [None, ""]}}]}
    if client_id:
        zq["client_id"] = client_id
        mq = {"$and": [mq, {"client_id": client_id}]}
    async for z in db.zyxel_devices.find(zq, {"_id": 0, "client_id": 1, "name": 1, "model": 1, "device_type": 1}):
        assets.append({"client_id": z.get("client_id"), "name": z.get("name") or z.get("model"),
                       "vendor": "Zyxel", "model": z.get("model"), "device_type": z.get("device_type"), "source": "nebula"})
    async for m in db.managed_devices.find(mq, {"_id": 0, "client_id": 1, "name": 1, "vendor": 1, "model": 1, "device_type": 1}):
        assets.append({"client_id": m.get("client_id"), "name": m.get("name"),
                       "vendor": m.get("vendor"), "model": m.get("model"), "device_type": m.get("device_type"), "source": "managed"})

    # 3) Matching conservativo
    results = []
    for a in assets:
        vend_str = _kev_norm(f"{a.get('vendor')} {a.get('model')} {a.get('name')}")
        prod_str = _kev_norm(f"{a.get('model')} {a.get('name')}")
        prod_tokens = set(prod_str.split())
        vend_tokens = set(vend_str.split())
        asset_cat = _asset_category(a.get("device_type"), a.get("model"), a.get("vendor"))
        seen = {}
        for vt, klist in kev_by_vendor.items():
            if vt not in vend_tokens:
                continue
            for k in klist:
                specific = bool(k["_ptoks"] & prod_tokens)
                broad = bool(asset_cat and asset_cat in k["_cats"])
                if not (specific or broad):
                    continue
                seen[k["cve_id"]] = {
                    "cve_id": k["cve_id"], "product": k.get("product"),
                    "name": k.get("name"), "short_description": k.get("short_description"),
                    "required_action": k.get("required_action"), "due_date": k.get("due_date"),
                    "ransomware": k.get("ransomware"),
                    "match_type": "specific" if specific else "vendor_category",
                }
        if seen:
            cves = list(seen.values())
            cves.sort(key=lambda c: c.get("due_date") or "9999")
            results.append({**{kk: a[kk] for kk in ("client_id", "name", "vendor", "model", "device_type", "source")},
                            "matches": cves, "match_count": len(cves)})

    # 4) Nome cliente
    cids = list({r["client_id"] for r in results if r.get("client_id")})
    clients = await db.clients.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for r in results:
        r["client_name"] = cmap.get(r.get("client_id"), r.get("client_id"))
    results.sort(key=lambda r: r["match_count"], reverse=True)
    return {"total": len(results), "assets_scanned": len(assets), "items": results}


@router.get("/kev/asset-exposure")
async def kev_asset_exposure(client_id: Optional[str] = None,
                             current_user: dict = Depends(get_current_user)):
    return await _compute_kev_asset_exposure(client_id)


@router.get("/exposure")
async def exposure(
    client_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Findings di esposizione (Shodan InternetDB) sugli IP pubblici monitorati.
    Filtrabile per cliente (isolamento multi-tenant)."""
    query: dict = {}
    if client_id:
        query["client_id"] = client_id
    items = await db.osint_exposure.find(query, {"_id": 0}).sort("kev_count", -1).to_list(1000)
    client_ids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}


@router.post("/c2-scan")
async def c2_scan(current_user: dict = Depends(get_current_user)):
    """Esegue subito la correlazione C2 sui syslog recenti (trigger manuale, admin)."""
    require_admin(current_user)
    from services.osint_poller import osint_c2_tick
    summary = await osint_c2_tick()
    return {"ok": True, "summary": summary}


@router.get("/c2-matches")
async def c2_matches(
    client_id: Optional[str] = None,
    status_filter: Optional[str] = "active",
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """Alert di comunicazione con IP malevoli noti (source_type=osint_c2)."""
    query: dict = {"source_type": "osint_c2"}
    if client_id:
        query["client_id"] = client_id
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    items = await db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 500))
    client_ids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}
