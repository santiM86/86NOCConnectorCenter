"""Regression test: /api/device-profiles deve sopravvivere a override
corrotti in DB invece di andare in 500 (problema segnalato in PROD).
"""
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
from database import db  # noqa: E402

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")


async def test_device_profiles_survives_corrupt_overrides():
    """Inject 4 documenti patologici in device_profile_overrides:
    - overrides=string (non dict)
    - overrides=None
    - doc senza campo `key`
    - override valido su un profilo reale (hpe_ilo)
    Verifica che l'endpoint risponda 200 con tutti i seed profile + applichi
    correttamente l'override valido. NO 500.
    """
    test_keys = ["__PYTEST_BAD_STRING__", "__PYTEST_BAD_NONE__"]
    try:
        # Setup patologico
        for k, ov in [
            (test_keys[0], "not-a-dict-but-a-string"),
            (test_keys[1], None),
        ]:
            await db.device_profile_overrides.update_one(
                {"key": k}, {"$set": {"key": k, "overrides": ov}}, upsert=True
            )
        # doc senza key
        await db.device_profile_overrides.update_one(
            {"_pytest_no_key": True},
            {"$set": {"_pytest_no_key": True, "overrides": {"a": 1}}},
            upsert=True
        )
        # override valido
        await db.device_profile_overrides.update_one(
            {"key": "hpe_ilo"},
            {"$set": {"key": "hpe_ilo",
                      "overrides": {"polling_interval_seconds": 42}}},
            upsert=True
        )

        async with httpx.AsyncClient(timeout=20) as ac:
            r = await ac.post(f"{API_URL}/api/auth/login",
                              json={"email": "info@86bit.it",
                                    "password": "Ariel17051986@!@86"})
            token = r.json()["token"]
            resp = await ac.get(f"{API_URL}/api/device-profiles",
                                headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200, \
                f"Atteso 200 nonostante override corrotti, got {resp.status_code}: {resp.text[:200]}"
            body = resp.json()
            assert body["count"] > 0, "Lista profili vuota — regressione"
            assert isinstance(body.get("errors"), list), "Campo errors[] mancante"
            # Override valido applicato
            ilo = next((p for p in body["profiles"] if p["key"] == "hpe_ilo"), None)
            assert ilo is not None, "hpe_ilo non trovato"
            assert ilo.get("polling_interval_seconds") == 42, \
                f"Override hpe_ilo non applicato: {ilo.get('polling_interval_seconds')}"
            assert ilo.get("_has_overrides") is True
            print(f"✅ /api/device-profiles HTTP 200 con {body['count']} profili "
                  f"nonostante 3 override corrotti")
    finally:
        # Cleanup
        await db.device_profile_overrides.delete_many(
            {"key": {"$in": test_keys}})
        await db.device_profile_overrides.delete_many({"_pytest_no_key": True})
        await db.device_profile_overrides.delete_one({"key": "hpe_ilo"})


if __name__ == "__main__":
    asyncio.run(test_device_profiles_survives_corrupt_overrides())
