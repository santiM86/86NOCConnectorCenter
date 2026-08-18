"""Iteration 118 — Zyxel Nebula (NCC OpenAPI) integration tests.

Copre: config read-only, test connessione, organizations (cache + refresh),
links, devices (flotta), sync-now, PUT client link + devices del cliente.

NOTA: non elimina la config globale ne' il mapping esistente di 86BIT_Office.
Eventuali mapping di test creati su altri clienti vengono rimossi in teardown.
"""
import os
import re
from pathlib import Path

import pyotp
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")

TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


# ==================== Fixtures ====================

@pytest.fixture(scope="session")
def test_credentials():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing /app/memory/test_credentials.md")
    content = p.read_text(encoding="utf-8")
    email = re.search(r'(?im)^\s*-\s*Email:\s*`([^`]+)`', content)
    pwd = re.search(r'(?im)^\s*-\s*Password:\s*`([^`]+)`', content)
    if not email or not pwd:
        pytest.skip("no credentials found")
    return {"email": email.group(1), "password": pwd.group(1)}


@pytest.fixture(scope="session")
def token(test_credentials):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={
        "email": test_credentials["email"],
        "password": test_credentials["password"],
    }, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    if data.get("requires_2fa"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"} if tok else None, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:400]}")
        tok = r2.json().get("token") or r2.json().get("access_token")
    if not tok:
        pytest.fail(f"no token in login response: {str(data)[:400]}")
    return tok


@pytest.fixture(scope="session")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def temp_links():
    """client_ids of test-created links, removed at session end."""
    return []


@pytest.fixture(scope="session")
def temp_clients():
    return []


@pytest.fixture(scope="session", autouse=True)
def cleanup(client, temp_links, temp_clients):
    yield
    for cid in temp_links:
        try:
            client.delete(f"{BASE_URL}/api/clients/{cid}/zyxel/link", timeout=60)
        except Exception:
            pass
    for cid in temp_clients:
        try:
            client.delete(f"{BASE_URL}/api/clients/{cid}", timeout=60)
        except Exception:
            pass


# ==================== Config ====================

