"""Match Uplink Esteso: switch HPE che NON annunciano local_chassis_id e con
remote_ip di altra subnet + chassis-id non risolvibile -> collegabili SOLO via
reciprocita' FDB (base-MAC imparato reciprocamente). Catena B<->A, B<->C.
Client di test: da3d6e40-b3e5-4d46-9787-dde328a3aa36"""
import asyncio
from datetime import datetime, timezone
from database import db

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
now = datetime.now(timezone.utc).isoformat()

# (name, mgmt_ip, primary_mac)
SW = [
    ("FDBSW-A", "10.10.42.221", "aaaa00000011"),
    ("FDBSW-B", "10.10.42.220", "bbbb00000012"),
    ("FDBSW-C", "10.10.42.222", "cccc00000013"),
]


async def main():
    base = {"client_id": CID}
    ips = [s[1] for s in SW]
    await db.managed_devices.delete_many({**base, "ip": {"$in": ips}})
    await db.device_poll_status.delete_many({**base, "device_ip": {"$in": ips}})
    await db.lldp_neighbors.delete_many({**base, "local_ip": {"$in": ips}})
    await db.discovered_endpoints.delete_many({**base, "switch_ip": {"$in": ips}})

    mac = {s[1]: s[2] for s in SW}
    for name, ip, pmac in SW:
        await db.managed_devices.insert_one({**base, "ip": ip, "name": name,
            "device_name": name, "device_type": "switch", "updated_at": now})
        await db.device_poll_status.insert_one({**base, "device_ip": ip,
            "device_name": name, "primary_mac": pmac, "device_type": "switch",
            "reachable": True, "last_poll": now, "updated_at": now})

    lldp = []

    def nb(local_ip, local_port, remote_ip, remote_port):
        # NIENTE local_chassis_id, remote_ip di altra subnet, chassis-id garbage,
        # sys_name generico => NON risolvibile con i metodi standard.
        lldp.append({**base, "local_ip": local_ip,
            "local_port_id": local_port, "local_port_desc": local_port,
            "remote_ip": remote_ip, "remote_chassis_id": "ffff.ffff.dead",
            "remote_sys_name": "HPE", "remote_port_id": remote_port,
            "remote_port_desc": remote_port, "updated_at": now})

    nb("10.10.42.220", "Ten-GigabitEthernet1/0/25", "192.168.201.4", "Ten-GigabitEthernet1/0/50")
    nb("10.10.42.221", "Ten-GigabitEthernet1/0/50", "192.168.88.30", "Ten-GigabitEthernet1/0/25")
    nb("10.10.42.220", "Ten-GigabitEthernet1/0/26", "192.168.88.31", "Ten-GigabitEthernet1/0/25")
    nb("10.10.42.222", "Ten-GigabitEthernet1/0/25", "192.168.88.32", "Ten-GigabitEthernet1/0/26")
    await db.lldp_neighbors.insert_many(lldp)

    # FDB reciproca: A e B si sono imparati; B e C si sono imparati. A NON impara C.
    fdb = []
    for a, learned_mac, vlan in [
        ("10.10.42.220", mac["10.10.42.221"], 10),  # B ha A
        ("10.10.42.221", mac["10.10.42.220"], 10),  # A ha B
        ("10.10.42.220", mac["10.10.42.222"], 10),  # B ha C
        ("10.10.42.222", mac["10.10.42.220"], 10),  # C ha B
    ]:
        fdb.append({**base, "switch_ip": a, "mac": learned_mac, "vlan": vlan,
                    "source": "agent_fdb", "updated_at": now})
    await db.discovered_endpoints.insert_many(fdb)
    print(f"Seed FDB-match OK: {len(lldp)} LLDP (no chassis), {len(fdb)} FDB su {ips}")


if __name__ == "__main__":
    asyncio.run(main())
