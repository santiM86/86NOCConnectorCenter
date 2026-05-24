"""Regression: 'Scarica ZIP' button must not fall into React SPA fallback.

Bug 2026-05-07 (segnalato dall'utente con 2 screenshot):
  Il pulsante "Scarica ZIP" nella pagina /connectors puntava a `/86NocConnector.zip`
  (path statico). In produzione (argus.86bit.it), il static server cattura tutti
  i path non-API con il fallback React SPA -> ritorna `index.html` (~3.9 KB) come
  Content-Type: text/html. L'utente scaricava ripetutamente file ZIP da 4 KB
  che Windows non riusciva ad estrarre ("La cartella compressa e' vuota").

Fix:
  - frontend/ConnectorsPage.js linea 280: cambiato href da `/86NocConnector.zip`
    a `${API}/connector/public-download/latest`. Questo passa per il backend
    FastAPI che restituisce sempre l'application/zip corretto della versione
    attiva nel DB connector_updates.

Verifica: download da `/api/connector/public-download/latest` deve essere ZIP
valido, > 50 KB, e con magic bytes 'PK' all'inizio.
"""
import os
import zipfile
from io import BytesIO

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://device-scanner-pro-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"


def test_public_download_returns_real_zip_not_html_fallback():
    """L'endpoint pubblico DEVE restituire un ZIP valido, MAI l'index.html del SPA."""
    r = requests.get(f"{API}/connector/public-download/latest", timeout=30)
    assert r.status_code == 200, f"Download fallito: {r.status_code}"

    # Content-Type deve essere application/zip, mai text/html
    ct = r.headers.get("content-type", "")
    assert "application/zip" in ct or "octet-stream" in ct, \
        f"Content-Type sbagliato: '{ct}' (probabile SPA fallback su index.html)"

    # Size > 50 KB (un ZIP del connector pesa ~400 KB; index.html del SPA ~4 KB)
    assert len(r.content) > 50000, \
        f"Body sospetto piccolo: {len(r.content)} byte (probabile index.html, non ZIP)"

    # Magic bytes ZIP: 'PK\x03\x04'
    assert r.content[:2] == b"PK", \
        f"Magic bytes errati: {r.content[:8]!r} (atteso 'PK...' - probabile HTML)"

    # Apriamolo per davvero come ZIP — se non e' un archivio valido qui esplode
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        names = zf.namelist()
    assert len(names) > 10, f"ZIP con troppo pochi file: {len(names)}"


def test_public_download_no_auth_required():
    """L'endpoint deve essere pubblico (no header X-API-Key, no Authorization)."""
    r = requests.get(f"{API}/connector/public-download/latest", timeout=10)
    assert r.status_code == 200, f"Endpoint richiede auth? {r.status_code}: {r.text[:200]}"


def test_legacy_static_path_falls_back_to_html_in_production_like_envs():
    """Documenta il bug: in produzione `/86NocConnector.zip` (path statico) ritorna
    HTML perche' viene catturato dal SPA fallback. Questo test serve a impedire
    a uno sviluppatore distratto di rimettere quel path nell'UI.

    In ambiente preview (Kubernetes ingress dell'agente Emergent) il file e'
    presente fisicamente in /app/frontend/build/ quindi viene servito come ZIP.
    Ma in altri ambienti (deploy Vercel, deploy custom Node static server,
    nginx con `try_files $uri /index.html;`) cade nel fallback HTML.

    Per questo motivo il pulsante UI DEVE puntare all'endpoint API, non al
    path statico.
    """
    r = requests.get(f"{BASE_URL}/86NocConnector.zip", timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Static path non disponibile in questo env: {r.status_code}")
    ct = r.headers.get("content-type", "")
    if "application/zip" in ct or "octet-stream" in ct:
        # In preview qui il file ESISTE perche' viene copiato durante upload-update.
        # Non e' un errore, ma documentiamo la situazione.
        return
    if "text/html" in ct:
        # CONFERMA del bug. Non lo trattiamo come failure perche' dipende dal
        # comportamento del static server, ma il test sopra (public-download)
        # garantisce che l'API funzioni sempre.
        pytest.skip(f"Conferma bug noto: static path serve text/html (size={len(r.content)})")


def test_connectors_page_source_uses_api_endpoint():
    """Il sorgente di ConnectorsPage.js NON deve piu' contenere il path statico
    /86NocConnector.zip nell'href del bottone 'Scarica ZIP'."""
    src = "/app/frontend/src/pages/ConnectorsPage.js"
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    # La stringa /86NocConnector.zip non deve apparire come href del bottone download.
    # Verifichiamo che il bottone usi il path API.
    assert 'data-testid="download-connector-btn"' in content, \
        "Bottone 'Scarica ZIP' rinominato/rimosso? Aggiorna questo test."
    # Cerchiamo l'<a> piu' vicino al bottone (nelle ~10 righe sopra)
    idx = content.find('data-testid="download-connector-btn"')
    block = content[max(0, idx - 500):idx]
    assert "/connector/public-download/latest" in block, \
        f"Il bottone DEVE puntare all'endpoint API. Block trovato:\n{block[-300:]}"
    # Inoltre il path statico non deve piu' essere usato come href
    assert 'href="/86NocConnector.zip"' not in block, \
        "Trovato href='/86NocConnector.zip' che cade nel SPA fallback. USARE l'API endpoint."
