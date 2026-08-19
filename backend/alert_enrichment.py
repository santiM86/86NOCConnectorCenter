"""
Arricchimento alert (Argus Center) — Fase 3.
Aggiunge ad ogni alert rilevante:
  - ORGANIZZAZIONE del cliente (clienti raggruppati in 1 organizzazione Nebula)
  - IMPATTO a valle: "uplink X giu' -> N device, M vitali impattati"
cosi' il tecnico/cliente capisce subito la gravita'.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("alert_enrichment")

# source_type per cui vale la pena calcolare l'impatto a valle (guasti "a monte")
_IMPACT_SOURCES = (
    "corr_site_power_down", "corr_site_isolated", "corr_switch_down",
    "corr_switch_unreachable", "corr_firewall_mgmt_down", "corr_isp_down",
    "site_blackout",
)


async def get_org_for_client(db, client_id: str) -> Optional[Dict[str, str]]:
    """Organizzazione (Nebula) a cui appartiene il cliente, se mappata."""
    if not client_id:
        return None
    try:
        link = await db.zyxel_client_links.find_one(
            {"client_id": client_id}, {"_id": 0, "org_id": 1, "org_name": 1})
        if link and link.get("org_id"):
            return {"org_id": link["org_id"], "org_name": link.get("org_name") or link["org_id"]}
    except Exception:  # noqa: BLE001
        pass
    return None


async def _entity_id_for(db, client_id: str, ip: str) -> Optional[str]:
    if not ip:
        return None
    doc = await db.cmdb_identity_keys.find_one(
        {"client_id": client_id, "key_type": "ip", "key_value": f"{client_id}:{ip}"},
        {"_id": 0, "entity_id": 1})
    return doc["entity_id"] if doc else None


async def enrich_alert(db, alert: Dict[str, Any]) -> Dict[str, Any]:
    """Aggiunge org + impatto all'alert (in-place) e ne arricchisce il messaggio."""
    cid = alert.get("client_id")
    # Organizzazione
    org = await get_org_for_client(db, cid)
    if org:
        alert["org_id"] = org["org_id"]
        alert["org_name"] = org["org_name"]

    st = alert.get("source_type") or ""
    if st not in _IMPACT_SOURCES:
        if org:
            alert["message"] = f"[Org: {org['org_name']}] " + (alert.get("message") or "")
        return alert

    # Impatto a valle
    try:
        import graph_builder as gb
        entity_id = await _entity_id_for(db, cid, alert.get("device_ip"))
        impact = await gb.compute_impact(db, entity_id) if entity_id else None
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich impact failed: %s", e)
        impact = None

    prefix = f"[Org: {org['org_name']}] " if org else ""
    if impact and impact.get("found") and impact.get("impacted_count", 0) > 0:
        n = impact["impacted_count"]
        v = impact["impacted_vital"]
        names = ", ".join(d["name"] for d in impact["impacted"][:6] if d.get("name"))
        more = f" e altri {n - 6}" if n > 6 else ""
        vital_txt = f", di cui {v} vitali" if v else ""
        alert["impact_count"] = n
        alert["impact_vital"] = v
        alert["message"] = (
            f"{prefix}{alert.get('message','')}\n\n🔗 IMPATTO: se cade, restano coinvolti "
            f"{n} dispositivi a valle{vital_txt} ({names}{more})."
        )
    elif prefix:
        alert["message"] = prefix + (alert.get("message") or "")
    return alert
