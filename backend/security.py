"""
NOC Alert Command Center - Security Module
Enterprise-grade security with AES-256-GCM encryption and Argon2id hashing
"""
import os
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import pyotp
import qrcode
import io
from datetime import datetime, timezone
from typing import Optional, Tuple

# AES-256-GCM Encryption Key (must be 32 bytes)
# In production, this should come from a secure key management system (AWS KMS, HashiCorp Vault, etc.)
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', secrets.token_hex(32))

class SecurityManager:
    """Enterprise-grade security manager for credential encryption and password hashing."""
    
    def __init__(self):
        # Initialize Argon2id hasher with secure parameters
        self.password_hasher = PasswordHasher(
            time_cost=3,          # Number of iterations
            memory_cost=65536,    # Memory usage in kibibytes (64 MB)
            parallelism=4,        # Number of parallel threads
            hash_len=32,          # Length of the hash in bytes
            salt_len=16           # Length of the salt in bytes
        )
        
        # Derive AES key from the encryption key
        self._master_key = self._derive_key(ENCRYPTION_KEY)
    
    def _derive_key(self, key_material: str) -> bytes:
        """Derive a 256-bit key using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'noc_salt_v1',  # In production, use a unique salt per deployment
            iterations=100000,
        )
        return kdf.derive(key_material.encode())
    
    # ==================== PASSWORD HASHING (Argon2id) ====================
    
    def hash_password(self, password: str) -> str:
        """
        Hash a password using Argon2id.
        
        Args:
            password: Plain text password
            
        Returns:
            Argon2id hash string
        """
        return self.password_hasher.hash(password)
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """
        Verify a password against its Argon2id hash.
        
        Args:
            password: Plain text password to verify
            hashed: Argon2id hash to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            self.password_hasher.verify(hashed, password)
            return True
        except VerifyMismatchError:
            return False
    
    def needs_rehash(self, hashed: str) -> bool:
        """Check if a hash needs to be rehashed with updated parameters."""
        return self.password_hasher.check_needs_rehash(hashed)
    
    # ==================== AES-256-GCM ENCRYPTION ====================
    
    def encrypt_credential(self, plaintext: str) -> str:
        """
        Encrypt sensitive data using AES-256-GCM.
        
        Args:
            plaintext: Data to encrypt
            
        Returns:
            Base64-encoded encrypted data (nonce + ciphertext + tag)
        """
        aesgcm = AESGCM(self._master_key)
        nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
        
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # Combine nonce + ciphertext for storage
        encrypted = nonce + ciphertext
        return base64.b64encode(encrypted).decode('utf-8')
    
    def decrypt_credential(self, encrypted: str) -> str:
        """
        Decrypt AES-256-GCM encrypted data.
        
        Args:
            encrypted: Base64-encoded encrypted data
            
        Returns:
            Decrypted plaintext
            
        Raises:
            ValueError: If decryption fails (tampered or wrong key)
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted.encode('utf-8'))
            
            # Extract nonce (first 12 bytes) and ciphertext
            nonce = encrypted_bytes[:12]
            ciphertext = encrypted_bytes[12:]
            
            aesgcm = AESGCM(self._master_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            return plaintext.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}")
    
    # ==================== TWO-FACTOR AUTHENTICATION ====================
    
    def generate_totp_secret(self) -> str:
        """Generate a new TOTP secret for 2FA."""
        return pyotp.random_base32()
    
    def get_totp_uri(self, secret: str, email: str, issuer: str = "NOC Command Center") -> str:
        """Generate a TOTP URI for QR code generation."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=issuer)
    
    def generate_qr_code(self, totp_uri: str) -> bytes:
        """Generate a QR code image for TOTP setup."""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return buffer.getvalue()
    
    def verify_totp(self, secret: str, code: str) -> bool:
        """
        Verify a TOTP code.
        
        Args:
            secret: The user's TOTP secret
            code: The 6-digit code to verify
            
        Returns:
            True if valid, False otherwise
        """
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # Allow 1 period tolerance
    
    # ==================== TOKEN GENERATION ====================
    
    def generate_secure_token(self, length: int = 32) -> str:
        """Generate a cryptographically secure random token."""
        return secrets.token_urlsafe(length)
    
    def generate_api_key(self) -> str:
        """Generate a secure API key for external integrations."""
        return f"noc_{secrets.token_hex(24)}"


# Global security manager instance
security_manager = SecurityManager()
