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

from database import db
from deps import get_current_user, audit_logger
from audit import AuditAction
from display_name import best_display_name

router = APIRouter(prefix="/api", tags=["device-info-card"])


def _ip_match(device_ip: str) -> dict:
    """Match managed_devices sia sul campo canonico `ip` che sull'alias legacy
    `ip_address`.

    Alcuni documenti storici salvano l'IP SOLO in `ip_address` (mai in `ip`).
    Senza questo OR le update by-ip con `{"ip": device_ip}` non trovavano il
    doc e la upsert creava un DUPLICATO → l'impostazione (es. `virtualization`)
    veniva scritta su un doc fantasma e la UI continuava a leggere il vecchio
    documento vuoto ("salva ma me lo richiede ogni volta").
    """
    return {"$or": [{"ip": device_ip}, {"ip_address": device_ip}]}


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


def _scalar_num(d):
    """Estrae un valore scalare numerico da uno scalare o da un dict {idx: val},
    SENZA il clamp <1000 di _max_valid_number (per contatori/KB grandi: sessioni, memoria)."""
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, (int, float)):
                return float(v)
        return None
    if isinstance(d, (int, float)):
        return float(d)
    return None


def _ucd_mem_pct(vm: dict):
    """Memoria% da UCD-SNMP-MIB (Zyxel uOS FLEX H):
    (memTotalReal - memAvailReal - memBuffer - memCached) / memTotalReal * 100."""
    total = _scalar_num(vm.get("memTotalReal"))
    avail = _scalar_num(vm.get("memAvailReal"))
    if not total or total <= 0 or avail is None:
        return None
    buff = _scalar_num(vm.get("memBuffer")) or 0.0
    cach = _scalar_num(vm.get("memCached")) or 0.0
    used = total - avail - buff - cach
    if used < 0:
        used = total - avail
    pct = (used / total) * 100.0
    if pct < 0 or pct > 100:
        return None
    return pct


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
    if mem is None:
        # Zyxel USG FLEX H (uOS): la mem% diretta puo' essere vuota → calcolo UCD-SNMP.
        mem = _ucd_mem_pct(vm)
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


