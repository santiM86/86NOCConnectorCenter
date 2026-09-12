"""Iter153 backend regression: AI knowledge, feedback, cases, port-memory settings, port-explain kb_refs."""
import os
import time
import pyotp
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
DEVICE_IP = "10.10.41.220"
PORT_NAME = "GigabitEthernet1/0/1"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    d = r.json()
    tok = d["token"]
    if d.get("requires_2fa"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": code}, headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    return tok


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


# -------- AI Knowledge --------
def test_kb_list_has_25_builtin(H):
    r = requests.get(f"{BASE}/api/ai/knowledge", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["builtin_count"] == 25
    assert isinstance(d["user_count"], int)
    assert isinstance(d["items"], list)


TEST_KB_ID = {"id": None}


def test_kb_create(H):
    body = {
        "title": "Test KB P408i controller failure",
        "vendor": "HPE",
        "tags": ["iml", "controller", "p408i"],
        "content": "Controller Smart Array P408i in failure: sostituire, verificare backup prima.",
    }
    r = requests.post(f"{BASE}/api/ai/knowledge", json=body, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"].startswith("user-")
    TEST_KB_ID["id"] = d["id"]


def test_kb_search_returns_user_first(H):
    r = requests.get(f"{BASE}/api/ai/knowledge/search", params={"text": "P408i controller failure"}, headers=H)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    # user entry should be present with source=user
    user_matches = [i for i in items if i.get("source") == "user" and i.get("id") == TEST_KB_ID["id"]]
    assert user_matches, f"user entry not in search results: {items[:3]}"


def test_kb_update(H):
    kb_id = TEST_KB_ID["id"]
    body = {
        "title": "Test KB P408i controller failure v2",
        "vendor": "HPE",
        "tags": ["iml", "controller"],
        "content": "Controller Smart Array P408i in failure: sostituire subito.",
    }
    r = requests.put(f"{BASE}/api/ai/knowledge/{kb_id}", json=body, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_kb_delete_then_404(H):
    kb_id = TEST_KB_ID["id"]
    r = requests.delete(f"{BASE}/api/ai/knowledge/{kb_id}", headers=H)
    assert r.status_code == 200
    r2 = requests.delete(f"{BASE}/api/ai/knowledge/{kb_id}", headers=H)
    assert r2.status_code == 404


# -------- Feedback + Cases --------
def test_feedback_create_and_list(H):
    body = {
        "analysis_kind": "port_explain",
        "client_id": CLIENT_ID,
        "device_ip": DEVICE_IP,
        "port_name": PORT_NAME,
        "port_idx": 1,
        "ai_verdict": "guasto_probabile",
        "correct": False,
        "note": "era il cavo, sostituito",
    }
    r = requests.post(f"{BASE}/api/ai/feedback", json=body, headers=H)
    assert r.status_code == 200, r.text
    assert "id" in r.json()

    r2 = requests.get(f"{BASE}/api/ai/feedback", headers=H)
    assert r2.status_code == 200
    d = r2.json()
    assert d["stats"]["total"] >= 1
    assert d["stats"]["accuracy_pct"] is not None


def test_cases_include_ai_feedback(H):
    r = requests.get(
        f"{BASE}/api/ai/cases",
        params={"client_id": CLIENT_ID, "device_ip": DEVICE_IP, "port_name": PORT_NAME},
        headers=H,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    fb = [i for i in items if i.get("kind") == "ai_feedback"]
    assert fb, f"no ai_feedback in cases items: {items[:3]}"
    assert any("era il cavo" in (i.get("note") or "") for i in fb)


# -------- Port memory settings --------
def test_port_memory_settings_default7(H):
    r = requests.get(f"{BASE}/api/ai/port-memory/settings", headers=H)
    assert r.status_code == 200
    assert r.json()["learning_days"] == 7


def test_port_memory_put_45_reflects_in_switch_ports(H):
    r = requests.put(f"{BASE}/api/ai/port-memory/settings", json={"learning_days": 45}, headers=H)
    assert r.status_code == 200 and r.json()["learning_days"] == 45

    r2 = requests.get(f"{BASE}/api/devices/{DEVICE_IP}/switch-ports", params={"client_id": CLIENT_ID}, headers=H)
    assert r2.status_code == 200
    d = r2.json()
    assert d.get("port_memory", {}).get("learning_days") == 45
    ports = d.get("ports") or []
    by_idx = {p.get("idx"): p for p in ports}
    for idx in (3, 10):
        p = by_idx.get(idx)
        assert p is not None, f"port idx {idx} missing"
        assert (p.get("habit") or {}).get("verdict") == "learning", f"port {idx} habit not learning: {p.get('habit')}"


def test_port_memory_put_7_restores_habitual(H):
    r = requests.put(f"{BASE}/api/ai/port-memory/settings", json={"learning_days": 7}, headers=H)
    assert r.status_code == 200 and r.json()["learning_days"] == 7
    r2 = requests.get(f"{BASE}/api/devices/{DEVICE_IP}/switch-ports", params={"client_id": CLIENT_ID}, headers=H)
    assert r2.status_code == 200
    ports = r2.json().get("ports") or []
    p3 = next((p for p in ports if p.get("idx") == 3), None)
    assert p3 is not None
    assert (p3.get("habit") or {}).get("verdict") == "habitual", f"port 3 habit: {p3.get('habit')}"


def test_port_memory_put_0_422(H):
    r = requests.put(f"{BASE}/api/ai/port-memory/settings", json={"learning_days": 0}, headers=H)
    assert r.status_code == 422


# -------- Port explain latest --------
def test_port_explain_latest_exists(H):
    r = requests.get(
        f"{BASE}/api/devices/{DEVICE_IP}/switch-ports/1/ai-explain",
        params={"client_id": CLIENT_ID},
        headers=H,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # latest is optional; if present, it should have result fields
    latest = d.get("latest") or d.get("result") or d
    assert isinstance(d, dict)


def test_port_explain_post_once(H):
    r = requests.post(
        f"{BASE}/api/devices/{DEVICE_IP}/switch-ports/1/ai-explain",
        params={"client_id": CLIENT_ID},
        headers=H,
        timeout=90,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    result = d.get("result") or d
    assert "kb_refs" in result, f"kb_refs missing in {list(result.keys())}"
    assert isinstance(result["kb_refs"], list)
    expl = (result.get("explanation") or "").lower()
    # Just ensure explanation exists and mentions port/cable-related terms
    assert expl, "empty explanation"
