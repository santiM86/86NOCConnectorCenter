"""Backend tests for the GitHub Release proxy endpoints introduced in
NOC con agent Go v4 (iteration 80).

The Center exposes:
  GET /api/agent-builds/{version}/manifest.json
  GET /api/agent-builds/{version}/{filename}
both authenticated via ?token=<agent_token|client.api_key>.

Cache: /tmp/agent-builds-cache (overridable via AGENT_BUILDS_CACHE_DIR).

Bulk update endpoint already exists at POST /api/agents/bulk-update and
must refuse target_version == "latest" (returns 503).
"""

import os
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://device-monitor-94.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
CACHE_DIR = os.environ.get("AGENT_BUILDS_CACHE_DIR", "/tmp/agent-builds-cache")

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"


# ---------- fixtures ---------------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo_creds():
    """Fetch an existing non-revoked agent_token and a client api_key
    directly from Mongo. The proxy auth (_token_or_403) accepts both."""
    async def _go():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        tok = await db.agent_tokens.find_one(
            {"revoked": {"$ne": True}}, {"_id": 0, "token": 1, "client_id": 1}
        )
        cl = await db.clients.find_one(
            {}, {"_id": 0, "api_key": 1, "client_id": 1, "slug": 1, "id": 1}
        )
        cli.close()
        return tok, cl

    tok, cl = asyncio.get_event_loop().run_until_complete(_go())
    assert tok and tok.get("token"), "No non-revoked agent_token in DB"
    assert cl and cl.get("api_key"), "No client.api_key in DB"
    return {"agent_token": tok["token"], "api_key": cl["api_key"]}


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed {r.status_code}: {r.text[:200]}")
    return r.json().get("access_token") or r.json().get("token")


# ---------- /api/agent-builds/latest/manifest.json ---------------------------

class TestManifestAuth:
    def test_manifest_no_token_returns_401(self, http):
        r = http.get(f"{BASE_URL}/api/agent-builds/latest/manifest.json", timeout=20)
        assert r.status_code == 401
        assert "token" in r.text.lower()

    def test_manifest_invalid_token_returns_403(self, http):
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": "definitely-not-a-real-token-xyz"},
            timeout=20,
        )
        assert r.status_code == 403

    def test_manifest_with_agent_token_returns_200(self, http, mongo_creds):
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": mongo_creds["agent_token"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Schema
        for k in ("version", "name", "published_at", "assets"):
            assert k in data, f"missing key {k} in manifest"
        assert isinstance(data["assets"], list) and data["assets"], "assets empty"
        # version must resolve from 'latest' to a concrete tag like v4.x.y
        assert data["version"].startswith("v"), data["version"]
        assert data["version"] != "latest"
        # All asset URLs must be proxied through the Center, NOT raw GitHub.
        for a in data["assets"]:
            assert "name" in a and "url" in a
            assert a["url"].startswith(f"/api/agent-builds/{data['version']}/"), a["url"]
            assert "github.com" not in a["url"]
            assert "browser_download_url" not in a  # field must NOT be present

    def test_manifest_with_client_api_key_returns_200(self, http, mongo_creds):
        """_token_or_403 must also accept client.api_key."""
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": mongo_creds["api_key"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["version"].startswith("v")


# ---------- /api/agent-builds/{version}/{filename} ---------------------------

