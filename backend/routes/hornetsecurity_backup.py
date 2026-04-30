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


# Sub-group extraction (per-domain bucketing within a single Hornetsecurity tenant)
# ---------------------------------------------------------------------------
SUBGROUP_UNGROUPED = "_ungrouped_"  # workloads without an identifiable email domain


def _extract_sub_group(workload: dict) -> str:
    """Estrae il sotto-gruppo (dominio email) di un workload dentro un tenant.

    Regole:
    1. Se `workload_user` contiene un `@`, ritorna il dominio (lowercase).
    2. Se `workload_name` contiene un `@` (es. SharePoint con email mailbox), idem.
    3. Altrimenti ritorna SUBGROUP_UNGROUPED (sotto-gruppo "Senza dominio") in
       modo che SharePoint senza owner email, Entra ID di sistema, o workload
       con metadata mancanti restino visibili e mappabili separatamente.
    """
    user = (workload.get("workload_user") or "").strip().lower()
    if "@" in user:
        dom = user.split("@", 1)[1].strip().rstrip(".")
        if dom:
            return dom
    name = (workload.get("workload_name") or "").strip().lower()
    if "@" in name:
        dom = name.split("@", 1)[1].strip().rstrip(".")
        if dom:
            return dom
    return SUBGROUP_UNGROUPED


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


def _normalize_status(backup_state: Any, state_enum: Any) -> str:
    """Mappa il backupState Hornetsecurity al nostro vocabolario (success/failed/in_progress/excluded/not_applicable/unknown).

    backupStateEnum noti (operational report Hornetsecurity 365 Total Backup):
        4 = Protected (success)
        2 = No <workload> (not_applicable: feature non presente per l'utente)
        Altri valori: dedotti dalla stringa backupState.
    """
    s = (str(backup_state) if backup_state is not None else "").strip().lower()
    if not s:
        return "unknown"
    if s in ("protected", "protected (disabled)"):
        return "success"
    if "fail" in s or "error" in s:
        return "failed"
    if "in progress" in s or "running" in s:
        return "in_progress"
    if "excluded" in s:
        return "excluded"
    if s.startswith("no ") or s in ("no item", "no oneDrive", "no teams chats",
                                    "no mailbox", "no entra id", "no sharepoint site"):
        return "not_applicable"
    return s.replace(" ", "_")


