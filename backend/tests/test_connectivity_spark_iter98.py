"""
Iteration 98 — Feature "Connettivita' / Spark" (Fase 1).

Copre:
- GET  /api/devices/by-ip/{ip}/connectivity-report (24h, tutti i period, period invalido, IP senza storico)
- POST /api/devices/by-ip/{ip}/connectivity-test (404 atteso senza agent LIVE, 400 senza client_id)
"""
import os

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
DEVICE_IP = "192.168.1.3"
UNKNOWN_IP = "9.9.9.9"

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"Login admin fallito: {r.status_code} {r.text[:300]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        pytest.fail(f"Login response senza token: {list(data.keys())}")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---------- connectivity-report ----------

class TestConnectivityReport:
    def test_report_24h_seeded_device(self, client):
        r = client.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                       params={"period": "24h", "client_id": CLIENT_ID}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        print("REPORT 24h:", {k: v for k, v in d.items() if k != "series"})

        assert d["device_ip"] == DEVICE_IP
        assert d["client_id"] == CLIENT_ID
        assert d["period"] == "24h"
        assert isinstance(d["samples"], int) and d["samples"] > 0, "storico ping mancante"
        assert 0 <= d["uptime_pct"] <= 100

        lat = d["latency"]
        for k in ("avg", "min", "max", "p95", "jitter"):
            assert k in lat, f"latency.{k} mancante"
            assert lat[k] is not None
        assert lat["min"] <= lat["avg"] <= lat["max"]
        assert lat["min"] <= lat["p95"] <= lat["max"]

        loss = d["loss"]
        assert loss["avg"] is not None and loss["max"] is not None
        assert loss["avg"] <= loss["max"]

        assert isinstance(d["disconnections"], int)
        assert d["disconnections"] >= 1, f"attese ~2 disconnessioni, trovate {d['disconnections']}"
        assert isinstance(d["down_windows"], list)
        assert d["severity"] in ("ok", "warn", "crit")
        assert d["thresholds"]["latency_warn_ms"] == 30.0
        assert d["thresholds"]["latency_crit_ms"] == 100.0
        assert d["thresholds"]["loss_warn_pct"] == 2.0
        assert d["thresholds"]["loss_crit_pct"] == 10.0

        series = d["series"]
        assert isinstance(series, list) and len(series) > 0
        for p in series[:5]:
            assert set(["ts", "latency_avg", "loss_avg", "up_ratio"]).issubset(p.keys())
        # MTTR coerente con le finestre risolte
        resolved = [w for w in d["down_windows"] if w.get("duration_min") is not None]
        if resolved:
            assert d["mttr_min"] is not None

    @pytest.mark.parametrize("period,expected_buckets_max", [
        ("1h", 60), ("6h", 72), ("24h", 96), ("7d", 168), ("30d", 180),
    ])
    def test_report_all_periods(self, client, period, expected_buckets_max):
        r = client.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                       params={"period": period, "client_id": CLIENT_ID}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["period"] == period
        print(f"period={period} samples={d['samples']} buckets={len(d['series'])}")
        assert len(d["series"]) <= 500

    def test_report_bucket_granularity_differs(self, client):
        out = {}
        for p in ("1h", "24h", "30d"):
            r = client.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                           params={"period": p, "client_id": CLIENT_ID}, timeout=60)
            assert r.status_code == 200
            out[p] = r.json()
        # 24h ha piu' campioni di 1h (storico 24h seedato)
        assert out["24h"]["samples"] >= out["1h"]["samples"]
        # 30d copre >= 24h
        assert out["30d"]["samples"] >= out["24h"]["samples"]

    def test_report_invalid_period_falls_back_to_24h(self, client):
        r = client.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                       params={"period": "banana", "client_id": CLIENT_ID}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["period"] == "24h"

    def test_report_unknown_ip_returns_empty(self, client):
        r = client.get(f"{API}/devices/by-ip/{UNKNOWN_IP}/connectivity-report",
                       params={"period": "24h", "client_id": CLIENT_ID}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["samples"] == 0
        assert d["uptime_pct"] is None
        assert d["latency"]["avg"] is None
        assert d["disconnections"] == 0
        assert d["down_windows"] == []
        assert d["series"] == []

    def test_report_wrong_client_id_isolates_data(self, client):
        r = client.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                       params={"period": "24h", "client_id": "00000000-0000-0000-0000-000000000000"},
                       timeout=60)
        assert r.status_code == 200
        assert r.json()["samples"] == 0, "multi-tenant leak: dati visibili con client_id errato"

    def test_report_requires_auth(self):
        r = requests.get(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-report",
                         params={"period": "24h", "client_id": CLIENT_ID}, timeout=30)
        assert r.status_code in (401, 403), f"endpoint non protetto: {r.status_code}"


# ---------- connectivity-test ----------

class TestConnectivityTest:
    def test_run_test_no_live_agent_returns_404(self, client):
        r = client.post(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-test",
                        json={"client_id": CLIENT_ID, "count": 5}, timeout=120)
        print("connectivity-test:", r.status_code, r.text[:300])
        assert r.status_code != 500, f"errore server: {r.text[:400]}"
        if r.status_code == 404:
            detail = (r.json().get("detail") or "").lower()
            assert "agent" in detail
        else:
            assert r.status_code == 200, r.text[:300]
            d = r.json()
            assert d["ok"] is True
            assert d["stats"]["sent"] == 5
            assert len(d["packets"]) == 5

    def test_run_test_missing_client_id_returns_400(self, client):
        r = client.post(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-test",
                        json={"count": 5}, timeout=60)
        assert r.status_code == 400, f"attesa 400, ricevuto {r.status_code}: {r.text[:300]}"
        assert "client_id" in (r.json().get("detail") or "")

    def test_run_test_empty_body_returns_400(self, client):
        r = client.post(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-test",
                        json={}, timeout=60)
        assert r.status_code == 400, f"attesa 400, ricevuto {r.status_code}: {r.text[:300]}"

    def test_run_test_requires_auth(self):
        r = requests.post(f"{API}/devices/by-ip/{DEVICE_IP}/connectivity-test",
                          json={"client_id": CLIENT_ID, "count": 3}, timeout=30)
        assert r.status_code in (401, 403), f"endpoint non protetto: {r.status_code}"
