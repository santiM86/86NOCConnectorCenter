"""
Comprehensive smoke test of ALL ARGUS NOC backend routes.
Goal: identify GREEN / BROKEN / MISSING endpoints. NO refactoring.
"""
import os
import json
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://device-poller-ws.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"

results = []  # collected for final summary


def record(name, method, url, resp, expected=(200,), extra=None):
    ok = resp is not None and resp.status_code in expected
    entry = {
        "name": name,
        "method": method,
        "url": url,
        "status": resp.status_code if resp is not None else None,
        "ok": ok,
        "extra": extra or {},
    }
    if resp is not None and not ok:
        try:
            entry["body"] = resp.text[:400]
        except Exception:
            entry["body"] = "<unreadable>"
    results.append(entry)
    return entry


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    record("auth.login", "POST", "/api/auth/login", r)
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text[:200]}")
    token = r.json().get("access_token") or r.json().get("token")
    s.headers["Authorization"] = f"Bearer {token}"
    return s


@pytest.fixture(scope="session")
def client_id(session):
    r = session.get(f"{BASE_URL}/api/clients", timeout=15)
    record("clients.list", "GET", "/api/clients", r)
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("clients") or data.get("items") or []
        if items:
            return items[0].get("id") or items[0].get("client_id") or items[0].get("_id")
    return None


# ----- helpers -----
def gget(session, name, path, expected=(200,), extra=None):
    try:
        r = session.get(f"{BASE_URL}{path}", timeout=20)
    except Exception as e:
        results.append({"name": name, "method": "GET", "url": path, "status": None, "ok": False, "error": str(e)})
        return None
    record(name, "GET", path, r, expected, extra)
    return r


