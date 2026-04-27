"""
Regression test per il manager WireGuard embedded (POC).
Verifica che:
  - Il modulo si importi senza side-effect (nessun subprocess avviato).
  - detect_environment() ritorni i campi attesi.
  - Lo status iniziale sia coerente (running=false, no pid, no error).
  - start() in ambiente non-privilegiato sia fail-safe (no exception, last_error popolato).
  - I binari bundled siano presenti per arm64 e amd64.
  - Il binario per l'arch corrente sia eseguibile.
"""
import os
from pathlib import Path

import pytest


def test_import_no_sideeffect():
    """Importare wireguard_embedded NON deve avviare subprocess."""
    import wireguard_embedded

    assert wireguard_embedded.wg_manager.process is None
    assert wireguard_embedded.wg_manager.started_at is None


def test_bundled_binaries_present():
    """I 2 binari (arm64 + amd64) devono essere nel repo, eseguibili."""
    bin_dir = Path("/app/backend/bin")
    for arch in ("amd64", "arm64"):
        b = bin_dir / f"wireguard-go-linux-{arch}"
        assert b.exists(), f"missing binary {b}"
        assert os.access(b, os.X_OK), f"binary {b} not executable"
        # ELF magic
        assert b.read_bytes()[:4] == b"\x7fELF", f"{b} is not an ELF binary"


def test_detect_environment_shape():
    """detect_environment ritorna sempre tutti i campi attesi."""
    from wireguard_embedded import wg_manager

    env = wg_manager.detect_environment()
    expected_keys = {
        "host_arch",
        "binary_arch",
        "binary_path",
        "binary_present",
        "kernel_wireguard_module",
        "tun_device_available",
        "cap_net_admin",
        "cap_eff_hex",
        "pyroute2_available",
        "ready_to_start",
        "missing_prerequisites",
    }
    assert expected_keys.issubset(env.keys())
    assert isinstance(env["missing_prerequisites"], list)
    # Almeno il binario per l'arch corrente deve essere presente
    if env["binary_arch"] != "unsupported":
        assert env["binary_present"] is True


def test_status_initial_state():
    """Status iniziale: not running, no error, environment populato."""
    from wireguard_embedded import wg_manager

    st = wg_manager.status()
    assert st["enabled"] is True
    assert st["running"] is False
    assert st["pid"] is None
    assert st["started_at"] is None
    assert "environment" in st
    assert isinstance(st["environment"]["missing_prerequisites"], list)


@pytest.mark.asyncio
async def test_start_failsafe_in_unprivileged_env():
    """In ambiente senza CAP_NET_ADMIN o /dev/net/tun, start() NON deve sollevare.
    Deve ritornare uno status con running=false e last_error popolato.
    Questo e` il caso del preview Kubernetes attuale."""
    from wireguard_embedded import wg_manager

    env = wg_manager.detect_environment()
    if env["ready_to_start"]:
        pytest.skip("Test only valid in unprivileged environment")

    st = await wg_manager.start()
    assert st["running"] is False
    assert st["pid"] is None
    assert st["last_error"] is not None
    assert "Prerequisiti mancanti" in st["last_error"]


@pytest.mark.asyncio
async def test_stop_idempotent():
    """stop() su un manager non avviato e` idempotente, non solleva."""
    from wireguard_embedded import wg_manager

    st = await wg_manager.stop()
    assert st["running"] is False
    assert st["pid"] is None
