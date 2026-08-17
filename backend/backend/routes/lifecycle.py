"""
Hardware Lifecycle & Warranty Management — stile Park Place Technologies ParkView.
Estende il CMDB con:
- Scadenze garanzia OEM (HPE/Dell/Cisco/Lenovo/...)
- EOL (End Of Life) e EOSL (End Of Service Life) del produttore
- Contratti di manutenzione 3rd party
- Risk score hardware (eta' + stato garanzia + criticita' asset)
- Alert automatici per scadenze imminenti (90/60/30 gg)
- Import massivo via CSV/JSON
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone, timedelta, date
import uuid
import csv
import io
import logging

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])
audit = logging.getLogger("audit")


# ======================== MODELS ========================

class LifecycleRecord(BaseModel):
    device_ip: str
    client_id: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[str] = None     # YYYY-MM-DD
    install_date: Optional[str] = None
    warranty_start: Optional[str] = None
    warranty_end: Optional[str] = None
    warranty_level: Optional[str] = None    # es: "NBD", "4h 24x7", "Foundation Care"
    oem_contract_number: Optional[str] = None
    eol_date: Optional[str] = None          # End of Life (product)
    eosl_date: Optional[str] = None         # End of Service Life
    third_party_maintenance: Optional[str] = None  # vendor (es: "Park Place", "Curvature")
    maintenance_end: Optional[str] = None
    maintenance_contract_number: Optional[str] = None
    criticality: Optional[str] = Field(default="medium", description="low|medium|high|critical")
    replacement_cost_eur: Optional[float] = None
    notes: Optional[str] = None


# ======================== HELPERS ========================

def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        return None


def _days_until(d_str: Optional[str]) -> Optional[int]:
    d = _parse_iso_date(d_str)
    if not d:
        return None
    return (d - date.today()).days


def _enrich_record(doc: dict) -> dict:
    doc.pop("_id", None)
    doc["warranty_days_left"] = _days_until(doc.get("warranty_end"))
    doc["maintenance_days_left"] = _days_until(doc.get("maintenance_end"))
    doc["eosl_days_left"] = _days_until(doc.get("eosl_date"))

    # Risk score calculation (0-100, higher = more risk)
    risk = 0
    w = doc.get("warranty_days_left")
    m = doc.get("maintenance_days_left")
    e = doc.get("eosl_days_left")
    if w is not None:
        if w < 0: risk += 30
        elif w < 30: risk += 25
        elif w < 90: risk += 15
        elif w < 180: risk += 5
    else:
        risk += 10  # unknown warranty
    if m is not None:
        if m < 0: risk += 15
        elif m < 60: risk += 10
    if e is not None:
        if e < 0: risk += 35      # EOSL reached = no OEM support
        elif e < 180: risk += 25
        elif e < 365: risk += 10
    crit = (doc.get("criticality") or "medium").lower()
    if crit == "critical": risk = min(100, risk + 15)
    elif crit == "high": risk = min(100, risk + 8)
    doc["risk_score"] = min(100, risk)
    if risk >= 55: doc["risk_band"] = "high"
    elif risk >= 25: doc["risk_band"] = "medium"
    else: doc["risk_band"] = "low"
    return doc


# ======================== CRUD ========================

@router.get("/records")
async def list_records(client_id: Optional[str] = None, risk_band: Optional[str] = None,
                        current_user: dict = Depends(get_current_user)):
    q = {}
    if client_id:
        q["client_id"] = client_id
    cursor = db.lifecycle_records.find(q, {"_id": 0}).limit(1000)
    items = [_enrich_record(d) async for d in cursor]
    if risk_band:
        items = [i for i in items if i.get("risk_band") == risk_band]
    items.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/records/{device_ip}")
async def get_record(device_ip: str, current_user: dict = Depends(get_current_user)):
    doc = await db.lifecycle_records.find_one({"device_ip": device_ip}, {"_id": 0})
    if not doc:
        return {"record": None}
    return {"record": _enrich_record(doc)}


@router.post("/records")
async def upsert_record(rec: LifecycleRecord, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc).isoformat()
    data = rec.model_dump()
    device_ip = data.pop("device_ip")  # in filter + $setOnInsert only
    data["updated_at"] = now
    data["updated_by"] = current_user.get("email")
    await db.lifecycle_records.update_one(
        {"device_ip": device_ip},
        {"$set": data, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now, "device_ip": device_ip}},
        upsert=True
    )
    audit.info(f"[AUDIT] lifecycle_upsert | user={current_user.get('email')} | device={device_ip}")
    return {"ok": True, "device_ip": device_ip}


@router.delete("/records/{device_ip}")
async def delete_record(device_ip: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.lifecycle_records.delete_one({"device_ip": device_ip})
    return {"deleted": res.deleted_count > 0}


# ======================== BULK IMPORT CSV ========================

@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except Exception:
        text = content.decode("latin-1", errors="ignore")
    # auto-detect delimiter
    delim = ","
    for cand in [";", "\t", "|"]:
        if text.count(cand) > text.count(","):
            delim = cand
            break
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    # Normalize headers
    def _norm(h): return (h or "").strip().lower().replace(" ", "_")
    reader.fieldnames = [_norm(h) for h in (reader.fieldnames or [])]
    alias = {
        "ip": "device_ip", "ip_address": "device_ip", "host": "device_ip",
        "serial": "serial_number", "sn": "serial_number", "s/n": "serial_number",
        "produttore": "vendor", "manufacturer": "vendor",
        "modello": "model",
        "data_acquisto": "purchase_date",
        "scadenza_garanzia": "warranty_end", "warranty_expiration": "warranty_end",
        "scadenza_contratto": "maintenance_end", "support_end": "maintenance_end",
        "eol": "eol_date", "eosl": "eosl_date",
        "criticita": "criticality", "criticality_level": "criticality",
    }
    imported = 0
    skipped = 0
    errors = []
    now = datetime.now(timezone.utc).isoformat()
    for row in reader:
        nrow = {alias.get(k, k): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if v not in (None, "")}
        ip = nrow.get("device_ip")
        if not ip:
            skipped += 1
            errors.append({"row": row, "reason": "missing device_ip"})
            continue
        # Keep only known fields
        allowed = set(LifecycleRecord.model_fields.keys())
        payload = {k: v for k, v in nrow.items() if k in allowed}
        # Remove device_ip from $set (it's in filter and $setOnInsert)
        payload.pop("device_ip", None)
        if "replacement_cost_eur" in payload:
            try:
                payload["replacement_cost_eur"] = float(str(payload["replacement_cost_eur"]).replace(",", "."))
            except Exception:
                payload.pop("replacement_cost_eur")
        payload["updated_at"] = now
        payload["updated_by"] = current_user.get("email")
        await db.lifecycle_records.update_one(
            {"device_ip": ip},
            {"$set": payload, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now, "device_ip": ip}},
            upsert=True
        )
        imported += 1
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


# ======================== DASHBOARD & ALERTS ========================

@router.get("/expiring")
async def expiring_warranties(days_ahead: int = 90, current_user: dict = Depends(get_current_user)):
    cutoff_date = (date.today() + timedelta(days=days_ahead)).isoformat()
    cursor = db.lifecycle_records.find({}, {"_id": 0}).limit(1000)
    expiring = []
    async for d in cursor:
        en = _enrich_record(d)
        w = en.get("warranty_days_left")
        m = en.get("maintenance_days_left")
        e = en.get("eosl_days_left")
        flags = []
        if w is not None and w <= days_ahead: flags.append(("warranty", w))
        if m is not None and m <= days_ahead: flags.append(("maintenance", m))
        if e is not None and e <= days_ahead: flags.append(("eosl", e))
        if flags:
            en["expiring_flags"] = [{"type": t, "days_left": dl} for t, dl in flags]
            expiring.append(en)
    expiring.sort(key=lambda x: min(f["days_left"] for f in x["expiring_flags"]))
    return {"cutoff_date": cutoff_date, "items": expiring, "total": len(expiring)}


@router.get("/dashboard")
async def lifecycle_dashboard(current_user: dict = Depends(get_current_user)):
    cursor = db.lifecycle_records.find({}, {"_id": 0}).limit(5000)
    total = 0
    high_risk = 0
    medium_risk = 0
    low_risk = 0
    expired_warranty = 0
    expiring_30 = 0
    expiring_90 = 0
    eosl_reached = 0
    by_vendor = {}
    by_client = {}
    async for d in cursor:
        en = _enrich_record(d)
        total += 1
        band = en.get("risk_band")
        if band == "high": high_risk += 1
        elif band == "medium": medium_risk += 1
        else: low_risk += 1
        w = en.get("warranty_days_left")
        if w is not None:
            if w < 0: expired_warranty += 1
            elif w <= 30: expiring_30 += 1
            elif w <= 90: expiring_90 += 1
        if (en.get("eosl_days_left") or 9999) < 0:
            eosl_reached += 1
        vnd = (en.get("vendor") or "Unknown").strip() or "Unknown"
        by_vendor[vnd] = by_vendor.get(vnd, 0) + 1
        cid = en.get("client_id") or "unassigned"
        by_client[cid] = by_client.get(cid, 0) + 1
    return {
        "total": total,
        "high_risk": high_risk,
        "medium_risk": medium_risk,
        "low_risk": low_risk,
        "expired_warranty": expired_warranty,
        "expiring_30_days": expiring_30,
        "expiring_90_days": expiring_90,
        "eosl_reached": eosl_reached,
        "by_vendor": [{"vendor": k, "count": v} for k, v in sorted(by_vendor.items(), key=lambda x: -x[1])],
        "by_client": [{"client_id": k, "count": v} for k, v in sorted(by_client.items(), key=lambda x: -x[1])[:20]],
    }


async def init_indexes():
    await db.lifecycle_records.create_index([("device_ip", 1)], unique=True)
    await db.lifecycle_records.create_index([("client_id", 1)])
    await db.lifecycle_records.create_index([("warranty_end", 1)])
