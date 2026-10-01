"""Iter 156: tests end-to-end API /api/seclog/* via public URL con admin + 2FA TOTP.
Copre: ingest-manual, events, stats (400 senza client_id), verify (ok/tamper), admins PUT ricalcolo,
settings 422 fuori range, report.pdf (header %PDF), alert in db.alerts.
Cleanup finale per client_id test-seclog-qa.
"""
import os
import uuid
import pytest
import pyotp
import requests
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://noc-alert-hub-2.preview.emergentagent.com").rstrip("/")
EMAIL = "info@86bit.it"
PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
CID = "test-seclog-qa"
HOST = "QA-API-SRV"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    if j.get("requires_2fa") or j.get("requires_2fa_setup") is False or not j.get("refresh_token"):
        # verify-2fa needed
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r2.status_code == 200, r2.text
        tok = r2.json().get("token") or r2.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _ev(rid, eid, data, log="Security"):
    return {"log": log, "record_id": rid, "event_id": eid,
            "ts": datetime.now(timezone.utc).isoformat(), "data": data}


@pytest.fixture(scope="module", autouse=True)
def cleanup(hdr):
    # pre-cleanup via direct mongo (unavailable from here) — rely on unique seq by using fresh CID per run? spec says fixed. Use delete endpoint? none → best effort: let test be idempotent by picking high record_ids
    yield
    # best-effort cleanup through connection to local mongo via test runner cwd env
    try:
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from database import db  # type: ignore
        async def _c():
            for c in ("security_events", "security_chain_state", "security_admins",
                      "security_log_settings", "alerts"):
                await db[c].delete_many({"client_id": CID})
            await db.alerts.delete_many({"device_ip": HOST})
        asyncio.get_event_loop().run_until_complete(_c())
    except Exception as e:
        print("cleanup error:", e)


def test_01_pre_cleanup_mongo():
    """Clear previous residue for CID to make test deterministic."""
    import asyncio, sys
    sys.path.insert(0, "/app/backend")
    from database import db  # type: ignore
    async def _c():
        for c in ("security_events", "security_chain_state", "security_admins",
                  "security_log_settings", "alerts"):
            await db[c].delete_many({"client_id": CID})
    asyncio.get_event_loop().run_until_complete(_c())


