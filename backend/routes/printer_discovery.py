"""
Printer Discovery API (v3.7.3)
==============================
Aggrega tutte le stampanti di rete di un cliente incrociando 4 fonti:

  1. OUI vendor — MAC prefix che appartiene a produttori stampanti noti
     (HP Printer, Epson, Canon, Brother, Lexmark, Kyocera, Xerox, Ricoh,
      OKI, Sharp, Konica Minolta, Zebra, Samsung Printer, Develop, Fuji Xerox).
  2. SNMP sysDescr — managed device con `device_type == 'printer'` o sysDescr
     contenente keyword stampante.
  3. Datto RMM — device con hostname tipo PRINT-/MFP-/HP-LJ-/EPSON-.
  4. Manual binding — endpoint con manual_binding_type == 'printer'.

Posizione fisica (switch IP + porta) via `discovered_endpoints` FDB.

Endpoint:
- GET /api/clients/{client_id}/printers-discovery
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends

from database import db
from deps import get_current_user
from routes.oui_lookup import lookup_oui, is_printer_vendor

router = APIRouter(prefix="/api", tags=["printer-discovery"])


PRINTER_SYSDESCR_KEYWORDS = (
    "printer", "laserjet", "officejet", "pagewide", "deskjet", "envy",
    "stylus", "workforce", "expression", "ecotank",
    "imagerunner", "imageclass", "pixma", "maxify",
    "hl-", "mfc-", "dcp-", "brother",
    "lexmark", "ecosys", "taskalfa", "kyocera",
    "xerox", "workcentre", "phaser",
    "ricoh", "aficio",
    "oki ", "okipage",
    "sharp", "konica", "bizhub",
    "zebra", "zt410", "zt510",
    "develop", "ineo",
    "mfp", "multifunction", "copier", "plotter",
)


def _looks_like_printer_sysdescr(desc: str) -> bool:
    if not desc:
        return False
    d = desc.lower()
    return any(k in d for k in PRINTER_SYSDESCR_KEYWORDS)


HOSTNAME_PRINTER_PATTERN = re.compile(
    r"(?i)^(print|printer|mfp|copier|hp-lj|hplj|epson|canon|brother|"
    r"lexmark|kyocera|ricoh|xerox|oki|sharp|konica|zebra|plot|plotter)[-_]?"
)


def _looks_like_printer_hostname(name: str) -> bool:
    if not name:
        return False
    return bool(HOSTNAME_PRINTER_PATTERN.match(name.strip()))


# v3.7.7: keyword match su LLDP-MED manufacturer / model (come arriva dallo
# switch via OID lldpXMedRemInventory). Nomi vendor tipici pubblicati dalle
# stampanti enterprise: "Hewlett-Packard", "HP Inc.", "Brother Industries",
# "Canon Inc.", "Seiko Epson Corp.", "Lexmark International", "Kyocera",
# "Ricoh Company", "Xerox Corporation", "Sharp Corporation", "OKI Data",
# "Konica Minolta", "Zebra Technologies", "Fuji Xerox".
_PRINTER_MED_KEYWORDS = (
    "brother", "canon", "epson", "lexmark", "kyocera", "ricoh",
    "xerox", "sharp", "oki", "konica", "zebra", "hp inc", "hewlett-packard",
    "develop", "fuji xerox", "toshiba tec", "samsung printer",
    "laserjet", "officejet", "workforce", "imagerunner", "bizhub",
    "taskalfa", "ecosys", "workcentre", "phaser",
)


def _looks_like_printer_lldp_med(mfg: str, model: str) -> bool:
    """True se LLDP-MED mfg o model contengono keyword stampante enterprise."""
    blob = f"{mfg or ''} {model or ''}".lower()
    if not blob.strip():
        return False
    return any(k in blob for k in _PRINTER_MED_KEYWORDS)


@router.get("/clients/{client_id}/printers-discovery")
async def discover_client_printers(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Lista stampanti del cliente aggregando FDB/SNMP/Datto/manual."""
    # 1. Endpoint FDB (MAC-IP-switch-port + nuovi campi da printer-probe)
    eps = await db.discovered_endpoints.find(
        {"client_id": client_id},
        {"_id": 0, "ip": 1, "mac": 1, "switch_ip": 1, "port": 1,
         "datto_name": 1, "manual_binding_name": 1, "manual_binding_type": 1,
         "is_managed": 1,
         # v3.7.3: arricchimenti da printer-probe del connector
         "is_printer": 1, "sys_descr": 1, "printer_model": 1,
         "printer_probe_ports": 1,
         # v3.7.4: arricchimenti da switch-enrichment (LLDP-MED)
         "lldp_med_mfg": 1, "lldp_med_model": 1, "ip_source": 1},
    ).to_list(100000)

    # 2. Managed devices (per sysDescr / device_type / vendor)
    managed = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "ip_address": 1, "ip": 1,
         "mac_address": 1, "device_type": 1, "vendor": 1, "model": 1,
         "sys_descr": 1, "datto_name": 1},
    ).to_list(10000)
    managed_by_ip: dict = {}
    managed_by_mac: dict = {}
    for md in managed:
        ip = md.get("ip_address") or md.get("ip") or ""
        mac = (md.get("mac_address") or "").upper()
        if ip:
            managed_by_ip[ip] = md
        if mac:
            managed_by_mac[mac] = md

    # 3. Datto devices (privacy-safe: solo name/mac/ip)
    datto_by_mac: dict = {}
    datto_by_ip: dict = {}
    async for d in db.datto_devices.find(
        {"client_id": client_id},
        {"_id": 0, "name": 1, "mac_list": 1, "ip_list": 1},
    ):
        for m in (d.get("mac_list") or []):
            if m:
                datto_by_mac.setdefault(m.upper(), d)
        for ip in (d.get("ip_list") or []):
            if ip:
                datto_by_ip.setdefault(ip, d)

    # 4. Aggrega
    printers: dict = {}

    def _key(mac: str, ip: str) -> str:
        return (mac or "").upper() or f"ip:{ip}"

    for ep in eps:
        mac = (ep.get("mac") or "").upper()
        ip = ep.get("ip") or ""
        vendor = lookup_oui(mac) if mac else ""
        is_by_oui = is_printer_vendor(vendor)
        md = managed_by_ip.get(ip) or managed_by_mac.get(mac) or {}
        # sys_descr: prima dal probe dell'endpoint (piu' fresco), poi dal managed
        ep_sys_descr = ep.get("sys_descr") or ""
        sys_descr = ep_sys_descr or md.get("sys_descr") or ""
        dtype = (md.get("device_type") or "").lower()
        is_by_snmp = (
            bool(ep.get("is_printer"))
            or _looks_like_printer_sysdescr(sys_descr)
            or dtype == "printer"
        )
        # v3.7.7: LLDP-MED signal (Brother/Lexmark/HP enterprise/... pubblicano
        # marca/modello via LLDP-MED anche quando non c'e' managed_devices match
        # ne OUI riconoscibile (es. MAC virtualizzati o OUI fuori dal DB ridotto).
        lldp_mfg = ep.get("lldp_med_mfg") or ""
        lldp_model = ep.get("lldp_med_model") or ""
        is_by_lldp_med = _looks_like_printer_lldp_med(lldp_mfg, lldp_model)
        datto_name = ep.get("datto_name") or ""
        datto_dev = datto_by_mac.get(mac) or (datto_by_ip.get(ip) if ip else None)
        is_by_datto = bool(datto_name) and _looks_like_printer_hostname(datto_name)
        is_by_manual = (ep.get("manual_binding_type") or "").lower() == "printer"

        if not (is_by_oui or is_by_snmp or is_by_lldp_med or is_by_datto or is_by_manual):
            continue

        k = _key(mac, ip)
        entry = printers.get(k)
        if not entry:
            entry = {
                "name": "", "ip": ip, "mac": mac, "vendor": vendor, "model": "",
                "switch_ip": ep.get("switch_ip") or "",
                "switch_port": str(ep.get("port") or ""),
                "sources": set(),
                "is_managed": False, "datto_matched": False,
                "probe_ports": ep.get("printer_probe_ports") or [],
            }
            printers[k] = entry

        # name priority: managed > datto > manual > probe_model > lldp-med > (vendor default)
        if md.get("name") and not entry["name"]:
            entry["name"] = md["name"]
        elif datto_name and not entry["name"]:
            entry["name"] = datto_name
        elif ep.get("manual_binding_name") and not entry["name"]:
            entry["name"] = ep["manual_binding_name"]
        elif datto_dev and not entry["name"]:
            entry["name"] = datto_dev.get("name", "")
        elif ep.get("printer_model") and not entry["name"]:
            entry["name"] = ep["printer_model"]
        elif lldp_model and not entry["name"]:
            # es. "HL-L2370DW" -> diventa nome visualizzabile
            if lldp_mfg:
                entry["name"] = f"{lldp_mfg.strip()} {lldp_model.strip()}".strip()
            else:
                entry["name"] = lldp_model.strip()

        # Model: priorità probe > sysDescr managed > LLDP-MED model
        if ep.get("printer_model") and not entry["model"]:
            entry["model"] = ep["printer_model"][:120]
        elif sys_descr and not entry["model"]:
            entry["model"] = sys_descr[:120].strip()
        elif lldp_model and not entry["model"]:
            entry["model"] = lldp_model[:120].strip()
        if not entry["vendor"] and md.get("vendor"):
            entry["vendor"] = md["vendor"]
        if not entry["vendor"] and lldp_mfg:
            entry["vendor"] = lldp_mfg.strip()[:60]

        if is_by_oui:
            entry["sources"].add("oui")
        if is_by_snmp:
            entry["sources"].add("snmp")
            entry["is_managed"] = bool(md) or bool(ep.get("is_printer"))
        if is_by_lldp_med:
            entry["sources"].add("lldp-med")
        if is_by_datto or datto_dev:
            entry["sources"].add("datto")
            if datto_dev:
                entry["datto_matched"] = True
        if is_by_manual:
            entry["sources"].add("manual")

    # 4b. Managed printers non nei FDB (statici)
    for md in managed:
        dtype = (md.get("device_type") or "").lower()
        sys_descr = md.get("sys_descr") or ""
        if dtype != "printer" and not _looks_like_printer_sysdescr(sys_descr):
            continue
        ip = md.get("ip_address") or md.get("ip") or ""
        mac = (md.get("mac_address") or "").upper()
        k = _key(mac, ip)
        if k in printers:
            continue
        vendor = (lookup_oui(mac) if mac else "") or (md.get("vendor") or "")
        printers[k] = {
            "name": md.get("name") or "",
            "ip": ip, "mac": mac, "vendor": vendor,
            "model": sys_descr[:120].strip() or (md.get("model") or ""),
            "switch_ip": "", "switch_port": "",
            "sources": {"snmp"},
            "is_managed": True,
            "datto_matched": bool(md.get("datto_name")),
        }

    # Normalizza output
    items = []
    for p in printers.values():
        p["sources"] = sorted(list(p["sources"]))
        if not p["name"]:
            p["name"] = (
                p.get("model")
                or (f"{p['vendor']} printer" if p.get("vendor") else "Stampante")
            )
        items.append(p)
    items.sort(key=lambda x: (x["name"].lower(), x["ip"]))

    by_vendor: dict = {}
    unique_ips = set()
    for p in items:
        v = p.get("vendor") or "Sconosciuto"
        by_vendor[v] = by_vendor.get(v, 0) + 1
        if p.get("ip"):
            unique_ips.add(p["ip"])

    return {
        "items": items,
        "count": len(items),
        "unique_ips": len(unique_ips),
        "by_vendor": dict(sorted(by_vendor.items(), key=lambda x: -x[1])),
    }
