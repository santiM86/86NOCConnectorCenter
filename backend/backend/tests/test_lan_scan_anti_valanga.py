"""Test fix anti-valanga Scanner v3.8.21.

Verifica le 3 protezioni dell'endpoint POST /api/connector/lan-scan:
1. Skip MAC LAA (Locally Administered Address) senza hostname
2. Cap massimo per /lan-scan call (LAN_SCAN_MAX_AUTO_ADD_PER_CALL)
3. Throttle per cliente in 24h (LAN_SCAN_MAX_AUTO_ADD_PER_DAY)

Test isolato: simula la logica dei 3 check senza HTTP.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _is_laa_mac(mac_normalized: str) -> bool:
    """Replica della funzione interna lan-scan."""
    try:
        first_byte = int(mac_normalized.split(":")[0], 16)
        return bool(first_byte & 0x02)
    except Exception:
        return False


# ============================================================================
# Test 1: detection MAC LAA
# ============================================================================
def test_is_laa_mac_globally_unique_mac():
    """OUI registrati IEEE: bit 0x02 NON settato sul primo byte."""
    # Apple, Cisco, Microsoft, Dell, HPE etc.
    assert _is_laa_mac("00:1b:21:aa:bb:cc") is False  # Intel
    assert _is_laa_mac("3c:5a:b4:11:22:33") is False  # Google
    assert _is_laa_mac("a4:83:e7:de:ad:be") is False  # Apple


def test_is_laa_mac_locally_administered():
    """MAC privacy randomization (iOS/Android): bit 0x02 settato."""
    assert _is_laa_mac("02:00:00:00:00:01") is True
    assert _is_laa_mac("06:11:22:33:44:55") is True
    assert _is_laa_mac("0a:bc:de:f0:12:34") is True
    assert _is_laa_mac("1a:13:5a:13:c6:f6") is True  # esempio reale dal log incidente


def test_is_laa_mac_invalid():
    assert _is_laa_mac("") is False
    assert _is_laa_mac("invalid") is False


# ============================================================================
# Test 2: simulazione del loop anti-valanga
# ============================================================================
class FakeEndpoint:
    def __init__(self, mac, ip, hostname=""):
        self.mac = mac
        self.ip = ip
        self.hostname = hostname


def _simulate_loop(endpoints, max_per_call=10, max_per_day=50, already_24h=0):
    """Replica la logica anti-valanga di /api/connector/lan-scan."""
    auto_added = 0
    auto_skipped_laa = 0
    auto_skipped_cap = 0
    auto_skipped_throttle = 0

    for ep in endpoints:
        mac_norm = (ep.mac or "").lower().replace("-", ":").strip()
        if not mac_norm or len(mac_norm.replace(":", "")) != 12:
            continue
        if not ep.ip:
            continue
        mac_is_laa_check = _is_laa_mac(mac_norm)
        ep_hostname_clean = (ep.hostname or "").strip()
        # 1. Skip MAC LAA senza hostname
        if mac_is_laa_check and not ep_hostname_clean:
            auto_skipped_laa += 1
            continue
        # 2. Cap per call
        if auto_added >= max_per_call:
            auto_skipped_cap += 1
            continue
        # 3. Throttle per giorno
        if (already_24h + auto_added) >= max_per_day:
            auto_skipped_throttle += 1
            continue
        auto_added += 1

    return {
        "auto_added": auto_added,
        "skipped_laa": auto_skipped_laa,
        "skipped_cap": auto_skipped_cap,
        "skipped_throttle": auto_skipped_throttle,
    }


def test_skip_laa_anonymous_iphone_android():
    """30 device LAA senza hostname (privacy mode) => 0 aggiunti, 30 skip."""
    endpoints = [FakeEndpoint(f"02:00:00:00:00:{i:02x}", f"192.168.1.{i}") for i in range(1, 31)]
    res = _simulate_loop(endpoints)
    assert res["auto_added"] == 0
    assert res["skipped_laa"] == 30


def test_keep_laa_with_hostname():
    """LAA ma con hostname valido (es. 'iPhone-Mario') => aggiunti."""
    endpoints = [
        FakeEndpoint("02:00:00:00:00:01", "192.168.1.1", hostname="iPhone-Mario"),
        FakeEndpoint("02:00:00:00:00:02", "192.168.1.2", hostname="Galaxy-Anna"),
    ]
    res = _simulate_loop(endpoints)
    assert res["auto_added"] == 2
    assert res["skipped_laa"] == 0


def test_cap_per_call():
    """100 device IEEE OUI buoni => solo 10 aggiunti (cap), 90 skip cap."""
    endpoints = [FakeEndpoint(f"00:1b:21:00:00:{i:02x}", f"10.0.0.{i}") for i in range(1, 101)]
    res = _simulate_loop(endpoints, max_per_call=10, max_per_day=50)
    assert res["auto_added"] == 10
    assert res["skipped_cap"] == 90


def test_throttle_per_day():
    """Se gia' aggiunti 48 in 24h e arriva /lan-scan con 10 nuovi => max 2 aggiunti."""
    endpoints = [FakeEndpoint(f"00:1b:21:00:00:{i:02x}", f"10.0.0.{i}") for i in range(1, 11)]
    res = _simulate_loop(endpoints, max_per_call=10, max_per_day=50, already_24h=48)
    assert res["auto_added"] == 2
    assert res["skipped_throttle"] == 8


def test_combined_realistic_scenario_galvani():
    """Scenario reale del 06/05/2026: 80 endpoint scoperti, mix di:
    - 60 LAA senza hostname (smartphone privati clienti) => skip
    - 20 IEEE OUI buoni (server, switch, stampanti) => primi 10 aggiunti, 10 skip cap
    """
    endpoints = []
    # 60 LAA anonimi
    for i in range(60):
        endpoints.append(FakeEndpoint(f"0a:00:00:00:00:{i:02x}", f"192.168.16.{i+10}"))
    # 20 IEEE OUI buoni
    for i in range(20):
        endpoints.append(FakeEndpoint(f"00:1b:21:00:00:{i:02x}", f"10.100.61.{i+100}"))

    res = _simulate_loop(endpoints, max_per_call=10, max_per_day=50)
    assert res["auto_added"] == 10  # CAP rispettato
    assert res["skipped_laa"] == 60  # tutti gli smartphone privati skippati
    assert res["skipped_cap"] == 10  # i 10 IEEE rimanenti oltre il cap
    # In totale: 10 added + 60 LAA + 10 cap = 80 (no perdite)
    assert res["auto_added"] + res["skipped_laa"] + res["skipped_cap"] == 80
