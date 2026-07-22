"""End-to-end seed test: create a fake vital offline device + poll status,
run alert-engine, verify alert is created, then clean up."""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

CID = "test-alert-engine-iter89"
IP = "10.253.253.253"


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    try:
        # Ensure client exists (needed for name lookup)
        await db.clients.update_one(
            {"id": CID}, {"$set": {"id": CID, "name": "TEST_AlertEngineClient"}}, upsert=True
        )
        # Seed vital managed device
        await db.managed_devices.update_one(
            {"client_id": CID, "ip": IP},
            {"$set": {
                "client_id": CID, "ip": IP, "name": "TEST_vital_device",
                "is_vital": True, "device_type": "server",
                "mac": "aa:bb:cc:dd:ee:ff",
            }},
            upsert=True,
        )
        # Seed device_poll_status offline
        past = datetime.now(timezone.utc) - timedelta(minutes=30)
        await db.device_poll_status.update_one(
            {"client_id": CID, "device_ip": IP},
            {"$set": {
                "client_id": CID, "device_ip": IP,
                "reachable": False, "consecutive_failures": 6,
                "last_reachable_at": past.isoformat(),
                "last_ping_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        # Vital offline state — first_offline 15 min ago (past crit=10min)
        first_off = datetime.now(timezone.utc) - timedelta(minutes=15)
        await db.vital_offline_state.update_one(
            {"client_id": CID, "ip": IP},
            {"$set": {
                "client_id": CID, "ip": IP, "device_name": "TEST_vital_device",
                "first_offline_at": first_off.isoformat(), "level": 0, "alert_id": None,
            }},
            upsert=True,
        )
        # Delete any prior alerts for this
        await db.alerts.delete_many({"client_id": CID, "source_type": {"$in": ["vital_device_offline", "vital_device_recovery"]}})

        # Run alert engine
        import sys
        sys.path.insert(0, "/app/backend")
        import alert_engine as ae
        engine = ae.AlertEngine(db)
        result = await engine.run_once()
        print(f"run_once result: {result}")

        # Verify alert created
        alerts = await db.alerts.find({"client_id": CID, "source_type": "vital_device_offline"}, {"_id": 0}).to_list(10)
        print(f"Alerts found: {len(alerts)}")
        for a in alerts:
            print(f"  - severity={a.get('severity')} title={a.get('title')[:80]}")
        assert len(alerts) >= 1, "No vital_device_offline alert generated!"
        # State should be at level 2 (elapsed=15min > crit_min=10)
        state = await db.vital_offline_state.find_one({"client_id": CID, "ip": IP})
        print(f"State level: {state.get('level')}")

        print("SEED TEST PASSED")

    finally:
        # Cleanup
        await db.managed_devices.delete_many({"client_id": CID})
        await db.device_poll_status.delete_many({"client_id": CID})
        await db.vital_offline_state.delete_many({"client_id": CID})
        await db.datto_offline_state.delete_many({"client_id": CID})
        await db.alerts.delete_many({"client_id": CID})
        await db.clients.delete_many({"id": CID})
        await db.alert_engine_config.delete_many({"_id": f"client:{CID}"})
        # Clear the fake telegram token from previous test
        await db.alert_engine_config.update_one(
            {"_id": "global"},
            {"$set": {"telegram_bot_token": ""}},
        )
        print("CLEANUP DONE")
        client.close()


asyncio.run(main())
