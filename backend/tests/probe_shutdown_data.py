import os, asyncio
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def m():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    d = await db.discovered_endpoints.find_one({'switch_ip': {'$exists': True}}, {'_id': 0})
    print('EP keys', sorted(d.keys()) if d else None)
    print({k: d.get(k) for k in ['ip', 'mac', 'switch_ip', 'switch_port', 'port_idx', 'port_name', 'last_seen', 'first_seen', 'last_seen_via']} if d else None)
    sp = await db.switch_ports.find_one({}, {'_id': 0}); print('SWITCH_PORTS keys', sorted(sp.keys()) if sp else None)
    for c in ['port_events', 'switch_port_events', 'device_status_history', 'status_history', 'device_state_events', 'liveness_events', 'device_metrics_history', 'metric_history']:
        print(c, await db[c].count_documents({}))
    md = await db.managed_devices.find_one({'datto_uid': {'$nin': [None, '']}}, {'_id': 0})
    print('MD datto keys', {k: v for k, v in (md or {}).items() if 'datto' in k})
    print('ALERT types', await db.alerts.distinct('alert_type'))
    a = await db.alerts.find_one({'alert_type': {'$regex': 'offline|down|unreach'}}, {'_id': 0})
    print('ALERT sample', {k: a.get(k) for k in ['alert_type', 'device_ip', 'client_id', 'created_at', 'resolved_at', 'status', 'source_type']} if a else None)
    ps = await db.device_poll_status.find_one({}, {'_id': 0})
    print('POLL keys', sorted(ps.keys()) if ps else None)

asyncio.run(m())
