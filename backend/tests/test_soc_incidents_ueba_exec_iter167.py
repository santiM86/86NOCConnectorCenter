# Iter167: Incidenti correlati + indagine AI, UEBA (evaluate_event / user risk), Dashboard Direzione (executive summary)
import os, sys, asyncio, uuid, pytest, requests, pyotp
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')
sys.path.insert(0, '/app/backend')
BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
CID = 'TEST_cli_iter167'
KEEP = os.environ.get('KEEP_TEST167') == '1'
ALERT_IDS = [f"TEST_a167_{i}_{uuid.uuid4().hex[:6]}" for i in range(3)]
RISK_IDS = [f"TEST_r167_{i}_{uuid.uuid4().hex[:6]}" for i in range(2)]


def _db():
    return AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]


def run(fn):
    async def w():
        return await fn(_db())
    return asyncio.run(w())


@pytest.fixture(scope='module')
def H():
    tf = '/tmp/argus_tok'
    if os.path.exists(tf):
        t = open(tf).read().strip()
        if requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 200:
            return {"Authorization": f"Bearer {t}"}
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    t = r.json()['token']
    r2 = requests.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP('NMHDJNO53WLTOSREUXWERE6FDH5TAKC3').now()},
                       headers={"Authorization": f"Bearer {t}"})
    assert r2.status_code == 200, r2.text
    t = r2.json()['token']
    open(tf, 'w').write(t)
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope='module', autouse=True)
def seed():
    async def up(db):
        await db.clients.insert_one({"id": CID, "name": "TEST_Cliente167", "description": "TEST", "contact_email": "test167@example.com", "created_at": datetime.now(timezone.utc).isoformat()})
    run(up)
    yield
    if KEEP:
        return
    async def down(db):
        await db.alerts.delete_many({"id": {"$in": ALERT_IDS + RISK_IDS}})
        await db.incidents.delete_many({"client_id": CID})
        await db.ueba_profiles.delete_many({"client_id": CID})
        await db.security_events.delete_many({"client_id": CID, "TEST_iter167": True})
        await db.clients.delete_many({"id": CID})
    run(down)


def _alert(i, aid, st, sev):
    now = datetime.now(timezone.utc).isoformat()
    return {"id": aid, "client_id": CID, "device_ip": "10.167.0.5", "device_name": "TEST_SRV167", "severity": sev,
            "source_type": st, "status": "active", "title": f"TEST_ alert {st}", "message": "TEST", "created_at": now,
            "ueba_user": "mario", "acknowledged_at": None, "resolved_at": None}


# --- Correlation
class TestCorrelation:
    def test_correlate_creates_one_incident(self, H):
        specs = [("ueba_new_host", "medium"), ("seclog_new_origin", "high"), ("ueba_unusual_hour", "medium")]
        async def up(db):
            await db.alerts.insert_many([_alert(i, ALERT_IDS[i], s, v) for i, (s, v) in enumerate(specs)])
        run(up)
        r = requests.post(f"{BASE_URL}/api/incidents/correlate-now", headers=H, timeout=180)
        assert r.status_code == 200, r.text
        assert isinstance(r.json()["created"], int)
        async def chk(db):
            incs = await db.incidents.find({"client_id": CID}, {"_id": 0}).to_list(10)
            al = await db.alerts.find({"id": {"$in": ALERT_IDS}}, {"_id": 0, "incident_id": 1}).to_list(10)
            return incs, al
        incs, al = run(chk)
        assert len(incs) == 1, incs
        inc = incs[0]
        assert inc["source"] == "auto_correlation"
        assert sorted(inc["alert_ids"]) == sorted(ALERT_IDS)
        assert inc["priority"] == "high"
        assert "auto" in inc["tags"]
        assert all(a.get("incident_id") == inc["id"] for a in al)
        # high priority -> auto AI investigation expected
        print("auto ai_investigation present:", bool(inc.get("ai_investigation")), inc.get("status"))

    def test_second_correlate_creates_zero(self, H):
        r = requests.post(f"{BASE_URL}/api/incidents/correlate-now", headers=H, timeout=180)
        assert r.status_code == 200
        n = run(lambda db: db.incidents.count_documents({"client_id": CID}))
        assert n == 1

    def test_incident_list_contains_auto(self, H):
        r = requests.get(f"{BASE_URL}/api/incidents", headers=H, timeout=30)
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("incidents") or data.get("items") or []
        mine = [i for i in items if i.get("client_id") == CID]
        assert mine and mine[0]["source"] == "auto_correlation"
        assert "_id" not in mine[0]