def _parse_workloads(report: dict) -> list[dict]:
    """Normalizza il JSON Hornetsecurity in record per-workload.

    Layout supportati (ordine di rilevamento):
      1) Hornetsecurity Operational Report (PRINCIPALE):
         { "statistics": [
             { "customerName", "office365Organisation",
               "objectTypeBackedUp" (Mailbox/OneDrive/SharePoint Files/...),
               "objectName", "objectDetails", "backupState",
               "backupStateEnum", "lastBackup", "lastErrorMessage" } ] }
      2) Tenants nested:    { "tenants": [ { "name", "workloads": [...] } ] }
      3) Workloads flat:    { "workloads": [...] }
      4) Generic data:      { "data": [...] }
    """
    if not isinstance(report, dict):
        return []

    out: list[dict] = []

    # Layout 1: Operational Report Hornetsecurity (REALE)
    stats = report.get("statistics")
    if isinstance(stats, list) and stats:
        for s in stats:
            if not isinstance(s, dict):
                continue
            tenant = (s.get("office365Organisation") or s.get("customerName") or "")
            wid = (s.get("objectDetails") or s.get("objectName") or "")
            wname = (s.get("objectName") or s.get("objectDetails") or "")
            wtype_raw = str(s.get("objectTypeBackedUp") or "unknown")
            # Normalize type ("SharePoint Files" -> "sharepoint", "User Teams Chats" -> "teams")
            wtype_lc = wtype_raw.lower().replace(" ", "_")
            if "sharepoint" in wtype_lc:
                wtype_lc = "sharepoint"
            elif "teams" in wtype_lc:
                wtype_lc = "teams"
            elif "onedrive" in wtype_lc:
                wtype_lc = "onedrive"
            elif "mailbox" in wtype_lc:
                wtype_lc = "mailbox"
            elif "entra" in wtype_lc:
                wtype_lc = "entra_id"
            elif "planner" in wtype_lc:
                wtype_lc = "planner"
            err = s.get("lastErrorMessage")
            if err and str(err).strip().upper() in ("N/A", "NA", "NONE", ""):
                err = None
            out.append({
                "tenant": str(tenant)[:200],
                "tenant_long": str(s.get("customerName") or "")[:200],
                "workload_id": f"{tenant}|{wtype_lc}|{wid}"[:300],
                "workload_name": str(wname)[:300],
                "workload_user": str(s.get("objectDetails") or "")[:200],
                "workload_subcategory": str(s.get("objectTypeSubcategory") or "")[:50],
                "workload_type": wtype_lc[:50],
                "status": _normalize_status(s.get("backupState"), s.get("backupStateEnum")),
                "status_raw": str(s.get("backupState") or "")[:80],
                "last_backup_time": s.get("lastBackup"),
                "size_bytes": 0,  # Operational Report non include size per workload
                "error": str(err)[:500] if err else None,
            })
        return out

    # Fallback parsers per altri possibili layout
    def _norm_one(w: dict, default_tenant: str = "") -> dict:
        tenant = (w.get("tenant") or w.get("tenant_name") or w.get("Tenant") or default_tenant or "")
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
            "tenant_long": str(tenant)[:200],
            "workload_id": str(wid)[:300],
            "workload_name": str(wname)[:300],
            "workload_user": str(wid)[:200],
            "workload_subcategory": "",
            "workload_type": str(wtype).lower()[:50],
            "status": str(status).lower()[:30],
            "status_raw": str(status)[:80],
            "last_backup_time": last_at,
            "size_bytes": int(size_bytes) if isinstance(size_bytes, (int, float)) else 0,
            "error": str(err)[:500] if err else None,
        }

    tenants = report.get("tenants")
    if isinstance(tenants, list):
        for t in tenants:
            t_name = t.get("name") or t.get("tenant_name") or ""
            for w in (t.get("workloads") or t.get("users") or []):
                if isinstance(w, dict):
                    out.append(_norm_one(w, default_tenant=t_name))
    if not out and isinstance(report.get("workloads"), list):
        for w in report["workloads"]:
            if isinstance(w, dict):
                out.append(_norm_one(w))
    if not out and isinstance(report.get("data"), list):
        for w in report["data"]:
            if isinstance(w, dict):
                out.append(_norm_one(w))

    return out


def _parse_storage_per_tenant(report: dict) -> dict[str, int]:
    """Estrae lo storage usato per tenant.

    NOTA: l'Operational Report Hornetsecurity 365 Total Backup NON include
    informazioni di storage per workload o per tenant. Questa funzione resta
    per compatibilita` futura (se Hornetsecurity rilascia un Storage Report
    dedicato) e per i layout legacy.
    """
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
    if not storage:
        agg: dict[str, int] = {}
        for w in _parse_workloads(report):
            if w.get("size_bytes"):
                agg[w["tenant"]] = agg.get(w["tenant"], 0) + (w.get("size_bytes") or 0)
        storage = {k: v for k, v in agg.items() if v > 0}
    return storage


