"""
NOC Alert Command Center - LDAP/Active Directory Integration
Enterprise SSO support
"""
import os
from typing import Optional, Dict, Any, List
from ldap3 import Server, Connection, ALL, NTLM, SIMPLE
import logging

logger = logging.getLogger("ldap")

class LDAPConfig:
    """LDAP configuration."""
    def __init__(self):
        self.enabled = os.environ.get('LDAP_ENABLED', 'false').lower() == 'true'
        self.server_url = os.environ.get('LDAP_SERVER_URL', '')
        self.base_dn = os.environ.get('LDAP_BASE_DN', '')
        self.bind_dn = os.environ.get('LDAP_BIND_DN', '')
        self.bind_password = os.environ.get('LDAP_BIND_PASSWORD', '')
        self.user_search_filter = os.environ.get('LDAP_USER_FILTER', '(sAMAccountName={username})')
        self.group_search_filter = os.environ.get('LDAP_GROUP_FILTER', '(member={user_dn})')
        self.use_ssl = os.environ.get('LDAP_USE_SSL', 'true').lower() == 'true'
        self.auth_method = os.environ.get('LDAP_AUTH_METHOD', 'SIMPLE')  # SIMPLE or NTLM

class LDAPManager:
    """LDAP/Active Directory authentication manager."""
    
    def __init__(self, db):
        self.db = db
        self.config = LDAPConfig()
    
    async def get_config(self) -> Dict[str, Any]:
        """Get LDAP configuration from database or environment."""
        db_config = await self.db.settings.find_one(
            {"key": "ldap_config"},
            {"_id": 0}
        )
        
        if db_config and db_config.get("value"):
            return db_config["value"]
        
        return {
            "enabled": self.config.enabled,
            "server_url": self.config.server_url,
            "base_dn": self.config.base_dn,
            "user_search_filter": self.config.user_search_filter,
            "use_ssl": self.config.use_ssl
        }
    
    async def save_config(self, config: dict):
        """Save LDAP configuration to database."""
        # Don't save password in plain text - this should be in env vars
        safe_config = {k: v for k, v in config.items() if k != 'bind_password'}
        
        await self.db.settings.update_one(
            {"key": "ldap_config"},
            {"$set": {"key": "ldap_config", "value": safe_config}},
            upsert=True
        )
    
    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate a user against LDAP/AD.
        
        Returns:
            User info dict if successful, None otherwise
        """
        if not self.config.enabled:
            return None
        
        try:
            server = Server(
                self.config.server_url, 
                use_ssl=self.config.use_ssl,
                get_info=ALL
            )
            
            # First bind with service account to search for user
            service_conn = Connection(
                server,
                user=self.config.bind_dn,
                password=self.config.bind_password,
                authentication=SIMPLE
            )
            
            if not service_conn.bind():
                logger.error(f"LDAP service account bind failed: {service_conn.last_error}")
                return None
            
            # Search for user
            search_filter = self.config.user_search_filter.format(username=username)
            service_conn.search(
                self.config.base_dn,
                search_filter,
                attributes=['cn', 'mail', 'memberOf', 'sAMAccountName', 'displayName']
            )
            
            if not service_conn.entries:
                logger.info(f"LDAP user not found: {username}")
                return None
            
            user_entry = service_conn.entries[0]
            user_dn = user_entry.entry_dn
            
            service_conn.unbind()
            
            # Now authenticate with user's credentials
            if self.config.auth_method == 'NTLM':
                user_conn = Connection(
                    server,
                    user=f"{username}",
                    password=password,
                    authentication=NTLM
                )
            else:
                user_conn = Connection(
                    server,
                    user=user_dn,
                    password=password,
                    authentication=SIMPLE
                )
            
            if not user_conn.bind():
                logger.info(f"LDAP authentication failed for: {username}")
                return None
            
            user_conn.unbind()
            
            # Extract user info
            user_info = {
                "username": str(user_entry.sAMAccountName) if hasattr(user_entry, 'sAMAccountName') else username,
                "email": str(user_entry.mail) if hasattr(user_entry, 'mail') else f"{username}@company.com",
                "name": str(user_entry.displayName) if hasattr(user_entry, 'displayName') else str(user_entry.cn),
                "dn": user_dn,
                "groups": [str(g) for g in user_entry.memberOf] if hasattr(user_entry, 'memberOf') else []
            }
            
            logger.info(f"LDAP authentication successful: {username}")
            return user_info
            
        except Exception as e:
            logger.error(f"LDAP authentication error: {e}")
            return None
    
    async def sync_user(self, ldap_user: dict) -> dict:
        """
        Sync LDAP user to local database.
        Creates or updates user record.
        """
        import uuid
        
        existing = await self.db.users.find_one(
            {"email": ldap_user["email"]},
            {"_id": 0}
        )
        
        if existing:
            # Update existing user
            await self.db.users.update_one(
                {"id": existing["id"]},
                {
                    "$set": {
                        "name": ldap_user["name"],
                        "ldap_dn": ldap_user["dn"],
                        "ldap_groups": ldap_user["groups"],
                        "last_ldap_sync": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
                    }
                }
            )
            return existing
        else:
            # Create new user
            user_doc = {
                "id": str(uuid.uuid4()),
                "email": ldap_user["email"],
                "name": ldap_user["name"],
                "password_hash": None,  # No local password for LDAP users
                "role": self._map_groups_to_role(ldap_user["groups"]),
                "auth_type": "ldap",
                "ldap_dn": ldap_user["dn"],
                "ldap_groups": ldap_user["groups"],
                "two_factor_enabled": False,
                "created_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                "last_ldap_sync": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
            }
            await self.db.users.insert_one(user_doc)
            return user_doc
    
    def _map_groups_to_role(self, groups: List[str]) -> str:
        """Map LDAP groups to application roles."""
        # This should be configurable
        group_role_map = {
            "CN=NOC-Admins": "admin",
            "CN=NOC-Operators": "operator",
            "CN=NOC-Viewers": "viewer"
        }
        
        for group in groups:
            for pattern, role in group_role_map.items():
                if pattern in group:
                    return role
        
        return "viewer"  # Default role
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test LDAP connection."""
        if not self.config.enabled:
            return {"success": False, "error": "LDAP not enabled"}
        
        try:
            server = Server(
                self.config.server_url,
                use_ssl=self.config.use_ssl,
                get_info=ALL
            )
            
            conn = Connection(
                server,
                user=self.config.bind_dn,
                password=self.config.bind_password,
                authentication=SIMPLE
            )
            
            if conn.bind():
                info = {
                    "success": True,
                    "server": str(server.info) if server.info else "Connected",
                    "base_dn": self.config.base_dn
                }
                conn.unbind()
                return info
            else:
                return {"success": False, "error": conn.last_error}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
