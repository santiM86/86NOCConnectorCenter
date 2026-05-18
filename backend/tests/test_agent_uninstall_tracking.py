"""Iteration 82 — Tests for the remote-uninstall tracking flow.

Covers (from review_request):
 - GET /api/agents → uninstall_progress 0..95 lineare sui 3 minuti
   (seed uninstall_started_at di X secondi fa, verifica progress~int(X/1.8))
 - Auto-completion: agent in_progress + NOT live (no REGISTRY) + started_at >30s
   → status='completed', progress=100, cleanup managed_agents + 5 collezioni,
     audit con criteria='uninstall-finalized'
 - Auto-failure: agent ancora LIVE dopo 90s → status='failed'
   (live flag non controllabile dal test ma copriamo il branch tramite seed
   `agent_id` di un'istanza che NON è in REGISTRY: testiamo il path negativo)
 - Auto-timeout: uninstall_started_at >3min fa, mai live → status='completed'
   (perchè not live + >30s ha priorità).  Per testare timeout puro creiamo
   un doc con uninstall_started_at >3min + live forzando un caso edge:
   non possiamo forzare live=true senza WS reale, quindi documentiamo il
   limite e testiamo solo l'auto-completion / timeout-not-live.
 - Tracking flag su DELETE quando agent offline: deve restituire
   uninstall_status='agent_offline' e NON tracking_uninstall (perché
   nessun comando inviato).
 - PS1 magic trigger: file install-noc-agent.ps1 contiene il blocco
   __uninstall__ con uninstall.ps1 + fallback inline.
"""
import os
import time
import uuid
import requests
import pytest
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

PS1_PATH = "/app/noc-agent/build/install-noc-agent.ps1"


# ---------- Fixtures --------------------------------------------------------

@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    db = cli[DB_NAME]
    yield db
    # cleanup any stray TEST_ docs
    for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                "device_poll_status", "agent_log_buffer", "agent_command_audit"):
        try:
            db[col].delete_many({"agent_id": {"$regex": "^TEST_iter82"}})
        except Exception:
            pass
    try:
        db.agent_cleanup_audit.delete_many({"deleted_ids": {"$regex": "^TEST_iter82"}})
    except Exception:
        pass
    cli.close()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _seed_agent_in_progress(db, agent_id: str, seconds_ago: float,
                            uninstall_method: str = "legacy_update"):
    """Insert managed_agents doc with uninstall_status='in_progress'
    and uninstall_started_at = now - seconds_ago.
    """
    started = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.managed_agents.insert_one({
        "agent_id": agent_id,
        "hostname": f"TEST_iter82_host_{agent_id[-8:]}",
        "client_id": "TEST_iter82_client",
        "agent_version": "v4.10.5-test",
        "uninstall_status": "in_progress",
        "uninstall_started_at": started.isoformat(),
        "uninstall_method": uninstall_method,
        "uninstall_initiated_by": "test@example.com",
        "uninstall_purge_data": True,
    })
    # add some related docs that should be cleaned up on auto-complete
    db.sys_metrics_latest.insert_one({"agent_id": agent_id, "cpu_pct": 1.0})
    db.sys_metrics_history.insert_many([
        {"agent_id": agent_id, "cpu_pct": 1.0},
        {"agent_id": agent_id, "cpu_pct": 2.0},
    ])
    db.device_poll_status.insert_one({"agent_id": agent_id, "device_id": "TEST_d"})
    db.agent_log_buffer.insert_one({"agent_id": agent_id, "level": "info"})
    db.agent_command_audit.insert_one({"agent_id": agent_id, "command": "noop"})


def _cleanup_agent(db, agent_id: str):
    for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                "device_poll_status", "agent_log_buffer", "agent_command_audit"):
        try:
            db[col].delete_many({"agent_id": agent_id})
        except Exception:
            pass


# ---------- Progress computation -------------------------------------------

