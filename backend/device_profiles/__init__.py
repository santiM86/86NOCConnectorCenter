"""Device Profile Library — auto-configuration for multi-vendor devices.

Each profile defines:
- `key`: stable identifier (e.g. "hp_procurve")
- `vendor`, `family`, `label`: human-readable metadata
- `fingerprint`: detection rules for automatic matching
    - `sysobjectid_prefixes`: list of OID prefixes (e.g. "1.3.6.1.4.1.11.2.3.7.11.")
    - `sysdescr_patterns`: list of regex patterns (case-insensitive) to match sysDescr
- `snmp`: default SNMP settings (port, version, community_suggestion, recommended_timeout)
- `web_console`: default port, scheme, path for Web Console V4
- `oids`: dict of useful OIDs {name: oid} for polling (CPU, memory, temp, uptime, disks, interfaces)
- `thresholds`: recommended thresholds for alerts
- `polling_interval_seconds`: recommended polling frequency

Profiles are hard-coded as the seed truth; they get inserted into `device_profiles`
Mongo collection on startup (upsert keyed by `key` with `seed_version`). Users can
override specific fields from UI; overrides are stored in the same document under
`overrides` key, so `effective = {**seed, **overrides}`.
"""
from __future__ import annotations
from typing import Any

# ruff: noqa: E501 — long strings are intentional in OID tables

SEED_VERSION = 8  # v2026-08: aggiunto profilo Hyper-V VM (Windows guest via SNMP HOST-RESOURCES)

# Common standard OIDs (usable as fallback for any SNMP device)
COMMON_OIDS = {
    "sysDescr":        "1.3.6.1.2.1.1.1.0",
    "sysObjectID":     "1.3.6.1.2.1.1.2.0",
    "sysUpTime":       "1.3.6.1.2.1.1.3.0",
    "sysContact":      "1.3.6.1.2.1.1.4.0",
    "sysName":         "1.3.6.1.2.1.1.5.0",
    "sysLocation":     "1.3.6.1.2.1.1.6.0",
    "ifNumber":        "1.3.6.1.2.1.2.1.0",
    "ifDescr":         "1.3.6.1.2.1.2.2.1.2",
    "ifOperStatus":    "1.3.6.1.2.1.2.2.1.8",
    "ifInOctets":      "1.3.6.1.2.1.2.2.1.10",
    "ifOutOctets":     "1.3.6.1.2.1.2.2.1.16",
}


# =========================================================================
# PROFILE DEFINITIONS
# =========================================================================

