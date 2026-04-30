"""
Hornetsecurity 365 Total Backup Integration
============================================
Polls the custom-generated API endpoint provided by Hornetsecurity Control Panel
(Backups → Generate Report → API link + X-API-KEY) and stores backup status per
client into MongoDB collections:
- hornetsecurity_configs : per-client API URL + encrypted X-API-KEY + scheduling
- backup_job_status      : per-workload latest status snapshots (mailbox, OneDrive, …)
- backup_storage_history : per-tenant storage trend (one point per polling cycle)
- backup_alerts          : derived alerts when backup state degrades

Rate limit: Hornetsecurity enforces 1 request / 5 minutes per endpoint. Default
polling interval is 30 minutes; minimum allowed by config is 5 minutes.

Endpoints exposed:
- GET    /api/clients/{client_id}/backup/hornetsecurity/config
- PUT    /api/clients/{client_id}/backup/hornetsecurity/config
- DELETE /api/clients/{client_id}/backup/hornetsecurity/config
- POST   /api/clients/{client_id}/backup/hornetsecurity/test
- POST   /api/clients/{client_id}/backup/hornetsecurity/poll
- GET    /api/clients/{client_id}/backup/hornetsecurity/status
- GET    /api/clients/{client_id}/backup/hornetsecurity/storage-trend
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api", tags=["hornetsecurity-backup"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class HornetsecurityConfigIn(BaseModel):
    api_url: str = Field(..., min_length=10, max_length=500,
                         description="API link generato dal Control Panel Hornetsecurity (custom per scope/tenants)")
    api_key: str = Field(..., min_length=8, max_length=400,
                         description="X-API-KEY value (mostrato una sola volta in fase di generazione)")
    poll_interval_minutes: int = Field(default=30, ge=5, le=720,
                                       description="Frequenza polling (min 5, default 30, max 720)")
    enabled: bool = Field(default=True)


class HornetsecurityConfigOut(BaseModel):
    client_id: str
    api_url: str
    api_key_preview: str  # solo "****1234" — mai la chiave completa
    poll_interval_minutes: int
    enabled: bool
    last_polled_at: Optional[datetime] = None
    last_poll_status: Optional[str] = None  # "success" | "failed"
    last_poll_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask_key(api_key: str) -> str:
    if not api_key or len(api_key) < 8:
        return "********"
    return f"****{api_key[-4:]}"


def _config_to_out(doc: dict) -> dict:
    return {
        "client_id": doc["client_id"],
        "api_url": doc.get("api_url", ""),
        "api_key_preview": doc.get("api_key_preview", "********"),
        "poll_interval_minutes": doc.get("poll_interval_minutes", 30),
        "enabled": doc.get("enabled", True),
        "last_polled_at": doc.get("last_polled_at"),
        "last_poll_status": doc.get("last_poll_status"),
        "last_poll_error": doc.get("last_poll_error"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def _ensure_client_exists(client_id: str) -> dict:
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CRUD config
# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/backup/hornetsecurity/config")
async def get_hornetsecurity_config(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ritorna la configurazione Hornetsecurity per un cliente (key mascherata)."""
    await _ensure_client_exists(client_id)
    doc = await db.hornetsecurity_configs.find_one({"client_id": client_id}, {"_id": 0})
    if not doc:
        return {"configured": False, "client_id": client_id}
    return {"configured": True, **_config_to_out(doc)}


@router.put("/clients/{client_id}/backup/hornetsecurity/config")
async def set_hornetsecurity_config(
    client_id: str,
    payload: HornetsecurityConfigIn,
    current_user: dict = Depends(get_current_user),
):
    """Crea/aggiorna la configurazione Hornetsecurity di un cliente.

    Solo admin possono scrivere. La X-API-KEY viene crittografata con il
    SecurityManager (Fernet/AES-256) prima di essere salvata. Mai esposta in chiaro
    via API.
    """
    require_admin(current_user)
    await _ensure_client_exists(client_id)

    # Validazione minima URL (deve iniziare con https)
    if not payload.api_url.lower().startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="api_url deve iniziare con https:// (Hornetsecurity API e` solo HTTPS)",
        )

    encrypted_key = security_manager.encrypt_credential(payload.api_key)
    now_iso = _now_utc_iso()

    existing = await db.hornetsecurity_configs.find_one({"client_id": client_id})
    update_doc = {
        "client_id": client_id,
        "api_url": payload.api_url.strip(),
        "api_key_enc": encrypted_key,
        "api_key_preview": _mask_key(payload.api_key),
        "poll_interval_minutes": payload.poll_interval_minutes,
        "enabled": payload.enabled,
        "updated_at": now_iso,
    }
    if not existing:
        update_doc["created_at"] = now_iso

    await db.hornetsecurity_configs.update_one(
        {"client_id": client_id},
        {"$set": update_doc},
        upsert=True,
    )

    audit.warning(
        f"HORNETSECURITY_CONFIG_SAVED by={current_user.get('email')} "
        f"client_id={client_id} url={payload.api_url[:60]}... "
        f"interval={payload.poll_interval_minutes}m enabled={payload.enabled}"
    )

    saved = await db.hornetsecurity_configs.find_one({"client_id": client_id}, {"_id": 0})
    return {"saved": True, **_config_to_out(saved)}


