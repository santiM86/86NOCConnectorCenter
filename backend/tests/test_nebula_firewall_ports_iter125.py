"""Iter125 — Zyxel Nebula firewall: porte reali (ports-status), public_ip, line_state, NAT.

Endpoint sotto test: GET /api/clients/{client_id}/zyxel/devices
"""
import os
import re
from pathlib import Path

import pytest
import pyotp
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def creds():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing test_credentials.md")
    c = p.read_text(encoding="utf-8")
    e = re.search(r'(?im)^-\s*Email:\s*`([^`]+)`', c)
    pw = re.search(r'(?im)^-\s*Password:\s*`([^`]+)`', c)
    if not e or not pw:
        pytest.skip("no creds parsed")
    return {"email": e.group(1), "password": pw.group(1)}


@pytest.fixture(scope="module")
def client(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": creds["email"], "password": creds["password"]}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("token")
    if data.get("requires_2fa"):
        s.headers.update({"Authorization": f"Bearer {token}"})
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        token = r2.json().get("token")
    if not token:
        pytest.fail("no token obtained")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def payload(client):
    r = client.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/zyxel/devices", timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    return r.json()


class TestZyxelDevicesEndpoint:
    def test_auth_required(self):
        r = requests.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/zyxel/devices", timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_shape(self, payload):
        assert isinstance(payload.get("devices"), list)
        assert payload.get("count") == len(payload["devices"])
        assert payload["count"] > 0, "nessun device Zyxel sincronizzato per il client di test"

    def test_no_mongo_id(self, payload):
        for d in payload["devices"]:
            assert "_id" not in d

    def test_firewall_present(self, payload):
        fws = [d for d in payload["devices"] if d.get("device_type") == "firewall"]
        assert fws, "nessun firewall (device_type=='firewall') trovato"

    def test_firewall_fields(self, payload):
        fw = [d for d in payload["devices"] if d.get("device_type") == "firewall"][0]
        for k in ("dev_id", "model", "sn", "mac", "online_status"):
            assert fw.get(k), f"campo {k} mancante/vuoto: {fw.get(k)!r}"
        assert "public_ip" in fw and fw["public_ip"], f"public_ip mancante: {fw.get('public_ip')}"
        assert fw.get("line_state") in ("up", "down"), fw.get("line_state")
        assert isinstance(fw.get("wan_interfaces"), list) and fw["wan_interfaces"], "wan_interfaces vuoto"
        assert isinstance(fw.get("nat_rules"), list), "nat_rules non è una lista"

    def test_firewall_ports_real(self, payload):
        fw = [d for d in payload["devices"] if d.get("device_type") == "firewall"][0]
        ports = fw.get("ports")
        assert isinstance(ports, list) and len(ports) > 0, f"ports vuoto/assente: {ports!r}"
        print(f"PORTS({len(ports)}): {ports}")
        for p in ports:
            assert set(("port", "group", "speed", "status")).issubset(p.keys()), p
            assert p["port"] is not None, p
            assert p["status"] in ("up", "down"), p
            # coerenza status <-> linkSpeed
            speed = str(p.get("speed") or "").strip().lower()
            if speed and speed not in ("down", "0", "no link", "n/a", "-"):
                assert p["status"] == "up", f"speed valorizzato ma status down: {p}"
            else:
                assert p["status"] == "down", f"speed vuoto ma status up: {p}"

    def test_ports_status_mix(self, payload):
        fw = [d for d in payload["devices"] if d.get("device_type") == "firewall"][0]
        ups = [p for p in fw["ports"] if p["status"] == "up"]
        assert ups, "nessuna porta up: sospetto parsing linkSpeed errato"

    def test_other_client_no_firewall_ok(self, client):
        """Cliente senza link Nebula: endpoint deve rispondere 200 con lista vuota."""
        r = client.get(f"{BASE_URL}/api/clients/__no_such_client__/zyxel/devices", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json() == {"devices": [], "count": 0}
