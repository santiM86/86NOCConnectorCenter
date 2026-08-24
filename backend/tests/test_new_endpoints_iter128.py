"""Iter128 — nuovi endpoint: POST /api/maintenance/{client_id}/silence-now e
POST /api/security/rogue/investigate. Test tramite ingress pubblico con auth 2FA."""
import os
from datetime import datetime, timezone

import pyotp
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")

EMAIL = "info@86bit.it"
PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in login response: {data}"
    if data.get("requires_2fa"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r2.status_code == 200, f"verify-2fa failed {r2.status_code}: {r2.text[:300]}"
        tok = r2.json().get("token") or r2.json().get("access_token")
        assert tok
    elif data.get("requires_2fa_setup"):
        r2 = s.post(f"{BASE_URL}/api/auth/setup-2fa", json={},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        secret = r2.json()["secret"]
        r3 = s.post(f"{BASE_URL}/api/auth/confirm-2fa", json={"code": pyotp.TOTP(secret).now()},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r3.status_code == 200, r3.text[:300]
        tok = r3.json()["token"]
    return tok


@pytest.fixture(scope="module")
def client(token):
    r = requests.get(f"{BASE_URL}/api/clients", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert r.status_code == 200, f"/api/clients {r.status_code}: {r.text[:300]}"
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items") or items.get("clients") or []
    assert items, "no clients available"
    return items[0]


class TestSilenceNow:
    """POST /api/maintenance/{client_id}/silence-now"""

    def test_silence_now_hours(self, token, client):
        h = {"Authorization": f"Bearer {token}"}
        cid = client["id"]
        r = requests.post(f"{BASE_URL}/api/maintenance/{cid}/silence-now", json={"hours": 1},
                          headers=h, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        w = r.json()
        assert w["client_id"] == cid
        assert w["status"] == "active"
        assert w["suppress_alerts"] is True
        assert w["recurring"] is False
        assert "id" in w and isinstance(w["id"], str)
        assert "_id" not in w
        start = datetime.fromisoformat(w["start_time"])
        end = datetime.fromisoformat(w["end_time"])
        assert abs((end - start).total_seconds() - 3600) < 5

        # GET verify persistence + active gate
        g = requests.get(f"{BASE_URL}/api/maintenance/{cid}", headers=h, timeout=30)
        assert g.status_code == 200
        assert any(x["id"] == w["id"] for x in g.json()), "window not persisted in list"

        a = requests.get(f"{BASE_URL}/api/maintenance/active/{cid}", timeout=30)
        assert a.status_code == 200
        assert a.json().get("in_maintenance") is True

        # cleanup
        d = requests.delete(f"{BASE_URL}/api/maintenance/{cid}/{w['id']}", headers=h, timeout=30)
        assert d.status_code in (200, 204)
        g2 = requests.get(f"{BASE_URL}/api/maintenance/{cid}", headers=h, timeout=30)
        assert not any(x["id"] == w["id"] for x in g2.json())

    def test_silence_now_until_tomorrow(self, token, client):
        h = {"Authorization": f"Bearer {token}"}
        cid = client["id"]
        r = requests.post(f"{BASE_URL}/api/maintenance/{cid}/silence-now",
                          json={"until_tomorrow": True}, headers=h, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        w = r.json()
        end = datetime.fromisoformat(w["end_time"])
        assert end > datetime.now(timezone.utc)
        assert "domani" in w["title"].lower()
        requests.delete(f"{BASE_URL}/api/maintenance/{cid}/{w['id']}", headers=h, timeout=30)

    def test_silence_now_requires_auth(self, client):
        r = requests.post(f"{BASE_URL}/api/maintenance/{client['id']}/silence-now",
                          json={"hours": 1}, timeout=30)
        assert r.status_code in (401, 403), f"unexpected {r.status_code}"


class TestRogueInvestigate:
    """POST /api/security/rogue/investigate"""

    def test_investigate_ok(self, token, client):
        h = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE_URL}/api/security/rogue/investigate",
                          json={"client_id": client["id"], "mac": "aa:bb:cc:dd:ee:ff", "note": "TEST_iter128"},
                          headers=h, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("mac") == "aa:bb:cc:dd:ee:ff"
        assert isinstance(data.get("updated"), int)

    def test_investigate_validation(self, token):
        h = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE_URL}/api/security/rogue/investigate",
                          json={"client_id": "x"}, headers=h, timeout=30)
        assert r.status_code == 422, f"expected 422, got {r.status_code}"

    def test_investigate_requires_auth(self, client):
        r = requests.post(f"{BASE_URL}/api/security/rogue/investigate",
                          json={"client_id": client["id"], "mac": "aa:bb:cc:dd:ee:ff"}, timeout=30)
        assert r.status_code in (401, 403)

    def test_rogue_status(self, token):
        r = requests.get(f"{BASE_URL}/api/security/rogue/status",
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "config" in d and "active_alerts" in d
