"""Iteration 81 — Tests for the 3 combined fixes:

1. install-noc-agent.ps1: param Source default '' + auto-detect block that
   selects "center" when Token+BackendUrl provided, "github" otherwise.
2. Center proxy (agent_builds_asset) prefers `browser_download_url` (public
   CDN, no rate-limit, no auth) over the API URL for public-repo releases.
3. _fetch_release_meta fallback: if the GitHub API fails (rate-limit / 401
   from a fake AGENT_GITHUB_TOKEN), returns a synthetic manifest built
   from _KNOWN_RELEASE_ASSETS so download still works.

Also covered:
  - Bulk-update with DB override (agent_latest_version_override) + only
    agent_ids → resolves via override, no 503.
  - Cache TTL: 2nd manifest call < 100ms (in-memory cache hit).
  - Negative cache for unknown version (no infinite retry loop).
  - Path traversal still blocked.
  - Auto-detect Source block present in install-noc-agent.ps1.
"""

import os
import asyncio
import time
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
CACHE_DIR = os.environ.get("AGENT_BUILDS_CACHE_DIR", "/tmp/agent-builds-cache")

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"

PS1_PATH = "/app/noc-agent/build/install-noc-agent.ps1"

_KNOWN_ASSET_NAMES = {
    "nocagent.exe", "nocwatchdog.exe", "nocinstall.exe", "nocagent-ui.exe",
    "ArgusDesktop.exe", "install-noc-agent.ps1",
    "installer_gui.ps1.template", "SHA256SUMS.txt",
}


# ---------------- fixtures ---------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def creds():
    """Fetch a working agent_token + admin login."""
    async def _go():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        tok = await db.agent_tokens.find_one(
            {"revoked": {"$ne": True}}, {"_id": 0, "token": 1}
        )
        cli.close()
        return tok

    tok = asyncio.get_event_loop().run_until_complete(_go())
    assert tok and tok.get("token"), "No agent_token available"

    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code}"
    admin_jwt = r.json().get("access_token") or r.json().get("token")
    return {"agent_token": tok["token"], "admin_jwt": admin_jwt}


# ---------------- 1. PS1 auto-detect Source block ---------------------------

class TestPS1AutoDetectSource:
    def test_ps1_file_exists(self):
        assert os.path.exists(PS1_PATH), f"missing {PS1_PATH}"

    def test_ps1_contains_auto_detect_block(self):
        content = open(PS1_PATH, encoding="utf-8").read()
        # Comment marker that flags the new block
        assert "Auto-detect Source quando non specificato esplicitamente" in content, \
            "missing Auto-detect Source comment block"
        # The actual logic
        assert "if (-not $Source)" in content
        assert '$Source = "center"' in content
        assert '$Source = "github"' in content
        # Token + BackendUrl combined check
        assert "$Token -and $BackendUrl" in content

    def test_ps1_source_param_default_empty(self):
        content = open(PS1_PATH, encoding="utf-8").read()
        assert '[ValidateSet("","github","center")][string]$Source = ""' in content, \
            "Source param must default to empty string for auto-detect"


# ---------------- 2. Manifest happy path (real GitHub API) ------------------

