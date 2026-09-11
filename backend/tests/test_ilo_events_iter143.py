"""Iter143 — IML/SEL events: canale diretto (mock iLO 4) + cache connector.
Esecuzione: cd /app/backend && set -a && source .env && set +a && python tests/test_ilo_events_iter143.py
"""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API = "https://noc-alert-hub-2.preview.emergentagent.com"
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
FAKE_IP = "10.99.99.9"
MOCK_PORT = 8765

IML = {"Members": [
    {"Id": "1", "Severity": "OK", "Created": "2024-08-29T10:00:00Z", "Message": "IML Cleared (iLO 4 user: admin)",
     "Oem": {"Hp": {"Class": 33, "Code": 1, "Number": 1, "Severity": "Informational"}}},
    {"Id": "2", "Severity": "Warning", "Created": "2025-03-01T08:15:00Z",
     "Message": "Power Supply Failure (Power Supply 2)", "Oem": {"Hp": {"Class": 5, "Code": 7, "Number": 2, "Repaired": False}}},
    {"Id": "3", "Severity": "Critical", "Created": "2025-06-10T12:00:00Z",
     "Message": "Uncorrectable Memory Error (Processor 1, DIMM 3)",
     "Oem": {"Hp": {"Class": 3, "Code": 10, "Number": 3, "Repaired": True}}},
]}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if "$top" in self.path:
            return self._send(400, {"error": "QueryNotSupported"})
        if self.path.startswith("/redfish/v1/Systems/1/LogServices/IML/Entries"):
            return self._send(200, IML)
        if self.path.startswith("/redfish/v1/Managers/1/LogServices/IEL/Entries"):
            return self._send(200, {"Members": [{"Id": "9", "Severity": "OK", "Created": "2025-01-01T00:00:00Z", "Message": "Browser login: admin"}]})
        return self._send(404, {})

    def _send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def login():
    r = requests.post(f"{API}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}).json()
    tok = r.get("token") or r.get("access_token")
    r2 = requests.post(f"{API}/api/auth/verify-2fa", json={"code": pyotp.TOTP("NMHDJNO53WLTOSREUXWERE6FDH5TAKC3").now()},
                       headers={"Authorization": f"Bearer {tok}"}).json()
    return r2.get("token") or r2.get("access_token") or tok


async def main():
    from security import security_manager
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    srv = HTTPServer(("127.0.0.1", MOCK_PORT), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    await db.device_credentials.delete_many({"device_ip": FAKE_IP})
    await db.ilo_events.delete_many({"device_ip": FAKE_IP})
    await db.device_credentials.insert_one({
        "id": "test-iter143", "client_id": CID, "device_ip": FAKE_IP, "device_name": "MOCK-ILO4",
        "credential_type": "ilo", "external_url": f"http://127.0.0.1:{MOCK_PORT}",
        "username_enc": security_manager.encrypt_credential("admin"),
        "password_enc": security_manager.encrypt_credential("pw"),
    })
    tok = login()
    H = {"Authorization": f"Bearer {tok}"}
    try:
        # STEP1 — canale diretto (backend gira sullo stesso host → 127.0.0.1 raggiungibile)
        r = requests.get(f"{API}/api/servers/ilo-events/{FAKE_IP}", params={"client_id": CID, "limit": 40}, headers=H)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "direct" and d["stale"] is False, d
        assert d["log_path"] == "/redfish/v1/Systems/1/LogServices/IML/Entries/", d["log_path"]
        assert d["total_events"] == 3, d
        ev = d["events"]
        assert ev[0]["id"] == "3" and ev[0]["repaired"] is True and ev[0]["class"] == 3 and ev[0]["code"] == 10, ev[0]
        assert ev[1]["id"] == "2" and ev[1]["repaired"] is False and ev[1]["severity"] == "warning", ev[1]
        assert ev[2]["severity"] == "informational", ev[2]
        print("STEP1 OK: fetch diretto IML (Systems/1, no $top), ordinati desc, Oem.Hp normalizzato")

        cached = await db.ilo_events.find_one({"device_ip": FAKE_IP})
        assert cached and cached["source"] == "direct" and len(cached["events"]) == 3
        print("STEP2 OK: cache ilo_events popolata dal fetch diretto")

        # STEP3 — canale diretto giù → fallback cache (stale)
        srv.shutdown()
        srv.server_close()
        r = requests.get(f"{API}/api/servers/ilo-events/{FAKE_IP}", params={"client_id": CID}, headers=H)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["stale"] is True and d["total_events"] == 3 and d.get("error"), d
        print("STEP3 OK: iLO irraggiungibile → cache stale + messaggio errore")

        # STEP4 — connector device-report con redfish.iml_events → cache source=connector
        client = await db.clients.find_one({"id": CID}, {"_id": 0, "api_key": 1})
        payload = {"hostname": "TEST-CONN", "devices": [{
            "device_ip": FAKE_IP, "device_name": "MOCK-ILO4", "reachable": True, "device_class": "hpe-ilo",
            "redfish": {"bios_version": "P92 v3.40", "iml_events": IML["Members"] + [
                {"Id": "4", "Severity": "Critical", "Created": "2026-02-02T02:00:00Z", "Message": "Fan Failure (Fan 1)",
                 "Oem": {"Hpe": {"Class": 17, "Code": 2, "Count": 2, "Repaired": False}}}],
                "iml_log_path": "/redfish/v1/Systems/1/LogServices/IML/Entries/"},
        }]}
        r = requests.post(f"{API}/api/connector/device-report", json=payload, headers={"X-API-Key": client["api_key"]})
        assert r.status_code == 200, r.text
        cached = await db.ilo_events.find_one({"device_ip": FAKE_IP})
        assert cached["source"] == "connector" and len(cached["events"]) == 4 and cached["events"][0]["id"] == "4", cached
        ps = await db.device_poll_status.find_one({"client_id": CID, "device_ip": FAKE_IP}, {"_id": 0, "redfish": 1})
        assert "iml_events" not in (ps.get("redfish") or {}), ps
        print("STEP4 OK: device-report connector → cache source=connector, iml_events NON in poll_status")

        r = requests.get(f"{API}/api/servers/ilo-events/{FAKE_IP}", params={"client_id": CID}, headers=H).json()
        assert r["total_events"] == 4 and r["source"] == "connector" and r["events"][0]["count"] == 2, r
        print("STEP5 OK: endpoint serve la cache connector quando il diretto non risponde")

        # STEP6 — nessuna credenziale e nessuna cache → 404
        r = requests.get(f"{API}/api/servers/ilo-events/10.99.99.10", params={"client_id": CID}, headers=H)
        assert r.status_code == 404, r.text
        print("STEP6 OK: 404 senza credenziali né cache")
        print("\nALL ILO EVENTS TESTS PASSED")
    finally:
        await db.device_credentials.delete_many({"device_ip": FAKE_IP})
        await db.ilo_events.delete_many({"device_ip": FAKE_IP})
        await db.device_poll_status.delete_many({"device_ip": FAKE_IP})
        await db.managed_devices.delete_many({"ip": FAKE_IP, "client_id": CID})


if __name__ == "__main__":
    asyncio.run(main())
