import asyncio
from datetime import datetime, timezone
from database import db

CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
FW = {"ip": "10.10.41.1", "name": "FORTIGATE-FW", "mac": "001122330000", "type": "firewall"}
SW = [
    {"ip": "10.10.41.221", "name": "SWITCH01", "mac": "001122330001"},
    {"ip": "10.10.41.222", "name": "SWITCH03", "mac": "001122330003"},
    {"ip": "10.10.41.228", "name": "SWITCH02", "mac": "001122330002"},
]
# Catena: FW -> SW01 -> SW03 -> SW02
CHAIN = [
    {"a": FW, "b": SW[0], "a_port": "wan1", "b_port": "Gi1/0/1", "gw": True},
    {"a": SW[0], "b": SW[1], "a_port": "Gi1/0/24", "b_port": "Gi1/0/1", "gw": False},
    {"a": SW[1], "b": SW[2], "a_port": "Gi1/0/24", "b_port": "Gi1/0/1", "gw": False},
]


async def main():
    now = datetime.now(timezone.utc).isoformat()
    base = {"client_id": CLIENT_ID}

    # Pulizia precedente seed cascata
    ips = [FW["ip"]] + [s["ip"] for s in SW]
    await db.lldp_neighbors.delete_many({**base, "local_ip": {"$in": ips}})
    await db.discovered_endpoints.delete_many({**base, "switch_ip": {"$in": [s["ip"] for s in SW]}, "source": "agent_fdb"})

    # managed_devices + device_poll_status
    for d in [FW] + SW:
        await db.managed_devices.update_one(
            {**base, "ip": d["ip"]},
            {"$set": {**base, "ip": d["ip"], "hostname": d["name"], "name": d["name"],
                      "device_type": d.get("type", "switch"), "updated_at": now}},
            upsert=True,
        )
        await db.device_poll_status.update_one(
            {**base, "device_ip": d["ip"]},
            {"$set": {**base, "device_ip": d["ip"], "device_name": d["name"],
                      "primary_mac": d["mac"], "reachable": True, "updated_at": now}},
            upsert=True,
        )

    # LLDP bidirezionale per ogni link della catena
    def lldp(a, b, ap, bp):
        return {**base, "local_ip": a["ip"], "local_port_id": ap, "local_port_desc": ap,
                "remote_ip": b["ip"], "remote_sys_name": b["name"],
                "remote_chassis_id": b["mac"], "remote_port_id": bp, "remote_port_desc": bp,
                "updated_at": now}

    lldp_docs = []
    for link in CHAIN:
        lldp_docs.append(lldp(link["a"], link["b"], link["a_port"], link["b_port"]))
        lldp_docs.append(lldp(link["b"], link["a"], link["b_port"], link["a_port"]))
    await db.lldp_neighbors.insert_many(lldp_docs)

    # FDB (discovered_endpoints agent_fdb): il MAC base di ogni switch compare nella
    # FDB del vicino -> link VERIFICATO. Aggiungo anche endpoint fittizi per il conteggio.
    fdb_docs = []
    for link in CHAIN:
        if link["gw"]:
            continue
        a, b = link["a"], link["b"]
        fdb_docs.append({**base, "switch_ip": a["ip"], "mac": b["mac"], "vlan": 1, "source": "agent_fdb"})
        fdb_docs.append({**base, "switch_ip": b["ip"], "mac": a["mac"], "vlan": 1, "source": "agent_fdb"})
    # endpoint fittizi
    for i, s in enumerate(SW):
        for j in range(3 + i):
            fdb_docs.append({**base, "switch_ip": s["ip"], "mac": f"aabbcc0{i}00{j:02d}", "vlan": 1, "source": "agent_fdb"})
    await db.discovered_endpoints.insert_many(fdb_docs)

    print(f"Seed cascata OK: FW->{SW[0]['name']}->{SW[1]['name']}->{SW[2]['name']} | {len(lldp_docs)} LLDP, {len(fdb_docs)} FDB")


if __name__ == "__main__":
    asyncio.run(main())