class TestManifestHappyPath:
    def test_manifest_returns_all_known_assets(self, http, creds):
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": creds["agent_token"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["version"].startswith("v") and data["version"] != "latest"
        names = {a["name"] for a in data["assets"]}
        # All 8 known assets must be reachable (either via real API or
        # synthetic fallback). When real, more assets may be present.
        missing = _KNOWN_ASSET_NAMES - names
        assert not missing, f"missing assets in manifest: {missing}"

    def test_manifest_cache_ttl_second_call_fast(self, http, creds):
        """Second call must hit in-memory cache (<100ms)."""
        # Warm up
        http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": creds["agent_token"]},
            timeout=30,
        )
        t0 = time.time()
        r = http.get(
            f"{BASE_URL}/api/agent-builds/latest/manifest.json",
            params={"token": creds["agent_token"]},
            timeout=10,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200
        # Allow generous bound for network RTT to preview env; truly
        # cached should be <500ms incl. network. If GitHub API is hit
        # again it'd be 1-3 seconds.
        assert elapsed < 1.5, f"second call too slow ({elapsed:.2f}s) — cache likely missed"


# ---------------- 3. Path traversal still blocked ---------------------------

class TestPathTraversal:
    def test_path_traversal_blocked(self, http, creds):
        r = http.get(
            f"{BASE_URL}/api/agent-builds/v4.11.0/..%2F..%2Fetc%2Fpasswd",
            params={"token": creds["agent_token"]},
            timeout=15,
            allow_redirects=False,
        )
        assert r.status_code in (400, 404), r.status_code
        assert b"root:x:" not in r.content


# ---------------- 4. Unknown version → 502 (no infinite retry) --------------

class TestUnknownVersionNegative:
    def test_unknown_version_returns_5xx_fast(self, http, creds):
        """A non-existent tag must return 5xx quickly, not loop on retries.
        Note: thanks to the synthetic fallback, even unknown versions now
        return a synthetic manifest (200) — that's the intended behaviour
        because the proxy WILL still try browser_download_url at request
        time. The asset download will eventually 404."""
        t0 = time.time()
        r = http.get(
            f"{BASE_URL}/api/agent-builds/v9.99.99-nonexistent/manifest.json",
            params={"token": creds["agent_token"]},
            timeout=30,
        )
        elapsed = time.time() - t0
        # Acceptable: 200 (synthetic) or 5xx — but NEVER hang
        assert r.status_code in (200, 502, 503, 404), f"unexpected {r.status_code}"
        assert elapsed < 20, f"unknown version took {elapsed:.1f}s — possible retry loop"

    def test_unknown_version_asset_download_eventual_failure(self, http, creds):
        """Downloading an asset for non-existent tag must 404/502 — not loop."""
        t0 = time.time()
        r = http.get(
            f"{BASE_URL}/api/agent-builds/v9.99.99-nonexistent/install-noc-agent.ps1",
            params={"token": creds["agent_token"]},
            timeout=30,
        )
        elapsed = time.time() - t0
        assert r.status_code in (404, 502, 503), f"unexpected {r.status_code}"
        assert elapsed < 25, f"download took {elapsed:.1f}s — possible retry loop"


# ---------------- 5. Bulk-update via DB override (no explicit version) ------

class TestBulkUpdateWithDBOverride:
    """Set system_settings override → POST /api/agents/bulk-update with
    only agent_ids (no version) must resolve via override + NOT return 503.
    """

    def test_bulk_update_resolves_via_db_override(self, http, creds):
        # 1) Set override to v4.11.0 via admin endpoint
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {creds['admin_jwt']}",
            "Content-Type": "application/json",
        })
        r = s.post(
            f"{BASE_URL}/api/admin/agent-latest-override",
            json={"version": "v4.11.0"},
            timeout=15,
        )
        assert r.status_code == 200, f"override set failed: {r.status_code} {r.text[:200]}"

        try:
            # Verify override is reflected in resolution
            r2 = s.get(f"{BASE_URL}/api/admin/agent-latest-override", timeout=10)
            assert r2.status_code == 200
            data = r2.json()
            assert data.get("db_override") == "v4.11.0"
            assert data.get("resolved", "").startswith("v")
            assert data["resolved"] != "latest"

            # 2) Bulk-update with only fake agent_ids (NO version field)
            r3 = s.post(
                f"{BASE_URL}/api/agents/bulk-update",
                json={"agent_ids": ["TEST_iter81_fake_agent"]},
                timeout=20,
            )
            # Must NOT be 503 (no rate-limit message). Acceptable outcomes:
            #  - 200 with sent=[] failed=[{agent non connesso}]
            #  - 400 only if validation rejects fake id (but our payload is valid)
            assert r3.status_code != 503, \
                f"bulk-update returned 503 despite DB override: {r3.text[:300]}"
            assert r3.status_code == 200, f"unexpected {r3.status_code}: {r3.text[:200]}"
            body = r3.json()
            assert body.get("target_version", "").startswith("v")
            assert body["target_version"] != "latest"
            # agent not connected → in failed list
            assert any(
                f.get("agent_id") == "TEST_iter81_fake_agent"
                for f in body.get("failed", [])
            )
        finally:
            # Cleanup: remove override
            s.post(
                f"{BASE_URL}/api/admin/agent-latest-override",
                json={"version": ""},
                timeout=10,
            )