# --- AI investigation
class TestInvestigate:
    def test_investigate_real_llm(self, H):
        inc = run(lambda db: db.incidents.find_one({"client_id": CID}, {"_id": 0, "id": 1}))
        r = requests.post(f"{BASE_URL}/api/incidents/{inc['id']}/investigate", headers=H, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("result", "at", "by", "model"):
            assert k in d
        res = d["result"]
        for k in ("headline", "verdict", "summary", "actions"):
            assert k in res, res
        assert isinstance(res["actions"], list) and res["actions"]
        assert res["verdict"] in ("vero_positivo", "probabile", "falso_positivo", "da_verificare")
        assert d["by"] == "info@86bit.it"
        doc = run(lambda db: db.incidents.find_one({"id": inc["id"]}, {"_id": 0}))
        assert doc["ai_investigation"]["result"]["headline"] == res["headline"]
        assert doc["status"] == "investigating"
        assert any(t.get("action") == "ai_investigation" for t in doc["timeline"])

    def test_investigate_unknown_404(self, H):
        r = requests.post(f"{BASE_URL}/api/incidents/does-not-exist-167/investigate", headers=H, timeout=30)
        assert r.status_code == 404

    def test_investigate_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/incidents/x/investigate", timeout=30)
        assert r.status_code in (401, 403)


# --- UEBA unit
class TestUebaUnit:
    def test_evaluate_event_learned_and_new(self):
        async def go():
            import ueba
            from database import db
            now = datetime.now(timezone.utc)
            hours = [0] * 24
            hours[9] = 50
            await db.ueba_profiles.insert_one({"client_id": CID, "user": "luigi", "hours": hours, "hosts": {"srv1_lan": 50}, "total": 50,
                                               "first_seen": (now - timedelta(days=10)).isoformat(), "last_seen": now.isoformat(),
                                               "last_public": {"ip": "8.8.8.8", "ts": (now - timedelta(minutes=5)).isoformat()}})
            await db.security_events.insert_many([{"client_id": CID, "category": "logon_failed", "user": "Luigi", "TEST_iter167": True, "seq": f"TEST167_{_i}",
                                                   "ts": now.isoformat()} for _i in range(5)])
            em = []
            async def emit(c, h, sev, t, m, st):
                em.append((st, sev))
            # 03:00 Rome local = 01:00/02:00 UTC
            from zoneinfo import ZoneInfo
            ts = now.astimezone(ZoneInfo("Europe/Rome")).replace(hour=3, minute=0).astimezone(timezone.utc).isoformat()
            await ueba.evaluate_event(CID, "srv2.lan", {"user": "Luigi", "domain": "CORP", "ts": ts, "src_ip": "1.1.1.1"}, "Europe/Rome", emit)
            prof = await db.ueba_profiles.find_one({"client_id": CID, "user": "luigi"}, {"_id": 0})
            em2 = []
            async def emit2(c, h, sev, t, m, st):
                em2.append(st)
            await ueba.evaluate_event(CID, "pc1", {"user": "newbie", "ts": ts, "src_ip": "192.168.1.4"}, "Europe/Rome", emit2)
            newp = await db.ueba_profiles.find_one({"client_id": CID, "user": "newbie"}, {"_id": 0})
            em3 = []
            async def emit3(c, h, sev, t, m, st):
                em3.append(st)
            await ueba.evaluate_event(CID, "pc1", {"user": "PC1$", "ts": ts}, "Europe/Rome", emit3)
            return em, prof, em2, newp, em3
        em, prof, em2, newp, em3 = asyncio.run(go())
        types = {t for t, _ in em}
        print("emitted:", em)
        assert types == {"ueba_unusual_hour", "ueba_new_host", "ueba_impossible", "ueba_bruteforce_ok"}
        assert dict(em)["ueba_impossible"] == "high" and dict(em)["ueba_bruteforce_ok"] == "high"
        assert prof["total"] == 51 and prof["hosts"]["srv2_lan"] == 1 and prof["hours"][3] == 1
        assert prof["last_public"]["ip"] == "1.1.1.1"
        assert em2 == []
        assert len(newp["hours"]) == 24 and sum(newp["hours"]) == 1 and newp["hours"][3] == 1
        assert newp["total"] == 1 and newp["hosts"] == {"pc1": 1} and newp["first_seen"]
        assert "last_public" not in newp
        assert em3 == []


# --- UEBA users + executive
class TestUebaAndExecutive:
    def test_ueba_users(self, H):
        now = datetime.now(timezone.utc).isoformat()
        async def up(db):
            await db.alerts.insert_many([
                {"id": RISK_IDS[0], "client_id": CID, "source_type": "ueba_impossible", "ueba_user": "luigi", "severity": "high",
                 "status": "resolved", "created_at": now, "title": "TEST_ risk", "incident_id": "TEST_none"},
                {"id": RISK_IDS[1], "client_id": CID, "source_type": "ueba_bruteforce_ok", "ueba_user": "luigi", "severity": "high",
                 "status": "resolved", "created_at": now, "title": "TEST_ risk2", "incident_id": "TEST_none"}])
        run(up)
        r = requests.get(f"{BASE_URL}/api/ueba/users", params={"client_id": CID, "days": 30}, headers=H, timeout=30)
        assert r.status_code == 200, r.text
        rows = {x["user"]: x for x in r.json()}
        print(rows)
        lu = rows["luigi"]
        assert lu["score"] == 60 and lu["anomalies"] == 2
        assert lu["types"] == {"ueba_impossible": 1, "ueba_bruteforce_ok": 1}
        assert lu["client_name"] == "TEST_Cliente167"
        assert lu["profile"]["logons"] == 51 and lu["profile"]["hosts"] == 2
        ma = rows["mario"]  # 3 correlation alerts: new_host 12 + new_origin 15 + unusual_hour 8
        assert ma["score"] == 35

    def test_executive_summary_client(self, H):
        r = requests.get(f"{BASE_URL}/api/executive/summary", params={"client_id": CID, "days": 30}, headers=H, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert 0 <= d["risk_score"] <= 100
        assert d["risk_level"] in ("basso", "medio", "alto")
        assert d["active_alerts"] == 3
        assert set(d["alerts_by_severity"]) == {"critical", "high", "medium", "low"}
        assert d["incidents_period"] == 1 and d["incidents_open"] == 1 and d["incidents_auto"] == 1
        assert d["top_risky_users"][0]["user"] == "luigi"
        assert len(d["compliance"]) == 8
        for c in d["compliance"]:
            assert set(c) >= {"key", "label", "norm", "status", "detail"} and c["status"] in ("ok", "warn", "ko")
        assert 0 <= d["compliance_score"] <= 100
        assert "mtta_min" in d and "mttr_min" in d
        print(d["risk_score"], d["compliance_score"])

    def test_executive_summary_global(self, H):
        r = requests.get(f"{BASE_URL}/api/executive/summary", params={"days": 7}, headers=H, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["days"] == 7 and d["client_id"] is None and len(d["compliance"]) == 8
        print({k: d[k] for k in ("risk_score", "risk_level", "active_alerts", "mtta_min", "mttr_min", "compliance_score")})

    def test_executive_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/executive/summary", timeout=30).status_code in (401, 403)
        assert requests.get(f"{BASE_URL}/api/ueba/users", timeout=30).status_code in (401, 403)
