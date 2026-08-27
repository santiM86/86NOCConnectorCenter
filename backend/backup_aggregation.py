"""Aggregazione stato backup per-cliente (fonte unica di verita').

Fonde le TRE fonti di backup usate in ARGUS in un unico conteggio per cliente:
  1. Legacy `backup_status` (doc per-cliente con `status` oppure `summary`).
  2. Hornetsecurity 365 Total Backup — `backup_job_status` (source="hornetsecurity")
     mappato via `clients.hornetsecurity_tenants`.
  3. Hornetsecurity VM Backup / Altaro — `vmbackup_jobs` (source="hornetsecurity-vm")
     mappato via `clients.hornetsecurity_vm_customers`.

Questa logica rispecchia ESATTAMENTE quella di `routes/overview.py` (dashboard
desktop) cosi' che TV wallboard e Mobile PWA mostrino gli stessi numeri del
desktop (fix discrepanza "Non monitorato" sul mobile per clienti con solo VM
Backup mappato).
"""
from __future__ import annotations


def _empty() -> dict:
    return {"total": 0, "ok": 0, "warning": 0, "error": 0, "missing": 0, "stale": 0}


async def build_backup_by_client(db) -> dict[str, dict]:
    """Ritorna {client_id: {total, ok, warning, error, missing, stale}}.
    Solo i clienti con almeno una fonte backup compaiono nel dict."""
    result: dict[str, dict] = {}

    # --- 1. Legacy backup_status -------------------------------------------
    # Stessa logica di routes/overview.py: un doc = un item, classificato per
    # campo `status` (NON `summary`) → garantisce parita' desktop/mobile/TV.
    backup_data = await db.backup_status.find(
        {}, {"_id": 0, "client_id": 1, "status": 1}
    ).to_list(5000)
    for b in backup_data:
        cid = b.get("client_id")
        if not cid:
            continue
        agg = result.setdefault(cid, _empty())
        st = b.get("status", "unknown")
        agg["total"] += 1
        if st in ("ok", "success", "completed"):
            agg["ok"] += 1
        elif st == "warning":
            agg["warning"] += 1
        else:
            agg["error"] += 1

    # --- 2. Hornetsecurity 365 Total Backup --------------------------------
    clients_hs_raw = await db.clients.find(
        {"hornetsecurity_tenants": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "hornetsecurity_tenants": 1},
    ).to_list(500)
    if clients_hs_raw:
        m365_workloads = await db.backup_job_status.find(
            {"source": "hornetsecurity"},
            {"_id": 0, "tenant": 1, "sub_group": 1, "status": 1},
        ).to_list(20000)
        for c in clients_hs_raw:
            cid = c.get("id")
            raw = c.get("hornetsecurity_tenants") or []
            if isinstance(raw, str):
                raw = [raw]
            filters = []
            for it in raw:
                if isinstance(it, str) and it.strip():
                    filters.append((it.strip(), None))
                elif isinstance(it, dict) and (it.get("tenant") or "").strip():
                    sg = it.get("sub_groups")
                    if isinstance(sg, list) and sg:
                        filters.append((it["tenant"].strip(), {str(x).lower() for x in sg if x}))
                    else:
                        filters.append((it["tenant"].strip(), None))
            if not filters:
                continue
            agg = result.setdefault(cid, _empty())
            for w in m365_workloads:
                t = w.get("tenant")
                sg = w.get("sub_group")
                for (ft, fsg) in filters:
                    if ft != t:
                        continue
                    if fsg is not None and sg not in fsg:
                        continue
                    agg["total"] += 1
                    st = w.get("status")
                    if st == "success":
                        agg["ok"] += 1
                    elif st == "failed":
                        agg["error"] += 1
                    break

    # --- 3. Hornetsecurity VM Backup (Altaro) ------------------------------
    clients_vm_raw = await db.clients.find(
        {"hornetsecurity_vm_customers": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "hornetsecurity_vm_customers": 1},
    ).to_list(500)
    if clients_vm_raw:
        vm_workloads = await db.vmbackup_jobs.find(
            {"source": "hornetsecurity-vm"},
            {"_id": 0, "customer_name": 1, "host_name": 1, "alert_reason": 1, "onsite_status": 1},
        ).to_list(20000)
        for c in clients_vm_raw:
            cid = c.get("id")
            raw_vm = c.get("hornetsecurity_vm_customers") or []
            if isinstance(raw_vm, str):
                raw_vm = [raw_vm]
            vm_filters = []
            for it in raw_vm:
                if isinstance(it, str) and it.strip():
                    vm_filters.append((it.strip(), None))
                elif isinstance(it, dict) and (it.get("customer") or "").strip():
                    hs = it.get("hosts")
                    if isinstance(hs, list) and hs:
                        vm_filters.append((it["customer"].strip(), {str(h) for h in hs if h}))
                    else:
                        vm_filters.append((it["customer"].strip(), None))
            if not vm_filters:
                continue
            agg = result.setdefault(cid, _empty())
            for w in vm_workloads:
                cn = w.get("customer_name")
                hn = w.get("host_name") or ""
                match = False
                for (fc, fh) in vm_filters:
                    if fc != cn:
                        continue
                    if fh is not None and hn not in fh:
                        continue
                    match = True
                    break
                if not match:
                    continue
                agg["total"] += 1
                r = w.get("alert_reason")
                if r == "failed":
                    agg["error"] += 1
                elif r == "warning":
                    agg["warning"] += 1
                elif r == "stale":
                    agg["stale"] += 1
                elif w.get("onsite_status") == "success":
                    agg["ok"] += 1

    return result
