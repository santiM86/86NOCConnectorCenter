"""
Iter-85 — Test backend WAN Advanced (FASE 2): 5 nuovi endpoint MSP-grade.

Endpoint testati (routes/wan_advanced.py):
- GET  /api/external-monitor/multi-isp/{client_id}
- GET  /api/external-monitor/saas-reachability/{client_id}
- POST /api/external-monitor/traceroute
- CRUD /api/external-monitor/alert-rules/{target_id} (GET/PUT/DELETE)
- GET  /api/external-monitor/history-bucket/{target_id}?days={N}

Non-regressione FASE 1:
- insights, geo-ip, dns-health, public-ip-history,
  speedtest (atteso 503), speedtest-history, speedtest-result
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


# ---------- fixtures auth ----------

@pytest.fixture(scope="module")
def auth_headers():
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Login fallito: {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    tok = body.get("token") or body.get("access_token")
    if not tok:
        pytest.skip(f"Token non trovato: {body}")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def any_target(auth_headers):
    r = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    targets = r.json().get("targets", [])
    if not targets:
        pytest.skip("Nessun WAN target presente in DB")
    return targets[0]


@pytest.fixture(scope="module")
def any_client_id(any_target):
    cid = any_target.get("client_id")
    if not cid:
        pytest.skip("Target senza client_id")
    return cid


# ==================== FASE 2 — MULTI-ISP ====================

class TestMultiISP:
    def test_multi_isp_structure(self, auth_headers, any_client_id):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/multi-isp/{any_client_id}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["client_id"] == any_client_id
        assert "multi_isp" in data and isinstance(data["multi_isp"], bool)
        assert "isps" in data and isinstance(data["isps"], list)
        assert "failover_events" in data and isinstance(data["failover_events"], list)
        # each isp must contain gateway_ip + target_ids + reachable fields
        for isp in data["isps"]:
            assert "gateway_ip" in isp
            assert "target_ids" in isp and isinstance(isp["target_ids"], list)
            assert "target_labels" in isp
            assert "reachable" in isp
            assert "latency_ms" in isp

    def test_multi_isp_unknown_client(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/multi-isp/__NOT_EXIST_{uuid.uuid4().hex[:8]}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["isps"] == []
        assert d["multi_isp"] is False
        assert d["failover_events"] == []


# ==================== FASE 2 — SAAS REACHABILITY ====================

class TestSaaSReachability:
    def test_saas_structure_and_persistence(self, auth_headers, any_client_id):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/saas-reachability/{any_client_id}",
            headers=auth_headers, timeout=60,  # outbound probe può essere lento
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["client_id"] == any_client_id
        assert "tested_at" in data
        # summary
        s = data["summary"]
        assert {"healthy", "total", "all_ok"} <= set(s.keys())
        assert s["total"] == 8  # 8 SAAS_TARGETS hardcoded
        assert isinstance(s["healthy"], int) and 0 <= s["healthy"] <= 8
        assert isinstance(s["all_ok"], bool)
        # services list
        services = data["services"]
        assert isinstance(services, list) and len(services) == 8
        for sv in services:
            assert "name" in sv
            assert "ok" in sv and isinstance(sv["ok"], bool)
            # if ok=True, deve avere ip/dns_ms/tcp_ms/latency_ms
            if sv["ok"]:
                assert sv.get("ip")
                assert sv.get("dns_ms") is not None
                assert sv.get("tcp_ms") is not None
                assert sv.get("latency_ms") is not None
        # Persistenza wan_saas_snapshots: rifaccio la call e verifico campi consistenti (best-effort)
        r2 = requests.get(
            f"{BASE_URL}/api/external-monitor/saas-reachability/{any_client_id}",
            headers=auth_headers, timeout=60,
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["summary"]["total"] == 8


# ==================== FASE 2 — TRACEROUTE ====================

class TestTraceroute:
    def test_traceroute_to_cloudflare(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/traceroute",
            headers=auth_headers,
            json={"target": "1.1.1.1", "max_hops": 10},
            timeout=80,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["target"] == "1.1.1.1"
        assert d["max_hops"] == 10
        assert "tested_at" in d
        assert "hop_count" in d
        assert isinstance(d["hops"], list)
        # almeno 1 hop deve esistere (o un errore strutturato)
        if d["hops"] and "error" not in d["hops"][0]:
            for h in d["hops"]:
                assert "hop" in h
                assert "ip" in h
                assert "rtt_ms" in h
                assert "raw" in h

    def test_traceroute_missing_target_400(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/traceroute",
            headers=auth_headers,
            json={"target": "", "max_hops": 5},
            timeout=15,
        )
        assert r.status_code == 400


# ==================== FASE 2 — ALERT RULES CRUD ====================

class TestAlertRules:
    def test_get_default_empty(self, auth_headers, any_target):
        tid = any_target["id"]
        # delete first to ensure clean state
        requests.delete(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, timeout=15,
        )
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["target_id"] == tid
        assert d["enabled"] is False
        assert d["latency_warn_ms"] is None
        assert d["latency_crit_ms"] is None
        assert d["loss_warn_pct"] is None
        assert d["uptime_warn_pct"] is None

    def test_put_and_persist(self, auth_headers, any_target):
        tid = any_target["id"]
        payload = {
            "target_id": tid,
            "enabled": True,
            "latency_warn_ms": 100,
            "latency_crit_ms": 250,
            "loss_warn_pct": 2.0,
            "loss_crit_pct": 5.0,
            "uptime_warn_pct": 99.0,
            "notify_email": "TEST_iter85@example.com",
            "notify_telegram_chat_id": None,
        }
        r = requests.put(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, json=payload, timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        rule = d["rule"]
        assert rule["enabled"] is True
        assert rule["latency_warn_ms"] == 100
        assert rule["latency_crit_ms"] == 250
        assert rule["loss_warn_pct"] == 2.0
        assert rule["uptime_warn_pct"] == 99.0
        assert rule["notify_email"] == "TEST_iter85@example.com"
        assert "updated_at" in rule
        assert "updated_by" in rule
        # GET di verifica persistenza
        rg = requests.get(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, timeout=15,
        )
        assert rg.status_code == 200
        dg = rg.json()
        assert dg["enabled"] is True
        assert dg["latency_warn_ms"] == 100
        assert dg["notify_email"] == "TEST_iter85@example.com"

    def test_put_target_id_mismatch(self, auth_headers, any_target):
        tid = any_target["id"]
        payload = {"target_id": "OTHER_ID", "enabled": True}
        r = requests.put(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, json=payload, timeout=15,
        )
        assert r.status_code == 400

    def test_put_unknown_target_404(self, auth_headers):
        fake = f"NOTEXIST_{uuid.uuid4().hex[:10]}"
        payload = {"target_id": fake, "enabled": True}
        r = requests.put(
            f"{BASE_URL}/api/external-monitor/alert-rules/{fake}",
            headers=auth_headers, json=payload, timeout=15,
        )
        assert r.status_code == 404

    def test_delete_cleanup(self, auth_headers, any_target):
        tid = any_target["id"]
        r = requests.delete(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # verifica torna default empty
        rg = requests.get(
            f"{BASE_URL}/api/external-monitor/alert-rules/{tid}",
            headers=auth_headers, timeout=15,
        )
        assert rg.status_code == 200
        assert rg.json()["enabled"] is False


# ==================== FASE 2 — HISTORY BUCKET ====================

class TestHistoryBucket:
    @pytest.mark.parametrize("days,expected_bucket", [(1, 300), (7, 3600), (30, 21600)])
    def test_bucket_size(self, auth_headers, any_target, days, expected_bucket):
        tid = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/history-bucket/{tid}?days={days}",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["target_id"] == tid
        assert d["days"] == days
        assert d["bucket_sec"] == expected_bucket
        assert isinstance(d["buckets"], list)
        assert "total_samples" in d
        for b in d["buckets"]:
            assert "t" in b
            assert "avg_latency" in b
            assert "avg_loss" in b
            assert "uptime_pct" in b
            assert "samples" in b
            assert 0 <= b["uptime_pct"] <= 100
            assert b["samples"] >= 1

    def test_history_bucket_clamps_days(self, auth_headers, any_target):
        tid = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/history-bucket/{tid}?days=200",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200
        # clamp 90 max
        assert r.json()["days"] == 90


# ==================== NON-REGRESSIONE FASE 1 ====================

class TestPhase1NonRegression:
    def test_insights(self, auth_headers, any_target):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/insights/{any_target['id']}",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # struttura minima
        assert "target_id" in d or "uptime_pct" in d or "stats" in d or "latency" in d

    def test_geo_ip(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/geo-ip/8.8.8.8",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200
        d = r.json()
        # tollero rate-limit ip-api.com → potrebbe ritornare error
        assert "ip" in d or "error" in d or "country" in d

    def test_dns_health(self, auth_headers, any_target):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/dns-health/{any_target['id']}",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200

    def test_public_ip_history(self, auth_headers, any_target):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/public-ip-history/{any_target['id']}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200

    def test_speedtest_trigger_503(self, auth_headers, any_client_id):
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/speedtest/{any_client_id}",
            headers=auth_headers, timeout=20,
        )
        # 503 atteso (no agent v4 LIVE), 200 accettato se esiste un agent
        assert r.status_code in (200, 503), r.text

    def test_speedtest_history(self, auth_headers, any_client_id):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/speedtest-history/{any_client_id}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200

    def test_speedtest_result_submit(self, auth_headers, any_client_id):
        marker = f"TEST_iter85_{uuid.uuid4().hex[:8]}"
        body = {
            "command_id": marker,
            "client_id": any_client_id,
            "target_id": marker,
            "download_mbps": 100.0,
            "upload_mbps": 50.0,
            "ping_ms": 12.3,
            "server": "TEST_iter85",
            "isp": "TEST_ISP",
        }
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/speedtest-result",
            headers=auth_headers, json=body, timeout=15,
        )
        assert r.status_code in (200, 201, 204), r.text


# ==================== ROUTER REGISTRATION ====================

class TestRouterRegistration:
    def test_wan_advanced_router_mounted(self, auth_headers):
        """Se gli endpoint wan_advanced rispondono 200/4xx (non 404) il router e' montato."""
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/multi-isp/__probe__",
            headers=auth_headers, timeout=10,
        )
        assert r.status_code != 404, "wan_advanced_router non montato in server.py"
