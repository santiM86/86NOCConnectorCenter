"""Iter-83: DELETE /api/alerts/clear-all endpoint tests.

- 401/403 without auth or non-admin
- 200 con scope=active default
- Seed un alert TEST_ → call clear-all?scope=active&client_id=<id> → verify deleted=1
- scope invalido → 400
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("access_token") or body.get("token")


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_clear_all_requires_auth():
    r = requests.delete(f"{BASE_URL}/api/alerts/clear-all?scope=active", timeout=10)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_clear_all_invalid_scope(auth_headers):
    r = requests.delete(f"{BASE_URL}/api/alerts/clear-all?scope=bogus",
                        headers=auth_headers, timeout=10)
    assert r.status_code == 400


def test_clear_all_active_scope_responds_200(auth_headers):
    # We DO NOT delete real alerts. Use a non-existent client_id to scope to 0 docs.
    fake_client = f"TEST_iter83_noclient_{uuid.uuid4()}"
    r = requests.delete(
        f"{BASE_URL}/api/alerts/clear-all?scope=active&client_id={fake_client}",
        headers=auth_headers, timeout=15)
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "deleted" in body
    assert body["deleted"] == 0
    assert body["scope"] == "active"


def test_clear_all_seed_and_delete(auth_headers):
    """Create a TEST alert via API → delete via clear-all scoped to fake client → verify."""
    fake_client = f"TEST_iter83_client_{uuid.uuid4()}"
    # Create an alert
    payload = {
        "client_id": fake_client,
        "device_id": f"TEST_iter83_dev_{uuid.uuid4()}",
        "severity": "low",
        "source_type": "manual",
        "title": "TEST_iter83 alert",
        "message": "iter-83 test",
    }
    r = requests.post(f"{BASE_URL}/api/alerts", json=payload, headers=auth_headers, timeout=15)
    assert r.status_code == 200, f"create alert failed: {r.status_code} {r.text[:200]}"

    # Now clear scoped to that fake client
    r = requests.delete(
        f"{BASE_URL}/api/alerts/clear-all?scope=active&client_id={fake_client}",
        headers=auth_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] >= 1, f"expected >=1 deleted, got {body}"
    assert body["scope"] == "active"


def test_clear_all_resolved_scope_zero(auth_headers):
    fake_client = f"TEST_iter83_resolved_{uuid.uuid4()}"
    r = requests.delete(
        f"{BASE_URL}/api/alerts/clear-all?scope=resolved&client_id={fake_client}",
        headers=auth_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["deleted"] == 0
