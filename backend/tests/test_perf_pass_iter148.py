"""Iter148 — Regressione performance pass: KPI aggregation + Mongo indexes."""
import asyncio
import os
import sys

import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/app/backend/.env")

API = "https://noc-alert-hub-2.preview.emergentagent.com"
EMAIL = "info@86bit.it"
PWD = "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


def auth_token():
    r = requests.post(f"{API}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=15)
    assert r.status_code == 200, r.text
    tmp = r.json()["token"]
    code = pyotp.TOTP(TOTP).now()
    r2 = requests.post(f"{API}/api/auth/verify-2fa", json={"code": code},
                       headers={"Authorization": f"Bearer {tmp}"}, timeout=15)
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def test_kpi_endpoint_and_alerts_breakdown():
    tok = auth_token()
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{API}/api/overview/kpi?period=24h", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    outer = r.json()
    kpi_list = outer.get("kpis", [])
    d = {k["key"]: k for k in kpi_list}
    # 9 kpi keys expected
    expected_keys = {"availability", "clients", "alerts", "opened", "mttr", "noise", "backup", "hw", "agents"}
    got = set(d.keys())
    assert expected_keys.issubset(got), f"missing keys: {expected_keys - got}, got {got}"
    alerts = d["alerts"]
    assert "value" in alerts and "breakdown" in alerts
    bd_sum = sum(alerts["breakdown"].values()) if isinstance(alerts["breakdown"], dict) else None
    print(f"alerts.value={alerts['value']} breakdown_sum={bd_sum} breakdown={alerts['breakdown']}")
    # verify against DB
    return alerts, d


async def _verify():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    # DB count of active/acknowledged alerts
    n = await db.alerts.count_documents({"status": {"$in": ["active", "acknowledged"]}})
    # indexes
    idx = await db.alerts.index_information()
    print("db.alerts indexes:", list(idx.keys()))
    has_status_source = any(
        [("status", 1) in v.get("key", []) and ("source_type", 1) in v.get("key", []) for v in idx.values()]
    )
    has_created_at = any([("created_at", -1) in v.get("key", []) or ("created_at", 1) in v.get("key", []) for v in idx.values()])
    print(f"db_alerts_active_ack={n}, has_status_source_index={has_status_source}, has_created_at_index={has_created_at}")
    return n, has_status_source, has_created_at


def test_overview_clients_200():
    tok = auth_token()
    r = requests.get(f"{API}/api/overview/clients", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    assert r.status_code == 200, r.text
    print(f"overview/clients OK — {len(r.json().get('clients', []))} client(s)")


if __name__ == "__main__":
    alerts, full = test_kpi_endpoint_and_alerts_breakdown()
    db_n, has_ss, has_ca = asyncio.run(_verify())
    # Check alerts.value matches DB count
    assert alerts["value"] == db_n, f"kpi.alerts.value={alerts['value']} but DB active/ack={db_n}"
    print(f"PASS: kpi.alerts.value == DB count = {db_n}")
    # Check breakdown sums to value
    if isinstance(alerts["breakdown"], dict):
        bd_sum = sum(alerts["breakdown"].values())
        assert bd_sum == alerts["value"], f"breakdown sum {bd_sum} != value {alerts['value']}"
        print(f"PASS: alerts.breakdown sum = {bd_sum} == alerts.value")
    # Indexes
    assert has_ss, "Missing composite index on (status, source_type)"
    assert has_ca, "Missing created_at index"
    print("PASS: required Mongo indexes present on db.alerts")
    test_overview_clients_200()
    print("\nALL PERF PASS TESTS PASSED (iter148)")