async def find_physical_uplinks(client_id: Optional[str], device_ip: str,
                                device_mac: Optional[str]) -> list:
    """Incrocia il MAC del device con la MAC-table (FDB) degli ALTRI switch per
    ricostruire il collegamento fisico: se il MAC di questo device compare sulla
    porta X di un altro switch, quel device e' (direttamente o via chain)
    raggiungibile da quella porta. Euristica: una porta con pochi MAC (<=2) e'
    quasi certamente un link punto-punto diretto; molti MAC = trunk/uplink verso
    il resto della rete. Ritorna la lista ordinata (link piu' probabile prima)."""
    if not device_mac:
        return []
    mac = device_mac.upper().replace("-", ":").strip()
    if len(mac.replace(":", "")) != 12:
        return []
    base = {"client_id": client_id} if client_id else {}
    q = {**base, "mac": mac, "source": "agent_fdb",
         "switch_ip": {"$nin": ["", None, device_ip]}}
    entries = await db.discovered_endpoints.find(
        q, {"_id": 0, "switch_ip": 1, "port": 1, "vlan": 1}).to_list(50)

    def _hex12(v):
        s = str(v or "").strip()
        if s.lower().startswith("hex:"):
            s = s[4:]
        if s.lower().startswith("0x"):
            s = s[2:]
        h = re.sub(r"[^0-9a-fA-F]", "", s).lower()
        return h if len(h) == 12 else ""

    mac_hex = _hex12(mac)
    results = []
    seen = set()
    for e in entries:
        sw = e.get("switch_ip")
        port = e.get("port")
        if not sw or not port or (sw, port) in seen:
            continue
        seen.add((sw, port))
        macs_on_port = await db.discovered_endpoints.count_documents(
            {**base, "switch_ip": sw, "port": port, "source": "agent_fdb"})
        sp = await db.switch_ports.find_one(
            {**base, "local_ip": sw, "idx": port}, {"_id": 0, "name": 1})
        nb = await db.managed_devices.find_one(
            {**base, "ip": sw}, {"_id": 0, "hostname": 1, "name": 1, "device_name": 1})
        # Doppia evidenza LLDP: lo switch vicino (sw) ha un vicino LLDP il cui
        # chassis-id coincide col MAC del device? Allora il link e' confermato
        # (LLDP + MAC-table concordano) -> verified=100%.
        verified = False
        lldp_local_port = None
        lldp_remote_port = None
        async for ld in db.lldp_neighbors.find(
            {**base, "local_ip": sw},
            {"_id": 0, "remote_chassis_id": 1, "local_port_id": 1,
             "local_port_desc": 1, "remote_port_id": 1, "remote_sys_name": 1}):
            if mac_hex and _hex12(ld.get("remote_chassis_id")) == mac_hex:
                verified = True
                lldp_local_port = ld.get("local_port_desc") or ld.get("local_port_id")
                lldp_remote_port = ld.get("remote_port_id")
                break
        results.append({
            "neighbor_ip": sw,
            "neighbor_name": (nb or {}).get("hostname") or (nb or {}).get("name")
                             or (nb or {}).get("device_name") or sw,
            "port": port,
            "port_name": (sp or {}).get("name"),
            "vlan": e.get("vlan") or None,
            "macs_on_port": macs_on_port,
            "direct": macs_on_port <= 2,
            "verified": verified,
            "lldp_local_port": lldp_local_port,
            "lldp_remote_port": lldp_remote_port,
        })
    # Ordina: prima i VERIFICATI, poi per pochi MAC (link piu' probabile)
    results.sort(key=lambda r: (not r["verified"], r["macs_on_port"]))
    return results



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
    managed = await db.managed_devices.find_one(_q(_ip_match(device_ip)), {"_id": 0}) or {}
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
    # Fallback: MAC scoperto dall'agent v4 (scan ARP/mDNS) e salvato in
    # discovered_endpoints con chiave (client_id, ip). Copre gli switch/host L3
    # raggiungibili in SNMP il cui MAC non e' esposto via SNMP ma e' visibile
    # nella tabella ARP dell'agent del segmento (caso HPE Comware su IP proprio).
    if not primary_mac:
        ep = await db.discovered_endpoints.find_one(
            _q({"ip": device_ip, "mac": {"$exists": True, "$nin": [None, ""]}}),
            {"_id": 0, "mac": 1, "last_seen_subnet": 1, "last_seen_via": 1},
            sort=[("last_seen_at", -1)],
        )
        if ep and ep.get("mac"):
            primary_mac = ep["mac"]
            mac_source = "arp-scan"
            arp_source_ip = ep.get("last_seen_subnet") or ep.get("last_seen_via")
    # Fallback finale: mappa IP->MAC dello scan di rete del cliente
    if not primary_mac:
        nd = await db.network_discovery.find_one(
            _q({}), {"_id": 0, "device_macs": 1}, sort=[("scanned_at", -1)])
        for dm in (nd or {}).get("device_macs", []) or []:
            if isinstance(dm, dict) and dm.get("ip") == device_ip:
                _m = dm.get("macs") or dm.get("mac")
                _m = _m[0] if isinstance(_m, list) and _m else _m
                if _m:
                    primary_mac = _m
                    mac_source = "net-scan"
                break

    device_type = _first_not_none(
        poll.get("device_class"),
        managed.get("device_type"),
        cmdb.get("device_type"),
        (profile_doc or {}).get("family"),
    )

    # Topologia fisica: incrocia il MAC del device con la FDB degli altri switch
    physical_links = await find_physical_uplinks(client_id, device_ip, primary_mac)

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
        "physical_links": physical_links,
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
            "firewall_sessions": fw_data.get("active_sessions") if fw_data.get("active_sessions") is not None else (
                int(_ss) if (_ss := _scalar_num(vm.get("zyFlexHSessions") or vm.get("zyActiveSessions"))) is not None else None
            ),
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
        or await db.managed_devices.count_documents(_q(_ip_match(device_ip))) > 0
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
    md_query = _ip_match(device_ip)
    if explicit_client_id:
        md_query = {**md_query, "client_id": explicit_client_id}
    md = await db.managed_devices.find_one(md_query, {"_id": 0, "id": 1, "name": 1, "client_id": 1})

    # Se piu' device matchano (multi-tenant), seleziona quello del client_id
    # esplicito; altrimenti se ne esiste piu' di uno → errore.
    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents(_ip_match(device_ip))
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
            {"id": md["id"]},
            {"$set": {**lock_fields, "ip": device_ip}},
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

    md_query = _ip_match(device_ip)
    if explicit_client_id:
        md_query = {**md_query, "client_id": explicit_client_id}

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents(_ip_match(device_ip))
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
        {"id": md["id"]},
        {"$set": {
            "is_vital": is_vital,
            "is_vital_set_by": user_email,
            "is_vital_set_at": now_iso,
            "is_vital_reason": reason or None,
            "ip": device_ip,  # normalizza il campo chiave (docs legacy con solo ip_address)
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

    md_query = _ip_match(device_ip)
    if explicit_client_id:
        md_query = {**md_query, "client_id": explicit_client_id}

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents(_ip_match(device_ip))
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

    set_fields = {
        "virtualization": virt,
        "hyperv_vm_name": vm_name,
        "hyperv_host_hint": host_hint,
        "virtualization_set_by": user_email,
        "virtualization_set_at": now_iso,
        "ip": device_ip,  # normalizza il campo chiave (docs legacy con solo ip_address)
        # Lock manuale: se l'admin imposta un valore (anche "physical"),
        # l'auto-aggancio Hyper-V non deve piu' sovrascriverlo. Se invece
        # azzera (""), sblocchiamo per consentire il rilevamento automatico.
        "virtualization_user_locked": bool(virt),
        "virtualization_auto_matched": False,
    }

    if md:
        # v2026-08 FIX DATA-LOSS: prima eliminavamo i doc legacy duplicati SENZA
        # fondere i loro campi → si perdevano impostazioni presenti solo sul
        # legacy (es. snmp_community, is_vital). Ora FONDIAMO i campi legacy
        # mancanti nel canonico, poi eliminiamo i duplicati.
        from managed_device_dedup import merge_field_dicts
        siblings = await db.managed_devices.find(md_query, {"_id": 0}).to_list(50)
        canonical = next((d for d in siblings if d.get("ip") == device_ip), None) or siblings[0]
        merged_fill: dict = {}
        canon_view = {**canonical, **set_fields}
        for sib in siblings:
            if sib.get("id") == canonical.get("id"):
                continue
            for k, v in merge_field_dicts({**canon_view, **merged_fill}, sib).items():
                merged_fill[k] = v
        dup_ids = [d["id"] for d in siblings if d.get("id") and d["id"] != canonical["id"]]
        if dup_ids:
            await db.managed_devices.delete_many({"id": {"$in": dup_ids}})
        await db.managed_devices.update_one({"id": canonical["id"]}, {"$set": {**merged_fill, **set_fields}})
        md = {**md, "id": canonical["id"]}
    else:
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
            {"ip": device_ip, "client_id": explicit_client_id},
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "id": md["id"],
                    "name": device_ip,
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

    md_query = _ip_match(device_ip)
    if explicit_client_id:
        md_query = {**md_query, "client_id": explicit_client_id}

    if not explicit_client_id:
        cnt = await db.managed_devices.count_documents(_ip_match(device_ip))
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

    set_fields = {
        "hyperv_alert_on_off": enabled,
        "hyperv_alert_on_off_set_by": user_email,
        "hyperv_alert_on_off_set_at": now_iso,
        "ip": device_ip,  # normalizza il campo chiave (docs legacy con solo ip_address)
    }

    if md:
        # v2026-08 FIX DATA-LOSS: fondi i campi legacy mancanti nel canonico
        # PRIMA di eliminare i duplicati (vedi set_device_virtualization).
        from managed_device_dedup import merge_field_dicts
        siblings = await db.managed_devices.find(md_query, {"_id": 0}).to_list(50)
        canonical = next((d for d in siblings if d.get("ip") == device_ip), None) or siblings[0]
        merged_fill: dict = {}
        canon_view = {**canonical, **set_fields}
        for sib in siblings:
            if sib.get("id") == canonical.get("id"):
                continue
            for k, v in merge_field_dicts({**canon_view, **merged_fill}, sib).items():
                merged_fill[k] = v
        dup_ids = [d["id"] for d in siblings if d.get("id") and d["id"] != canonical["id"]]
        if dup_ids:
            await db.managed_devices.delete_many({"id": {"$in": dup_ids}})
        await db.managed_devices.update_one({"id": canonical["id"]}, {"$set": {**merged_fill, **set_fields}})
        md = {**md, "id": canonical["id"]}
    else:
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
            {"ip": device_ip, "client_id": explicit_client_id},
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "id": md["id"],
                    "name": device_ip,
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


@router.post("/devices/bulk-apply-settings")
async def bulk_apply_device_settings(
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Applica in blocco i parametri del pannello "Modifica Dispositivo" a piu'
    dispositivi selezionati (azione multipla nella tab Dispositivi Vitali).

    Body: {
      "client_id": str,
      "ips": [str, ...],
      "apply": {  # SOLO i campi presenti vengono scritti
         "virtualization"?: "physical"|"hyperv"|"vmware"|"vm_generic"|"",
         "vm_alert"?: bool,          # hyperv_alert_on_off
         "silenced"?: bool, "silence_reason"?: str,
         "monitor_type"?: "ping"|"snmp"|"http"|"snmp+http",
         "snmp_version"?: "v1"|"v2c"|"v3",
         "community"?: str
      }
    }
    Applica a TUTTI gli IP selezionati senza distinzione di tipo device.
    """
    from alert_filter import invalidate_silence_cache

    client_id = (payload or {}).get("client_id")
    ips = payload.get("ips") or []
    apply = payload.get("apply") or {}
    if not client_id or not isinstance(ips, list) or not ips:
        raise HTTPException(status_code=400, detail="client_id e ips[] sono obbligatori")
    if not isinstance(apply, dict) or not apply:
        raise HTTPException(status_code=400, detail="apply{} vuoto: nessun parametro da applicare")

    set_fields: Dict[str, Any] = {}
    applied: List[str] = []

    if "virtualization" in apply:
        valid = {"", "physical", "hyperv", "vmware", "vm_generic"}
        virt = apply.get("virtualization")
        if virt not in valid:
            raise HTTPException(status_code=400, detail=f"virtualization deve essere uno di {sorted(valid)}")
        set_fields["virtualization"] = virt
        set_fields["virtualization_user_locked"] = bool(virt)
        set_fields["virtualization_auto_matched"] = False
        applied.append("tipo macchina")
        if "hyperv_vm_name" in apply:
            set_fields["hyperv_vm_name"] = (apply.get("hyperv_vm_name") or "").strip()
        if "hyperv_host_hint" in apply:
            set_fields["hyperv_host_hint"] = (apply.get("hyperv_host_hint") or "").strip()

    if "vm_alert" in apply:
        set_fields["hyperv_alert_on_off"] = bool(apply.get("vm_alert"))
        applied.append("alert VM spenta")

    if "silenced" in apply:
        set_fields["alerts_silenced"] = bool(apply.get("silenced"))
        set_fields["alerts_silenced_reason"] = (apply.get("silence_reason") or "").strip()
        applied.append("silenzia alert")

    if "monitor_type" in apply:
        mt = apply.get("monitor_type")
        if mt not in ("ping", "snmp", "http", "snmp+http"):
            raise HTTPException(status_code=400, detail="monitor_type non valido")
        set_fields["monitor_type"] = mt
        applied.append("metodo monitoraggio")

    if "snmp_version" in apply:
        if apply.get("snmp_version") not in ("v1", "v2c", "v3"):
            raise HTTPException(status_code=400, detail="snmp_version non valido")
        set_fields["snmp_version"] = apply.get("snmp_version")
        applied.append("versione SNMP")

    if "community" in apply:
        set_fields["snmp_community"] = apply.get("community") or ""
        set_fields["community"] = apply.get("community") or ""
        applied.append("community SNMP")

    # v4.30.3: Host/Nome VM applicabili anche SENZA cambiare il tipo macchina.
    # (Il "vm_only" a valle limita comunque l'update ai soli device gia' VM.)
    if "hyperv_host_hint" in apply and "hyperv_host_hint" not in set_fields:
        set_fields["hyperv_host_hint"] = (apply.get("hyperv_host_hint") or "").strip()
        applied.append("host Hyper-V")
    if "hyperv_vm_name" in apply and "hyperv_vm_name" not in set_fields:
        set_fields["hyperv_vm_name"] = (apply.get("hyperv_vm_name") or "").strip()
        applied.append("nome VM")

    if not set_fields:
        raise HTTPException(status_code=400, detail="Nessun campo valido da applicare")

    set_fields["bulk_settings_set_by"] = current_user.get("email")
    set_fields["bulk_settings_set_at"] = datetime.now(timezone.utc).isoformat()

    q = {"client_id": client_id, "$or": [{"ip": {"$in": ips}}, {"ip_address": {"$in": ips}}]}
    # v4.30.3: se vm_only, applica SOLO ai dispositivi gia' classificati come VM
    # (salta switch/stampanti/host fisici) — utile per host/nome VM e alert VM.
    if bool(payload.get("vm_only")):
        q["virtualization"] = {"$in": ["hyperv", "vmware", "vm_generic"]}
    res = await db.managed_devices.update_many(q, {"$set": set_fields})

    try:
        for ip in ips:
            invalidate_silence_cache(client_id=client_id, device_ip=ip)
    except Exception:
        pass

    try:
        await audit_logger.log(
            user_email=current_user.get("email"),
            action=AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.OTHER,
            resource_type="device",
            resource_id=None,
            metadata={"action": "bulk_apply_settings", "client_id": client_id,
                      "ips_count": len(ips), "applied": applied, "fields": list(set_fields.keys())},
            request=request,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "matched": res.matched_count,
        "modified": res.modified_count,
        "applied": applied,
        "message": f"{res.modified_count} dispositivi aggiornati ({', '.join(applied) or 'nessun parametro'})",
    }


# ==================== Preset impostazioni device (GLOBALI) ====================
# Profili riutilizzabili (es. "VM critica H-V", "Switch SNMP v2c") applicabili con
# un click dal modal "Applica impostazioni". Globali = validi per tutti i clienti.

@router.get("/device-setting-presets")
async def list_device_setting_presets(current_user: dict = Depends(get_current_user)):
    docs = await db.device_setting_presets.find({}, {"_id": 0}).sort("name", 1).to_list(length=200)
    return {"presets": docs}


@router.post("/device-setting-presets")
async def create_device_setting_preset(payload: dict, current_user: dict = Depends(get_current_user)):
    import uuid as _uuid
    name = (payload.get("name") or "").strip()
    apply = payload.get("apply") or {}
    if not name:
        raise HTTPException(status_code=400, detail="Nome preset obbligatorio")
    if not isinstance(apply, dict) or not apply:
        raise HTTPException(status_code=400, detail="Nessun parametro da salvare nel preset")
    doc = {
        "id": str(_uuid.uuid4()),
        "name": name,
        "apply": apply,
        "vm_only": bool(payload.get("vm_only")),
        "created_by": current_user.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # upsert per nome (evita duplicati): sovrascrive se esiste gia' lo stesso nome
    existing = await db.device_setting_presets.find_one({"name": name}, {"_id": 0, "id": 1})
    if existing:
        doc["id"] = existing["id"]
        await db.device_setting_presets.update_one({"id": doc["id"]}, {"$set": doc})
    else:
        await db.device_setting_presets.insert_one(dict(doc))
    return {"ok": True, "preset": doc}


@router.delete("/device-setting-presets/{preset_id}")
async def delete_device_setting_preset(preset_id: str, current_user: dict = Depends(get_current_user)):
    res = await db.device_setting_presets.delete_one({"id": preset_id})
    return {"ok": True, "deleted": res.deleted_count}


@router.post("/devices/normalize-ip-fields")
async def normalize_managed_device_ip_fields(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """One-shot idempotente: FONDE i documenti duplicati di `managed_devices`.

    Per lo stesso IP possono coesistere un doc canonico (`ip`) e uno o piu' doc
    legacy (solo `ip_address`). Le impostazioni (Tipo Macchina, device_type,
    SNMP, is_vital, silence) potevano finire su doc diversi e la lettura ne
    perdeva una parte. Questo unisce i duplicati in un unico doc canonico
    (nessuna impostazione persa) e allinea `ip_address` → `ip`.

    Sicuro da rilanciare piu' volte.
    """
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo admin")

    from managed_device_dedup import merge_duplicate_managed_devices
    res = await merge_duplicate_managed_devices(db)
    total = res.get("deleted_docs", 0) + res.get("promoted", 0)
    return {
        "ok": True,
        "normalized": total,
        "merged_groups": res.get("merged_groups", 0),
        "deleted_docs": res.get("deleted_docs", 0),
        "promoted": res.get("promoted", 0),
        "message": (
            f"{res.get('merged_groups', 0)} IP normalizzati "
            f"({res.get('deleted_docs', 0)} duplicati fusi, "
            f"{res.get('promoted', 0)} legacy promossi)."
            if total
            else "Nessun duplicato da fondere: DB gia' coerente."
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
