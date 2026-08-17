"""Riproduce il bug uplink non rilevati: peer LLDP con mgmt-IP di altra subnet e
chassis-id diverso dal primary_mac -> risolvibile solo via local_chassis_id.
Client di test: da3d6e40-b3e5-4d46-9787-dde328a3aa36"""
import asyncio
from datetime import datetime, timezone
from database import db

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
now = datetime.now(timezone.utc).isoformat()

# (name, mgmt_ip, primary_mac, chassis annunciato via LLDP - DIVERSO dal primary)
SW = [
    ("CHASW-A", "10.10.41.221", "aaaa00000001", "dddd00000001"),
    ("CHASW-B", "10.10.41.220", "bbbb00000002", "dddd00000002"),
    ("CHASW-C", "10.10.41.222", "cccc00000003", "dddd00000003"),
]


async def main():
    base = {"client_id": CID}
    ips = [s[1] for s in SW]
    await db.managed_devices.delete_many({**base, "ip": {"$in": ips}})
    await db.device_poll_status.delete_many({**base, "device_ip": {"$in": ips}})
    await db.lldp_neighbors.delete_many({**base, "local_ip": {"$in": ips}})
    await db.discovered_endpoints.delete_many({**base, "switch_ip": {"$in": ips}})

    for name, ip, pmac, _ in SW:
        await db.managed_devices.insert_one({**base, "ip": ip, "name": name,
            "device_name": name, "device_type": "switch", "updated_at": now})
        await db.device_poll_status.insert_one({**base, "device_ip": ip,
            "device_name": name, "primary_mac": pmac, "device_type": "switch",
            "reachable": True, "last_poll": now, "updated_at": now})

    ch = {s[1]: s[3] for s in SW}  # ip -> chassis annunciato
    lldp = []

    def nb(local_ip, local_port, remote_ip, remote_chassis, remote_port, remote_name):
        lldp.append({**base, "local_ip": local_ip, "local_chassis_id": ch[local_ip],
            "local_port_id": local_port, "local_port_desc": local_port,
            "remote_ip": remote_ip, "remote_chassis_id": remote_chassis,
            "remote_sys_name": remote_name, "remote_port_id": remote_port,
            "remote_port_desc": remote_port, "updated_at": now})

    # B<->A: B vede A con IP di ALTRA subnet e chassis annunciato di A
    nb("10.10.41.220", "Ten-GigabitEthernet1/0/25", "192.168.101.4", ch["10.10.41.221"],
       "Ten-GigabitEthernet1/0/50", "HPE")
    nb("10.10.41.221", "Ten-GigabitEthernet1/0/50", "192.168.88.20", ch["10.10.41.220"],
       "Ten-GigabitEthernet1/0/25", "HPE")
    # B<->C
    nb("10.10.41.220", "Ten-GigabitEthernet1/0/26", "192.168.88.9", ch["10.10.41.222"],
       "Ten-GigabitEthernet1/0/25", "HPE")
    nb("10.10.41.222", "Ten-GigabitEthernet1/0/25", "192.168.88.21", ch["10.10.41.220"],
       "Ten-GigabitEthernet1/0/26", "HPE")
    await db.lldp_neighbors.insert_many(lldp)

    # FDB per verifica: il primary_mac di ciascuno compare nella FDB del vicino
    fdb = []
    for a, bmac, vlan in [("10.10.41.220", "aaaa00000001", 10), ("10.10.41.221", "bbbb00000002", 10),
                          ("10.10.41.220", "cccc00000003", 10), ("10.10.41.222", "bbbb00000002", 10)]:
        fdb.append({**base, "switch_ip": a, "mac": bmac, "vlan": vlan,
                    "source": "agent_fdb", "updated_at": now})
    await db.discovered_endpoints.insert_many(fdb)
    print(f"Seed chassis-match OK: {len(lldp)} LLDP, {len(fdb)} FDB su {ips}")


if __name__ == "__main__":
    asyncio.run(main())