async def _persist_poll_results_global(report: dict) -> dict:
    """Salva globalmente workloads + emette alert su backup falliti.

    Usato dal polling globale: la chiave di unicita` e` (tenant, workload_id),
    NON client_id (che e` derivato in lettura via mapping). Status considerati
    falliti veri (alert): solo "failed" (Hornetsecurity 'Last Backup Failed').
    "not_applicable" / "excluded" non generano alert (sono stati informativi).
    """
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    workloads = _parse_workloads(report)
    storage = _parse_storage_per_tenant(report)

    counts = {"failed": 0, "success": 0, "in_progress": 0,
              "not_applicable": 0, "excluded": 0, "other": 0}
    tenants_seen: set[str] = set()

    for w in workloads:
        tenants_seen.add(w["tenant"])
        sub_group = _extract_sub_group(w)
        await db.backup_job_status.update_one(
            {"tenant": w["tenant"], "workload_id": w["workload_id"]},
            {"$set": {
                "tenant": w["tenant"],
                "tenant_long": w["tenant_long"],
                "workload_id": w["workload_id"],
                "workload_name": w["workload_name"],
                "workload_user": w["workload_user"],
                "workload_subcategory": w["workload_subcategory"],
                "workload_type": w["workload_type"],
                "sub_group": sub_group,
                "status": w["status"],
                "status_raw": w["status_raw"],
                "last_backup_time": w["last_backup_time"],
                "size_bytes": w["size_bytes"],
                "error": w["error"],
                "captured_at": now_iso,
                "source": "hornetsecurity",
            }},
            upsert=True,
        )
        bucket = w["status"] if w["status"] in counts else "other"
        counts[bucket] += 1

        if w["status"] == "failed":
            await db.backup_alerts.update_one(
                {"tenant": w["tenant"], "workload_id": w["workload_id"], "resolved": False},
                {"$set": {
                    "tenant": w["tenant"],
                    "tenant_long": w["tenant_long"],
                    "workload_id": w["workload_id"],
                    "workload_name": w["workload_name"],
                    "workload_type": w["workload_type"],
                    "sub_group": sub_group,
                    "severity": "warning",
                    "message": w.get("error") or f"Backup fallito per {w['workload_name']} ({w['status_raw']})",
                    "last_seen": now_iso,
                    "resolved": False,
                    "source": "hornetsecurity",
                }, "$setOnInsert": {"created_at": now_iso}},
                upsert=True,
            )
        else:
            await db.backup_alerts.update_many(
                {"tenant": w["tenant"], "workload_id": w["workload_id"], "resolved": False},
                {"$set": {"resolved": True, "resolved_at": now_iso}},
            )

    for tenant_name, bytes_used in storage.items():
        await db.backup_storage_history.insert_one({
            "tenant": tenant_name,
            "size_bytes": int(bytes_used),
            "recorded_at": now_iso,
        })

    return {
        "workloads_total": len(workloads),
        "workloads_failed": counts["failed"],
        "workloads_success": counts["success"],
        "workloads_in_progress": counts["in_progress"],
        "workloads_not_applicable": counts["not_applicable"],
        "workloads_excluded": counts["excluded"],
        "tenants_seen": len(tenants_seen),
        "tenants_with_storage": len(storage),
    }


async def _persist_poll_results(client_id: str, report: dict) -> dict:
    """[Legacy] Persistenza per-cliente (modalita` storica). Mantiene compat
    con il design originale ma viene chiamata ora da poll forzato lato cliente."""
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
# Read endpoints (UI) — leggono dati globali filtrati via mapping cliente↔tenant
# ---------------------------------------------------------------------------
async def _resolve_client_tenants(client_id: str) -> list[str]:
    """[Compat] Ritorna solo nomi tenant (legacy). Per la nuova logica con
    sub-group usare `_resolve_client_filters`.
    """
    filters = await _resolve_client_filters(client_id)
    return sorted({f["tenant"] for f in filters})


async def _resolve_client_filters(client_id: str) -> list[dict]:
    """Ritorna i filtri tenant/sub_group di un cliente.

    Ogni elemento del mapping puo` essere:
      - string  → mapping legacy "tutto il tenant"  → {tenant, sub_groups: None}
      - dict    → {tenant, sub_groups: [...] | None}
        * sub_groups None / vuoto / mancante → tutto il tenant
        * sub_groups lista non vuota → solo quei domini
    """
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "hornetsecurity_tenants": 1})
    if not client:
        return []
    raw = client.get("hornetsecurity_tenants") or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            if item.strip():
                out.append({"tenant": item.strip(), "sub_groups": None})
        elif isinstance(item, dict):
            t = (item.get("tenant") or "").strip()
            if not t:
                continue
            sg = item.get("sub_groups")
            if isinstance(sg, list):
                sg_clean = sorted({str(x).strip().lower() for x in sg if x and str(x).strip()})
                out.append({"tenant": t, "sub_groups": sg_clean if sg_clean else None})
            else:
                out.append({"tenant": t, "sub_groups": None})
    return out


