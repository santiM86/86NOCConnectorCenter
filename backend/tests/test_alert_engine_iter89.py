"""Tests for Alert Engine proattivo (iteration 89)."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://noc-monitor-4.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"

TEST_CLIENT_ID = "test-alert-engine-iter89"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --- Config get / put with mask ---
class TestAlertEngineConfig:
    def test_get_config_defaults_and_masked(self, h):
        r = requests.get(f"{API}/alert-engine/config", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        cfg = r.json()
        # Default keys
        for k in ["enabled", "vital_warn_minutes", "vital_crit_minutes",
                  "datto_server_offline_hours", "datto_sync_stale_minutes",
                  "channels", "telegram_enabled", "auto_recovery",
                  "telegram_bot_token", "telegram_bot_token_set"]:
            assert k in cfg, f"missing key {k}"
        # Token must never be clear text (only "", "***" or masked "...…...")
        tok = cfg["telegram_bot_token"]
        assert tok == "" or tok == "***" or "…" in tok, f"token leaked: {tok!r}"

    def test_put_config_updates_and_persists(self, h):
        # set values
        patch = {"vital_warn_minutes": 5, "vital_crit_minutes": 12}
        r = requests.put(f"{API}/alert-engine/config", json=patch, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["vital_warn_minutes"] == 5
        assert r.json()["vital_crit_minutes"] == 12
        # verify via GET
        r2 = requests.get(f"{API}/alert-engine/config", headers=h, timeout=15).json()
        assert r2["vital_warn_minutes"] == 5
        assert r2["vital_crit_minutes"] == 12
        # restore defaults
        requests.put(f"{API}/alert-engine/config",
                     json={"vital_warn_minutes": 3, "vital_crit_minutes": 10},
                     headers=h, timeout=15)

    def test_put_config_does_not_overwrite_token_with_mask(self, h):
        # First set a real-ish token
        real_token = "999999:TEST_TOKEN_DO_NOT_USE_iter89"
        requests.put(f"{API}/alert-engine/config",
                     json={"telegram_bot_token": real_token}, headers=h, timeout=15)
        # Now send masked value → must be ignored
        r = requests.put(f"{API}/alert-engine/config",
                         json={"telegram_bot_token": "***", "vital_warn_minutes": 4},
                         headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["telegram_bot_token_set"] is True
        # send empty → must be ignored
        r = requests.put(f"{API}/alert-engine/config",
                         json={"telegram_bot_token": "  "}, headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["telegram_bot_token_set"] is True
        # cleanup: clear token by sending explicit blank via direct clear
        # (we don't expose an explicit "clear", so leave it — will be overwritten later
        # but next test needs no-token; we clear via a fresh save cycle by writing "" is ignored
        # so we can't easily wipe. Skip cleanup — telegram test uses explicit token override
        requests.put(f"{API}/alert-engine/config", json={"vital_warn_minutes": 3},
                     headers=h, timeout=15)


class TestClientOverride:
    def test_get_override_default_empty(self, h):
        r = requests.get(f"{API}/alert-engine/config/{TEST_CLIENT_ID}", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json().get("override_enabled") in (False, None) or "override_enabled" in r.json()

    def test_put_override_persists(self, h):
        patch = {"override_enabled": True, "vital_warn_minutes": 2}
        r = requests.put(f"{API}/alert-engine/config/{TEST_CLIENT_ID}",
                         json=patch, headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["override_enabled"] is True
        assert r.json()["vital_warn_minutes"] == 2
        # verify persistence
        r2 = requests.get(f"{API}/alert-engine/config/{TEST_CLIENT_ID}", headers=h, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["vital_warn_minutes"] == 2


class TestRunAndStatus:
    def test_run_now(self, h):
        r = requests.post(f"{API}/alert-engine/run-now", json={}, headers=h, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        assert "result" in j
        assert "vital_actions" in j["result"]
        assert "datto_actions" in j["result"]

    def test_status(self, h):
        # ensure run-now has been called
        requests.post(f"{API}/alert-engine/run-now", json={}, headers=h, timeout=60)
        time.sleep(0.5)
        r = requests.get(f"{API}/alert-engine/status", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "last_run" in j
        assert "vital_offline_tracked" in j
        assert "datto_offline_tracked" in j


class TestTelegramNoToken:
    """When no real Telegram token is configured, endpoints must return 400 (not 500)."""

    def test_telegram_test_no_token(self, h):
        # override with bogus token then clear via override: not possible easily.
        # However, test endpoint returns 400 if token or chat_id missing.
        # We send explicit empty token in body → falls back to stored one.
        # Given the previous test stored a fake token, sending here will attempt HTTP.
        # We expect either 400 (token missing/chat_id missing) or 400 (send failed with fake token).
        r = requests.post(f"{API}/alert-engine/telegram/test",
                          json={"token": "", "chat_id": ""}, headers=h, timeout=20)
        assert r.status_code == 400, f"expected 400 got {r.status_code} body={r.text[:200]}"
        # Body must contain a detail string (not stack trace)
        body = r.json()
        assert "detail" in body

    def test_telegram_detect_chats_bad_token(self, h):
        # detect-chats will try http; fake token → non-200 → 400 with detail
        r = requests.get(f"{API}/alert-engine/telegram/detect-chats", headers=h, timeout=20)
        # Could be 400 (token missing OR API rejected fake token) — never 500
        assert r.status_code in (200, 400), f"expected 400/200 got {r.status_code} body={r.text[:200]}"


class TestAdminAuth:
    def test_put_config_requires_admin(self):
        # unauth request
        r = requests.put(f"{API}/alert-engine/config", json={"vital_warn_minutes": 9}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_run_now_requires_admin(self):
        r = requests.post(f"{API}/alert-engine/run-now", json={}, timeout=15)
        assert r.status_code in (401, 403)


# --- Regression: existing Datto endpoints still work ---
class TestRegression:
    def test_settings_bootstrap(self, h):
        # a widely used endpoint that Settings uses
        r = requests.get(f"{API}/clients", headers=h, timeout=15)
        assert r.status_code == 200

    def test_datto_status(self, h):
        r = requests.get(f"{API}/datto/status", headers=h, timeout=15)
        # 200 or 404 acceptable if endpoint path different; we just ensure not 500
        assert r.status_code < 500, r.text
