"""Regression: integrity SHA256 nel flusso update connector + rebuild-zip endpoint.

Bug 2026-05-07 (chiesto dall'utente):
  Il flusso di update non aveva verifica integrita' del download. Inoltre lo
  ZIP buildato manualmente poteva mancare di file critici (es.
  "Installa 86NocConnector.vbs" che e' l'entry point user-friendly UAC).

Fix:
  - backend/build_connector_zip.py: builda ZIP da source con elenco ESPLICITO file
  - backend/routes/connector.py upload-update: calcola SHA256 a save-time
  - backend/routes/connector.py update-check: include sha256 nel response
  - noc-connector update_check.ps1: Get-FileHash -Algorithm SHA256 dopo download,
    abort se mismatch
  - admin endpoint POST /api/admin/connector/rebuild-zip
"""
import hashlib
import os
import zipfile
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://device-poller-ws.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code == 429:
        pytest.skip("Auth rate-limited in this run")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_update_check_includes_sha256():
    r = requests.get(
        f"{API}/connector/update-check",
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    if not data.get("update_available", False):
        # niente update attivo => non possiamo verificare SHA, skip pulito
        pytest.skip("No active update — sha256 non verificabile")
    assert "sha256" in data, "update-check NON include il campo sha256"
    sha = data["sha256"]
    assert isinstance(sha, str), f"sha256 deve essere stringa, ricevuto {type(sha)}"
    if sha:  # se backend ha hash (post v3.8.25)
        assert len(sha) == 64, f"sha256 deve avere 64 char esadecimali, ricevuto {len(sha)}: {sha}"
        assert all(c in "0123456789abcdef" for c in sha.lower()), \
            f"sha256 deve essere esadecimale lowercase, ricevuto: {sha}"


def test_update_check_size_matches_actual_file():
    """Il file_size in /update-check deve coincidere con la size reale del ZIP scaricabile."""
    check = requests.get(
        f"{API}/connector/update-check",
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    ).json()
    if not check.get("update_available"):
        pytest.skip("No active update")
    expected_size = check.get("file_size")
    expected_sha = (check.get("sha256") or "").lower()

    dl = requests.get(f"{API}/connector/public-download/latest", timeout=30)
    assert dl.status_code == 200
    actual_size = len(dl.content)
    assert actual_size == expected_size, \
        f"size mismatch: backend dice {expected_size}, reale {actual_size}"

    if expected_sha:
        actual_sha = hashlib.sha256(dl.content).hexdigest()
        assert actual_sha == expected_sha, \
            f"SHA256 mismatch: atteso {expected_sha}, ricevuto {actual_sha}"


def test_zip_contains_all_required_files():
    """Lo ZIP attivo DEVE contenere tutti i file necessari per installazione +
    auto-update + entry point user-friendly. Niente di meno, niente di legacy."""
    dl = requests.get(f"{API}/connector/public-download/latest", timeout=30)
    if dl.status_code != 200:
        pytest.skip(f"Download failed: {dl.status_code}")
    zip_path = Path("/tmp/_test_active_connector.zip")
    zip_path.write_bytes(dl.content)

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    REQUIRED = {
        # Root level: entry point user-friendly per non-tech (UAC auto-elevation)
        "Installa 86NocConnector.vbs",
        # prg/ root: NSSM, version, installer scripts, README
        "prg/nssm.exe",
        "prg/version.json",
        "prg/install.bat",
        "prg/installa_servizio.bat",
        "prg/uninstall.bat",
        "prg/uninstall.ps1",
        "prg/86NocConnector.bat",
        "prg/diagnostica_connessione.ps1",
        # prg/src/ — codice del connector
        "prg/src/connector.ps1",
        "prg/src/snmp_poller.ps1",
        "prg/src/argus-scanner.ps1",
        "prg/src/installer_gui.ps1",
        "prg/src/tray_app.ps1",
        "prg/src/tray_launcher.vbs",
        "prg/src/update_check.ps1",
        "prg/src/wireguard_client.ps1",
        "prg/src/remote_browser.ps1",
        "prg/src/backup_monitor.ps1",
        "prg/src/switch_enrichment.ps1",
        "prg/src/printer_probe.ps1",
        "prg/src/network_scanner.ps1",
        "prg/src/diagnostica.ps1",
        "prg/src/service_wrapper.ps1",
        # Branding
        "prg/src/86bit_logo.ico",
        "prg/src/86bit_logo.jpg",
        "prg/src/86bit_logo_256.png",
    }
    missing = REQUIRED - names
    assert not missing, f"ZIP manca {len(missing)} file critici: {sorted(missing)}"

    zip_path.unlink(missing_ok=True)


def test_zip_version_json_matches_published_version():
    """Il version.json DENTRO lo ZIP deve combaciare con la versione attiva nel DB."""
    import json
    check = requests.get(
        f"{API}/connector/update-check",
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    ).json()
    if not check.get("update_available"):
        pytest.skip("No active update")
    expected_version = check["latest_version"]

    dl = requests.get(f"{API}/connector/public-download/latest", timeout=30)
    zip_path = Path("/tmp/_test_version_zip.zip")
    zip_path.write_bytes(dl.content)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open("prg/version.json") as f:
                version_data = json.loads(f.read().decode("utf-8"))
        assert version_data.get("version") == expected_version, \
            f"version.json nello ZIP dice {version_data.get('version')}, atteso {expected_version}"
    finally:
        zip_path.unlink(missing_ok=True)


def test_admin_rebuild_zip_endpoint_exists_and_requires_admin():
    # Without admin token -> 401 or 403
    r = requests.post(f"{API}/admin/connector/rebuild-zip",
                      json={"version": "9.9.99"}, timeout=10)
    assert r.status_code in (401, 403, 422), \
        f"endpoint dovrebbe richiedere admin, ricevuto {r.status_code}"


def test_admin_rebuild_zip_validates_version(admin_token):
    """Versione invalida deve essere rifiutata 400."""
    r = requests.post(
        f"{API}/admin/connector/rebuild-zip",
        json={"version": "abc-def"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 400, f"versione invalida -> 400, ricevuto {r.status_code}: {r.text}"


def test_admin_rebuild_zip_requires_version_field(admin_token):
    """Body senza version -> 400."""
    r = requests.post(
        f"{API}/admin/connector/rebuild-zip",
        json={"changelog": "no version"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 400, f"missing version -> 400, ricevuto {r.status_code}"


def test_db_active_update_has_sha256_and_size():
    """Il documento active nel DB deve avere sha256 + file_size correttamente popolati
    dopo la rebuild fatta in v3.8.25."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _check():
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        client = AsyncIOMotorClient(mongo_url)
        try:
            doc = await client[db_name].connector_updates.find_one(
                {"active": True}, {"_id": 0}
            )
            return doc
        finally:
            client.close()

    doc = asyncio.run(_check())
    assert doc, "Nessun connector_update attivo in DB"
    # SHA256: 64 char esadecimali
    sha = doc.get("sha256", "")
    assert sha and len(sha) == 64, f"SHA256 mancante o invalido: '{sha}'"
    # File size: int positivo
    assert doc.get("file_size", 0) > 50000, f"file_size sospetto: {doc.get('file_size')}"
    # Filename pattern
    fn = doc.get("filename", "")
    assert fn.startswith("86NocConnector_v") and fn.endswith(".zip"), f"filename invalido: {fn}"
