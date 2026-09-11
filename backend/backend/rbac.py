"""
NOC Alert Command Center - RBAC (Role-Based Access Control)
Enterprise-grade permission system
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from functools import wraps
from fastapi import HTTPException, Depends
from pydantic import BaseModel

class Permission(str, Enum):
    # Alert permissions
    ALERT_VIEW = "alert:view"
    ALERT_CREATE = "alert:create"
    ALERT_ACKNOWLEDGE = "alert:acknowledge"
    ALERT_RESOLVE = "alert:resolve"
    ALERT_DELETE = "alert:delete"
    
    # Client permissions
    CLIENT_VIEW = "client:view"
    CLIENT_CREATE = "client:create"
    CLIENT_UPDATE = "client:update"
    CLIENT_DELETE = "client:delete"
    
    # Device permissions
    DEVICE_VIEW = "device:view"
    DEVICE_CREATE = "device:create"
    DEVICE_UPDATE = "device:update"
    DEVICE_DELETE = "device:delete"
    DEVICE_CREDENTIALS = "device:credentials"
    
    # User management
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_ROLE_ASSIGN = "user:role_assign"
    
    # System settings
    SETTINGS_VIEW = "settings:view"
    SETTINGS_UPDATE = "settings:update"
    
    # Reports
    REPORT_VIEW = "report:view"
    REPORT_GENERATE = "report:generate"
    REPORT_EXPORT = "report:export"
    
    # Audit
    AUDIT_VIEW = "audit:view"
    
    # Maintenance
    MAINTENANCE_VIEW = "maintenance:view"
    MAINTENANCE_CREATE = "maintenance:create"
    MAINTENANCE_UPDATE = "maintenance:update"
    MAINTENANCE_DELETE = "maintenance:delete"
    
    # SLA
    SLA_VIEW = "sla:view"
    SLA_MANAGE = "sla:manage"

class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    CLIENT_ADMIN = "client_admin"  # Can only manage their assigned clients

# Role-Permission mapping
ROLE_PERMISSIONS: Dict[str, List[str]] = {
    Role.SUPER_ADMIN.value: [p.value for p in Permission],  # All permissions
    
    Role.ADMIN.value: [
        Permission.ALERT_VIEW.value, Permission.ALERT_CREATE.value, 
        Permission.ALERT_ACKNOWLEDGE.value, Permission.ALERT_RESOLVE.value,
        Permission.CLIENT_VIEW.value, Permission.CLIENT_CREATE.value,
        Permission.CLIENT_UPDATE.value, Permission.CLIENT_DELETE.value,
        Permission.DEVICE_VIEW.value, Permission.DEVICE_CREATE.value,
        Permission.DEVICE_UPDATE.value, Permission.DEVICE_DELETE.value,
        Permission.DEVICE_CREDENTIALS.value,
        Permission.USER_VIEW.value, Permission.USER_CREATE.value,
        Permission.USER_UPDATE.value,
        Permission.SETTINGS_VIEW.value, Permission.SETTINGS_UPDATE.value,
        Permission.REPORT_VIEW.value, Permission.REPORT_GENERATE.value,
        Permission.REPORT_EXPORT.value,
        Permission.AUDIT_VIEW.value,
        Permission.MAINTENANCE_VIEW.value, Permission.MAINTENANCE_CREATE.value,
        Permission.MAINTENANCE_UPDATE.value, Permission.MAINTENANCE_DELETE.value,
        Permission.SLA_VIEW.value, Permission.SLA_MANAGE.value,
    ],
    
    Role.OPERATOR.value: [
        Permission.ALERT_VIEW.value, Permission.ALERT_ACKNOWLEDGE.value,
        Permission.ALERT_RESOLVE.value,
        Permission.CLIENT_VIEW.value,
        Permission.DEVICE_VIEW.value,
        Permission.REPORT_VIEW.value,
        Permission.MAINTENANCE_VIEW.value,
        Permission.SLA_VIEW.value,
    ],
    
    Role.VIEWER.value: [
        Permission.ALERT_VIEW.value,
        Permission.CLIENT_VIEW.value,
        Permission.DEVICE_VIEW.value,
        Permission.REPORT_VIEW.value,
        Permission.SLA_VIEW.value,
    ],
    
    Role.CLIENT_ADMIN.value: [
        Permission.ALERT_VIEW.value, Permission.ALERT_ACKNOWLEDGE.value,
        Permission.ALERT_RESOLVE.value,
        Permission.CLIENT_VIEW.value,
        Permission.DEVICE_VIEW.value,
        Permission.REPORT_VIEW.value,
        Permission.SLA_VIEW.value,
    ],
}

class RBACManager:
    """Role-Based Access Control Manager."""
    
    def __init__(self, db):
        self.db = db
    
    def get_role_permissions(self, role: str) -> List[str]:
        """Get all permissions for a role."""
        return ROLE_PERMISSIONS.get(role, [])
    
    def has_permission(self, user: dict, permission: str) -> bool:
        """Check if user has a specific permission."""
        role = user.get("role", "viewer")
        permissions = self.get_role_permissions(role)
        
        # Also check custom permissions assigned to user
        custom_permissions = user.get("custom_permissions", [])
        all_permissions = set(permissions) | set(custom_permissions)
        
        return permission in all_permissions
    
    async def check_client_access(self, user: dict, client_id: str) -> bool:
        """Check if user has access to a specific client (for client_admin role)."""
        if user.get("role") in [Role.SUPER_ADMIN.value, Role.ADMIN.value]:
            return True
        
        # Client admins can only access their assigned clients
        assigned_clients = user.get("assigned_clients", [])
        return client_id in assigned_clients or not assigned_clients
    
    async def filter_clients_for_user(self, user: dict, clients: list) -> list:
        """Filter clients based on user access."""
        if user.get("role") in [Role.SUPER_ADMIN.value, Role.ADMIN.value]:
            return clients
        
        assigned_clients = user.get("assigned_clients", [])
        if not assigned_clients:
            return clients
        
        return [c for c in clients if c["id"] in assigned_clients]


def require_permission(permission: Permission):
    """Decorator to require a specific permission."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user: dict = None, **kwargs):
            if current_user is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            
            role = current_user.get("role", "viewer")
            permissions = ROLE_PERMISSIONS.get(role, [])
            custom_permissions = current_user.get("custom_permissions", [])
            all_permissions = set(permissions) | set(custom_permissions)
            
            if permission.value not in all_permissions:
                raise HTTPException(
                    status_code=403, 
                    detail=f"Permission denied: {permission.value} required"
                )
            
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator


class RoleCreate(BaseModel):
    name: str
    description: str
    permissions: List[str]

class UserRoleUpdate(BaseModel):
    role: str
    assigned_clients: Optional[List[str]] = None
    custom_permissions: Optional[List[str]] = None
