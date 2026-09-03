"""Verifica robustezza raccolta Redfish: retry su fallimenti transitori + paginazione Members."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from redfish import RedfishPoller


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


class FakeClient:
    """Simula httpx.AsyncClient.get con sequenze programmate per URL."""
    def __init__(self, script):
        # script: dict url -> list di (azione). azione: FakeResp | Exception
        self.script = script
        self.calls = {}
    async def get(self, url, auth=None, timeout=None):
        self.calls[url] = self.calls.get(url, 0) + 1
        seq = self.script.get(url, [])
        idx = min(self.calls[url] - 1, len(seq) - 1)
        item = seq[idx]
        if isinstance(item, Exception):
            raise item
        return item


async def run():
    poller = RedfishPoller(db=None)

    # 1) Retry: 2 timeout poi 200 → deve ritornare il dato (non None)
    fc = FakeClient({
        "http://x/a": [httpx.TimeoutException("t"), httpx.TimeoutException("t"), FakeResp(200, {"ok": 1})],
    })
    r = await poller._get(fc, "http://x/a", ("u", "p"))
    assert r == {"ok": 1}, f"atteso dato dopo retry, invece {r}"
    assert fc.calls["http://x/a"] == 3, f"attesi 3 tentativi, {fc.calls}"
    print("[OK] _get: ritenta i timeout transitori e recupera il dato (3 tentativi)")

    # 2) 401 → None immediato SENZA retry
    fc2 = FakeClient({"http://x/b": [FakeResp(401)]})
    r2 = await poller._get(fc2, "http://x/b", ("u", "p"))
    assert r2 is None and fc2.calls["http://x/b"] == 1, "401 non deve ritentare"
    print("[OK] _get: 401 → None immediato (nessun retry)")

    # 3) ConnectError → None immediato (fail-fast host giù)
    fc3 = FakeClient({"http://x/c": [httpx.ConnectError("down")]})
    r3 = await poller._get(fc3, "http://x/c", ("u", "p"))
    assert r3 is None and fc3.calls["http://x/c"] == 1, "ConnectError deve fallire subito"
    print("[OK] _get: ConnectError → None immediato (fail-fast)")

    # 4) Paginazione: pagina1 (2 membri + nextLink) → pagina2 (3 membri) = 5 totali
    base = "http://x"
    fc4 = FakeClient({
        f"{base}/drives/": [FakeResp(200, {
            "Members": [{"@odata.id": "/d/1"}, {"@odata.id": "/d/2"}],
            "Members@odata.nextLink": "/drives/?$skip=2",
        })],
        f"{base}/drives/?$skip=2": [FakeResp(200, {
            "Members": [{"@odata.id": "/d/3"}, {"@odata.id": "/d/4"}, {"@odata.id": "/d/5"}],
        })],
    })
    members = await poller._get_members(fc4, f"{base}/drives/", ("u", "p"), base)
    assert len(members) == 5, f"attesi 5 dischi (paginazione seguita), trovati {len(members)}"
    print("[OK] _get_members: segue Members@odata.nextLink → 5/5 dischi (niente troncamento)")

    print("\nTUTTI I TEST PASSATI")


if __name__ == "__main__":
    asyncio.run(run())
