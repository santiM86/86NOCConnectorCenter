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