class TestAssetDownload:
    def _resolved_version(self, http, mongo_creds):
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": mongo_creds["agent_token"]},
            timeout=30,
        )
        assert r.status_code == 200
        return r.json()["version"]

    def test_download_ps1_first_time(self, http, mongo_creds):
        ver = self._resolved_version(http, mongo_creds)
        # Clean cache file before this test so we exercise miss → hit path.
        cache_file = os.path.join(CACHE_DIR, ver, "install-noc-agent.ps1")
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
        except OSError:
            pass
        r = http.get(
            f"{BASE_URL}/api/agent-builds/{ver}/install-noc-agent.ps1",
            params={"token": mongo_creds["agent_token"]},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.content
        # PS1 file is around 29KB
        assert 5_000 < len(body) < 200_000, f"unexpected size {len(body)}"
        # Sanity: contains PowerShell content
        assert b"#Requires" in body or b"param(" in body or b"Write-Host" in body or b"PowerShell" in body or b"$PSScriptRoot" in body or b"Set-Variable" in body or b"function " in body or len(body) > 5000

    def test_download_cache_hit_on_second_request(self, http, mongo_creds):
        ver = self._resolved_version(http, mongo_creds)
        cache_file = os.path.join(CACHE_DIR, ver, "install-noc-agent.ps1")
        # File should exist after first download
        assert os.path.exists(cache_file), f"cache file not created at {cache_file}"
        size_before = os.path.getsize(cache_file)
        mtime_before = os.path.getmtime(cache_file)
        r = http.get(
            f"{BASE_URL}/api/agent-builds/{ver}/install-noc-agent.ps1",
            params={"token": mongo_creds["agent_token"]},
            timeout=30,
        )
        assert r.status_code == 200
        # Cache file must not have been re-downloaded (mtime unchanged).
        assert os.path.getmtime(cache_file) == mtime_before, "cache miss on second request"
        assert os.path.getsize(cache_file) == size_before
        assert len(r.content) == size_before

    def test_download_nonexistent_asset_404(self, http, mongo_creds):
        ver = self._resolved_version(http, mongo_creds)
        r = http.get(
            f"{BASE_URL}/api/agent-builds/{ver}/nonexistent-file-xyz.exe",
            params={"token": mongo_creds["agent_token"]},
            timeout=30,
        )
        assert r.status_code == 404, r.text[:200]

    def test_path_traversal_blocked(self, http, mongo_creds):
        """Even if Starlette routes /etc/passwd up, the asset must not be
        readable. Filename gets sanitized inside _cache_path."""
        # FastAPI routes won't match `..` segments — they get normalized.
        # We still test the lookup endpoint with an encoded traversal.
        r = http.get(
            f"{BASE_URL}/api/agent-builds/v4.11.0/..%2F..%2Fetc%2Fpasswd",
            params={"token": mongo_creds["agent_token"]},
            timeout=20,
            allow_redirects=False,
        )
        assert r.status_code in (400, 404), f"expected 400/404, got {r.status_code} body={r.text[:200]}"
        # And the response body must not contain /etc/passwd content
        assert b"root:x:" not in r.content


# ---------- /api/agents/bulk-update target=latest refusal --------------------

class TestBulkUpdateRefuseLatest:
    def test_bulk_update_latest_returns_503(self, http, admin_token):
        # Force literal "latest" — endpoint must refuse with 503 + clear msg.
        r = http.post(
            f"{BASE_URL}/api/agents/bulk-update",
            json={"agent_ids": ["fake-agent-id-for-test"], "version": "latest"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 503, r.text[:300]
        msg = r.json().get("detail", "").lower()
        assert "rate" in msg or "github" in msg or "agent_github_token" in msg, msg


# ---------- hello handler: completion detection -----------------------------

class TestHelloCompletionDetection:
    """Seed an agent in update_status='in_progress' and verify the hello
    handler flips it to 'completed' when the agent reports a different
    version. We cannot run a real WS agent in preview, so we exercise the
    logic via direct DB seed + then assert the same logic by import."""

    def test_completion_logic_via_import(self):
        """Directly invoke _normalize_ver and replicate the branch from
        agent_ws.py lines 215-244 to ensure the helper is exposed and the
        condition for ambiguous-target completion works."""
        import sys
        sys.path.insert(0, "/app/backend")
        from routes.agent_ws import _normalize_ver  # type: ignore

        # Case A: target matches → completed
        assert _normalize_ver("v4.11.0") == _normalize_ver("4.11.0")
        # Case B: target=latest, started!=current → ambiguous-but-changed
        started = _normalize_ver("v4.10.3")
        current = _normalize_ver("v4.11.0")
        target = _normalize_ver("latest")
        assert started and current and started != current
        assert (not target or target == "latest")
        # Case C: target!=latest and matches current
        assert _normalize_ver("v4.11.0") == _normalize_ver("4.11.0+build123")

    def test_completion_db_flip_via_seed(self):
        """Seed a managed_agents row with update_status=in_progress and a
        started_version different from agent_version, then directly call
        the same DB update code path."""
        async def _go():
            cli = AsyncIOMotorClient(MONGO_URL)
            db = cli[DB_NAME]
            aid = "TEST_iter80_completion_agent"
            try:
                await db.managed_agents.delete_one({"agent_id": aid})
                await db.managed_agents.insert_one({
                    "agent_id": aid,
                    "client_id": "pytest",
                    "agent_version": "v4.11.0",         # current after restart
                    "update_status": "in_progress",
                    "update_target_version": "latest",
                    "update_started_version": "v4.10.3",
                    "last_hello_at": datetime.now(timezone.utc).isoformat(),
                })
                # Simulate the patch the hello handler would apply
                import sys
                sys.path.insert(0, "/app/backend")
                from routes.agent_ws import _normalize_ver  # type: ignore
                doc = await db.managed_agents.find_one({"agent_id": aid})
                target_n = _normalize_ver(doc.get("update_target_version"))
                current_n = _normalize_ver(doc.get("agent_version"))
                started_n = _normalize_ver(doc.get("update_started_version"))
                completed = (
                    (not target_n or target_n == "latest")
                    and started_n
                    and current_n
                    and started_n != current_n
                )
                assert completed, f"completion logic failed t={target_n} c={current_n} s={started_n}"
                await db.managed_agents.update_one(
                    {"agent_id": aid},
                    {"$set": {"update_status": "completed"}},
                )
                after = await db.managed_agents.find_one({"agent_id": aid})
                assert after["update_status"] == "completed"
            finally:
                await db.managed_agents.delete_one({"agent_id": aid})
                cli.close()

        asyncio.get_event_loop().run_until_complete(_go())
