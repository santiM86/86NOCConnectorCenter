"""
NOC Alert Command Center - Audit Logging System
Complete audit trail for security compliance
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
import os
from enum import Enum

class AuditAction(str, Enum):
    # Authentication
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    REGISTER = "register"
    PASSWORD_CHANGE = "password_change"
    TWO_FA_ENABLED = "2fa_enabled"
    TWO_FA_DISABLED = "2fa_disabled"
    TWO_FA_VERIFIED = "2fa_verified"
    TWO_FA_FAILED = "2fa_failed"
    
    # Data Access
    VIEW_ALERT = "view_alert"
    VIEW_ALERTS = "view_alerts"
    VIEW_CLIENT = "view_client"
    VIEW_DEVICE = "view_device"
    VIEW_CREDENTIALS = "view_credentials"
    
    # Data Modification
    CREATE_ALERT = "create_alert"
    UPDATE_ALERT = "update_alert"
    DELETE_ALERT = "delete_alert"
    CREATE_CLIENT = "create_client"
    UPDATE_CLIENT = "update_client"
    DELETE_CLIENT = "delete_client"
    CREATE_DEVICE = "create_device"
    UPDATE_DEVICE = "update_device"
    DELETE_DEVICE = "delete_device"
    
    # Credential Management
    STORE_CREDENTIAL = "store_credential"
    UPDATE_CREDENTIAL = "update_credential"
    DELETE_CREDENTIAL = "delete_credential"
    DECRYPT_CREDENTIAL = "decrypt_credential"
    
    # System Actions
    API_KEY_GENERATED = "api_key_generated"
    API_KEY_REVOKED = "api_key_revoked"
    REDFISH_POLL = "redfish_poll"
    NOTIFICATION_SENT = "notification_sent"
    WEBHOOK_TRIGGERED = "webhook_triggered"
    
    # Maintenance
    MAINTENANCE_CREATE = "maintenance_create"
    MAINTENANCE_UPDATE = "maintenance_update"
    MAINTENANCE_DELETE = "maintenance_delete"
    
    # User Management
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    
    # Security Events
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    IP_BLOCKED = "ip_blocked"

class AuditLogger:
    """Audit logger for tracking all security-relevant events."""
    
    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger("audit")
    
    async def log(
        self,
        action: AuditAction,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        severity: str = "info"
    ):
        """
        Log an audit event to the database.
        
        Args:
            action: The type of action being logged
            user_id: ID of the user performing the action
            user_email: Email of the user
            ip_address: IP address of the request
            user_agent: User agent string
            resource_type: Type of resource affected (alert, client, device, etc.)
            resource_id: ID of the affected resource
            details: Additional details about the action
            success: Whether the action was successful
            severity: Log severity (info, warning, error, critical)
        """
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action.value,
            "user_id": user_id,
            "user_email": user_email,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "success": success,
            "severity": severity
        }
        
        try:
            await self.db.audit_logs.insert_one(audit_entry)
            
            # Also log to standard logger for immediate visibility
            log_msg = f"[AUDIT] {action.value} | User: {user_email} | IP: {ip_address} | Success: {success}"
            if severity == "critical":
                self.logger.critical(log_msg)
            elif severity == "error":
                self.logger.error(log_msg)
            elif severity == "warning":
                self.logger.warning(log_msg)
            else:
                self.logger.info(log_msg)
                
        except Exception as e:
            self.logger.error(f"Failed to write audit log: {e}")
    
    async def get_user_activity(
        self,
        user_id: str,
        limit: int = 100,
        actions: Optional[list] = None
    ) -> list:
        """Get audit logs for a specific user."""
        query = {"user_id": user_id}
        if actions:
            query["action"] = {"$in": [a.value for a in actions]}
        
        logs = await self.db.audit_logs.find(
            query, {"_id": 0}
        ).sort("timestamp", -1).to_list(limit)
        
        return logs
    
    async def get_security_events(self, hours: int = 24, limit: int = 1000) -> list:
        """Get security-related events from the last N hours."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        security_actions = [
            AuditAction.LOGIN_FAILED.value,
            AuditAction.TWO_FA_FAILED.value,
            AuditAction.RATE_LIMIT_EXCEEDED.value,
            AuditAction.SUSPICIOUS_ACTIVITY.value,
            AuditAction.IP_BLOCKED.value
        ]
        
        logs = await self.db.audit_logs.find(
            {
                "timestamp": {"$gte": cutoff},
                "action": {"$in": security_actions}
            },
            {"_id": 0}
        ).sort("timestamp", -1).to_list(limit)
        
        return logs
    
    async def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 50
    ) -> list:
        """Get audit history for a specific resource."""
        logs = await self.db.audit_logs.find(
            {
                "resource_type": resource_type,
                "resource_id": resource_id
            },
            {"_id": 0}
        ).sort("timestamp", -1).to_list(limit)
        
        return logs
