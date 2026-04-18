"""
NOC Alert Command Center - Redfish iLO Direct Polling & Failover Service
Polls HPE iLO devices directly from the SOC backend when:
  1) Configured for direct polling (external URL available)
  2) Connector goes offline (automatic failover)
"""
import os
import json
import uuid
import logging
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("redfish")

FAILOVER_THRESHOLD_SECONDS = 120  # 2 minutes without heartbeat = connector offline


class RedfishPoller:
    """
    Direct Redfish poller for HPE iLO devices.
    Supports:
    - Always-on direct polling (when iLO is reachable from backend via NAT/VPN)
    - Automatic failover when the Windows connector goes offline
    - Manual test connection from the SOC dashboard
    """

    def __init__(self, db, notification_service=None):
        self.db = db
        self.notification_service = notification_service
        self.scheduler = AsyncIOScheduler()
        self.security_manager = None

    def set_security_manager(self, sm):
        self.security_manager = sm

    async def start_scheduler(self, interval_minutes: int = 5):
        self.scheduler.add_job(
            self.poll_cycle,
            IntervalTrigger(minutes=interval_minutes),
            id='redfish_poll',
            name='Redfish Polling Job',
            replace_existing=True
        )
        self.scheduler.start()
        logger.info(f"Redfish polling scheduler started (interval: {interval_minutes} minutes)")

    def stop_scheduler(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    # ==================== MAIN POLL CYCLE ====================

    async def poll_cycle(self):
        """Main polling cycle: find devices to poll and poll them."""
        if not self.security_manager:
            return

        # Get all iLO credentials from the vault that have an external_url
        ilo_creds = await self.db.device_credentials.find(
            {"credential_type": "ilo"},
            {"_id": 0}
        ).to_list(500)

        if not ilo_creds:
            return

        # Determine which devices need direct polling
        devices_to_poll = []
        for cred in ilo_creds:
            external_url = cred.get("external_url")
            direct_poll = cred.get("direct_poll", False)
            device_ip = cred.get("device_ip")

            if not external_url and not direct_poll:
                # Check failover: is the connector for this device offline?
                should_failover = await self._should_failover(device_ip)
                if should_failover and external_url:
                    devices_to_poll.append({
                        "cred": cred,
                        "reason": "failover",
                    })
            elif direct_poll and external_url:
                devices_to_poll.append({
                    "cred": cred,
                    "reason": "direct",
                })
            elif external_url:
                # Has external URL, check if connector offline for failover
                should_failover = await self._should_failover(device_ip)
                if should_failover:
                    devices_to_poll.append({
                        "cred": cred,
                        "reason": "failover",
                    })

        if not devices_to_poll:
            return

        logger.info(f"Redfish direct polling: {len(devices_to_poll)} devices")

        for item in devices_to_poll:
            try:
                await self._poll_device(item["cred"], item["reason"])
            except Exception as e:
                logger.error(f"Redfish poll error for {item['cred'].get('device_ip')}: {e}")

    async def _should_failover(self, device_ip: str) -> bool:
        """Check if the connector responsible for this device is offline."""
        # Find which client owns this device
        device = await self.db.device_poll_status.find_one(
            {"device_ip": device_ip},
            {"_id": 0, "client_id": 1}
        )
        if not device:
            # No poll status = never been polled by connector. Check managed_devices
            managed = await self.db.managed_devices.find_one(
                {"ip": device_ip},
                {"_id": 0, "client_id": 1}
            )
            if not managed:
                return True  # No connector assigned, poll directly
            client_id = managed["client_id"]
        else:
            client_id = device.get("client_id")

        if not client_id:
            return True

        # Check connector heartbeat
        connector = await self.db.connector_status.find_one(
            {"client_id": client_id},
            {"_id": 0, "last_seen": 1}
        )
        if not connector or not connector.get("last_seen"):
            return True  # No connector ever connected

        try:
            last_seen = datetime.fromisoformat(connector["last_seen"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
            return elapsed > FAILOVER_THRESHOLD_SECONDS
        except Exception:
            return True

    async def _poll_device(self, cred: dict, reason: str):
        """Poll a single iLO device via Redfish REST API."""
        device_ip = cred.get("device_ip", "")
        external_url = cred.get("external_url", "")
        device_name = cred.get("device_name", device_ip)

        # Decrypt credentials
        try:
            username = self.security_manager.decrypt_credential(cred["username_enc"])
            password = self.security_manager.decrypt_credential(cred["password_enc"])
        except Exception as e:
            logger.error(f"Cannot decrypt credentials for {device_ip}: {e}")
            return

        port = cred.get("port") or 443
        base_url = external_url.rstrip("/") if external_url else f"https://{device_ip}:{port}"

        logger.info(f"Polling {device_name} ({device_ip}) via {base_url} [reason={reason}]")

        result = {
            "redfish_ok": False,
            "power_watts": None,
            "bios_version": None,
            "server_model": None,
            "serial_number": None,
            "uuid": None,
            "ilo_firmware": None,
            "ilo_license": None,
            "total_memory_gb": None,
            "memory_dimms": [],
            "network_adapters": [],
            "storage_controllers": [],
            "health_status": None,
            "temperatures": [],
            "fans": [],
            "power_supplies": [],
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                auth = (username, password)

                # 1. System Info
                sys_data = await self._get(client, f"{base_url}/redfish/v1/Systems/1/", auth)
                if sys_data:
                    result["redfish_ok"] = True
                    result["server_model"] = sys_data.get("Model")
                    result["serial_number"] = sys_data.get("SerialNumber")
                    result["uuid"] = sys_data.get("UUID")
                    result["bios_version"] = sys_data.get("BiosVersion")
                    if sys_data.get("MemorySummary"):
                        result["total_memory_gb"] = sys_data["MemorySummary"].get("TotalSystemMemoryGiB")
                    health = sys_data.get("Status", {}).get("Health", "Unknown")
                    result["health_status"] = health.lower() if health else "unknown"

                # 2. Power
                power_data = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/Power/", auth)
                if power_data and power_data.get("PowerControl"):
                    pc = power_data["PowerControl"][0] if power_data["PowerControl"] else {}
                    result["power_watts"] = pc.get("PowerConsumedWatts")
                    # Power supplies
                    for ps in power_data.get("PowerSupplies", []):
                        result["power_supplies"].append({
                            "name": ps.get("Name", "PSU"),
                            "condition": (ps.get("Status", {}).get("Health", "OK")).lower(),
                            "watts": ps.get("PowerCapacityWatts"),
                        })

                # 3. Thermal
                thermal = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/Thermal/", auth)
                if thermal:
                    for t in thermal.get("Temperatures", []):
                        if t.get("ReadingCelsius") and t["ReadingCelsius"] > 0:
                            result["temperatures"].append({
                                "locale": t.get("Name", "Sensor"),
                                "value": t["ReadingCelsius"],
                                "condition": (t.get("Status", {}).get("Health", "OK")).lower(),
                            })
                    for f in thermal.get("Fans", []):
                        result["fans"].append({
                            "locale": f.get("Name", "Fan"),
                            "speed": f.get("Reading"),
                            "condition": (f.get("Status", {}).get("Health", "OK")).lower(),
                        })

                # 4. iLO Manager info
                mgr = await self._get(client, f"{base_url}/redfish/v1/Managers/1/", auth)
                if mgr:
                    result["ilo_firmware"] = mgr.get("FirmwareVersion")
                    oem = mgr.get("Oem", {})
                    hpe = oem.get("Hpe") or oem.get("Hp") or {}
                    lic = hpe.get("License", {})
                    result["ilo_license"] = lic.get("LicenseString")

                # 5. Memory DIMMs
                mem_col = await self._get(client, f"{base_url}/redfish/v1/Systems/1/Memory/", auth)
                if mem_col and mem_col.get("Members"):
                    for ref in mem_col["Members"][:32]:
                        dimm = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if dimm and dimm.get("Status", {}).get("State") == "Enabled":
                            result["memory_dimms"].append({
                                "name": dimm.get("DeviceLocator", "DIMM"),
                                "size_gb": round(dimm.get("CapacityMiB", 0) / 1024, 1),
                                "speed_mhz": dimm.get("OperatingSpeedMhz"),
                                "type": dimm.get("MemoryDeviceType"),
                                "status": dimm.get("Status", {}).get("Health", "OK"),
                            })

                # 6. Network Adapters
                nics = await self._get(client, f"{base_url}/redfish/v1/Systems/1/EthernetInterfaces/", auth)
                if nics and nics.get("Members"):
                    for ref in nics["Members"][:16]:
                        nic = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if nic:
                            result["network_adapters"].append({
                                "name": nic.get("Name", "NIC"),
                                "mac": nic.get("MACAddress"),
                                "speed_mbps": nic.get("SpeedMbps"),
                                "status": (nic.get("Status", {}).get("Health") or "N/A"),
                                "ipv4": (nic.get("IPv4Addresses", [{}])[0].get("Address") if nic.get("IPv4Addresses") else None),
                            })

                # 7. Storage
                storage = await self._get(client, f"{base_url}/redfish/v1/Systems/1/SmartStorage/ArrayControllers/", auth)
                if not storage:
                    storage = await self._get(client, f"{base_url}/redfish/v1/Systems/1/Storage/", auth)
                if storage and storage.get("Members"):
                    for ref in storage["Members"][:8]:
                        ctrl = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if ctrl:
                            ctrl_info = {
                                "name": ctrl.get("Model") or ctrl.get("Name", "Controller"),
                                "status": (ctrl.get("Status", {}).get("Health") or "OK"),
                                "logical_drives": [],
                            }
                            ld_path = ref['@odata.id'].rstrip('/') + "/LogicalDrives/"
                            lds = await self._get(client, f"{base_url}{ld_path}", auth)
                            if lds and lds.get("Members"):
                                for ldref in lds["Members"]:
                                    ld = await self._get(client, f"{base_url}{ldref['@odata.id']}", auth)
                                    if ld:
                                        ctrl_info["logical_drives"].append({
                                            "name": ld.get("LogicalDriveName", "LUN"),
                                            "capacity_gb": round(ld.get("CapacityMiB", 0) / 1024, 1) if ld.get("CapacityMiB") else None,
                                            "raid": ld.get("Raid"),
                                            "status": (ld.get("Status", {}).get("Health") or "OK"),
                                        })
                            result["storage_controllers"].append(ctrl_info)

        except httpx.TimeoutException:
            logger.warning(f"Timeout polling {device_ip}")
        except httpx.ConnectError:
            logger.warning(f"Connection refused for {device_ip}")
        except Exception as e:
            logger.error(f"Unexpected error polling {device_ip}: {e}")

        # Save results to device_poll_status (same as connector does)
        now_iso = datetime.now(timezone.utc).isoformat()
        if result["redfish_ok"]:
            update_doc = {
                "device_ip": device_ip,
                "device_name": device_name,
                "reachable": True,
                "monitor_type": "redfish_direct",
                "polling_source": reason,
                "device_class": "hpe-ilo",
                "redfish": {
                    "power_watts": result["power_watts"],
                    "bios_version": result["bios_version"],
                    "server_model": result["server_model"],
                    "serial_number": result["serial_number"],
                    "uuid": result["uuid"],
                    "ilo_firmware": result["ilo_firmware"],
                    "ilo_license": result["ilo_license"],
                    "total_memory_gb": result["total_memory_gb"],
                    "memory_dimms": result["memory_dimms"],
                    "network_adapters": result["network_adapters"],
                    "storage_controllers": result["storage_controllers"],
                },
                "hardware": {
                    "health_status": result["health_status"],
                    "temperatures": result["temperatures"],
                    "fans": result["fans"],
                    "power_supplies": result["power_supplies"],
                },
                "last_poll": now_iso,
                "updated_at": now_iso,
            }

            # Find client_id for this device (3-layer lookup + smart fallback)
            # 1) Prefer client_id from the vault credential (most reliable for new devices)
            # 2) Fallback to existing device_poll_status client_id
            # 3) Fallback to managed_devices client_id
            # 4) Fallback to discovered_endpoints (LLDP/MAC table from any connector)
            # 5) Last resort: if only one client exists in the system, use that one
            client_id_to_set = cred.get("client_id")
            if not client_id_to_set:
                existing = await self.db.device_poll_status.find_one(
                    {"device_ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if existing and existing.get("client_id"):
                    client_id_to_set = existing["client_id"]
            if not client_id_to_set:
                md = await self.db.managed_devices.find_one(
                    {"ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if md and md.get("client_id"):
                    client_id_to_set = md["client_id"]
            if not client_id_to_set:
                # Look in discovered endpoints (LLDP/MAC table from any connector's topology)
                ep = await self.db.discovered_endpoints.find_one(
                    {"ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if ep and ep.get("client_id"):
                    client_id_to_set = ep["client_id"]
            if not client_id_to_set:
                # Last resort: single-client installation -> auto-assign
                all_clients = await self.db.clients.find({}, {"_id": 0, "id": 1}).to_list(10)
                if len(all_clients) == 1:
                    client_id_to_set = all_clients[0]["id"]
                    logger.info(f"Redfish {device_ip}: auto-assigned to single client {client_id_to_set}")
            if client_id_to_set:
                update_doc["client_id"] = client_id_to_set
                update_doc["device_type"] = "ilo"
                # Auto-heal: also update the Vault credential so next polls don't need fallback logic
                if not cred.get("client_id"):
                    try:
                        await self.db.device_credentials.update_one(
                            {"device_ip": device_ip, "credential_type": "ilo"},
                            {"$set": {"client_id": client_id_to_set}}
                        )
                        logger.info(f"Vault cred for {device_ip} auto-assigned to client {client_id_to_set}")
                    except Exception as e:
                        logger.warning(f"Vault cred auto-heal failed: {e}")
            else:
                logger.warning(f"Redfish {device_ip}: could not determine client_id — alerts will be orphan")

            await self.db.device_poll_status.update_one(
                {"device_ip": device_ip},
                {"$set": update_doc},
                upsert=True
            )

            # Historical metrics
            main_temp = result["temperatures"][0]["value"] if result["temperatures"] else None
            await self.db.device_metrics_history.insert_one({
                "client_id": client_id_to_set,
                "device_ip": device_ip,
                "timestamp": now_iso,
                "power_watts": result["power_watts"],
                "temperature": main_temp,
            })

            # Generate alerts for critical conditions
            await self._check_alerts(device_ip, device_name, result, client_id_to_set)

            logger.info(f"Redfish OK: {device_name} | {result['server_model']} | {result['power_watts']}W | Health: {result['health_status']}")
        else:
            logger.warning(f"Redfish failed for {device_name} ({device_ip})")

    async def _check_alerts(self, device_ip: str, device_name: str, result: dict, client_id: Optional[str] = None):
        """Generate alerts for critical iLO conditions."""
        alerts = []

        # Overall health
        if result["health_status"] and result["health_status"] not in ("ok", "unknown"):
            alerts.append({
                "severity": "critical",
                "title": f"iLO Health {result['health_status'].upper()}",
                "message": f"Server {device_name} ({device_ip}) stato salute: {result['health_status']}",
            })

        # Temperature sensors
        for t in result["temperatures"]:
            if t["value"] > 75:
                alerts.append({
                    "severity": "critical",
                    "title": f"Temperatura critica: {t['value']}C",
                    "message": f"{t['locale']} su {device_name} ({device_ip}): {t['value']}C",
                })
            elif t["value"] > 65:
                alerts.append({
                    "severity": "high",
                    "title": f"Temperatura elevata: {t['value']}C",
                    "message": f"{t['locale']} su {device_name} ({device_ip}): {t['value']}C",
                })

        # Fans
        for f in result["fans"]:
            if f["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "high",
                    "title": f"Ventola {f['condition']}",
                    "message": f"{f['locale']} su {device_name} ({device_ip}): {f['condition']}",
                })

        # Power supplies
        for ps in result["power_supplies"]:
            if ps["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "critical",
                    "title": f"Alimentatore {ps['condition']}",
                    "message": f"{ps['name']} su {device_name} ({device_ip}): {ps['condition']}",
                })

        # Storage controllers + drives
        for ctrl in (result.get("storage_controllers") or []):
            ctrl_health = (ctrl.get("health") or "").lower()
            ctrl_status = (ctrl.get("status") or "").lower()
            if ctrl_health and ctrl_health not in ("ok", "unknown", ""):
                alerts.append({
                    "severity": "critical",
                    "title": f"Controller RAID {ctrl_health.upper()}",
                    "message": f"Controller '{ctrl.get('name','?')}' su {device_name} ({device_ip}): stato {ctrl_health}" +
                               (f" ({ctrl_status})" if ctrl_status else ""),
                })
            for dr in (ctrl.get("drives") or []):
                drive_health = (dr.get("health") or "").lower()
                drive_state = (dr.get("state") or "").lower()
                drive_failed = bool(dr.get("failure_predicted"))
                label = dr.get("model") or dr.get("name") or "disco"
                if drive_health and drive_health not in ("ok", "unknown", ""):
                    alerts.append({
                        "severity": "critical",
                        "title": f"Disco {drive_health.upper()}: {label}",
                        "message": f"Disco {label} (slot {dr.get('slot','?')}) su {device_name} ({device_ip}): health={drive_health}, state={drive_state or 'n/a'}",
                    })
                elif drive_failed:
                    alerts.append({
                        "severity": "high",
                        "title": f"Disco guasto previsto: {label}",
                        "message": f"Disco {label} (slot {dr.get('slot','?')}) su {device_name} ({device_ip}): SMART prevede guasto imminente",
                    })

        # Memory DIMMs
        for dimm in (result.get("memory_dimms") or []):
            dimm_health = (dimm.get("health") or "").lower()
            if dimm_health and dimm_health not in ("ok", "unknown", "") and dimm.get("capacity_mb", 0) > 0:
                alerts.append({
                    "severity": "critical",
                    "title": f"DIMM Memoria {dimm_health.upper()}",
                    "message": f"DIMM '{dimm.get('name','?')}' ({dimm.get('capacity_mb',0)}MB) su {device_name} ({device_ip}): {dimm_health}",
                })

        # Network adapters (NIC link status)
        for nic in (result.get("network_adapters") or []):
            nic_health = (nic.get("health") or "").lower()
            link_status = (nic.get("link_status") or "").lower()
            nic_name = nic.get("name") or nic.get("id") or "NIC"
            # Alert only on configured/connected NICs that went down
            if link_status == "linkdown" and nic.get("speed_mbps"):
                alerts.append({
                    "severity": "high",
                    "title": f"Link LAN DOWN: {nic_name}",
                    "message": f"Interfaccia {nic_name} ({nic.get('mac','?')}) su {device_name} ({device_ip}): link DOWN",
                })
            elif nic_health and nic_health not in ("ok", "unknown", ""):
                alerts.append({
                    "severity": "high",
                    "title": f"NIC {nic_health.upper()}: {nic_name}",
                    "message": f"Interfaccia {nic_name} su {device_name} ({device_ip}): health={nic_health}",
                })

        for alert in alerts:
            existing = await self.db.alerts.find_one({
                "device_ip": device_ip,
                "source_type": "redfish_direct",
                "title": alert["title"],
                "status": "active",
            })
            if not existing:
                await self.db.alerts.insert_one({
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "device_ip": device_ip,
                    "device_name": device_name,
                    "device_type": "ilo",
                    "severity": alert["severity"],
                    "source_type": "redfish_direct",
                    "title": alert["title"],
                    "message": alert["message"],
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

    async def _get(self, client: httpx.AsyncClient, url: str, auth: tuple) -> Optional[dict]:
        """Safe GET request with error handling."""
        try:
            r = await client.get(url, auth=auth)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    # ==================== PUBLIC API ====================

    async def test_connection(self, url: str, username: str, password: str) -> dict:
        """Test Redfish connection from the SOC backend."""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                r = await client.get(f"{url}/redfish/v1/", auth=(username, password))
                if r.status_code == 200:
                    data = r.json()
                    # Also try to get system info
                    sys_r = await client.get(f"{url}/redfish/v1/Systems/1/", auth=(username, password))
                    sys_info = sys_r.json() if sys_r.status_code == 200 else {}
                    return {
                        "success": True,
                        "redfish_version": data.get("RedfishVersion"),
                        "product": data.get("Product", sys_info.get("Manufacturer", "Unknown")),
                        "model": sys_info.get("Model"),
                        "serial": sys_info.get("SerialNumber"),
                        "health": sys_info.get("Status", {}).get("Health"),
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}
        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout connessione"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_failover_status(self) -> list:
        """Get failover status for all iLO devices."""
        ilo_creds = await self.db.device_credentials.find(
            {"credential_type": "ilo"},
            {"_id": 0, "device_ip": 1, "device_name": 1, "external_url": 1, "direct_poll": 1, "id": 1}
        ).to_list(500)

        result = []
        for cred in ilo_creds:
            device_ip = cred.get("device_ip")
            connector_offline = await self._should_failover(device_ip)
            external_url = cred.get("external_url")
            direct_poll = cred.get("direct_poll", False)

            polling_mode = "connector"
            if direct_poll and external_url:
                polling_mode = "direct"
            elif connector_offline and external_url:
                polling_mode = "failover"
            elif connector_offline:
                polling_mode = "offline"

            result.append({
                "device_ip": device_ip,
                "device_name": cred.get("device_name"),
                "external_url": external_url,
                "direct_poll": direct_poll,
                "connector_offline": connector_offline,
                "polling_mode": polling_mode,
            })

        return result


    # ==================== POWER CONTROL ====================

    async def power_action(self, url: str, username: str, password: str, action: str) -> dict:
        """
        Execute a power action on a server via iLO Redfish.
        Actions: On, ForceOff, GracefulShutdown, ForceRestart, PushPowerButton
        """
        valid_actions = ["On", "ForceOff", "GracefulShutdown", "ForceRestart", "PushPowerButton"]
        if action not in valid_actions:
            return {"success": False, "error": f"Azione non valida. Valide: {valid_actions}"}

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                # First get current power state
                sys_r = await client.get(
                    f"{url}/redfish/v1/Systems/1/",
                    auth=(username, password)
                )
                power_state = "Unknown"
                if sys_r.status_code == 200:
                    power_state = sys_r.json().get("PowerState", "Unknown")

                # Execute the reset action
                r = await client.post(
                    f"{url}/redfish/v1/Systems/1/Actions/ComputerSystem.Reset/",
                    auth=(username, password),
                    json={"ResetType": action},
                    headers={"Content-Type": "application/json"}
                )

                if r.status_code in (200, 204):
                    return {
                        "success": True,
                        "action": action,
                        "previous_state": power_state,
                        "message": f"Comando '{action}' inviato con successo",
                    }
                elif r.status_code == 400:
                    # iLO returns 400 if the action is not applicable (e.g., PowerOn when already On)
                    error_body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                    msg = error_body.get("error", {}).get("@Message.ExtendedInfo", [{}])
                    detail = msg[0].get("MessageId", "") if msg else str(error_body)
                    return {
                        "success": False,
                        "error": f"Azione non applicabile (stato attuale: {power_state}): {detail}",
                        "power_state": power_state,
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}

        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout connessione iLO"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata - iLO non raggiungibile"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_power_state(self, url: str, username: str, password: str) -> dict:
        """Get the current power state of a server via iLO Redfish."""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                r = await client.get(
                    f"{url}/redfish/v1/Systems/1/",
                    auth=(username, password)
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "success": True,
                        "power_state": data.get("PowerState", "Unknown"),
                        "health": data.get("Status", {}).get("Health", "Unknown"),
                        "model": data.get("Model"),
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}
        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata"}
        except Exception as e:
            return {"success": False, "error": str(e)}
