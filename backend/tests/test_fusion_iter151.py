"""Iter151 — Evidence Fusion v2 backend regression."""
import os
import sys
import time
import pyotp
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "10.10.41.50"
SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()},
                headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


# ------------- /api/fusion/device/{ip} -----------------
def test_fusion_device_pc_mario(H):
    r = requests.get(f"{BASE}/api/fusion/device/{IP}", params={"client_id": CID}, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    print("device fusion keys:", list(j.keys()))
    print("root_cause:", j.get("root_cause"), "label:", j.get("label"),
          "conf:", j.get("confidence"), "conflict:", j.get("conflict"), "sources:", j.get("sources"))
    assert j["root_cause"] == "intentional_off", j.get("root_cause")
    assert j["label"] == "Spento volutamente"
    assert j["confidence"] >= 88, f"conf={j['confidence']}"
    assert j["conflict"] is False
    for s in ["datto", "l2", "port", "port_memory", "schedule"]:
        assert s in j["sources"], f"missing source {s}: {j['sources']}"
    assert isinstance(j["evidence"], list) and len(j["evidence"]) > 0
    for e in j["evidence"]:
        assert "source" in e and "title" in e and "votes" in e
    cov = j.get("coverage") or {}
    assert cov.get("sources_count", 0) >= 4, cov
    assert cov.get("max_confidence") == 97, cov


# ------------- /api/fusion/certainty/{cid} -----------------
def test_fusion_certainty(H):
    r = requests.get(f"{BASE}/api/fusion/certainty/{CID}", headers=H, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ["total", "ready_90", "down", "down_ge_90", "avg_max_confidence", "missing_summary", "devices"]:
        assert k in j, f"missing {k}"
    pc = next((d for d in j["devices"] if d["ip"] == IP), None)
    assert pc is not None, "PC-MARIO not in list"
    print("PC-MARIO row:", {k: pc.get(k) for k in ["reachable", "verdict", "confidence", "max_confidence", "sources"]})
    assert pc["reachable"] is False
    assert pc["verdict"] == "intentional_off"
    assert pc["confidence"] >= 88
    assert pc["max_confidence"] == 97
    # check other devices have expected max_confidence and missing[]
    others = [d for d in j["devices"] if d["ip"] != IP]
    with_missing_65 = [d for d in others if d.get("max_confidence") == 65]
    print(f"others total={len(others)}, with max_conf=65: {len(with_missing_65)}")
    assert len(with_missing_65) > 0, "expected some devices with max_confidence=65"
    for d in with_missing_65[:5]:
        keys = {m["key"] for m in d.get("missing") or []}
        assert keys & {"port", "schedule", "datto", "ilo", "port_memory"}, f"unexpected missing keys: {keys}"

    # cache test
    t0 = time.time()
    r2 = requests.get(f"{BASE}/api/fusion/certainty/{CID}", headers=H, timeout=120)
    dt = time.time() - t0
    assert r2.status_code == 200
    print(f"second call latency: {dt:.2f}s (should be fast <2s from cache)")
    assert dt < 3.0, f"cache seems not working, took {dt:.2f}s"


# ------------- /api/fusion/shadow -----------------
def test_alert_engine_run_then_shadow(H):
    rr = requests.post(f"{BASE}/api/alert-engine/run-now", headers=H, timeout=180)
    assert rr.status_code in (200, 202), rr.text
    time.sleep(3)
    r = requests.get(f"{BASE}/api/fusion/shadow", params={"client_id": CID}, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    print("shadow total:", j["total"], "agree:", j["agree"], "disagree:", j["disagree"])
    assert j["total"] >= 1, j
    row = next((r for r in j["rows"] if r.get("device_ip") == IP), None)
    assert row is not None, f"PC-MARIO not in shadow rows: {[r.get('device_ip') for r in j['rows'][:5]]}"
    print("row v1:", row["v1"], "v2 label:", row["v2"]["label"], "conf:", row["v2"]["confidence"])
    assert row["v1"]["root_cause"] == "unreachable"
    assert row["v2"]["label"] == "Spento volutamente"
    assert row["v2"]["confidence"] >= 88
    assert row["agree"] is True
    assert row["applied"] is False


# ------------- /api/fusion/config -----------------
def test_fusion_config_toggle(H):
    r = requests.get(f"{BASE}/api/fusion/config", headers=H)
    assert r.status_code == 200
    print("initial cfg:", r.json())

    r2 = requests.put(f"{BASE}/api/fusion/config", json={"fusion_v2_enabled": True}, headers=H)
    assert r2.status_code == 200, r2.text
    assert r2.json()["fusion_v2_enabled"] is True

    r3 = requests.put(f"{BASE}/api/fusion/config", json={"fusion_v2_enabled": False}, headers=H)
    assert r3.status_code == 200
    assert r3.json()["fusion_v2_enabled"] is False

    # unauth PUT
    r4 = requests.put(f"{BASE}/api/fusion/config", json={"fusion_v2_enabled": True})
    assert r4.status_code in (401, 403), r4.status_code


# ------------- unit sanity of evidence_fusion._score -----------------
def test_score_single_source_capped():
    import evidence_fusion as ef
    L = ef.Ledger()
    L.add("port", "Porta down", "test", {"hardware_down": 1.0}, age_min=1)
    out = ef._score(L, "1.2.3.4")
    print("single-source result:", out["root_cause"], out["confidence"], "conflict:", out["conflict"])
    assert out["confidence"] <= 65


def test_score_conflict_capped():
    import evidence_fusion as ef
    L = ef.Ledger()
    L.add("port", "porta", "t", {"hardware_down": 1.0, "os_hung": 0.75}, age_min=1)
    L.add("l2", "l2", "t", {"hardware_down": 1.0, "os_hung": 0.75}, age_min=1)
    out = ef._score(L, "1.2.3.4")
    print("conflict result:", out["root_cause"], out["confidence"], "conflict:", out["conflict"])
    assert out["conflict"] is True
    assert out["confidence"] <= 60
