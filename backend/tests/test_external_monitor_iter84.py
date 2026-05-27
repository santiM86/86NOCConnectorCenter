"""
Iter-84 — Test backend per nuovi endpoint WAN Client Tab.

Endpoint testati (v2026-03-01):
- GET  /api/external-monitor/insights/{target_id}    — fix history flat
- GET  /api/external-monitor/geo-ip/{ip}             — lookup ip-api.com
- GET  /api/external-monitor/dns-health/{target_id}  — DNS UDP probe
- GET  /api/external-monitor/public-ip-history/{target_id}
- POST /api/external-monitor/speedtest/{client_id}   — atteso 503 (no agent)
- GET  /api/external-monitor/speedtest-history/{client_id}
- POST /api/external-monitor/speedtest-result        — submit manuale

Non-regressione:
- GET  /api/external-monitor/targets
- GET  /api/external-monitor/status
- POST /api/external-monitor/test-connection
"""
import os
import time
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
    tok = resp.json().get("token") or resp.json().get("access_token")
    if not tok:
        pytest.skip(f"Token non trovato in risposta login: {resp.json()}")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def any_target(auth_headers):
    """Recupera il primo target WAN esistente per i test downstream."""
    r = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    targets = r.json().get("targets", [])
    if not targets:
        pytest.skip("Nessun WAN target presente in DB — impossibile testare gli endpoint per-target")
    return targets[0]


# ==================== NON-REGRESSIONE ====================

