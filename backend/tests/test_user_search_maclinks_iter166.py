# Iter166: 'Cerca utente' (/api/datto/user-search) + 'Collega MAC virtuali' (datto_mac_links)
import os, asyncio, pytest, requests, pyotp
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')
BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
CID = 'da3d6e40-b3e5-4d46-9787-dde328a3aa36'
SW_IP = '10.10.1.2'
VMAC = '00:15:5D:99:99:01'
VMAC2 = '00:15:5D:99:99:02'


def _db():
    return AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]


def run(coro_fn):
    async def w():
        return await coro_fn(_db())
    return asyncio.get_event_loop().run_until_complete(w()) if False else asyncio.run(w())


@pytest.fixture(scope='module')
def token():
    tf = '/tmp/argus_tok'
    if os.path.exists(tf):
        t = open(tf).read().strip()
        if requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 200:
            return t
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    t = r.json()['token']
    r2 = requests.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP('NMHDJNO53WLTOSREUXWERE6FDH5TAKC3').now()},
                       headers={"Authorization": f"Bearer {t}"})
    assert r2.status_code == 200, r2.text
    t = r2.json()['token']
    open(tf, 'w').write(t)
    return t


@pytest.fixture(scope='module')
def H(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope='module')
def seed():
    async def up(db):
        await db.managed_devices.insert_one({"id": "TEST_sw_iter166", "client_id": CID, "name": "TEST_SW_CORE", "ip": SW_IP,
                                             "ip_address": SW_IP, "device_type": "switch"})
        await db.discovered_endpoints.insert_one({"TEST_iter166": True, "client_id": CID, "mac": "00:15:5D:01:79:0D", "ip": "10.10.1.10",
                                                  "switch_ip": SW_IP, "port": 7, "last_seen_at": "2030-01-01T00:00:00+00:00"})
        await db.port_memory.insert_one({"TEST_iter166": True, "client_id": CID, "local_ip": SW_IP, "idx": 7, "name": "TEST_Gi1/0/7"})
    run(up)
    yield
    async def down(db):
        await db.managed_devices.delete_many({"id": "TEST_sw_iter166"})
        await db.discovered_endpoints.delete_many({"TEST_iter166": True})
        await db.port_memory.delete_many({"TEST_iter166": True})
        await db.datto_mac_links.delete_many({"mac": {"$in": [VMAC, VMAC2]}})
    run(down)


# --- user-search
def test_user_search_unauth():
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "admin"})
    assert r.status_code in (401, 403)


def test_user_search_short(H):
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "a"}, headers=H)
    assert r.status_code == 400


def test_user_search_structure(H):
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "administrator"}, headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d['query'] == 'administrator' and len(d['results']) > 0
    for x in d['results']:
        for k in ('client_id', 'client_name', 'pc_name', 'pc_ip', 'online', 'user', 'location'):
            assert k in x
        assert 'administrator' in x['user'].lower()


def test_user_search_only_existing_clients(H):
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "administrator"}, headers=H)
    async def ids(db):
        return set(await db.clients.distinct('id'))
    existing = run(ids)
    orphans = [x for x in r.json()['results'] if x['client_id'] not in existing]
    assert not orphans, f"results for non-existent clients: {[(o['client_id'], o['pc_name']) for o in orphans]}"


def test_user_search_location(H, seed):
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "SRVDATI86B"}, headers=H)
    assert r.status_code == 200
    res = [x for x in r.json()['results'] if x['pc_name'] == 'SRVDATI86B']
    assert res, r.json()
    loc = res[0]['location']
    assert loc and loc['switch_ip'] == SW_IP and loc['port'] == 7
    assert loc['switch_name'] == 'TEST_SW_CORE' and loc['port_name'] == 'TEST_Gi1/0/7'


def test_user_search_location_lowercase_mac(H, seed):
    # scanner endpoints often store lowercase MACs -> should still be located by MAC (different IP to isolate mac match)
    async def up(db):
        await db.discovered_endpoints.update_many({"TEST_iter166": True}, {"$set": {"mac": "00:15:5d:01:79:0d", "ip": "10.99.99.99"}})
    run(up)
    try:
        r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "SRVDATI86B"}, headers=H)
        res = [x for x in r.json()['results'] if x['pc_name'] == 'SRVDATI86B']
        assert res and res[0]['location'], "lowercase endpoint MAC not matched"
    finally:
        async def back(db):
            await db.discovered_endpoints.update_many({"TEST_iter166": True}, {"$set": {"mac": "00:15:5D:01:79:0D", "ip": "10.10.1.10"}})
        run(back)


