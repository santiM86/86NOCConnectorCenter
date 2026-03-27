"""
NOC Alert Command Center - Security Hardening
IP Whitelisting, Session Management, Password Policies, Data Retention
"""
import re
import ipaddress
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import secrets
import logging

logger = logging.getLogger("security_hardening")

# Password policy configuration
class PasswordPolicy(BaseModel):
    min_length: int = 12
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True
    max_age_days: int = 90  # Force password change after 90 days
    password_history: int = 5  # Cannot reuse last 5 passwords
    lockout_attempts: int = 5  # Lock after 5 failed attempts
    lockout_duration_minutes: int = 30

DEFAULT_PASSWORD_POLICY = PasswordPolicy()

class SecurityHardening:
    """Enterprise security hardening features."""
    
    def __init__(self, db):
        self.db = db
    
    # ==================== PASSWORD POLICIES ====================
    
    async def get_password_policy(self) -> PasswordPolicy:
        """Get the current password policy."""
        policy_doc = await self.db.settings.find_one(
            {"key": "password_policy"},
            {"_id": 0}
        )
        
        if policy_doc and policy_doc.get("value"):
            return PasswordPolicy(**policy_doc["value"])
        return DEFAULT_PASSWORD_POLICY
    
    async def set_password_policy(self, policy: PasswordPolicy):
        """Update the password policy."""
        await self.db.settings.update_one(
            {"key": "password_policy"},
            {"$set": {"key": "password_policy", "value": policy.model_dump()}},
            upsert=True
        )
    
    def validate_password(self, password: str, policy: PasswordPolicy) -> tuple[bool, List[str]]:
        """
        Validate a password against the policy.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if len(password) < policy.min_length:
            errors.append(f"Password must be at least {policy.min_length} characters")
        
        if policy.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")
        
        if policy.require_lowercase and not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")
        
        if policy.require_digit and not re.search(r'\d', password):
            errors.append("Password must contain at least one digit")
        
        if policy.require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain at least one special character")
        
        return len(errors) == 0, errors
    
    async def check_password_history(
        self, 
        user_id: str, 
        new_password_hash: str,
        security_manager
    ) -> bool:
        """
        Check if the new password was used recently.
        
        Returns:
            True if password is allowed (not in history)
        """
        policy = await self.get_password_policy()
        
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            return True
        
        password_history = user.get("password_history", [])
        
        # Check against recent passwords
        for old_hash in password_history[-policy.password_history:]:
            # We can't directly compare hashes, but we store the hashes
            # This is a simplified check - in production you'd store and compare properly
            if old_hash == new_password_hash:
                return False
        
        return True
    
    async def record_password_change(self, user_id: str, password_hash: str):
        """Record a password change in the user's history."""
        await self.db.users.update_one(
            {"id": user_id},
            {
                "$push": {
                    "password_history": {
                        "$each": [password_hash],
                        "$slice": -10  # Keep last 10
                    }
                },
                "$set": {
                    "password_changed_at": datetime.now(timezone.utc).isoformat()
                }
            }
        )
    
    async def check_password_expired(self, user: dict) -> bool:
        """Check if user's password has expired."""
        policy = await self.get_password_policy()
        
        changed_at = user.get("password_changed_at")
        if not changed_at:
            return False  # No record, assume not expired
        
        changed_date = datetime.fromisoformat(changed_at.replace("Z", "+00:00"))
        expiry_date = changed_date + timedelta(days=policy.max_age_days)
        
        return datetime.now(timezone.utc) > expiry_date
    
    # ==================== ACCOUNT LOCKOUT ====================
    
    async def is_account_locked(self, email: str) -> bool:
        """Check if account is locked by email."""
        user = await self.db.users.find_one({"email": email}, {"_id": 0, "id": 1, "locked": 1, "unlock_at": 1})
        if not user or not user.get("locked"):
            return False
        unlock_at = user.get("unlock_at")
        if unlock_at:
            try:
                unlock_time = datetime.fromisoformat(unlock_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > unlock_time:
                    await self.db.users.update_one(
                        {"email": email},
                        {"$set": {"locked": False}, "$unset": {"locked_at": "", "unlock_at": ""}}
                    )
                    return False
            except Exception:
                pass
        return True
    
    async def clear_failed_logins(self, email: str):
        """Clear failed login attempts for a user by email."""
        user = await self.db.users.find_one({"email": email}, {"_id": 0, "id": 1})
        if user:
            await self.db.login_attempts.delete_many({"user_id": user["id"], "success": False})
            await self.db.users.update_one(
                {"email": email},
                {"$set": {"locked": False}, "$unset": {"locked_at": "", "unlock_at": ""}}
            )

    async def record_failed_login(self, user_id_or_email: str, ip_address: str):
        """Record a failed login attempt. Accepts user_id or email."""
        # Resolve email to user_id if needed
        user_id = user_id_or_email
        if "@" in user_id_or_email:
            user = await self.db.users.find_one({"email": user_id_or_email}, {"_id": 0, "id": 1})
            user_id = user["id"] if user else user_id_or_email
        
        await self.db.login_attempts.insert_one({
            "user_id": user_id,
            "ip_address": ip_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False
        })
        
        # Check if should lock account
        policy = await self.get_password_policy()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=policy.lockout_duration_minutes)).isoformat()
        
        failed_count = await self.db.login_attempts.count_documents({
            "user_id": user_id,
            "success": False,
            "timestamp": {"$gte": cutoff}
        })
        
        if failed_count >= policy.lockout_attempts:
            await self._lock_account(user_id)
    
    async def _lock_account(self, user_id: str):
        """Lock a user account."""
        policy = await self.get_password_policy()
        unlock_at = datetime.now(timezone.utc) + timedelta(minutes=policy.lockout_duration_minutes)
        
        await self.db.users.update_one(
            {"id": user_id},
            {
                "$set": {
                    "locked": True,
                    "locked_at": datetime.now(timezone.utc).isoformat(),
                    "unlock_at": unlock_at.isoformat()
                }
            }
        )
        
        logger.warning(f"Account locked: {user_id}")
    
    async def check_account_locked(self, user_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if an account is locked.
        
        Returns:
            Tuple of (is_locked, unlock_time)
        """
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0})
        if not user or not user.get("locked"):
            return False, None
        
        unlock_at = user.get("unlock_at")
        if unlock_at:
            unlock_time = datetime.fromisoformat(unlock_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > unlock_time:
                # Auto-unlock
                await self.db.users.update_one(
                    {"id": user_id},
                    {"$set": {"locked": False}, "$unset": {"locked_at": "", "unlock_at": ""}}
                )
                return False, None
            return True, unlock_at
        
        return True, None
    
    async def record_successful_login(self, user_id: str, ip_address: str):
        """Record a successful login."""
        await self.db.login_attempts.insert_one({
            "user_id": user_id,
            "ip_address": ip_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True
        })
    
    # ==================== IP WHITELISTING ====================
    
    async def get_ip_whitelist(self) -> List[str]:
        """Get the IP whitelist."""
        setting = await self.db.settings.find_one(
            {"key": "ip_whitelist"},
            {"_id": 0}
        )
        return setting.get("value", []) if setting else []
    
    async def set_ip_whitelist(self, ips: List[str]):
        """Set the IP whitelist."""
        # Validate IPs
        validated = []
        for ip in ips:
            try:
                # Support both individual IPs and CIDR notation
                if '/' in ip:
                    ipaddress.ip_network(ip, strict=False)
                else:
                    ipaddress.ip_address(ip)
                validated.append(ip)
            except ValueError:
                logger.warning(f"Invalid IP in whitelist: {ip}")
        
        await self.db.settings.update_one(
            {"key": "ip_whitelist"},
            {"$set": {"key": "ip_whitelist", "value": validated}},
            upsert=True
        )
    
    async def is_ip_whitelisted(self, ip: str) -> bool:
        """Check if an IP is whitelisted."""
        whitelist = await self.get_ip_whitelist()
        
        if not whitelist:
            return True  # No whitelist = all allowed
        
        try:
            check_ip = ipaddress.ip_address(ip)
            
            for entry in whitelist:
                if '/' in entry:
                    if check_ip in ipaddress.ip_network(entry, strict=False):
                        return True
                else:
                    if check_ip == ipaddress.ip_address(entry):
                        return True
            
            return False
        except ValueError:
            return False
    
    async def is_ip_whitelist_enabled(self) -> bool:
        """Check if IP whitelisting is enabled."""
        setting = await self.db.settings.find_one(
            {"key": "ip_whitelist_enabled"},
            {"_id": 0}
        )
        return setting.get("value", False) if setting else False
    
    async def set_ip_whitelist_enabled(self, enabled: bool):
        """Enable or disable IP whitelisting."""
        await self.db.settings.update_one(
            {"key": "ip_whitelist_enabled"},
            {"$set": {"key": "ip_whitelist_enabled", "value": enabled}},
            upsert=True
        )
    
    # ==================== SESSION MANAGEMENT ====================
    
    async def create_session(
        self, 
        user_id: str, 
        ip_address: str, 
        user_agent: str
    ) -> str:
        """Create a new session and return session ID."""
        session_id = secrets.token_urlsafe(32)
        
        session_doc = {
            "session_id": session_id,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
            "active": True
        }
        
        await self.db.sessions.insert_one(session_doc)
        return session_id
    
    async def get_user_sessions(self, user_id: str) -> List[dict]:
        """Get all active sessions for a user."""
        sessions = await self.db.sessions.find(
            {"user_id": user_id, "active": True},
            {"_id": 0}
        ).sort("last_activity", -1).to_list(100)
        return sessions
    
    async def invalidate_session(self, session_id: str):
        """Invalidate a specific session."""
        await self.db.sessions.update_one(
            {"session_id": session_id},
            {"$set": {"active": False, "ended_at": datetime.now(timezone.utc).isoformat()}}
        )
    
    async def invalidate_all_sessions(self, user_id: str, except_session: Optional[str] = None):
        """Invalidate all sessions for a user (remote logout)."""
        query = {"user_id": user_id, "active": True}
        if except_session:
            query["session_id"] = {"$ne": except_session}
        
        await self.db.sessions.update_many(
            query,
            {"$set": {"active": False, "ended_at": datetime.now(timezone.utc).isoformat()}}
        )
    
    async def update_session_activity(self, session_id: str):
        """Update last activity time for a session."""
        await self.db.sessions.update_one(
            {"session_id": session_id},
            {"$set": {"last_activity": datetime.now(timezone.utc).isoformat()}}
        )
    
    # ==================== DATA RETENTION ====================
    
    async def get_retention_policy(self) -> dict:
        """Get data retention policy."""
        setting = await self.db.settings.find_one(
            {"key": "retention_policy"},
            {"_id": 0}
        )
        
        if setting and setting.get("value"):
            return setting["value"]
        
        # Default retention periods (in days)
        return {
            "alerts": 365,
            "audit_logs": 730,  # 2 years
            "sessions": 30,
            "login_attempts": 90,
            "notification_logs": 90,
            "sla_breaches": 365
        }
    
    async def set_retention_policy(self, policy: dict):
        """Set data retention policy."""
        await self.db.settings.update_one(
            {"key": "retention_policy"},
            {"$set": {"key": "retention_policy", "value": policy}},
            upsert=True
        )
    
    async def run_data_retention_cleanup(self) -> dict:
        """Run data retention cleanup based on policy."""
        policy = await self.get_retention_policy()
        results = {}
        
        collections_config = {
            "alerts": ("created_at", policy.get("alerts", 365)),
            "audit_logs": ("timestamp", policy.get("audit_logs", 730)),
            "sessions": ("created_at", policy.get("sessions", 30)),
            "login_attempts": ("timestamp", policy.get("login_attempts", 90)),
            "notification_logs": ("timestamp", policy.get("notification_logs", 90)),
            "sla_breaches": ("timestamp", policy.get("sla_breaches", 365)),
        }
        
        for collection, (date_field, retention_days) in collections_config.items():
            cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
            
            try:
                result = await self.db[collection].delete_many({
                    date_field: {"$lt": cutoff}
                })
                results[collection] = result.deleted_count
                
                if result.deleted_count > 0:
                    logger.info(f"Retention cleanup: deleted {result.deleted_count} records from {collection}")
            except Exception as e:
                logger.error(f"Retention cleanup error for {collection}: {e}")
                results[collection] = f"error: {str(e)}"
        
        return results


class IPWhitelistUpdate(BaseModel):
    ips: List[str]
    enabled: bool = True

class PasswordPolicyUpdate(BaseModel):
    min_length: int = 12
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True
    max_age_days: int = 90
    password_history: int = 5
    lockout_attempts: int = 5
    lockout_duration_minutes: int = 30

class RetentionPolicyUpdate(BaseModel):
    alerts: int = 365
    audit_logs: int = 730
    sessions: int = 30
    login_attempts: int = 90
    notification_logs: int = 90
    sla_breaches: int = 365
