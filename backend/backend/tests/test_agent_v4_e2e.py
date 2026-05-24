"""Smoke test: connect 86NocAgent v4 to backend, verify hello/welcome/heartbeat
and that managed_agents is populated. Run from /app:

    python backend/tests/test_agent_v4_e2e.py
"""
import asyncio
import os
import secrets
import subprocess
import sys
import time
import json
from pathlib import Path

import pymongo

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
AGENT_BIN = "/app/noc-agent/build/bin/nocagent"
BACKEND_WS = "ws://localhost:8001/api/agent/ws"
CLIENT_ID = "smoke-test-client"


def main() -> int:
    cli = pymongo.MongoClient(MONGO_URL)
    db = cli[DB_NAME]

    # 1. Provision a token
    token = "smoke-" + secrets.token_urlsafe(16)
    db.agent_tokens.delete_many({"client_id": CLIENT_ID})
    db.agent_tokens.insert_one(
        {"token": token, "client_id": CLIENT_ID, "label": "smoke", "revoked": False}
    )
    db.managed_agents.delete_many({"client_id": CLIENT_ID})

    # 2. Build a minimal agent.yaml
    cfg_path = Path("/tmp/agent_smoke.yaml")
    cfg_path.write_text(
        f"""
client_id: "{CLIENT_ID}"
token: "{token}"
backend:
  url: "{BACKEND_WS}"
heartbeat: 3s
discovery:
  enabled: true
  interval: 30s
  arp: true
  mdns: false
snmp:
  enabled: false
watchdog:
  enabled: false
update:
  enabled: false
""".strip()
    )

    # 3. Spawn the agent
    env = dict(os.environ)
    proc = subprocess.Popen(
        [AGENT_BIN, "--config", str(cfg_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    print(f"[smoke] agent pid={proc.pid}")

    # 4. Wait up to 20s for hello + heartbeat
    deadline = time.time() + 20
    ok = False
    while time.time() < deadline:
        doc = db.managed_agents.find_one({"client_id": CLIENT_ID})
        if doc and doc.get("connected") and doc.get("last_heartbeat_at"):
            ok = True
            print("[smoke] managed_agents populated:")
            print(json.dumps({k: v for k, v in doc.items() if k != "_id"}, indent=2, default=str))
            break
        time.sleep(0.5)

    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    print("[smoke] agent stderr/stdout (tail):")
    print("\n".join(out.splitlines()[-25:]))

    # 5. Cleanup
    db.agent_tokens.delete_many({"client_id": CLIENT_ID})

    if not ok:
        print("[smoke] FAIL: agent never registered + heartbeated")
        return 1
    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