def _build_mongo_filter_for_client(filters: list[dict], extra_match: dict | None = None) -> dict:
    """Costruisce una query Mongo `$or` partendo dai filtri tenant/sub_group.

    Se `filters` e` vuoto, ritorna un match impossibile (`__no_match__`) per
    evitare che la mancanza di mapping mostri tutto il dataset.
    """
    if not filters:
        return {"_no_mapping_": True}  # impossibile → 0 risultati
    or_blocks: list[dict] = []
    for f in filters:
        block: dict = {"tenant": f["tenant"]}
        if f.get("sub_groups"):
            block["sub_group"] = {"$in": f["sub_groups"]}
        if extra_match:
            block = {**block, **extra_match}
        or_blocks.append(block)
    if len(or_blocks) == 1:
        return or_blocks[0]
    return {"$or": or_blocks}


@router.get("/clients/{client_id}/backup/hornetsecurity/status")
async def get_backup_status(
    client_id: str,
    workload_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Lista ultimi status per workload del cliente, filtrati via mapping tenant.

    Cerca prima nei dati globali (poll globale); fa fallback ai dati legacy
    per-cliente per compatibilita`.
    """
    await _ensure_client_exists(client_id)
    filters = await _resolve_client_filters(client_id)
    tenants = sorted({f["tenant"] for f in filters})

    # Query globale via mapping (con sub_group se specificato)
    query: dict[str, Any] = {"source": "hornetsecurity"}
    if filters:
        mapping_q = _build_mongo_filter_for_client(filters)
        query.update(mapping_q)
    else:
        # Fallback: dati legacy per-cliente (config storica)
        query["client_id"] = client_id
    if workload_type:
        query["workload_type"] = workload_type.lower()
    if status_filter:
        query["status"] = status_filter.lower()

    cursor = db.backup_job_status.find(query, {"_id": 0}).sort("workload_name", 1).limit(5000)
    items = await cursor.to_list(5000)

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_tenant: dict[str, int] = {}
    by_sub_group: dict[str, int] = {}
    for it in items:
        by_status[it.get("status", "unknown")] = by_status.get(it.get("status", "unknown"), 0) + 1
        by_type[it.get("workload_type", "unknown")] = by_type.get(it.get("workload_type", "unknown"), 0) + 1
        by_tenant[it.get("tenant", "unknown")] = by_tenant.get(it.get("tenant", "unknown"), 0) + 1
        sg = it.get("sub_group") or SUBGROUP_UNGROUPED
        by_sub_group[sg] = by_sub_group.get(sg, 0) + 1

    alert_query: dict[str, Any] = {"resolved": False, "source": "hornetsecurity"}
    if filters:
        alert_query.update(_build_mongo_filter_for_client(filters))
    else:
        alert_query["client_id"] = client_id
    active_alerts = await db.backup_alerts.count_documents(alert_query)

    return {
        "mapped_tenants": tenants,
        "mapped_filters": filters,
        "items": items,
        "totals": {
            "by_status": by_status,
            "by_type": by_type,
            "by_tenant": by_tenant,
            "by_sub_group": by_sub_group,
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
    """Trend storage per tenant del cliente, negli ultimi N giorni."""
    await _ensure_client_exists(client_id)
    filters = await _resolve_client_filters(client_id)
    days = max(1, min(days, 180))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query: dict[str, Any] = {"recorded_at": {"$gte": since}}
    if filters:
        # storage_history e` aggregato per tenant (no sub_group), filtro solo per nome
        tenants = sorted({f["tenant"] for f in filters})
        query["tenant"] = {"$in": tenants}
    else:
        query["client_id"] = client_id
    cursor = db.backup_storage_history.find(query, {"_id": 0}).sort("recorded_at", 1).limit(10000)
    rows = await cursor.to_list(10000)
    return {"days": days, "points": rows}


@router.get("/clients/{client_id}/backup/hornetsecurity/alerts")
async def get_backup_alerts(
    client_id: str,
    only_active: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """Alert backup falliti del cliente (filtrati via mapping tenant + sub_group)."""
    await _ensure_client_exists(client_id)
    filters = await _resolve_client_filters(client_id)
    query: dict[str, Any] = {"source": "hornetsecurity"}
    if filters:
        query.update(_build_mongo_filter_for_client(filters))
    else:
        query["client_id"] = client_id
    if only_active:
        query["resolved"] = False
    cursor = db.backup_alerts.find(query, {"_id": 0}).sort("last_seen", -1).limit(500)
    rows = await cursor.to_list(500)
    return {"alerts": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# GLOBAL CONFIG — config a livello Center (singola key per tutti i tenant)
# ---------------------------------------------------------------------------
GLOBAL_CONFIG_ID = "global"


class HornetsecurityGlobalConfigIn(BaseModel):
    api_url: str = Field(..., min_length=10, max_length=500)
    api_key: str = Field(..., min_length=4, max_length=400)
    poll_interval_minutes: int = Field(default=30, ge=5, le=720)
    enabled: bool = Field(default=True)


@router.get("/admin/hornetsecurity/global-config")
async def get_hornetsecurity_global_config(current_user: dict = Depends(get_current_user)):
    """Config Hornetsecurity globale (livello Center)."""
    require_admin(current_user)
    doc = await db.hornetsecurity_global_config.find_one({"_id": GLOBAL_CONFIG_ID}, {"_id": 0})
    if not doc:
        return {"configured": False}
    return {
        "configured": True,
        "api_url": doc.get("api_url", ""),
        "api_key_preview": doc.get("api_key_preview", "********"),
        "poll_interval_minutes": doc.get("poll_interval_minutes", 30),
        "enabled": doc.get("enabled", True),
        "last_polled_at": doc.get("last_polled_at"),
        "last_poll_status": doc.get("last_poll_status"),
        "last_poll_error": doc.get("last_poll_error"),
        "last_poll_summary": doc.get("last_poll_summary"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.put("/admin/hornetsecurity/global-config")
async def set_hornetsecurity_global_config(
    payload: HornetsecurityGlobalConfigIn,
    current_user: dict = Depends(get_current_user),
):
    """Crea/aggiorna la config globale Hornetsecurity (una per Center)."""
    require_admin(current_user)
    if not payload.api_url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="api_url deve iniziare con https://")
    encrypted_key = security_manager.encrypt_credential(payload.api_key)
    now_iso = _now_utc_iso()
    existing = await db.hornetsecurity_global_config.find_one({"_id": GLOBAL_CONFIG_ID})
    update_doc = {
        "_id": GLOBAL_CONFIG_ID,
        "api_url": payload.api_url.strip(),
        "api_key_enc": encrypted_key,
        "api_key_preview": _mask_key(payload.api_key),
        "poll_interval_minutes": payload.poll_interval_minutes,
        "enabled": payload.enabled,
        "updated_at": now_iso,
    }
    if not existing:
        update_doc["created_at"] = now_iso
    await db.hornetsecurity_global_config.update_one(
        {"_id": GLOBAL_CONFIG_ID}, {"$set": update_doc}, upsert=True,
    )
    audit.warning(
        f"HORNETSECURITY_GLOBAL_CONFIG_SAVED by={current_user.get('email')} "
        f"interval={payload.poll_interval_minutes}m enabled={payload.enabled}"
    )
    return {"saved": True}


@router.delete("/admin/hornetsecurity/global-config")
async def delete_hornetsecurity_global_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.hornetsecurity_global_config.delete_one({"_id": GLOBAL_CONFIG_ID})
    audit.warning(f"HORNETSECURITY_GLOBAL_CONFIG_DELETED by={current_user.get('email')}")
    return {"deleted": res.deleted_count > 0}


@router.post("/admin/hornetsecurity/test")
async def test_hornetsecurity_global(current_user: dict = Depends(get_current_user)):
    """Esegue una chiamata di test alla config globale (no persistenza)."""
    require_admin(current_user)
    cfg = await db.hornetsecurity_global_config.find_one({"_id": GLOBAL_CONFIG_ID}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=404, detail="Config globale non configurata")
    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    code, body = await _fetch_backup_report(cfg["api_url"], api_key)
    ok = code == 200 and isinstance(body, dict)
    workloads = _parse_workloads(body) if ok else []
    tenants = sorted({w["tenant"] for w in workloads if w["tenant"]})
    by_status: dict[str, int] = {}
    for w in workloads:
        by_status[w["status"]] = by_status.get(w["status"], 0) + 1
    return {
        "ok": ok,
        "http_status": code,
        "workloads_detected": len(workloads),
        "tenants_detected": len(tenants),
        "tenants": tenants,
        "by_status": by_status,
        "raw_response_excerpt": (str(body)[:500] if not ok else None),
    }


@router.post("/admin/hornetsecurity/poll")
async def poll_hornetsecurity_global(current_user: dict = Depends(get_current_user)):
    """Forza un polling globale immediato (rispetta rate limit 5min)."""
    require_admin(current_user)
    cfg = await db.hornetsecurity_global_config.find_one({"_id": GLOBAL_CONFIG_ID}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=404, detail="Config globale non configurata")
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=400, detail="Polling disabilitato")

    last_polled_at = cfg.get("last_polled_at")
    if last_polled_at:
        try:
            last_dt = datetime.fromisoformat(str(last_polled_at).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < 300:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit Hornetsecurity: aspetta ancora {int(300 - age)}s",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    code, body = await _fetch_backup_report(cfg["api_url"], api_key)
    now_iso = _now_utc_iso()
    if code != 200 or not isinstance(body, dict):
        await db.hornetsecurity_global_config.update_one(
            {"_id": GLOBAL_CONFIG_ID},
            {"$set": {
                "last_polled_at": now_iso, "last_poll_status": "failed",
                "last_poll_error": f"HTTP {code}: {str(body)[:300]}",
            }},
        )
        raise HTTPException(
            status_code=502,
            detail=f"API Hornetsecurity HTTP {code}: {str(body)[:200]}",
        )

    summary = await _persist_poll_results_global(body)
    await db.hornetsecurity_global_config.update_one(
        {"_id": GLOBAL_CONFIG_ID},
        {"$set": {
            "last_polled_at": now_iso, "last_poll_status": "success",
            "last_poll_error": None, "last_poll_summary": summary,
        }},
    )
    audit.info(
        f"HORNETSECURITY_GLOBAL_POLL_OK by={current_user.get('email')} "
        f"workloads={summary['workloads_total']} failed={summary['workloads_failed']} "
        f"tenants={summary['tenants_seen']}"
    )
    return {"ok": True, "polled_at": now_iso, **summary}


@router.get("/admin/hornetsecurity/tenants")
async def list_detected_tenants(current_user: dict = Depends(get_current_user)):
    """Lista i tenant Hornetsecurity rilevati nei dati ingestiti, con statistiche."""
    require_admin(current_user)
    pipeline = [
        {"$match": {"source": "hornetsecurity"}},
        {"$group": {
            "_id": "$tenant",
            "tenant_long": {"$first": "$tenant_long"},
            "workloads_total": {"$sum": 1},
            "workloads_failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "workloads_protected": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
            "sub_groups": {"$addToSet": "$sub_group"},
            "last_seen": {"$max": "$captured_at"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.backup_job_status.aggregate(pipeline).to_list(500)
    out = []
    for r in rows:
        if not r.get("_id"):
            continue
        sgs = [s for s in (r.get("sub_groups") or []) if s]
        out.append({
            "tenant": r["_id"],
            "tenant_long": r.get("tenant_long"),
            "workloads_total": r.get("workloads_total", 0),
            "workloads_failed": r.get("workloads_failed", 0),
            "workloads_protected": r.get("workloads_protected", 0),
            "sub_groups_count": len(sgs),
            "last_seen": r.get("last_seen"),
        })

    # Mapping clienti → tenant per UI
    mappings = []
    async for c in db.clients.find({}, {"_id": 0, "id": 1, "name": 1, "hornetsecurity_tenants": 1}):
        if c.get("hornetsecurity_tenants"):
            raw = c["hornetsecurity_tenants"]
            if isinstance(raw, str):
                raw = [raw]
            # Espongo SIA la lista flat di tenant (legacy/whole) SIA la lista filters dettagliata
            flat_tenants: list[str] = []
            full_filters: list[dict] = []
            for it in raw:
                if isinstance(it, str):
                    flat_tenants.append(it)
                    full_filters.append({"tenant": it, "sub_groups": None})
                elif isinstance(it, dict) and it.get("tenant"):
                    if it.get("sub_groups"):
                        full_filters.append({"tenant": it["tenant"], "sub_groups": list(it["sub_groups"])})
                    else:
                        flat_tenants.append(it["tenant"])
                        full_filters.append({"tenant": it["tenant"], "sub_groups": None})
            mappings.append({
                "client_id": c["id"],
                "client_name": c.get("name"),
                "tenants": flat_tenants,
                "filters": full_filters,
            })
    return {"tenants": out, "mappings": mappings}


# ---------------------------------------------------------------------------
# CLIENT MAPPING — collega un cliente ARGUS a 1+ tenant Hornetsecurity
# ---------------------------------------------------------------------------
class TenantMappingIn(BaseModel):
    tenants: list[Any] = Field(
        default_factory=list,
        description=(
            "Lista mapping. Ogni elemento puo` essere:\n"
            "- string (nome tenant) → mappa l'intero tenant (legacy)\n"
            "- {tenant: str, sub_groups: [str] | null} → mappa solo i sotto-gruppi indicati"
        ),
    )


@router.get("/clients/{client_id}/backup/hornetsecurity/mapping")
async def get_client_tenant_mapping(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ritorna i tenant Hornetsecurity associati a questo cliente (con sub_groups se mappati)."""
    client = await _ensure_client_exists(client_id)
    raw = client.get("hornetsecurity_tenants", []) or []
    if isinstance(raw, str):
        raw = [raw]
    # Compat output: lista di stringhe (legacy) E lista normalizzata
    legacy_tenants = []
    full_filters = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            legacy_tenants.append(item.strip())
            full_filters.append({"tenant": item.strip(), "sub_groups": None})
        elif isinstance(item, dict):
            t = (item.get("tenant") or "").strip()
            if not t:
                continue
            sg = item.get("sub_groups")
            if isinstance(sg, list) and sg:
                full_filters.append({"tenant": t, "sub_groups": sorted({str(x).lower() for x in sg if x})})
            else:
                legacy_tenants.append(t)
                full_filters.append({"tenant": t, "sub_groups": None})
    return {
        "client_id": client_id,
        "client_name": client.get("name"),
        "tenants": legacy_tenants,         # backcompat
        "filters": full_filters,           # nuovo formato
    }


@router.put("/clients/{client_id}/backup/hornetsecurity/mapping")
async def set_client_tenant_mapping(
    client_id: str,
    payload: TenantMappingIn,
    current_user: dict = Depends(get_current_user),
):
    """Imposta il mapping cliente → tenant Hornetsecurity (1+ tenant per cliente).

    Accetta sia liste di stringhe (legacy: tutto il tenant) sia liste di
    oggetti {tenant, sub_groups} per mapping a livello sotto-gruppo (dominio).
    """
    require_admin(current_user)
    await _ensure_client_exists(client_id)

    cleaned: list[Any] = []
    seen_keys: set[str] = set()
    for item in payload.tenants or []:
        if isinstance(item, str):
            t = item.strip()
            if t and t not in seen_keys:
                cleaned.append(t)
                seen_keys.add(t)
        elif isinstance(item, dict):
            t = (item.get("tenant") or "").strip()
            if not t:
                continue
            sg_raw = item.get("sub_groups")
            if isinstance(sg_raw, list) and sg_raw:
                sg_clean = sorted({str(x).strip().lower() for x in sg_raw if x and str(x).strip()})
                if sg_clean:
                    key = f"{t}::{','.join(sg_clean)}"
                    if key not in seen_keys:
                        cleaned.append({"tenant": t, "sub_groups": sg_clean})
                        seen_keys.add(key)
                    continue
            # Nessun sub_group → mapping intero tenant (forma legacy stringa)
            if t not in seen_keys:
                cleaned.append(t)
                seen_keys.add(t)

    await db.clients.update_one(
        {"id": client_id},
        {"$set": {"hornetsecurity_tenants": cleaned}},
    )
    audit.warning(
        f"HORNETSECURITY_MAPPING_SET by={current_user.get('email')} "
        f"client_id={client_id} entries={cleaned}"
    )
    return {"saved": True, "tenants": cleaned}


# ---------------------------------------------------------------------------
# SUB-GROUP DISCOVERY — sotto-gruppi (domini email) dentro un tenant
# ---------------------------------------------------------------------------
@router.get("/admin/hornetsecurity/tenants/{tenant_name}/sub-groups")
async def list_tenant_sub_groups(
    tenant_name: str,
    current_user: dict = Depends(get_current_user),
):
    """Lista i sotto-gruppi (domini email) rilevati dentro un tenant
    Hornetsecurity, con conteggio workload e mapping clienti.

    Usato dalla UI mapping per espandere un tenant e mostrare i sub-group
    selezionabili come unita` di mapping.
    """
    require_admin(current_user)
    pipeline = [
        {"$match": {"source": "hornetsecurity", "tenant": tenant_name}},
        {"$group": {
            "_id": "$sub_group",
            "workloads_total": {"$sum": 1},
            "workloads_failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "workloads_protected": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
            "types": {"$addToSet": "$workload_type"},
            "last_seen": {"$max": "$captured_at"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.backup_job_status.aggregate(pipeline).to_list(500)
    sub_groups: list[dict] = []
    for r in rows:
        sub_groups.append({
            "sub_group": r["_id"] or SUBGROUP_UNGROUPED,
            "is_ungrouped": (r["_id"] is None) or (r["_id"] == SUBGROUP_UNGROUPED),
            "workloads_total": r.get("workloads_total", 0),
            "workloads_failed": r.get("workloads_failed", 0),
            "workloads_protected": r.get("workloads_protected", 0),
            "types": sorted([t for t in r.get("types", []) if t]),
            "last_seen": r.get("last_seen"),
        })

    # Mappature attuali sub_group -> client (per evidenziare nella UI)
    sg_to_clients: dict[str, list[dict]] = {}
    async for c in db.clients.find(
        {"hornetsecurity_tenants": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "name": 1, "hornetsecurity_tenants": 1},
    ):
        for item in c.get("hornetsecurity_tenants") or []:
            if isinstance(item, dict) and item.get("tenant") == tenant_name:
                for sg in item.get("sub_groups") or []:
                    sg_to_clients.setdefault(str(sg).lower(), []).append(
                        {"client_id": c["id"], "client_name": c.get("name")}
                    )
            elif isinstance(item, str) and item == tenant_name:
                # Cliente che ha mappato l'intero tenant → tutti i sub-group sono suoi
                sg_to_clients.setdefault("__whole_tenant__", []).append(
                    {"client_id": c["id"], "client_name": c.get("name")}
                )

    for sg in sub_groups:
        whole = sg_to_clients.get("__whole_tenant__", [])
        specific = sg_to_clients.get(sg["sub_group"].lower(), [])
        # whole-tenant clients also "own" this sub_group implicitly
        sg["mapped_clients"] = specific + [{**c, "via": "whole_tenant"} for c in whole]

    return {
        "tenant": tenant_name,
        "sub_groups": sub_groups,
        "total_sub_groups": len(sub_groups),
    }


@router.post("/admin/hornetsecurity/backfill-sub-groups")
async def backfill_sub_groups(current_user: dict = Depends(get_current_user)):
    """One-shot: ricalcola e salva il campo `sub_group` per tutti i workload
    Hornetsecurity gia` ingestiti (utile dopo l'aggiornamento del codice).
    """
    require_admin(current_user)
    updated = 0
    cursor = db.backup_job_status.find(
        {"source": "hornetsecurity", "sub_group": {"$exists": False}},
        {"_id": 1, "workload_user": 1, "workload_name": 1},
    )
    async for d in cursor:
        sg = _extract_sub_group(d)
        await db.backup_job_status.update_one(
            {"_id": d["_id"]},
            {"$set": {"sub_group": sg}},
        )
        updated += 1
    # Anche backup_alerts
    alerts_updated = 0
    cursor2 = db.backup_alerts.find(
        {"source": "hornetsecurity", "sub_group": {"$exists": False}},
        {"_id": 1, "workload_id": 1, "tenant": 1},
    )
    async for d in cursor2:
        # Resolve from latest workload status doc
        wd = await db.backup_job_status.find_one(
            {"tenant": d.get("tenant"), "workload_id": d.get("workload_id")},
            {"_id": 0, "sub_group": 1},
        )
        sg = (wd or {}).get("sub_group") or SUBGROUP_UNGROUPED
        await db.backup_alerts.update_one({"_id": d["_id"]}, {"$set": {"sub_group": sg}})
        alerts_updated += 1
    audit.warning(
        f"HORNETSECURITY_BACKFILL_SUBGROUPS by={current_user.get('email')} "
        f"workloads={updated} alerts={alerts_updated}"
    )
    return {"workloads_updated": updated, "alerts_updated": alerts_updated}