class TestNonRegression:
    """Verifica che gli endpoint preesistenti continuino a funzionare."""

    def test_targets_list(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "targets" in data and isinstance(data["targets"], list)

    def test_status_all(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/external-monitor/status", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # v2026-02-14: la risposta deve contenere targets/results/diagnoses
        for k in ("targets", "results", "diagnoses"):
            assert k in data, f"Manca chiave '{k}' nella risposta /status"
        assert isinstance(data["targets"], list)
        assert isinstance(data["results"], list)

    def test_test_connection_minimal(self, auth_headers):
        # ping verso 8.8.8.8, senza porte e senza gateway (test rapido)
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/test-connection",
            headers=auth_headers,
            json={"public_ip": "8.8.8.8", "check_ping": True, "check_ports": []},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ip"] == "8.8.8.8"
        assert "reachable" in data and isinstance(data["reachable"], bool)
        assert "summary" in data and isinstance(data["summary"], str)


# ==================== INSIGHTS ====================

class TestInsights:
    """GET /insights/{target_id} — uptime today/7d/30d, sparkline_24h, latency stats, MTTR."""

    def test_insights_structure(self, auth_headers, any_target):
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/insights/{target_id}?days=30",
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()

        # Chiavi top-level obbligatorie
        for k in (
            "target_id", "days", "samples",
            "uptime_pct", "uptime_today", "uptime_7d", "uptime_30d",
            "sla_target", "latency", "loss_pct_avg",
            "sparkline_24h", "down_periods",
            "down_count", "total_down_minutes", "mttr_min",
        ):
            assert k in data, f"insights missing key '{k}'"

        assert data["target_id"] == target_id
        assert data["days"] == 30
        assert data["sla_target"] == 99.9
        assert isinstance(data["sparkline_24h"], list)
        assert isinstance(data["down_periods"], list)
        assert isinstance(data["latency"], dict)
        for lk in ("avg", "min", "max", "p95", "jitter"):
            assert lk in data["latency"], f"latency missing '{lk}'"

    def test_insights_uptime_bounds(self, auth_headers, any_target):
        """Se ci sono samples, uptime% deve essere 0-100."""
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/insights/{target_id}",
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        if data["samples"] > 0:
            assert 0 <= data["uptime_pct"] <= 100
            for k in ("uptime_today", "uptime_7d", "uptime_30d"):
                v = data[k]
                if v is not None:
                    assert 0 <= v <= 100, f"{k} fuori range: {v}"

    def test_insights_flat_history_bug_fix(self, auth_headers, any_target):
        """Bug fix v2026-03-01: history e' FLAT (reachable/latency_ms al top-level).
        Se ci sono samples online, latency.avg deve essere popolato (non None),
        confermando che _is_online + _lat leggono correttamente lo schema flat.
        """
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/insights/{target_id}",
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        if data["samples"] > 0 and data.get("uptime_pct", 0) > 0:
            # almeno una metrica latency deve essere popolata
            lat = data["latency"]
            has_some = any(lat.get(k) is not None for k in ("avg", "min", "max", "p95"))
            assert has_some, (
                f"Bug: history flat ma latency tutto None. "
                f"samples={data['samples']} uptime={data['uptime_pct']} latency={lat}"
            )


# ==================== GEO-IP ====================

class TestGeoIP:
    """GET /geo-ip/{ip} — lookup ip-api.com con cache."""

    def test_geoip_google_dns(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/geo-ip/8.8.8.8",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ip") == "8.8.8.8"
        assert "cached" in data
        # Atteso: Google LLC / AS15169
        # se ip-api e' raggiungibile dovremmo avere isp/asn
        if "error" not in data:
            assert data.get("country_code") == "US", f"country_code={data.get('country_code')}"
            asn = (data.get("asn") or "")
            isp = (data.get("isp") or "")
            org = (data.get("org") or "")
            combined = f"{asn} {isp} {org}".lower()
            assert "google" in combined or "15169" in combined, (
                f"Atteso Google/AS15169, ricevuto asn={asn} isp={isp} org={org}"
            )

    def test_geoip_cache_second_call(self, auth_headers):
        # primo (potrebbe gia' essere cache da test precedente)
        requests.get(
            f"{BASE_URL}/api/external-monitor/geo-ip/1.1.1.1",
            headers=auth_headers, timeout=15,
        )
        # secondo: cached=True
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/geo-ip/1.1.1.1",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("cached") is True, f"Atteso cached=True al secondo lookup, ricevuto {data}"


# ==================== DNS HEALTH ====================

class TestDnsHealth:
    """GET /dns-health/{target_id} — test risoluzione DNS multi-resolver."""

    def test_dns_health_structure(self, auth_headers, any_target):
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/dns-health/{target_id}",
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["target_id"] == target_id
        assert "tested_at" in data
        # summary
        assert "summary" in data
        s = data["summary"]
        for k in ("healthy_resolvers", "total_resolvers", "all_ok"):
            assert k in s, f"summary missing '{k}'"
        assert isinstance(s["healthy_resolvers"], int)
        assert isinstance(s["total_resolvers"], int)
        # resolvers
        assert "resolvers" in data and isinstance(data["resolvers"], list)
        assert s["total_resolvers"] == len(data["resolvers"])
        # 3 base (Google/Cloudflare/Quad9) + eventuale gateway
        assert s["total_resolvers"] >= 3, f"Atteso >=3 resolver, ricevuto {s['total_resolvers']}"
        # ogni resolver ha campi attesi
        for r_ in data["resolvers"]:
            for k in ("name", "ip", "ok", "latency_ms", "queries"):
                assert k in r_, f"resolver missing '{k}'"
            assert isinstance(r_["queries"], list)

    def test_dns_health_public_resolvers_healthy(self, auth_headers, any_target):
        """Almeno 1 dei resolver pubblici (8.8.8.8, 1.1.1.1, 9.9.9.9) deve rispondere."""
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/dns-health/{target_id}",
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        public_ips = {"8.8.8.8", "1.1.1.1", "9.9.9.9"}
        healthy_public = [
            r_ for r_ in data["resolvers"]
            if r_["ip"] in public_ips and r_["ok"]
        ]
        assert len(healthy_public) >= 1, (
            f"Nessun resolver pubblico healthy: {[(r['ip'], r['ok']) for r in data['resolvers']]}"
        )

    def test_dns_health_404_unknown_target(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/dns-health/bogus-target-id-xyz",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 404


# ==================== PUBLIC IP HISTORY ====================

class TestPublicIPHistory:
    def test_public_ip_history_structure(self, auth_headers, any_target):
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/public-ip-history/{target_id}",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["target_id"] == target_id
        assert "changes" in data and isinstance(data["changes"], list)
        assert "count" in data and isinstance(data["count"], int)
        assert data["count"] == len(data["changes"])

    def test_public_ip_history_limit(self, auth_headers, any_target):
        target_id = any_target["id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/public-ip-history/{target_id}?limit=5",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["changes"]) <= 5


# ==================== SPEEDTEST ====================

class TestSpeedtest:
    """Speedtest endpoints — in test env nessun agent v4 LIVE -> 503 atteso."""

    def test_speedtest_trigger_503_no_agent(self, auth_headers, any_target):
        """POST /speedtest/{client_id} deve ritornare 503 se non c'e' agent v4 LIVE."""
        client_id = any_target["client_id"]
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/speedtest/{client_id}",
            headers=auth_headers,
            timeout=15,
        )
        # 503 atteso (nessun agent v4 LIVE in test env)
        # Se per caso c'e' un agent live, 200 e' accettabile
        assert r.status_code in (503, 200), f"status inatteso: {r.status_code} {r.text[:200]}"
        if r.status_code == 503:
            detail = r.json().get("detail", "")
            assert "agent" in detail.lower(), f"detail 503 inatteso: {detail}"

    def test_speedtest_history_structure(self, auth_headers, any_target):
        client_id = any_target["client_id"]
        r = requests.get(
            f"{BASE_URL}/api/external-monitor/speedtest-history/{client_id}",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["client_id"] == client_id
        assert "history" in data and isinstance(data["history"], list)
        assert "count" in data
        assert data["count"] == len(data["history"])

    def test_speedtest_result_manual_submit(self, auth_headers, any_target):
        """POST /speedtest-result — submit manuale crea record nuovo se cmd_id non esiste."""
        client_id = any_target["client_id"]
        cmd_id = f"TEST_iter84_{uuid.uuid4()}"
        payload = {
            "command_id": cmd_id,
            "client_id": client_id,
            "agent_id": "TEST_iter84_agent",
            "download_mbps": 123.45,
            "upload_mbps": 67.89,
            "ping_ms": 12.3,
            "jitter_ms": 1.2,
            "server": "TEST_server_milano",
            "isp": "TEST_ISP",
        }
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/speedtest-result",
            headers=auth_headers, json=payload, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ok"
        assert data["command_id"] == cmd_id

        # Verifica persistenza via history
        time.sleep(0.5)
        r2 = requests.get(
            f"{BASE_URL}/api/external-monitor/speedtest-history/{client_id}?limit=50",
            headers=auth_headers, timeout=15,
        )
        assert r2.status_code == 200
        hist = r2.json().get("history", [])
        matching = [h for h in hist if h.get("id") == cmd_id]
        assert len(matching) == 1, f"Record TEST_iter84 non trovato in history (n={len(hist)})"
        rec = matching[0]
        assert rec["status"] == "completed"
        assert rec["download_mbps"] == 123.45
        assert rec["upload_mbps"] == 67.89
        assert rec["server"] == "TEST_server_milano"

    def test_speedtest_result_missing_cmd_id(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/external-monitor/speedtest-result",
            headers=auth_headers,
            json={"client_id": "x"},
            timeout=10,
        )
        assert r.status_code == 400


# ==================== AUTH GUARD ====================

class TestAuthGuard:
    def test_insights_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/external-monitor/insights/whatever", timeout=10)
        assert r.status_code in (401, 403)

    def test_geoip_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/external-monitor/geo-ip/8.8.8.8", timeout=10)
        assert r.status_code in (401, 403)
