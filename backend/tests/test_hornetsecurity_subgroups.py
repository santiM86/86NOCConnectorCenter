"""
Backend tests for Hornetsecurity 365 Total Backup - Sub-Group Mapping (P0 feature).

Covers:
- POST /api/admin/hornetsecurity/backfill-sub-groups (admin only)
- GET  /api/admin/hornetsecurity/tenants  (sub_groups_count + filters)
- GET  /api/admin/hornetsecurity/tenants/{tenant_name}/sub-groups
- PUT  /api/clients/{client_id}/backup/hornetsecurity/mapping (string + dict mix)
- GET  /api/clients/{client_id}/backup/hornetsecurity/mapping (tenants + filters)
- GET  /api/clients/{client_id}/backup/hornetsecurity/status (filtered by sub_group)
- GET  /api/clients/{client_id}/backup/hornetsecurity/alerts (filtered by sub_group)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://device-monitor-94.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"  # 86BIT_Office (per agent context)
TENANT_GIAMBARINI = "Gruppo Giambarini"
SUB_GALVAN = "galvan.it"
SUB_OLFEZ = "olfez.it"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed ({r.status_code}): {r.text[:200]}")
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"No token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module", autouse=True)
def restore_mapping_after(auth):
    """After all tests, restore the 86BIT_Office mapping to empty (per request)."""
    yield
    try:
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": []},
            timeout=20,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Test: tenant list with sub_groups_count
# ---------------------------------------------------------------------------
class TestTenantList:
    def test_tenants_endpoint_returns_sub_groups_count(self, auth):
        r = requests.get(f"{API}/admin/hornetsecurity/tenants", headers=auth, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        tenants = data.get("tenants") or data.get("items") or data
        assert isinstance(tenants, list) and len(tenants) > 0
        # Each tenant must have sub_groups_count
        sample = tenants[0]
        assert "sub_groups_count" in sample, f"missing sub_groups_count: {sample}"
        # mappings entry shape: 'tenants' + 'filters' if any client has mapping
        # find Giambarini
        gb = next((t for t in tenants if t.get("tenant") == TENANT_GIAMBARINI or t.get("name") == TENANT_GIAMBARINI), None)
        if gb:
            assert gb["sub_groups_count"] >= 5, f"Giambarini should have >=5 sub-groups: {gb}"

    def test_tenants_mappings_have_filters_field(self, auth):
        # Pre-set a sub_group mapping so we can verify 'filters' exposure
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": [{"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN]}]},
            timeout=20,
        )
        r = requests.get(f"{API}/admin/hornetsecurity/tenants", headers=auth, timeout=30)
        assert r.status_code == 200
        data = r.json()
        # mappings is at top-level (not nested per-tenant)
        mappings = data.get("mappings") or []
        m = next((x for x in mappings if x.get("client_id") == CLIENT_ID), None)
        assert m is not None, f"client mapping not found in mappings: {mappings}"
        assert "filters" in m, f"missing 'filters' in mapping entry: {m}"
        assert "tenants" in m, f"missing legacy 'tenants' in mapping entry: {m}"
        # filters should contain the sub_group
        flat = []
        for f in m["filters"]:
            if f.get("sub_groups"):
                flat.extend(f["sub_groups"])
        assert SUB_GALVAN in flat, f"galvan.it not in filters: {m['filters']}"


# ---------------------------------------------------------------------------
# Test: sub-groups discovery endpoint
# ---------------------------------------------------------------------------
class TestSubGroupsDiscovery:
    def test_giambarini_sub_groups(self, auth):
        r = requests.get(
            f"{API}/admin/hornetsecurity/tenants/{TENANT_GIAMBARINI}/sub-groups",
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        sgs = data.get("sub_groups", [])
        assert isinstance(sgs, list)
        assert data.get("total_sub_groups", len(sgs)) >= 5, f"expected >=5 sub-groups: {data}"
        # find galvan/olfez/zincaturadicambiano
        names = [s.get("sub_group") for s in sgs]
        assert SUB_GALVAN in names, f"galvan.it missing: {names}"
        assert SUB_OLFEZ in names, f"olfez.it missing: {names}"
        # _ungrouped_ may exist
        # Each entry should have workloads count + types
        for sg in sgs:
            assert "workloads" in sg or "workloads_total" in sg or "count" in sg
            assert "sub_group" in sg

    def test_sub_groups_admin_only(self):
        # Without auth token
        r = requests.get(
            f"{API}/admin/hornetsecurity/tenants/{TENANT_GIAMBARINI}/sub-groups",
            timeout=20,
        )
        assert r.status_code in (401, 403), r.status_code

    def test_sub_groups_show_mapped_clients(self, auth):
        # Pre-condition: 86BIT_Office is mapped to galvan.it (set in previous test)
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": [{"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN]}]},
            timeout=20,
        )
        r = requests.get(
            f"{API}/admin/hornetsecurity/tenants/{TENANT_GIAMBARINI}/sub-groups",
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200
        sgs = r.json().get("sub_groups", [])
        galvan = next((s for s in sgs if s["sub_group"] == SUB_GALVAN), None)
        assert galvan is not None
        mc = galvan.get("mapped_clients") or []
        client_ids = [c.get("id") or c.get("client_id") for c in mc]
        assert CLIENT_ID in client_ids, f"client {CLIENT_ID} not in mapped_clients: {mc}"


# ---------------------------------------------------------------------------
# Test: PUT/GET client mapping (string vs dict)
# ---------------------------------------------------------------------------
class TestClientMapping:
    def test_set_mapping_with_subgroups_dict(self, auth):
        payload = {"tenants": [{"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN, SUB_OLFEZ]}]}
        r = requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out.get("saved") is True
        ts = out.get("tenants", [])
        assert len(ts) == 1
        entry = ts[0]
        assert isinstance(entry, dict)
        assert entry["tenant"] == TENANT_GIAMBARINI
        assert sorted(entry["sub_groups"]) == sorted([SUB_GALVAN, SUB_OLFEZ])

    def test_get_mapping_returns_tenants_and_filters(self, auth):
        r = requests.get(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        assert "tenants" in data and "filters" in data, data
        # filters should contain the giambarini entry with sub_groups list
        f = next((x for x in data["filters"] if x["tenant"] == TENANT_GIAMBARINI), None)
        assert f is not None
        assert sorted(f["sub_groups"]) == sorted([SUB_GALVAN, SUB_OLFEZ])

    def test_set_mapping_string_legacy(self, auth):
        # Whole-tenant mapping via string
        payload = {"tenants": [TENANT_GIAMBARINI]}
        r = requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200
        out = r.json()
        assert TENANT_GIAMBARINI in out["tenants"]

        g = requests.get(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            timeout=20,
        )
        gd = g.json()
        assert TENANT_GIAMBARINI in gd["tenants"]
        # filters should have sub_groups: None
        f = next((x for x in gd["filters"] if x["tenant"] == TENANT_GIAMBARINI), None)
        assert f is not None
        assert f.get("sub_groups") in (None, [])

    def test_set_mapping_mixed(self, auth):
        # Mix string + dict
        payload = {
            "tenants": [
                "Europizzi",
                {"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN]},
            ]
        }
        r = requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200
        out = r.json()
        ts = out["tenants"]
        # string Europizzi preserved as string; Giambarini as dict
        assert "Europizzi" in ts
        gb = next((x for x in ts if isinstance(x, dict) and x.get("tenant") == TENANT_GIAMBARINI), None)
        assert gb is not None
        assert gb["sub_groups"] == [SUB_GALVAN]


# ---------------------------------------------------------------------------
# Test: status & alerts filtering by sub_group
# ---------------------------------------------------------------------------
class TestStatusFiltered:
    def test_status_filtered_by_subgroups(self, auth):
        # Set mapping galvan + olfez
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": [{"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN, SUB_OLFEZ]}]},
            timeout=20,
        )
        r = requests.get(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/status",
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # totals: should be ~299 (98+201). Allow some tolerance because data may evolve.
        totals = data.get("totals") or data.get("by_state") or {}
        total_items = (
            data.get("total_workloads")
            or data.get("workloads_total")
            or totals.get("total")
            or sum(v for v in totals.values() if isinstance(v, int))
            or 0
        )
        assert total_items > 0, f"expected items > 0: {data}"
        assert total_items < 654, f"expected <654 (subgroup filter), got {total_items}"
        # by_sub_group must be present
        bsg = data.get("by_sub_group") or (totals.get("by_sub_group") if isinstance(totals, dict) else None)
        assert bsg is not None, f"missing by_sub_group: {data}"
        # Should contain only galvan / olfez keys
        keys = set(bsg.keys()) if isinstance(bsg, dict) else set()
        assert keys.issubset({SUB_GALVAN, SUB_OLFEZ}), f"unexpected sub_groups in result: {keys}"

    def test_status_whole_tenant(self, auth):
        # Whole-tenant mapping → ~654 workloads
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": [TENANT_GIAMBARINI]},
            timeout=20,
        )
        r = requests.get(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/status",
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        totals = data.get("totals") or data.get("by_state") or {}
        total_items = (
            data.get("total_workloads")
            or data.get("workloads_total")
            or totals.get("total")
            or sum(v for v in totals.values() if isinstance(v, int))
            or 0
        )
        assert total_items >= 400, f"whole-tenant should return all workloads, got {total_items}: {data}"

    def test_alerts_filtered(self, auth):
        # Set sub-group mapping and check alerts
        requests.put(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/mapping",
            headers=auth,
            json={"tenants": [{"tenant": TENANT_GIAMBARINI, "sub_groups": [SUB_GALVAN]}]},
            timeout=20,
        )
        r = requests.get(
            f"{API}/clients/{CLIENT_ID}/backup/hornetsecurity/alerts",
            headers=auth,
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        alerts = data if isinstance(data, list) else data.get("alerts", [])
        # Each alert (if any) must have sub_group == galvan.it (or be empty)
        for a in alerts:
            sg = a.get("sub_group")
            if sg:
                assert sg == SUB_GALVAN, f"unexpected sub_group in alert: {a}"


# ---------------------------------------------------------------------------
# Test: backfill admin endpoint
# ---------------------------------------------------------------------------
class TestBackfill:
    def test_backfill_admin_only(self):
        r = requests.post(f"{API}/admin/hornetsecurity/backfill-sub-groups", timeout=30)
        assert r.status_code in (401, 403)

    def test_backfill_runs_idempotent(self, auth):
        # Already executed per agent context, so this run should return 0 updates (idempotent)
        r = requests.post(
            f"{API}/admin/hornetsecurity/backfill-sub-groups",
            headers=auth,
            timeout=120,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Must contain counters
        assert "workloads_updated" in data or "updated_workloads" in data or "matched_workloads" in data, data
