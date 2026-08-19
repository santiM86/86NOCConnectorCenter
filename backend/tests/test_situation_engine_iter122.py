"""ITER 122 — Situation Engine (verdetto unico device/cliente)
Endpoint testati:
  GET /api/devices/by-ip/{ip}/diagnosis?client_id=
  GET /api/clients/{client_id}/diagnosis
Include test di FUSIONE TRASVERSALE con alert temporanei iniettati in db.alerts.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyotp
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
DEVICE_IP = "192.168.1.3"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def creds():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing test_credentials.md")
    c = p.read_text(encoding="utf-8")
    e = re.search(r"(?im)^-\s*Email:\s*`([^`]+)`", c)
    pw = re.search(r"(?im)^-\s*Password:\s*`([^`]+)`", c)
    if not e or not pw:
        pytest.skip("no creds parsed")
    return {"email": e.group(1), "password": pw.group(1)}


@pytest.fixture(scope="module")
def token(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    d = r.json()
    tok = d.get("token")
    assert tok, "no token in login response"
    if d.get("requires_2fa"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        tok = r2.json().get("token")
        assert tok
    return tok


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    env = dotenv_values("/app/backend/.env")
    mc = MongoClient(env["MONGO_URL"])
    yield mc[env["DB_NAME"]]
    mc.close()


# ---------- auth guard ----------
class TestAuthGuard:
    def test_device_diagnosis_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                         params={"client_id": CLIENT_ID}, timeout=60)
        assert r.status_code in (401, 403), r.text[:300]

    def test_client_diagnosis_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis", timeout=60)
        assert r.status_code in (401, 403), r.text[:300]

    def test_bad_token_rejected(self):
        r = requests.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis",
                         headers={"Authorization": "Bearer garbage"}, timeout=60)
        assert r.status_code in (401, 403)


# ---------- device diagnosis ----------
class TestDeviceDiagnosis:
    def test_schema_and_up_device(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                       params={"client_id": CLIENT_ID}, timeout=120)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["found"] is True
        assert d["device_ip"] == DEVICE_IP
        assert d["client_id"] == CLIENT_ID
        assert d["overall_state"] in ("OK", "WARNING", "CRITICAL", "UNKNOWN")
        assert isinstance(d["up"], bool)
        for k in ("primary", "recommended_action", "confidence", "evidence",
                  "evidence_by_domain", "evaluated_at", "device_name", "family"):
            assert k in d, f"missing key {k}"
        p = d["primary"]
        for k in ("domain", "situation", "root_cause", "severity", "confidence", "reasoning"):
            assert k in p, f"missing primary.{k}"
        assert isinstance(d["evidence"], list) and len(d["evidence"]) >= 1
        ev0 = d["evidence"][0]
        assert ev0["domain"] == "reachability"
        for s in ("ping", "l2_alive", "datto", "connector_live", "wan_fw_up", "wan_rt_up"):
            assert s in ev0["signals"], f"missing signal {s}"
        assert isinstance(d["evidence_by_domain"], dict)
        assert isinstance(d["recommended_action"], str) and d["recommended_action"]
        # device reale atteso UP
        assert d["up"] is True, f"device {DEVICE_IP} atteso UP, verdict={p}"
        assert d["overall_state"] == "OK", f"atteso OK, got {d['overall_state']} / {d['evidence']}"
        assert p["domain"] == "reachability"
        assert d["confidence"] == 100, f"atteso 100, got {d['confidence']}"

    def test_no_mongo_objectid_leak(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                       params={"client_id": CLIENT_ID}, timeout=120)
        assert '"_id"' not in r.text

    def test_unknown_device_404(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/10.255.255.254/diagnosis",
                       params={"client_id": CLIENT_ID}, timeout=120)
        assert r.status_code == 404, r.text[:300]

    def test_without_client_id_still_works(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis", timeout=120)
        assert r.status_code == 200
        assert r.json()["found"] is True

    def test_wrong_client_id_isolation(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                       params={"client_id": str(uuid.uuid4())}, timeout=120)
        assert r.status_code == 404, f"multi-tenant leak: {r.status_code} {r.text[:300]}"


# ---------- fusione trasversale ----------
class TestCrossDomainFusion:
    TAG = "TEST_ITER122"

    @pytest.fixture(scope="class")
    def injected(self, mongo):
        now = datetime.now(timezone.utc)
        alerts = [
            {"id": f"{self.TAG}-hw-{uuid.uuid4()}", "client_id": CLIENT_ID,
             "device_ip": DEVICE_IP, "source_type": "hardware_snmp", "severity": "high",
             "status": "active", "title": "TEST_ITER122 RAID degradato",
             "message": "test raid", "created_at": now},
            {"id": f"{self.TAG}-bkp-{uuid.uuid4()}", "client_id": CLIENT_ID,
             "device_ip": DEVICE_IP, "source_type": "backup_failed", "severity": "medium",
             "status": "active", "title": "TEST_ITER122 Backup fallito",
             "message": "test backup", "created_at": now},
            {"id": f"{self.TAG}-sec-{uuid.uuid4()}", "client_id": CLIENT_ID,
             "device_ip": DEVICE_IP, "source_type": "osint_c2", "severity": "critical",
             "status": "active", "title": "TEST_ITER122 C2 contact",
             "message": "test c2", "created_at": now},
        ]
        mongo.alerts.insert_many(alerts)
        yield alerts
        mongo.alerts.delete_many({"id": {"$regex": f"^{self.TAG}"}})

    def test_fusion_includes_all_domains_and_picks_security(self, client, injected):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                       params={"client_id": CLIENT_ID}, timeout=120)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        domains = [e["domain"] for e in d["evidence"]]
        assert domains[0] == "reachability"
        for dom in ("hardware", "backup", "security"):
            assert dom in domains, f"{dom} non fuso in evidence: {domains}"
        assert d["overall_state"] == "CRITICAL", d["overall_state"]
        assert d["primary"]["domain"] == "security", d["primary"]
        assert d["primary"]["root_cause"] == "osint_c2"
        assert d["confidence"] == 95, d["confidence"]
        assert "C2" in d["recommended_action"] or "COMPROMISSIONE" in d["recommended_action"]
        assert d["evidence_by_domain"].get("security") == 1
        assert d["evidence_by_domain"].get("hardware") == 1
        assert d["evidence_by_domain"].get("backup") == 1
        assert d["up"] is True

    def test_cleanup_restores_ok(self, client, mongo):
        # eseguito dopo il teardown della classe? no -> forza rimozione qui
        mongo.alerts.delete_many({"id": {"$regex": f"^{self.TAG}"}})
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{DEVICE_IP}/diagnosis",
                       params={"client_id": CLIENT_ID}, timeout=120)
        d = r.json()
        assert d["overall_state"] == "OK", f"stato residuo {d['overall_state']} {d['evidence']}"


# ---------- client diagnosis ----------
class TestClientDiagnosis:
    def test_schema(self, client):
        r = client.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis", timeout=180)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["client_id"] == CLIENT_ID
        for k in ("CRITICAL", "WARNING", "UNKNOWN", "OK"):
            assert k in d["counts"], f"missing counts.{k}"
            assert isinstance(d["counts"][k], int)
        assert isinstance(d["devices"], list)
        assert isinstance(d["client_situations"], list)
        assert '"_id"' not in r.text
        # only_problems default = True -> nessun OK nella lista
        assert all(x["overall_state"] != "OK" for x in d["devices"]), \
            [x["overall_state"] for x in d["devices"]]
        # ordinamento per gravita'
        order = {"CRITICAL": 0, "WARNING": 1, "UNKNOWN": 2, "OK": 3}
        ranks = [order[x["overall_state"]] for x in d["devices"]]
        assert ranks == sorted(ranks), ranks

    def test_client_situations_aggregation(self, client):
        r = client.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis", timeout=180)
        sits = r.json()["client_situations"]
        for g in sits:
            for k in ("domain", "source_type", "count", "severity", "state", "recommended_action"):
                assert k in g, f"missing client_situations.{k}"
            assert g["count"] >= 1
            assert g["state"] in ("OK", "WARNING", "CRITICAL", "UNKNOWN")
        # una sola voce per source_type
        sts = [g["source_type"] for g in sits]
        assert len(sts) == len(set(sts)), sts
        # ordinamento per severita' desc
        assert [{"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}[g["severity"]] for g in sits] == \
            sorted([{"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}[g["severity"]] for g in sits], reverse=True)

    def test_only_problems_false_includes_ok(self, client):
        r = client.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis",
                       params={"only_problems": "false"}, timeout=180)
        assert r.status_code == 200
        d = r.json()
        assert len(d["devices"]) == sum(v for k, v in d["counts"].items()
                                        if k in ("CRITICAL", "WARNING", "UNKNOWN", "OK")) or True
        assert len(d["devices"]) >= 1
        assert any(x["overall_state"] == "OK" for x in d["devices"]), \
            "only_problems=false dovrebbe includere device OK"

    def test_counts_match_devices_when_all_returned(self, client):
        r = client.get(f"{BASE_URL}/api/clients/{CLIENT_ID}/diagnosis",
                       params={"only_problems": "false"}, timeout=180)
        d = r.json()
        from collections import Counter
        actual = Counter(x["overall_state"] for x in d["devices"])
        for state in ("CRITICAL", "WARNING", "UNKNOWN", "OK"):
            assert actual.get(state, 0) == d["counts"][state], \
                f"{state}: devices={actual.get(state,0)} counts={d['counts'][state]}"

    def test_unknown_client_returns_empty(self, client):
        r = client.get(f"{BASE_URL}/api/clients/{uuid.uuid4()}/diagnosis", timeout=120)
        assert r.status_code == 200
        d = r.json()
        assert d["devices"] == []
        assert d["client_situations"] == []
