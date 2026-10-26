"""
Iter 87 — Unificazione liveness (ICMP vs SNMP) per la Scheda Dispositivo.

Verifica:
1) GET /api/devices?client_id=... e GET /api/devices/by-ip/{ip}/info-card
   CONCORDANO sullo status del device seedato 10.99.99.222 (SNMP-only HP).
2) Campi nuovi nella info-card per device SNMP-only.
3) Device "normale" (ICMP ok) -> live_reason='ping'.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SNMP_ONLY_IP = "10.99.99.222"
NORMAL_IP = "192.168.1.3"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no access_token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestLivenessUnification:
    def test_devices_list_has_snmp_only_device(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/devices",
            params={"client_id": CLIENT_ID},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        match = [
            d for d in items
            if d.get("ip_address") == SNMP_ONLY_IP
            or d.get("ip") == SNMP_ONLY_IP
        ]
        assert match, (
            f"Device {SNMP_ONLY_IP} non trovato nella lista del client "
            f"{CLIENT_ID}. Potrebbe non essere seedato."
        )
        # MUST be online
        status = (match[0].get("status") or "").lower()
        assert status == "online", (
            f"Atteso ONLINE per device SNMP-only {SNMP_ONLY_IP}, "
            f"ottenuto: {status}. Dev row: {match[0]}"
        )

    def test_info_card_snmp_only_device(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{SNMP_ONLY_IP}/info-card",
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        card = r.json()
        st = card.get("status") or {}

        assert st.get("effective_status") == "online", (
            f"effective_status != online: {st}"
        )
        # ICMP false, SNMP true/fresh
        assert st.get("icmp_reachable") is False, (
            f"icmp_reachable atteso False, got {st.get('icmp_reachable')}"
        )
        assert st.get("snmp_reachable") is True, (
            f"snmp_reachable atteso True, got {st.get('snmp_reachable')}"
        )
        assert st.get("snmp_fresh") is True, (
            f"snmp_fresh atteso True, got {st.get('snmp_fresh')}"
        )
        assert st.get("live_reason") == "snmp", (
            f"live_reason atteso 'snmp', got {st.get('live_reason')}"
        )
        label = (st.get("live_reason_label") or "")
        assert "SNMP" in label and "ICMP" in label, (
            f"live_reason_label deve citare SNMP e ICMP bloccato: '{label}'"
        )
        # Backward-compat: status.reachable mappato a True (online)
        assert st.get("reachable") is True, (
            f"status.reachable backward-compat atteso True, got "
            f"{st.get('reachable')}"
        )

    def test_consistency_list_vs_info_card_snmp_only(self, headers):
        r1 = requests.get(
            f"{BASE_URL}/api/devices",
            params={"client_id": CLIENT_ID},
            headers=headers,
            timeout=30,
        )
        r2 = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{SNMP_ONLY_IP}/info-card",
            headers=headers,
            timeout=30,
        )
        assert r1.status_code == 200 and r2.status_code == 200
        m = [
            d for d in r1.json()
            if d.get("ip_address") == SNMP_ONLY_IP
            or d.get("ip") == SNMP_ONLY_IP
        ]
        assert m, "device non in lista"
        list_status = (m[0].get("status") or "").lower()
        card_status = (
            (r2.json().get("status") or {}).get("effective_status") or ""
        ).lower()
        assert list_status == card_status == "online", (
            f"Inconsistenza: list={list_status} card={card_status}"
        )

    def test_info_card_normal_device(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{NORMAL_IP}/info-card",
            headers=headers,
            timeout=30,
        )
        # Accept 404 only if the seed isn't present, but the request shouldn't
        # crash with 500
        assert r.status_code in (200, 404), r.text
        if r.status_code == 404:
            pytest.skip(f"device {NORMAL_IP} non presente nel DB")
        card = r.json()
        st = card.get("status") or {}
        assert st.get("effective_status") == "online", (
            f"effective_status atteso 'online' per device ICMP-ok, got {st}"
        )
        assert st.get("icmp_reachable") is True, (
            f"icmp_reachable atteso True per device ICMP-ok, got "
            f"{st.get('icmp_reachable')}"
        )
        assert st.get("live_reason") in ("ping", "icmp_native"), (
            f"live_reason atteso 'ping'/'icmp_native', got "
            f"{st.get('live_reason')}"
        )
