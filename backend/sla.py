"""
NOC Alert Command Center - SLA & Escalation System
Enterprise-grade SLA tracking and automatic escalation
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from enum import Enum
from pydantic import BaseModel
import logging

logger = logging.getLogger("sla")

class EscalationLevel(str, Enum):
    L1 = "L1"  # First responder
    L2 = "L2"  # Senior operator
    L3 = "L3"  # Team lead
    L4 = "L4"  # Manager
    L5 = "L5"  # Director/Emergency

class SLAConfig(BaseModel):
    severity: str
    response_time_minutes: int  # Time to acknowledge
    resolution_time_minutes: int  # Time to resolve
    escalation_intervals: List[int]  # Minutes before each escalation level

# Default SLA configurations
DEFAULT_SLA_CONFIGS = {
    "critical": SLAConfig(
        severity="critical",
        response_time_minutes=5,
        resolution_time_minutes=60,
        escalation_intervals=[5, 15, 30, 60, 120]  # L1 at 5min, L2 at 15min, etc.
    ),
    "high": SLAConfig(
        severity="high",
        response_time_minutes=15,
        resolution_time_minutes=240,
        escalation_intervals=[15, 30, 60, 120, 240]
    ),
    "medium": SLAConfig(
        severity="medium",
        response_time_minutes=60,
        resolution_time_minutes=480,
        escalation_intervals=[60, 120, 240, 480]
    ),
    "low": SLAConfig(
        severity="low",
        response_time_minutes=240,
        resolution_time_minutes=1440,
        escalation_intervals=[240, 480, 720, 1440]
    ),
}

class SLAManager:
    """SLA tracking and automatic escalation manager."""
    
    def __init__(self, db, notification_service=None):
        self.db = db
        self.notification_service = notification_service
        self._running = False
    
    async def start_monitoring(self, check_interval_seconds: int = 60):
        """Start the SLA monitoring background task."""
        self._running = True
        logger.info("SLA monitoring started")
        
        while self._running:
            try:
                await self._check_sla_violations()
            except Exception as e:
                logger.error(f"SLA check error: {e}")
            
            await asyncio.sleep(check_interval_seconds)
    
    def stop_monitoring(self):
        """Stop the SLA monitoring."""
        self._running = False
        logger.info("SLA monitoring stopped")
    
    async def _check_sla_violations(self):
        """Check for SLA violations and escalations."""
        # Get all active alerts
        active_alerts = await self.db.alerts.find(
            {"status": {"$in": ["active", "acknowledged"]}},
            {"_id": 0}
        ).to_list(10000)
        
        now = datetime.now(timezone.utc)
        
        for alert in active_alerts:
            await self._process_alert_sla(alert, now)
    
    async def _process_alert_sla(self, alert: dict, now: datetime):
        """Process SLA for a single alert."""
        severity = alert.get("severity", "medium")
        created_at = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
        
        # Get SLA config
        sla_config = await self._get_sla_config(severity)
        
        # Calculate elapsed time
        elapsed_minutes = (now - created_at).total_seconds() / 60
        
        # Check response SLA (time to acknowledge)
        if alert["status"] == "active":
            if elapsed_minutes > sla_config["response_time_minutes"]:
                await self._record_sla_breach(alert, "response", elapsed_minutes)
        
        # Check resolution SLA
        if alert["status"] != "resolved":
            if elapsed_minutes > sla_config["resolution_time_minutes"]:
                await self._record_sla_breach(alert, "resolution", elapsed_minutes)
        
        # Check escalation
        current_level = alert.get("escalation_level", 0)
        escalation_intervals = sla_config.get("escalation_intervals", [])
        
        for i, interval in enumerate(escalation_intervals):
            if elapsed_minutes >= interval and current_level <= i:
                await self._escalate_alert(alert, i + 1, elapsed_minutes)
                break
    
    async def _get_sla_config(self, severity: str) -> dict:
        """Get SLA configuration for a severity level."""
        # Try to get custom config from database
        config = await self.db.sla_configs.find_one(
            {"severity": severity},
            {"_id": 0}
        )
        
        if config:
            return config
        
        # Fall back to default
        default = DEFAULT_SLA_CONFIGS.get(severity, DEFAULT_SLA_CONFIGS["medium"])
        return default.model_dump()
    
    async def _record_sla_breach(self, alert: dict, breach_type: str, elapsed_minutes: float):
        """Record an SLA breach."""
        breach_key = f"sla_{breach_type}_breached"
        
        # Only record once
        if alert.get(breach_key):
            return
        
        await self.db.alerts.update_one(
            {"id": alert["id"]},
            {
                "$set": {
                    breach_key: True,
                    f"sla_{breach_type}_breach_at": datetime.now(timezone.utc).isoformat(),
                    f"sla_{breach_type}_elapsed_minutes": elapsed_minutes
                }
            }
        )
        
        # Log breach
        await self.db.sla_breaches.insert_one({
            "alert_id": alert["id"],
            "client_id": alert.get("client_id"),
            "device_id": alert.get("device_id"),
            "severity": alert.get("severity"),
            "breach_type": breach_type,
            "elapsed_minutes": elapsed_minutes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        logger.warning(f"SLA {breach_type} breach for alert {alert['id']}: {elapsed_minutes:.1f} minutes")
        
        # Send notification
        if self.notification_service:
            from notifications import NotificationChannel, NotificationPriority
            await self.notification_service.send_notification(
                channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
                title=f"SLA BREACH: {breach_type.upper()}",
                message=f"Alert '{alert['title']}' has breached {breach_type} SLA after {elapsed_minutes:.0f} minutes",
                priority=NotificationPriority.CRITICAL,
                alert_id=alert["id"]
            )
    
    async def _escalate_alert(self, alert: dict, new_level: int, elapsed_minutes: float):
        """Escalate an alert to a higher level."""
        level_names = ["", "L1", "L2", "L3", "L4", "L5"]
        level_name = level_names[new_level] if new_level < len(level_names) else f"L{new_level}"
        
        await self.db.alerts.update_one(
            {"id": alert["id"]},
            {
                "$set": {
                    "escalation_level": new_level,
                    f"escalated_to_{level_name}_at": datetime.now(timezone.utc).isoformat()
                },
                "$push": {
                    "escalation_history": {
                        "level": level_name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elapsed_minutes": elapsed_minutes
                    }
                }
            }
        )
        
        logger.info(f"Alert {alert['id']} escalated to {level_name} after {elapsed_minutes:.1f} minutes")
        
        # Send escalation notification
        if self.notification_service:
            from notifications import NotificationChannel, NotificationPriority
            await self.notification_service.send_notification(
                channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH, NotificationChannel.TEAMS],
                title=f"ESCALATION {level_name}: {alert['title']}",
                message=f"Alert escalated to {level_name} - unresolved for {elapsed_minutes:.0f} minutes",
                priority=NotificationPriority.CRITICAL,
                alert_id=alert["id"]
            )
    
    async def get_sla_stats(self, client_id: Optional[str] = None, days: int = 30) -> dict:
        """Get SLA statistics for reporting."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        query = {"created_at": {"$gte": cutoff}}
        if client_id:
            query["client_id"] = client_id
        
        alerts = await self.db.alerts.find(query, {"_id": 0}).to_list(100000)
        
        total = len(alerts)
        resolved = sum(1 for a in alerts if a["status"] == "resolved")
        response_breaches = sum(1 for a in alerts if a.get("sla_response_breached"))
        resolution_breaches = sum(1 for a in alerts if a.get("sla_resolution_breached"))
        
        # Calculate average response times
        response_times = []
        resolution_times = []
        
        for alert in alerts:
            if alert.get("acknowledged_at"):
                created = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
                acked = datetime.fromisoformat(alert["acknowledged_at"].replace("Z", "+00:00"))
                response_times.append((acked - created).total_seconds() / 60)
            
            if alert.get("resolved_at"):
                created = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
                resolved_at = datetime.fromisoformat(alert["resolved_at"].replace("Z", "+00:00"))
                resolution_times.append((resolved_at - created).total_seconds() / 60)
        
        return {
            "period_days": days,
            "total_alerts": total,
            "resolved_alerts": resolved,
            "resolution_rate": (resolved / total * 100) if total > 0 else 0,
            "response_sla_breaches": response_breaches,
            "resolution_sla_breaches": resolution_breaches,
            "response_sla_compliance": ((total - response_breaches) / total * 100) if total > 0 else 100,
            "resolution_sla_compliance": ((total - resolution_breaches) / total * 100) if total > 0 else 100,
            "avg_response_time_minutes": sum(response_times) / len(response_times) if response_times else 0,
            "avg_resolution_time_minutes": sum(resolution_times) / len(resolution_times) if resolution_times else 0,
            "by_severity": await self._get_stats_by_severity(alerts)
        }
    
    async def _get_stats_by_severity(self, alerts: list) -> dict:
        """Get SLA stats broken down by severity."""
        stats = {}
        for severity in ["critical", "high", "medium", "low"]:
            severity_alerts = [a for a in alerts if a.get("severity") == severity]
            total = len(severity_alerts)
            if total == 0:
                continue
            
            resolved = sum(1 for a in severity_alerts if a["status"] == "resolved")
            response_breaches = sum(1 for a in severity_alerts if a.get("sla_response_breached"))
            resolution_breaches = sum(1 for a in severity_alerts if a.get("sla_resolution_breached"))
            
            stats[severity] = {
                "total": total,
                "resolved": resolved,
                "response_breaches": response_breaches,
                "resolution_breaches": resolution_breaches,
                "response_compliance": ((total - response_breaches) / total * 100) if total > 0 else 100,
                "resolution_compliance": ((total - resolution_breaches) / total * 100) if total > 0 else 100
            }
        
        return stats


class SLAConfigUpdate(BaseModel):
    severity: str
    response_time_minutes: int
    resolution_time_minutes: int
    escalation_intervals: List[int]
