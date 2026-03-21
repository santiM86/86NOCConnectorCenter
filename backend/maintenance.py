"""
NOC Alert Command Center - Maintenance Windows
Schedule maintenance periods to suppress alerts
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import logging

logger = logging.getLogger("maintenance")

class MaintenanceWindowCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    client_id: Optional[str] = None  # None = all clients
    device_ids: Optional[List[str]] = None  # None = all devices for client
    start_time: str  # ISO format
    end_time: str  # ISO format
    suppress_alerts: bool = True
    suppress_severities: List[str] = ["low", "medium"]  # Only suppress these severities
    recurring: bool = False
    recurrence_pattern: Optional[str] = None  # "daily", "weekly", "monthly"
    recurrence_days: Optional[List[int]] = None  # For weekly: 0=Mon, 6=Sun

class MaintenanceWindowResponse(BaseModel):
    id: str
    name: str
    description: str
    client_id: Optional[str]
    client_name: Optional[str] = None
    device_ids: Optional[List[str]]
    start_time: str
    end_time: str
    suppress_alerts: bool
    suppress_severities: List[str]
    recurring: bool
    recurrence_pattern: Optional[str]
    recurrence_days: Optional[List[int]]
    status: str  # scheduled, active, completed
    created_by: str
    created_at: str

class MaintenanceManager:
    """Maintenance window manager."""
    
    def __init__(self, db):
        self.db = db
    
    async def is_in_maintenance(
        self, 
        client_id: str, 
        device_id: str, 
        severity: str
    ) -> tuple[bool, Optional[dict]]:
        """
        Check if a device is currently in a maintenance window.
        
        Returns:
            Tuple of (is_in_maintenance, maintenance_window_info)
        """
        now = datetime.now(timezone.utc).isoformat()
        
        # Find active maintenance windows
        windows = await self.db.maintenance_windows.find({
            "$and": [
                {"start_time": {"$lte": now}},
                {"end_time": {"$gte": now}},
                {"suppress_alerts": True},
                {
                    "$or": [
                        {"client_id": None},  # Global maintenance
                        {"client_id": client_id}
                    ]
                },
                {
                    "$or": [
                        {"device_ids": None},  # All devices
                        {"device_ids": []},  # All devices
                        {"device_ids": device_id}
                    ]
                }
            ]
        }, {"_id": 0}).to_list(100)
        
        for window in windows:
            # Check if severity should be suppressed
            suppress_severities = window.get("suppress_severities", ["low", "medium"])
            if severity in suppress_severities:
                return True, window
        
        return False, None
    
    async def create_window(
        self, 
        window: MaintenanceWindowCreate, 
        created_by: str
    ) -> dict:
        """Create a new maintenance window."""
        import uuid
        
        window_doc = {
            "id": str(uuid.uuid4()),
            "name": window.name,
            "description": window.description or "",
            "client_id": window.client_id,
            "device_ids": window.device_ids,
            "start_time": window.start_time,
            "end_time": window.end_time,
            "suppress_alerts": window.suppress_alerts,
            "suppress_severities": window.suppress_severities,
            "recurring": window.recurring,
            "recurrence_pattern": window.recurrence_pattern,
            "recurrence_days": window.recurrence_days,
            "status": self._calculate_status(window.start_time, window.end_time),
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        await self.db.maintenance_windows.insert_one(window_doc)
        logger.info(f"Maintenance window created: {window.name}")
        
        return window_doc
    
    async def get_windows(
        self, 
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[dict]:
        """Get maintenance windows."""
        query = {}
        if client_id:
            query["$or"] = [{"client_id": None}, {"client_id": client_id}]
        if status:
            query["status"] = status
        
        windows = await self.db.maintenance_windows.find(
            query, {"_id": 0}
        ).sort("start_time", -1).to_list(limit)
        
        # Update statuses
        now = datetime.now(timezone.utc).isoformat()
        for window in windows:
            window["status"] = self._calculate_status(window["start_time"], window["end_time"])
        
        return windows
    
    async def get_active_windows(self) -> List[dict]:
        """Get currently active maintenance windows."""
        now = datetime.now(timezone.utc).isoformat()
        
        windows = await self.db.maintenance_windows.find({
            "start_time": {"$lte": now},
            "end_time": {"$gte": now}
        }, {"_id": 0}).to_list(100)
        
        for window in windows:
            window["status"] = "active"
        
        return windows
    
    async def delete_window(self, window_id: str) -> bool:
        """Delete a maintenance window."""
        result = await self.db.maintenance_windows.delete_one({"id": window_id})
        return result.deleted_count > 0
    
    async def update_window(self, window_id: str, updates: dict) -> Optional[dict]:
        """Update a maintenance window."""
        allowed_fields = [
            "name", "description", "start_time", "end_time", 
            "suppress_alerts", "suppress_severities", "device_ids"
        ]
        
        update_data = {k: v for k, v in updates.items() if k in allowed_fields}
        
        if update_data:
            await self.db.maintenance_windows.update_one(
                {"id": window_id},
                {"$set": update_data}
            )
        
        return await self.db.maintenance_windows.find_one({"id": window_id}, {"_id": 0})
    
    def _calculate_status(self, start_time: str, end_time: str) -> str:
        """Calculate the current status of a maintenance window."""
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        if now < start:
            return "scheduled"
        elif now > end:
            return "completed"
        else:
            return "active"
    
    async def cleanup_old_windows(self, days_to_keep: int = 90):
        """Clean up completed maintenance windows older than specified days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).isoformat()
        
        result = await self.db.maintenance_windows.delete_many({
            "end_time": {"$lt": cutoff},
            "recurring": False
        })
        
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} old maintenance windows")