@router.delete("/clients/{client_id}/backup/hornetsecurity/config")
async def delete_hornetsecurity_config(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Rimuove la configurazione Hornetsecurity per un cliente (storico mantenuto)."""
    require_admin(current_user)
    await _ensure_client_exists(client_id)
    result = await db.hornetsecurity_configs.delete_one({"client_id": client_id})
    audit.warning(
        f"HORNETSECURITY_CONFIG_DELETED by={current_user.get('email')} "
        f"client_id={client_id} deleted_count={result.deleted_count}"
    )
    return {"deleted": result.deleted_count > 0}


# ---------------------------------------------------------------------------
# Poll / Test
# ---------------------------------------------------------------------------
async def _fetch_backup_report(api_url: str, api_key: str, timeout: float = 30.0) -> tuple[int, dict | str]:
    """Esegue una GET al report Hornetsecurity. Ritorna (status_code, payload)."""
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(api_url, headers=headers)
            content_type = (r.headers.get("content-type") or "").lower()
            try:
                body = r.json() if "json" in content_type else r.text
            except Exception:
                body = r.text
            return r.status_code, body
    except httpx.TimeoutException:
        return 0, "Timeout durante chiamata API Hornetsecurity"
    except httpx.RequestError as e:
        return 0, f"Errore rete: {e}"


def _parse_workloads(report: dict) -> list[dict]:
    """Normalizza il JSON Hornetsecurity in record per-workload.

    Il payload Hornetsecurity puo` variare leggermente per release; supportiamo i
    layout piu` comuni:
      A) report = { "tenants": [ { "name", "workloads": [...] } ] }
      B) report = { "workloads": [ { "tenant", "user", "type", "status", … } ] }
      C) report = { "data": [...] }   (fallback generico)
    """
    if not isinstance(report, dict):
        return []

    out: list[dict] = []

    def _norm_one(w: dict, default_tenant: str = "") -> dict:
        tenant = (w.get("tenant") or w.get("tenant_name")
                  or w.get("Tenant") or default_tenant or "")
        wid = (w.get("id") or w.get("workload_id") or w.get("WorkloadId")
               or w.get("user_id") or w.get("UserId")
               or w.get("user") or w.get("UserName") or "")
        wname = (w.get("name") or w.get("display_name") or w.get("DisplayName")
                 or w.get("user") or w.get("UserName") or wid or "")
        wtype = (w.get("type") or w.get("workload_type") or w.get("WorkloadType")
                 or w.get("service") or "unknown")
        status = (w.get("status") or w.get("backup_status") or w.get("BackupStatus")
                  or w.get("state") or w.get("Result") or "unknown")
        last_at = (w.get("last_backup_time") or w.get("last_backup")
                   or w.get("LastBackupTime") or w.get("last_run")
                   or w.get("LastRun") or w.get("last_successful_backup"))
        size_bytes = (w.get("size_bytes") or w.get("backup_size")
                      or w.get("BackupSize") or w.get("size") or 0)
        err = (w.get("error") or w.get("error_message")
               or w.get("ErrorMessage") or w.get("last_error") or None)
        return {
            "tenant": str(tenant)[:200],
            "workload_id": str(wid)[:300],
            "workload_name": str(wname)[:300],
            "workload_type": str(wtype).lower()[:50],
            "status": str(status).lower()[:30],
            "last_backup_time": last_at,
            "size_bytes": int(size_bytes) if isinstance(size_bytes, (int, float)) else 0,
            "error": str(err)[:500] if err else None,
        }

    # Layout A
    tenants = report.get("tenants")
    if isinstance(tenants, list):
        for t in tenants:
            t_name = t.get("name") or t.get("tenant_name") or ""
            for w in (t.get("workloads") or t.get("users") or []):
                if isinstance(w, dict):
                    out.append(_norm_one(w, default_tenant=t_name))

    # Layout B
    if not out and isinstance(report.get("workloads"), list):
        for w in report["workloads"]:
            if isinstance(w, dict):
                out.append(_norm_one(w))

    # Layout C
    if not out and isinstance(report.get("data"), list):
        for w in report["data"]:
            if isinstance(w, dict):
                out.append(_norm_one(w))

    return out


def _parse_storage_per_tenant(report: dict) -> dict[str, int]:
    """Estrae lo storage usato per tenant. Ritorna { tenant_name: bytes }."""
    storage: dict[str, int] = {}
    if not isinstance(report, dict):
        return storage
    tenants = report.get("tenants")
    if isinstance(tenants, list):
        for t in tenants:
            tname = t.get("name") or t.get("tenant_name") or "unknown"
            sb = (t.get("storage_used_bytes") or t.get("size_bytes")
                  or t.get("StorageUsed") or 0)
            if isinstance(sb, (int, float)) and sb > 0:
                storage[str(tname)] = int(sb)
    # fallback: sum from workloads
    if not storage:
        agg: dict[str, int] = {}
        for w in _parse_workloads(report):
            agg[w["tenant"]] = agg.get(w["tenant"], 0) + (w.get("size_bytes") or 0)
        storage = {k: v for k, v in agg.items() if v > 0}
    return storage


async def _persist_poll_results(client_id: str, report: dict) -> dict:
    """Salva workloads + storage + emette alert su backup falliti."""
    now_dt = datetime.now(timezone.utc)
    workloads = _parse_workloads(report)
    storage = _parse_storage_per_tenant(report)

    failed_count = 0
    success_count = 0

    # Upsert per-workload status (ultimo stato noto)
    for w in workloads:
        await db.backup_job_status.update_one(
            {
                "client_id": client_id,
                "tenant": w["tenant"],
                "workload_id": w["workload_id"],
            },
            {"$set": {
                "client_id": client_id,
                "tenant": w["tenant"],
                "workload_id": w["workload_id"],
                "workload_name": w["workload_name"],
                "workload_type": w["workload_type"],
                "status": w["status"],
                "last_backup_time": w["last_backup_time"],
                "size_bytes": w["size_bytes"],
                "error": w["error"],
                "captured_at": now_dt.isoformat(),
                "source": "hornetsecurity",
            }},
            upsert=True,
        )
        if w["status"] in ("failed", "error", "fail", "ko"):
            failed_count += 1
            # alert dedup: 1 alert aperto per workload
            await db.backup_alerts.update_one(
                {
                    "client_id": client_id,
                    "tenant": w["tenant"],
                    "workload_id": w["workload_id"],
                    "resolved": False,
                },
                {"$set": {
                    "client_id": client_id,
                    "tenant": w["tenant"],
                    "workload_id": w["workload_id"],
                    "workload_name": w["workload_name"],
                    "workload_type": w["workload_type"],
                    "severity": "warning",
                    "message": w.get("error") or f"Backup fallito per {w['workload_name']}",
                    "last_seen": now_dt.isoformat(),
                    "resolved": False,
                    "source": "hornetsecurity",
                }, "$setOnInsert": {"created_at": now_dt.isoformat()}},
                upsert=True,
            )
        else:
            success_count += 1
            # auto-resolve alert se status non e` failed
            await db.backup_alerts.update_many(
                {
                    "client_id": client_id,
                    "tenant": w["tenant"],
                    "workload_id": w["workload_id"],
                    "resolved": False,
                },
                {"$set": {
                    "resolved": True,
                    "resolved_at": now_dt.isoformat(),
                }},
            )

    # Storia storage per trend grafico (un sample per polling cycle)
    for tenant_name, bytes_used in storage.items():
        await db.backup_storage_history.insert_one({
            "client_id": client_id,
            "tenant": tenant_name,
            "size_bytes": int(bytes_used),
            "recorded_at": now_dt.isoformat(),
        })

    return {
        "workloads_total": len(workloads),
        "workloads_failed": failed_count,
        "workloads_success": success_count,
        "tenants_with_storage": len(storage),
    }


@router.post("/clients/{client_id}/backup/hornetsecurity/test")
async def test_hornetsecurity_connection(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Esegue una chiamata di test (NON persiste niente)."""
    require_admin(current_user)
    await _ensure_client_exists(client_id)

    cfg = await db.hornetsecurity_configs.find_one({"client_id": client_id}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=404, detail="Configurazione Hornetsecurity non trovata")

    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    code, body = await _fetch_backup_report(cfg["api_url"], api_key)

    ok = code == 200 and isinstance(body, dict)
    workloads = _parse_workloads(body) if ok else []
    storage = _parse_storage_per_tenant(body) if ok else {}

    return {
        "ok": ok,
        "http_status": code,
        "workloads_detected": len(workloads),
        "tenants_with_storage": len(storage),
        "raw_response_excerpt": (str(body)[:500] if not ok else None),
        "sample_workload": workloads[0] if workloads else None,
    }


