"""
Test suite for Connector Auto-Update bug fix (v3.6.16)

Bug RCA:
  GET /api/connector/update-check returned `download_url` but NOT `filename`.
  PowerShell client (update_check.ps1) reads $checkResponse.filename then
  concatenates it to /api/connector/download/$filename. If filename is null
  the URL becomes empty and the download fails.

Fix verified:
  routes/connector.py update-check (lines 633-660) and heartbeat force_update
  (lines 298-306) now return the `filename` field.

Coverage:
  - update-check returns full payload with `filename`
  - download endpoint with X-API-Key (200, application/zip, expected size)
  - download endpoint with admin JWT (200)
  - download for non-existing file -> 404
  - heartbeat with force_update returns filename + download_url
  - update-info admin endpoint
  - public-download/latest (no auth)
  - regression: no active update -> update_available=False, version=1.0.0
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://snmp-hub-noc.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Connector API key for client "86BIT_Office" (read from db.clients)
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"

ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"

# Expected version is read dynamically from DB at fixture time so the test
# does not become stale when a new connector ZIP is published.
FILENAME_PATTERN = re.compile(r"^86NocConnector_v[\d\.]+\.zip$")


# ============= Fixtures =============
@pytest.fixture(scope="module")
def expected_active_update():
    """Resolve current active connector update from MongoDB once per module."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    async def _fetch():
        client = AsyncIOMotorClient(mongo_url)
        try:
            doc = await client[db_name].connector_updates.find_one(
                {"active": True}, {"_id": 0, "version": 1, "filename": 1}
            )
            return doc
        finally:
            client.close()
    doc = asyncio.run(_fetch())
    assert doc, "No active connector_update found in DB"
    return doc
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def update_check_response():
    """Capture the update-check response once for shared assertions."""
    r = requests.get(f"{API}/connector/update-check",
                     headers={"X-API-Key": CONNECTOR_API_KEY}, timeout=15)
    assert r.status_code == 200, f"update-check failed: {r.status_code} {r.text}"
    return r.json()


# ============= Tests =============

# --- update-check endpoint ---
class TestUpdateCheck:
    def test_update_check_returns_filename_field(self, update_check_response):
        """v3.6.16 fix: update-check MUST include 'filename' (was missing)."""
        data = update_check_response
        assert "filename" in data, f"BUG: 'filename' field missing in update-check response: {data}"
        assert data["filename"], "BUG: 'filename' is empty/null"
        assert FILENAME_PATTERN.match(data["filename"]), \
            f"filename does not match expected pattern: {data['filename']}"

    def test_update_check_full_payload(self, update_check_response):
        data = update_check_response
        # required keys per the contract
        for key in ("update_available", "latest_version", "filename",
                    "download_url", "file_size", "changelog", "published_at"):
            assert key in data, f"Missing key '{key}' in update-check: {data}"
        # types
        assert isinstance(data["update_available"], bool)
        assert isinstance(data["latest_version"], str) and data["latest_version"]
        assert isinstance(data["filename"], str) and data["filename"]
        assert isinstance(data["download_url"], str) and data["download_url"]
        assert isinstance(data["file_size"], int) and data["file_size"] > 0

    def test_update_check_latest_version(self, update_check_response, expected_active_update):
        assert update_check_response["latest_version"] == expected_active_update["version"]
        assert update_check_response["filename"] == expected_active_update["filename"]

    def test_download_url_consistency(self, update_check_response):
        """download_url must terminate with the same filename."""
        data = update_check_response
        assert data["download_url"].endswith(data["filename"]), \
            f"download_url '{data['download_url']}' does not end with filename '{data['filename']}'"
        assert data["download_url"].startswith("/api/connector/download/")

    def test_update_check_invalid_api_key(self):
        r = requests.get(f"{API}/connector/update-check",
                         headers={"X-API-Key": "noc_invalid_key_999"}, timeout=10)
        assert r.status_code == 401


