"""
NOC Alert Command Center - Alert Correlation & Deduplication
Prevent alert storms and correlate related alerts
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
import hashlib
import logging

logger = logging.getLogger("correlation")

class AlertCorrelationManager:
    """
    Alert correlation and deduplication engine.
    Groups related alerts and prevents alert storms.
    """
    
    def __init__(self, db):
        self.db = db
        # Deduplication window in minutes
        self.dedup_window_minutes = 5
        # Correlation window in minutes
        self.correlation_window_minutes = 15
        # Max alerts per device before storm detection
        self.storm_threshold = 10
        self.storm_window_minutes = 5
    
    def _generate_dedup_key(self, alert: dict) -> str:
        """
        Generate a deduplication key for an alert.
        Same key = potential duplicate.
        """
        key_parts = [
            alert.get("client_id", ""),
            alert.get("device_id", ""),
            alert.get("source_type", ""),
            alert.get("title", ""),
            # Normalize message for comparison
            alert.get("message", "")[:100].lower().strip()
        ]
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    async def check_duplicate(self, alert: dict) -> Tuple[bool, Optional[str]]:
        """
        Check if an alert is a duplicate of a recent alert.
        
        Returns:
            Tuple of (is_duplicate, original_alert_id)
        """
        dedup_key = self._generate_dedup_key(alert)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.dedup_window_minutes)).isoformat()
        
        # Look for recent alerts with same dedup key
        existing = await self.db.alerts.find_one({
            "dedup_key": dedup_key,
            "created_at": {"$gte": cutoff},
            "status": {"$ne": "resolved"}
        }, {"_id": 0})
        
        if existing:
            # Increment duplicate count
            await self.db.alerts.update_one(
                {"id": existing["id"]},
                {
                    "$inc": {"duplicate_count": 1},
                    "$set": {"last_occurrence": datetime.now(timezone.utc).isoformat()}
                }
            )
            logger.info(f"Duplicate alert detected, incrementing count for {existing['id']}")
            return True, existing["id"]
        
        return False, None
    
    async def check_alert_storm(self, client_id: str, device_id: str) -> Tuple[bool, int]:
        """
        Check if there's an alert storm for a device.
        
        Returns:
            Tuple of (is_storm, alert_count)
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.storm_window_minutes)).isoformat()
        
        count = await self.db.alerts.count_documents({
            "device_id": device_id,
            "created_at": {"$gte": cutoff}
        })
        
        if count >= self.storm_threshold:
            # Check if storm already recorded
            existing_storm = await self.db.alert_storms.find_one({
                "device_id": device_id,
                "status": "active"
            })
            
            if not existing_storm:
                # Record new storm
                await self._record_storm(client_id, device_id, count)
            
            return True, count
        
        return False, count
    
    async def _record_storm(self, client_id: str, device_id: str, alert_count: int):
        """Record an alert storm event."""
        import uuid
        
        storm_doc = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_id": device_id,
            "alert_count": alert_count,
            "status": "active",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "suppressed_alerts": 0
        }
        
        await self.db.alert_storms.insert_one(storm_doc)
        logger.warning(f"Alert storm detected for device {device_id}: {alert_count} alerts")
    
    async def correlate_alerts(self, alert: dict) -> Optional[str]:
        """
        Find correlated alerts and potentially group them.
        
        Returns:
            Correlation group ID if correlated, None otherwise
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.correlation_window_minutes)).isoformat()
        
        # Find recent alerts from same device
        related_alerts = await self.db.alerts.find({
            "device_id": alert.get("device_id"),
            "created_at": {"$gte": cutoff},
            "status": {"$ne": "resolved"},
            "id": {"$ne": alert.get("id")}
        }, {"_id": 0}).to_list(100)
        
        if not related_alerts:
            return None
        
        # Check if there's already a correlation group
        for related in related_alerts:
            if related.get("correlation_group_id"):
                # Add to existing group
                group_id = related["correlation_group_id"]
                await self._add_to_correlation_group(alert["id"], group_id)
                return group_id
        
        # Create new correlation group if multiple alerts
        if len(related_alerts) >= 2:
            group_id = await self._create_correlation_group(
                alert, 
                related_alerts
            )
            return group_id
        
        return None
    
    async def _create_correlation_group(
        self, 
        new_alert: dict, 
        related_alerts: list
    ) -> str:
        """Create a new correlation group."""
        import uuid
        
        group_id = str(uuid.uuid4())
        
        # Create group document
        group_doc = {
            "id": group_id,
            "device_id": new_alert.get("device_id"),
            "client_id": new_alert.get("client_id"),
            "alert_ids": [new_alert["id"]] + [a["id"] for a in related_alerts],
            "alert_count": len(related_alerts) + 1,
            "primary_alert_id": new_alert["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active"
        }
        
        await self.db.correlation_groups.insert_one(group_doc)
        
        # Update all alerts with group ID
        all_ids = [new_alert["id"]] + [a["id"] for a in related_alerts]
        await self.db.alerts.update_many(
            {"id": {"$in": all_ids}},
            {"$set": {"correlation_group_id": group_id}}
        )
        
        logger.info(f"Created correlation group {group_id} with {len(all_ids)} alerts")
        return group_id
    
    async def _add_to_correlation_group(self, alert_id: str, group_id: str):
        """Add an alert to an existing correlation group."""
        await self.db.correlation_groups.update_one(
            {"id": group_id},
            {
                "$push": {"alert_ids": alert_id},
                "$inc": {"alert_count": 1}
            }
        )
        
        await self.db.alerts.update_one(
            {"id": alert_id},
            {"$set": {"correlation_group_id": group_id}}
        )
    
    async def get_correlation_group(self, group_id: str) -> Optional[dict]:
        """Get a correlation group with all its alerts."""
        group = await self.db.correlation_groups.find_one(
            {"id": group_id},
            {"_id": 0}
        )
        
        if group:
            # Fetch all alerts in the group
            alerts = await self.db.alerts.find(
                {"id": {"$in": group["alert_ids"]}},
                {"_id": 0}
            ).to_list(1000)
            group["alerts"] = alerts
        
        return group
    
    async def get_active_storms(self) -> List[dict]:
        """Get all active alert storms."""
        storms = await self.db.alert_storms.find(
            {"status": "active"},
            {"_id": 0}
        ).to_list(100)
        
        # Enrich with device info
        for storm in storms:
            device = await self.db.devices.find_one(
                {"id": storm["device_id"]},
                {"_id": 0, "name": 1, "ip_address": 1}
            )
            if device:
                storm["device_name"] = device.get("name")
                storm["ip_address"] = device.get("ip_address")
        
        return storms
    
    async def end_storm(self, device_id: str):
        """End an active storm for a device."""
        await self.db.alert_storms.update_one(
            {"device_id": device_id, "status": "active"},
            {
                "$set": {
                    "status": "resolved",
                    "ended_at": datetime.now(timezone.utc).isoformat()
                }
            }
        )
    
    async def prepare_alert_for_storage(self, alert: dict) -> dict:
        """
        Prepare an alert for storage with deduplication key and correlation.
        
        Returns the prepared alert dict with additional fields.
        """
        alert["dedup_key"] = self._generate_dedup_key(alert)
        alert["duplicate_count"] = 0
        alert["last_occurrence"] = alert.get("created_at")
        alert["correlation_group_id"] = None
        
        return alert
