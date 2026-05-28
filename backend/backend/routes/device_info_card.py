"""
Device Info Card — anagrafica unificata per MSP.

Aggrega in una singola risposta JSON standard:
  - managed_devices (CRUD manuale per cliente)
  - device_poll_status (live dal connector)
  - cmdb_assets (inventory business)
  - lifecycle_records (warranty + EOL)
  - ilo_status (Redfish iLO)
  - firmware_catalog compliance
  - device_profiles library

Parser sys_descr regex multi-vendor per estrarre modello+firmware
anche da device non profilati (Cisco IOS, HP ProCurve, Aruba, Allied,
Ubiquiti, Juniper, D-Link, TP-Link, ecc.).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Dict, Any
import re

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["device-info-card"])


# ==================== HELPER: vendor_metrics extraction & sanitization ====================
# Bug noti dei polling SNMP: 0xFFFF=65535 viene usato come "no value" sentinel da molti vendor.
# Inoltre alcuni walk OID restituiscono indici parassiti (84-96) che non sono PSU/Fan veri.

def _sanitize_temp(v):
    """Filtra valori temperatura palesemente errati (sentinel 65535, valori >= 200°C, negativi)."""
    if not isinstance(v, (int, float)):
        return None
    if v <= -50 or v >= 200:
        return None
    return float(v)


def _max_valid_number(d):
    """Da un dict {idx: value}, ritorna il max dei value numerici validi (>0, <1000), None altrimenti.
    Se invece e` un singolo numero, lo ritorna pulito."""
    if isinstance(d, dict):
        nums = [v for v in d.values() if isinstance(v, (int, float)) and 0 < v < 1000]
        return max(nums) if nums else None
    if isinstance(d, (int, float)) and 0 < d < 1000:
        return float(d)
    return None


def _filter_states(d, max_idx=12):
    """Filtra un dict {idx: state} a soli indici plausibili (1..max_idx) e valori interi.
    Risolve il bug di walk OID che includeva indici parassiti (es. PSU 84-96).
    state code WireGuard/RFC 4133: 1=unknown, 2=ok, 3=warning, 4=critical."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        try:
            idx = int(k)
        except (ValueError, TypeError):
            continue
        if not (1 <= idx <= max_idx):
            continue
        try:
            v_int = int(v)
        except (ValueError, TypeError):
            continue
        out[str(idx)] = v_int
    return out


def _extract_switch_metrics(vm: dict) -> dict:
    """Estrae dal vendor_metrics i dati Performance/Hardware tipici di switch HP/H3C/Comware/Zyxel.
    Ritorna dict con cpu_usage, memory_usage, temperature (sanitizzati), psu_states, fan_states."""
    if not vm:
        return {}
    cpu = _max_valid_number(vm.get("h3cEntityExtCpuUsage") or vm.get("cpuUtil") or vm.get("zyxelCpuCurrent"))
    mem = _max_valid_number(vm.get("h3cEntityExtMemUsage") or vm.get("memUtil"))
    temp = _sanitize_temp(_max_valid_number(vm.get("h3cEntityExtTemperature") or vm.get("entTemperature")))
    psu = _filter_states(vm.get("h3cPowerState") or vm.get("psuStatus"))
    fan = _filter_states(vm.get("h3cFanState") or vm.get("fanStatus"))
    return {
        "cpu_usage": round(cpu, 1) if cpu is not None else None,
        "memory_usage": round(mem, 1) if mem is not None else None,
        "temperature": round(temp, 1) if temp is not None else None,
        "psu_states": psu or None,
        "fan_states": fan or None,
    }


# ==================== sys_descr PARSER ====================

# Regex pattern list: ordered by specificity.
# Each returns (vendor, model, firmware, os_family) when match.
_SYSDESCR_PATTERNS = [
    # Cisco IOS Classic / IOS XE
    # "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11, RELEASE SOFTWARE (fc2)"
    (
        re.compile(r"Cisco\s+(IOS(?:\s*XE)?)\s+Software.*?(\w[\w\-]+)\s+Software.*?Version\s+([^\s,]+)", re.I),
        lambda m: ("Cisco", m.group(2), m.group(3), "IOS"),
    ),
    # Cisco NX-OS
    (
        re.compile(r"Cisco\s+Nexus\s+(\w+).*?Version\s+([^\s,\)]+)", re.I),
        lambda m: ("Cisco", f"Nexus {m.group(1)}", m.group(2), "NX-OS"),
    ),
    # Cisco IOS short
    (
        re.compile(r"Cisco\s+(?:Internetwork\s+Operating\s+System|IOS).*?\(([A-Z0-9\-]+)\),\s+Version\s+([^\s,]+)", re.I),
        lambda m: ("Cisco", m.group(1), m.group(2), "IOS"),
    ),
    # HPE/HP ProCurve/Aruba classic: "ProCurve J9085A Switch 2610-24"
    (
        re.compile(r"Pro[Cc]urve\s+(J?\w+)\s+Switch\s+(\S+)(?:.*?(?:revision|Version)\s+([^\s,;]+))?", re.I),
        lambda m: ("HPE", f"ProCurve {m.group(2)}", (m.group(3) or ""), "ProVision"),
    ),
    # HPE Comware / H3C: "HPE Comware Platform Software, Software Version 7.1.070, Release 3208P26"
    (
        re.compile(r"(HPE?|H3C)\s+Comware.*?Version\s+([^\s,]+)(?:.*?Release\s+([^\s,]+))?", re.I),
        lambda m: ("HPE", "Comware Switch", (m.group(3) or m.group(2)), "Comware"),
    ),
    # Aruba (HPE) OS-CX: "Aruba JL659A 6200F 48G CL4 4SFP+ Switch, SW: 10.10.1020"
    (
        re.compile(r"Aruba\s+(\S+)\s+(\S+).*?(?:SW|Version):\s*([^\s,]+)", re.I),
        lambda m: ("Aruba (HPE)", f"{m.group(2)}", m.group(3), "AOS-CX"),
    ),
    # Allied Telesis: "Allied Telesis AT-x230-10GP, Version 5.5.2-0.1"
    (
        re.compile(r"Allied\s+Telesis\s+([A-Za-z0-9\-]+).*?(?:Version|Rev)\s+([^\s,]+)", re.I),
        lambda m: ("Allied Telesis", m.group(1), m.group(2), "AlliedWare Plus"),
    ),
    # MikroTik RouterOS: "RouterOS RB4011iGS+ 7.10.2 (stable)" or "MikroTik CCR1036-12G-4S RouterOS 6.49.7"
    (
        re.compile(r"(?:MikroTik\s+)?(?:Router\s*OS)\s+([\w\-\+]+)\s+([\d\.]+)", re.I),
        lambda m: ("MikroTik", m.group(1), m.group(2), "RouterOS"),
    ),
    (
        re.compile(r"MikroTik\s+([A-Z0-9\-\+]+)\s+RouterOS\s+([\d\.]+)", re.I),
        lambda m: ("MikroTik", m.group(1), m.group(2), "RouterOS"),
    ),
    # Ubiquiti EdgeOS / UniFi
    (
        re.compile(r"EdgeOS\s+(\w+)\s+v([\d\.\-\w]+)", re.I),
        lambda m: ("Ubiquiti", f"EdgeRouter {m.group(1)}", m.group(2), "EdgeOS"),
    ),
    (
        re.compile(r"UniFi\s+(?:Network\s+)?(?:Controller|Device)?\s*([A-Z0-9\-]+)?\s*(?:[Vv]er(?:sion)?|v)\.?\s*([\d\.\-\w]+)", re.I),
        lambda m: ("Ubiquiti", f"UniFi {m.group(1) or ''}".strip(), m.group(2), "UniFi"),
    ),
    # Juniper JunOS: "Juniper Networks, Inc. ex2200-24t-4g Ethernet Switch, kernel JUNOS 12.3R12"
    (
        re.compile(r"Juniper\s+Networks.*?(\S+)\s+(?:Ethernet\s+Switch|Router).*?JUNOS\s+([^\s,]+)", re.I),
        lambda m: ("Juniper", m.group(1), m.group(2), "JunOS"),
    ),
    # D-Link: "D-Link DGS-1210-28 Gigabit Ethernet Switch ver 4.00.008"
    (
        re.compile(r"D-Link\s+([A-Z]+-\d+[\w\-]*)\s+.*?(?:ver|version)\s+([^\s,]+)", re.I),
        lambda m: ("D-Link", m.group(1), m.group(2), "D-Link OS"),
    ),
    # TP-Link: "TP-Link T2600G-28TS, Firmware version: 3.0.5 Build 20220701"
    (
        re.compile(r"TP-?[Ll]ink\s+([A-Z0-9\-]+).*?(?:Firmware|version)\s*(?:version)?\s*:?\s*([\d\.]+(?:\s+Build\s+\d+)?)", re.I),
        lambda m: ("TP-Link", m.group(1), m.group(2), "TP-Link OS"),
    ),
    # Synology DSM: "Linux NAS01 4.4.302+ #42962 SMP Wed ... armv8" — usa diversi OID per DSM version
    (
        re.compile(r"Linux\s+\S+\s+[\d\.\-\+]+.*?Synology", re.I),
        lambda m: ("Synology", "DSM NAS", "", "DSM Linux"),
    ),
    # QNAP: "Linux QNAP 5.10.60-qnap1 #1 SMP..."
    (
        re.compile(r"Linux\s+\S+\s+[\d\.\-]+(?:-qnap\w*)", re.I),
        lambda m: ("QNAP", "QTS NAS", "", "QTS Linux"),
    ),
    # Fortinet: "FortiGate-100E v7.2.5,build1517,230918 (GA)" or "FortiGate-60F"
    (
        re.compile(r"(FortiGate|FortiSwitch|FortiAP|FortiMail|FortiAnalyzer)-?(\w+)\s+v([^,\s]+)", re.I),
        lambda m: ("Fortinet", f"{m.group(1)}-{m.group(2)}", m.group(3), "FortiOS"),
    ),
    # Zyxel USG/ATP: "USG FLEX 200 V5.37(ABUH.0) | 2023-03-14 14:51:53"
    (
        re.compile(r"(USG\s*(?:FLEX)?|ATP|GS\d+|XGS\d+|XS\d+)\s+(\S+)\s+V([\d\.\(\)A-Z]+)", re.I),
        lambda m: ("Zyxel", f"{m.group(1)} {m.group(2)}".strip(), m.group(3), "ZLD"),
    ),
    # HPE iLO: "Hewlett Packard Enterprise Integrated Lights-Out 5, firmware version 2.93"
    (
        re.compile(r"(?:Hewlett[\s\-]Packard\s+)?(?:Enterprise\s+)?Integrated\s+Lights-Out\s+(\d+).*?version\s+([^\s,;]+)", re.I),
        lambda m: ("HPE", f"iLO {m.group(1)}", m.group(2), "iLO"),
    ),
    # Dell iDRAC
    (
        re.compile(r"iDRAC\s*(\d+)?.*?(?:version|v)\.?\s*([^\s,]+)", re.I),
        lambda m: ("Dell", f"iDRAC {m.group(1) or ''}".strip(), m.group(2), "iDRAC"),
    ),
    # APC UPS: "APC Web/SNMP Management Card (MB:v4.4.2 PF:v7.1.1 PN:apc_hw05_aos_711.bin ..."
    (
        re.compile(r"APC\s+(?:Web/)?SNMP.*?(?:PF|firmware):\s*v?([^\s,]+)", re.I),
        lambda m: ("APC", "Smart-UPS", m.group(1), "NMC"),
    ),
    # Generic Linux — last resort
    (
        re.compile(r"Linux\s+(\S+)\s+([\d\.\-\+]+)", re.I),
        lambda m: ("Linux", m.group(1), m.group(2), "Linux"),
    ),
    # Windows — "Hardware: AMD64 Family 23 Model 1 - Software: Windows Version 10.0 (Build 19045 Multiprocessor Free)"
    (
        re.compile(r"Software:\s+Windows\s+Version\s+([\d\.]+)\s+\(Build\s+(\d+)", re.I),
        lambda m: ("Microsoft", "Windows Server", f"{m.group(1)} build {m.group(2)}", "Windows"),
    ),
]


def parse_sys_descr(sys_descr: Optional[str]) -> Dict[str, Optional[str]]:
    """Parse SNMP sysDescr OID (1.3.6.1.2.1.1.1.0) to extract vendor/model/firmware.
    Returns dict with keys: vendor, model, firmware, os_family, matched (bool).
    """
    result = {"vendor": None, "model": None, "firmware": None, "os_family": None, "matched": False}
    if not sys_descr or not isinstance(sys_descr, str):
        return result
    raw = sys_descr.strip()
    for pattern, extractor in _SYSDESCR_PATTERNS:
        m = pattern.search(raw)
        if m:
            try:
                vendor, model, firmware, os_family = extractor(m)
                result.update({
                    "vendor": vendor.strip() if vendor else None,
                    "model": (model or "").strip() or None,
                    "firmware": (firmware or "").strip() or None,
                    "os_family": os_family,
                    "matched": True,
                })
                return result
            except Exception:
                continue
    return result


# ==================== INFO CARD AGGREGATOR ====================

def _first_not_none(*values):
    for v in values:
        if v is not None and v != "":
            return v
    return None


def _first_meaningful_metric(*values):
    """Come _first_not_none ma scarta anche zero (CPU/Memoria 0% su switch attivo non ha senso e
    di solito indica che il poll non ha letto il dato; preferiamo il fallback dal vendor_metrics)."""
    for v in values:
        if v is None or v == "":
            continue
        try:
            if float(v) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        return v
    # Se davvero tutto e' 0/None, ritorna il primo valore (puo' essere 0 reale)
    for v in values:
        if v is not None and v != "":
            return v
    return None


def _safe_iso(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


async def build_info_card(device_ip: str) -> Dict[str, Any]:
    """Aggrega info da tutte le sorgenti disponibili per device_ip."""
    # 1) Live poll from connector
    poll = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0}) or {}
    # 2) Manual/managed device (user-configured SNMP+WebConsole)
    managed = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0}) or {}
    # 3) CMDB asset (business-level inventory)
    cmdb = await db.cmdb_assets.find_one({"ip_address": device_ip}, {"_id": 0}) or {}
    # 4) Lifecycle record (warranty/EOL)
    lifecycle = await db.lifecycle_records.find_one({"device_ip": device_ip}, {"_id": 0}) or {}
    # 5) Redfish iLO deep data
    ilo = await db.ilo_status.find_one({"device_ip": device_ip}, {"_id": 0}) or {}
    # 6) Firmware compliance
    fw_compliance = poll.get("firmware_compliance") or {}
    # 7) Parse sys_descr as fallback
    parsed = parse_sys_descr(poll.get("sys_descr") or managed.get("sys_descr"))

    # 7b) ENTITY-MIB (universal SNMP, high-priority source for vendor/model/serial/firmware)
    entity = poll.get("entity_mib") or {}

    # 8) Device profile (vendor capabilities)
    profile_key = _first_not_none(poll.get("profile_key"), managed.get("profile_key"))
    profile_doc = None
    if profile_key:
        profile_doc = await db.device_profiles.find_one({"key": profile_key}, {"_id": 0})

    # Switch vendor_metrics extracted once (sanitized)
    # 9) Firewall metrics (Zyxel / Fortinet)
    fw_data = poll.get("firewall") or {}
    vm = poll.get("vendor_metrics") or {}

    # Switch-style vendor metrics extracted/sanitized once
    sw_metrics = _extract_switch_metrics(vm)

    # 10) Client info
    client_id = _first_not_none(poll.get("client_id"), managed.get("client_id"), cmdb.get("client_id"))
    client = await db.clients.find_one({"id": client_id}, {"_id": 0}) if client_id else None

    sources = []
    if poll:
        sources.append("connector")
    if managed:
        sources.append("managed_devices")
    if cmdb:
        sources.append("cmdb")
    if lifecycle:
        sources.append("lifecycle")
    if ilo:
        sources.append("redfish_ilo")
    if profile_doc:
        sources.append("device_profile")
    if entity:
        sources.append("entity_mib")
    if parsed.get("matched"):
        sources.append("sys_descr_parser")

    # Resolve identity (priority: ilo > entity_mib > firewall metadata > lifecycle > cmdb > profile > parsed > poll)
    vendor = _first_not_none(
        ilo.get("manufacturer"),
        entity.get("vendor"),
        fw_data.get("vendor"),
        lifecycle.get("vendor"),
        cmdb.get("vendor"),
        (profile_doc or {}).get("vendor"),
        parsed.get("vendor"),
        poll.get("vendor"),
    )
    model = _first_not_none(
        ilo.get("server_model"),
        ilo.get("model"),
        entity.get("model"),
        fw_data.get("product_name"),
        vm.get("modelName"),
        lifecycle.get("model"),
        cmdb.get("model"),
        parsed.get("model"),
        (profile_doc or {}).get("family"),
    )

    # Sostituisci il modello con quello specifico dato dal sysObjectID se mappato nel profilo.
    # Esempio: profilo hpe_comware ha model_by_oid_suffix per .161 (5130 EI), .162 (5130 HI), .173 (5140 EI).
    sysoid_for_model = poll.get("sys_object_id") or managed.get("sys_object_id") or entity.get("sys_object_id")
    if sysoid_for_model and profile_doc:
        try:
            from device_profiles import detect_model_label
            specific = detect_model_label(profile_doc, sysoid_for_model)
            if specific:
                model = specific
        except Exception:
            pass
    serial = _first_not_none(
        ilo.get("serial_number"),
        entity.get("serial_number"),
        fw_data.get("serial_number"),
        vm.get("serialNumber"),
        lifecycle.get("serial_number"),
        cmdb.get("serial_number"),
    )
    firmware = _first_not_none(
        ilo.get("ilo_firmware") or ilo.get("ilo_version"),
        entity.get("firmware"),
        fw_data.get("firmware"),
        vm.get("firmwareVersion"),
        parsed.get("firmware"),
    )
    bios = ilo.get("bios_version")

    hostname = _first_not_none(
        poll.get("sys_name"),
        poll.get("device_name"),
        managed.get("name"),
        cmdb.get("hostname"),
    )

    # MAC: prefer primary MAC if exposed; else first from device_macs list; else ARP-cache lookup
    macs = poll.get("device_macs") or []
    primary_mac = poll.get("primary_mac")
    if not primary_mac and isinstance(macs, list) and macs:
        first = macs[0]
        primary_mac = first.get("mac") if isinstance(first, dict) else first
    # Cross-device ARP cache lookup (IP discovered by a neighbor router/switch)
    mac_source = None
    arp_source_ip = None
    if primary_mac:
        mac_source = "self-snmp"
    else:
        arp_doc = await db.arp_cache.find_one({"ip": device_ip}, {"_id": 0}, sort=[("last_seen", -1)])
        if arp_doc and arp_doc.get("mac"):
            primary_mac = arp_doc["mac"]
            mac_source = "arp-cache"
            arp_source_ip = arp_doc.get("source_device_ip")

    device_type = _first_not_none(
        poll.get("device_class"),
        managed.get("device_type"),
        cmdb.get("device_type"),
        (profile_doc or {}).get("family"),
    )

    # Uptime calculation
    uptime_days = None
    sys_uptime = poll.get("sys_uptime")
    if sys_uptime and isinstance(sys_uptime, (int, float)):
        try:
            uptime_days = round(float(sys_uptime) / (100 * 86400), 1)  # SNMP timeticks = centiseconds
        except Exception:
            pass

    return {
        "device_ip": device_ip,
        "client": {
            "id": client_id,
            "name": (client or {}).get("name") if client else None,
        },
        "identity": {
            "ip": device_ip,
            "hostname": hostname,
            "mac_primary": primary_mac,
            "mac_source": mac_source,
            "mac_arp_source_ip": arp_source_ip,
            "mac_count": len(macs) if isinstance(macs, list) else 0,
            "vendor": vendor,
            "model": model,
            "serial_number": serial,
            "asset_tag": _first_not_none(cmdb.get("asset_tag"), lifecycle.get("asset_tag")),
            "device_type": device_type,
            "profile_key": profile_key,
            "os_family": parsed.get("os_family") or ((profile_doc or {}).get("os_family")),
        },
        "firmware": {
            "current": firmware,
            "bios": bios,
            "hardware_rev": entity.get("hardware_rev"),
            "compliance": {
                "status": fw_compliance.get("overall_status"),
                "severity": fw_compliance.get("severity"),
                "cve_count": len(fw_compliance.get("cves") or []),
                "advisory_url": fw_compliance.get("advisory_url"),
                "components": fw_compliance.get("components") or [],
            } if fw_compliance else None,
        },
        "status": {
            "reachable": poll.get("reachable"),
            "monitor_type": poll.get("monitor_type"),
            "last_poll": _safe_iso(poll.get("last_poll") or poll.get("updated_at")),
            "last_update": _safe_iso(poll.get("updated_at") or poll.get("last_update")),
            "uptime_days": uptime_days,
            "unreachable_since": _safe_iso(poll.get("unreachable_since")),
            "connector_hostname": poll.get("connector_hostname"),
        },
        "hardware": {
            "cpu_usage": _first_meaningful_metric(poll.get("cpu_usage"), sw_metrics.get("cpu_usage")),
            "memory_usage": _first_meaningful_metric(poll.get("memory_usage"), sw_metrics.get("memory_usage")),
            "temperature": _sanitize_temp(_first_meaningful_metric(poll.get("temperature"), sw_metrics.get("temperature"))),
            "power_watts": ilo.get("power_watts"),
            "fan_count": len(ilo.get("fans") or []) or None,
            "psu_count": len(ilo.get("power_supplies") or []) or None,
            "temp_sensor_count": len(ilo.get("temperatures") or []) or None,
            "storage_drive_count": sum(len((c or {}).get("drives", [])) for c in (ilo.get("storage_controllers") or [])) or None,
            "memory_dimm_count": len(ilo.get("memory_modules") or []) or None,
            "nic_count": len(ilo.get("network_interfaces") or []) or None,
            "firewall_sessions": fw_data.get("active_sessions"),
            "firewall_flash_usage_pct": fw_data.get("flash_usage"),
            # Switch-specific structured states (sanitizzato vs vendor_metrics raw)
            "psu_states": sw_metrics.get("psu_states"),
            "fan_states": sw_metrics.get("fan_states"),
        },
        "network": {
            "open_ports": poll.get("open_ports") or [],
            "interfaces_count": len(poll.get("ports") or []),
            "ping_ms": poll.get("ping_ms"),
            "ping_stats": poll.get("ping_stats"),
            "web_console_url": managed.get("web_console_url"),
            "web_console_port": managed.get("web_console_port"),
            "web_console_scheme": managed.get("web_console_scheme"),
            "web_console_working": managed.get("web_console_working"),
            "web_console_title": managed.get("web_console_title"),
            "snmp_version": managed.get("snmp_version"),
            "snmp_port": managed.get("snmp_port", 161),
        },
        "lifecycle": {
            "purchase_date": _safe_iso(lifecycle.get("purchase_date")),
            "warranty_end": _safe_iso(lifecycle.get("warranty_end")),
            "maintenance_end": _safe_iso(lifecycle.get("maintenance_end")),
            "eol_date": _safe_iso(lifecycle.get("eol_date")),
            "eosl_date": _safe_iso(lifecycle.get("eosl_date")),
            "risk_score": lifecycle.get("risk_score"),
            "risk_band": lifecycle.get("risk_band"),
            "criticality": lifecycle.get("criticality"),
            "contract_number": lifecycle.get("contract_number"),
            "vendor_support_tier": lifecycle.get("vendor_support_tier"),
        } if lifecycle else None,
        "location": {
            "site": cmdb.get("site"),
            "building": cmdb.get("building"),
            "floor": cmdb.get("floor"),
            "room": cmdb.get("room"),
            "rack": cmdb.get("rack"),
            "rack_unit": cmdb.get("rack_unit"),
            "owner": cmdb.get("owner") or lifecycle.get("responsible"),
            "cost_monthly": cmdb.get("cost_monthly"),
            "notes": cmdb.get("notes"),
        },
        "capabilities": (profile_doc or {}).get("capabilities") or [],
        "vendor_metrics_summary": {
            "keys": list(vm.keys())[:20] if vm else [],
            "count": len(vm) if vm else 0,
        },
        # Raw vendor_metrics (key:value) — usato dal pulsante "Tutte le metriche" in UI.
        # Limitato a 200 chiavi per evitare payload eccessivi.
        "vendor_metrics_full": dict(list(vm.items())[:200]) if vm else {},
        # Raw poll snapshot — fornisce all'admin TUTTI i dati grezzi raccolti dal dispositivo
        # (CPU, memoria, ports, vendor_metrics, hardware, ecc.) per ispezione completa.
        # Filtra solo campi non serializzabili (datetime gia` convertiti, nessun ObjectId).
        "raw_data": {
            k: v for k, v in poll.items()
            if k not in {"_id", "client_id", "device_ip", "id", "uuid"} and not k.startswith("_")
        } if poll else {},
        "sys_descr_raw": poll.get("sys_descr"),
        "data_sources": sources,
    }


@router.get("/devices/by-ip/{device_ip}/info-card")
async def get_info_card(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Scheda anagrafica unificata del dispositivo (modello/serial/firmware/lifecycle/location).
    Aggrega device_poll_status + managed_devices + cmdb_assets + lifecycle_records + ilo_status.
    """
    # Check that device exists somewhere
    exists = (
        await db.device_poll_status.count_documents({"device_ip": device_ip}) > 0
        or await db.managed_devices.count_documents({"ip": device_ip}) > 0
        or await db.cmdb_assets.count_documents({"ip_address": device_ip}) > 0
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Device not found in any source")
    return await build_info_card(device_ip)


@router.post("/devices/info-card/parse-sys-descr")
async def parse_sys_descr_debug(payload: dict, current_user: dict = Depends(get_current_user)):
    """Debug endpoint: prova il parser sys_descr su una stringa arbitraria."""
    sd = (payload or {}).get("sys_descr", "")
    return {"input": sd, "parsed": parse_sys_descr(sd)}
