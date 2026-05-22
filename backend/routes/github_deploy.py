"""
github_deploy.py — Webhook GitHub per auto-deploy del Center
============================================================

Quando l'utente fa "Save to GitHub" da Emergent (o un push manuale da
qualsiasi client) sul branch `main`, GitHub chiama questo endpoint che:

  1. Verifica la firma HMAC-SHA256 del payload usando GITHUB_WEBHOOK_SECRET
     (impostata sia in repo Settings → Webhooks sia in backend/.env).
  2. Filtra solo eventi `push` sul branch `refs/heads/main`.
  3. Lancia in background `scripts/auto-deploy.sh` che esegue:
       - `git pull origin main`
       - `pip install -r backend/requirements.txt --quiet` (idempotente)
       - `yarn install --silent` nel frontend (idempotente)
       - `yarn build` nel frontend
       - `sudo systemctl restart noc-backend noc-frontend`
  4. Risponde subito HTTP 202 (l'esecuzione dura ~30-60s, GitHub timeout 10s).

Configurazione richiesta sul server prod:
  - GITHUB_WEBHOOK_SECRET in backend/.env (token random ≥ 32 chars).
  - Lo stesso secret in GitHub repo → Settings → Webhooks → Add webhook:
      URL: https://argus.86bit.it/api/webhooks/github-deploy
      Content type: application/json
      Secret: <stesso valore>
      Events: Just the push event.
  - Sudoer NOPASSWD per il restart, esempio /etc/sudoers.d/noc-deploy:
      arslan ALL=(ALL) NOPASSWD: /bin/systemctl restart noc-backend.service
      arslan ALL=(ALL) NOPASSWD: /bin/systemctl restart noc-frontend.service
  - Lo script auto-deploy.sh deve essere eseguibile dall'utente del backend.

Audit: ogni invocazione (success/skip/failure) viene loggata in
`github_deploy_audit` (collection MongoDB) per troubleshooting.

Endpoint manuale `POST /api/webhooks/github-deploy/trigger` (admin-only,
autenticato JWT) permette di forzare un deploy senza aspettare il push
GitHub — utile per ri-applicare il deploy se il primo fallisce.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .agent_ws import _now  # type: ignore  # riusa helper datetime
from .auth import get_current_user  # type: ignore

logger = logging.getLogger("noc.routes.github_deploy")

# Mongo
from motor.motor_asyncio import AsyncIOMotorClient
_mongo_url = os.environ.get("MONGO_URL")
_db_name = os.environ.get("DB_NAME", "test_database")
_client = AsyncIOMotorClient(_mongo_url) if _mongo_url else None
_db = _client[_db_name] if _client is not None else None

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Path del repo. Override-abile via env per chi installa fuori /home/arslan.
REPO_DIR = os.environ.get("NOC_REPO_DIR", "/home/arslan/86NOCConnectorCenter")
DEPLOY_SCRIPT = os.environ.get(
    "NOC_DEPLOY_SCRIPT",
    str(Path(REPO_DIR) / "scripts" / "auto-deploy.sh"),
)


def _verify_signature(body: bytes, signature: Optional[str], secret: str) -> bool:
    """Verifica HMAC-SHA256 header `X-Hub-Signature-256: sha256=<hex>`.

    GitHub firma il body raw del POST con il secret condiviso. Usiamo
    `hmac.compare_digest` per evitare timing attacks.
    """
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _run_deploy(reason: str, actor: str, ref: str = "main") -> None:
    """Esegue lo script auto-deploy.sh in background. NON propaga errori
    (li logga soltanto in audit collection) perché viene chiamato come
    background task fire-and-forget.
    """
    started = _now()
    audit_id: Optional[str] = None
    try:
        # Audit "started"
        if _db is not None:
            res = await _db.github_deploy_audit.insert_one({
                "event": "deploy_started",
                "reason": reason,
                "actor": actor,
                "ref": ref,
                "started_at": started.isoformat(),
                "deploy_script": DEPLOY_SCRIPT,
                "repo_dir": REPO_DIR,
            })
            audit_id = str(res.inserted_id)

        if not Path(DEPLOY_SCRIPT).exists():
            raise FileNotFoundError(f"deploy script non trovato: {DEPLOY_SCRIPT}")

        # Eseguiamo in subprocess separato e non blocchiamo il loop.
        proc = await asyncio.create_subprocess_exec(
            "bash", DEPLOY_SCRIPT,
            cwd=REPO_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        # Timeout 300s (5 min): yarn build può essere lento al primo run.
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("deploy timed out after 5 minutes")

        log_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        # Trim log a 32KB per non saturare Mongo
        if len(log_text) > 32_768:
            log_text = log_text[-32_768:]

        finished = _now()
        status = "success" if proc.returncode == 0 else "failed"
        if _db is not None:
            await _db.github_deploy_audit.insert_one({
                "event": "deploy_finished",
                "status": status,
                "exit_code": proc.returncode,
                "reason": reason,
                "actor": actor,
                "ref": ref,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_sec": (finished - started).total_seconds(),
                "log": log_text,
            })
        logger.info("auto-deploy %s (exit=%s, dur=%.1fs)",
                    status, proc.returncode, (finished - started).total_seconds())
    except Exception as e:  # noqa: BLE001
        logger.exception("auto-deploy failed: %s", e)
        if _db is not None:
            try:
                await _db.github_deploy_audit.insert_one({
                    "event": "deploy_failed",
                    "status": "exception",
                    "reason": reason,
                    "actor": actor,
                    "ref": ref,
                    "started_at": started.isoformat(),
                    "finished_at": _now().isoformat(),
                    "error": str(e),
                })
            except Exception:  # noqa: BLE001
                pass


@router.post("/github-deploy")
async def github_deploy_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
    x_github_event: Optional[str] = Header(default=None),
    x_github_delivery: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Endpoint pubblico chiamato da GitHub. Sicurezza via HMAC."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        # In assenza del secret rifiutiamo TUTTO: non vogliamo eseguire
        # subprocess su trigger non autenticati.
        raise HTTPException(status_code=503,
                            detail="GITHUB_WEBHOOK_SECRET non configurato nel backend .env")

    body = await request.body()
    if not _verify_signature(body, x_hub_signature_256, secret):
        # Log tentativo non autenticato per audit
        if _db is not None:
            try:
                await _db.github_deploy_audit.insert_one({
                    "event": "signature_invalid",
                    "delivery_id": x_github_delivery,
                    "github_event": x_github_event,
                    "received_at": _now().isoformat(),
                    "remote": request.client.host if request.client else "?",
                })
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(status_code=401, detail="invalid HMAC signature")

    # Ping → 200 (configurazione webhook lato GitHub)
    if x_github_event == "ping":
        return JSONResponse({"ok": True, "pong": True})

    if x_github_event != "push":
        return JSONResponse({"ok": True, "ignored": f"event={x_github_event}"})

    try:
        payload: Dict[str, Any] = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="payload non JSON")

    ref = payload.get("ref", "")
    allowed_refs = (os.environ.get("NOC_DEPLOY_REFS", "refs/heads/main")).split(",")
    if ref not in [r.strip() for r in allowed_refs]:
        if _db is not None:
            try:
                await _db.github_deploy_audit.insert_one({
                    "event": "branch_skipped",
                    "ref": ref,
                    "allowed": allowed_refs,
                    "received_at": _now().isoformat(),
                })
            except Exception:  # noqa: BLE001
                pass
        return JSONResponse({"ok": True, "skipped": ref})

    pusher = payload.get("pusher", {}).get("name", "?")
    head_commit = payload.get("head_commit", {}).get("id", "")[:7]
    reason = f"push by {pusher} ({head_commit})"

    # Fire-and-forget: rispondiamo subito a GitHub (timeout webhook 10s)
    # e lasciamo il deploy completare in background.
    asyncio.create_task(_run_deploy(reason=reason, actor=pusher, ref=ref))

    return JSONResponse(
        {"ok": True, "queued": True, "reason": reason},
        status_code=202,
    )


@router.post("/github-deploy/trigger")
async def github_deploy_manual_trigger(
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Trigger manuale (admin-only) — utile quando il webhook fallisce
    o per forzare un re-deploy. Esegue lo stesso script.
    """
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="admin only")
    actor = current_user.get("email") or current_user.get("id") or "admin"
    asyncio.create_task(_run_deploy(reason="manual trigger", actor=actor, ref="manual"))
    return JSONResponse({"ok": True, "queued": True, "actor": actor}, status_code=202)


