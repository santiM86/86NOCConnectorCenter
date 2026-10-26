"""Regression test v3.8.35 — Classificazione ruolo porta firewall/router.

Testa l'algoritmo che assegna role=wan|lan|dmz|mgmt|other a una porta basandosi
su name + alias (descrizione SNMP), per la sezione "Interfacce per ruolo" della UI.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _classify(name: str, alias: str) -> str:
    """Replica della logica in topology.get_switch_ports per testarla isolata."""
    label_src = f"{(alias or '')} {(name or '')}".lower()
    if any(k in label_src for k in ("wan", "internet", "isp", "external", "uplink", "fiber", "fttc", "ftth")):
        return "wan"
    if any(k in label_src for k in ("dmz", "opt", "untrust")):
        return "dmz"
    if any(k in label_src for k in ("mgmt", "mgt", "managem", "admin", "console", "oob")):
        return "mgmt"
    if any(k in label_src for k in ("lan", "internal", "trust", "user", "client", "office")):
        return "lan"
    return "other"


def test_classify_wan():
    # Zyxel USG: alias custom "WAN1"
    assert _classify("ge1", "WAN1") == "wan"
    # FortiGate: nome wan1
    assert _classify("wan1", "") == "wan"
    # pfSense: alias "WAN" generico
    assert _classify("igb0", "WAN") == "wan"
    # Cisco: description "Internet ISP TIM"
    assert _classify("GigabitEthernet0/0", "Internet ISP TIM") == "wan"
    # Italian ISP keywords
    assert _classify("ge2", "Fibra FTTH 1Gbps") == "wan"


def test_classify_lan():
    assert _classify("ge3", "LAN_USERS") == "lan"
    assert _classify("port5", "Internal") == "lan"
    assert _classify("eth1", "Trust Zone") == "lan"
    assert _classify("vlan10", "OFFICE_VLAN") == "lan"


def test_classify_dmz():
    assert _classify("ge6", "DMZ_SERVERS") == "dmz"
    assert _classify("opt1", "Untrust") == "dmz"


def test_classify_mgmt():
    assert _classify("mgmt0", "") == "mgmt"
    assert _classify("port16", "Management") == "mgmt"
    assert _classify("ge0", "OOB Console") == "mgmt"


def test_classify_other():
    # Nome neutro senza hint
    assert _classify("ge5", "") == "other"
    assert _classify("port7", "Unused") == "other"


def test_priority_wan_over_lan():
    """Se l'alias contiene sia 'WAN' che 'LAN' (caso ibrido), WAN ha priorita'."""
    assert _classify("port1", "WAN_TO_LAN_BRIDGE") == "wan"


def test_topology_route_returns_role_field():
    """Smoke: il file topology.py deve esporre il campo role e by_role."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "routes", "topology.py")).read()
    assert '"role": port_role' in src
    assert "by_role" in src
    assert "v3.8.35" in src
