"""Pydantic models for the NOC Alert Command Center."""
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TwoFactorSetup(BaseModel):
    password: str

class TwoFactorVerify(BaseModel):
    code: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    role: str = "operator"
    two_factor_enabled: bool = False

class ClientCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    contact_email: Optional[str] = ""

class ClientResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    description: str
    contact_email: str
    api_key: Optional[str] = ""
    created_at: str

class DeviceCreate(BaseModel):
    client_id: str
    name: str
    device_type: str
    ip_address: str
    hostname: Optional[str] = ""
    location: Optional[str] = ""
    redfish_enabled: Optional[bool] = False

class DeviceCredentials(BaseModel):
    username: str
    password: str

class DeviceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: str
    client_name: Optional[str] = ""
    name: str
    device_type: str
    ip_address: str
    hostname: str
    location: str
    status: str = "active"
    redfish_enabled: bool = False
    has_credentials: bool = False
    last_poll: Optional[str] = None
    health_status: Optional[str] = None
    # source: where the device record originated
    source: Optional[str] = None  # manual | connector-master | connector-scanner | managed
    auto_added: Optional[bool] = False
    discovered_via: Optional[str] = None
    discovered_subnet: Optional[str] = None
    vlan_id: Optional[int] = None
    last_seen_at: Optional[str] = None
    sys_descr: Optional[str] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    temperature: Optional[float] = None
    uptime: Optional[str] = None
    connector_hostname: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_version: Optional[str] = None
    ports: Optional[list] = None
    ping_ms: Optional[float] = None
    # Web Console (auto-detected by Connector tray "Apri Web UI")
    web_console_url: Optional[str] = None
    web_console_port: Optional[int] = None
    web_console_scheme: Optional[str] = None
    web_console_title: Optional[str] = None
    http_port: Optional[int] = None
    monitor_type: Optional[str] = None
    # Device profile (auto-configurazione vendor-specific)
    profile_key: Optional[str] = None
    vendor: Optional[str] = None
    family: Optional[str] = None
    profile_auto_matched: Optional[bool] = None
    # Alert silencing (admin can silence alerts per-device for noisy/best-effort devices)
    alerts_silenced: Optional[bool] = False
    alerts_silenced_reason: Optional[str] = None
    # v3.8.16+: Scanner enrichment fields (MAC, randomization flag, Fingerbank)
    mac: Optional[str] = None
    mac_is_random: Optional[bool] = False
    fingerbank_device_name: Optional[str] = None
    fingerbank_score: Optional[int] = None
    # v3.8.17: connection classification (LAN cavo / Wi-Fi)
    connection_type: Optional[str] = None  # "lan" | "wifi" | "unknown"
    connection_source: Optional[str] = None  # cam_table | lldp:ap=... | laa_inference | self_is_lldp_device | no_mac
    connection_via_switch: Optional[str] = None
    connection_via_port: Optional[str] = None
    connection_confidence: Optional[int] = None  # 0-99
    created_at: str

class AlertCreate(BaseModel):
    client_id: str
    device_id: str
    severity: str
    source_type: str
    title: str
    message: str
    raw_data: Optional[str] = ""

class AlertResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: Optional[str] = ""
    client_name: Optional[str] = ""
    device_id: Optional[str] = ""
    device_name: Optional[str] = ""
    device_type: Optional[str] = ""
    device_ip: Optional[str] = ""
    ip_address: Optional[str] = ""
    severity: str
    source_type: str
    title: str
    message: str
    raw_data: Optional[str] = ""
    status: str = "active"
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str

class AlertUpdate(BaseModel):
    status: Optional[str] = None
    acknowledged_by: Optional[str] = None

class NotificationSettingsUpdate(BaseModel):
    email_enabled: bool = True
    push_enabled: bool = True
    webhook_teams: Optional[str] = None
    webhook_slack: Optional[str] = None
    webhook_telegram: Optional[str] = None
    webhook_generic: Optional[str] = None

class RedfishTestRequest(BaseModel):
    ip_address: str
    username: str
    password: str

class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str
    role: str = "operator"

class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None