def test_uninstall_progress_low_at_10s(admin_headers, mongo):
    """Agent in_progress da ~10s → progress ~ int(10/1.8)=5 (clamp min 5)."""
    agent_id = f"TEST_iter82_prog10_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=10)
    try:
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        agents = r.json().get("agents", [])
        rec = next((a for a in agents if a.get("agent_id") == agent_id), None)
        assert rec is not None, "seeded agent not in /api/agents"
        # X=10s, expected int(10/1.8)=5, clamp 5..95
        # accept range 5..15 (clock skew + processing time)
        assert rec.get("uninstall_status") == "in_progress"
        prog = rec.get("uninstall_progress")
        assert isinstance(prog, int)
        assert 5 <= prog <= 15, f"progress at 10s should be ~5%, got {prog}"
        assert rec.get("uninstall_method") == "legacy_update"
    finally:
        _cleanup_agent(mongo, agent_id)


def test_uninstall_progress_mid_at_90s(admin_headers, mongo):
    """Agent in_progress da ~90s → progress ~ int(90/1.8)=50.
    NOTE: poiche' l'agent NON e' live (no WS) e elapsed>30s, viene
    autocompletato a 100% e cleanup-up.  Testiamo questo branch.
    """
    agent_id = f"TEST_iter82_prog90_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=90)
    try:
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        agents = r.json().get("agents", [])
        rec = next((a for a in agents if a.get("agent_id") == agent_id), None)
        # Because not-live + elapsed>30s → auto-completed and purged
        # So either the record reports 'completed' with progress=100,
        # OR it's already been removed from managed_agents (depends on
        # whether the response is built before or after the cleanup).
        if rec is None:
            # Already purged by previous list_agents call; verify audit.
            audit = list(mongo.agent_cleanup_audit.find(
                {"deleted_ids": agent_id}).sort("deleted_at", -1).limit(1))
            assert audit, "expected uninstall-finalized audit row"
            assert audit[0].get("criteria") == "uninstall-finalized"
            assert audit[0].get("outcome") == "completed"
        else:
            assert rec.get("uninstall_status") == "completed"
            assert rec.get("uninstall_progress") == 100
    finally:
        _cleanup_agent(mongo, agent_id)


# ---------- Auto-completion (not live + >30s) ------------------------------

def test_auto_completion_cleans_db_and_writes_audit(admin_headers, mongo):
    agent_id = f"TEST_iter82_autocomp_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=45)
    try:
        # Pre-conditions: docs exist
        assert mongo.managed_agents.count_documents({"agent_id": agent_id}) == 1
        assert mongo.sys_metrics_history.count_documents({"agent_id": agent_id}) == 2

        # Call /api/agents → triggers auto-completion + cleanup
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200

        # The list_agents endpoint enqueues finalization AFTER computing
        # the response. Give it a moment to finish the cleanup.
        time.sleep(1.0)

        # All related collections should be empty for this agent
        for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                    "device_poll_status", "agent_log_buffer",
                    "agent_command_audit"):
            left = mongo[col].count_documents({"agent_id": agent_id})
            assert left == 0, f"{col} still has {left} docs"

        # Audit row with criteria='uninstall-finalized'
        audit = list(mongo.agent_cleanup_audit.find(
            {"deleted_ids": agent_id}).sort("deleted_at", -1).limit(2))
        assert audit, "uninstall-finalized audit row missing"
        row = audit[0]
        assert row.get("criteria") == "uninstall-finalized"
        assert row.get("outcome") == "completed"
        assert row.get("deleted_by") == "uninstall-watcher"
        cp = row.get("collections_purged") or {}
        assert cp.get("managed_agents", 0) >= 1
        assert cp.get("sys_metrics_history", 0) >= 2
    finally:
        _cleanup_agent(mongo, agent_id)


# ---------- Edge: short elapsed (NOT completed yet) -------------------------

def test_progress_short_elapsed_not_completed(admin_headers, mongo):
    """uninstall_started_at solo 5s fa → progress floor 5%, ancora in_progress."""
    agent_id = f"TEST_iter82_short_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=5)
    try:
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        agents = r.json().get("agents", [])
        rec = next((a for a in agents if a.get("agent_id") == agent_id), None)
        assert rec is not None
        assert rec.get("uninstall_status") == "in_progress", \
            f"agent should still be in_progress at 5s, got {rec.get('uninstall_status')}"
        # progress clamp min = 5
        assert rec.get("uninstall_progress") == 5
        # uninstall_elapsed_sec presente
        assert rec.get("uninstall_elapsed_sec") is not None
    finally:
        _cleanup_agent(mongo, agent_id)