@router.get("/github-deploy/audit")
async def github_deploy_audit(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Ritorna le ultime N entry dell'audit log di auto-deploy.
    Utile per verificare lo storico dei deploy + i log per troubleshooting.
    """
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="admin only")
    if _db is None:
        return {"items": [], "count": 0}
    cursor = _db.github_deploy_audit.find(
        {}, {"_id": 0}
    ).sort("started_at", -1).limit(min(max(limit, 1), 100))
    items = await cursor.to_list(length=None)
    return {"items": items, "count": len(items)}


@router.get("/github-deploy/health")
async def github_deploy_health() -> Dict[str, Any]:
    """Pubblico: verifica setup. Comodo come pre-flight prima di
    configurare il webhook su GitHub.
    """
    has_secret = bool(os.environ.get("GITHUB_WEBHOOK_SECRET"))
    repo_ok = Path(REPO_DIR).exists()
    script_ok = Path(DEPLOY_SCRIPT).exists()
    script_exec = script_ok and os.access(DEPLOY_SCRIPT, os.X_OK)
    git_ok = shutil.which("git") is not None
    return {
        "ok": has_secret and repo_ok and script_ok and script_exec and git_ok,
        "webhook_secret_configured": has_secret,
        "repo_dir_exists": repo_ok,
        "repo_dir": REPO_DIR,
        "deploy_script_exists": script_ok,
        "deploy_script_executable": script_exec,
        "deploy_script": DEPLOY_SCRIPT,
        "git_available": git_ok,
    }