def has_mongo_id(obj):
    if isinstance(obj, dict):
        if "_id" in obj:
            return True
        return any(has_mongo_id(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_mongo_id(x) for x in obj)
    return False


# ============ TESTS ============

def test_auth_me(session):
    r = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    record("auth.me", "GET", "/api/auth/me", r)
    assert r.status_code == 200
    assert r.json().get("email") == ADMIN_EMAIL


def test_clients(session):
    r = gget(session, "clients", "/api/clients")
    assert r is not None and r.status_code == 200


def test_devices(session):
    r = gget(session, "devices", "/api/devices")
    if r and r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("devices") or data.get("items") or []
        results[-1]["extra"]["count"] = len(items)
        results[-1]["extra"]["mongo_id_leak"] = has_mongo_id(items[:5])


def test_overview_clients(session):
    gget(session, "overview.clients", "/api/overview/clients")


def test_alerts(session):
    r = gget(session, "alerts", "/api/alerts")
    if r and r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("alerts") or data.get("items") or []
        results[-1]["extra"]["count"] = len(items)


def test_connector_list(session):
    # try multiple paths
    for path in ["/api/connector/list", "/api/connectors", "/api/connector"]:
        r = gget(session, f"connector.list[{path}]", path, expected=(200, 404, 405))
        if r and r.status_code == 200:
            break


def test_connector_discovery_results(session, client_id):
    if not client_id:
        pytest.skip("no client_id")
    gget(session, "connector.discovery_results", f"/api/connector/discovery-results/{client_id}")


def test_connector_force_update_fake(session):
    r = session.post(f"{BASE_URL}/api/connector/fake-id-9999/force-update", json={}, timeout=10)
    record("connector.force_update_fake", "POST", "/api/connector/fake-id-9999/force-update", r, expected=(404, 400, 422))


def test_admin_cleanup_dry_run(session):
    r = session.post(f"{BASE_URL}/api/admin/cleanup-scanner-rogue-devices", json={"dry_run": True}, timeout=20)
    record("admin.cleanup_rogue_dry", "POST", "/api/admin/cleanup-scanner-rogue-devices", r, expected=(200, 202))


def test_vault(session, client_id):
    path = f"/api/vault/credentials?client_id={client_id}" if client_id else "/api/vault/credentials"
    gget(session, "vault.credentials", path)


def test_runbooks(session):
    r = gget(session, "runbooks", "/api/runbooks")
    if r and r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("runbooks") or data.get("items") or []
        results[-1]["extra"]["count"] = len(items)


def test_device_profiles(session):
    r = gget(session, "device_profiles", "/api/device-profiles")
    if r and r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get("profiles") or data.get("items") or []
        results[-1]["extra"]["count"] = len(items)


def test_datto_scheduler(session):
    gget(session, "datto.scheduler_status", "/api/datto/scheduler-status")


def test_datto_admin_config(session):
    gget(session, "datto.admin_config", "/api/admin/datto/config")


def test_hornetsecurity_config(session):
    for p in ["/api/hornetsecurity/config", "/api/admin/hornetsecurity/config"]:
        gget(session, f"hornet.config[{p}]", p, expected=(200, 404))


def test_hornetsecurity_vmbackup(session):
    gget(session, "hornet.vmbackup_config", "/api/hornetsecurity/vmbackup/config", expected=(200, 404))


def test_oncall(session):
    gget(session, "oncall.schedule", "/api/oncall/schedule")
    gget(session, "oncall.users", "/api/oncall/users")


def test_cmdb_assets(session):
    gget(session, "cmdb.assets", "/api/cmdb/assets")


def test_sla(session):
    gget(session, "sla.targets", "/api/sla/targets")


def test_lifecycle(session):
    gget(session, "lifecycle.records", "/api/lifecycle/records")
    gget(session, "lifecycle.dashboard", "/api/lifecycle/dashboard")


def test_notifications(session):
    gget(session, "notifications.templates", "/api/notifications/templates")
    gget(session, "notifications.escalation_rules", "/api/notifications/escalation-rules")


def test_intel(session):
    gget(session, "intel.triage_stats", "/api/intel/triage/stats")
    gget(session, "intel.autodispatch_history", "/api/intel/auto-dispatch/history")
    gget(session, "intel.autodispatch_status", "/api/intel/auto-dispatch/status")


def test_external_monitor(session):
    gget(session, "ext_mon.targets", "/api/external-monitor/targets")
    gget(session, "ext_mon.status", "/api/external-monitor/status")


def test_admin_integrations(session):
    gget(session, "admin.fingerbank", "/api/admin/integrations/fingerbank")


def test_wireguard(session):
    gget(session, "wg.peers", "/api/admin/wireguard/peers")
    gget(session, "wg.server_status", "/api/admin/wireguard/server-status")


def test_console_v4(session):
    gget(session, "console_v4.sessions", "/api/console-v4/sessions")


def test_topology(session, client_id):
    if not client_id:
        pytest.skip("no client_id")
    gget(session, "topology", f"/api/network/topology/{client_id}")


def test_switch_ports(session):
    for ip in ["192.168.99.98", "192.168.1.3"]:
        gget(session, f"switch_ports[{ip}]", f"/api/devices/{ip}/switch-ports", expected=(200, 404))


def test_bmc_candidates(session):
    gget(session, "bmc.candidates", "/api/bmc-candidates")


def test_mac_bindings(session):
    gget(session, "topology.mac_bindings", "/api/topology/mac-bindings")


def test_push(session):
    gget(session, "push.vapid_public_key", "/api/push/vapid-public-key")
    gget(session, "push.status", "/api/push/status")


def test_incidents(session):
    gget(session, "incidents", "/api/incidents")


def test_inventory(session):
    gget(session, "inventory.devices", "/api/inventory/devices")


def test_printers(session, client_id):
    if not client_id:
        pytest.skip("no client_id")
    gget(session, "printers.dashboard", f"/api/printers/dashboard/{client_id}")


def test_backup(session):
    gget(session, "backup.status", "/api/backup/status")


def test_soc_ai(session):
    for p in ["/api/soc/incidents", "/api/soc/status"]:
        gget(session, f"soc_ai[{p}]", p, expected=(200, 404))


def test_vulnerability(session):
    gget(session, "vuln.scans", "/api/vulnerability/scans")


def test_security_status(session):
    gget(session, "security.status", "/api/security/status")


def test_audit(session):
    for p in ["/api/audit/logs", "/api/audit-logs", "/api/admin/audit/logs"]:
        gget(session, f"audit[{p}]", p, expected=(200, 404))


def test_firmware_catalog(session):
    gget(session, "firmware.catalog", "/api/firmware/catalog")


def test_public_dashboard(session):
    gget(session, "public.dashboards", "/api/public/dashboards", expected=(200, 401))


def test_customer_portal(session, client_id):
    for p in ["/api/customer-portal/clients", "/api/customer-portal/dashboard", "/api/customer-portal"]:
        gget(session, f"customer_portal[{p}]", p, expected=(200, 404, 401))


def test_connector_update(session):
    gget(session, "connector.update_check", "/api/connector/update-check", expected=(200, 401, 422))
    gget(session, "connector.update_info", "/api/connector/update-info", expected=(200, 401, 422))
    gget(session, "connector.public_download_latest", "/api/connector/public-download/latest", expected=(200, 302, 401, 404))


def test_web_proxy(session, client_id):
    if not client_id:
        pytest.skip()
    gget(session, "web_proxy.pending", f"/api/web-proxy/{client_id}/pending?wait=2", expected=(200, 204, 408))


def test_arp_cache(session):
    for p in ["/api/arp-cache", "/api/arp-cache/list", "/api/network/arp-cache"]:
        gget(session, f"arp[{p}]", p, expected=(200, 404))


def test_syslog_trap(session):
    for p in ["/api/syslog", "/api/traps", "/api/syslog/messages", "/api/syslog-trap/messages"]:
        gget(session, f"syslog[{p}]", p, expected=(200, 404))


def test_tv_dashboard():
    # No auth
    r = requests.get(f"{BASE_URL}/api/tv/clients", timeout=15)
    record("tv.clients", "GET", "/api/tv/clients", r)


def test_reports(session):
    for p in ["/api/reports", "/api/reports/list", "/api/reports/templates"]:
        gget(session, f"reports[{p}]", p, expected=(200, 404))


def test_settings(session):
    gget(session, "settings", "/api/settings")


def test_users(session):
    gget(session, "users", "/api/users")


def test_save_summary():
    """Always-last test: dump results to disk"""
    out = "/app/test_reports/pytest/smoke_results.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} results -> {out}")
    broken = [r for r in results if not r.get("ok")]
    print(f"\nBROKEN ({len(broken)}):")
    for b in broken:
        print(f"  - {b['name']:40s} {b['method']} {b['url']} -> {b.get('status')}")
    print(f"\nGREEN: {len(results) - len(broken)} / {len(results)}")