# ---------- Timeout (>3min fa, not live) -----------------------------------

def test_timeout_path_results_in_completion_when_not_live(admin_headers, mongo):
    """uninstall_started_at >3min fa, agent NOT live (no WS).
    Logica: not live + >30s ha priorità su timeout → autocompletato come
    success. Verifichiamo che la pulizia avvenga e audit sia 'completed'.
    """
    agent_id = f"TEST_iter82_tmout_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=200)
    try:
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        time.sleep(1.0)
        # Cleanup avvenuto
        assert mongo.managed_agents.count_documents({"agent_id": agent_id}) == 0
        # Audit con criteria uninstall-finalized e outcome completed
        audit = list(mongo.agent_cleanup_audit.find(
            {"deleted_ids": agent_id}).sort("deleted_at", -1).limit(1))
        assert audit and audit[0].get("outcome") == "completed"
    finally:
        _cleanup_agent(mongo, agent_id)


# ---------- DELETE on offline agent (should NOT track_progress) -------------

def test_delete_offline_no_tracking(admin_headers, mongo):
    """Agent senza WS connection: DELETE con uninstall_remote=true deve
    restituire uninstall_status='agent_offline' e cancellare subito i dati
    (track_progress=False quando comando NON inviato).
    """
    agent_id = f"TEST_iter82_offline_{uuid.uuid4().hex[:8]}"
    mongo.managed_agents.insert_one({
        "agent_id": agent_id,
        "hostname": "TEST_iter82_offhost",
        "client_id": "TEST_iter82_client",
        "agent_version": "v4.10.0-test",
    })
    try:
        r = requests.delete(
            f"{API}/agents/{agent_id}",
            params={"uninstall_remote": "true"},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # Offline path: deleted=True (sync purge), no tracking_uninstall
        assert body.get("deleted") is True
        assert body.get("tracking_uninstall") in (None, False), \
            f"offline agent should not enable tracking, got: {body}"
        assert body.get("uninstall_status") == "agent_offline"
        # And the doc must be gone
        assert mongo.managed_agents.count_documents({"agent_id": agent_id}) == 0
    finally:
        _cleanup_agent(mongo, agent_id)


# ---------- PS1 magic trigger ----------------------------------------------

def test_ps1_contains_magic_trigger_block():
    assert os.path.isfile(PS1_PATH), f"{PS1_PATH} missing"
    body = open(PS1_PATH, "r", encoding="utf-8").read()
    # Header comment present
    assert "MAGIC TRIGGER" in body
    assert '"__uninstall__"' in body or "'__uninstall__'" in body
    # Main check
    assert "if ($Version -eq \"__uninstall__\")" in body
    # Path to uninstall.ps1
    assert 'Join-Path $InstallDir "uninstall.ps1"' in body
    # Fallback inline must contain Stop-Service + sc.exe delete + Remove-Item
    assert "Stop-Service '86NocAgent'" in body
    assert "sc.exe delete '86NocAgent'" in body
    assert "Remove-Item -Path $InstallDir" in body
    assert "Remove-Item -Path \"$env:ProgramData\\86NocAgent\"" in body


# ---------- Method label is one of allowed values --------------------------

def test_uninstall_method_persisted_value(admin_headers, mongo):
    agent_id = f"TEST_iter82_method_{uuid.uuid4().hex[:8]}"
    _seed_agent_in_progress(mongo, agent_id, seconds_ago=8,
                            uninstall_method="native")
    try:
        r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        rec = next((a for a in r.json().get("agents", [])
                    if a.get("agent_id") == agent_id), None)
        assert rec is not None
        assert rec.get("uninstall_method") in ("native", "legacy_update")
    finally:
        _cleanup_agent(mongo, agent_id)