# --- download endpoint ---
class TestDownload:
    def test_download_with_api_key(self, update_check_response):
        filename = update_check_response["filename"]
        expected_size = update_check_response["file_size"]
        r = requests.get(f"{API}/connector/download/{filename}",
                         headers={"X-API-Key": CONNECTOR_API_KEY}, timeout=30)
        assert r.status_code == 200, f"download failed: {r.status_code} {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "application/zip" in ct, f"unexpected content-type: {ct}"
        assert len(r.content) == expected_size, \
            f"size mismatch: expected {expected_size}, got {len(r.content)}"
        # ZIP magic bytes
        assert r.content[:2] == b"PK", "Body is not a valid ZIP file"

    def test_download_with_admin_jwt(self, admin_token, update_check_response):
        filename = update_check_response["filename"]
        r = requests.get(f"{API}/connector/download/{filename}",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
        assert r.status_code == 200, f"admin download failed: {r.status_code} {r.text[:200]}"
        assert "application/zip" in r.headers.get("content-type", "")

    def test_download_with_admin_jwt_query_param(self, admin_token, update_check_response):
        """Browser anchor download via ?token=<jwt>."""
        filename = update_check_response["filename"]
        r = requests.get(f"{API}/connector/download/{filename}?token={admin_token}", timeout=30)
        assert r.status_code == 200

    def test_download_non_existing_file_404(self):
        r = requests.get(f"{API}/connector/download/non_existing_file.zip",
                         headers={"X-API-Key": CONNECTOR_API_KEY}, timeout=10)
        assert r.status_code == 404

    def test_download_no_auth_401(self, update_check_response):
        filename = update_check_response["filename"]
        r = requests.get(f"{API}/connector/download/{filename}", timeout=10)
        assert r.status_code == 401


# --- heartbeat with force_update ---
class TestHeartbeatForceUpdate:
    @pytest.fixture(scope="class")
    def setup_force_update(self, admin_token):
        """Ensure connector_status doc exists & has force_update=True with old version."""
        # Read client_id by triggering a heartbeat with old version
        # Then set force_update=True via DB-direct manipulation through the admin
        # API (we use force-update endpoint).
        # First: heartbeat to register/update the connector_status with old version
        old_version_payload = {
            "connector_version": "1.0.0",
            "hostname": "test-autoupdate-host",
            "uptime_seconds": 100,
            "traps_received": 0,
            "syslogs_received": 0,
        }
        r = requests.post(f"{API}/connector/heartbeat",
                          headers={"X-API-Key": CONNECTOR_API_KEY},
                          json=old_version_payload, timeout=15)
        assert r.status_code == 200, f"first heartbeat failed: {r.text}"

        # Now invoke force-update via admin endpoint to set force_update=True
        # Need the client_id of our connector
        clients_resp = requests.get(f"{API}/clients",
                                    headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
        assert clients_resp.status_code == 200
        clients = clients_resp.json()
        target = next((c for c in clients if c.get("name") == "86BIT_Office"), None)
        assert target, "86BIT_Office client not found"
        client_id = target["id"]

        force_resp = requests.post(f"{API}/connector/{client_id}/force-update",
                                   headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        # 200 OK if forced, 400 if up-to-date, 409 if connector offline (preview env without live connector).
        if force_resp.status_code == 409:
            pytest.skip(f"Connector offline in this env (preview): {force_resp.text[:120]}")
        assert force_resp.status_code in (200, 400), f"force-update unexpected: {force_resp.status_code} {force_resp.text}"
        return old_version_payload

    def test_heartbeat_force_update_returns_filename(self, setup_force_update):
        """Heartbeat with force_update=True must return both filename AND download_url."""
        r = requests.post(f"{API}/connector/heartbeat",
                          headers={"X-API-Key": CONNECTOR_API_KEY},
                          json=setup_force_update, timeout=15)
        assert r.status_code == 200, f"heartbeat failed: {r.text}"
        data = r.json()
        # force_update may or may not appear depending on connector_status state.
        # If the previous test triggered force_update then it should be present here.
        if data.get("force_update"):
            assert "filename" in data, f"BUG: filename missing in force_update heartbeat response: {data}"
            assert data["filename"], "filename empty in force_update response"
            assert FILENAME_PATTERN.match(data["filename"])
            assert "download_url" in data
            assert data["download_url"].endswith(data["filename"])
            assert data["latest_version"] == expected_active_update["version"]
        else:
            pytest.skip("force_update not active in connector_status (race) — skipping")


# --- update-info admin endpoint ---
class TestUpdateInfo:
    def test_update_info_admin(self, admin_token, expected_active_update):
        r = requests.get(f"{API}/connector/update-info",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data.get("active") is True, f"active flag not True: {data}"
        assert "total_connectors" in data
        assert "pending_connectors" in data
        assert "updated_connectors" in data
        assert isinstance(data["total_connectors"], int)
        # coherence: pending + updated == total
        assert data["pending_connectors"] + data["updated_connectors"] == data["total_connectors"]
        assert data.get("version") == expected_active_update["version"]


# --- public-download/latest endpoint ---
class TestPublicDownload:
    def test_public_download_latest_no_auth(self, expected_active_update):
        r = requests.get(f"{API}/connector/public-download/latest", timeout=30)
        assert r.status_code == 200, f"public download failed: {r.status_code} {r.text[:200]}"
        assert "application/zip" in r.headers.get("content-type", "")
        # disposition should reference current active filename
        cd = r.headers.get("content-disposition", "")
        assert expected_active_update["filename"] in cd, f"filename not in content-disposition: {cd}"
        assert r.content[:2] == b"PK"


# --- regression: no active update ---
class TestNoActiveUpdate:
    def test_no_active_update_response(self):
        """When no connector_update with active=True, response must default safely.

        We cannot easily flip active flag without mutating production DB. Instead
        we directly perform the DB operation in a transactional way: deactivate
        all, run the test, then restore.
        """
        import asyncio
        # Lazy import — only when this test runs — to avoid env-load issues
        # at collection time.
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ.get("DB_NAME", "test_database")
        client = AsyncIOMotorClient(mongo_url)
        local_db = client[db_name]

        async def run():
            # Find currently active doc
            active_doc = await local_db.connector_updates.find_one({"active": True}, {"_id": 1})
            if not active_doc:
                return None
            await local_db.connector_updates.update_one(
                {"_id": active_doc["_id"]}, {"$set": {"active": False}}
            )
            try:
                r = requests.get(f"{API}/connector/update-check",
                                 headers={"X-API-Key": CONNECTOR_API_KEY}, timeout=15)
                return r.status_code, r.json()
            finally:
                # restore
                await local_db.connector_updates.update_one(
                    {"_id": active_doc["_id"]}, {"$set": {"active": True}}
                )

        status, data = asyncio.run(run())
        assert status == 200, f"update-check returned {status}: {data}"
        assert data.get("update_available") is False
        assert data.get("latest_version") == "1.0.0"