PROFILES: list[dict[str, Any]] = [
    # ---------------- HPE iLO — ProLiant Gen9/Gen10/Gen11 ----------------
    {
        "key": "hpe_ilo",
        "vendor": "HPE",
        "family": "server_oob",
        "label": "HPE iLO (ProLiant Gen9/10/11)",
        "description": "Server HPE ProLiant con iLO 4 (Gen9), iLO 5 (Gen10/10+) o iLO 6 (Gen11). Preferisce Redfish; SNMP via CPQHLTH-MIB come fallback se HP Agents installati sull'OS ospite.",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.232.",   # Compaq/HP enterprise tree (CPQ-MIBs)
                "1.3.6.1.4.1.11.5.7.", # iLO-specific entity
            ],
            "sysdescr_patterns": [
                r"integrated\s+lights[-\s]*out",
                r"ilo\s*[456]",
                r"proliant\s+(dl|ml|bl|xl|apollo)\d+\s+gen\d+",
                r"hp(e)?\s+proliant",
                r"cpqhost",
                r"cpqhlth",
            ],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {
            "port": 443, "scheme": "https", "path": "/",
            "notes": "iLO webui è SPA React (iLO 5+) con CSP strict — richiede Popup V4 per bypass iframe. Console KVM HTML5 integrata. Login default: Administrator/<serial-number-tag>."
        },
        "oids": {
            **COMMON_OIDS,
            # CPQSINFO-MIB — System info
            "cpqSiSysSerialNum":        "1.3.6.1.4.1.232.2.2.2.1.0",
            "cpqSiProductName":         "1.3.6.1.4.1.232.2.2.4.2.0",
            # CPQHLTH-MIB — Health aggregate
            "cpqHeMibCondition":        "1.3.6.1.4.1.232.6.1.3.0",      # 1=other, 2=ok, 3=degraded, 4=failed
            "cpqHeThermalSystemStatus": "1.3.6.1.4.1.232.6.2.6.5.0",
            "cpqHeThermalCpuStatus":    "1.3.6.1.4.1.232.6.2.6.4.0",
            "cpqHeThermalTempStatus":   "1.3.6.1.4.1.232.6.2.6.3.0",
            # Temperatures (table)
            "cpqHeTempTable":           "1.3.6.1.4.1.232.6.2.6.8.1",
            "cpqHeTempLocale":          "1.3.6.1.4.1.232.6.2.6.8.1.3",  # locale: 2=cpu,3=memory,5=system,etc
            "cpqHeTempCelsius":         "1.3.6.1.4.1.232.6.2.6.8.1.4",
            "cpqHeTempCondition":       "1.3.6.1.4.1.232.6.2.6.8.1.6",
            # Fans (table)
            "cpqHeFltTolFanTable":      "1.3.6.1.4.1.232.6.2.6.7.1",
            "cpqHeFltTolFanLocale":     "1.3.6.1.4.1.232.6.2.6.7.1.3",
            "cpqHeFltTolFanPresent":    "1.3.6.1.4.1.232.6.2.6.7.1.4",
            "cpqHeFltTolFanCondition":  "1.3.6.1.4.1.232.6.2.6.7.1.9",
            "cpqHeFltTolFanSpeed":      "1.3.6.1.4.1.232.6.2.6.7.1.12",
            # Power supplies (table)
            "cpqHeFltTolPowerSupplyStatus":    "1.3.6.1.4.1.232.6.2.9.3.1.4",
            "cpqHeFltTolPowerSupplyCondition": "1.3.6.1.4.1.232.6.2.9.3.1.5",
            "cpqHeFltTolPowerSupplyCapacity":  "1.3.6.1.4.1.232.6.2.9.3.1.7",
            # CMOS battery
            "cpqHeSysBatteryCondition": "1.3.6.1.4.1.232.6.2.17.2.1.4",
            # CPU
            "cpqSeCpuUnitTable":        "1.3.6.1.4.1.232.1.2.2.1",
            "cpqSeCpuStatus":           "1.3.6.1.4.1.232.1.2.2.1.1.6",
            "cpqSeCpuSpeed":            "1.3.6.1.4.1.232.1.2.2.1.1.4",
            # Memory
            "cpqHeResilientMemTotalMB": "1.3.6.1.4.1.232.6.2.14.4.0",
            "cpqHeResMemModuleTable":   "1.3.6.1.4.1.232.6.2.14.11.1",
            "cpqHeResMemModuleCondition": "1.3.6.1.4.1.232.6.2.14.11.1.9",
            # Smart Array (storage)
            "cpqDaCntlrTable":          "1.3.6.1.4.1.232.3.2.2.1",
            "cpqDaCntlrCondition":      "1.3.6.1.4.1.232.3.2.2.1.1.6",
            "cpqDaLogDrvTable":         "1.3.6.1.4.1.232.3.2.3.1",
            "cpqDaLogDrvStatus":        "1.3.6.1.4.1.232.3.2.3.1.1.4",      # 1=other,2=ok,3=failed,4=unconfigured,5=recovering,6=ready-for-rebuild,7=rebuilding,etc
            "cpqDaPhyDrvTable":         "1.3.6.1.4.1.232.3.2.5.1",
            "cpqDaPhyDrvStatus":        "1.3.6.1.4.1.232.3.2.5.1.1.6",
            "cpqDaPhyDrvSMARTStatus":   "1.3.6.1.4.1.232.3.2.5.1.1.57",     # 1=ok, 3=replaceDrive
            "cpqDaPhyDrvCurrentTemperature": "1.3.6.1.4.1.232.3.2.5.1.1.70",
        },
        "thresholds": {
            "cpu_warn_pct": 70, "cpu_crit_pct": 90,
            "mem_warn_pct": 80, "mem_crit_pct": 95,
            "inlet_temp_warn_c": 27, "inlet_temp_crit_c": 32,    # ASHRAE A1 tolleranze
            "cpu_temp_warn_c": 75, "cpu_temp_crit_c": 90,
            "fan_percent_warn": 70, "fan_percent_crit": 90,
            "disk_temp_warn_c": 45, "disk_temp_crit_c": 55,
            "psu_redundancy_required": True,
        },
        "polling_interval_seconds": 60,
        "capabilities": [
            "snmp_basic", "redfish_preferred", "hardware_oob",
            "kvm_console_html5", "virtual_media", "power_control",
            "firmware_inventory", "thermal_detail", "smart_array_status",
            "ilo_generation_detect", "ilo_federation",
        ],
        "api_endpoints": {
            # Redfish — common across iLO 4 (Gen9), iLO 5 (Gen10), iLO 6 (Gen11)
            "redfish_root":        "/redfish/v1/",
            "redfish_systems":     "/redfish/v1/Systems/1",
            "redfish_chassis":     "/redfish/v1/Chassis/1",
            "redfish_managers":    "/redfish/v1/Managers/1",
            "redfish_thermal":     "/redfish/v1/Chassis/1/Thermal",
            "redfish_power":       "/redfish/v1/Chassis/1/Power",
            "redfish_thermal_subsys":  "/redfish/v1/Chassis/1/ThermalSubsystem",  # iLO 5 Gen10+ schema
            "redfish_power_subsys":    "/redfish/v1/Chassis/1/PowerSubsystem",
            "redfish_storage":     "/redfish/v1/Systems/1/Storage",
            "redfish_memory":      "/redfish/v1/Systems/1/Memory",
            "redfish_network":     "/redfish/v1/Systems/1/EthernetInterfaces",
            "redfish_processors":  "/redfish/v1/Systems/1/Processors",
            "redfish_firmware":    "/redfish/v1/UpdateService/FirmwareInventory",
            "redfish_log_services":"/redfish/v1/Managers/1/LogServices",
            # iLO-specific extensions (Oem/Hpe)
            "ilo_hpe_security":    "/redfish/v1/Managers/1/SecurityService",
            "ilo_virtual_media":   "/redfish/v1/Managers/1/VirtualMedia",
            "ilo_power_action":    "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
        },
        "generations": {
            "gen9":  {"ilo_version": "iLO 4", "redfish_schema": "legacy", "ssl_min": "TLSv1.1", "notes": "Redfish parziale; preferire RIBCL o HPONCFG per Gen9 su operazioni complesse."},
            "gen10": {"ilo_version": "iLO 5", "redfish_schema": "modern", "ssl_min": "TLSv1.2", "notes": "Redfish completo, ThermalSubsystem disponibile, Federation group supportato."},
            "gen11": {"ilo_version": "iLO 6", "redfish_schema": "modern", "ssl_min": "TLSv1.3", "notes": "SPDM attestation, iLO Scale-out, migliori log security e HSM."},
        },
    },

    # ---------------- HPE Comware (ex-H3C) — 5130/5140/5500/5900/7500 ----------------
    {
        "key": "hpe_comware",
        "vendor": "HPE / H3C",
        "family": "switch",
        "label": "HPE Comware (5130/5140/5500/5900/7500)",
        "description": "Switch HPE Comware ex-H3C (5130 EI/HI/SI, 5140 EI, 5500, 5900, 7500) — MIB H3C/HH3C.",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.25506.",         # H3C enterprise (matrice principale OID device)
                "1.3.6.1.4.1.11.2.3.7.8.",    # HPE Comware via HP tree (Comware 5/altri)
                "1.3.6.1.4.1.11.2.3.7.11.",   # HPE FlexNetwork 5130/5140 (Comware 7) — PREFISSO UFFICIALE
            ],
            "sysdescr_patterns": [
                r"comware",
                r"h3c",
                r"hpe?\s*5130",
                r"hpe?\s*5140",
                r"hpe?\s*5500",
                r"hpe?\s*5900",
                r"hpe?\s*7500",
                r"3com.*switch",
            ],
            # Model lookup: dopo il match del profilo, mappa l'ultimo numero del sysObjectID
            # al modello specifico (HPE FlexNetwork tree .11.2.3.7.11.<X>)
            "model_by_oid_suffix": {
                "1.3.6.1.4.1.11.2.3.7.11.161": "HPE FlexNetwork 5130 EI",
                "1.3.6.1.4.1.11.2.3.7.11.162": "HPE FlexNetwork 5130 HI",
                "1.3.6.1.4.1.11.2.3.7.11.173": "HPE FlexNetwork 5140 EI",
            },
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "HPE Comware HTTPS 443 (HTTP 80 disabilitato di default). La webui è SPA — richiede popup V4 per bypass CSP/X-Frame. Auth: local-user 'admin' role network-admin."},
        "oids": {
            **COMMON_OIDS,
            # H3C/HH3C enterprise MIB (vale anche per HPE 5130/5140 anche se sysObjectID e` HP tree)
            "h3cEntityExtCpuUsage":   "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
            "h3cEntityExtMemUsage":   "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
            "h3cEntityExtTemperature":"1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
            "h3cFanState":            "1.3.6.1.4.1.25506.2.6.1.1.1.1.16",
            "h3cPowerState":          "1.3.6.1.4.1.25506.2.6.1.1.1.1.18",
            # MAC base dello switch (BRIDGE-MIB) — permette di leggere il MAC
            # anche quando l'agent NON e' sul segmento L2 (nessuna voce ARP).
            "dot1dBaseBridgeAddress": "1.3.6.1.2.1.17.1.1.0",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 55, "temp_crit_c": 70},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "port_traffic", "stack_status", "comware_cli_ssh", "https_webui"],
    },

    # ---------------- Xanto UPS (Serie 2017, scheda SNMP Megatec/NetAgent) ----------------
    {
        "key": "xanto_ups",
        "vendor": "Xanto (Riello Group)",
        "family": "ups",
        "label": "UPS Xanto Serie 2017 (NetAgent/Megatec)",
        "description": "UPS Xanto con scheda SNMP NetAgent/Megatec (Enterprise OID 3468). Legge lo stato vendor-specific via MIB 1.3.6.1.4.1.3468.* + battery/input/output via RFC 1628 UPS-MIB standard.",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.3468.",     # Megatec / NetAgent (schede SNMP Xanto, Tecnoware, alcune OEM italiane)
            ],
            "sysdescr_patterns": [r"xanto", r"ups.*xanto", r"netagent", r"megatec"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Scheda NetAgent espone WebUI HTTP 80 (alcune versioni firmware recenti supportano HTTPS 443). Login default: admin/admin. La WebUI permette gestione carichi, shutdown schedule, log eventi."},
        "oids": {
            **COMMON_OIDS,
            # Vendor-specific (Megatec/NetAgent enterprise MIB)
            "upsStatus":                   "1.3.6.1.4.1.3468.1.1.1.0",   # Stato generale UPS (specifico Xanto/Megatec)
            # RFC 1628 UPS-MIB — batteria
            "upsBatteryStatus":            "1.3.6.1.2.1.33.1.2.1.0",      # 1=unknown, 2=normal, 3=low, 4=depleted
            "upsSecondsOnBattery":         "1.3.6.1.2.1.33.1.2.2.0",      # s trascorsi in modalità batteria
            "upsEstimatedMinutesRemaining": "1.3.6.1.2.1.33.1.2.3.0",     # min autonomia stimata
            "upsEstimatedChargeRemaining": "1.3.6.1.2.1.33.1.2.4.0",      # % carica residua
            "upsBatteryVoltage":           "1.3.6.1.2.1.33.1.2.5.0",      # dV (decivolt)
            "upsBatteryTemperature":       "1.3.6.1.2.1.33.1.2.7.0",      # °C temperatura batterie
            # RFC 1628 UPS-MIB — input (fase 1)
            "upsInputLineBads":            "1.3.6.1.2.1.33.1.3.1.0",
            "upsInputVoltage":             "1.3.6.1.2.1.33.1.3.3.1.3.1",  # V tensione ingresso fase 1
            "upsInputFrequency":           "1.3.6.1.2.1.33.1.3.3.1.2.1",  # dHz frequenza ingresso fase 1
            # RFC 1628 UPS-MIB — output (fase 1)
            "upsOutputSource":             "1.3.6.1.2.1.33.1.4.1.0",      # 1=other, 2=none, 3=normal, 4=bypass, 5=battery, 6=booster, 7=reducer
            "upsOutputVoltage":            "1.3.6.1.2.1.33.1.4.4.1.2.1",  # V tensione uscita fase 1
            "upsOutputPercentLoad":        "1.3.6.1.2.1.33.1.4.4.1.5.1",  # % carico uscita fase 1
            # RFC 1628 UPS-MIB — identificazione (se presente)
            "upsIdentManufacturer":        "1.3.6.1.2.1.33.1.1.1.0",
            "upsIdentModel":               "1.3.6.1.2.1.33.1.1.2.0",
            "upsIdentUpsFirmware":         "1.3.6.1.2.1.33.1.1.3.0",
            "upsAlarmsPresent":            "1.3.6.1.2.1.33.1.6.1.0",
        },
        "thresholds": {
            "cpu_warn_pct": 70, "cpu_crit_pct": 90,
            "temp_warn_c": 40, "temp_crit_c": 50,           # Batterie UPS soffrono >50°C
            "battery_pct_warn": 30, "battery_pct_crit": 15, # Scarica batteria critica
            "runtime_min_warn": 15, "runtime_min_crit": 5,
            "load_pct_warn": 70, "load_pct_crit": 90,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "battery_monitoring", "input_voltage", "output_voltage", "rfc1628_ups_mib", "netagent_webui", "megatec_vendor_oid"],
    },

    # ---------------- Generic UPS (Riello, CyberPower, Eaton, Socomec) ----------------
    {
        "key": "generic_ups",
        "vendor": "Riello / CyberPower / Eaton",
        "family": "ups",
        "label": "UPS generico (RFC 1628 UPS-MIB)",
        "description": "UPS generici non-APC con RFC 1628 UPS-MIB standard (Riello enterprise, CyberPower, Eaton, Socomec, MGE). Per Xanto con scheda NetAgent usare il profilo dedicato xanto_ups.",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.3808.",    # CyberPower
                "1.3.6.1.4.1.534.",     # Eaton/Powerware
                "1.3.6.1.4.1.4555.",    # Riello (enterprise diretto, non NetAgent)
                "1.3.6.1.4.1.705.",     # MGE UPS Systems
                "1.3.6.1.4.1.4329.",    # Socomec
            ],
            "sysdescr_patterns": [r"riello", r"cyberpower", r"eaton.*ups", r"powerware", r"socomec", r"mge\s*ups"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "UPS moderni usano HTTPS 443 (alcuni vecchi solo HTTP 80). XANTO/Riello di default: HTTPS 443, login admin/admin."},
        "oids": {
            **COMMON_OIDS,
            # RFC 1628 UPS-MIB (supportato da tutti i principali vendor moderni)
            "upsIdentManufacturer":   "1.3.6.1.2.1.33.1.1.1.0",
            "upsIdentModel":          "1.3.6.1.2.1.33.1.1.2.0",
            "upsIdentUpsFirmware":    "1.3.6.1.2.1.33.1.1.3.0",
            "upsBatteryStatus":       "1.3.6.1.2.1.33.1.2.1.0",       # 1=unknown, 2=normal, 3=low, 4=depleted
            "upsSecondsOnBattery":    "1.3.6.1.2.1.33.1.2.2.0",
            "upsEstimatedMinutesRemaining": "1.3.6.1.2.1.33.1.2.3.0",
            "upsEstimatedChargeRemaining":  "1.3.6.1.2.1.33.1.2.4.0",  # %
            "upsBatteryVoltage":      "1.3.6.1.2.1.33.1.2.5.0",       # dV (decivolt)
            "upsBatteryTemperature":  "1.3.6.1.2.1.33.1.2.7.0",       # °C
            "upsInputLineBads":       "1.3.6.1.2.1.33.1.3.1.0",
            "upsInputVoltage":        "1.3.6.1.2.1.33.1.3.3.1.3",
            "upsInputFrequency":      "1.3.6.1.2.1.33.1.3.3.1.2",
            "upsOutputSource":        "1.3.6.1.2.1.33.1.4.1.0",       # 1=other, 2=none, 3=normal, 4=bypass, 5=battery, 6=booster, 7=reducer
            "upsOutputPercentLoad":   "1.3.6.1.2.1.33.1.4.4.1.5",
            "upsAlarmsPresent":       "1.3.6.1.2.1.33.1.6.1.0",
        },
        "thresholds": {"battery_pct_warn": 75, "battery_pct_crit": 30, "runtime_min_warn": 15, "runtime_min_crit": 5, "load_pct_warn": 70, "load_pct_crit": 90, "temp_warn_c": 40, "temp_crit_c": 55},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "battery_monitoring", "input_voltage", "rfc1628_ups_mib"],
    },

    # ---------------- HPE OfficeConnect 1620 (smart / web-managed) ----------------
    # IMPORTANTE: definito PRIMA di hp_procurve. Il 1620 (1620-8G/24G/48G, JG912A..JG917A)
    # e' uno smart switch WEB-MANAGED: espone via SNMP SOLO MIB standard (IF-MIB, BRIDGE-MIB,
    # LLDP-MIB, RFC1213, RMON). NON ha la MIB enterprise HP-ICF → niente CPU/memoria/temperatura
    # via SNMP (limite HARDWARE, non di Argus). Questo profilo evita che hp_procurve provi OID
    # HP-ICF inesistenti (letture a vuoto/timeout) e imposta le capability corrette.
    {
        "key": "hpe_officeconnect_1620",
        "vendor": "HPE",
        "family": "switch",
        "label": "HPE OfficeConnect 1620 (web-managed)",
        "description": "Smart switch HPE OfficeConnect serie 1620 (1620-8G/24G/48G, incl. PoE+). SNMP v1/v2c/v3 ma solo MIB standard (IF-MIB/BRIDGE-MIB/LLDP-MIB/RFC1213/RMON): identita', porte, uptime, LLDP e tabella MAC OK. CPU/memoria/temperatura NON disponibili via SNMP su questo hardware (servirebbe scraping della web UI).",
        "fingerprint": {
            # Il segnale primario e' il sysDescr (OfficeConnect/1620/SKU JG91xA). Il prefisso
            # HP tree e' condiviso con altri modelli, quindi il discriminante e' la descrizione.
            "sysobjectid_prefixes": ["1.3.6.1.4.1.11.2.3.7.11."],
            "sysdescr_patterns": [r"officeconnect", r"\b1620\b", r"jg91[2-7]a"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "alt_ports": [443], "notes": "Web UI HTTP 80 (alcune build supportano HTTPS 443). Login: admin, password vuota di default. CPU/mem visibili solo qui (support.lsp), non via SNMP."},
        "oids": {
            **COMMON_OIDS,
            # Solo MIB-II / standard: nessun OID CPU/mem/temp (il 1620 non li espone).
            "ifSpeed": "1.3.6.1.2.1.2.2.1.5",
        },
        "thresholds": {},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "port_traffic", "lldp", "mac_table"],
    },

    # ---------------- HP / Aruba ProCurve / Aruba CX ----------------
    {
        "key": "hp_procurve",
        "vendor": "HP / Aruba",
        "family": "switch",
        "label": "HP / Aruba ProCurve (SNMP)",
        "description": "Switch managed HP ProCurve e Aruba 2xxx/3xxx/5xxx con MIB HP-ICF-OID.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.11.2.3.7.11.", "1.3.6.1.4.1.11.2.14."],
            "sysdescr_patterns": [r"procurve", r"hp\s+switch", r"aruba.*switch", r"hpe.*switch", r"j\d{4}[a-z]?"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Molti modelli più vecchi solo HTTP, Aruba CX supporta HTTPS su 443."},
        "oids": {
            **COMMON_OIDS,
            "cpuUtil":       "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0",      # HP-ICF CPU %
            "memTotalBytes": "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5.1",
            "memFreeBytes":  "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1",
            "stackHealth":   "1.3.6.1.4.1.11.2.14.11.5.1.116.1.1.1.1.5",
            "psuStatus":     "1.3.6.1.4.1.11.2.14.11.5.1.54.2.1.3",     # power supply status table
            "fanStatus":     "1.3.6.1.4.1.11.2.14.11.5.1.54.1.1.3",     # fan status table
            "tempSensor":    "1.3.6.1.4.1.11.2.14.11.5.1.54.3.1.3",     # temperature sensor status
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 55, "temp_crit_c": 70},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "port_traffic", "poe_status"],
    },

    # ---------------- Synology NAS (DSM) ----------------
    {
        "key": "synology_dsm",
        "vendor": "Synology",
        "family": "nas",
        "label": "Synology DiskStation (DSM)",
        "description": "Synology NAS con SNMP attivo + API DSM. Monitora volumi, RAID, temperature HDD, UPS.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.6574."],
            "sysdescr_patterns": [r"synology", r"dsm.*version", r"linux.*synology"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 5001, "scheme": "https", "path": "/", "notes": "DSM 7 usa HTTPS 5001 (HTTP 5000 in alternativa). Bypass CSP richiede popup V4."},
        "oids": {
            **COMMON_OIDS,
            # Synology-specific MIB: SYNOLOGY-SYSTEM-MIB + SYNOLOGY-DISK-MIB + SYNOLOGY-RAID-MIB
            "modelName":        "1.3.6.1.4.1.6574.1.5.1.0",
            "serialNumber":     "1.3.6.1.4.1.6574.1.5.2.0",
            "dsmVersion":       "1.3.6.1.4.1.6574.1.5.3.0",
            "systemStatus":     "1.3.6.1.4.1.6574.1.1.0",               # 1=Normal, 2=Failed
            "temperatureC":     "1.3.6.1.4.1.6574.1.2.0",
            "cpuUserUsage":     "1.3.6.1.4.1.2021.11.9.0",              # UCD-SNMP
            "cpuSystemUsage":   "1.3.6.1.4.1.2021.11.10.0",
            "memTotalReal":     "1.3.6.1.4.1.2021.4.5.0",               # KB
            "memAvailReal":     "1.3.6.1.4.1.2021.4.6.0",
            # Disk table
            "diskID":           "1.3.6.1.4.1.6574.2.1.1.2",
            "diskModel":        "1.3.6.1.4.1.6574.2.1.1.3",
            "diskStatus":       "1.3.6.1.4.1.6574.2.1.1.5",             # 1=Normal, 2=Init, 3=SysPart failed, 4=Crashed, 5=Failed
            "diskTempC":        "1.3.6.1.4.1.6574.2.1.1.6",
            # RAID table
            "raidName":         "1.3.6.1.4.1.6574.3.1.1.2",
            "raidStatus":       "1.3.6.1.4.1.6574.3.1.1.3",             # 1=Normal, 11=Degrade, 20=Crashed
            "raidFreeSize":     "1.3.6.1.4.1.6574.3.1.1.4",
            "raidTotalSize":    "1.3.6.1.4.1.6574.3.1.1.5",
            # Services
            "serviceUsersLogin":"1.3.6.1.4.1.6574.5.1.0",
            "upsBatteryPct":    "1.3.6.1.4.1.6574.4.3.1.1.0",
            "upsStatus":        "1.3.6.1.4.1.6574.4.2.1.0",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 50, "temp_crit_c": 60, "disk_temp_warn_c": 45, "disk_temp_crit_c": 55, "volume_used_warn_pct": 80, "volume_used_crit_pct": 95},
        "polling_interval_seconds": 120,
        "capabilities": ["snmp_basic", "disk_smart", "raid_status", "volume_usage", "ups_attached", "dsm_api_ready"],
        "api_endpoints": {
            "login":    "/webapi/auth.cgi?api=SYNO.API.Auth&version=6&method=login",
            "system_info": "/webapi/entry.cgi?api=SYNO.Core.System&version=3&method=info",
            "storage":  "/webapi/entry.cgi?api=SYNO.Storage.CGI.Storage&version=1&method=load_info",
            "hyper_backup": "/webapi/entry.cgi?api=SYNO.Backup.Task&version=1&method=list",
        },
    },

    # ---------------- QNAP NAS (QTS) ----------------
    {
        "key": "qnap_qts",
        "vendor": "QNAP",
        "family": "nas",
        "label": "QNAP TurboStation (QTS)",
        "description": "QNAP NAS con MIB QNAP-specifico (volumi, HDD SMART, temperature).",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.24681."],
            "sysdescr_patterns": [r"qnap", r"qts\s+\d", r"turbonas"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "Default QTS HTTPS 443, HTTP 8080."},
        "oids": {
            **COMMON_OIDS,
            "modelName":     "1.3.6.1.4.1.24681.1.2.12.0",
            "firmware":      "1.3.6.1.4.1.24681.1.2.13.0",
            "cpuUsage":      "1.3.6.1.4.1.24681.1.2.1.0",
            "systemTempC":   "1.3.6.1.4.1.24681.1.2.6.0",
            "cpuTempC":      "1.3.6.1.4.1.24681.1.2.5.0",
            "freeMemMB":     "1.3.6.1.4.1.24681.1.2.4.0",
            "totalMemMB":    "1.3.6.1.4.1.24681.1.2.2.0",
            # HDD table
            "hddDescr":      "1.3.6.1.4.1.24681.1.2.11.1.2",
            "hddTempC":      "1.3.6.1.4.1.24681.1.2.11.1.3",
            "hddStatus":     "1.3.6.1.4.1.24681.1.2.11.1.7",            # 0=Ready, 1=NoDisk, 2=Invalid, 3=RW-err, 4=Unknown
            "hddSMART":      "1.3.6.1.4.1.24681.1.2.11.1.8",            # "GOOD"/"WARNING"/"ERROR"
            # Volume table
            "volName":       "1.3.6.1.4.1.24681.1.2.17.1.2",
            "volTotal":      "1.3.6.1.4.1.24681.1.2.17.1.4",
            "volFree":       "1.3.6.1.4.1.24681.1.2.17.1.5",
            "volStatus":     "1.3.6.1.4.1.24681.1.2.17.1.6",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 50, "temp_crit_c": 65, "disk_temp_warn_c": 45, "disk_temp_crit_c": 55, "volume_used_warn_pct": 80, "volume_used_crit_pct": 95},
        "polling_interval_seconds": 120,
        "capabilities": ["snmp_basic", "disk_smart", "volume_usage"],
    },

    # ---------------- Fortinet FortiGate ----------------
    {
        "key": "fortinet_fortigate",
        "vendor": "Fortinet",
        "family": "firewall",
        "label": "Fortinet FortiGate (FortiOS)",
        "description": "Firewall Fortinet con SNMP + REST API FortiOS per VPN, HA, sessioni.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.12356."],
            "sysdescr_patterns": [r"fortigate", r"fortinet", r"fortios"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "HTTPS 443 default. La webui FortiOS richiede popup V4 (CSP strict)."},
        "oids": {
            **COMMON_OIDS,
            "fgSysVersion":     "1.3.6.1.4.1.12356.101.4.1.1.0",
            "fgSysModel":       "1.3.6.1.4.1.12356.100.1.1.1.0",
            "fgSysSerial":      "1.3.6.1.4.1.12356.100.1.1.1.0",
            "fgSysCpuUsage":    "1.3.6.1.4.1.12356.101.4.1.3.0",
            "fgSysMemUsage":    "1.3.6.1.4.1.12356.101.4.1.4.0",
            "fgSysSesCount":    "1.3.6.1.4.1.12356.101.4.1.8.0",
            "fgSysDiskUsage":   "1.3.6.1.4.1.12356.101.4.1.6.0",
            "fgHaGroupId":      "1.3.6.1.4.1.12356.101.13.1.1.0",
            "fgHaSysMode":      "1.3.6.1.4.1.12356.101.13.1.2.0",
            # VPN tunnel table
            "fgVpnTunEntName":  "1.3.6.1.4.1.12356.101.12.2.2.1.2",
            "fgVpnTunEntStatus":"1.3.6.1.4.1.12356.101.12.2.2.1.20",     # 1=down, 2=up
            # Firmware
            "fgSysFwVersion":   "1.3.6.1.4.1.12356.101.4.1.1.0",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "disk_used_warn_pct": 80, "disk_used_crit_pct": 95, "session_warn_pct": 75},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "vpn_tunnels", "ha_status", "session_count", "fortios_api_ready"],
        "api_endpoints": {
            "login":            "/logincheck",
            "system_status":    "/api/v2/monitor/system/status",
            "vpn_tunnels":      "/api/v2/monitor/vpn/ipsec",
            "ha_status":        "/api/v2/monitor/system/ha-peer",
            "firmware":         "/api/v2/monitor/system/firmware",
        },
    },

    # ---------------- Ubiquiti UniFi (AP, Switch, Gateway) ----------------
    {
        "key": "unifi",
        "vendor": "Ubiquiti",
        "family": "unifi",
        "label": "Ubiquiti UniFi (AP/Switch/Gateway)",
        "description": "Device UniFi gestiti da Controller. Supporta SNMP v2c + UniFi Controller API.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.41112.", "1.3.6.1.4.1.10002."],
            "sysdescr_patterns": [r"unifi", r"ubnt", r"ubiquiti"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 8443, "scheme": "https", "path": "/", "notes": "UniFi Controller HTTPS 8443. Singoli AP non hanno UI diretta (gestiti dal controller)."},
        "oids": {
            **COMMON_OIDS,
            # UniFi MIB (unofficial, from AP models)
            "unifiApModel":     "1.3.6.1.4.1.41112.1.6.1.1.1.1.1",
            "unifiApSerial":    "1.3.6.1.4.1.41112.1.6.3.1.0",
            "unifiApUptime":    "1.3.6.1.4.1.41112.1.6.1.2.1.0",
            "unifiApClients":   "1.3.6.1.4.1.41112.1.6.1.2.1.8",
            "cpuUserUsage":     "1.3.6.1.4.1.2021.11.9.0",
            "memTotalReal":     "1.3.6.1.4.1.2021.4.5.0",
            "memAvailReal":     "1.3.6.1.4.1.2021.4.6.0",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "clients_warn": 50},
        "polling_interval_seconds": 90,
        "capabilities": ["snmp_basic", "client_count", "controller_api_ready"],
        "api_endpoints": {
            "login":   "/api/login",
            "sites":   "/api/self/sites",
            "devices": "/api/s/{site}/stat/device",
            "clients": "/api/s/{site}/stat/sta",
            "health":  "/api/s/{site}/stat/health",
        },
    },

    # ---------------- TP-Link Omada / EAP (Access Point) ----------------
    {
        "key": "tplink_omada_ap",
        "vendor": "TP-Link",
        "family": "access-point",
        "label": "TP-Link Omada / EAP (Access Point)",
        "description": "Access Point TP-Link Omada (gestiti da OC200/OC300/software controller) e EAP standalone. Enterprise OID .1.3.6.1.4.1.11863. Telemetria via MIB-II + estensioni TP-Link (CPU/RAM/client Wi-Fi). Web Console Omada Controller su HTTPS 8043; AP standalone su 80/443. Porte di adoption/management 29810-29814. SNMP UDP 161.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.11863."],
            "sysdescr_patterns": [r"tp-?link", r"omada", r"\beap\d", r"oc200", r"oc300"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {
            "port": 8043, "scheme": "https", "path": "/", "alt_ports": [443, 80, 8088],
            "notes": "Omada Controller (OC200/OC300/software) HTTPS 8043. AP standalone: HTTP 80 / HTTPS 443. Adoption/management: TCP 29810-29814.",
        },
        "oids": {
            **COMMON_OIDS,
            # TP-Link enterprise extensions (.1.3.6.1.4.1.11863)
            "tpSysCpuUsage":     "1.3.6.1.4.1.11863.6.4.1.1.1",     # CPU usage %
            "tpSysMemoryUsage":  "1.3.6.1.4.1.11863.6.4.1.1.2",     # RAM usage %
            "tpDot11ClientNum":  "1.3.6.1.4.1.11863.6.7.1.2.1.1",   # client wireless connessi
        },
        "thresholds": {
            "cpu_warn_pct": 80, "cpu_crit_pct": 95,
            "mem_warn_pct": 85, "mem_crit_pct": 92,
            "clients_warn": 50, "clients_crit": 80,
            "uplink_down_crit": True,
            "latency_warn_ms": 100, "packet_loss_warn_pct": 2,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "cpu_memory", "client_count", "interface_status", "omada_controller_ready"],
    },

    # ---------------- Aruba Instant On (Access Point) ----------------
    {
        "key": "aruba_instant_on",
        "vendor": "Aruba (HPE)",
        "family": "access-point",
        "label": "Aruba Instant On (AP11/12/15/22/25)",
        "description": "Access Point Aruba Instant On (AP11/12/15/17/22/25). Gestione nativa via Portal Cloud (portal.arubainstanton.com) o mobile app; tabella SNMP volutamente snella (metriche dettagliate nel Cloud/API). Enterprise OID generico Aruba/HPE .1.3.6.1.4.1.14823. NB: l'SNMP va abilitato dal portale Cloud (Gestione Dispositivo -> Opzioni). SNMP UDP 161.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.14823."],
            "sysdescr_patterns": [r"instant\s*on", r"instanton", r"aruba\s*ap1[0-9]", r"aruba\s*ap2[0-9]", r"\baruba\b.*instant"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {
            "port": 443, "scheme": "https", "path": "/",
            "notes": "Gestione via Cloud: https://portal.arubainstanton.com (TCP 443). Local Status Page sull'IP dell'AP: HTTPS 443 (solo stato base/diagnostica).",
        },
        "oids": {
            **COMMON_OIDS,
            # ifTable POE uplink (index 1 = porta LAN/POE)
            "ifInOctetsPoe":               "1.3.6.1.2.1.2.2.1.10.1",   # byte ricevuti porta POE
            "ifOutOctetsPoe":              "1.3.6.1.2.1.2.2.1.16.1",   # byte inviati porta POE
            # Aruba/HPE enterprise (.1.3.6.1.4.1.14823) — conteggio client associati
            "dot11AssociatedStationCount": "1.3.6.1.4.1.14823.2.2.1.5.2.1",
        },
        "thresholds": {
            "cpu_warn_pct": 80, "cpu_crit_pct": 95,
            "mem_warn_pct": 85, "mem_crit_pct": 92,
            "clients_warn": 50, "clients_crit": 80,
            "uplink_down_crit": True,
            "latency_warn_ms": 100, "packet_loss_warn_pct": 2,
        },
        "polling_interval_seconds": 90,
        "capabilities": ["snmp_basic", "client_count", "interface_traffic", "cloud_managed"],
    },

    # ---------------- Zyxel USG FLEX H (uOS) — serie "H" ----------------
    # IMPORTANTE: definito PRIMA di zyxel_usg (ZLD). A parita' di punteggio
    # fingerprint vince il PRIMO in lista: cosi' un FLEX 100H/200H/... (uOS)
    # sceglie questo profilo, mentre un vecchio USG/ATP/Flex ZLD ricade su
    # zyxel_usg (che matcha anche i pattern 'zld'/'usg N' → punteggio piu' alto).
    {
        "key": "zyxel_usg_flex_h",
        "vendor": "Zyxel",
        "family": "firewall",
        "label": "Zyxel USG FLEX H (uOS)",
        "description": "Firewall Zyxel USG FLEX serie H (uOS: 50H/100H/200H/500H/700H). Gli OID uOS DIFFERISCONO dallo ZLD: sessioni attive sul ramo .1.19, CPU su .2.21, memoria calcolata via UCD-SNMP-MIB (.1.3.6.1.4.1.2021.4.*). NB: SNMP disabilitato di default sul firewall; da firmware v1.37p1 richiede SIA Community 1 SIA Community 2; su v1.39p0 alcuni OID Zyxel (mem .2.5.0) potevano essere vuoti → usare il calcolo UCD.",
        "fingerprint": {
            # Condivide il ramo enterprise Zyxel (890.) con lo ZLD → il
            # discriminante e' il sysDescr con la 'H' finale del modello o 'uOS'.
            "sysobjectid_prefixes": ["1.3.6.1.4.1.890.1.15.1.", "1.3.6.1.4.1.890."],
            "sysdescr_patterns": [r"flex\s*\d+\s*hp?\b", r"usg\s*flex\s*\d+\s*h", r"\buos\b"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "alt_ports": [8443], "notes": "uOS Web GUI HTTPS 443. Se la GUI ha bug SNMP, usare la CLI via SSH o l'icona 'Web Console' in alto a destra."},
        "oids": {
            **COMMON_OIDS,
            # CPU % (uOS: media core). Nome 'cpuUtil' cosi' viene letto SIA dalla
            # card device_info_card SIA dagli hardware_alerts (classify cpu+util).
            "cpuUtil":          "1.3.6.1.4.1.890.1.15.3.2.21",
            # Memoria % diretta Zyxel (funziona su firmware patchati; su v1.39p0
            # puo' essere vuota → fallback calcolato via UCD-SNMP qui sotto).
            "memUtil":          "1.3.6.1.4.1.890.1.15.3.2.5.0",
            # UCD-SNMP-MIB per il calcolo memoria affidabile su uOS:
            # mem% = (memTotalReal - memAvailReal - memBuffer - memCached) / memTotalReal * 100
            "memTotalReal":     "1.3.6.1.4.1.2021.4.5.0",
            "memAvailReal":     "1.3.6.1.4.1.2021.4.6.0",
            "memBuffer":        "1.3.6.1.4.1.2021.4.14.0",
            "memCached":        "1.3.6.1.4.1.2021.4.15.0",
            # Sessioni attive (uOS: "Forward Active Session").
            "zyFlexHSessions":  "1.3.6.1.4.1.890.1.15.3.1.19.0",
            "ifSpeed":          "1.3.6.1.2.1.2.2.1.5",
        },
        "thresholds": {
            "cpu_warn_pct": 70, "cpu_crit_pct": 90,
            "mem_warn_pct": 80, "mem_crit_pct": 95,
            "sessions_warn": 50000, "sessions_crit": 100000,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "interface_traffic", "session_count", "cpu_memory", "uos"],
    },

    # ---------------- Zyxel (USG / ATP / Nebula) ----------------
    {
        "key": "zyxel_usg",
        "vendor": "Zyxel",
        "family": "firewall",
        "label": "Zyxel USG / ATP / Flex",
        "description": "Firewall Zyxel USG/ATP/Flex (ZLD). Classificazione via sysObjectID Zyxel-MIB (1.3.6.1.4.1.890.1.15.1.x), monitoraggio ifTable standard + OID specifici Zyxel CPU/Memory/Sessions.",
        "fingerprint": {
            # v3.8.33: prefix specifico USG/ATP/Flex (manteniamo anche il generico
            # 1.3.6.1.4.1.890. per compat con switch GS/XS Zyxel e altri prodotti).
            "sysobjectid_prefixes": ["1.3.6.1.4.1.890.1.15.1.", "1.3.6.1.4.1.890."],
            "sysdescr_patterns": [r"zyxel", r"zywall", r"zld", r"usg\s*\d", r"atp\s*\d", r"flex\s*\d"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "alt_ports": [8443, 80], "notes": "ZyWALL/USG HTTPS 443 default; alcune installazioni usano 8443. Su HTTP 80 spesso redirect a HTTPS."},
        "oids": {
            **COMMON_OIDS,
            # v3.8.33 OID corretti secondo doc utente (Zyxel ZLD MIB):
            "zyCpuUsage":       "1.3.6.1.4.1.890.1.15.3.2.4.0",   # CPU usage %
            "zyMemUsage":       "1.3.6.1.4.1.890.1.15.3.2.5.0",   # Memory usage %
            "zyActiveSessions": "1.3.6.1.4.1.890.1.15.3.2.1.0",   # Numero sessioni attive
            "zySysUptime":      "1.3.6.1.2.1.1.3.0",
            # ifTable per monitoraggio porte (standard MIB-II, gia' in COMMON_OIDS
            # ma esplicitati qui per documentare il polling delle interfacce):
            "ifSpeed":          "1.3.6.1.2.1.2.2.1.5",   # bps per port (table)
        },
        "thresholds": {
            "cpu_warn_pct": 70, "cpu_crit_pct": 90,
            "mem_warn_pct": 80, "mem_crit_pct": 95,
            "sessions_warn": 50000, "sessions_crit": 100000,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "interface_traffic", "session_count", "cpu_memory", "nebula_cloud_ready"],
    },

    # ---------------- DrayTek Vigor (router/firewall) ----------------
    {
        "key": "draytek_vigor",
        "vendor": "DrayTek",
        "family": "router",
        "label": "DrayTek Vigor (Router/Firewall)",
        "description": "Router/firewall DrayTek serie Vigor (es. Vigor2865/2927/2962/3910/165). Classificazione via enterprise OID DrayTek (1.3.6.1.4.1.7367) o sysDescr. Monitoraggio interfacce standard MIB-II + OID DrayTek per memoria/modello/firmware. Su firmware datati CPU/memoria possono essere disponibili solo nella stringa sysDescr. SNMP va abilitato in System Maintenance > SNMP sul router.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.7367."],
            "sysdescr_patterns": [r"draytek", r"vigor"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "alt_ports": [80, 8080], "notes": "Vigor default HTTPS 443 (o HTTP 80). Alcune installazioni cambiano la porta di management. Abilitare SNMP v2c in System Maintenance > SNMP."},
        "oids": {
            **COMMON_OIDS,
            "drRouterModel":     "1.3.6.1.4.1.7367.3.1.0",   # modello router
            "drRouterRevision":  "1.3.6.1.4.1.7367.3.2.0",   # revisione / firmware
            "drFirmwareBuild":   "1.3.6.1.4.1.7367.3.3.0",   # data build firmware
            "drMemoryUsagePct":  "1.3.6.1.4.1.7367.3.7.0",   # % memoria usata (firmware recenti)
            "drLanMac":          "1.3.6.1.4.1.7367.3.8.0",   # MAC LAN
            "hrProcessorLoad":   "1.3.6.1.2.1.25.3.3.1.2",   # CPU % via HOST-RESOURCES (se supportato dal modello)
            "ifSpeed":           "1.3.6.1.2.1.2.2.1.5",      # bps per porta (table)
        },
        "thresholds": {
            "cpu_warn_pct": 70, "cpu_crit_pct": 90,
            "mem_warn_pct": 80, "mem_crit_pct": 95,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "interface_traffic", "cpu_memory"],
    },

    # ---------------- Microsoft Hyper-V VM (Windows guest via SNMP) ----------------
    {
        "key": "hyperv_vm",
        "vendor": "Microsoft",
        "family": "vm",
        "label": "Hyper-V VM (Windows guest, SNMP)",
        "description": "Macchina virtuale su Microsoft Hyper-V con guest Windows e servizio SNMP attivo. Monitoraggio via HOST-RESOURCES-MIB (CPU, RAM, dischi, processi) + MIB-II per le interfacce. NB: richiede il servizio 'SNMP Service' abilitato nel guest Windows con la community configurata. Le metriche a livello di HOST Hyper-V (checkpoint, replica, stato VM) richiedono invece WMI/agent sull'host, non SNMP.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.311."],  # Microsoft enterprise (Windows SNMP)
            "sysdescr_patterns": [r"hyper-?v", r"virtual machine", r"windows", r"microsoft"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 3389, "scheme": "rdp", "path": "/", "alt_ports": [443, 5985], "notes": "Nessuna web console nativa: accesso via RDP (3389) o console Hyper-V dell'host. WinRM su 5985/5986 se si usa gestione remota."},
        "oids": {
            **COMMON_OIDS,
            # HOST-RESOURCES-MIB (guest Windows)
            "hrSystemUptime":         "1.3.6.1.2.1.25.1.1.0",     # uptime OS (piu' preciso di sysUpTime)
            "hrSystemProcesses":      "1.3.6.1.2.1.25.1.6.0",     # numero processi
            "hrSystemNumUsers":       "1.3.6.1.2.1.25.1.5.0",     # utenti loggati
            "hrProcessorLoad":        "1.3.6.1.2.1.25.3.3.1.2",   # CPU % (per-core, table → media)
            "hrMemorySize":           "1.3.6.1.2.1.25.2.2.0",     # RAM totale (KB)
            "hrStorageDescr":         "1.3.6.1.2.1.25.2.3.1.3",   # table: RAM/Virtual/C:/D:
            "hrStorageAllocationUnit":"1.3.6.1.2.1.25.2.3.1.4",   # byte per unita'
            "hrStorageSize":          "1.3.6.1.2.1.25.2.3.1.5",   # dimensione (in unita')
            "hrStorageUsed":          "1.3.6.1.2.1.25.2.3.1.6",   # usato (in unita')
            "ifSpeed":                "1.3.6.1.2.1.2.2.1.5",      # bps per interfaccia (table)
        },
        "thresholds": {
            "cpu_warn_pct": 80, "cpu_crit_pct": 95,
            "mem_warn_pct": 85, "mem_crit_pct": 95,
            "disk_warn_pct": 85, "disk_crit_pct": 95,
        },
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "cpu_memory", "disk_usage", "interface_traffic"],
    },

    # ---------------- APC UPS (PowerNet) ----------------
    {
        "key": "apc_ups",
        "vendor": "APC / Schneider",
        "family": "ups",
        "label": "APC Smart-UPS (PowerNet SNMP)",
        "description": "UPS APC con scheda AP9630/AP9631 o SmartConnect. PowerNet-MIB standard.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.318."],
            "sysdescr_patterns": [r"apc", r"powernet", r"smart-ups", r"symmetra"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "Newer cards HTTPS 443. Legacy cards solo HTTP 80 (SNMPv1)."},
        "oids": {
            **COMMON_OIDS,
            "upsAdvBatteryCapacity":    "1.3.6.1.4.1.318.1.1.1.2.2.1.0",     # %
            "upsAdvBatteryRunTime":     "1.3.6.1.4.1.318.1.1.1.2.2.3.0",     # TimeTicks (1/100 sec)
            "upsAdvBatteryTemperature": "1.3.6.1.4.1.318.1.1.1.2.2.2.0",     # °C
            "upsBasicBatteryStatus":    "1.3.6.1.4.1.318.1.1.1.2.1.1.0",     # 1=unknown, 2=normal, 3=low, 4=depleted
            "upsBasicOutputStatus":     "1.3.6.1.4.1.318.1.1.1.4.1.1.0",     # 2=onLine, 3=onBattery, 4=onSmartBoost, ...
            "upsAdvInputVoltage":       "1.3.6.1.4.1.318.1.1.1.3.2.1.0",     # V
            "upsAdvInputFrequency":     "1.3.6.1.4.1.318.1.1.1.3.2.4.0",
            "upsAdvOutputLoad":         "1.3.6.1.4.1.318.1.1.1.4.2.3.0",     # %
            "upsAdvOutputCurrent":      "1.3.6.1.4.1.318.1.1.1.4.2.4.0",     # A
            "upsBasicIdentModel":       "1.3.6.1.4.1.318.1.1.1.1.1.1.0",
            "upsAdvTestLastDiagnosticsDate": "1.3.6.1.4.1.318.1.1.1.7.2.4.0",
            "upsAdvTestDiagnosticsResults":  "1.3.6.1.4.1.318.1.1.1.7.2.3.0",  # 1=passed, 2=failed, 3=invalidTest, 4=testInProgress
        },
        "thresholds": {"battery_pct_warn": 75, "battery_pct_crit": 30, "runtime_min_warn": 15, "runtime_min_crit": 5, "load_pct_warn": 70, "load_pct_crit": 90, "temp_warn_c": 40, "temp_crit_c": 55},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "battery_monitoring", "self_test_result", "input_voltage"],
    },

    # ---------------- Cisco Catalyst / SMB (IOS/NX-OS) ----------------
    {
        "key": "cisco_catalyst",
        "vendor": "Cisco",
        "family": "switch",
        "label": "Cisco Catalyst / SMB (IOS/NX-OS)",
        "description": "Cisco Catalyst, SG series e Nexus. SNMP standard + CISCO-PROCESS-MIB.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.9."],
            "sysdescr_patterns": [r"cisco\s+ios", r"cisco\s+nx-os", r"cisco\s+catalyst", r"cisco.*switch", r"cisco.*router"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "Cisco SMB ha GUI HTTPS. Catalyst enterprise richiede CLI SSH."},
        "oids": {
            **COMMON_OIDS,
            # CISCO-PROCESS-MIB
            "cpmCPUTotal5sec":  "1.3.6.1.4.1.9.9.109.1.1.1.1.3",
            "cpmCPUTotal1min":  "1.3.6.1.4.1.9.9.109.1.1.1.1.4",
            "cpmCPUTotal5min":  "1.3.6.1.4.1.9.9.109.1.1.1.1.5",
            # CISCO-MEMORY-POOL-MIB
            "ciscoMemoryPoolUsed": "1.3.6.1.4.1.9.9.48.1.1.1.5",
            "ciscoMemoryPoolFree": "1.3.6.1.4.1.9.9.48.1.1.1.6",
            # CISCO-ENVMON-MIB
            "ciscoEnvMonTempStatusValue":  "1.3.6.1.4.1.9.9.13.1.3.1.3",
            "ciscoEnvMonTempStatusState":  "1.3.6.1.4.1.9.9.13.1.3.1.6",
            "ciscoEnvMonFanState":         "1.3.6.1.4.1.9.9.13.1.4.1.3",
            "ciscoEnvMonSupplyState":      "1.3.6.1.4.1.9.9.13.1.5.1.3",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 55, "temp_crit_c": 70},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "port_traffic", "temp_fan_psu_status"],
    },

    # ---------------- Dell iDRAC (server OOB) ----------------
    {
        "key": "dell_idrac",
        "vendor": "Dell",
        "family": "server_oob",
        "label": "Dell iDRAC (Redfish)",
        "description": "Server Dell PowerEdge con iDRAC 8/9/10. Preferire Redfish over SNMP.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.674."],
            "sysdescr_patterns": [r"idrac", r"integrated\s+dell\s+remote", r"poweredge"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "iDRAC SPA richiede popup V4 — stesso discorso di iLO HPE."},
        "oids": {
            **COMMON_OIDS,
            # IDRAC-MIB-SMIv2 — only most-used OIDs
            "systemServiceTag":     "1.3.6.1.4.1.674.10892.5.1.3.2.0",
            "systemModelName":      "1.3.6.1.4.1.674.10892.5.1.3.12.0",
            "globalSystemStatus":   "1.3.6.1.4.1.674.10892.5.2.1.0",     # 1=other, 2=unknown, 3=ok, 4=nonCritical, 5=critical, 6=nonRecoverable
            "powerUnitStatus":      "1.3.6.1.4.1.674.10892.5.4.600.10.1.5",
            "temperatureProbeReading": "1.3.6.1.4.1.674.10892.5.4.700.20.1.6",
            "coolingDeviceReading": "1.3.6.1.4.1.674.10892.5.4.700.12.1.6",
        },
        "thresholds": {"temp_warn_c": 40, "temp_crit_c": 55},
        "polling_interval_seconds": 120,
        "capabilities": ["snmp_basic", "redfish_preferred", "hardware_oob"],
        "api_endpoints": {
            "redfish_systems":   "/redfish/v1/Systems/System.Embedded.1",
            "redfish_chassis":   "/redfish/v1/Chassis/System.Embedded.1",
            "redfish_thermal":   "/redfish/v1/Chassis/System.Embedded.1/Thermal",
            "redfish_power":     "/redfish/v1/Chassis/System.Embedded.1/Power",
        },
    },

    # =====================================================================
    # MULTI-VENDOR PRINTER PROFILES — RFC 3805 Printer-MIB compliant
    # =====================================================================
    # Tutti i profili stampante usano la Printer-MIB standard (RFC 3805) per
    # garantire compatibilita' cross-vendor: hrPrinterStatus per stato,
    # prtMarkerLifeCount per contatori pagine, prtMarkerSuppliesLevel /
    # prtMarkerSuppliesMaxCapacity per livelli consumabili. Gli enterprise OID
    # vendor-specific sono usati solo come signal aggiuntivo per la
    # classificazione (sysObjectID prefix matching) e dove RFC 3805 non basta
    # (es. seriale macchina, modello tradotto, firmware).
    # =====================================================================

    # ---------------- COMMON Printer-MIB OIDs (RFC 3805 + HR-MIB) ----------
    # Riusati come base in tutti i 6 profili. Estratti come variabile per
    # rispettare DRY e poter aggiornare in un solo punto se servono nuove
    # metriche standard cross-vendor.
    # NB: prtMarkerSuppliesLevel/MaxCapacity sono indicizzati per supply
    # (hrDeviceIndex.prtMarkerSuppliesIndex). Per polling esaustivo serve un
    # WALK sull'OID base, ma per fingerprint/discovery basta GET dell'istanza .1.1.

    # ---------------- HP / Hewlett-Packard / HPE ----------------
    {
        "key": "printer_hp",
        "vendor": "HP",
        "family": "printer",
        "label": "Stampante HP (LaserJet / OfficeJet / DesignJet)",
        "description": "Stampanti HP (Hewlett-Packard) con SNMP attivo. Supporta LaserJet Pro/Enterprise, OfficeJet, DesignJet, PageWide. RFC 3805 Printer-MIB per toner/pagine + enterprise OID HP per modello/seriale.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.11."],   # Enterprise HP
            "sysdescr_patterns": [r"\bhp\b", r"hewlett[-\s]?packard", r"laserjet", r"officejet", r"designjet", r"pagewide", r"deskjet"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Embedded Web Server (EWS) HP — HTTP 80; alcuni modelli enterprise espongono anche HTTPS 443. Login admin di default: admin/<vuoto> o admin/<serial>."},
        "oids": {
            **COMMON_OIDS,
            # HR-MIB device/printer status
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",   # 1=other,2=unknown,3=idle,4=printing,5=warmup
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",  # bit field (paper jam, toner low, etc.)
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",   # 1=unknown,2=running,3=warning,4=testing,5=down
            # Printer-MIB RFC 3805 — contatori e supplies
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            "prtMarkerSuppliesType":     "1.3.6.1.2.1.43.11.1.1.5.1.1",
            # HP enterprise — modello e seriale
            "hpModelNumber":             "1.3.6.1.4.1.11.2.3.9.4.2.1.1.3.3.0",
            "hpSerialNumber":            "1.3.6.1.4.1.11.2.3.9.4.2.1.1.3.4.0",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "page_count", "printer_status"],
    },

    # ---------------- Epson ----------------
    {
        "key": "printer_epson",
        "vendor": "Epson",
        "family": "printer",
        "label": "Stampante Epson (WorkForce / EcoTank / Stylus)",
        "description": "Stampanti inkjet/laser Epson con SNMP. Supporta WorkForce, EcoTank, Stylus, SureColor.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.1248."],
            "sysdescr_patterns": [r"\bepson\b", r"workforce", r"ecotank", r"stylus", r"surecolor"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Epson Remote Panel — HTTP 80. Alcuni modelli business hanno HTTPS 443."},
        "oids": {
            **COMMON_OIDS,
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            # Epson enterprise (sub-tree 1248.1.1)
            "epsonModelName":            "1.3.6.1.4.1.1248.1.1.3.1.3.8.0",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "ink_levels", "page_count"],
    },

    # ---------------- Kyocera ----------------
    {
        "key": "printer_kyocera",
        "vendor": "Kyocera",
        "family": "printer",
        "label": "Stampante Kyocera (ECOSYS / TASKalfa)",
        "description": "Stampanti laser Kyocera con SNMP. Supporta serie ECOSYS, FS-, TASKalfa MFP.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.1347."],
            "sysdescr_patterns": [r"\bkyocera\b", r"ecosys", r"taskalfa", r"\bfs[-\s]?\d{3,}"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Kyocera Command Center RX — HTTP 80, alcuni modelli HTTPS 443. Login admin di default: Admin/Admin (case-sensitive)."},
        "oids": {
            **COMMON_OIDS,
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            # Kyocera enterprise (kmprinter)
            "kyoceraModelInfo":          "1.3.6.1.4.1.1347.42.2.1.1.1.2",
            "kyoceraSerialNumber":       "1.3.6.1.4.1.1347.42.2.1.1.1.3",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "page_count", "duplex_count"],
    },

    # ---------------- Xerox ----------------
    {
        "key": "printer_xerox",
        "vendor": "Xerox",
        "family": "printer",
        "label": "Stampante Xerox (Phaser / WorkCentre / VersaLink / AltaLink)",
        "description": "Stampanti e MFP Xerox con SNMP. Supporta Phaser, WorkCentre, VersaLink, AltaLink, ColorQube.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.128.", "1.3.6.1.4.1.253."],   # Xerox enterprise (legacy 253, modern 128)
            "sysdescr_patterns": [r"\bxerox\b", r"workcentre", r"versalink", r"altalink", r"phaser", r"colorqube"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Xerox CentreWare Internet Services — HTTP 80 default, HTTPS 443 su modelli enterprise. Login admin: admin/1111 default."},
        "oids": {
            **COMMON_OIDS,
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            # Xerox enterprise
            "xeroxModel":                "1.3.6.1.4.1.128.2.1.4.1.1.0",
            "xeroxSerialNumber":         "1.3.6.1.4.1.253.8.53.3.2.1.3.1",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "page_count", "color_pages_count"],
    },

    # ---------------- Brother ----------------
    {
        "key": "printer_brother",
        "vendor": "Brother",
        "family": "printer",
        "label": "Stampante Brother (HL / MFC / DCP)",
        "description": "Stampanti laser/inkjet/MFP Brother con SNMP. Supporta serie HL-, MFC-, DCP-.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.2435."],
            "sysdescr_patterns": [r"\bbrother\b", r"\bhl[-\s]?\d", r"\bmfc[-\s]?\d", r"\bdcp[-\s]?\d"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Brother Web Based Management — HTTP 80 / HTTPS 443. Login admin di default: admin/initpass o vuoto."},
        "oids": {
            **COMMON_OIDS,
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            # Brother enterprise
            "brotherDeviceName":         "1.3.6.1.4.1.2435.2.3.9.1.1.7.0",
            "brotherSerialNumber":       "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.1.0",
            "brotherFirmwareVersion":    "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.2.0",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "drum_levels", "page_count"],
    },

    # ---------------- Canon ----------------
    {
        "key": "printer_canon",
        "vendor": "Canon",
        "family": "printer",
        "label": "Stampante Canon (imageRUNNER / imageCLASS / PIXMA / MAXIFY)",
        "description": "Stampanti e MFP Canon con SNMP. Supporta imageRUNNER, imageCLASS, PIXMA, MAXIFY business.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.1602."],
            "sysdescr_patterns": [r"\bcanon\b", r"imagerunner", r"imageclass", r"\bpixma\b", r"\bmaxify\b", r"\bir[-\s]?adv"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Canon Remote UI (RUI) — HTTP 80 default, HTTPS 443 / 8000 su modelli enterprise. Login admin: 7654321 default."},
        "oids": {
            **COMMON_OIDS,
            "hrPrinterStatus":           "1.3.6.1.2.1.25.3.5.1.1.1",
            "hrPrinterDetectedErrorState":"1.3.6.1.2.1.25.3.5.1.2.1",
            "hrDeviceStatus":            "1.3.6.1.2.1.25.3.2.1.5.1",
            "prtMarkerLifeCount":        "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "prtMarkerSuppliesLevel":    "1.3.6.1.2.1.43.11.1.1.9.1.1",
            "prtMarkerSuppliesMaxCap":   "1.3.6.1.2.1.43.11.1.1.8.1.1",
            "prtMarkerSuppliesDescription": "1.3.6.1.2.1.43.11.1.1.6.1.1",
            # Canon enterprise
            "canonProdName":             "1.3.6.1.4.1.1602.1.11.1.3.1.4.1",
            "canonSerial":               "1.3.6.1.4.1.1602.1.2.1.4.0",
        },
        "thresholds": {"toner_warn_pct": 15, "toner_crit_pct": 5, "page_jam_alert": True, "printer_error_alert": True},
        "polling_interval_seconds": 300,
        "capabilities": ["snmp_basic", "printer_mib_rfc3805", "toner_levels", "page_count", "color_pages_count"],
    },

    # ---------------- Generic SNMP fallback ----------------
    {
        "key": "generic_snmp",
        "vendor": "Generic",
        "family": "generic",
        "label": "Device SNMP generico (fallback)",
        "description": "Fallback per device senza fingerprint specifico. Usa solo OID standard MIB-II.",
        "fingerprint": {"sysobjectid_prefixes": [], "sysdescr_patterns": []},
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 80, "scheme": "http", "path": "/", "notes": "Default HTTP 80. Cambiare manualmente se necessario."},
        "oids": dict(COMMON_OIDS),
        "thresholds": {"cpu_warn_pct": 80, "cpu_crit_pct": 95},
        "polling_interval_seconds": 120,
        "capabilities": ["snmp_basic"],
    },
]


