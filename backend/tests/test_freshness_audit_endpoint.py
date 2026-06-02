"""Smoke test endpoint /api/admin/freshness-audit."""
import os
import sys
import asyncio
import pathlib

ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")


async def test_endpoint_admin_only_and_shape():
    async with httpx.AsyncClient(timeout=20) as ac:
        # Login admin
        r = await ac.post(f"{API_URL}/api/auth/login",
                          json={"email": "info@86bit.it",
                                "password": "Ariel17051986@!@86"})
        assert r.status_code == 200
        token = r.json()["token"]

        # Chiamata senza token: 401/403
        r0 = await ac.get(f"{API_URL}/api/admin/freshness-audit")
        assert r0.status_code in (401, 403), f"Atteso 401/403, got {r0.status_code}"

        # Chiamata admin: 200
        r1 = await ac.get(f"{API_URL}/api/admin/freshness-audit",
                          headers={"Authorization": f"Bearer {token}"})
        assert r1.status_code == 200
        body = r1.json()

        # Schema atteso
        assert "audited_at" in body
        assert body["overall_status"] in ("ok", "warning", "critical")
        assert "thresholds_seconds" in body
        assert isinstance(body["pipelines"], list)
        assert isinstance(body["per_client"], list)

        # Pipeline minime presenti
        names = {p["name"] for p in body["pipelines"]}
        for required in ("agent_heartbeat", "snmp_poll", "icmp_reachable",
                         "wan_probe", "discovery_seen", "lan_scan",
                         "connector_legacy"):
            assert required in names, f"Pipeline {required} mancante"

        # Ogni pipeline ha i campi obbligatori
        for p in body["pipelines"]:
            for k in ("name", "description", "collection", "field",
                      "threshold_seconds", "total", "fresh", "stale",
                      "no_timestamp", "status"):
                assert k in p, f"Campo {k} mancante in pipeline {p.get('name')}"

        print(f"✅ /api/admin/freshness-audit OK, overall={body['overall_status']}, "
              f"{len(body['pipelines'])} pipelines, {len(body['per_client'])} clients")


if __name__ == "__main__":
    asyncio.run(test_endpoint_admin_only_and_shape())
