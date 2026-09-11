"""Backend tests for KPI Strip (Panoramica) - iteration 145.

Covers:
- GET /api/overview/kpi with period=24h/7d/30d and invalid period
- Response structure (keys order, per-item fields)
- Consistency (alerts.value vs DB, availability sub vs /overview/clients)
- record_kpi_snapshot() flow: sparkline/trend appear once >=2 snapshots
- Auth guard
"""
import os
import time
import pytest
import requests
import pyotp
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"

EXPECTED_KEYS = ["availability", "clients", "alerts", "opened", "mttr", "noise", "backup", "hw", "agents"]


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    j = r.json()
    tmp = j.get("token") or j.get("access_token") or j.get("temp_token")
    if j.get("requires_2fa") or j.get("mfa_required") or True:
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa",
                    json={"code": code},
                    headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
        if r2.status_code != 200:
            # maybe not required
            return tmp
        return r2.json().get("token") or r2.json().get("access_token") or tmp
    return tmp


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---- Auth guard ----
def test_kpi_requires_auth():
    r = requests.get(f"{BASE_URL}/api/overview/kpi", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---- Basic structure per period ----
@pytest.mark.parametrize("period", ["24h", "7d", "30d"])
def test_kpi_structure(auth_headers, period):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": period},
                     headers=auth_headers, timeout=25)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 20, f"KPI too slow: {elapsed:.1f}s"
    data = r.json()
    for k in ("period", "from", "to", "snapshots", "baseline_at", "kpis"):
        assert k in data, f"missing top-level key: {k}"
    assert data["period"] == period
    assert isinstance(data["kpis"], list) and len(data["kpis"]) == 9
    keys = [k["key"] for k in data["kpis"]]
    assert keys == EXPECTED_KEYS, f"KPI order wrong: {keys}"
    for item in data["kpis"]:
        for f in ("key", "label", "value", "unit", "sub", "trend", "series", "link", "tone"):
            assert f in item, f"kpi {item.get('key')} missing {f}"
        assert isinstance(item["series"], list)
        assert item["trend"] is None or set(item["trend"].keys()) >= {"delta", "pct", "good"}


def test_kpi_invalid_period_falls_back(auth_headers):
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "xxx"},
                     headers=auth_headers, timeout=25)
    assert r.status_code == 200
    assert r.json()["period"] == "24h"


def test_opened_series_sum_matches_value(auth_headers):
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "24h"},
                     headers=auth_headers, timeout=25)
    assert r.status_code == 200
    kpis = {k["key"]: k for k in r.json()["kpis"]}
    opened = kpis["opened"]
    assert isinstance(opened["series"], list)
    assert len(opened["series"]) == 24, f"opened.series has {len(opened['series'])} buckets"
    assert sum(opened["series"]) == opened["value"], \
        f"sum({sum(opened['series'])}) != value({opened['value']})"


def test_alerts_breakdown_present(auth_headers):
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "24h"},
                     headers=auth_headers, timeout=25)
    kpis = {k["key"]: k for k in r.json()["kpis"]}
    br = kpis["alerts"].get("breakdown")
    assert br is not None
    for sev in ("critical", "high", "medium", "low"):
        assert sev in br


# ---- Consistency vs DB ----
def test_alerts_value_matches_db(auth_headers):
    import pymongo
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = pymongo.MongoClient(mongo_url)
    db = client[db_name]
    db_count = db.alerts.count_documents({"status": {"$in": ["active", "acknowledged"]}})
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "24h"},
                     headers=auth_headers, timeout=25)
    kpis = {k["key"]: k for k in r.json()["kpis"]}
    api_val = kpis["alerts"]["value"]
    # tolerate slight timing drift
    assert abs(api_val - db_count) <= 5, f"alerts.value={api_val} vs db={db_count}"


def test_opened_7d_matches_db(auth_headers):
    import pymongo
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = pymongo.MongoClient(mongo_url)
    db = client[db_name]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    db_count = db.alerts.count_documents({"created_at": {"$gte": cutoff}})
    r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "7d"},
                     headers=auth_headers, timeout=25)
    kpis = {k["key"]: k for k in r.json()["kpis"]}
    api_val = kpis["opened"]["value"]
    assert abs(api_val - db_count) <= 5, f"opened.value={api_val} vs db(7d)={db_count}"


def test_availability_matches_overview_clients(auth_headers):
    r1 = requests.get(f"{BASE_URL}/api/overview/clients", headers=auth_headers, timeout=25)
    assert r1.status_code == 200
    g = (r1.json().get("global") or {})
    online = g.get("devices_online")
    total = g.get("total_devices")
    r2 = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "24h"},
                     headers=auth_headers, timeout=25)
    kpis = {k["key"]: k for k in r2.json()["kpis"]}
    sub = kpis["availability"]["sub"]
    assert f"{online}/{total} online" == sub, f"sub={sub!r} vs {online}/{total}"


# ---- Snapshots: baseline + trend appear once >=2 snapshots ----
def test_record_kpi_snapshot_enables_trend(auth_headers):
    """Insert two fake snapshots and verify baseline/trend/series activate."""
    import pymongo
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = pymongo.MongoClient(mongo_url)
    db = client[db_name]
    now = datetime.now(timezone.utc)
    fake = [
        {"at": (now - timedelta(minutes=30)).isoformat(), "availability_pct": 50.0,
         "vital_online": 1, "vital_total": 2, "clients_total": 1, "clients_critical": 0,
         "clients_warning": 0, "alerts_active": {"critical": 0, "high": 0, "medium": 0, "low": 0},
         "agents_total": 0, "agents_offline": 0, "backup_ko": 0, "backup_total": 0,
         "hw_risk": 0, "hw_predicted": 0, "_test_iter145": True},
        {"at": (now - timedelta(minutes=15)).isoformat(), "availability_pct": 75.0,
         "vital_online": 1, "vital_total": 2, "clients_total": 1, "clients_critical": 0,
         "clients_warning": 0, "alerts_active": {"critical": 0, "high": 0, "medium": 0, "low": 0},
         "agents_total": 0, "agents_offline": 0, "backup_ko": 0, "backup_total": 0,
         "hw_risk": 0, "hw_predicted": 0, "_test_iter145": True},
    ]
    ins = db.kpi_snapshots.insert_many(fake)
    try:
        r = requests.get(f"{BASE_URL}/api/overview/kpi", params={"period": "24h"},
                         headers=auth_headers, timeout=25)
        assert r.status_code == 200
        data = r.json()
        assert data["snapshots"] >= 1, f"snapshots={data['snapshots']}"
        assert data["baseline_at"] is not None, "baseline_at should be set"
        kpis = {k["key"]: k for k in data["kpis"]}
        avail = kpis["availability"]
        assert avail["trend"] is not None, "availability.trend should be non-null after 2 snaps"
        assert len(avail["series"]) >= 2, f"series len {len(avail['series'])}"
    finally:
        db.kpi_snapshots.delete_many({"_test_iter145": True})
