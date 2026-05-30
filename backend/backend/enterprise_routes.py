"""
NOC Alert Command Center - Enterprise Routes
RBAC, SLA, Maintenance, Reports, Security Hardening endpoints
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone
import io

# Import enterprise modules
from rbac import RBACManager, Role, Permission, ROLE_PERMISSIONS, UserRoleUpdate
from sla import SLAManager, SLAConfigUpdate, DEFAULT_SLA_CONFIGS
from maintenance import MaintenanceManager, MaintenanceWindowCreate, MaintenanceWindowResponse
from correlation import AlertCorrelationManager
from reports import ReportGenerator
from security_hardening import (
    SecurityHardening, PasswordPolicy, IPWhitelistUpdate, 
    PasswordPolicyUpdate, RetentionPolicyUpdate
)
from ldap_auth import LDAPManager

def create_enterprise_router(db, get_current_user, audit_logger):
    """Create enterprise router with all advanced endpoints."""
    
    router = APIRouter(prefix="/api")
    
    # Initialize managers
    rbac_manager = RBACManager(db)
    sla_manager = SLAManager(db)
    maintenance_manager = MaintenanceManager(db)
    correlation_manager = AlertCorrelationManager(db)
    report_generator = ReportGenerator(db)
    security_hardening = SecurityHardening(db)
    ldap_manager = LDAPManager(db)
    
    # ==================== RBAC ROUTES ====================
    
    @router.get("/rbac/roles")
    async def get_roles(current_user: dict = Depends(get_current_user)):
        """Get all available roles and their permissions."""
        roles = []
        for role in Role:
            roles.append({
                "name": role.value,
                "permissions": ROLE_PERMISSIONS.get(role.value, [])
            })
        return roles
    
    @router.get("/rbac/permissions")
    async def get_permissions(current_user: dict = Depends(get_current_user)):
        """Get all available permissions."""
        from rbac import Permission
        return [{"name": p.name, "value": p.value} for p in Permission]
    
    @router.get("/users")
    async def get_users(current_user: dict = Depends(get_current_user)):
        """Get all users (admin only)."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        users = await db.users.find(
            {}, 
            {"_id": 0, "password_hash": 0, "totp_secret": 0, "password_history": 0}
        ).to_list(1000)
        return users
    
    @router.patch("/users/{user_id}/role")
    async def update_user_role(
        user_id: str, 
        update: UserRoleUpdate,
        current_user: dict = Depends(get_current_user)
    ):
        """Update a user's role and permissions."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        if update.role not in [r.value for r in Role]:
            raise HTTPException(status_code=400, detail="Invalid role")
        
        update_data = {"role": update.role}
        if update.assigned_clients is not None:
            update_data["assigned_clients"] = update.assigned_clients
        if update.custom_permissions is not None:
            update_data["custom_permissions"] = update.custom_permissions
        
        result = await db.users.update_one(
            {"id": user_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        from audit import AuditAction
        await audit_logger.log(
            AuditAction.USER_UPDATE,
            user_id=current_user["id"],
            user_email=current_user["email"],
            resource_type="user",
            resource_id=user_id,
            details={"new_role": update.role}
        )
        
        return {"message": "User role updated"}
    
    # ==================== SLA ROUTES ====================
    
    @router.get("/sla/configs")
    async def get_sla_configs(current_user: dict = Depends(get_current_user)):
        """Get SLA configurations for all severities."""
        configs = await db.sla_configs.find({}, {"_id": 0}).to_list(10)
        
        # Merge with defaults
        result = {}
        for severity in ["critical", "high", "medium", "low"]:
            db_config = next((c for c in configs if c.get("severity") == severity), None)
            if db_config:
                result[severity] = db_config
            else:
                result[severity] = DEFAULT_SLA_CONFIGS[severity].model_dump()
        
        return result
    
    @router.post("/sla/configs")
    async def update_sla_config(
        config: SLAConfigUpdate,
        current_user: dict = Depends(get_current_user)
    ):
        """Update SLA configuration for a severity level."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        await db.sla_configs.update_one(
            {"severity": config.severity},
            {"$set": config.model_dump()},
            upsert=True
        )
        
        return {"message": "SLA config updated"}
    
    @router.get("/sla/stats")
    async def get_sla_stats(
        client_id: Optional[str] = None,
        days: int = 30,
        current_user: dict = Depends(get_current_user)
    ):
        """Get SLA statistics and compliance metrics."""
        stats = await sla_manager.get_sla_stats(client_id=client_id, days=days)
        return stats
    
    @router.get("/sla/breaches")
    async def get_sla_breaches(
        client_id: Optional[str] = None,
        days: int = 30,
        limit: int = 100,
        current_user: dict = Depends(get_current_user)
    ):
        """Get list of SLA breaches."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        query = {"timestamp": {"$gte": cutoff}}
        if client_id:
            query["client_id"] = client_id
        
        breaches = await db.sla_breaches.find(
            query, {"_id": 0}
        ).sort("timestamp", -1).to_list(limit)
        
        return breaches
    
    # ==================== MAINTENANCE ROUTES ====================
    
    @router.get("/maintenance/windows")
    async def get_maintenance_windows(
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        current_user: dict = Depends(get_current_user)
    ):
        """Get maintenance windows."""
        windows = await maintenance_manager.get_windows(
            client_id=client_id, 
            status=status
        )
        return windows
    
    @router.get("/maintenance/active")
    async def get_active_maintenance(current_user: dict = Depends(get_current_user)):
        """Get currently active maintenance windows."""
        return await maintenance_manager.get_active_windows()
    
    @router.post("/maintenance/windows")
    async def create_maintenance_window(
        window: MaintenanceWindowCreate,
        current_user: dict = Depends(get_current_user)
    ):
        """Create a new maintenance window."""
        if current_user.get("role") not in ["super_admin", "admin", "operator"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        result = await maintenance_manager.create_window(window, current_user["name"])
        
        from audit import AuditAction
        await audit_logger.log(
            AuditAction.MAINTENANCE_CREATE,
            user_id=current_user["id"],
            user_email=current_user["email"],
            resource_type="maintenance_window",
            resource_id=result["id"],
            details={"name": window.name}
        )
        
        return result
    
    @router.delete("/maintenance/windows/{window_id}")
    async def delete_maintenance_window(
        window_id: str,
        current_user: dict = Depends(get_current_user)
    ):
        """Delete a maintenance window."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        success = await maintenance_manager.delete_window(window_id)
        if not success:
            raise HTTPException(status_code=404, detail="Window not found")
        
        return {"message": "Maintenance window deleted"}
    
    # ==================== CORRELATION ROUTES ====================
    
    @router.get("/correlation/storms")
    async def get_alert_storms(current_user: dict = Depends(get_current_user)):
        """Get active alert storms."""
        return await correlation_manager.get_active_storms()
    
    @router.get("/correlation/groups/{group_id}")
    async def get_correlation_group(
        group_id: str,
        current_user: dict = Depends(get_current_user)
    ):
        """Get a correlation group with all its alerts."""
        group = await correlation_manager.get_correlation_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group
    
    # ==================== REPORT ROUTES ====================
    
    @router.get("/reports/sla/pdf")
    async def generate_sla_report_pdf(
        client_id: Optional[str] = None,
        days: int = 30,
        current_user: dict = Depends(get_current_user)
    ):
        """Generate SLA compliance report as PDF."""
        pdf_bytes = await report_generator.generate_sla_report_pdf(
            client_id=client_id,
            days=days
        )
        
        filename = f"sla_report_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @router.get("/reports/alerts/csv")
    async def generate_alerts_csv(
        client_id: Optional[str] = None,
        days: int = 30,
        status: Optional[str] = None,
        current_user: dict = Depends(get_current_user)
    ):
        """Generate alerts export as CSV."""
        csv_content = await report_generator.generate_alerts_csv(
            client_id=client_id,
            days=days,
            status=status
        )
        
        filename = f"alerts_export_{datetime.now().strftime('%Y%m%d')}.csv"
        
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @router.get("/reports/devices/csv")
    async def generate_devices_csv(
        client_id: Optional[str] = None,
        current_user: dict = Depends(get_current_user)
    ):
        """Generate devices export as CSV."""
        csv_content = await report_generator.generate_devices_csv(client_id=client_id)
        
        filename = f"devices_export_{datetime.now().strftime('%Y%m%d')}.csv"
        
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    # ==================== SECURITY HARDENING ROUTES ====================
    
    @router.get("/security/password-policy")
    async def get_password_policy(current_user: dict = Depends(get_current_user)):
        """Get current password policy."""
        policy = await security_hardening.get_password_policy()
        return policy.model_dump()
    
    @router.post("/security/password-policy")
    async def update_password_policy(
        policy: PasswordPolicyUpdate,
        current_user: dict = Depends(get_current_user)
    ):
        """Update password policy (super_admin only)."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        await security_hardening.set_password_policy(PasswordPolicy(**policy.model_dump()))
        return {"message": "Password policy updated"}
    
    @router.get("/security/ip-whitelist")
    async def get_ip_whitelist(current_user: dict = Depends(get_current_user)):
        """Get IP whitelist configuration."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        ips = await security_hardening.get_ip_whitelist()
        enabled = await security_hardening.is_ip_whitelist_enabled()
        return {"ips": ips, "enabled": enabled}
    
    @router.post("/security/ip-whitelist")
    async def update_ip_whitelist(
        update: IPWhitelistUpdate,
        current_user: dict = Depends(get_current_user)
    ):
        """Update IP whitelist."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        await security_hardening.set_ip_whitelist(update.ips)
        await security_hardening.set_ip_whitelist_enabled(update.enabled)
        return {"message": "IP whitelist updated"}
    
    @router.get("/security/sessions")
    async def get_my_sessions(current_user: dict = Depends(get_current_user)):
        """Get current user's active sessions."""
        sessions = await security_hardening.get_user_sessions(current_user["id"])
        return sessions
    
    @router.delete("/security/sessions/{session_id}")
    async def invalidate_session(
        session_id: str,
        current_user: dict = Depends(get_current_user)
    ):
        """Invalidate a specific session (remote logout)."""
        await security_hardening.invalidate_session(session_id)
        return {"message": "Session invalidated"}
    
    @router.post("/security/sessions/logout-all")
    async def logout_all_sessions(current_user: dict = Depends(get_current_user)):
        """Logout from all other sessions."""
        # Keep current session
        current_session = current_user.get("_session_id")
        await security_hardening.invalidate_all_sessions(
            current_user["id"], 
            except_session=current_session
        )
        return {"message": "All other sessions invalidated"}
    
    @router.get("/security/retention-policy")
    async def get_retention_policy(current_user: dict = Depends(get_current_user)):
        """Get data retention policy."""
        if current_user.get("role") not in ["super_admin", "admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        return await security_hardening.get_retention_policy()
    
    @router.post("/security/retention-policy")
    async def update_retention_policy(
        policy: RetentionPolicyUpdate,
        current_user: dict = Depends(get_current_user)
    ):
        """Update data retention policy."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        await security_hardening.set_retention_policy(policy.model_dump())
        return {"message": "Retention policy updated"}
    
    @router.post("/security/retention/cleanup")
    async def run_retention_cleanup(current_user: dict = Depends(get_current_user)):
        """Manually run data retention cleanup."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        results = await security_hardening.run_data_retention_cleanup()
        return {"message": "Cleanup completed", "results": results}
    
    # ==================== LDAP ROUTES ====================
    
    @router.get("/ldap/config")
    async def get_ldap_config(current_user: dict = Depends(get_current_user)):
        """Get LDAP configuration (without sensitive data)."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        return await ldap_manager.get_config()
    
    @router.post("/ldap/test")
    async def test_ldap_connection(current_user: dict = Depends(get_current_user)):
        """Test LDAP connection."""
        if current_user.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        return await ldap_manager.test_connection()
    
    return router
