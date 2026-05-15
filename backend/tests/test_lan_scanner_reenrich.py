"""Test reale flow re-enrich → managed_devices.

Crea un finto lan_scan_run + un finto managed_device con name=IP nudo,
chiama l'endpoint e verifica che il device venga effettivamente
aggiornato. Cleanup automatico a fine test.
"""
import asyncio
import uuid
from datetime import datetime, timezone


async def main():
    from database import db

    # Setup: cliente fittizio
    test_client_id = "test-reenrich-" + uuid.uuid4().hex[:8]
    test_scan_id = uuid.uuid4().hex
    test_ip = "10.99.99.55"

    await db.clients.insert_one({
        "id": test_client_id,
        "name": "TEST RE-ENRICH",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Finto scan con risultati ricchi
    await db.lan_scan_runs.insert_one({
        "scan_id": test_scan_id,
        "agent_id": "test-agent",
        "client_id": test_client_id,
        "cidr": "10.99.99.0/24",
        "status": "done",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "progress": {"done": 254, "total": 254, "found": 1},
        "results": [{
            "ip": test_ip,
            "mac": "00:11:32:aa:bb:cc",
            "hostname": "SYNO-NAS-01",
            "vendor": "Synology",
            "status": "alive",
            "rtt_ms": 1,
            "mdns_name": "Syno-Office",
            "services": ["_smb._tcp", "_http._tcp"],
            "http_server": "nginx Synology DSM 7.2",
            "device_name": "Hardware Manufacturer/Synology",
            "device_score": 35,
        }],
    })

    # Finto managed_device importato MALE (name=IP nudo)
    test_device_id = uuid.uuid4().hex
    await db.managed_devices.insert_one({
        "id": test_device_id,
        "client_id": test_client_id,
        "ip": test_ip,
        "name": test_ip,  # <-- BUG da fixare
        "monitor_type": "ping",
        "device_type": "generic",
        "community": "public",
    })

    print(f"[SETUP] client={test_client_id} scan={test_scan_id} device.name={test_ip}")

    # Chiama l'endpoint via funzione direttamente (no auth richiesta a livello servizio)
    from routes.lan_scanner import re_enrich_client_devices

    # Mock user (Depends su get_current_user, ma chiamiamo la funzione direttamente)
    class FakeUser(dict):
        pass

    user = {"email": "test@86bit.it", "id": "test-user"}
    result = await re_enrich_client_devices(test_client_id, user)
    print(f"[ENDPOINT RESPONSE] {result}")

    # Verifica DB post-update
    after = await db.managed_devices.find_one(
        {"id": test_device_id}, {"_id": 0}
    )
    print(f"[DB AFTER] name={after.get('name')!r}, vendor={after.get('vendor')!r}, "
          f"mdns_name={after.get('mdns_name')!r}, http_server={after.get('http_server')!r}, "
          f"fingerbank={after.get('fingerbank_device_name')!r}, "
          f"notes={after.get('notes')!r}")

    # Verifica espliciti
    assert after["name"] == "SYNO-NAS-01", f"name not updated: {after['name']}"
    assert after["vendor"] == "Synology", f"vendor not set: {after['vendor']}"
    assert after["mdns_name"] == "Syno-Office", f"mdns missing: {after['mdns_name']}"
    assert "Synology DSM" in after["http_server"], f"http banner missing"
    assert "_smb._tcp" in after["mdns_services"], f"services missing"
    assert "Synology" in after["notes"], f"notes missing"
    print("[OK] tutti gli assert passati")

    # CASE 2: name manuale NON deve essere sovrascritto
    test_device_id_2 = uuid.uuid4().hex
    test_ip_2 = "10.99.99.56"
    await db.managed_devices.insert_one({
        "id": test_device_id_2,
        "client_id": test_client_id,
        "ip": test_ip_2,
        "name": "Nome scelto a mano",  # <-- non IP, deve essere preservato
        "monitor_type": "ping",
    })
    await db.lan_scan_runs.update_one(
        {"scan_id": test_scan_id},
        {"$push": {"results": {
            "ip": test_ip_2, "hostname": "AUTODETECTED",
            "vendor": "TestVendor", "status": "alive", "rtt_ms": 1,
        }}},
    )
    result2 = await re_enrich_client_devices(test_client_id, user)
    print(f"[ENDPOINT 2 RESPONSE] {result2}")
    after2 = await db.managed_devices.find_one({"id": test_device_id_2}, {"_id": 0})
    print(f"[DB AFTER 2] name={after2.get('name')!r}, vendor={after2.get('vendor')!r}")
    assert after2["name"] == "Nome scelto a mano", f"manuale sovrascritto: {after2['name']}"
    assert after2["vendor"] == "TestVendor"
    print("[OK] nome manuale preservato")

    # CLEANUP
    await db.clients.delete_one({"id": test_client_id})
    await db.lan_scan_runs.delete_one({"scan_id": test_scan_id})
    await db.managed_devices.delete_many({"client_id": test_client_id})
    print("[CLEANUP] done")


if __name__ == "__main__":
    asyncio.run(main())
