"""
ARGUS Center — Embedded WireGuard runtime manager
==================================================
POC v1: lifecycle del binario `wireguard-go` userspace bundlato in
`/app/backend/bin/`. Si occupa di:
  - rilevare l'ambiente (kernel WG, /dev/net/tun, CAP_NET_ADMIN, arch)
  - scegliere il binario corretto per l'architettura host
  - generare/persistere la chiave privata server in
    `/app/backend/data/wireguard/server.key`
  - avviare wireguard-go come subprocess (interfaccia es. wg-argus)
  - configurare l'interfaccia via UAPI socket (private key, listen port)
  - applicare ip addr / ip link tramite pyroute2 (zero `wg-tools` richiesti)
  - gestire stop pulito on shutdown FastAPI

Questa POC NON gestisce ancora i peer (DB+API gia` esistono in
`routes/wireguard.py`). Quel pezzo arrivera` nel passo 2 dopo conferma utente
che la POC fa boot-up corretto in produzione.

Design choice: manager fail-safe. Se anche solo un prerequisito manca
(`/dev/net/tun` assente, mancanza CAP_NET_ADMIN, arch non supportata),
`start()` registra il motivo in `last_error` e ritorna senza sollevare —
il backend continua a funzionare senza WG embedded. Lo `status()` rivela
ESATTAMENTE che cosa manca, cosi` l'admin puo` agire sul sistema host.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import platform
import secrets
import socket
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# Configuration (env vars)
# ============================================================
WG_INTERFACE = os.environ.get("WG_EMBEDDED_INTERFACE", "wg-argus")
WG_LISTEN_PORT = int(os.environ.get("WG_EMBEDDED_LISTEN_PORT", "51820"))
WG_TUNNEL_CIDR = os.environ.get("WG_EMBEDDED_TUNNEL_CIDR", "10.86.0.1/16")
WG_DATA_DIR = Path(os.environ.get("WG_EMBEDDED_DATA_DIR", "/app/backend/data/wireguard"))
WG_BIN_DIR = Path(os.environ.get("WG_EMBEDDED_BIN_DIR", "/app/backend/bin"))
WG_LOG_PATH = Path(os.environ.get("WG_EMBEDDED_LOG_PATH", "/var/log/argus-wireguard.log"))

# CAP_NET_ADMIN bit nel bitmask delle capabilities Linux
_CAP_NET_ADMIN_BIT = 12


# ============================================================
# Manager
# ============================================================
class EmbeddedWireGuardManager:
    """Singleton manager per il runtime userspace WireGuard."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[str] = None
        self.last_error: Optional[str] = None
        self._private_key_b64: Optional[str] = None
        self._public_key_b64: Optional[str] = None
        self._uapi_socket: Optional[Path] = None

    # ---------- Environment detection ----------
    def detect_environment(self) -> dict:
        """Diagnostica completa: cosa c'e` e cosa manca per far girare WG."""
        arch = platform.machine().lower()
        # Mappa python machine() -> nome binario
        arch_map = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }
        bin_arch = arch_map.get(arch, "unsupported")
        binary = WG_BIN_DIR / f"wireguard-go-linux-{bin_arch}" if bin_arch != "unsupported" else None

        binary_present = bool(binary and binary.exists() and os.access(binary, os.X_OK))
        kernel_wg = Path("/sys/module/wireguard").exists()
        tun_present = Path("/dev/net/tun").exists()

        # Read effective capabilities mask from /proc/self/status
        cap_eff_hex = "0"
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("CapEff:"):
                        cap_eff_hex = line.split()[1]
                        break
        except Exception as e:
            logger.debug(f"Cannot read CapEff: {e}")
        try:
            cap_eff_int = int(cap_eff_hex, 16)
        except Exception:
            cap_eff_int = 0
        has_cap_net_admin = bool(cap_eff_int & (1 << _CAP_NET_ADMIN_BIT))

        # Pyroute2 disponibile? (per gestire ip addr/link senza wg-tools)
        pyroute2_available = False
        try:
            import pyroute2  # noqa: F401
            pyroute2_available = True
        except ImportError:
            pass

        # Tutti i prerequisiti per partire
        ready = bool(
            binary_present
            and tun_present
            and has_cap_net_admin
            and bin_arch != "unsupported"
        )

        missing = []
        if not binary_present:
            missing.append(f"binary {binary} not found or not executable")
        if not tun_present:
            missing.append("/dev/net/tun device unavailable (need to mknod or run with --device=/dev/net/tun)")
        if not has_cap_net_admin:
            missing.append("CAP_NET_ADMIN not present (run as root or with --cap-add=NET_ADMIN)")
        if bin_arch == "unsupported":
            missing.append(f"unsupported host architecture: {arch}")

        return {
            "host_arch": arch,
            "binary_arch": bin_arch,
            "binary_path": str(binary) if binary else "",
            "binary_present": binary_present,
            "kernel_wireguard_module": kernel_wg,
            "tun_device_available": tun_present,
            "cap_net_admin": has_cap_net_admin,
            "cap_eff_hex": cap_eff_hex,
            "pyroute2_available": pyroute2_available,
            "ready_to_start": ready,
            "missing_prerequisites": missing,
        }

    # ---------- Key management ----------
    def _ensure_keys(self) -> None:
        """Genera o carica la chiave privata server. Persistita su disco con
        permessi 0600. La chiave pubblica viene derivata via wireguard-go."""
        WG_DATA_DIR.mkdir(parents=True, exist_ok=True)
        priv_path = WG_DATA_DIR / "server.key"
        if priv_path.exists():
            self._private_key_b64 = priv_path.read_text().strip()
            logger.info(f"WG: loaded existing private key from {priv_path}")
        else:
            # WireGuard private key = 32 random bytes, base64 encoded.
            # NB: il "clamping" Curve25519 viene applicato dal codice WG al boot.
            raw = secrets.token_bytes(32)
            self._private_key_b64 = base64.b64encode(raw).decode()
            priv_path.write_text(self._private_key_b64)
            try:
                os.chmod(priv_path, 0o600)
            except Exception:
                pass
            logger.info(f"WG: generated new private key at {priv_path}")

        # Public key: derivabile via wg pubkey o curve25519. Per la POC la
        # calcoliamo via subprocess al binario wg se disponibile, altrimenti
        # lasciamo None (la pubkey verra` esposta dal UAPI dopo lo start).
        try:
            wg_bin = WG_BIN_DIR / "wg"  # bundled tool, optional
            if wg_bin.exists():
                proc = subprocess.run(
                    [str(wg_bin), "pubkey"],
                    input=self._private_key_b64,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    self._public_key_b64 = proc.stdout.strip()
        except Exception as e:
            logger.debug(f"WG pubkey derivation skipped: {e}")

    # ---------- Lifecycle ----------
    async def start(self) -> dict:
        """Avvia wireguard-go. Idempotent. Ritorna lo status finale."""
        env = self.detect_environment()
        if not env["ready_to_start"]:
            self.last_error = (
                "Prerequisiti mancanti: " + "; ".join(env["missing_prerequisites"])
            )
            logger.warning(f"WG embedded NOT started: {self.last_error}")
            return self.status()

        if self.process and self.process.poll() is None:
            logger.info(f"WG embedded already running (pid={self.process.pid})")
            return self.status()

        self._ensure_keys()

        binary = env["binary_path"]
        # `wireguard-go --foreground <iface>` blocca; subprocess in background.
        # Log su file dedicato per troubleshooting.
        try:
            WG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        log_handle = open(WG_LOG_PATH, "ab") if WG_LOG_PATH.parent.exists() else subprocess.DEVNULL

        try:
            self.process = subprocess.Popen(
                [binary, "--foreground", WG_INTERFACE],
                stdout=log_handle,
                stderr=log_handle,
                env={**os.environ, "LOG_LEVEL": "info"},
                start_new_session=True,
            )
        except FileNotFoundError as e:
            self.last_error = f"binary not found: {e}"
            return self.status()
        except PermissionError as e:
            self.last_error = f"permission denied launching binary: {e}"
            return self.status()
        except Exception as e:
            self.last_error = f"unexpected error launching binary: {e}"
            return self.status()

        # Attendi creazione UAPI socket (max 3s)
        self._uapi_socket = Path(f"/var/run/wireguard/{WG_INTERFACE}.sock")
        for _ in range(30):
            if self._uapi_socket.exists():
                break
            await asyncio.sleep(0.1)
        else:
            # Timeout: verifica se il processo e` ancora vivo
            if self.process.poll() is not None:
                self.last_error = (
                    f"wireguard-go exited immediately (rc={self.process.returncode}). "
                    f"Check {WG_LOG_PATH}"
                )
                self.process = None
                return self.status()
            self.last_error = (
                f"UAPI socket {self._uapi_socket} not created within 3s. "
                f"Process is alive but socket missing."
            )

        # Configura private key + listen port via UAPI
        config_ok = await self._uapi_set_config()
        if not config_ok:
            logger.warning("WG embedded started ma UAPI config failed; check logs")

        # Attiva interfaccia (ip addr add + ip link set up) via pyroute2
        link_ok = self._activate_link()
        if not link_ok:
            logger.warning("WG embedded started ma activation link failed; check logs")

        self.started_at = datetime.now(timezone.utc).isoformat()
        self.last_error = None
        logger.info(
            f"WG embedded started: pid={self.process.pid} iface={WG_INTERFACE} "
            f"port={WG_LISTEN_PORT} cidr={WG_TUNNEL_CIDR}"
        )
        return self.status()

    async def stop(self) -> dict:
        """Stop pulito del subprocess + cleanup."""
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
                logger.info("WG embedded stopped")
            except Exception as e:
                logger.warning(f"Error stopping WG embedded: {e}")
        self.process = None
        self.started_at = None
        return self.status()

    # ---------- UAPI configuration ----------
    async def _uapi_set_config(self) -> bool:
        """Scrive la private key e la listen port via UAPI socket (formato testo)."""
        if not self._uapi_socket or not self._uapi_socket.exists():
            return False
        # WireGuard UAPI accetta private_key come 32 byte HEX (NON base64)
        try:
            priv_raw = base64.b64decode(self._private_key_b64)
            priv_hex = priv_raw.hex()
        except Exception as e:
            logger.error(f"UAPI: invalid private key encoding: {e}")
            return False

        msg = (
            f"set=1\n"
            f"private_key={priv_hex}\n"
            f"listen_port={WG_LISTEN_PORT}\n"
            f"replace_peers=true\n"
            f"\n"
        )
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(str(self._uapi_socket))
            sock.sendall(msg.encode())
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n\n" in data:
                    break
            sock.close()
            text = data.decode("utf-8", errors="replace")
            ok = "errno=0" in text
            if not ok:
                logger.warning(f"UAPI set config returned: {text!r}")
            return ok
        except Exception as e:
            logger.error(f"UAPI set config failed: {e}")
            return False

    async def get_uapi_state(self) -> dict:
        """Legge lo stato corrente via UAPI (peers, handshake, listen port)."""
        if not self._uapi_socket or not self._uapi_socket.exists():
            return {"available": False, "reason": "UAPI socket missing"}
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(str(self._uapi_socket))
            sock.sendall(b"get=1\n\n")
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n\n" in data:
                    break
            sock.close()
            text = data.decode("utf-8", errors="replace")
            return _parse_uapi_get(text)
        except Exception as e:
            return {"available": False, "reason": str(e)}

    # ---------- Link activation ----------
    def _activate_link(self) -> bool:
        """Set the wg-argus interface up + add IP address. Usa pyroute2 se
        disponibile, altrimenti fallback a `ip` subprocess."""
        try:
            from pyroute2 import IPRoute  # type: ignore

            with IPRoute() as ipr:
                idx_list = ipr.link_lookup(ifname=WG_INTERFACE)
                if not idx_list:
                    logger.warning(f"WG: interface {WG_INTERFACE} not found post-start")
                    return False
                idx = idx_list[0]
                # Add IP if not already present
                addr, prefix = WG_TUNNEL_CIDR.split("/")
                try:
                    ipr.addr("add", index=idx, address=addr, prefixlen=int(prefix))
                except Exception as e:
                    # Often: "File exists" if already configured — ignore
                    if "File exists" not in str(e):
                        logger.warning(f"WG addr add failed: {e}")
                ipr.link("set", index=idx, state="up")
            logger.info(f"WG link {WG_INTERFACE} brought up with {WG_TUNNEL_CIDR}")
            return True
        except ImportError:
            # Fallback: subprocess ip
            try:
                subprocess.run(
                    ["ip", "addr", "add", WG_TUNNEL_CIDR, "dev", WG_INTERFACE],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                subprocess.run(
                    ["ip", "link", "set", "up", "dev", WG_INTERFACE],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
                return True
            except Exception as e:
                logger.warning(f"WG link activation via ip subprocess failed: {e}")
                return False
        except Exception as e:
            logger.warning(f"WG link activation failed: {e}")
            return False

    # ---------- Status ----------
    def status(self) -> dict:
        env = self.detect_environment()
        running = bool(self.process and self.process.poll() is None)
        pid = self.process.pid if running else None
        public_key = self._public_key_b64 or ""
        return {
            "enabled": True,
            "running": running,
            "pid": pid,
            "started_at": self.started_at,
            "interface": WG_INTERFACE,
            "listen_port": WG_LISTEN_PORT,
            "tunnel_cidr": WG_TUNNEL_CIDR,
            "data_dir": str(WG_DATA_DIR),
            "log_path": str(WG_LOG_PATH),
            "uapi_socket": str(self._uapi_socket) if self._uapi_socket else "",
            "uapi_socket_exists": bool(
                self._uapi_socket and self._uapi_socket.exists()
            ),
            "public_key": public_key,
            "last_error": self.last_error,
            "environment": env,
        }


def _parse_uapi_get(text: str) -> dict:
    """Parser molto piccolo del formato UAPI 'get=1' di wireguard-go.
    Esempio output:
      private_key=...
      listen_port=51820
      public_key=...   <-- inizia un peer
      preshared_key=...
      endpoint=10.0.0.5:1234
      last_handshake_time_sec=...
      tx_bytes=...
      ...
      errno=0
    """
    out: dict = {"available": True, "peers": []}
    current_peer: Optional[dict] = None
    for line in text.splitlines():
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k == "public_key":
            # nuovo peer
            current_peer = {"public_key": v}
            out["peers"].append(current_peer)
        elif current_peer is not None and k in (
            "preshared_key",
            "endpoint",
            "last_handshake_time_sec",
            "last_handshake_time_nsec",
            "tx_bytes",
            "rx_bytes",
            "persistent_keepalive_interval",
            "allowed_ip",
            "protocol_version",
        ):
            current_peer[k] = v
        elif k in ("private_key", "listen_port", "fwmark", "errno"):
            out[k] = v
    return out


# Singleton
wg_manager = EmbeddedWireGuardManager()
