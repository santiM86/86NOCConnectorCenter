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


async def _backbone_diagnosis(db, client_id: Optional[str], switch_ip: Optional[str]) -> Optional[str]:
    """v2026-06: quando uno switch va giu', verifica SUBITO la DORSALE (uplink
    verso il parent): controlla la porta sul parent che affaccia verso questo
    switch. Se e' LINK DOWN o passa traffico ZERO → probabile problema di
    dorsale (cavo/SFP), non solo lo switch spento."""
    if not client_id or not switch_ip:
        return None
    try:
        from routes.topology_diagram import compute_switch_cascade
        casc = await compute_switch_cascade(client_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("backbone diag cascade failed: %s", e)
        return None
    node = next((c for c in casc.get("cascade", []) if c.get("ip") == switch_ip), None)
    if not node or not node.get("uplink"):
        return None
    up = node["uplink"]
    parent_ip = up.get("to_ip")
    parent_name = up.get("to_name") or parent_ip
    remote_port = up.get("remote_port")  # porta sul parent verso questo switch
    if not parent_ip or not remote_port:
        return None
    ports = await db.switch_ports.find(
        {"client_id": client_id, "local_ip": parent_ip}, {"_id": 0}).to_list(2000)
    rp = str(remote_port).strip().lower()
    port = next((p for p in ports
                 if str(p.get("name") or "").strip().lower() == rp
                 or str(p.get("alias") or "").strip().lower() == rp), None)
    if not port:
        return None
    oper = port.get("oper")
    traffic_known = ("rx_bps" in port) or ("tx_bps" in port)
    rx = int(port.get("rx_bps") or 0)
    tx = int(port.get("tx_bps") or 0)
    if oper != 1:
        return (f"🔌 DORSALE: la porta {remote_port} su {parent_name} (verso questo switch) "
                f"è LINK DOWN → probabile problema di DORSALE (cavo/SFP/uplink), non solo lo switch spento.")
    if traffic_known and (rx + tx) == 0:
        return (f"🔌 DORSALE: la porta {remote_port} su {parent_name} è UP ma con traffico a ZERO "
                f"→ verificare la DORSALE/uplink (possibile guasto backbone).")
    if traffic_known:
        return (f"🔌 DORSALE: la porta {remote_port} su {parent_name} è attiva e passa traffico "
                f"→ la dorsale funziona, il down riguarda il solo switch.")
    return None


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

    # v2026-06: diagnosi DORSALE per switch giu' (verifica uplink/backbone).
    if st in ("corr_switch_down", "corr_switch_unreachable"):
        try:
            diag = await _backbone_diagnosis(db, cid, alert.get("device_ip"))
            if diag:
                alert["backbone_diag"] = diag
                alert["message"] = (alert.get("message") or "") + "\n\n" + diag
        except Exception as e:  # noqa: BLE001
            logger.debug("backbone diagnosis failed: %s", e)
    return alert