def test_02_set_admins(hdr):
    r = requests.put(f"{BASE_URL}/api/seclog/admins/{CID}",
                     json={"users": ["it-admin", "m.rossi"]}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    assert set(r.json()["users"]) == {"it-admin", "m.rossi"}


def test_03_settings_out_of_range_422(hdr):
    r = requests.put(f"{BASE_URL}/api/seclog/settings/{CID}",
                     json={"retention_months": 3}, headers=hdr, timeout=15)
    assert r.status_code == 422, r.text
    r2 = requests.put(f"{BASE_URL}/api/seclog/settings/{CID}",
                      json={"retention_months": 999}, headers=hdr, timeout=15)
    assert r2.status_code == 422


def test_04_settings_ok(hdr):
    r = requests.put(f"{BASE_URL}/api/seclog/settings/{CID}",
                     json={"retention_months": 24}, headers=hdr, timeout=15)
    assert r.status_code == 200
    assert r.json()["retention_months"] == 24


def test_05_ingest_manual(hdr):
    batch = [
        _ev(1001, 4624, {"TargetUserName": "m.rossi", "TargetDomainName": "ACME",
                         "LogonType": "10", "IpAddress": "10.0.0.5", "WorkstationName": "PC-ROSSI"}),
        _ev(1002, 4624, {"TargetUserName": "QA-API-SRV$", "LogonType": "3"}),  # noise
        _ev(1003, 4624, {"TargetUserName": "SYSTEM", "LogonType": "5"}),  # noise
        _ev(1004, 4672, {"SubjectUserName": "it-admin"}),
        _ev(1005, 4720, {"TargetUserName": "backdoor", "SubjectUserName": "it-admin"}),
        _ev(1006, 4732, {"MemberName": "CN=backdoor", "TargetUserName": "Administrators",
                         "SubjectUserName": "it-admin"}),
        _ev(1007, 1102, {"SubjectUserName": "it-admin"}),
        _ev(1050, 6005, {}, "System"),
        _ev(1051, 1149, {"User": "m.rossi", "Address": "10.0.0.9"}, "TerminalServices"),
    ] + [_ev(1100 + i, 4625, {"TargetUserName": "administrator",
                               "IpAddress": "203.0.113.9", "LogonType": "3"}) for i in range(12)]
    r = requests.post(f"{BASE_URL}/api/seclog/ingest-manual",
                      json={"client_id": CID, "host": HOST, "events": batch},
                      headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    # 2 noise discarded + 21 stored (1 unknown? no, 1149 known) → stored=21 skipped=2
    assert j["stored"] == 19, j
    assert j["skipped"] == 2, j


def test_06_dedup(hdr):
    """Re-send same batch → stored=0."""
    batch = [_ev(1001, 4624, {"TargetUserName": "m.rossi", "LogonType": "10"})]
    r = requests.post(f"{BASE_URL}/api/seclog/ingest-manual",
                      json={"client_id": CID, "host": HOST, "events": batch},
                      headers=hdr, timeout=15)
    assert r.status_code == 200
    assert r.json()["stored"] == 0


def test_07_events_list(hdr):
    r = requests.get(f"{BASE_URL}/api/seclog/events",
                     params={"client_id": CID, "hours": 24, "host": HOST, "limit": 500},
                     headers=hdr, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 19, j["total"]
    # ordered desc by ts (so first event has highest seq area)
    seqs = [e["seq"] for e in j["events"]]
    assert len(seqs) == 19
    # chain fields present
    for e in j["events"]:
        assert "hash" in e and "prev_hash" in e and "seq" in e
    # 4624 m.rossi normalized
    rossi = [e for e in j["events"] if e["event_id"] == 4624 and e["user"] == "m.rossi"]
    assert rossi and rossi[0]["logon_type"] == 10 and rossi[0]["src_ip"] == "10.0.0.5"
    # 4732 group=Administrators, user=backdoor
    grp = [e for e in j["events"] if e["event_id"] == 4732]
    assert grp and grp[0]["group"] == "Administrators" and grp[0]["user"] == "backdoor"


def test_08_events_filters(hdr):
    r = requests.get(f"{BASE_URL}/api/seclog/events",
                     params={"client_id": CID, "hours": 24, "admin_only": True, "limit": 500},
                     headers=hdr, timeout=15)
    assert r.status_code == 200
    assert all(e["is_admin"] for e in r.json()["events"])
    r2 = requests.get(f"{BASE_URL}/api/seclog/events",
                      params={"client_id": CID, "hours": 24, "category": "log_cleared"},
                      headers=hdr, timeout=15)
    assert r2.status_code == 200
    evs = r2.json()["events"]
    assert evs and all(e["category"] == "log_cleared" for e in evs)
    r3 = requests.get(f"{BASE_URL}/api/seclog/events",
                      params={"client_id": CID, "hours": 24, "q": "administrator"},
                      headers=hdr, timeout=15)
    assert r3.status_code == 200
    assert r3.json()["total"] >= 10


def test_09_stats(hdr):
    r = requests.get(f"{BASE_URL}/api/seclog/stats",
                     params={"client_id": CID}, headers=hdr, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["by_category"]["logon_failed"] >= 12
    assert j["admin_events"] >= 1
    assert any(h["host"] == HOST for h in j["hosts"])
    assert j["chain"] and j["chain"]["last_seq"] == 19
    assert j["retention_months"] == 24
    assert "it-admin" in j["admins"]


def test_10_stats_without_client_id_400(hdr):
    r = requests.get(f"{BASE_URL}/api/seclog/stats", headers=hdr, timeout=15)
    assert r.status_code == 400


def test_11_verify_ok(hdr):
    r = requests.get(f"{BASE_URL}/api/seclog/verify",
                     params={"client_id": CID}, headers=hdr, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["checked"] == 19


def test_12_verify_tamper():
    """Alter directly in mongo an event and verify chain broken."""
    import asyncio, sys
    sys.path.insert(0, "/app/backend")
    from database import db  # type: ignore
    import requests as rq

    async def _tamper():
        orig = await db.security_events.find_one({"client_id": CID, "event_id": 4624,
                                                   "user": "m.rossi"}, {"_id": 0, "seq": 1, "user": 1})
        return orig
    orig = asyncio.get_event_loop().run_until_complete(_tamper())
    assert orig
    seq = orig["seq"]

    async def _apply(user):
        await db.security_events.update_one({"client_id": CID, "seq": seq},
                                            {"$set": {"user": user}})
    asyncio.get_event_loop().run_until_complete(_apply("hacker"))

    # Need auth header — use module fixture by re-login quick
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    tok = r.json().get("token")
    if not r.json().get("refresh_token"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa",
                    json={"code": code}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        tok = r2.json().get("token")
    r3 = s.get(f"{BASE_URL}/api/seclog/verify", params={"client_id": CID},
               headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r3.status_code == 200
    j = r3.json()
    assert j["ok"] is False
    assert j["broken_at_seq"] == seq
    # restore
    asyncio.get_event_loop().run_until_complete(_apply(orig["user"]))
    r4 = s.get(f"{BASE_URL}/api/seclog/verify", params={"client_id": CID},
               headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r4.json()["ok"] is True


def test_13_admins_recalc(hdr):
    """Change admins list → is_admin ricalcolato on events (not 4672)."""
    r = requests.put(f"{BASE_URL}/api/seclog/admins/{CID}",
                     json={"users": ["m.rossi"]}, headers=hdr, timeout=15)
    assert r.status_code == 200
    # 4624 m.rossi should now be is_admin true
    r2 = requests.get(f"{BASE_URL}/api/seclog/events",
                      params={"client_id": CID, "hours": 24, "user": "m.rossi", "limit": 50},
                      headers=hdr, timeout=15)
    rossi = [e for e in r2.json()["events"] if e["event_id"] == 4624]
    assert rossi and all(e["is_admin"] for e in rossi)
    # 4672 by it-admin: it-admin NOT in list but event_id=4672 kept as admin
    r3 = requests.get(f"{BASE_URL}/api/seclog/events",
                      params={"client_id": CID, "hours": 24, "category": "privileged_logon"},
                      headers=hdr, timeout=15)
    priv = r3.json()["events"]
    assert priv and all(e["is_admin"] for e in priv)


def test_14_alerts_created(hdr):
    r = requests.get(f"{BASE_URL}/api/alerts",
                     params={"client_id": CID, "status": "active", "limit": 100},
                     headers=hdr, timeout=15)
    assert r.status_code == 200
    data = r.json()
    items = data if isinstance(data, list) else data.get("alerts") or data.get("items") or []
    titles = " || ".join(a.get("title", "") for a in items)
    assert "REGISTRO EVENTI CANCELLATO" in titles, titles
    assert "Nuovo account backdoor" in titles, titles
    assert "gruppo amministrativo" in titles, titles
    assert "Brute-force" in titles and "administrator" in titles, titles


def test_15_report_pdf(hdr):
    now = datetime.now(timezone.utc)
    month = f"{now.year}-{now.month:02d}"
    r = requests.get(f"{BASE_URL}/api/seclog/report.pdf",
                     params={"client_id": CID, "month": month},
                     headers=hdr, timeout=30)
    assert r.status_code == 200
    assert "application/pdf" in r.headers.get("content-type", ""), r.headers
    assert r.content[:4] == b"%PDF", r.content[:20]
    assert len(r.content) > 2000