class CredentialCreate(BaseModel):
    device_ip: Optional[str] = None
    device_name: Optional[str] = None
    credential_type: str
    username: str
    password: str
    url: Optional[str] = None
    port: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = []
    external_url: Optional[str] = None
    connector_only: Optional[bool] = False  # Disattiva polling diretto anche se external_url presente
    client_id: Optional[str] = None

class CredentialUpdate(BaseModel):
    device_name: Optional[str] = None
    credential_type: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    url: Optional[str] = None
    port: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    external_url: Optional[str] = None
    connector_only: Optional[bool] = None
    client_id: Optional[str] = None

class SyslogMessage(BaseModel):
    device_ip: str
    facility: Optional[int] = 1
    severity_level: Optional[int] = 5
    message: str
    timestamp: Optional[str] = None

class SNMPTrap(BaseModel):
    device_ip: str
    oid: str
    value: str
    trap_type: Optional[str] = "generic"
    device_name: Optional[str] = None
    severity: Optional[str] = None

class ConnectorHeartbeat(BaseModel):
    connector_version: str
    hostname: str
    uptime_seconds: int
    traps_received: int
    syslogs_received: int
    # v3.8: connector mode (master = polling completo; scanner = solo discovery LAN)
    mode: Optional[str] = "master"
    subnet: Optional[str] = None       # subnet visibile dal connector (es. "10.100.61.0/24")
    vlan_id: Optional[int] = None      # opzionale, per UI grouping
    # v3.8.27 LIVE DIAGNOSTICS: telemetria operativa del connector inviata
    # ad ogni heartbeat (~60s) per la UI Center. Tutti opzionali per retro-compat
    # con connettori v3.8.x precedenti (i vecchi non li mandano e quelli rimangono
    # None nel doc, la UI mostra '—' al posto del valore).
    bytes_sent_60s: Optional[int] = None   # byte JSON inviati al NOC negli ultimi ~60s
    bytes_recv_60s: Optional[int] = None   # byte ricevuti dal NOC negli ultimi ~60s
    jobs_alive: Optional[int] = None       # job PowerShell in stato Running
    jobs_total: Optional[int] = None       # totale job (alive + completed/failed)
    ram_mb: Optional[int] = None           # WorkingSet64 del processo connector in MB


class LanScanEndpoint(BaseModel):
    """Endpoint rilevato dal mini-scanner via ARP/mDNS/SNMP locale."""
    mac: str
    ip: Optional[str] = None
    hostname: Optional[str] = None
    sys_descr: Optional[str] = None
    sys_name: Optional[str] = None
    discovered_via: str = "arp"        # arp | mdns | snmp | dhcp | ping+arp
    rtt_ms: Optional[float] = None     # latenza ICMP
    vendor: Optional[str] = None       # v3.8.2: vendor da OUI lookup (es. "Cisco", "HP")


class LanScanReport(BaseModel):
    """Report periodico dello scanner: endpoint visti nella subnet locale."""
    subnet: str
    vlan_id: Optional[int] = None
    scan_started_at: str
    scan_ended_at: str
    endpoints: list[LanScanEndpoint]
    hostname: Optional[str] = None  # hostname del mini-scanner che invia il report

class DeviceStatusReport(BaseModel):
    device_ip: str
    device_name: str
    community: str = "public"
    reachable: bool
    ports: Optional[list] = []
    sys_descr: Optional[str] = ""
    sys_uptime: Optional[str] = ""
    poll_timestamp: str

class PollingReport(BaseModel):
    devices: list[DeviceStatusReport]

class ManagedDevice(BaseModel):
    ip: str
    community: str = "public"
    name: str
    monitor_type: str = "snmp"
    device_type: str = "network"
    http_port: Optional[int] = 80
    snmp_version: str = "v2c"  # "v1", "v2c", "v3"
    # SNMPv3 fields
    snmpv3_username: Optional[str] = None
    snmpv3_auth_protocol: Optional[str] = None   # "MD5", "SHA", "SHA256", None
    snmpv3_auth_password: Optional[str] = None
    snmpv3_priv_protocol: Optional[str] = None   # "DES", "AES", "AES256", None
    snmpv3_priv_password: Optional[str] = None
    snmpv3_security_level: Optional[str] = "authPriv"  # "noAuthNoPriv", "authNoPriv", "authPriv"
