"""
ARGUS Center — System Admin Routes
===================================
Endpoint per operazioni di amministrazione SISTEMA (non applicative).
Attualmente: self-update del backend (download nuovo codice, backup, rimpiazzo,
restart) gestito interamente da UI senza richiedere SSH all'admin.

Endpoint:
- GET  /api/admin/system/version              versione corrente del backend
- POST /api/admin/system/self-update          triggera l'update (job detached)
- GET  /api/admin/system/self-update/status   polling del progress
"""
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(tags=["system-admin"])

# Path locations
BACKEND_DIR_DEFAULT = Path(__file__).resolve().parent.parent  # /app/backend
SELF_UPDATE_SCRIPT = BACKEND_DIR_DEFAULT / "scripts" / "self_update.sh"
STATUS_FILE = Path(os.environ.get("ARGUS_UPDATE_STATUS_FILE", "/tmp/argus-update-status.json"))
RUNNER_LOG = Path("/tmp/argus-update-runner.log")

# Versione del backend: aggiornata manualmente ad ogni release importante
BACKEND_VERSION = os.environ.get("ARGUS_BACKEND_VERSION", "3.5.26-fase2")


class SelfUpdateRequest(BaseModel):
    """Body per POST /self-update.

    `package_url`: dove scaricare il tarball (default: /downloads/argus-backend-latest.tar.gz)
    `enable_wireguard`: se true, lo script aggiunge `WG_EMBEDDED_ENABLED=true` al .env
    `wireguard_host`: hostname pubblico server (per WG_SERVER_HOST)
    """
    package_url: Optional[str] = None
    enable_wireguard: bool = False
    wireguard_host: Optional[str] = Field(default=None, max_length=200)


@router.get("/api/admin/system/version")
async def get_system_version(current_user: dict = Depends(get_current_user)):
    """Versione corrente del backend ARGUS Center."""
    require_admin(current_user)
    return {
        "version": BACKEND_VERSION,
        "backend_dir": str(BACKEND_DIR_DEFAULT),
        "self_update_supported": SELF_UPDATE_SCRIPT.exists(),
    }


@router.get("/api/admin/system/self-update/status")
async def self_update_status(current_user: dict = Depends(get_current_user)):
    """Ritorna lo stato dell'ultima sessione di self-update.

    Risposta:
    - se nessun update mai lanciato: {phase: "idle"}
    - durante update: {phase, progress (0-100), message, updated_at}
    - completato: {phase: "done", progress: 100, message}
    - fallito: {phase: "failed", progress: <last>, error, message}
    """
    require_admin(current_user)
    if not STATUS_FILE.exists():
        return {"phase": "idle", "progress": 0, "message": "Nessun aggiornamento in corso"}
    try:
        with STATUS_FILE.open() as f:
            data = json.load(f)
        # Anti-stale: se updated_at piu` di 10 minuti fa e phase non e` done/failed/idle,
        # marca come stale (probabilmente il runner e` morto)
        if data.get("phase") not in {"done", "failed", "idle"}:
            updated_at = data.get("updated_at", "")
            if updated_at:
                try:
                    from datetime import datetime, timezone
                    upd = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - upd).total_seconds()
                    if age > 600:
                        data["phase"] = "stale"
                        data["message"] = f"Update bloccato da {int(age)}s (runner morto?)"
                except Exception:
                    pass
        return data
    except Exception as e:
        return {"phase": "error", "error": str(e), "message": "Errore lettura status file"}


@router.post("/api/admin/system/self-update", status_code=202)
async def trigger_self_update(payload: SelfUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Avvia il processo di self-update in subprocess detached.

    Il backend FastAPI corrente CONTINUERA` a rispondere fino a quando il runner
    non chiama `systemctl stop` (~step 4 del runner). Questo da` tempo all'UI di
    iniziare il polling dello status.

    Risposta immediata 202 Accepted con `job_started=true`.
    Lo status va seguito su GET /self-update/status.
    """
    require_admin(current_user)

    if not SELF_UPDATE_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Self-update script non trovato in {SELF_UPDATE_SCRIPT}. "
                   f"Backend non aggiornabile da UI in questo deploy.",
        )

    # Pre-check: se gia` in corso, rifiuta
    if STATUS_FILE.exists():
        try:
            with STATUS_FILE.open() as f:
                last = json.load(f)
            phase = last.get("phase", "")
            updated_at = last.get("updated_at", "")
            if phase not in {"done", "failed", "idle", "stale", "error"}:
                # Verifica freshness
                try:
                    from datetime import datetime, timezone
                    upd = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - upd).total_seconds()
                    if age < 300:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Update gia` in corso (phase={phase}, da {int(age)}s)",
                        )
                except HTTPException:
                    raise
                except Exception:
                    pass
        except HTTPException:
            raise
        except Exception:
            pass

    # Default URL: cdn pubblico del Center stesso
    package_url = payload.package_url or "https://argus.86bit.it/downloads/argus-backend-latest.tar.gz"

    # Auto-detect host per WG_SERVER_HOST se enable_wireguard e nessun host fornito
    wg_host = payload.wireguard_host or ""

    # Reset status file
    initial = {
        "phase": "queued",
        "progress": 0,
        "message": "Update accodato, in avvio...",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    STATUS_FILE.write_text(json.dumps(initial))

    # Backend dir per il runner: in locale e` /app/backend, ma in produzione l'admin
    # potrebbe avere path diverso. Lo passiamo come arg.
    backend_dir_arg = os.environ.get("ARGUS_BACKEND_DIR", str(BACKEND_DIR_DEFAULT))

    cmd = [
        "/bin/bash",
        str(SELF_UPDATE_SCRIPT),
        package_url,
        str(STATUS_FILE),
        backend_dir_arg,
        "true" if payload.enable_wireguard else "false",
        wg_host,
    ]

    try:
        # Detached subprocess: sopravvive al restart del backend
        log_handle = open(RUNNER_LOG, "ab")
        proc = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        audit.warning(
            f"SYSTEM_SELF_UPDATE_STARTED by={current_user.get('name', 'admin')} "
            f"url={package_url} pid={proc.pid} enable_wg={payload.enable_wireguard}"
        )
        return {
            "job_started": True,
            "pid": proc.pid,
            "package_url": package_url,
            "status_endpoint": "/api/admin/system/self-update/status",
            "expected_duration_sec": 60,
        }
    except Exception as e:
        logger.error(f"Self-update spawn failed: {e}")
        STATUS_FILE.write_text(json.dumps({
            "phase": "failed",
            "progress": 0,
            "error": str(e),
            "message": "Impossibile lanciare il runner",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }))
        raise HTTPException(status_code=500, detail=f"Spawn runner failed: {e}")


@router.get("/api/admin/system/self-update/log")
async def self_update_log(lines: int = 100, current_user: dict = Depends(get_current_user)):
    """Ritorna le ultime N righe di log del runner. Utile per troubleshooting."""
    require_admin(current_user)
    if not RUNNER_LOG.exists():
        return {"lines": [], "total": 0}
    try:
        with RUNNER_LOG.open("rb") as f:
            f.seek(0, 2)  # SEEK_END
            size = f.tell()
            chunk = min(size, 64 * 1024)
            f.seek(-chunk, 2)
            text = f.read().decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        return {
            "lines": all_lines[-lines:],
            "total": len(all_lines),
            "log_path": str(RUNNER_LOG),
        }
    except Exception as e:
        return {"lines": [], "error": str(e)}
