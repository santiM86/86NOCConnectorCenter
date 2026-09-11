"""Iter152 — VM sotto host in topology map + Evidence Fusion v2 auto-promotion status."""
import os
import sys
import pyotp
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SW = "10.10.41.220"
HOST_IP = "10.10.41.10"
SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
VM_MACS = ["mac-00155D017004", "mac-00155D017005", "mac-00155D017006"]


@pytest.fixture(scope="module")
def H():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()},
                headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 200, r2.text
    return {"Authorization": f"Bearer {r2.json()['token']}"}


# ---------------- VM sotto host in topology ----------------
def test_topology_vm_parents(H):
    r = requests.get(f"{BASE}/api/network/topology/{CID}", headers=H, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    print("vm_links:", j.get("vm_links"))
    assert j.get("vm_links") == 3, f"expected 3 vm_links, got {j.get('vm_links')}"

    edges = j.get("edges") or []
    vm_edges = [e for e in edges if e.get("type") == "vm" and e.get("source") == "vm_parent"]
    print("vm edges:", vm_edges)
    assert len(vm_edges) >= 3
    for mac_node in VM_MACS:
        matches = [e for e in vm_edges if e.get("from") == HOST_IP and e.get("to") == mac_node]
        assert matches, f"no vm edge from {HOST_IP} to {mac_node}"
        assert matches[0].get("label") == "VM Hyper-V"

    # NO edge from switch to those mac nodes
    stale = [e for e in edges if e.get("from") == SW and e.get("to") in VM_MACS]
    assert not stale, f"stale switch->vm edges: {stale}"

    node_by_id = {n.get("id"): n for n in j.get("nodes") or []}
    for mac_node in VM_MACS:
        n = node_by_id.get(mac_node)
        assert n is not None, f"missing node {mac_node}"
        assert n.get("is_vm") is True
        assert n.get("vm_host_ip") == HOST_IP
        assert n.get("virtualization") == "Hyper-V"


# ---------------- Switch port attached[] ----------------
def test_switch_port_attached(H):
    r = requests.get(f"{BASE}/api/devices/{SW}/switch-ports", params={"client_id": CID}, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    ports = j.get("ports") if isinstance(j, dict) else j
    port1 = next((p for p in ports if p.get("idx") == 1), None)
    assert port1 is not None, "port idx 1 missing"
    print("port1 attached_count:", port1.get("attached_count"))
    assert port1.get("attached_count") == 4, port1
    names = [a.get("name") for a in port1.get("attached") or []]
    print("attached names:", names)
    assert "SRV-DC01" in names
    assert "VM-DC" in names
    assert "VM-SQL" in names
    # Microsoft Hyper-V device from mac_oui source
    hv = next((a for a in port1["attached"] if a.get("source") == "mac_oui" and "Hyper-V" in (a.get("name") or a.get("vendor") or "")), None)
    assert hv is not None, f"no mac_oui Hyper-V device in {port1['attached']}"
    # sources
    src_by_name = {a["name"]: a.get("source") for a in port1["attached"]}
    print("src_by_name:", src_by_name)
    assert src_by_name.get("SRV-DC01") in ("mac_managed", "managed", "datto_rmm", "mac_manual")
    assert src_by_name.get("VM-DC") == "hostname" or src_by_name.get("VM-DC") == "hostname_dhcp"
    assert src_by_name.get("VM-SQL") in ("hostname", "hostname_dhcp")


# ---------------- Fusion shadow + promotion ----------------
def test_fusion_shadow_promotion(H):
    r = requests.get(f"{BASE}/api/fusion/shadow", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    promo = j.get("promotion")
    assert promo is not None, "missing 'promotion' in /api/fusion/shadow"
    print("promotion:", promo)
    for k in ["cases", "agree", "agree_pct", "days", "min_cases", "min_agree_pct", "min_days",
              "auto_promote", "criteria_met", "enabled"]:
        assert k in promo, f"missing key {k}"
    assert promo["min_cases"] == 10
    assert promo["min_agree_pct"] == 90
    assert promo["min_days"] == 3
    assert promo["auto_promote"] is True
    assert promo["criteria_met"] is False
    assert promo["enabled"] is False


# ---------------- Fusion config with auto_promote toggle ----------------
def test_fusion_config_auto_promote(H):
    r = requests.get(f"{BASE}/api/fusion/config", headers=H)
    assert r.status_code == 200, r.text
    cfg = r.json()
    print("initial cfg:", cfg)
    assert cfg["fusion_v2_enabled"] is False
    assert "fusion_v2_auto_promote" in cfg
    assert "promoted_at" in cfg
    assert cfg["promoted_at"] is None

    # toggle auto_promote off
    r2 = requests.put(f"{BASE}/api/fusion/config",
                      json={"fusion_v2_enabled": False, "fusion_v2_auto_promote": False}, headers=H)
    assert r2.status_code == 200, r2.text
    print("after off:", r2.json())
    assert r2.json()["fusion_v2_auto_promote"] is False

    # restore
    r3 = requests.put(f"{BASE}/api/fusion/config",
                      json={"fusion_v2_enabled": False, "fusion_v2_auto_promote": True}, headers=H)
    assert r3.status_code == 200, r3.text
    assert r3.json()["fusion_v2_auto_promote"] is True
    assert r3.json()["fusion_v2_enabled"] is False