@router.post("/clients/{client_id}/backup/hornetsecurity/poll")
async def poll_hornetsecurity(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Forza un polling immediato (rispetta rate limit Hornetsecurity 1 req/5min)."""
    require_admin(current_user)
    await _ensure_client_exists(client_id)

    cfg = await db.hornetsecurity_configs.find_one({"client_id": client_id}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=404, detail="Configurazione Hornetsecurity non trovata")
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=400, detail="Polling disabilitato per questo cliente")

    # Anti-flood: rispetta minimo 5 minuti tra poll consecutivi
    last_polled_at = cfg.get("last_polled_at")
    if last_polled_at:
        try:
            last_dt = datetime.fromisoformat(last_polled_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < 300:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit Hornetsecurity: aspetta ancora {int(300 - age)}s prima del prossimo poll",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    code, body = await _fetch_backup_report(cfg["api_url"], api_key)
    now_iso = _now_utc_iso()

    if code != 200 or not isinstance(body, dict):
        await db.hornetsecurity_configs.update_one(
            {"client_id": client_id},
            {"$set": {
                "last_polled_at": now_iso,
                "last_poll_status": "failed",
                "last_poll_error": f"HTTP {code}: {str(body)[:300]}",
            }},
        )
        raise HTTPException(
            status_code=502,
            detail=f"API Hornetsecurity non ha risposto correttamente (HTTP {code}): {str(body)[:200]}",
        )

    summary = await _persist_poll_results(client_id, body)
    await db.hornetsecurity_configs.update_one(
        {"client_id": client_id},
        {"$set": {
            "last_polled_at": now_iso,
            "last_poll_status": "success",
            "last_poll_error": None,
            "last_poll_summary": summary,
        }},
    )

    audit.info(
        f"HORNETSECURITY_POLL_OK by={current_user.get('email')} "
        f"client_id={client_id} workloads={summary['workloads_total']} "
        f"failed={summary['workloads_failed']}"
    )
    return {"ok": True, "polled_at": now_iso, **summary}


# ---------------------------------------------------------------------------
# Read endpoints (UI)
# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/backup/hornetsecurity/status")
async def get_backup_status(
    client_id: str,
    workload_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Lista latest status per workload del cliente."""
    await _ensure_client_exists(client_id)
    query: dict[str, Any] = {"client_id": client_id, "source": "hornetsecurity"}
    if workload_type:
        query["workload_type"] = workload_type.lower()
    if status_filter:
        query["status"] = status_filter.lower()

    cursor = db.backup_job_status.find(query, {"_id": 0}).sort("workload_name", 1).limit(2000)
    items = await cursor.to_list(2000)

    # aggregate per status
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for it in items:
        by_status[it.get("status", "unknown")] = by_status.get(it.get("status", "unknown"), 0) + 1
        by_type[it.get("workload_type", "unknown")] = by_type.get(it.get("workload_type", "unknown"), 0) + 1

    # active alerts
    active_alerts = await db.backup_alerts.count_documents({
        "client_id": client_id, "resolved": False, "source": "hornetsecurity",
    })

    return {
        "items": items,
        "totals": {
            "by_status": by_status,
            "by_type": by_type,
            "total_items": len(items),
            "active_alerts": active_alerts,
        },
    }


@router.get("/clients/{client_id}/backup/hornetsecurity/storage-trend")
async def get_storage_trend(
    client_id: str,
    days: int = 30,
    current_user: dict = Depends(get_current_user),
):
    """Trend storage per tenant negli ultimi N giorni."""
    await _ensure_client_exists(client_id)
    days = max(1, min(days, 180))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = db.backup_storage_history.find(
        {"client_id": client_id, "recorded_at": {"$gte": since}},
        {"_id": 0},
    ).sort("recorded_at", 1).limit(10000)
    rows = await cursor.to_list(10000)
    return {"days": days, "points": rows}


@router.get("/clients/{client_id}/backup/hornetsecurity/alerts")
async def get_backup_alerts(
    client_id: str,
    only_active: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """Alert backup falliti per cliente (default solo non risolti)."""
    await _ensure_client_exists(client_id)
    query: dict[str, Any] = {"client_id": client_id, "source": "hornetsecurity"}
    if only_active:
        query["resolved"] = False
    cursor = db.backup_alerts.find(query, {"_id": 0}).sort("last_seen", -1).limit(500)
    rows = await cursor.to_list(500)
    return {"alerts": rows, "count": len(rows)}
