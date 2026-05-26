"""Tests for the centralized liveness/status resolver."""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from liveness_resolver import effective_reachable, compute_status


def _iso_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ============ effective_reachable ============

def test_reachable_true_returns_online():
    assert effective_reachable({"reachable": True}) is True


def test_reachable_false_no_history_offline():
    assert effective_reachable({"reachable": False}) is False


def test_reachable_false_single_failure_still_online():
    pd = {
        "reachable": False,
        "consecutive_failures": 1,
        "last_reachable_at": _iso_ago(60),
    }
    # 1 fail solo → debounce non scattato → ancora online (transitorio)
    assert effective_reachable(pd) is True


def test_reachable_false_below_grace_seconds_still_online():
    pd = {
        "reachable": False,
        "consecutive_failures": 5,
        "last_reachable_at": _iso_ago(120),  # 2 min ago < 5 min grace
    }
    # 5 fail ma <5min dall'ultimo OK → ancora online
    assert effective_reachable(pd) is True


def test_reachable_false_full_debounce_offline():
    pd = {
        "reachable": False,
        "consecutive_failures": 5,
        "last_reachable_at": _iso_ago(600),  # 10 min ago
    }
    # 5 fail E >5min senza OK → offline
    assert effective_reachable(pd) is False


def test_empty_pd_is_offline():
    assert effective_reachable(None) is False
    assert effective_reachable({}) is False


# ============ compute_status ============

def test_evidence_overrides_offline_poll():
    pd = {"reachable": False, "consecutive_failures": 10, "last_reachable_at": _iso_ago(3600)}
    md = {"ip": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:ff"}
    ip_ev = {"10.0.0.5": "mac_table_switch"}
    status, label = compute_status(pd, md, ip_ev, {})
    assert status == "online"
    assert label == "mac_table_switch"


def test_mac_evidence_overrides_when_ip_not_pinged():
    md = {"ip": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:ff"}
    mac_ev = {"aa:bb:cc:dd:ee:ff": "agent_v4_arp"}
    status, label = compute_status(None, md, {}, mac_ev)
    assert status == "online"
    assert label == "agent_v4_arp"


def test_poll_reachable_no_evidence_online():
    pd = {"reachable": True, "method": "tcp:443"}
    md = {"ip": "10.0.0.5"}
    status, label = compute_status(pd, md, {}, {})
    assert status == "online"
    assert label == "tcp:443"


def test_poll_offline_no_evidence_is_offline():
    pd = {"reachable": False, "consecutive_failures": 10, "last_reachable_at": _iso_ago(3600)}
    md = {"ip": "10.0.0.5"}
    status, _ = compute_status(pd, md, {}, {})
    assert status == "offline"


def test_scanner_source_recent_online():
    md = {
        "ip": "10.0.0.5",
        "source": "connector-scanner",
        "last_seen_at": _iso_ago(120),
    }
    status, label = compute_status(None, md, {}, {})
    assert status == "online"
    assert label == "scanner_lan"


def test_scanner_source_old_offline():
    md = {
        "ip": "10.0.0.5",
        "source": "connector-scanner",
        "last_seen_at": _iso_ago(7200),  # 2h ago > 30 min
    }
    status, _ = compute_status(None, md, {}, {})
    assert status == "offline"


def test_no_poll_no_evidence_no_scanner_pending():
    md = {"ip": "10.0.0.5", "source": "manual"}
    status, _ = compute_status(None, md, {}, {})
    assert status == "pending"


def test_mac_normalization():
    md = {"ip": "10.0.0.5", "mac": "AA-BB-CC-DD-EE-FF"}
    mac_ev = {"aa:bb:cc:dd:ee:ff": "scanner_lan"}
    status, _ = compute_status(None, md, {}, mac_ev)
    assert status == "online"


# ============ Cascata connector offline → stale ============

def test_cascade_connector_offline_demotes_offline_to_stale():
    """Galvan caso reale: ZITACSRV offline → device "offline" → STALE."""
    pd = {
        "reachable": False,
        "consecutive_failures": 10,
        "last_reachable_at": _iso_ago(3600),
        "client_id": "galvan-uuid",
    }
    md = {"ip": "10.10.5.5", "client_id": "galvan-uuid"}
    offline_clients = {"galvan-uuid"}
    status, label = compute_status(pd, md, {}, {}, offline_clients)
    assert status == "stale"
    assert label == "agent_offline"


def test_cascade_evidence_overrides_cascade_stale():
    """Stessa cascata MA evidence FDB switch → ONLINE (override)."""
    pd = {
        "reachable": False,
        "consecutive_failures": 10,
        "last_reachable_at": _iso_ago(3600),
        "client_id": "galvan-uuid",
    }
    md = {"ip": "10.10.5.5", "mac": "aa:bb:cc:dd:ee:ff", "client_id": "galvan-uuid"}
    ip_ev = {"10.10.5.5": "mac_table_switch"}
    offline_clients = {"galvan-uuid"}
    status, _ = compute_status(pd, md, ip_ev, {}, offline_clients)
    assert status == "online"


def test_cascade_other_client_unaffected():
    """Solo i device del cliente con connector offline sono "stale".
    Altri clienti restano "offline" reali."""
    pd = {
        "reachable": False,
        "consecutive_failures": 10,
        "last_reachable_at": _iso_ago(3600),
        "client_id": "altro-cliente",
    }
    md = {"ip": "10.10.5.5", "client_id": "altro-cliente"}
    offline_clients = {"galvan-uuid"}
    status, _ = compute_status(pd, md, {}, {}, offline_clients)
    assert status == "offline"


def test_cascade_reachable_true_with_offline_clients_still_online():
    """Se il device E' reachable (qualche connector funziona), niente stale."""
    pd = {"reachable": True, "client_id": "galvan-uuid"}
    md = {"ip": "10.10.5.5", "client_id": "galvan-uuid"}
    offline_clients = {"galvan-uuid"}
    status, _ = compute_status(pd, md, {}, {}, offline_clients)
    assert status == "online"


def test_cascade_no_offline_clients_set_works_normally():
    """Senza il parametro offline_clients tutto funziona come prima."""
    pd = {
        "reachable": False,
        "consecutive_failures": 10,
        "last_reachable_at": _iso_ago(3600),
        "client_id": "galvan-uuid",
    }
    md = {"ip": "10.10.5.5", "client_id": "galvan-uuid"}
    status, _ = compute_status(pd, md, {}, {})
    assert status == "offline"



def test_debounce_grace_combined_anti_flap():
    # 2 fail, 10 min senza OK → fail count <3 → online (anti-flap dominante)
    pd = {
        "reachable": False,
        "consecutive_failures": 2,
        "last_reachable_at": _iso_ago(600),
    }
    md = {"ip": "10.0.0.5"}
    status, _ = compute_status(pd, md, {}, {})
    assert status == "online"