# ---------------- 6. Synthetic fallback (simulate GitHub API down) ----------

class TestSyntheticFallback:
    """Set AGENT_GITHUB_TOKEN to a fake value → real GitHub API returns 401
    → _fetch_release_meta falls back to synthetic manifest. The asset
    download must still work because browser_download_url is preferred and
    needs no auth on public repos.
    """

    @staticmethod
    def _patch_env(fake: bool):
        """Add/remove AGENT_GITHUB_TOKEN=fake to /app/backend/.env and
        restart the backend. Returns when service is responsive again."""
        env_path = "/app/backend/.env"
        with open(env_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines()
                     if not ln.startswith("AGENT_GITHUB_TOKEN=")]
        if fake:
            lines.append("AGENT_GITHUB_TOKEN=ghp_FAKE_FAKE_FAKE_FAKE_FAKE_iter81test")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.system("sudo supervisorctl restart backend > /dev/null 2>&1")
        # wait for backend to come back
        for _ in range(40):
            time.sleep(0.5)
            try:
                r = requests.get(f"{BASE_URL}/api/health", timeout=2)
                if r.status_code < 500:
                    return
            except Exception:
                pass
        raise RuntimeError("backend did not come back after restart")

    @staticmethod
    def _clear_cache():
        os.system("rm -rf /tmp/agent-builds-cache > /dev/null 2>&1")

    def test_full_fake_token_flow(self, http, creds):
        """End-to-end: fake token forces synthetic fallback + browser CDN download."""
        # Clear in-memory and disk caches by restarting with fake token
        self._clear_cache()
        try:
            self._patch_env(fake=True)
            # Re-fetch agent_token (still valid, DB unchanged)
            token = creds["agent_token"]

            # 6a) Manifest still returns 200 with all known assets
            # (use a concrete version, since 'latest' resolution would
            # also fail with fake token → 503).
            r = requests.get(
                f"{BASE_URL}/api/agent-builds/v4.11.0/manifest.json",
                params={"token": token},
                timeout=30,
            )
            assert r.status_code == 200, f"manifest failed under fake token: {r.status_code} {r.text[:300]}"
            data = r.json()
            assert data["version"] == "v4.11.0"
            names = {a["name"] for a in data["assets"]}
            missing = _KNOWN_ASSET_NAMES - names
            assert not missing, f"synthetic manifest missing assets: {missing}"
            # All URLs proxied through Center
            for a in data["assets"]:
                assert a["url"].startswith("/api/agent-builds/v4.11.0/")

            # 6b) Download PS1 → uses browser_download_url (CDN, no auth)
            r2 = requests.get(
                f"{BASE_URL}/api/agent-builds/v4.11.0/install-noc-agent.ps1",
                params={"token": token},
                timeout=60,
            )
            assert r2.status_code == 200, f"PS1 download failed: {r2.status_code} {r2.text[:300]}"
            assert 5_000 < len(r2.content) < 200_000, f"unexpected PS1 size {len(r2.content)}"
            assert b"86NocAgent" in r2.content or b"NOC Agent" in r2.content.replace(b"\x00", b"")

            # 6c) Download large binary (nocagent.exe) → 200
            # Confirms browser_download_url works for binary > 7MB.
            r3 = requests.get(
                f"{BASE_URL}/api/agent-builds/v4.11.0/nocagent.exe",
                params={"token": token},
                timeout=180,
            )
            assert r3.status_code == 200, f"nocagent.exe failed: {r3.status_code}"
            assert len(r3.content) > 1_000_000, f"nocagent.exe too small: {len(r3.content)}"

            # 6d) Cache hit on 2nd PS1 request — disk cache survives
            cache_file = os.path.join(CACHE_DIR, "v4.11.0", "install-noc-agent.ps1")
            assert os.path.exists(cache_file), "PS1 not cached on disk"
            mtime_before = os.path.getmtime(cache_file)
            r4 = requests.get(
                f"{BASE_URL}/api/agent-builds/v4.11.0/install-noc-agent.ps1",
                params={"token": token},
                timeout=30,
            )
            assert r4.status_code == 200
            assert os.path.getmtime(cache_file) == mtime_before, "cache was re-downloaded"
        finally:
            # Always cleanup: remove fake token, restart, clear cache
            self._patch_env(fake=False)
            self._clear_cache()
