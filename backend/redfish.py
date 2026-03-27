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

            # Find client_id for this device
            existing = await self.db.device_poll_status.find_one(
                {"device_ip": device_ip}, {"_id": 0, "client_id": 1}
            )
            if existing and existing.get("client_id"):
                update_doc["client_id"] = existing["client_id"]

            await self.db.device_poll_status.update_one(
                {"device_ip": device_ip},
                {"$set": update_doc},
                upsert=True
            )

            # Historical metrics
            main_temp = result["temperatures"][0]["value"] if result["temperatures"] else None
            await self.db.device_metrics_history.insert_one({
                "client_id": update_doc.get("client_id"),
                "device_ip": device_ip,
                "timestamp": now_iso,
                "power_watts": result["power_watts"],
                "temperature": main_temp,
            })

            # Generate alerts for critical conditions
            await self._check_alerts(device_ip, device_name, result)

            logger.info(f"Redfish OK: {device_name} | {result['server_model']} | {result['power_watts']}W | Health: {result['health_status']}")
        else:
            logger.warning(f"Redfish failed for {device_name} ({device_ip})")

    async def _check_alerts(self, device_ip: str, device_name: str, result: dict):
        """Generate alerts for critical iLO conditions."""
        alerts = []

        if result["health_status"] and result["health_status"] not in ("ok", "unknown"):
            alerts.append({
                "severity": "critical",
                "title": f"iLO Health {result['health_status'].upper()}",
                "message": f"Server {device_name} ({device_ip}) stato salute: {result['health_status']}",
            })

        for t in result["temperatures"]:
            if t["value"] > 75:
                alerts.append({
                    "severity": "critical",
                    "title": f"Temperatura critica: {t['value']}C",
                    "message": f"{t['locale']} su {device_name} ({device_ip}): {t['value']}C",
                })

        for f in result["fans"]:
            if f["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "high",
                    "title": f"Ventola {f['condition']}",
                    "message": f"{f['locale']} su {device_name} ({device_ip}): {f['condition']}",
                })

        for ps in result["power_supplies"]:
            if ps["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "critical",
                    "title": f"Alimentatore {ps['condition']}",
                    "message": f"{ps['name']} su {device_name} ({device_ip}): {ps['condition']}",
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
                    "device_ip": device_ip,
                    "device_name": device_name,
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
