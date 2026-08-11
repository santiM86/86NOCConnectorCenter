import asyncio
import random
from datetime import datetime, timezone, timedelta
from database import db

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "10.100.41.25"
NAME = "ZITASRV-ILO"


async def main():
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    await db.managed_devices.update_one(
        {"client_id": CLIENT_ID, "ip": IP},
        {"$set": {
            "client_id": CLIENT_ID, "ip": IP, "name": NAME,
            "device_type": "ilo", "vendor": "HPE", "model": "ProLiant ML350 Gen10",
            "updated_at": now_iso,
        }},
        upsert=True,
    )

    redfish = {
        "power_watts": 269,
        "bios_version": "U41 v3.66 (04/01/2026)",
        "server_model": "ProLiant ML350 Gen10",
        "serial_number": "MXQ0438J7M",
        "uuid": "35353036-3730-584D-5130-343338J7M00",
        "ilo_firmware": "iLO 5 v3.19",
        "ilo_license": "iLO Advanced",
        "total_memory_gb": 256,
        "power_state": "On",
        "indicator_led": "Off",
        "post_state": "FinishedPost",
        "processor_summary": {"count": 2, "model": "Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz", "cores": 40, "health": "OK"},
        "processors": [
            {"socket": "Proc 1", "model": "Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz", "cores": 20, "threads": 40, "speed_mhz": 2100, "health": "OK", "state": "Enabled"},
            {"socket": "Proc 2", "model": "Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz", "cores": 20, "threads": 40, "speed_mhz": 2100, "health": "OK", "state": "Enabled"},
        ],
        "memory_dimms": [
            {"name": f"PROC 1 DIMM {i}", "size_gb": 32, "speed_mhz": 2933, "type": "DDR4", "rank": 2, "manufacturer": "Samsung", "part_number": "M393A4K40CB2-CVF", "health": "OK"} for i in range(1, 5)
        ] + [
            {"name": f"PROC 2 DIMM {i}", "size_gb": 32, "speed_mhz": 2933, "type": "DDR4", "rank": 2, "manufacturer": "Samsung", "part_number": "M393A4K40CB2-CVF", "health": "OK"} for i in range(1, 5)
        ],
        "network_adapters": [
            {"name": "Ethernet 1 (LOM)", "mac": "48:DF:37:1A:2B:01", "speed_mbps": 1000, "status": "OK", "state": "Enabled", "link_status": "LinkUp", "ipv4": "10.100.41.25", "vlan": 41, "fqdn": None},
            {"name": "Ethernet 2 (LOM)", "mac": "48:DF:37:1A:2B:02", "speed_mbps": 10000, "status": "OK", "state": "Enabled", "link_status": "LinkUp", "ipv4": "10.100.61.34", "vlan": 61, "fqdn": None},
            {"name": "Ethernet 3", "mac": "48:DF:37:1A:2B:03", "speed_mbps": None, "status": "OK", "state": "Disabled", "link_status": "LinkDown", "ipv4": None, "vlan": None, "fqdn": None},
        ],
        "storage_controllers": [
            {"name": "HPE Smart Array P408i-a SR Gen10", "firmware": "3.53", "status": "OK", "health": "ok",
             "logical_drives": [
                {"name": "LogicalDrive 1 (OS)", "capacity_gb": 2400, "raid": "RAID5", "status": "OK"},
                {"name": "LogicalDrive 2 (DATA)", "capacity_gb": 480, "raid": "RAID1", "status": "OK"},
             ],
             "drives": [
                {"slot": 1, "model": "EG001200JWJNQ", "serial": "S4H0A", "capacity_gb": 1200, "media_type": "HDD", "interface_type": "SAS", "health": "ok", "state": "Enabled", "failure_predicted": False, "rotation_rpm": 10000, "hours_used": 21440, "temp_celsius": 34, "wear_percent": None},
                {"slot": 2, "model": "EG001200JWJNQ", "serial": "S4H0B", "capacity_gb": 1200, "media_type": "HDD", "interface_type": "SAS", "health": "ok", "state": "Enabled", "failure_predicted": False, "rotation_rpm": 10000, "hours_used": 21440, "temp_celsius": 35, "wear_percent": None},
                {"slot": 3, "model": "EG001200JWJNQ", "serial": "S4H0C", "capacity_gb": 1200, "media_type": "HDD", "interface_type": "SAS", "health": "warning", "state": "Enabled", "failure_predicted": True, "rotation_rpm": 10000, "hours_used": 42100, "temp_celsius": 41, "wear_percent": None},
                {"slot": 4, "model": "VO000480JWZJT", "serial": "S4H0D", "capacity_gb": 480, "media_type": "SSD", "interface_type": "SATA", "health": "ok", "state": "Enabled", "failure_predicted": False, "rotation_rpm": None, "hours_used": 15000, "temp_celsius": 28, "wear_percent": 12},
                {"slot": 5, "model": "VO000480JWZJT", "serial": "S4H0E", "capacity_gb": 480, "media_type": "SSD", "interface_type": "SATA", "health": "ok", "state": "Enabled", "failure_predicted": False, "rotation_rpm": None, "hours_used": 15000, "temp_celsius": 29, "wear_percent": 74},
                {"slot": 6, "model": "VO000480JWZJT", "serial": "S4H0F", "capacity_gb": 480, "media_type": "SSD", "interface_type": "SATA", "health": "ok", "state": "Enabled", "failure_predicted": False, "rotation_rpm": None, "hours_used": 15000, "temp_celsius": 30, "wear_percent": 93},
             ]},
        ],
    }
    hardware = {
        "health_status": "ok",
        "temperatures": [
            {"locale": "01-Inlet Ambient", "value": 15, "condition": "OK"},
            {"locale": "04-P1 DIMM 1-6", "value": 39, "condition": "OK"},
            {"locale": "53-CPU 1 PkgTmp", "value": 58, "condition": "OK"},
            {"locale": "15-VR P1", "value": 57, "condition": "OK"},
            {"locale": "02-BMC Zone", "value": 45, "condition": "OK"},
        ],
        "fans": [
            {"locale": f"Fan {i}", "speed": 7 + i, "condition": "OK"} for i in range(1, 7)
        ],
        "power_supplies": [
            {"name": "PSU 1", "watts": 500, "model": "865414-B21", "condition": "OK", "health": "OK"},
            {"name": "PSU 2", "watts": 500, "model": "865414-B21", "condition": "OK", "health": "OK"},
        ],
    }

    await db.device_poll_status.update_one(
        {"device_ip": IP},
        {"$set": {
            "device_ip": IP, "device_name": NAME, "client_id": CLIENT_ID,
            "reachable": True, "monitor_type": "redfish_direct", "device_class": "hpe-ilo",
            "device_type": "ilo", "redfish": redfish, "hardware": hardware,
            "last_poll": now_iso, "updated_at": now_iso,
        }},
        upsert=True,
    )

    # Telemetria storica per grafici (ultime 6h, 1 punto ogni 10 min)
    await db.ilo_telemetry.delete_many({"device_ip": IP})
    docs = []
    for k in range(36, -1, -1):
        ts = now - timedelta(minutes=10 * k)
        base_power = 260 + random.randint(-15, 25)
        max_temp = 55 + random.randint(-4, 8)
        docs.append({
            "client_id": CLIENT_ID, "device_ip": IP, "device_name": NAME,
            "source": "REDFISH_DIRECT", "timestamp": ts,
            "power_watts": base_power, "health_status": "ok",
            "temperatures": [
                {"name": "01-Inlet Ambient", "celsius": 14 + random.randint(0, 3), "health": "OK"},
                {"name": "53-CPU 1 PkgTmp", "celsius": max_temp, "health": "OK"},
                {"name": "15-VR P1", "celsius": max_temp - 2, "health": "OK"},
            ],
            "fans": [{"name": f"Fan {i}", "rpm_percent": 7 + i, "health": "OK"} for i in range(1, 7)],
            "power_supplies": hardware["power_supplies"],
        })
    if docs:
        await db.ilo_telemetry.insert_many(docs)

    print(f"Seed iLO OK: {NAME} ({IP}) su client {CLIENT_ID}, {len(docs)} snapshot telemetria")


if __name__ == "__main__":
    asyncio.run(main())