class TestZyxelConfig:
    def test_get_config_configured_and_masked(self, client):
        r = client.get(f"{BASE_URL}/api/admin/zyxel/config", timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["configured"] is True, f"expected configured=true, got {d}"
        preview = d["api_key_preview"]
        assert "****" in preview, f"api_key_preview not masked: {preview}"
        assert len(preview) <= 16, f"preview too long (possible leak): {preview}"
        assert "nebula" in d["base_url"].lower()

    def test_config_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/zyxel/config", timeout=60)
        assert r.status_code in (401, 403), f"unauthenticated access allowed: {r.status_code}"

    def test_connection_test(self, client):
        r = client.post(f"{BASE_URL}/api/admin/zyxel/test", timeout=120)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["ok"] is True
        assert d["org_count"] > 0, f"org_count={d['org_count']}"
        assert d["pro_org_count"] > 0, f"pro_org_count={d['pro_org_count']}"
        assert isinstance(d.get("sample"), list) and len(d["sample"]) > 0
        assert d["sample"][0].get("orgId")


# ==================== Organizations ====================

class TestZyxelOrganizations:
    def test_list_orgs_cached(self, client):
        r = client.get(f"{BASE_URL}/api/zyxel/organizations", timeout=120)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        orgs = d["organizations"]
        assert len(orgs) > 0
        for o in orgs[:5]:
            assert o.get("org_id")
            assert "name" in o and "mode" in o

    def test_list_orgs_refresh(self, client):
        r = client.get(f"{BASE_URL}/api/zyxel/organizations?refresh=true", timeout=180)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["cached"] is False
        assert len(d["organizations"]) > 0
        assert any((o.get("mode") or "").upper() == "PRO" for o in d["organizations"])

    def test_org_sites_and_devices(self, client):
        links = client.get(f"{BASE_URL}/api/zyxel/links", timeout=60).json()["links"]
        assert links, "no existing zyxel links to derive an org from"
        org_id = links[0]["org_id"]
        rs = client.get(f"{BASE_URL}/api/zyxel/organizations/{org_id}/sites", timeout=120)
        assert rs.status_code == 200, rs.text[:400]
        assert isinstance(rs.json()["sites"], list)
        rd = client.get(f"{BASE_URL}/api/zyxel/organizations/{org_id}/devices", timeout=120)
        assert rd.status_code == 200, rd.text[:400]
        assert isinstance(rd.json()["devices"], list)


# ==================== Links & fleet ====================

class TestZyxelLinksAndDevices:
    def test_links_have_device_count(self, client):
        r = client.get(f"{BASE_URL}/api/zyxel/links", timeout=60)
        assert r.status_code == 200, r.text[:400]
        links = r.json()["links"]
        assert len(links) >= 1, "expected at least the 86BIT_Office mapping"
        for l in links:
            assert l.get("client_id") and l.get("org_id")
            assert isinstance(l.get("device_count"), int)
            assert "_id" not in l

    def test_fleet_devices_fields(self, client):
        r = client.get(f"{BASE_URL}/api/zyxel/devices", timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        devs = d["devices"]
        assert d["count"] == len(devs)
        assert len(devs) > 0, "fleet is empty"
        assert all("_id" not in x for x in devs)
        for x in devs:
            assert x.get("dev_id")
            assert x.get("device_type") in ("firewall", "switch", "ap", "network")
        fw = [x for x in devs if "700H" in (x.get("model") or "")]
        assert fw, f"USG FLEX 700H not found; models={[x.get('model') for x in devs]}"
        h = fw[0]
        assert h.get("online_status") == "ONLINE", f"700H status={h.get('online_status')}"
        assert isinstance(h.get("cpu_usage"), (int, float)), f"cpu_usage={h.get('cpu_usage')}"
        assert isinstance(h.get("mem_usage"), (int, float)), f"mem_usage={h.get('mem_usage')}"
        assert isinstance(h.get("sessions"), (int, float)), f"sessions={h.get('sessions')}"
        assert h.get("firmware", {}).get("current"), f"firmware={h.get('firmware')}"

    def test_sync_now(self, client):
        r = client.post(f"{BASE_URL}/api/zyxel/sync-now", timeout=290)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["clients"] >= 1
        assert d["devices_synced"] >= 0
        assert d["errors"] == [], f"sync errors: {d['errors']}"

    def test_client_devices_for_existing_link(self, client):
        links = client.get(f"{BASE_URL}/api/zyxel/links", timeout=60).json()["links"]
        cid = links[0]["client_id"]
        r = client.get(f"{BASE_URL}/api/clients/{cid}/zyxel/devices", timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["count"] == len(d["devices"])
        assert all(x["client_id"] == cid for x in d["devices"])

    def test_get_link_for_existing_client(self, client):
        links = client.get(f"{BASE_URL}/api/zyxel/links", timeout=60).json()["links"]
        cid = links[0]["client_id"]
        r = client.get(f"{BASE_URL}/api/clients/{cid}/zyxel/link", timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["linked"] is True
        assert d["org_id"] == links[0]["org_id"]

    def test_put_link_invalid_client_404(self, client):
        orgs = client.get(f"{BASE_URL}/api/zyxel/organizations", timeout=120).json()["organizations"]
        r = client.put(f"{BASE_URL}/api/clients/TEST_nonexistent_client/zyxel/link",
                       json={"org_id": orgs[0]["org_id"]}, timeout=120)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:300]}"

    def test_put_link_validation_error(self, client):
        r = client.put(f"{BASE_URL}/api/clients/whatever/zyxel/link", json={"org_id": "x"}, timeout=60)
        assert r.status_code == 422, f"expected 422 for too-short org_id, got {r.status_code}"

    def test_create_link_on_other_client_and_sync(self, client, temp_links, temp_clients):
        """PUT link on a NON-mapped (temp) client -> mapping created + immediate sync."""
        cr = client.post(f"{BASE_URL}/api/clients", json={
            "name": "TEST_zyxel_iter118", "description": "temp client for zyxel link test",
            "contact_email": "qa@example.test",
        }, timeout=60)
        assert cr.status_code in (200, 201), cr.text[:400]
        target = {"id": cr.json()["id"]}
        temp_clients.append(target["id"])

        orgs = client.get(f"{BASE_URL}/api/zyxel/organizations", timeout=120).json()["organizations"]
        pro = next((o for o in orgs if (o.get("mode") or "").upper() == "PRO"), orgs[0])

        r = client.put(f"{BASE_URL}/api/clients/{target['id']}/zyxel/link",
                       json={"org_id": pro["org_id"]}, timeout=290)
        assert r.status_code == 200, r.text[:500]
        temp_links.append(target["id"])
        d = r.json()
        assert d["linked"] is True
        assert d["org_id"] == pro["org_id"]
        assert d["org_name"] == pro["name"]
        assert isinstance(d["device_count"], int)

        # GET verifies persistence
        g = client.get(f"{BASE_URL}/api/clients/{target['id']}/zyxel/link", timeout=60)
        assert g.status_code == 200
        assert g.json()["linked"] is True
        assert g.json()["org_id"] == pro["org_id"]

        dv = client.get(f"{BASE_URL}/api/clients/{target['id']}/zyxel/devices", timeout=60)
        assert dv.status_code == 200
        assert dv.json()["count"] == d["device_count"]

    def test_delete_temp_link_removes_devices(self, client, temp_links):
        if not temp_links:
            pytest.skip("no temp link created")
        cid = temp_links[0]
        r = client.delete(f"{BASE_URL}/api/clients/{cid}/zyxel/link", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["linked"] is False
        g = client.get(f"{BASE_URL}/api/clients/{cid}/zyxel/link", timeout=60)
        assert g.json()["linked"] is False
        dv = client.get(f"{BASE_URL}/api/clients/{cid}/zyxel/devices", timeout=60)
        assert dv.json()["count"] == 0
        temp_links.remove(cid)
