"""Regression per la fusione multi-fonte + source-health gating (affidabilita' 100%).

Copre:
  - Datto scartato quando la sorgente e' inaffidabile (internet down/blackout)
  - Datto usato quando affidabile (ping fail + datto offline -> server_down)
  - Match hostname FQDN->short e serial
  - build_context calcola source_health e blackout Datto
"""
import correlation_engine as ce


def _base_ctx():
    return {
        "ip_ev": {}, "mac_ev": {}, "offline_clients": set(), "wan": {},
        "child_to_switch": {},
        "datto": {"c1": {"by_ip": {}, "by_mac": {}, "by_name": {},
                          "by_uid": {}, "by_serial": {}, "by_host": {}}},
        "source_health": {"c1": {"datto_reliable": True, "connector_reliable": True,
                                 "internet_up": True, "datto_reason": "ok"}},
    }


def test_datto_discarded_when_unreliable():
    ctx = _base_ctx()
    b = ctx["datto"]["c1"]
    dd = {"uid": "u1", "online": False, "datto_last_seen": None}
    b["by_ip"]["10.0.0.5"] = dd
    b["by_uid"]["u1"] = dd
    ctx["source_health"]["c1"]["datto_reliable"] = False
    md = {"client_id": "c1", "ip": "10.0.0.5", "device_type": "server", "name": "SRV1"}
    s = ce.gather_signals(md, {"reachable": True}, ctx)
    assert s["datto"] is None, "Datto deve essere scartato se inaffidabile"
    v = ce.verdict_server(s, None)
    assert v["up"] is True and v["alertable"] is False


def test_datto_used_when_reliable():
    ctx = _base_ctx()
    b = ctx["datto"]["c1"]
    dd = {"uid": "u1", "online": False, "datto_last_seen": None}
    b["by_ip"]["10.0.0.5"] = dd
    b["by_uid"]["u1"] = dd
    md = {"client_id": "c1", "ip": "10.0.0.5", "device_type": "server", "name": "SRV1"}
    s = ce.gather_signals(md, {"reachable": False, "consecutive_failures": 5,
                               "last_reachable_at": None}, ctx)
    assert s["datto"] == "offline"
    v = ce.verdict_server(s, None)
    assert v["root_cause"] == "server_down" and v["severity"] == "critical"


def test_hostname_and_serial_match():
    ctx = _base_ctx()
    b = ctx["datto"]["c1"]
    b["by_host"]["srv1"] = {"uid": "u9", "online": True}
    b["by_serial"]["ABC123"] = {"uid": "u7", "online": True}
    # FQDN -> hostname corto
    md_fqdn = {"client_id": "c1", "ip": "1.2.3.4", "name": "SRV1.dominio.local"}
    assert ce._datto_lookup(ctx, md_fqdn) is not None
    # serial (case-insensitive)
    md_ser = {"client_id": "c1", "ip": "9.9.9.9", "serial": "abc123"}
    assert ce._datto_lookup(ctx, md_ser) is not None


def test_persisted_uid_link_priority():
    ctx = _base_ctx()
    b = ctx["datto"]["c1"]
    target = {"uid": "uZ", "online": True}
    b["by_uid"]["uZ"] = target
    md = {"client_id": "c1", "ip": "1.1.1.1", "datto_uid": "uZ"}
    assert ce._datto_lookup(ctx, md) is target
