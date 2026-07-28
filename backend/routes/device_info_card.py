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
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import re
import logging

logger = logging.getLogger("device_info_card")

from database import db
from deps import get_current_user, audit_logger
from audit import AuditAction
from display_name import best_display_name
from liveness_resolver import (
    build_evidence_maps, compute_status, build_clients_without_online_agent,
    _snmp_fresh,
)

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


async def build_info_card(device_ip: str, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Aggrega info da tutte le sorgenti disponibili per device_ip.

    v2026-06 FIX multi-tenant: se client_id e' fornito, OGNI query e' filtrata
    per client_id. Senza questo filtro, IP privati comuni (es. 192.168.1.x)
    condivisi tra piu' clienti causavano un leak cross-tenant (find_one per solo
    IP restituiva il device di un altro cliente).
    """
    def _q(base: dict) -> dict:
        if client_id:
            return {**base, "client_id": client_id}
        return base
    # 1) Live poll from connector
    poll = await db.device_poll_status.find_one(_q({"device_ip": device_ip}), {"_id": 0}) or {}
    # 2) Manual/managed device (user-configured SNMP+WebConsole)
    managed = await db.managed_devices.find_one(_q({"ip": device_ip}), {"_id": 0}) or {}
    # 3) CMDB asset (business-level inventory)
    cmdb = await db.cmdb_assets.find_one(_q({"ip_address": device_ip}), {"_id": 0}) or {}
    # 4) Lifecycle record (warranty/EOL)
    lifecycle = await db.lifecycle_records.find_one(_q({"device_ip": device_ip}), {"_id": 0}) or {}
    # 5) Redfish iLO deep data
    ilo = await db.ilo_status.find_one(_q({"device_ip": device_ip}), {"_id": 0}) or {}
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

    # 10) Client info — preferisci il client_id passato (scope multi-tenant),
    # fallback ai valori delle sorgenti.
    client_id = client_id or _first_not_none(poll.get("client_id"), managed.get("client_id"), cmdb.get("client_id"))
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

    # v2026-02-14: detail con motivo per le fonti MANCANTI.
    # Cosi' l'admin capisce QUALE pezzo configurare per attivare quel badge.
    sys_descr_raw = (poll.get("sys_descr") or managed.get("sys_descr") or "").strip()
    sources_status = []
    for key, present, reason_missing in [
        ("connector", bool(poll), "Il connector v4 non ha mai pollato questo device. Verifica che sia registrato e attivo per il cliente."),
        ("managed_devices", bool(managed), "Device non presente in managed_devices. Aggiungilo manualmente o attendi che il connector lo scopra."),
        ("entity_mib", bool(entity), (
            "ENTITY-MIB (OID 1.3.6.1.2.1.47.*) non e' stato letto. "
            "Verifica: (1) credenziali SNMP configurate e funzionanti, "
            "(2) il device espone ENTITY-MIB (la maggior parte di switch/firewall enterprise sì, alcuni CPE consumer no), "
            "(3) il connector v4 ha aggiornato la sua lista profili."
        )),
        ("sys_descr_parser", bool(parsed.get("matched")), (
            "sysDescr non riconosciuto dal parser. " + (
                f"Stringa ricevuta: \"{sys_descr_raw[:80]}{'...' if len(sys_descr_raw)>80 else ''}\". "
                "Aggiungi una regola al parser in backend/sys_descr_parser.py."
                if sys_descr_raw else
                "sysDescr vuoto: verifica credenziali SNMP e che il device risponda all'OID 1.3.6.1.2.1.1.1.0."
            )
        )),
        ("device_profile", bool(profile_doc), (
            f"Nessun profilo vendor assegnato (profile_key='{profile_key or 'generic'}'). "
            "Il classifier non ha riconosciuto modello/vendor; il device usera' OID base senza metriche specifiche."
        )),
        ("cmdb", bool(cmdb), "Nessuna scheda CMDB associata (ubicazione, owner, costo)."),
        ("lifecycle", bool(lifecycle), "Nessun record di lifecycle (acquisto, garanzia, EOL)."),
        ("redfish_ilo", bool(ilo), "iLO/Redfish non configurato. Per server HP/Dell aggiungi credenziali iLO dalla tab Credenziali."),
    ]:
        sources_status.append({
            "key": key,
            "present": present,
            "reason": reason_missing if not present else None,
        })

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

    hostname = best_display_name(managed, poll, device_ip)

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
        arp_doc = await db.arp_cache.find_one(_q({"ip": device_ip}), {"_id": 0}, sort=[("last_seen", -1)])
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

    # v2026-06-23 LIVENESS UNIFICATO + TRASPARENZA:
    # la Scheda Dispositivo prima mostrava poll.reachable GREZZO (solo ICMP)
    # → uno switch HP che blocca ICMP ma risponde a SNMP appariva OFFLINE
    # qui mentre la lista Dispositivi lo dava ONLINE. Ora usiamo lo stesso
    # liveness_resolver di lista+panoramica e mostriamo SEPARATAMENTE la
    # verita' ICMP e quella SNMP + il motivo, cosi' l'admin sa esattamente
    # PERCHE' un device e' considerato online/offline.
    icmp_reachable = poll.get("reachable")
    snmp_reachable = poll.get("snmp_reachable")
    snmp_is_fresh = _snmp_fresh(poll) if poll else False
    effective_status = "pending"
    live_reason = None
    try:
        ip_ev, mac_ev = await build_evidence_maps(db, client_id=client_id) if client_id else ({}, {})
        offline_clients = await build_clients_without_online_agent(db)
        effective_status, live_reason = compute_status(
            poll, managed, ip_ev, mac_ev, offline_clients,
        )
    except Exception:
        # Fallback prudente: ICMP OR SNMP fresco. Logghiamo per non mascherare
        # regressioni silenziose su build_evidence_maps / offline_clients.
        logger.exception("compute_status fallito per %s, uso fallback ICMP/SNMP", device_ip)
        if icmp_reachable or snmp_is_fresh:
            effective_status = "online"
            live_reason = "snmp" if (not icmp_reachable and snmp_is_fresh) else "ping"
        elif poll:
            effective_status = "offline"

    # Etichette human-readable italiane per il motivo dello stato
    _reason_labels = {
        "mac_table_switch": "Visto nella MAC table dello switch (SNMP/FDB)",
        "agent_v4_arp": "Visto nella tabella ARP dell'agent",
        "scanner_lan": "Visto dallo Scanner LAN (ARP/mDNS)",
        "snmp": "Risponde a SNMP (ICMP bloccato dal firewall)",
        "ping": "Risponde al ping ICMP",
        "icmp_native": "Risponde al ping ICMP (nativo)",
        "agent_offline": "Connector offline — stato incerto",
    }
    live_reason_label = _reason_labels.get(
        live_reason,
        (live_reason or "").replace("_", " ").strip() or None,
    )
    # Backward-compat: il frontend legacy usa status.reachable per il badge.
    # Lo mappiamo allo stato EFFETTIVO (non piu' il solo ICMP grezzo).
    effective_reachable_bool = (
        True if effective_status == "online"
        else (False if effective_status == "offline" else None)
    )

    # v2026-06-23: stato manutenzione (scheduled downtime) per badge UI
    in_maintenance = False
    maintenance_window = None
    try:
        if client_id:
            from alert_filter import get_active_maintenance_windows
            for w in await get_active_maintenance_windows(db, client_id):
                ips = w.get("device_ips") or []
                if not ips or device_ip in ips:
                    in_maintenance = True
                    maintenance_window = {
                        "title": w.get("title"),
                        "end_time": w.get("end_time"),
                        "scope": "client" if not ips else "device",
                    }
                    break
    except Exception:
        pass

    # v2026-06-23 SOFT/HARD STATE: espone lo stato di conferma per la UI.
    # state_type: hard=confermato (online stabile o offline confermato),
    # soft=in verifica (degrading, sotto soglia, nessun alert).
    state_type = managed.get("state_type")
    degraded = bool(managed.get("degraded", False))
    failed_attempts = int(managed.get("consecutive_ping_failures") or 0)
    try:
        if managed.get("max_check_attempts"):
            max_check_attempts = int(managed.get("max_check_attempts"))
        else:
            _mca = await db.settings.find_one({"key": "max_check_attempts"}, {"_id": 0, "value": 1})
            max_check_attempts = int(_mca.get("value")) if _mca and _mca.get("value") else 5
    except Exception:
        max_check_attempts = 5

    # v2026-06-23 PARENT DEPENDENCY: se il device e' offline ma il suo padre
    # e' offline, e' IRRAGGIUNGIBILE (non down per colpa sua).
    parent_ip = managed.get("parent_ip") or None
    parent_name = None
    parent_status = None
    unreachable_dependency = False
    try:
        from alert_filter import get_dependency_state
        p_ip, p_name, p_status = await get_dependency_state(db, client_id, device_ip)
        parent_ip, parent_name, parent_status = p_ip, p_name, p_status
        if p_status == "offline" and effective_status != "online":
            unreachable_dependency = True
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
            "reachable": effective_reachable_bool,
            "icmp_reachable": icmp_reachable,
            "snmp_reachable": snmp_reachable,
            "snmp_fresh": snmp_is_fresh,
            "snmp_last_check_at": _safe_iso(poll.get("snmp_last_check_at")),
            "effective_status": effective_status,
            "live_reason": live_reason,
            "live_reason_label": live_reason_label,
            "in_maintenance": in_maintenance,
            "maintenance_window": maintenance_window,
            "state_type": state_type,
            "degraded": degraded,
            "failed_attempts": failed_attempts,
            "max_check_attempts": max_check_attempts,
            "parent_ip": parent_ip,
            "parent_name": parent_name,
            "parent_status": parent_status,
            "unreachable_dependency": unreachable_dependency,
            "monitor_type": poll.get("monitor_type"),
            "last_poll": _safe_iso(poll.get("last_poll") or poll.get("updated_at") or poll.get("last_poll_at")),
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
        "data_sources_status": sources_status,
    }


@router.get("/devices/by-ip/{device_ip}/info-card")
async def get_info_card(device_ip: str, client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Scheda anagrafica unificata del dispositivo (modello/serial/firmware/lifecycle/location).
    Aggrega device_poll_status + managed_devices + cmdb_assets + lifecycle_records + ilo_status.

    v2026-06 FIX multi-tenant: client_id (query param) filtra ogni sorgente per
    evitare leak cross-tenant su IP privati condivisi tra clienti (es. 192.168.1.x).
    """
    def _q(base: dict) -> dict:
        return {**base, "client_id": client_id} if client_id else base
    # Check that device exists somewhere (nello scope del client se fornito)
    exists = (
        await db.device_poll_status.count_documents(_q({"device_ip": device_ip})) > 0
        or await db.managed_devices.count_documents(_q({"ip": device_ip})) > 0
        or await db.cmdb_assets.count_documents(_q({"ip_address": device_ip})) > 0
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Device not found in any source")
    return await build_info_card(device_ip, client_id=client_id)


@router.post("/devices/info-card/parse-sys-descr")
async def parse_sys_descr_debug(payload: dict, current_user: dict = Depends(get_current_user)):
    """Debug endpoint: prova il parser sys_descr su una stringa arbitraria."""
    sd = (payload or {}).get("sys_descr", "")
    return {"input": sd, "parsed": parse_sys_descr(sd)}


@router.post("/devices/by-ip/{device_ip}/rename")
async def rename_device_by_ip(
    device_ip: str,
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Rinomina manualmente un dispositivo per IP, propagando il nuovo nome in
    TUTTE le collezioni e bloccando il classifier dal sovrascrivere la scelta
    al prossimo poll.

    Body: {"name": "Nuovo nome leggibile"}

    Effetti (atomici per quanto possibile, cascade best-effort):
      - managed_devices: name, device_name, name_user_locked=True, _by, _at
      - devices: name + name_user_locked (se record presente)
      - device_poll_status: device_name (per coerenza display backend)
      - best_display_name() rispetta SEMPRE name_user_locked, quindi il nuovo
        nome sara' usato in:
          * Panoramica (raggruppamento)
          * Tab Dispositivi
          * DeviceInfoCard
          * Alerts (display)
          * Vulnerability
          * Topology
      - Audit log completo

    v2026-02-14: richiesto dall'utente "voglio scrivere io il nome del device
    e averlo ovunque" — i firewall Zyxel ritornano sysDescr brutto
    ("Hardware Manufacturer/Zyxel Communications Corporation") e l'admin
    vuole forzare un display name leggibile come "USGFlex 100H".
    """
    new_name = (payload.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name e' obbligatorio")
    if len(new_name) > 200:
        raise HTTPException(status_code=400, detail="name troppo lungo (max 200 char)")

    # v2026-02-14: scope esplicito per client_id quando piu' tenant hanno
    # lo stesso IP (192.168.x.x, 10.0.x.x sono comuni). Senza scope, il rename
    # potrebbe aggiornare il device del client sbagliato. Accettiamo client_id
    # opzionale dal body per safety.
    explicit_client_id = (payload.get("client_id") or "").strip() or None

    # Verifica che il device esista almeno in una collezione
    exists_in = []
    md_query = {"ip": device_ip}
    if explicit_client_id:
        md_query["client_id"] = explicit_client_id
    md = await db.managed_devices.find_one(md_query, {"_id": 0, "id": 1, "name": 1, "client_id": 1})

    # Se piu' device matchano (multi-tenant), seleziona quello del client_id
    # esplicito; altrimenti se ne esiste piu' di uno → errore.
    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents({"ip": device_ip})
        if cnt > 1:
            raise HTTPException(
                status_code=409,
                detail=f"IP {device_ip} appartiene a {cnt} client diversi. Includi client_id nel body per disambiguare.",
            )

    if md:
        exists_in.append("managed_devices")
    dv_query = {"ip_address": device_ip}
    if explicit_client_id:
        dv_query["client_id"] = explicit_client_id
    dv = await db.devices.find_one(dv_query, {"_id": 0, "id": 1, "name": 1, "client_id": 1})
    if dv:
        exists_in.append("devices")
    ps_query = {"device_ip": device_ip}
    if explicit_client_id:
        ps_query["client_id"] = explicit_client_id
    ps = await db.device_poll_status.find_one(ps_query, {"_id": 0, "device_name": 1, "client_id": 1})
    if ps:
        exists_in.append("device_poll_status")

    if not exists_in:
        raise HTTPException(
            status_code=404,
            detail=f"Device {device_ip} non trovato in alcuna collezione",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    # 1. managed_devices: crea se manca, altrimenti update
    lock_fields = {
        "name": new_name,
        "device_name": new_name,
        "name_locked": True,           # legacy key letta da display_name.py
        "name_user_locked": True,      # nuovo key (allineato a device_type_user_locked)
        "name_user_locked_by": user_email,
        "name_user_locked_at": now_iso,
    }
    old_name = None
    client_id = None
    if md:
        old_name = md.get("name")
        client_id = md.get("client_id")
        await db.managed_devices.update_one(
            {"ip": device_ip, "client_id": client_id},
            {"$set": lock_fields},
        )
    else:
        # Crea entry ghost in managed_devices cosi' il lock sia rispettato
        from uuid import uuid4
        client_id = explicit_client_id or (ps or {}).get("client_id") or (dv or {}).get("client_id")
        if client_id:
            await db.managed_devices.insert_one({
                "id": str(uuid4()),
                "client_id": client_id,
                "ip": device_ip,
                "source": "user_rename",
                "created_at": now_iso,
                **lock_fields,
            })
            exists_in.append("managed_devices(created)")

    # 2. devices (vecchia collezione, mantenuta per backwards compat)
    if dv:
        if old_name is None:
            old_name = dv.get("name")
        dv_filter = {"ip_address": device_ip}
        if client_id:
            dv_filter["client_id"] = client_id
        await db.devices.update_one(
            dv_filter,
            {"$set": {
                "name": new_name,
                "name_locked": True,
                "name_user_locked": True,
                "updated_at": now_iso,
            }},
        )

    # 3. device_poll_status: aggiorna solo device_name (no lock perche' poll
    # status e' rigenerato dal connector; il display name backend usa
    # best_display_name() che gia' preferisce managed_devices.name quando
    # name_user_locked=True). Inoltre il connector/device-report ora rispetta
    # name_locked e NON sovrascrive device_name al prossimo heartbeat.
    if ps:
        ps_filter = {"device_ip": device_ip}
        if client_id:
            ps_filter["client_id"] = client_id
        await db.device_poll_status.update_one(
            ps_filter,
            {"$set": {"device_name": new_name}},
        )

    # 4. Audit log
    try:
        await audit_logger.log(
            AuditAction.UPDATE_DEVICE,
            user_id=current_user["id"],
            user_email=user_email,
            ip_address=current_user.get("_request_ip"),
            resource_type="device",
            resource_id=device_ip,
            details={
                "action": "rename_by_ip",
                "device_ip": device_ip,
                "old_name": old_name,
                "new_name": new_name,
                "client_id": client_id,
                "collections_updated": exists_in,
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "device_ip": device_ip,
        "old_name": old_name,
        "new_name": new_name,
        "locked": True,
        "collections_updated": exists_in,
        "message": (
            f"Device rinominato in '{new_name}'. Il nuovo nome sara' visibile "
            "in Panoramica, Dispositivi, Alert e Topology dopo il refresh."
        ),
    }

# ==================== VITAL FLAG ENDPOINT ====================
# v2026-02-28: device "vitali" (mission-critical) vs "best-effort":
# - is_vital=True  → priorita' MAX, alert SEMPRE inviati (non silenziabili)
# - is_vital=False → device monitorato ma alert NON inviati di default
# - is_vital missing → backward compat, alert come prima (emit)
# Vedi alert_filter.is_device_silenced per la semantica completa.
# ============================================================
@router.post("/devices/by-ip/{device_ip}/vital")
async def set_device_vital(
    device_ip: str,
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Toggle del flag `is_vital` per un device.

    Body: {"is_vital": bool, "client_id"?: str, "reason"?: str}

    Effetti:
      - managed_devices.is_vital = bool
      - managed_devices.is_vital_set_by / _at = metadata audit
      - cache alert_filter invalidata immediatamente
      - audit log
    """
    from alert_filter import invalidate_silence_cache

    if "is_vital" not in (payload or {}):
        raise HTTPException(status_code=400, detail="is_vital (bool) e' obbligatorio")
    is_vital = bool(payload.get("is_vital"))
    explicit_client_id = (payload.get("client_id") or "").strip() or None
    reason = (payload.get("reason") or "").strip()[:200]

    md_query = {"ip": device_ip}
    if explicit_client_id:
        md_query["client_id"] = explicit_client_id

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents({"ip": device_ip})
        if cnt > 1:
            raise HTTPException(
                status_code=409,
                detail=f"IP {device_ip} appartiene a {cnt} client diversi. Includi client_id nel body per disambiguare.",
            )

    md = await db.managed_devices.find_one(md_query, {"_id": 0, "id": 1, "client_id": 1, "name": 1, "is_vital": 1})
    if not md:
        raise HTTPException(status_code=404, detail=f"Device {device_ip} non trovato in managed_devices")

    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    await db.managed_devices.update_one(
        md_query,
        {"$set": {
            "is_vital": is_vital,
            "is_vital_set_by": user_email,
            "is_vital_set_at": now_iso,
            "is_vital_reason": reason or None,
        }},
    )

    # Invalida cache immediatamente cosi' il prossimo alert riflette il nuovo stato
    invalidate_silence_cache(client_id=md.get("client_id"), device_ip=device_ip)

    # Audit
    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=md.get("id"),
            metadata={
                "action": "set_vital_by_ip",
                "device_ip": device_ip,
                "is_vital": is_vital,
                "previous_value": md.get("is_vital"),
                "client_id": md.get("client_id"),
                "device_name": md.get("name"),
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "device_ip": device_ip,
        "is_vital": is_vital,
        "previous_value": md.get("is_vital"),
        "message": (
            f"Device {'VITALE' if is_vital else 'best-effort (alert silenziati di default)'}: "
            f"{md.get('name') or device_ip}"
        ),
    }


@router.post("/devices/by-ip/{device_ip}/virtualization")
async def set_device_virtualization(
    device_ip: str,
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Imposta il "tipo macchina" del device (fisico / VM).

    Body: {
      "virtualization": "physical"|"hyperv"|"vmware"|"vm_generic"|"",
      "hyperv_vm_name"?: str,   # override nome VM per aggancio snapshot Hyper-V
      "hyperv_host_hint"?: str, # host Hyper-V (opzionale, informativo)
      "client_id"?: str
    }

    Le VM sono escluse dalla lista "server senza credenziali iLO". Per le VM
    Hyper-V, hyperv_vm_name permette l'aggancio allo snapshot anche se il nome
    VM (Get-VM) non coincide col nome/hostname del device.
    """
    from alert_filter import invalidate_silence_cache

    valid = {"", "physical", "hyperv", "vmware", "vm_generic"}
    virt = (payload or {}).get("virtualization")
    if virt is None or virt not in valid:
        raise HTTPException(status_code=400, detail=f"virtualization deve essere uno di {sorted(valid)}")
    vm_name = (payload.get("hyperv_vm_name") or "").strip()
    host_hint = (payload.get("hyperv_host_hint") or "").strip()
    explicit_client_id = (payload.get("client_id") or "").strip() or None

    md_query = {"ip": device_ip}
    if explicit_client_id:
        md_query["client_id"] = explicit_client_id

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents({"ip": device_ip})
        if cnt > 1:
            raise HTTPException(
                status_code=409,
                detail=f"IP {device_ip} appartiene a {cnt} client diversi. Includi client_id nel body per disambiguare.",
            )

    md = await db.managed_devices.find_one(
        md_query, {"_id": 0, "id": 1, "client_id": 1, "name": 1, "virtualization": 1}
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    if not md:
        # Device poll-only (es. server iLO/redfish presenti solo in
        # device_poll_status) senza doc in managed_devices → creiamo un doc
        # minimale via upsert, cosi' l'impostazione persiste ed e' leggibile
        # da ilo-health (esclusione) e gather_signals (aggancio Hyper-V).
        if not explicit_client_id:
            raise HTTPException(
                status_code=400,
                detail=f"Device {device_ip} non e' in managed_devices: includi client_id nel body per poterlo classificare.",
            )
        from uuid import uuid4
        md = {"id": str(uuid4()), "client_id": explicit_client_id, "name": device_ip, "virtualization": ""}

    await db.managed_devices.update_one(
        md_query,
        {
            "$set": {
                "virtualization": virt,
                "hyperv_vm_name": vm_name,
                "hyperv_host_hint": host_hint,
                "virtualization_set_by": user_email,
                "virtualization_set_at": now_iso,
            },
            "$setOnInsert": {
                "id": md["id"],
                "name": md.get("name") or device_ip,
                "created_at": now_iso,
                "source": "poll",
                "device_type": "",
            },
        },
        upsert=True,
    )

    invalidate_silence_cache(client_id=md.get("client_id"), device_ip=device_ip)

    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=md.get("id"),
            metadata={
                "action": "set_virtualization",
                "device_ip": device_ip,
                "virtualization": virt,
                "hyperv_vm_name": vm_name,
                "previous_value": md.get("virtualization"),
                "client_id": md.get("client_id"),
                "device_name": md.get("name"),
            },
            request=request,
        )
    except Exception:
        pass

    is_vm = virt in ("hyperv", "vmware", "vm_generic")
    return {
        "ok": True,
        "device_ip": device_ip,
        "virtualization": virt,
        "hyperv_vm_name": vm_name,
        "hyperv_host_hint": host_hint,
        "is_vm": is_vm,
        "message": (
            f"Tipo macchina impostato: {virt or 'non impostato'}"
            + (f" (VM: {vm_name})" if vm_name else "")
            + (" — esclusa dalla lista iLO." if is_vm else ".")
        ),
    }



@router.post("/devices/by-ip/{device_ip}/vm-alert")
async def set_device_vm_alert(
    device_ip: str,
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Toggle dell'alert opzionale "VM spenta inaspettatamente".

    Body: {"enabled": bool, "client_id"?: str}

    Quando ENABLED, se la VM risulta Off/Saved/Paused sull'host Hyper-V
    (spegnimento inatteso di una VM che deve restare sempre accesa) viene
    generato un alert CRITICO. Default False = comportamento storico (VM
    spenta = nessun alert, zero falsi positivi).
    """
    from alert_filter import invalidate_silence_cache

    if "enabled" not in (payload or {}):
        raise HTTPException(status_code=400, detail="enabled (bool) e' obbligatorio")
    enabled = bool(payload.get("enabled"))
    explicit_client_id = (payload.get("client_id") or "").strip() or None

    md_query = {"ip": device_ip}
    if explicit_client_id:
        md_query["client_id"] = explicit_client_id

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents({"ip": device_ip})
        if cnt > 1:
            raise HTTPException(
                status_code=409,
                detail=f"IP {device_ip} appartiene a {cnt} client diversi. Includi client_id nel body per disambiguare.",
            )

    md = await db.managed_devices.find_one(
        md_query, {"_id": 0, "id": 1, "client_id": 1, "name": 1, "hyperv_alert_on_off": 1}
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    if not md:
        # Device poll-only (iLO/redfish in device_poll_status) senza doc in
        # managed_devices → upsert di un doc minimale, cosi' l'impostazione persiste.
        if not explicit_client_id:
            raise HTTPException(
                status_code=400,
                detail=f"Device {device_ip} non e' in managed_devices: includi client_id nel body.",
            )
        from uuid import uuid4
        md = {"id": str(uuid4()), "client_id": explicit_client_id, "name": device_ip}

    await db.managed_devices.update_one(
        md_query,
        {
            "$set": {
                "hyperv_alert_on_off": enabled,
                "hyperv_alert_on_off_set_by": user_email,
                "hyperv_alert_on_off_set_at": now_iso,
            },
            "$setOnInsert": {
                "id": md["id"],
                "name": md.get("name") or device_ip,
                "created_at": now_iso,
                "source": "poll",
                "device_type": "",
            },
        },
        upsert=True,
    )

    invalidate_silence_cache(client_id=md.get("client_id"), device_ip=device_ip)

    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=md.get("id"),
            metadata={
                "action": "set_vm_alert_on_off",
                "device_ip": device_ip,
                "enabled": enabled,
                "previous_value": md.get("hyperv_alert_on_off"),
                "client_id": md.get("client_id"),
                "device_name": md.get("name"),
            },
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "device_ip": device_ip,
        "hyperv_alert_on_off": enabled,
        "previous_value": md.get("hyperv_alert_on_off"),
        "message": (
            f"Alert 'VM spenta inaspettatamente' {'ATTIVATO' if enabled else 'DISATTIVATO'}: "
            f"{md.get('name') or device_ip}"
        ),
    }



@router.post("/devices/bulk-vital")
async def set_devices_vital_bulk(
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Marca/rimuove in blocco il flag `is_vital` su piu' device.

    Body: {"ips": [str, ...], "is_vital": bool, "client_id": str, "reason"?: str}

    `client_id` e' obbligatorio: la selezione multipla avviene sempre nel
    contesto di un cliente, quindi evitiamo ambiguita' cross-tenant.
    """
    from alert_filter import invalidate_silence_cache

    ips = payload.get("ips")
    if not isinstance(ips, list) or not ips:
        raise HTTPException(status_code=400, detail="ips (lista non vuota) e' obbligatorio")
    if "is_vital" not in (payload or {}):
        raise HTTPException(status_code=400, detail="is_vital (bool) e' obbligatorio")
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id e' obbligatorio per l'azione multipla")
    is_vital = bool(payload.get("is_vital"))
    reason = (payload.get("reason") or "").strip()[:200]
    # Normalizza + dedup gli IP
    ip_list = list({str(i).strip() for i in ips if str(i).strip()})

    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    res = await db.managed_devices.update_many(
        {"client_id": client_id, "ip": {"$in": ip_list}},
        {"$set": {
            "is_vital": is_vital,
            "is_vital_set_by": user_email,
            "is_vital_set_at": now_iso,
            "is_vital_reason": reason or None,
        }},
    )

    # v2026-07 FIX: i device visti solo da scanner/connector (device_poll_status)
    # non hanno ancora una riga in managed_devices → update_many non li tocca e
    # la marcatura "vitale" non persisteva ("selezionati ma non succede nulla").
    # Qui li PROMUOVIAMO (upsert) creando la riga managed_devices, cosi' appaiono
    # subito nel tab Dispositivi Vitali.
    import uuid as _uuid
    promoted = 0
    if is_vital:
        existing_ips = set(await db.managed_devices.distinct(
            "ip", {"client_id": client_id, "ip": {"$in": ip_list}}))
        for ip in [x for x in ip_list if x not in existing_ips]:
            src = await db.device_poll_status.find_one(
                {"client_id": client_id, "device_ip": ip},
                {"_id": 0, "device_name": 1, "device_class": 1, "mac": 1}) or {}
            if not src:
                src = await db.discovered_endpoints.find_one(
                    {"client_id": client_id, "ip": ip}, {"_id": 0}) or {}
            name = src.get("device_name") or src.get("hostname") or src.get("name") or ip
            dtype = src.get("device_class") or src.get("device_type") or "generic"
            r = await db.managed_devices.update_one(
                {"client_id": client_id, "ip": ip},
                {"$set": {
                    "is_vital": True, "is_vital_set_by": user_email,
                    "is_vital_set_at": now_iso, "is_vital_reason": reason or "promoted-vital"},
                 "$setOnInsert": {
                    "id": str(_uuid.uuid4()), "client_id": client_id, "ip": ip,
                    "name": name, "device_name": name, "device_type": dtype,
                    "mac": src.get("mac") or "", "source": "promoted-scan",
                    "created_at": now_iso}},
                upsert=True)
            if r.upserted_id is not None:
                promoted += 1

    # Invalida la cache silence per ogni IP toccato
    for ip in ip_list:
        invalidate_silence_cache(client_id=client_id, device_ip=ip)

    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=None,
            metadata={
                "action": "set_vital_bulk",
                "client_id": client_id,
                "ips": ip_list,
                "is_vital": is_vital,
                "matched": res.matched_count,
                "modified": res.modified_count,
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "client_id": client_id,
        "is_vital": is_vital,
        "requested": len(ip_list),
        "matched": res.matched_count,
        "modified": res.modified_count + promoted,
        "promoted": promoted,
        "message": (
            f"{res.modified_count + promoted} dispositivi {'marcati VITALI' if is_vital else 'rimossi dai vitali'}"
            + (f" ({promoted} promossi dallo scanner)" if promoted else "")
        ),
    }


@router.post("/clients/{client_id}/devices/reset-vital")
async def reset_devices_vital(
    client_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Azzera TUTTI i flag `is_vital` dei device di un cliente → il tab
    'Dispositivi Vitali' riparte da zero. Rimuove anche lo stato di tracking
    offline dei vitali (vital_offline_state) per quel cliente."""
    from alert_filter import invalidate_silence_cache

    client_id = (client_id or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id e' obbligatorio")
    user_email = current_user.get("email")

    # IP toccati (per invalidare la cache silence)
    touched_ips = await db.managed_devices.distinct(
        "ip", {"client_id": client_id, "is_vital": {"$exists": True}})

    res = await db.managed_devices.update_many(
        {"client_id": client_id, "is_vital": {"$exists": True}},
        {"$unset": {
            "is_vital": "", "is_vital_reason": "",
            "is_vital_set_by": "", "is_vital_set_at": "",
        }},
    )
    state_cleared = await db.vital_offline_state.delete_many({"client_id": client_id})

    for ip in touched_ips:
        if ip:
            invalidate_silence_cache(client_id=client_id, device_ip=ip)

    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=None,
            metadata={"action": "reset_vital", "client_id": client_id,
                      "cleared": res.modified_count},
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "client_id": client_id,
        "cleared": res.modified_count,
        "tracking_cleared": state_cleared.deleted_count,
        "message": f"{res.modified_count} dispositivi azzerati: il tab Dispositivi Vitali riparte da zero.",
    }



@router.post("/devices/bulk-silence")
async def set_devices_silence_bulk(
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Silenzia/riattiva in blocco gli alert di piu' device.

    Body: {"ips": [str, ...], "silenced": bool, "client_id": str, "reason"?: str}

    Semantica identica al toggle singolo (connector.update_device_silence):
    quando `silenced=True` nessun nuovo alert viene emesso per il device
    (gating in alert_filter.should_emit_alert). I device marcati VITALI
    ignorano comunque il silence (override in alert_filter). Gli alert gia'
    esistenti NON vengono toccati.
    """
    from alert_filter import invalidate_silence_cache

    ips = payload.get("ips")
    if not isinstance(ips, list) or not ips:
        raise HTTPException(status_code=400, detail="ips (lista non vuota) e' obbligatorio")
    if "silenced" not in (payload or {}):
        raise HTTPException(status_code=400, detail="silenced (bool) e' obbligatorio")
    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id e' obbligatorio per l'azione multipla")
    silenced = bool(payload.get("silenced"))
    reason = (payload.get("reason") or "").strip()[:200]
    ip_list = list({str(i).strip() for i in ips if str(i).strip()})

    now_iso = datetime.now(timezone.utc).isoformat()
    user_email = current_user.get("email")

    res = await db.managed_devices.update_many(
        {"client_id": client_id, "ip": {"$in": ip_list}},
        {"$set": {
            "alerts_silenced": silenced,
            "alerts_silenced_updated_at": now_iso,
            "alerts_silenced_reason": reason if silenced else "",
            "alerts_silenced_by": user_email if silenced else "",
        }},
    )

    for ip in ip_list:
        invalidate_silence_cache(client_id=client_id, device_ip=ip)

    try:
        await audit_logger.log(
            user_email=user_email,
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=None,
            metadata={
                "action": "set_silence_bulk",
                "client_id": client_id,
                "ips": ip_list,
                "alerts_silenced": silenced,
                "matched": res.matched_count,
                "modified": res.modified_count,
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "client_id": client_id,
        "alerts_silenced": silenced,
        "requested": len(ip_list),
        "matched": res.matched_count,
        "modified": res.modified_count,
        "message": (
            f"{res.modified_count} dispositivi {'silenziati' if silenced else 'riattivati'}"
        ),
    }
