"""
In-Memory Session Cache - Token di sessione con UUID crittografico.
- Cache sessioni con TTL 5 minuti e max 500 sessioni in memoria.
- Auto-eviction delle sessioni scadute.
"""
import time
import secrets
import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("session_cache")

SESSION_TTL_SECONDS = 300  # 5 minuti
MAX_SESSIONS = 500


class SessionEntry:
    __slots__ = ("user_id", "email", "role", "created_at", "last_access")

    def __init__(self, user_id: str, email: str, role: str):
        self.user_id = user_id
        self.email = email
        self.role = role
        now = time.time()
        self.created_at = now
        self.last_access = now

    def is_expired(self, now: float) -> bool:
        return (now - self.last_access) > SESSION_TTL_SECONDS

    def touch(self):
        self.last_access = time.time()

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at,
            "last_access": self.last_access,
        }


class InMemorySessionCache:
    """Cache sessioni in memoria con TTL e auto-eviction."""

    def __init__(self, max_size: int = MAX_SESSIONS, ttl: int = SESSION_TTL_SECONDS):
        self.max_size = max_size
        self.ttl = ttl
        self._sessions: OrderedDict[str, SessionEntry] = OrderedDict()

    def create_session(self, user_id: str, email: str, role: str) -> str:
        self._evict_expired()
        session_token = secrets.token_hex(32)
        if len(self._sessions) >= self.max_size:
            self._sessions.popitem(last=False)
            logger.debug("Session cache piena, rimossa sessione più vecchia")
        self._sessions[session_token] = SessionEntry(user_id, email, role)
        return session_token

    def get_session(self, token: str) -> Optional[dict]:
        entry = self._sessions.get(token)
        if entry is None:
            return None
        if entry.is_expired(time.time()):
            del self._sessions[token]
            return None
        entry.touch()
        self._sessions.move_to_end(token)
        return entry.to_dict()

    def invalidate(self, token: str) -> bool:
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False

    def invalidate_user(self, user_id: str) -> int:
        tokens_to_remove = [
            t for t, e in self._sessions.items() if e.user_id == user_id
        ]
        for t in tokens_to_remove:
            del self._sessions[t]
        return len(tokens_to_remove)

    def _evict_expired(self):
        now = time.time()
        expired = [t for t, e in self._sessions.items() if e.is_expired(now)]
        for t in expired:
            del self._sessions[t]

    @property
    def active_count(self) -> int:
        self._evict_expired()
        return len(self._sessions)

    def get_stats(self) -> dict:
        self._evict_expired()
        return {
            "active_sessions": len(self._sessions),
            "max_sessions": self.max_size,
            "ttl_seconds": self.ttl,
        }


session_cache = InMemorySessionCache()