def test_backfill_last_user(H):
    async def unset(db):
        d = await db.datto_devices.find_one({"name": "SRVDATI86B", "client_id": CID}, {"_id": 1, "last_user": 1})
        await db.datto_devices.update_one({"_id": d["_id"]}, {"$unset": {"last_user": ""}})
        return d
    run(unset)
    r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "SRVDATI86B\\Admin"}, headers=H)
    assert r.status_code == 200
    assert any(x['pc_name'] == 'SRVDATI86B' for x in r.json()['results'])
    async def chk(db):
        return (await db.datto_devices.find_one({"name": "SRVDATI86B", "client_id": CID}, {"last_user": 1})).get("last_user")
    assert run(chk) == 'SRVDATI86B\\Administrator'


# --- MAC links
def test_device_info_creates_link_then_mac_only(H):
    async def clean(db):
        await db.datto_mac_links.delete_many({"mac": VMAC})
    run(clean)
    r = requests.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "mac": VMAC, "ip": "10.10.1.10"}, headers=H)
    assert r.status_code == 200 and r.json()['found'] is True and r.json()['name'] == 'SRVDATI86B'
    async def lk(db):
        return await db.datto_mac_links.find_one({"client_id": CID, "mac": VMAC}, {"_id": 0})
    link = run(lk)
    assert link and link['datto_name'] == 'SRVDATI86B' and link['source'] == 'lookup' and link['datto_uid']
    r2 = requests.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "mac": VMAC}, headers=H)
    assert r2.status_code == 200 and r2.json()['found'] is True and r2.json()['name'] == 'SRVDATI86B'
    # lowercase/dashed format → normalized
    r3 = requests.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "mac": VMAC.lower().replace(':', '-')}, headers=H)
    assert r3.json()['found'] is True
    run(clean)
    r4 = requests.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "mac": VMAC}, headers=H)
    assert r4.json()['found'] is False


def test_datto_users_for_linked_mac():
    import sys
    sys.path.insert(0, '/app/backend')
    from routes.datto_rmm import datto_users_for
    async def go(db):
        import database
        d = await db.datto_devices.find_one({"name": "SRVDATI86B", "client_id": CID}, {"_id": 0, "uid": 1})
        await db.datto_mac_links.update_one({"client_id": CID, "mac": VMAC2}, {"$set": {"datto_uid": d['uid'], "datto_name": "SRVDATI86B", "source": "test"}}, upsert=True)
        try:
            database.db = db
            import routes.datto_rmm as m
            m.db = db
            return await datto_users_for(CID, {VMAC2}, set())
        finally:
            await db.datto_mac_links.delete_many({"mac": VMAC2})
    out = run(go)
    assert VMAC2 in out and 'Administrator' in out[VMAC2]['user']


def test_user_search_uses_link_mac(H, seed):
    # endpoint seen only with virtual mac (no ip match) → found through datto_mac_links
    async def up(db):
        d = await db.datto_devices.find_one({"name": "SRVDATI86B", "client_id": CID}, {"_id": 0, "uid": 1})
        await db.datto_mac_links.update_one({"client_id": CID, "mac": VMAC2}, {"$set": {"datto_uid": d['uid'], "datto_name": "SRVDATI86B", "source": "test"}}, upsert=True)
        await db.discovered_endpoints.update_many({"TEST_iter166": True}, {"$set": {"mac": VMAC2, "ip": "10.99.99.98"}})
    run(up)
    try:
        r = requests.get(f"{BASE_URL}/api/datto/user-search", params={"q": "SRVDATI86B"}, headers=H)
        res = [x for x in r.json()['results'] if x['pc_name'] == 'SRVDATI86B']
        assert res and res[0]['location'] and res[0]['location']['port'] == 7
    finally:
        async def back(db):
            await db.datto_mac_links.delete_many({"mac": VMAC2})
            await db.discovered_endpoints.update_many({"TEST_iter166": True}, {"$set": {"mac": "00:15:5D:01:79:0D", "ip": "10.10.1.10"}})
        run(back)
