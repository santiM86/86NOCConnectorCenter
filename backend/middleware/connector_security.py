"""Advanced connector security: HMAC signature, anti-replay, key rotation."""
import hmac
import hashlib
import time
import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException
from database import db

logger = logging.getLogger(__name__)

# Obfuscated connector path prefix (replaces /connector/)
CONNECTOR_PATH = os.environ.get("CONNECTOR_PATH", "c7x9")

# HMAC shared secret (derived from API key + server secret)
HMAC_SECRET = os.environ.get("HMAC_SECRET", "argus-hmac-k3y-2026!")

# Anti-replay window (seconds)
REPLAY_WINDOW = 300  # 5 minutes

# Key rotation interval (days)
KEY_ROTATION_DAYS = 30


async def verify_connector_request(request: Request) -> dict:
    """Full security verification for connector requests:
    1. Validate API Key
    2. Verify HMAC signature
    3. Anti-replay (nonce + timestamp)
    Returns client data if all checks pass.
    """
    # 1. API Key validation
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    client = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 2. HMAC Signature verification
    signature = request.headers.get("X-HMAC-Signature")
    timestamp = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")

    # If connector sends HMAC headers, verify them strictly
    # If not (legacy connector), allow but log warning
    if signature and timestamp and nonce:
        # Verify timestamp is within window
        try:
            req_time = float(timestamp)
            now = time.time()
            if abs(now - req_time) > REPLAY_WINDOW:
                logger.warning(f"Connector replay attempt: timestamp drift {abs(now - req_time):.0f}s from {request.client.host}")
                raise HTTPException(status_code=401, detail="Request expired")
        except (ValueError, TypeError):
            raise HTTPException(status_code=401, detail="Invalid timestamp")

        # Anti-replay: check nonce hasn't been used
        existing_nonce = await db.connector_nonces.find_one({"nonce": nonce})
        if existing_nonce:
            logger.warning(f"Connector replay attack detected: duplicate nonce from {request.client.host}")
            raise HTTPException(status_code=401, detail="Duplicate request")

        # Store nonce (with TTL — auto-expires after REPLAY_WINDOW)
        await db.connector_nonces.insert_one({
            "nonce": nonce,
            "client_id": client["id"],
            "ip": request.client.host if request.client else "unknown",
            "created_at": datetime.now(timezone.utc),
        })

        # Verify HMAC-SHA256 signature
        # Signature = HMAC-SHA256(api_key + timestamp + nonce + body_hash, secret)
        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest() if body else ""
        message = f"{api_key}{timestamp}{nonce}{body_hash}"
        expected = hmac.new(
            (HMAC_SECRET + api_key).encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            logger.warning(f"HMAC signature mismatch from {request.client.host}")
            raise HTTPException(status_code=401, detail="Invalid signature")
    else:
        # Legacy connector without HMAC — allow but flag
        client["_legacy_auth"] = True

    # Check if API key needs rotation
    key_created = client.get("api_key_created_at")
    if key_created:
        try:
            if isinstance(key_created, str):
                created_dt = datetime.fromisoformat(key_created.replace("Z", "+00:00"))
            else:
                created_dt = key_created
            days_old = (datetime.now(timezone.utc) - created_dt).days
            if days_old >= KEY_ROTATION_DAYS:
                client["_key_rotation_needed"] = True
        except Exception:
            pass

    return client


async def rotate_api_key(client_id: str) -> dict:
    """Generate a new API key and store it. Returns new key."""
    new_key = f"argus_{secrets.token_urlsafe(32)}"
    now = datetime.now(timezone.utc).isoformat()

    await db.clients.update_one(
        {"id": client_id},
        {"$set": {
            "api_key": new_key,
            "api_key_created_at": now,
            "api_key_previous": None,  # Could keep old key for grace period
        }}
    )

    logger.info(f"API key rotated for client {client_id}")
    return {"new_api_key": new_key, "rotated_at": now}


async def setup_nonce_ttl_index():
    """Create TTL index on connector_nonces to auto-expire old nonces."""
    try:
        await db.connector_nonces.create_index(
            "created_at",
            expireAfterSeconds=REPLAY_WINDOW + 60  # Extra margin
        )
    except Exception:
        pass
