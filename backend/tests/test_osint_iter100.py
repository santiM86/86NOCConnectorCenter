"""
OSINT / Threat Intelligence endpoints — iteration 100
Modulo: /api/osint (status, refresh, keys, lookup, kev, exposure)
"""
import os
import re
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def creds():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    email = re.search(r"(?im)^\s*-\s*Email:\s*`([^`]+)`", content).group(1)
    pwd = re.search(r"(?im)^\s*-\s*Password:\s*`([^`]+)`", content).group(1)
    return {"email": email, "password": pwd}


@pytest.fixture(scope="module")
def client(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"Login failed {r.status_code}: {r.text[:300]}")
    token = r.json().get("token") or r.json().get("access_token")
    if not token:
        pytest.fail(f"No token in login response: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---------- STATUS ----------
class TestStatus:
    def test_status_contract(self, client):
        r = client.get(f"{BASE_URL}/api/osint/status", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ("feeds", "ioc_total", "kev_total", "exposure_total", "exposure_with_kev", "keys"):
            assert k in d, f"missing key {k}"
        assert d["ioc_total"] > 0, "ioc_total should be > 0"
        assert d["kev_total"] > 0, "kev_total should be > 0"
        keys = d["keys"]
        assert set(keys.keys()) == {"abusech", "abuseipdb", "greynoise", "nvd"}, keys.keys()
        for p, v in keys.items():
            assert "configured" in v and "masked_key" in v and "updated_at" in v

    def test_keyless_feeds_success(self, client):
        d = client.get(f"{BASE_URL}/api/osint/status", timeout=90).json()
        feeds = d["feeds"]
        for src in ("feodo", "spamhaus_drop", "firehol_level1", "cisa_kev"):
            assert src in feeds, f"feed {src} missing from status"
            assert feeds[src]["status"] == "success", f"{src} -> {feeds[src]}"
            assert feeds[src]["count"] > 0

    def test_status_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/osint/status", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------- REFRESH ----------
class TestRefresh:
    def test_refresh_forces_feeds(self, client):
        r = client.post(f"{BASE_URL}/api/osint/refresh", timeout=180)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("ok") is True
        assert "results" in d and "status" in d
        res = d["results"]
        for src in ("feodo", "spamhaus_drop", "firehol_level1", "cisa_kev"):
            assert src in res
            assert res[src] is None or isinstance(res[src], int)
        assert res.get("threatfox") is None, "threatfox should be skipped without key"

    def test_refresh_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/osint/refresh", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------- KEV ----------
class TestKev:
    def test_kev_list(self, client):
        r = client.get(f"{BASE_URL}/api/osint/kev", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["items"], list) and d["total"] == len(d["items"])
        assert d["total"] > 0
        item = d["items"][0]
        for k in ("cve_id", "vendor", "product", "name", "date_added"):
            assert k in item
        assert "_id" not in item

    def test_kev_search(self, client):
        r = client.get(f"{BASE_URL}/api/osint/kev", params={"q": "fortinet"}, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["total"] > 0, "expected fortinet KEV entries"
        blob = " ".join(
            f"{i.get('vendor')} {i.get('product')} {i.get('name')} {i.get('cve_id')}".lower()
            for i in d["items"]
        )
        assert "fortinet" in blob

    def test_kev_search_no_match(self, client):
        r = client.get(f"{BASE_URL}/api/osint/kev", params={"q": "zzz_no_such_vendor_zzz"}, timeout=60)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_kev_limit(self, client):
        r = client.get(f"{BASE_URL}/api/osint/kev", params={"limit": 5}, timeout=60)
        assert r.status_code == 200
        assert len(r.json()["items"]) == 5


# ---------- LOOKUP (SSRF guard) ----------
class TestLookup:
    @pytest.mark.parametrize("ip", ["192.168.1.1", "127.0.0.1", "10.0.0.5", "169.254.1.1", "not-an-ip"])
    def test_private_or_invalid_rejected(self, client, ip):
        r = client.get(f"{BASE_URL}/api/osint/lookup/{ip}", timeout=60)
        assert r.status_code == 400, f"{ip} -> {r.status_code} {r.text[:200]}"

    def test_public_ip_lookup(self, client):
        r = client.get(f"{BASE_URL}/api/osint/lookup/8.8.8.8", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["ip"] == "8.8.8.8"
        assert isinstance(d["local_matches"], list)
        assert isinstance(d["malicious"], bool)
        assert d["abuseipdb"] is None, "should be None without API key"
        assert d["greynoise"] is None, "should be None without API key"
        idb = d["internetdb"]
        assert isinstance(idb, dict) and "error" not in idb, idb
        assert isinstance(idb.get("ports"), list)
        assert isinstance(d["kev_hits"], list)

    def test_lookup_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/osint/lookup/8.8.8.8", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------- EXPOSURE ----------
class TestExposure:
    def test_exposure_list(self, client):
        r = client.get(f"{BASE_URL}/api/osint/exposure", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["items"], list) and d["total"] == len(d["items"])
        if d["items"]:
            it = d["items"][0]
            assert "_id" not in it
            for k in ("public_ip", "client_id", "client_name", "ports", "kev_count", "last_scan"):
                assert k in it, f"missing {k} in exposure item: {it}"

    def test_exposure_client_filter_isolation(self, client):
        d = client.get(f"{BASE_URL}/api/osint/exposure", timeout=60).json()
        if not d["items"]:
            pytest.skip("no exposure findings to filter")
        cid = d["items"][0]["client_id"]
        r = client.get(f"{BASE_URL}/api/osint/exposure", params={"client_id": cid}, timeout=60)
        assert r.status_code == 200
        assert all(i["client_id"] == cid for i in r.json()["items"])
        r2 = client.get(f"{BASE_URL}/api/osint/exposure", params={"client_id": "no-such-client"}, timeout=60)
        assert r2.status_code == 200 and r2.json()["total"] == 0


# ---------- KEYS ----------
class TestKeys:
    PROV = "greynoise"

    def test_set_get_delete_key(self, client):
        r = client.put(f"{BASE_URL}/api/osint/keys/{self.PROV}", json={"api_key": "testkey12345"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["ok"] is True
        assert d["keys"][self.PROV]["configured"] is True
        masked = d["keys"][self.PROV]["masked_key"]
        assert masked and masked.endswith("2345") and "testkey" not in masked, masked

        # persistence via status
        st = client.get(f"{BASE_URL}/api/osint/status", timeout=90).json()
        assert st["keys"][self.PROV]["configured"] is True
        assert st["keys"][self.PROV]["updated_at"]

        # delete
        dr = client.delete(f"{BASE_URL}/api/osint/keys/{self.PROV}", timeout=60)
        assert dr.status_code == 200 and dr.json()["deleted"] is True
        st2 = client.get(f"{BASE_URL}/api/osint/status", timeout=90).json()
        assert st2["keys"][self.PROV]["configured"] is False
        assert st2["keys"][self.PROV]["masked_key"] is None

    def test_invalid_provider(self, client):
        r = client.put(f"{BASE_URL}/api/osint/keys/invalidprovider", json={"api_key": "testkey12345"}, timeout=60)
        assert r.status_code == 400, r.text[:200]
        r2 = client.delete(f"{BASE_URL}/api/osint/keys/invalidprovider", timeout=60)
        assert r2.status_code == 400, r2.text[:200]

    def test_short_key_rejected(self, client):
        r = client.put(f"{BASE_URL}/api/osint/keys/greynoise", json={"api_key": "abc"}, timeout=60)
        assert r.status_code in (400, 422), r.status_code

    def test_keys_require_auth(self):
        r = requests.put(f"{BASE_URL}/api/osint/keys/greynoise", json={"api_key": "testkey12345"}, timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------- REGRESSION: alerts ----------
class TestAlertsRegression:
    def test_alerts_endpoint_ok(self, client):
        r = client.get(f"{BASE_URL}/api/alerts", timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        items = data if isinstance(data, list) else data.get("alerts", data.get("items"))
        assert isinstance(items, list)