# =========================================================================
# HELPERS
# =========================================================================

def fingerprint(sysobjectid: str | None, sysdescr: str | None) -> dict | None:
    """Return the best-matching profile for given SNMP identity, or None."""
    import re
    sysoid = (sysobjectid or "").strip()
    sysdesc = (sysdescr or "").strip().lower()
    best_match = None
    best_score = 0
    for profile in PROFILES:
        if profile["key"] == "generic_snmp":
            continue  # fallback considered last
        score = 0
        fp = profile.get("fingerprint") or {}
        # OID prefix match (strong signal)
        if sysoid:
            for prefix in fp.get("sysobjectid_prefixes") or []:
                if sysoid.startswith(prefix):
                    score += 100
                    break
        # sysDescr regex match (medium signal)
        if sysdesc:
            for pat in fp.get("sysdescr_patterns") or []:
                try:
                    if re.search(pat, sysdesc, re.IGNORECASE):
                        score += 40
                        break
                except re.error:
                    continue
        if score > best_score:
            best_score = score
            best_match = profile
    if best_score >= 40:
        return best_match
    return None


def get_profile(key: str) -> dict | None:
    for p in PROFILES:
        if p["key"] == key:
            return p
    return None


def all_profiles() -> list[dict]:
    return list(PROFILES)


def detect_model_label(profile: dict | None, sysobjectid: str | None) -> str | None:
    """Dato un profilo e il sysObjectID, ritorna il nome modello specifico se il profilo
    espone una mappa `fingerprint.model_by_oid_suffix`. Esempio: per HPE Comware il sysoid
    1.3.6.1.4.1.11.2.3.7.11.162 viene mappato a "HPE FlexNetwork 5130 HI"."""
    if not profile or not sysobjectid:
        return None
    fp = profile.get("fingerprint") or {}
    table = fp.get("model_by_oid_suffix") or {}
    sysoid = sysobjectid.strip()
    # Match esatto (le chiavi sono OID interi, non suffissi)
    if sysoid in table:
        return table[sysoid]
    # Match come prefisso (per OID con suffissi serializzazione, es. .162.0)
    for oid_key, label in table.items():
        if sysoid.startswith(oid_key + ".") or sysoid == oid_key:
            return label
    return None
