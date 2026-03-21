"""
NOC Alert Command Center - Redfish API Polling Service
Automated polling of HPE iLO and other Redfish-compatible BMCs
"""
import os
import json
import logging
import httpx
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("redfish")

class RedfishPoller:
    """
    Redfish API poller for HPE iLO and compatible BMC systems.
    Supports auto-discovery of health status, sensors, and events.
    """
    
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.scheduler = AsyncIOScheduler()
        self.security_manager = None  # Set during initialization
        
    def set_security_manager(self, security_manager):
        """Set the security manager for credential decryption."""
        self.security_manager = security_manager
    
    async def start_scheduler(self, interval_minutes: int = 5):
        """Start the Redfish polling scheduler."""
        self.scheduler.add_job(
            self.poll_all_devices,
            IntervalTrigger(minutes=interval_minutes),
            id='redfish_poll',
            name='Redfish Polling Job',
            replace_existing=True
        )
        self.scheduler.start()
        logger.info(f"Redfish polling scheduler started (interval: {interval_minutes} minutes)")
    
    def stop_scheduler(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Redfish polling scheduler stopped")
    
    async def poll_all_devices(self):
        """Poll all devices configured for Redfish monitoring."""
        devices = await self.db.devices.find(
            {
                "device_type": "ilo",
                "redfish_enabled": True
            },
            {"_id": 0}
        ).to_list(1000)
        
        logger.info(f"Starting Redfish poll for {len(devices)} devices")
        
        for device in devices:
            try:
                await self.poll_device(device)
            except Exception as e:
                logger.error(f"Error polling device {device.get('name')}: {e}")
    
    async def poll_device(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """
        Poll a single Redfish-enabled device.
        
        Args:
            device: Device configuration from database
            
        Returns:
            Poll results including health status and any alerts
        """
        device_id = device["id"]
        ip_address = device["ip_address"]
        
        # Get decrypted credentials
        credentials = await self._get_device_credentials(device_id)
        if not credentials:
            logger.warning(f"No credentials found for device {device_id}")
            return {"success": False, "error": "No credentials"}
        
        results = {
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "health": {},
            "alerts": []
        }
        
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                # Get system health
                health_data = await self._get_system_health(client, ip_address, credentials)
                results["health"] = health_data
                
                # Get thermal data
                thermal_data = await self._get_thermal_data(client, ip_address, credentials)
                results["thermal"] = thermal_data
                
                # Get power data
                power_data = await self._get_power_data(client, ip_address, credentials)
                results["power"] = power_data
                
                # Get event log
                events = await self._get_event_log(client, ip_address, credentials)
                
                # Process events and create alerts
                alerts = await self._process_events(device, events, health_data)
                results["alerts"] = alerts
                
                # Update device last poll time
                await self.db.devices.update_one(
                    {"id": device_id},
                    {"$set": {
                        "last_poll": datetime.now(timezone.utc).isoformat(),
                        "last_poll_status": "success",
                        "health_status": health_data.get("Status", {}).get("Health", "Unknown")
                    }}
                )
                
                results["success"] = True
                
        except httpx.TimeoutException:
            results["success"] = False
            results["error"] = "Connection timeout"
            await self._create_connectivity_alert(device, "timeout")
            
        except httpx.ConnectError:
            results["success"] = False
            results["error"] = "Connection failed"
            await self._create_connectivity_alert(device, "connection_failed")
            
        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            logger.error(f"Redfish poll error for {device_id}: {e}")
        
        # Store poll result
        await self.db.redfish_polls.insert_one(results)
        
        return results
    
    async def _get_device_credentials(self, device_id: str) -> Optional[Dict[str, str]]:
        """Get and decrypt device credentials."""
        cred = await self.db.device_credentials.find_one(
            {"device_id": device_id},
            {"_id": 0}
        )
        
        if not cred or not self.security_manager:
            return None
        
        try:
            return {
                "username": self.security_manager.decrypt_credential(cred["username_encrypted"]),
                "password": self.security_manager.decrypt_credential(cred["password_encrypted"])
            }
        except Exception as e:
            logger.error(f"Failed to decrypt credentials for device {device_id}: {e}")
            return None
    
    async def _get_system_health(
        self,
        client: httpx.AsyncClient,
        ip: str,
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """Get system health status via Redfish."""
        try:
            response = await client.get(
                f"https://{ip}/redfish/v1/Systems/1",
                auth=(credentials["username"], credentials["password"])
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _get_thermal_data(
        self,
        client: httpx.AsyncClient,
        ip: str,
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """Get thermal sensor data via Redfish."""
        try:
            response = await client.get(
                f"https://{ip}/redfish/v1/Chassis/1/Thermal",
                auth=(credentials["username"], credentials["password"])
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _get_power_data(
        self,
        client: httpx.AsyncClient,
        ip: str,
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """Get power supply data via Redfish."""
        try:
            response = await client.get(
                f"https://{ip}/redfish/v1/Chassis/1/Power",
                auth=(credentials["username"], credentials["password"])
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _get_event_log(
        self,
        client: httpx.AsyncClient,
        ip: str,
        credentials: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Get IML (Integrated Management Log) events via Redfish."""
        try:
            response = await client.get(
                f"https://{ip}/redfish/v1/Systems/1/LogServices/IML/Entries",
                auth=(credentials["username"], credentials["password"])
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("Members", [])
            return []
        except Exception as e:
            logger.error(f"Failed to get event log: {e}")
            return []
    
    async def _process_events(
        self,
        device: Dict[str, Any],
        events: List[Dict[str, Any]],
        health_data: Dict[str, Any]
    ) -> List[str]:
        """Process Redfish events and create alerts if needed."""
        created_alerts = []
        
        # Check overall health status
        health_status = health_data.get("Status", {}).get("Health", "OK")
        if health_status in ["Critical", "Warning"]:
            alert_id = await self._create_health_alert(device, health_status, health_data)
            if alert_id:
                created_alerts.append(alert_id)
        
        # Process recent events (last hour)
        from datetime import timedelta
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        for event in events[:20]:  # Check last 20 events
            try:
                event_time = datetime.fromisoformat(event.get("Created", "").replace("Z", "+00:00"))
                if event_time > one_hour_ago:
                    severity = self._map_event_severity(event.get("Severity", "OK"))
                    if severity in ["critical", "high"]:
                        alert_id = await self._create_event_alert(device, event)
                        if alert_id:
                            created_alerts.append(alert_id)
            except Exception as e:
                logger.error(f"Error processing event: {e}")
        
        return created_alerts
    
    def _map_event_severity(self, redfish_severity: str) -> str:
        """Map Redfish severity to NOC severity."""
        mapping = {
            "Critical": "critical",
            "Warning": "high",
            "OK": "low"
        }
        return mapping.get(redfish_severity, "medium")
    
    async def _create_health_alert(
        self,
        device: Dict[str, Any],
        health_status: str,
        health_data: Dict[str, Any]
    ) -> Optional[str]:
        """Create an alert for unhealthy system status."""
        import uuid
        
        severity = "critical" if health_status == "Critical" else "high"
        
        # Check for duplicate
        existing = await self.db.alerts.find_one({
            "device_id": device["id"],
            "source_type": "redfish",
            "status": "active",
            "title": {"$regex": "System Health"}
        })
        
        if existing:
            return None
        
        alert_doc = {
            "id": str(uuid.uuid4()),
            "client_id": device["client_id"],
            "device_id": device["id"],
            "severity": severity,
            "source_type": "redfish",
            "title": f"System Health: {health_status}",
            "message": f"iLO reports system health status: {health_status}",
            "raw_data": json.dumps(health_data, indent=2),
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "resolved_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        await self.db.alerts.insert_one(alert_doc)
        
        # Send notification
        if self.notification_service:
            from notifications import NotificationChannel, NotificationPriority
            await self.notification_service.send_notification(
                channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
                title=alert_doc["title"],
                message=alert_doc["message"],
                priority=NotificationPriority.CRITICAL if severity == "critical" else NotificationPriority.HIGH,
                alert_id=alert_doc["id"]
            )
        
        return alert_doc["id"]
    
    async def _create_event_alert(
        self,
        device: Dict[str, Any],
        event: Dict[str, Any]
    ) -> Optional[str]:
        """Create an alert from a Redfish event."""
        import uuid
        
        event_id = event.get("Id", "")
        
        # Check for duplicate
        existing = await self.db.alerts.find_one({
            "device_id": device["id"],
            "source_type": "redfish",
            "raw_data": {"$regex": event_id}
        })
        
        if existing:
            return None
        
        severity = self._map_event_severity(event.get("Severity", "OK"))
        
        alert_doc = {
            "id": str(uuid.uuid4()),
            "client_id": device["client_id"],
            "device_id": device["id"],
            "severity": severity,
            "source_type": "redfish",
            "title": event.get("Name", "Redfish Event"),
            "message": event.get("Message", "No message provided"),
            "raw_data": json.dumps(event, indent=2),
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "resolved_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        await self.db.alerts.insert_one(alert_doc)
        return alert_doc["id"]
    
    async def _create_connectivity_alert(
        self,
        device: Dict[str, Any],
        error_type: str
    ) -> str:
        """Create an alert for device connectivity issues."""
        import uuid
        
        # Check for existing connectivity alert
        existing = await self.db.alerts.find_one({
            "device_id": device["id"],
            "source_type": "redfish",
            "status": "active",
            "title": {"$regex": "Connectivity"}
        })
        
        if existing:
            return existing["id"]
        
        alert_doc = {
            "id": str(uuid.uuid4()),
            "client_id": device["client_id"],
            "device_id": device["id"],
            "severity": "critical",
            "source_type": "redfish",
            "title": f"iLO Connectivity Issue: {error_type}",
            "message": f"Unable to connect to iLO at {device['ip_address']}: {error_type}",
            "raw_data": json.dumps({"error": error_type, "ip": device["ip_address"]}),
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "resolved_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        await self.db.alerts.insert_one(alert_doc)
        return alert_doc["id"]
    
    async def test_connection(self, ip: str, username: str, password: str) -> Dict[str, Any]:
        """Test Redfish connection to a device."""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                response = await client.get(
                    f"https://{ip}/redfish/v1",
                    auth=(username, password)
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "product": data.get("Product", "Unknown"),
                        "version": data.get("RedfishVersion", "Unknown")
                    }
                elif response.status_code == 401:
                    return {"success": False, "error": "Invalid credentials"}
                else:
                    return {"success": False, "error": f"HTTP {response.status_code}"}
                    
        except httpx.TimeoutException:
            return {"success": False, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connection refused"}
        except Exception as e:
            return {"success": False, "error": str(e)}
