"""Regression: multi-homed agent target dispatch.

Bug (2026-06): _build_poller_config computed a SINGLE /24 from the agent's
"primary" IP. A multi-homed agent (e.g. VPN 10.211.x listed before LAN
10.10.10.x) got the wrong subnet, so switches on the LAN subnet were never
assigned to it -> ifTable/ports never collected, even though the agent could
reach the switch. Fix: consider ALL of the agent's interface subnets.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from routes.agent_ws import (  # noqa: E402
    _subnets_from_ips,
    _ip_in_subnet,
    _agent_subnet_from_ip,
    _primary_ip_from_hello,
)


def test_multihomed_agent_covers_lan_switch():
    ips = ["10.211.55.4", "10.10.10.102", "169.254.13.1"]
    switch_ip = "10.10.10.105"

    # Old single-subnet logic would pick the VPN IP and miss the switch.
    primary = _primary_ip_from_hello({"ips": ips})
    old_match = _ip_in_subnet(switch_ip, _agent_subnet_from_ip(primary))
    assert old_match is False  # documents the original bug

    # New logic: all interface subnets are considered.
    subnets = _subnets_from_ips(ips)
    assert "10.10.10.0/24" in subnets
    assert "10.211.55.0/24" in subnets
    assert any(_ip_in_subnet(switch_ip, s) for s in subnets) is True


def test_subnets_from_ips_skips_apipa_and_dedups():
    subnets = _subnets_from_ips(
        ["169.254.1.1", "192.168.1.10", "192.168.1.20", None, ""]
    )
    assert subnets == ["192.168.1.0/24"]


def test_single_homed_agent_unaffected():
    subnets = _subnets_from_ips(["192.168.16.21"])
    assert subnets == ["192.168.16.0/24"]
    assert any(_ip_in_subnet("192.168.16.50", s) for s in subnets) is True
    assert any(_ip_in_subnet("10.0.0.5", s) for s in subnets) is False
