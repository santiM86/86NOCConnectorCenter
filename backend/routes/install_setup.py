"""Endpoint: scarica un installer "setup ZIP" pre-configurato per un cliente.

ZIP contains:
- setup.exe       → rename di nocinstall.exe (GUI installer Windows nativa)
- nocinstall.cfg  → sidecar TOKEN=... BACKEND=... letto automaticamente
                    dal binario `nocinstall.exe` al boot (vedi cmd/installer/main.go:249)
- LEGGIMI.txt     → istruzioni breve

Il tecnico estrae il ZIP, fa doppio click su `setup.exe`, autorizza UAC.
NESSUN PowerShell, nessun comando da copiare.

Restituisce 503 se la cache locale non ha ancora `nocinstall.exe` per la
versione richiesta (necessario pubblicare la GitHub Release prima).
"""
from __future__ import annotations

import io
import os
import re
import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/agent/install", tags=["agent-install-setup"])

_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "release-bin",
)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._\-+/=]+$")
_VER_RE = re.compile(r"^v?[0-9.]+$")


def _resolve_version(requested: str) -> str:
    """Risolve 'latest' alla versione più alta presente nel mirror.
    Per le richieste esplicite (v4.25.2) verifica solo l'esistenza."""
    if not os.path.isdir(_BASE_DIR):
        raise HTTPException(404, "no builds cached on this server")
    if requested == "latest":
        versions = [v for v in os.listdir(_BASE_DIR) if _VER_RE.match(v)]
        if not versions:
            raise HTTPException(404, "no versioned builds available")
        versions.sort(key=lambda s: tuple(int(p) for p in s.lstrip("v").split(".")))
        return versions[-1]
    if not _VER_RE.match(requested):
        raise HTTPException(400, "invalid version format")
    if not os.path.isdir(os.path.join(_BASE_DIR, requested)):
        raise HTTPException(404, f"version {requested} not in cache; publish a GitHub Release first")
    return requested


@router.get("/setup.zip")
async def download_setup_zip(
    token: str = Query(..., description="Client install token (server-side issued)"),
    client_id: str = Query("", description="Client UUID, opzionale ma consigliato"),
    role: str = Query("master", regex=r"^(master|scanner)$"),
    label: str = Query("", description="Etichetta libera (es. SRV principale)"),
    version: str = Query("latest", description="Versione (latest oppure v4.25.2)"),
    backend: str = Query("", description="Backend URL override (default: REACT_APP_BACKEND_URL)"),
) -> StreamingResponse:
    if not _TOKEN_RE.match(token):
        raise HTTPException(400, "invalid token format")
    ver = _resolve_version(version)
    bin_path = os.path.join(_BASE_DIR, ver, "nocinstall.exe")
    if not os.path.isfile(bin_path):
        raise HTTPException(503, f"nocinstall.exe not cached for {ver}")

    # Backend URL: usa env del backend, fallback a request host noto in PROD
    backend_url = (backend or os.environ.get("PUBLIC_BACKEND_URL")
                   or "https://argus.86bit.it").rstrip("/")

    # Sidecar cfg (formato chiave=valore, letto da cmd/installer/main.go:249)
    cfg_lines = [
        f"TOKEN={token}",
        f"BACKEND={backend_url}",
    ]
    if client_id:
        cfg_lines.append(f"CLIENT_ID={client_id}")
    if role:
        cfg_lines.append(f"ROLE={role}")
    if label:
        cfg_lines.append(f"LABEL={label}")
    cfg_body = "\n".join(cfg_lines) + "\n"

    readme = (
        "Argus NOC — Setup connector\n"
        "============================\n\n"
        f"Versione binario : {ver}\n"
        f"Ruolo            : {role}\n"
        f"Backend          : {backend_url}\n"
        f"Cliente          : {client_id or '(token-based)'}\n\n"
        "Come installare\n"
        "---------------\n"
        "1) Estrai TUTTO il contenuto del .zip in una cartella temporanea\n"
        "   (es. C:\\Temp\\ArgusSetup\\). Non spostare solo setup.exe: il file\n"
        "   nocinstall.cfg accanto serve all'installer per leggere token e\n"
        "   URL backend del NOC.\n\n"
        "2) Click destro su setup.exe -> 'Esegui come amministratore'.\n\n"
        "3) Attendi la fine. L'installer crea il servizio Windows '86NocAgent',\n"
        "   lo avvia e si registra al NOC. Entro 30 secondi vedrai il connector\n"
        "   apparire LIVE nella pagina 'Server con Agent' del NOC.\n\n"
        "Risoluzione problemi\n"
        "--------------------\n"
        "- Se Windows Defender blocca l'eseguibile, sblocca dalle proprieta'\n"
        "  del file (tab 'Generale' -> 'Sblocca' in basso).\n"
        "- Se serve un proxy HTTP, imposta la variabile d'ambiente HTTPS_PROXY\n"
        "  prima di lanciare setup.exe.\n"
        "- Log dell'installazione in: %TEMP%\\86noc-install-*.log\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with open(bin_path, "rb") as f:
            z.writestr("setup.exe", f.read())
        z.writestr("nocinstall.cfg", cfg_body)
        z.writestr("LEGGIMI.txt", readme)
    buf.seek(0)

    fname = f"ArgusSetup-{(label or 'connector').replace(' ', '_')}-{ver}.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
