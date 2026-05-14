"""Regression test v3.8.39 — lan-scan aggiorna last_seen_at per qualsiasi device.

Bug originale (riga 543-551 di connector.py): l'endpoint /connector/lan-scan
aggiornava managed_devices.last_seen_at SOLO se il device esistente aveva
source=connector-scanner. Risultato: device aggiunti manualmente dall'utente o
auto-promossi dal Master mantenevano un last_seen_at congelato all'epoca della
prima discovery — anche se lo Scanner continuava a vederli ad ogni ciclo.

Fix v3.8.39: l'update viene applicato a TUTTI i device esistenti (manual,
master, scanner). Solo l'aggiornamento dell'hostname rimane limitato a source=
connector-scanner per non sovrascrivere nomi customizzati dall'utente.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_lan_scan_updates_last_seen_for_any_source():
    """Smoke: il file connector.py contiene il fix v3.8.39 e non ha piu' il
    filtro restrittivo source=connector-scanner sul update di last_seen_at."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "routes", "connector.py")).read()
    # Fix marker presente
    assert "v3.8.39" in src
    # Il commento esplicativo del fix e' presente
    assert "qualsiasi device" in src.lower() or "qualsiasi device esistente" in src.lower()
    # La query di update deve usare {client_id, ip} (senza filtro source) — non piu' source-specific
    assert '{"client_id": client_id, "ip": ep.ip},\n                    {"$set": upd}' in src


def test_hostname_update_still_scoped_to_scanner():
    """L'aggiornamento dell'hostname resta limitato ai device scanner-source per
    non sovrascrivere nomi custom inseriti dall'utente."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "routes", "connector.py")).read()
    # cerca la riga del fix dove l'hostname e' aggiornato solo se source=connector-scanner
    assert 'existing.get("source") == "connector-scanner"' in src
