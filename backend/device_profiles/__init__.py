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

SEED_VERSION = 1

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

    # ---------------- HPE Comware (ex-H3C) — 5130/5500/5900/7500 ----------------
    {
        "key": "hpe_comware",
        "vendor": "HPE / H3C",
        "family": "switch",
        "label": "HPE Comware (5130/5500/5900/7500)",
        "description": "Switch HPE Comware ex-H3C (5130 EI/HI/SI, 5500, 5900, 7500) — MIB H3C/HH3C.",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.25506.",    # H3C enterprise
                "1.3.6.1.4.1.11.2.3.7.8.",  # HPE Comware via HP tree
            ],
            "sysdescr_patterns": [r"comware", r"h3c", r"hpe?\s*5130", r"hpe?\s*5500", r"hpe?\s*5900", r"hpe?\s*7500", r"3com.*switch"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "HPE Comware HTTPS 443 (HTTP 80 disabilitato di default). La webui è SPA — richiede popup V4 per bypass CSP/X-Frame."},
        "oids": {
            **COMMON_OIDS,
            # H3C/HH3C enterprise MIB
            "h3cEntityExtCpuUsage":   "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
            "h3cEntityExtMemUsage":   "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
            "h3cEntityExtTemperature":"1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
            "h3cFanState":            "1.3.6.1.4.1.25506.2.6.1.1.1.1.16",
            "h3cPowerState":          "1.3.6.1.4.1.25506.2.6.1.1.1.1.18",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 55, "temp_crit_c": 70},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "port_traffic", "stack_status", "comware_cli_ssh"],
    },

    # ---------------- Generic UPS (Riello, XANTO, CyberPower, Eaton) ----------------
    {
        "key": "generic_ups",
        "vendor": "Riello / XANTO / CyberPower / Eaton",
        "family": "ups",
        "label": "UPS generico (RFC 1628 UPS-MIB)",
        "description": "UPS generici non-APC con RFC 1628 UPS-MIB standard (XANTO/Riello, CyberPower, Eaton, Socomec).",
        "fingerprint": {
            "sysobjectid_prefixes": [
                "1.3.6.1.4.1.3808.",    # CyberPower
                "1.3.6.1.4.1.534.",     # Eaton/Powerware
                "1.3.6.1.4.1.4555.",    # Riello / XANTO
                "1.3.6.1.4.1.705.",     # MGE UPS Systems
                "1.3.6.1.4.1.4329.",    # Socomec
            ],
            "sysdescr_patterns": [r"xanto", r"riello", r"cyberpower", r"eaton.*ups", r"powerware", r"socomec", r"mge\s*ups"],
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

    # ---------------- Zyxel (USG / ATP / Nebula) ----------------
    {
        "key": "zyxel_usg",
        "vendor": "Zyxel",
        "family": "firewall",
        "label": "Zyxel USG / ATP / Flex",
        "description": "Firewall Zyxel USG series. SNMP v2c standard + CLI via SSH.",
        "fingerprint": {
            "sysobjectid_prefixes": ["1.3.6.1.4.1.890."],
            "sysdescr_patterns": [r"zyxel", r"zywall", r"zld", r"usg\s*\d", r"atp\s*\d", r"flex\s*\d"],
        },
        "snmp": {"port": 161, "version": "v2c", "community_suggestion": "public", "timeout_seconds": 5, "retries": 2},
        "web_console": {"port": 443, "scheme": "https", "path": "/", "notes": "ZyWALL/USG HTTPS 443 (HTTP 80 spesso redirect)."},
        "oids": {
            **COMMON_OIDS,
            "zyCpuUsage":     "1.3.6.1.4.1.890.1.15.3.2.4.0",       # ZyXEL ZLD CPU %
            "zyMemUsage":     "1.3.6.1.4.1.890.1.15.3.2.6.0",
            "zySessionUsage": "1.3.6.1.4.1.890.1.15.3.2.8.0",
            "zySysUptime":    "1.3.6.1.2.1.1.3.0",
            "zyTempC":        "1.3.6.1.4.1.890.1.15.3.2.5.0",
        },
        "thresholds": {"cpu_warn_pct": 70, "cpu_crit_pct": 90, "mem_warn_pct": 80, "mem_crit_pct": 95, "temp_warn_c": 50, "temp_crit_c": 65},
        "polling_interval_seconds": 60,
        "capabilities": ["snmp_basic", "session_count", "nebula_cloud_ready"],
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
