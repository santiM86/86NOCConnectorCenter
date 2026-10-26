"""Regression test: middleware timeout per long-poll endpoints.

Bug 2026-05-07 (segnalato da utente):
  Il connector PowerShell loggava continuamente:
    Errore secure GET (connector/web-proxy/pending?wait=20):
    Errore del server remoto: (502) Gateway non valido.

Root cause:
  RequestTimeoutMiddleware aveva timeout=45s per /api/connector/, ma l'endpoint
  /api/connector/web-proxy/pending fa long-poll fino a LONG_POLL_MAX_SEC=60s.
  Risultato: il middleware uccideva la richiesta con 504 → il reverse proxy
  nginx lo convertiva in 502 verso il connector.

Fix:
  Aggiunto in middleware/request_timeout.py una regola dedicata per i long-poll
  endpoint con timeout=75s (60s + 15s buffer di rete).
"""
from middleware.request_timeout import _get_timeout, TIMEOUT_RULES


def test_long_poll_endpoints_have_75s_timeout():
    """I long-poll endpoint del connector devono avere timeout >= 75s."""
    long_poll_paths = [
        "/api/connector/web-proxy/pending",
        "/api/connector/discovery-check",
    ]
    for p in long_poll_paths:
        t = _get_timeout(p)
        assert t >= 75, f"Path {p} timeout={t}s, atteso >= 75s (long-poll a 60s + buffer)"


def test_web_console_endpoints_have_at_least_45s():
    """Web Console (browser → connector long-poll 30s) deve avere timeout >= 45s."""
    paths = [
        "/api/web-console/proxy/foo",
        "/api/console-v4/s/abc/",
        "/api/console-rmt/connector-ws/xyz",
    ]
    for p in paths:
        t = _get_timeout(p)
        assert t >= 45, f"Path {p} timeout={t}s, atteso >= 45s (long-poll 30s + buffer)"


def test_standard_connector_endpoints_keep_45s():
    """Heartbeat / device-report / lan-scan restano a 45s (nessuna regressione)."""
    paths = [
        "/api/connector/heartbeat",
        "/api/connector/device-report",
        "/api/connector/lan-scan",
        "/api/connector/managed-devices",
        "/api/connector/identify",
    ]
    for p in paths:
        t = _get_timeout(p)
        assert t == 45, f"Path {p} timeout={t}s, atteso 45s"


def test_default_timeout_unchanged():
    """Endpoint generici NON devono ereditare il timeout long-poll."""
    paths = [
        "/api/clients",
        "/api/devices",
        "/api/alerts",
        "/api/auth/me",
    ]
    for p in paths:
        t = _get_timeout(p)
        assert t == 20, f"Path {p} timeout={t}s, atteso default 20s"


def test_long_poll_rule_appears_before_generic_connector():
    """La regola long-poll DEVE essere prima della regola /api/connector/ generica
    altrimenti la prima 'startswith' match sarebbe quella generica (45s) e il
    bug 502 si ripresenta."""
    # Trova l'indice della prima regola che contiene "/api/connector/web-proxy/pending"
    long_poll_idx = None
    generic_idx = None
    for i, (prefixes, _) in enumerate(TIMEOUT_RULES):
        if any(p == "/api/connector/web-proxy/pending" for p in prefixes):
            long_poll_idx = i
        if any(p == "/api/connector/" for p in prefixes):
            generic_idx = i
    assert long_poll_idx is not None, "Regola long-poll mancante in TIMEOUT_RULES"
    assert generic_idx is not None, "Regola /api/connector/ generica mancante"
    assert long_poll_idx < generic_idx, \
        f"Ordine regole sbagliato: long-poll @{long_poll_idx} deve venire prima di /api/connector/ @{generic_idx}"
