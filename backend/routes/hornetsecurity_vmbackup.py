"""
Hornetsecurity VM Backup (ex-Altaro) Integration
================================================
Integrazione con l'API del portal MSP (Hornetsecurity VM Backup / Altaro).
Struttura payload:
    hornetSecurityReport[] {
      customerName, createdAt,
      installationStatusReports[] {
        name (server), version,
        hostStatusReports[] {
          name (host), hostTypeName (HyperV/VMware),
          virtualMachinesStatus[] {
            _id, name,
            lastOnsiteBackupResult / ResultName,
            lastOnsiteBackupTime, lastOnsiteBackupDuration,
            lastOnsiteBackupProcessedTransferSize,
            lastOffsiteCopyResult / ResultName / Time,
            lastSecondOffsiteCopyResult / ResultName / Time,
            nextOffsiteCopyTime, cdpEnabled
          }
        }
      }
    }

- Config globale: `hornetsecurity_vmbackup_config` (_id="global") con api_url,
  api_key cifrato, user_id, polling_interval_minutes (default 10).
- Storage VM: `vmbackup_jobs` (key: customer_name + installation + host + vm_id).
- Mapping cliente→customerName: `clients.hornetsecurity_vm_customers: [str]`.
- Alert fan-out su `db.alerts` come per M365 Backup.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger("hornetsecurity_vmbackup")
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api", tags=["hornetsecurity-vmbackup"])

GLOBAL_CONFIG_ID = "global"
DEFAULT_API_URL = "https://portal.86bit.it/api/v1/reports/altaro/getHornetSecurityReport"
STALE_BACKUP_HOURS = 48  # backup piu` vecchio di N ore → alert medium anche se "Success"


# ---------------------------------------------------------------------------
# Result mapping
# ---------------------------------------------------------------------------
# Altaro returns integer result codes + ResultName strings:
#   1=Success, 2=Warning, 3=Failed, 0=Unknown, 4=InProgress (osservati)
def _normalize_result(code: Any, name: Optional[str]) -> str:
    n = (name or "").strip().lower()
    if n == "success":
        return "success"
    if n in ("failed", "failure"):
        return "failed"
    if n == "warning":
        return "warning"
    if n in ("inprogress", "in progress", "running"):
        return "in_progress"
    if n == "unknown":
        return "unknown"
    # fallback per codici numerici
    try:
        c = int(code)
        return {1: "success", 2: "warning", 3: "failed", 4: "in_progress"}.get(c, "unknown")
    except Exception:
        return "unknown"


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s or s == "null":
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config models / endpoints
# ---------------------------------------------------------------------------
class VMBackupConfigIn(BaseModel):
    api_url: str = Field(default=DEFAULT_API_URL)
    api_key: str = Field(..., description="Chiave API del portal MSP")
    user_id: str = Field(..., description="userId da passare in query")
    polling_interval_minutes: int = Field(default=10, ge=5, le=120)
    enabled: bool = Field(default=True)


class VMBackupConfigOut(BaseModel):
    api_url: str
    user_id: str
    api_key_masked: str
    polling_interval_minutes: int
    enabled: bool
    configured: bool = False
    last_polled_at: Optional[str] = None
    last_poll_status: Optional[str] = None
    last_poll_error: Optional[str] = None
    last_poll_summary: Optional[dict] = None


def _mask_key(k: str) -> str:
    if not k or len(k) < 8:
        return "********"
    return f"****{k[-4:]}"


@router.get("/admin/hornetsecurity-vm/config", response_model=VMBackupConfigOut)
async def get_vmbackup_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.hornetsecurity_vmbackup_config.find_one({"_id": GLOBAL_CONFIG_ID})
    if not cfg:
        return VMBackupConfigOut(
            api_url=DEFAULT_API_URL, user_id="", api_key_masked="(non configurato)",
            polling_interval_minutes=10, enabled=True, configured=False,
        )
    try:
        k = security_manager.decrypt_credential(cfg.get("api_key_enc", ""))
    except Exception:
        k = ""
    return VMBackupConfigOut(
        api_url=cfg.get("api_url") or DEFAULT_API_URL,
        user_id=cfg.get("user_id", ""),
        api_key_masked=_mask_key(k),
        polling_interval_minutes=cfg.get("polling_interval_minutes", 10),
        enabled=cfg.get("enabled", True),
        configured=bool(cfg.get("api_key_enc") and cfg.get("user_id")),
        last_polled_at=cfg.get("last_polled_at"),
        last_poll_status=cfg.get("last_poll_status"),
        last_poll_error=cfg.get("last_poll_error"),
        last_poll_summary=cfg.get("last_poll_summary"),
    )


@router.put("/admin/hornetsecurity-vm/config")
async def set_vmbackup_config(
    payload: VMBackupConfigIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    enc_key = security_manager.encrypt_credential(payload.api_key.strip())
    await db.hornetsecurity_vmbackup_config.update_one(
        {"_id": GLOBAL_CONFIG_ID},
        {"$set": {
            "_id": GLOBAL_CONFIG_ID,
            "api_url": payload.api_url.strip() or DEFAULT_API_URL,
            "user_id": payload.user_id.strip(),
            "api_key_enc": enc_key,
            "polling_interval_minutes": payload.polling_interval_minutes,
            "enabled": payload.enabled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": current_user.get("email"),
        }},
        upsert=True,
    )
    audit.warning(f"VMBACKUP_CONFIG_SET by={current_user.get('email')}")
    return {"saved": True}


@router.delete("/admin/hornetsecurity-vm/config")
async def delete_vmbackup_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.hornetsecurity_vmbackup_config.delete_one({"_id": GLOBAL_CONFIG_ID})
    audit.warning(f"VMBACKUP_CONFIG_DELETED by={current_user.get('email')}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Fetch + Parse
# ---------------------------------------------------------------------------
async def _fetch_vmbackup_report(api_url: str, api_key: str, user_id: str) -> tuple[int, Any]:
    params = {"api_key": api_key, "userId": user_id, "json": "true"}
    try:
        async with httpx.AsyncClient(timeout=60.0, verify=True) as client:
            r = await client.get(api_url, params=params)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except httpx.HTTPError as e:
        return 0, f"Connection error: {e}"


def _iter_vms(report: dict):
    """Yield flattened VM records with customer/installation/host context."""
    customers = report.get("hornetSecurityReport") or []
    if not isinstance(customers, list):
        return
    for cust in customers:
        cname = (cust.get("customerName") or "").strip()
        if not cname:
            continue
        for inst in cust.get("installationStatusReports", []) or []:
            iname = (inst.get("name") or "").strip()
            iver = inst.get("version") or ""
            for host in inst.get("hostStatusReports", []) or []:
                hname = (host.get("name") or "").strip()
                htype = host.get("hostTypeName") or ""
                for vm in host.get("virtualMachinesStatus", []) or []:
                    vm_id = str(vm.get("_id") or "")
                    vm_name = (vm.get("name") or "").strip()
                    if not vm_id or not vm_name:
                        continue
                    yield {
                        "customer_name": cname,
                        "installation_name": iname,
                        "installation_version": iver,
                        "host_name": hname,
                        "host_type": htype,
                        "vm_id": vm_id,
                        "vm_name": vm_name,
                        "onsite_status": _normalize_result(vm.get("lastOnsiteBackupResult"), vm.get("lastOnsiteBackupResultName")),
                        "onsite_status_raw": vm.get("lastOnsiteBackupResultName") or "",
                        "onsite_time": vm.get("lastOnsiteBackupTime"),
                        "onsite_duration_s": vm.get("lastOnsiteBackupDuration") or 0,
                        "onsite_size_bytes": vm.get("lastOnsiteBackupProcessedTransferSize") or 0,
                        "offsite_status": _normalize_result(vm.get("lastOffsiteCopyResult"), vm.get("lastOffsiteCopyResultName")),
                        "offsite_status_raw": vm.get("lastOffsiteCopyResultName") or "",
                        "offsite_time": vm.get("lastOffsiteCopyTime"),
                        "next_offsite_time": vm.get("nextOffsiteCopyTime"),
                        "second_offsite_status": _normalize_result(vm.get("lastSecondOffsiteCopyResult"), vm.get("lastSecondOffsiteCopyResultName")),
                        "second_offsite_status_raw": vm.get("lastSecondOffsiteCopyResultName") or "",
                        "second_offsite_time": vm.get("lastSecondOffsiteCopyTime"),
                        "cdp_enabled": bool(vm.get("cdpEnabled", False)),
                    }


async def _persist_vmbackup_poll(report: dict) -> dict:
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    stale_cutoff = now_dt - timedelta(hours=STALE_BACKUP_HOURS)
    counts = {"vms": 0, "failed": 0, "warning": 0, "success": 0, "stale": 0, "customers": set()}
    for v in _iter_vms(report):
        counts["vms"] += 1
        counts["customers"].add(v["customer_name"])

        # Derive overall alert_severity for this VM (aggregato onsite+offsite)
        onsite = v["onsite_status"]
        offsite = v["offsite_status"]
        alert_severity = None
        alert_reason = None
        if onsite == "failed" or offsite == "failed":
            alert_severity = "high"
            alert_reason = "failed"
            counts["failed"] += 1
        elif onsite == "warning" or offsite == "warning":
            alert_severity = "medium"
            alert_reason = "warning"
            counts["warning"] += 1
        else:
            if onsite == "success":
                counts["success"] += 1
            # stale check: onsite "success" ma troppo vecchio
            ost = _parse_dt(v["onsite_time"])
            if ost and ost < stale_cutoff:
                alert_severity = "medium"
                alert_reason = "stale"
                counts["stale"] += 1

        v["alert_severity"] = alert_severity
        v["alert_reason"] = alert_reason
        v["captured_at"] = now_iso
        v["source"] = "hornetsecurity-vm"

        await db.vmbackup_jobs.update_one(
            {"customer_name": v["customer_name"], "host_name": v["host_name"], "vm_id": v["vm_id"]},
            {"$set": v},
            upsert=True,
        )

        # Fan-out / auto-resolve nel sistema alert principale
        try:
            if alert_severity:
                await _fanout_vm_alert(v, alert_severity, alert_reason, now_iso)
            else:
                await _resolve_vm_alerts(v["customer_name"], v["vm_id"], now_iso)
        except Exception as e:
            logger.warning(f"[vmbackup] fanout/resolve failed for {v['vm_name']}: {e}")

    customers_set = counts.pop("customers")
    counts["customers"] = len(customers_set)
    return counts


# ---------------------------------------------------------------------------
# Client mapping & status
# ---------------------------------------------------------------------------
async def _ensure_client(client_id: str) -> dict:
    c = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Client not found")
    return c


async def _client_vm_customers(client_id: str) -> list[str]:
    c = await db.clients.find_one({"id": client_id}, {"_id": 0, "hornetsecurity_vm_customers": 1})
    if not c:
        return []
    raw = c.get("hornetsecurity_vm_customers") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in raw if x and str(x).strip()]


class VMCustomerMappingIn(BaseModel):
    customers: list[str] = Field(default_factory=list)


@router.get("/clients/{client_id}/backup/vmbackup/mapping")
async def get_vm_mapping(client_id: str, current_user: dict = Depends(get_current_user)):
    c = await _ensure_client(client_id)
    return {"client_id": client_id, "client_name": c.get("name"),
            "customers": c.get("hornetsecurity_vm_customers") or []}


@router.put("/clients/{client_id}/backup/vmbackup/mapping")
async def set_vm_mapping(
    client_id: str, payload: VMCustomerMappingIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    await _ensure_client(client_id)
    cleaned = sorted({(c or "").strip() for c in payload.customers if c and c.strip()})
    await db.clients.update_one(
        {"id": client_id},
        {"$set": {"hornetsecurity_vm_customers": cleaned}},
    )
    audit.warning(f"VMBACKUP_MAPPING_SET by={current_user.get('email')} client={client_id} customers={cleaned}")
    synced = 0
    try:
        synced = await _sync_vm_alerts_for_client(client_id, cleaned)
    except Exception as e:
        logger.warning(f"[vmbackup] sync alerts after mapping: {e}")
    return {"saved": True, "customers": cleaned, "alerts_synced": synced}


@router.get("/clients/{client_id}/backup/vmbackup/status")
async def get_vm_status(client_id: str, current_user: dict = Depends(get_current_user)):
    await _ensure_client(client_id)
    customers = await _client_vm_customers(client_id)
    if not customers:
        return {"mapped_customers": [], "items": [], "totals": {
            "by_status": {}, "by_host": {}, "vms_total": 0,
            "failed": 0, "warning": 0, "stale": 0,
        }}
    items = await db.vmbackup_jobs.find(
        {"customer_name": {"$in": customers}}, {"_id": 0}
    ).sort("vm_name", 1).limit(5000).to_list(5000)
    by_host: dict[str, int] = {}
    by_status: dict[str, int] = {}
    failed = warning = stale = 0
    for it in items:
        h = it.get("host_name") or "—"
        by_host[h] = by_host.get(h, 0) + 1
        s = it.get("onsite_status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
        r = it.get("alert_reason")
        if r == "failed":
            failed += 1
        elif r == "warning":
            warning += 1
        elif r == "stale":
            stale += 1
    return {
        "mapped_customers": customers,
        "items": items,
        "totals": {
            "by_host": by_host, "by_status": by_status,
            "vms_total": len(items),
            "failed": failed, "warning": warning, "stale": stale,
        },
    }


# ---------------------------------------------------------------------------
# Admin: list discovered customers + per-customer stats + existing mappings
# ---------------------------------------------------------------------------
@router.get("/admin/hornetsecurity-vm/customers")
async def list_vm_customers(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    rows = await db.vmbackup_jobs.aggregate([
        {"$group": {
            "_id": "$customer_name",
            "vms_total": {"$sum": 1},
            "vms_failed": {"$sum": {"$cond": [{"$eq": ["$alert_reason", "failed"]}, 1, 0]}},
            "vms_warning": {"$sum": {"$cond": [{"$eq": ["$alert_reason", "warning"]}, 1, 0]}},
            "vms_stale": {"$sum": {"$cond": [{"$eq": ["$alert_reason", "stale"]}, 1, 0]}},
            "hosts": {"$addToSet": "$host_name"},
            "installations": {"$addToSet": "$installation_name"},
            "last_seen": {"$max": "$captured_at"},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(1000)
    customers = []
    for r in rows:
        if not r.get("_id"):
            continue
        customers.append({
            "customer_name": r["_id"],
            "vms_total": r.get("vms_total", 0),
            "vms_failed": r.get("vms_failed", 0),
            "vms_warning": r.get("vms_warning", 0),
            "vms_stale": r.get("vms_stale", 0),
            "hosts_count": len([h for h in r.get("hosts") or [] if h]),
            "installations_count": len([i for i in r.get("installations") or [] if i]),
            "last_seen": r.get("last_seen"),
        })
    mappings = []
    async for c in db.clients.find(
        {"hornetsecurity_vm_customers": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "name": 1, "hornetsecurity_vm_customers": 1},
    ):
        mappings.append({"client_id": c["id"], "client_name": c.get("name"),
                         "customers": c.get("hornetsecurity_vm_customers") or []})
    return {"customers": customers, "mappings": mappings}


# ---------------------------------------------------------------------------
# Alert fan-out to main alerts collection
# ---------------------------------------------------------------------------
async def _fanout_vm_alert(vm: dict, severity: str, reason: str, now_iso: str) -> int:
    """Crea/aggiorna alert in db.alerts per ogni cliente mappato al customer."""
    touched = 0
    async for client in db.clients.find(
        {"hornetsecurity_vm_customers": vm["customer_name"]},
        {"_id": 0, "id": 1},
    ):
        alert_id = f"vmbackup-{client['id']}-{vm['customer_name']}-{vm['vm_id']}"[:200]
        title_reason = {
            "failed": "Backup VM fallito",
            "warning": "Backup VM warning",
            "stale": "Backup VM non aggiornato",
        }.get(reason, "Backup VM anomalia")
        title = f"{title_reason}: {vm['vm_name']}"
        ctx = [f"host: {vm.get('host_name')}", f"customer: {vm['customer_name']}"]
        if vm.get("host_type"):
            ctx.append(f"hypervisor: {vm['host_type']}")
        if reason == "stale" and vm.get("onsite_time"):
            ctx.append(f"ultimo: {vm['onsite_time']}")
        elif reason in ("failed", "warning"):
            ctx.append(f"onsite: {vm.get('onsite_status_raw') or vm.get('onsite_status')}")
            ctx.append(f"offsite: {vm.get('offsite_status_raw') or vm.get('offsite_status')}")
        msg = f"{title_reason} per la VM {vm['vm_name']} (" + ", ".join(ctx) + ")"

        existing = await db.alerts.find_one({"id": alert_id}, {"_id": 0, "status": 1})
        doc = {
            "id": alert_id,
            "client_id": client["id"],
            "device_id": "",
            "severity": severity,
            "source_type": "backup",
            "title": title,
            "message": msg,
            "raw_data": json.dumps({
                "customer_name": vm["customer_name"], "vm_id": vm["vm_id"],
                "vm_name": vm["vm_name"], "host_name": vm.get("host_name"),
                "host_type": vm.get("host_type"), "reason": reason,
                "provider": "hornetsecurity-vm",
            }),
            "device_name": f"{vm['vm_name']} ({vm.get('host_name')})",
            "device_type": "backup",
            "last_seen": now_iso,
        }
        if existing:
            if existing.get("status") == "resolved":
                doc["status"] = "active"
                doc["resolved_at"] = None
            await db.alerts.update_one({"id": alert_id}, {"$set": doc})
        else:
            doc.update({"status": "active", "acknowledged_by": None,
                        "acknowledged_at": None, "resolved_at": None, "created_at": now_iso})
            await db.alerts.insert_one(doc)
        touched += 1
    return touched


async def _resolve_vm_alerts(customer_name: str, vm_id: str, now_iso: str) -> int:
    res = await db.alerts.update_many(
        {"source_type": "backup", "status": {"$in": ["active", "acknowledged"]},
         "id": {"$regex": f"^vmbackup-.*-{customer_name}-{vm_id}$"}},
        {"$set": {"status": "resolved", "resolved_at": now_iso}},
    )
    return res.modified_count


async def _sync_vm_alerts_for_client(client_id: str, customers: list[str]) -> int:
    """Rilegge VM con alert_severity attivo per i customer mappati e riemette alert."""
    if not customers:
        return 0
    now_iso = datetime.now(timezone.utc).isoformat()
    synced = 0
    cursor = db.vmbackup_jobs.find(
        {"customer_name": {"$in": customers}, "alert_severity": {"$ne": None}},
        {"_id": 0},
    )
    async for v in cursor:
        # Build single-client fan-out (inline per non reiterare sulla mappa completa)
        sev = v.get("alert_severity") or "medium"
        reason = v.get("alert_reason") or "warning"
        alert_id = f"vmbackup-{client_id}-{v['customer_name']}-{v['vm_id']}"[:200]
        existing = await db.alerts.find_one({"id": alert_id}, {"_id": 0, "status": 1})
        title_reason = {
            "failed": "Backup VM fallito",
            "warning": "Backup VM warning",
            "stale": "Backup VM non aggiornato",
        }.get(reason, "Backup VM anomalia")
        doc = {
            "id": alert_id, "client_id": client_id, "device_id": "",
            "severity": sev, "source_type": "backup",
            "title": f"{title_reason}: {v['vm_name']}",
            "message": f"{title_reason} per la VM {v['vm_name']} (host: {v.get('host_name')}, customer: {v['customer_name']})",
            "raw_data": json.dumps({
                "customer_name": v["customer_name"], "vm_id": v["vm_id"],
                "vm_name": v["vm_name"], "host_name": v.get("host_name"),
                "host_type": v.get("host_type"), "reason": reason,
                "provider": "hornetsecurity-vm",
            }),
            "device_name": f"{v['vm_name']} ({v.get('host_name')})",
            "device_type": "backup", "last_seen": now_iso,
        }
        if existing:
            if existing.get("status") == "resolved":
                doc["status"] = "active"
                doc["resolved_at"] = None
            await db.alerts.update_one({"id": alert_id}, {"$set": doc})
        else:
            doc.update({"status": "active", "acknowledged_by": None,
                        "acknowledged_at": None, "resolved_at": None, "created_at": now_iso})
            await db.alerts.insert_one(doc)
        synced += 1
    return synced


@router.post("/admin/hornetsecurity-vm/sync-all-alerts")
async def sync_all_vm_alerts(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    total = 0
    touched = 0
    async for c in db.clients.find(
        {"hornetsecurity_vm_customers": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "hornetsecurity_vm_customers": 1},
    ):
        n = await _sync_vm_alerts_for_client(c["id"], c.get("hornetsecurity_vm_customers") or [])
        total += n
        if n > 0:
            touched += 1
    audit.warning(f"VMBACKUP_SYNC_ALL by={current_user.get('email')} alerts={total} clients={touched}")
    return {"alerts_synced": total, "clients_touched": touched}


@router.post("/admin/hornetsecurity-vm/poll-now")
async def poll_vmbackup_now(current_user: dict = Depends(get_current_user)):
    """Trigger manuale (admin) del polling VMBackup."""
    require_admin(current_user)
    from services.hornetsecurity_vmbackup_poller import run_vmbackup_tick
    summary = await run_vmbackup_tick(force=True)
    return summary
