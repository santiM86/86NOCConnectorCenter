"""Tests per il REPORT PDF MULTI-PAGINA per cliente (iterazione 101).

Modulo sotto test: /app/backend/routes/reports.py
  - GET /api/reports/list
  - GET /api/reports/generate/{client_id}?days=N
"""
import os
import re
import io
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

EXPECTED_SECTIONS = [
    "Report di Rete",
    "Riepilogo Esecutivo",
    "Inventario Dispositivi",
    "Porte Switch e Consumo PoE",
    "Adiacenze di Rete (LLDP)",
    "SLA per Dispositivo",
]


@pytest.fixture(scope="session")
def credentials():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing test_credentials.md")
    c = p.read_text(encoding="utf-8")
    e = re.search(r'(?im)^\s*[-*]?\s*Email:\s*`?([^`\s]+)', c)
    pw = re.search(r'(?im)^\s*[-*]?\s*Password:\s*`?([^`\s]+)', c)
    if not e or not pw:
        pytest.skip("no credentials found")
    return {"email": e.group(1), "password": pw.group(1)}


@pytest.fixture(scope="session")
def token(credentials):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=credentials, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    t = r.json().get("token")
    if not t:
        pytest.fail(f"no token in login response: {r.text[:300]}")
    return t


@pytest.fixture(scope="session")
def auth(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---- /api/reports/list ----
class TestReportsList:
    def test_list_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/reports/list", timeout=60)
        assert r.status_code in (401, 403), f"got {r.status_code}"

    def test_list_returns_clients(self, auth):
        r = auth.get(f"{BASE_URL}/api/reports/list", timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert isinstance(data, list) and len(data) > 0
        for item in data:
            assert set(["client_id", "client_name", "device_count"]).issubset(item.keys())
            assert isinstance(item["client_id"], str)
            assert isinstance(item["device_count"], int)
        assert "_id" not in data[0]
        ids = [i["client_id"] for i in data]
        assert TEST_CLIENT_ID in ids, f"test client missing; got {ids}"
        target = next(i for i in data if i["client_id"] == TEST_CLIENT_ID)
        assert target["client_name"] == "86BIT_Office"


# ---- /api/reports/generate/{client_id} ----
class TestReportGenerate:
    def test_generate_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/reports/generate/{TEST_CLIENT_ID}", timeout=60)
        assert r.status_code in (401, 403), f"got {r.status_code}"

    def test_generate_unknown_client_404(self, auth):
        r = auth.get(f"{BASE_URL}/api/reports/generate/does-not-exist-xyz", timeout=60)
        assert r.status_code == 404, f"got {r.status_code}: {r.text[:200]}"
        assert "non trovato" in r.json().get("detail", "").lower()

    def test_generate_pdf_valid_multipage_with_sections(self, auth):
        r = auth.get(f"{BASE_URL}/api/reports/generate/{TEST_CLIENT_ID}?days=30", timeout=180)
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        assert ".pdf" in cd.lower()
        content = r.content
        assert content[:5] == b"%PDF-", content[:20]
        assert len(content) > 3000, f"pdf too small: {len(content)}"

        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        n_pages = len(reader.pages)
        assert n_pages >= 5, f"expected multi-page report, got {n_pages}"
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        missing = [s for s in EXPECTED_SECTIONS if s not in text]
        assert not missing, f"missing sections {missing}; pages={n_pages}"
        # copertina: brand + nome cliente
        assert "86BIT NOC" in text
        assert "86BIT_Office" in text
        # footer paginazione
        assert "Pagina 1" in text

    @pytest.mark.parametrize("days", [7, 90])
    def test_generate_various_periods(self, auth, days):
        r = auth.get(f"{BASE_URL}/api/reports/generate/{TEST_CLIENT_ID}?days={days}", timeout=180)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:5] == b"%PDF-"

    def test_generate_all_clients_no_500(self, auth):
        clients = auth.get(f"{BASE_URL}/api/reports/list", timeout=60).json()
        failures = []
        for c in clients[:10]:
            rr = auth.get(f"{BASE_URL}/api/reports/generate/{c['client_id']}?days=30", timeout=180)
            if rr.status_code != 200 or rr.content[:5] != b"%PDF-":
                failures.append((c["client_name"], rr.status_code, rr.text[:150]))
        assert not failures, f"report generation failed: {failures}"
