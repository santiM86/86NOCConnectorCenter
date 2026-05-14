"""
NOC Alert Command Center - Security Module
Enterprise-grade security with AES-256-GCM encryption and Argon2id hashing

ENCRYPTION HARDENING (v2 — 2026-04-30):
- Salt random per deployment (32 byte, persisted in data/encryption_salt.bin)
- PBKDF2-HMAC-SHA256 600k iterations (NIST SP 800-132 rev. 2024)
- Backward-compat: ciphertext senza prefisso → schema legacy (salt fisso, 100k)
- Versioned ciphertext: prefisso "v2:" per nuovi blob
- Failed-decrypt counter con alert SIEM su burst (3+ in 60s)
- Master key rotation supportata via security_admin route
"""
import os
import base64
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import pyotp
import qrcode
import io

logger = logging.getLogger(__name__)
sec_audit = logging.getLogger("audit")

# AES-256-GCM Encryption Key (must be present in env)
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY non configurata in .env - il vault non puo' funzionare senza una chiave persistente")

# Legacy schema: salt fisso, 100k iter (compat con dati cifrati prima del 2026-04-30)
_LEGACY_SALT = b'noc_salt_v1'
_LEGACY_ITER = 100_000

# v2 schema: salt random per deployment, 600k iter (NIST 2024)
_V2_ITER = 600_000
_V2_SALT_PATH = Path(os.environ.get('ARGUS_DATA_DIR', '/app/backend/data')) / "encryption_salt.bin"
_V2_PREFIX = b"v2:"


def _load_or_create_v2_salt() -> bytes:
    """Carica il salt v2 da disco; se non esiste lo genera (32 byte CSPRNG)."""
    try:
        _V2_SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _V2_SALT_PATH.exists():
            data = _V2_SALT_PATH.read_bytes()
            if len(data) == 32:
                return data
            logger.warning(f"[security] salt v2 file ha dimensione {len(data)} != 32, rigenerazione")
        new_salt = secrets.token_bytes(32)
        _V2_SALT_PATH.write_bytes(new_salt)
        try:
            os.chmod(_V2_SALT_PATH, 0o600)
        except Exception:
            pass
        logger.info(f"[security] generato nuovo salt v2 random in {_V2_SALT_PATH}")
        sec_audit.warning(f"SECURITY_SALT_V2_GENERATED path={_V2_SALT_PATH}")
        return new_salt
    except Exception as e:
        logger.error(f"[security] impossibile gestire salt v2 ({e}); fallback a salt deterministico")
        # Fallback: deriva un salt da ENCRYPTION_KEY in modo deterministico (meglio del salt fisso)
        return PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32,
            salt=b'noc_v2_deterministic_fallback', iterations=10_000,
        ).derive(ENCRYPTION_KEY.encode())


class SecurityManager:
    """Enterprise-grade security manager for credential encryption and password hashing."""

    def __init__(self):
        # Argon2id hasher per password (parametri OWASP 2024)
        self.password_hasher = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16,
        )

        # v2 key (primary): salt random + 600k iter
        self._v2_salt = _load_or_create_v2_salt()
        self._v2_key = self._derive_key(ENCRYPTION_KEY, self._v2_salt, _V2_ITER)

        # v1 key (legacy): salt fisso + 100k iter — usata SOLO in lettura per backward-compat
        self._v1_key = self._derive_key(ENCRYPTION_KEY, _LEGACY_SALT, _LEGACY_ITER)

        # Decrypt failure tracker (anti-tampering / wrong-key detection)
        self._fail_lock = threading.Lock()
        self._fail_timestamps: list[float] = []  # epoch seconds delle failure recenti

    @staticmethod
    def _derive_key(key_material: str, salt: bytes, iterations: int) -> bytes:
        """Derive a 256-bit key using PBKDF2-HMAC-SHA256."""
        return PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations,
        ).derive(key_material.encode())

    # ==================== PASSWORD HASHING (Argon2id) ====================
    def hash_password(self, password: str) -> str:
        return self.password_hasher.hash(password)

    def verify_password(self, password: str, hashed: str) -> bool:
        try:
            self.password_hasher.verify(hashed, password)
            return True
        except VerifyMismatchError:
            return False

    def needs_rehash(self, hashed: str) -> bool:
        return self.password_hasher.check_needs_rehash(hashed)

    # ==================== AES-256-GCM ENCRYPTION ====================
    def encrypt_credential(self, plaintext: str) -> str:
        """Encrypt sensitive data using AES-256-GCM with v2 key (salt random, 600k iter).

        Output format: 'v2:' + base64(nonce[12] || ciphertext_with_tag)
        """
        aesgcm = AESGCM(self._v2_key)
        nonce = secrets.token_bytes(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        encoded = base64.b64encode(nonce + ciphertext).decode('utf-8')
        return _V2_PREFIX.decode() + encoded

    def decrypt_credential(self, encrypted: str) -> str:
        """Decrypt AES-256-GCM data. Tenta prima v2 (se prefisso), poi v1 legacy.

        Failed decrypt registrate per detection burst (alert SIEM).
        """
        try:
            # v2 path: prefisso "v2:"
            if encrypted.startswith(_V2_PREFIX.decode()):
                return self._decrypt_with_key(encrypted[len(_V2_PREFIX):], self._v2_key)
            # legacy path: nessun prefisso → v1
            return self._decrypt_with_key(encrypted, self._v1_key)
        except Exception as e:
            self._record_decrypt_failure()
            raise ValueError(f"Decryption failed: {e}")

    def _decrypt_with_key(self, b64: str, key: bytes) -> str:
        encrypted_bytes = base64.b64decode(b64.encode('utf-8'))
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode('utf-8')

    def _record_decrypt_failure(self) -> None:
        """Tieni traccia delle decrypt fallite — emit alert SIEM su burst (3+ in 60s)."""
        now = time.time()
        with self._fail_lock:
            self._fail_timestamps.append(now)
            # purge entries > 60s
            self._fail_timestamps = [t for t in self._fail_timestamps if now - t <= 60]
            recent = len(self._fail_timestamps)
        if recent >= 3:
            sec_audit.error(
                f"SECURITY_ALERT decrypt_failed_burst count={recent} "
                f"window=60s — possibile tampering o wrong master key"
            )

    def is_v2_ciphertext(self, encrypted: str) -> bool:
        """True se il ciphertext usa schema v2 (per migration logic)."""
        return encrypted.startswith(_V2_PREFIX.decode())

    def reencrypt_to_v2(self, encrypted: str) -> Optional[str]:
        """Decifra un blob (v1 o v2) e ricifra con v2. Ritorna None se gia` v2."""
        if self.is_v2_ciphertext(encrypted):
            return None
        plaintext = self.decrypt_credential(encrypted)
        return self.encrypt_credential(plaintext)

    # ==================== TWO-FACTOR AUTHENTICATION ====================
    def generate_totp_secret(self) -> str:
        return pyotp.random_base32()

    def get_totp_uri(self, secret: str, email: str, issuer: str = "NOC Command Center") -> str:
        return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)

    def generate_qr_code(self, totp_uri: str) -> bytes:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer.getvalue()

    def verify_totp(self, secret: str, code: str) -> bool:
        return pyotp.TOTP(secret).verify(code, valid_window=1)

    # ==================== TOKEN GENERATION ====================
    def generate_secure_token(self, length: int = 32) -> str:
        return secrets.token_urlsafe(length)

    def generate_api_key(self) -> str:
        return f"noc_{secrets.token_hex(24)}"


# Global security manager instance
security_manager = SecurityManager()
