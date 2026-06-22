"""Endpoint temporaneo per servire binari Connector pre-release.

Pensato come "preview mirror" per fornire all'operatore i binari del
Connector compilati in preview, da scaricare e ri-caricare come asset
di una GitHub Release ufficiale. NON usare in PROD: e' senza auth e
senza rate-limit, esposto solo per il deploy della v4.23.0.

Da rimuovere appena la GitHub Release v4.23.0 e' pubblicata.
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api/preview-releases", tags=["preview-releases"])

_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "release-bin",
)
_SAFE_RE = re.compile(r"^[A-Za-z0-9._+-]+$")


@router.get("")
async def list_releases() -> JSONResponse:
    """Elenca tutte le release pre-compilate disponibili in preview."""
    out = {}
    if not os.path.isdir(_BASE_DIR):
        return JSONResponse({"releases": []})
    for ver in sorted(os.listdir(_BASE_DIR)):
        vdir = os.path.join(_BASE_DIR, ver)
        if not os.path.isdir(vdir):
            continue
        files = []
        for fn in sorted(os.listdir(vdir)):
            fp = os.path.join(vdir, fn)
            if os.path.isfile(fp):
                files.append({"name": fn, "size": os.path.getsize(fp)})
        out[ver] = files
    return JSONResponse({"releases": out})


@router.get("/{version}/{filename}")
async def download_binary(version: str, filename: str) -> FileResponse:
    if not _SAFE_RE.match(version) or not _SAFE_RE.match(filename):
        raise HTTPException(status_code=400, detail="version/filename invalido")
    path = os.path.join(_BASE_DIR, version, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"non trovato: {version}/{filename}")
    media_type = "application/octet-stream"
    if filename.endswith(".exe"):
        media_type = "application/vnd.microsoft.portable-executable"
    elif filename.endswith(".txt") or filename.startswith("SHA"):
        media_type = "text/plain"
    return FileResponse(path=path, filename=filename, media_type=media_type)
