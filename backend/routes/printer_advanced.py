"""Printer Advanced — Fase 1 di parity con MPS Monitor.

Aggiunte rispetto a `printers.py`:
  - Forecast esaurimento consumabili (giorni rimanenti basati su trend 30gg)
  - Page counter breakdown completo (Total / B&W / Color / Large / Duplex / Scan / Fax)
  - Cost-per-page (CPP) per stampante + costo mensile aggregato
  - Asset tag / Cespite per inventory MSP
  - Sede / Location (multi-sede MSP)
  - Export CSV dashboard (volumi, supplies, costi)

v2026-02-14
"""
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user

logger = logging.getLogger("printer_advanced")
router = APIRouter(prefix="/api/printers", tags=["printer-advanced"])


# ---------- Models ----------
class PrinterMetadata(BaseModel):
    asset_tag: Optional[str] = Field(None, max_length=100, description="Numero cespite/inventario")
    location: Optional[str] = Field(None, max_length=200, description="Sede / piano / ufficio")
    cost_center: Optional[str] = Field(None, max_length=100, description="Centro di costo")
    cpp_bw: Optional[float] = Field(None, ge=0, le=10, description="Cost-per-page B&W (€)")
    cpp_color: Optional[float] = Field(None, ge=0, le=10, description="Cost-per-page Color (€)")
    contract_ref: Optional[str] = Field(None, max_length=100, description="Riferimento contratto MPS")
    notes: Optional[str] = Field(None, max_length=2000)


# ---------- Forecast helper ----------
def _compute_supply_forecast(
    current_level_pct: Optional[float],
    history: List[Dict[str, Any]],
    supply_name: str,
) -> Dict[str, Any]:
    """Calcola giorni rimanenti di un supply basandosi sul trend storico.

    Strategia (realistica, media esatta):
      1. Trova nelle istantanee storiche il livello % di QUESTO supply
         (matching su `name` case-insensitive trimmed) negli ultimi 30gg.
      2. Se ho almeno 2 punti: consumo_giornaliero = (level_oldest - level_newest) / days_diff.
      3. days_remaining = current_level / consumo_giornaliero (se consumo > 0).

    Edge cases:
      - Supply ricaricato (level cresce): ritorna None (refilled di recente).
      - Consumo zero in 30gg: ritorna days_remaining = None ("stabile").
      - < 2 snapshot: ritorna None ("dati insufficienti").
    """
    if current_level_pct is None or current_level_pct <= 0:
        return {"days_remaining": None, "daily_pct": None, "reason": "no_current_level"}

    name_norm = (supply_name or "").strip().lower()
    if not name_norm:
        return {"days_remaining": None, "daily_pct": None, "reason": "no_supply_name"}

    # Estrai serie temporale (timestamp, level_pct) per QUESTO supply
    points = []
    for snap in history:
        ts = snap.get("timestamp")
        if not ts:
            continue
        for s in snap.get("supplies_snapshot", []) or []:
            if (s.get("name") or "").strip().lower() == name_norm:
                lvl = s.get("level_pct")
                if isinstance(lvl, (int, float)) and lvl >= 0:
                    points.append((ts, float(lvl)))
                break

    if len(points) < 2:
        return {"days_remaining": None, "daily_pct": None, "reason": "insufficient_history"}

    # Sort per timestamp ascendente
    points.sort(key=lambda x: x[0])
    ts_oldest, lvl_oldest = points[0]
    ts_newest, lvl_newest = points[-1]

    try:
        d_oldest = datetime.fromisoformat(ts_oldest.replace("Z", "+00:00"))
        d_newest = datetime.fromisoformat(ts_newest.replace("Z", "+00:00"))
        days_diff = max((d_newest - d_oldest).total_seconds() / 86400.0, 0.1)
    except Exception:
        return {"days_remaining": None, "daily_pct": None, "reason": "parse_error"}

    delta = lvl_oldest - lvl_newest  # positivo = consumato

    if delta <= 0:
        # Ricarica o livello stabile
        if delta < -5:
            return {"days_remaining": None, "daily_pct": 0.0, "reason": "recently_refilled"}
        return {"days_remaining": None, "daily_pct": 0.0, "reason": "stable_no_consumption"}

    daily_pct = delta / days_diff  # % consumato al giorno
    if daily_pct <= 0:
        return {"days_remaining": None, "daily_pct": 0.0, "reason": "no_consumption"}

    days_remaining = current_level_pct / daily_pct
    return {
        "days_remaining": round(days_remaining, 1),
        "daily_pct": round(daily_pct, 3),
        "samples": len(points),
        "days_observed": round(days_diff, 1),
        "reason": "ok",
    }


# ---------- Endpoints ----------
@router.get("/{client_id}/{device_ip}/forecast")
async def get_printer_forecast(
    client_id: str, device_ip: str,
    current_user: dict = Depends(get_current_user),
):
    """Per ogni supply attivo della stampante, calcola giorni rimanenti.

    Risposta:
      {
        "device_ip": "...",
        "supplies": [
          {"name": "Black Toner", "level_pct": 32, "days_remaining": 18.4, "daily_pct": 1.74},
          ...
        ]
      }
    """
    printer = await db.printer_status.find_one(
        {"client_id": client_id, "device_ip": device_ip}, {"_id": 0}
    )
    if not printer:
        raise HTTPException(status_code=404, detail="Stampante non trovata")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    history = await db.printer_history.find(
        {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("timestamp", 1).to_list(500)

    out = []
    for s in printer.get("supplies", []):
        fc = _compute_supply_forecast(
            s.get("level_pct"),
            history,
            s.get("name") or "",
        )
        out.append({
            "name": s.get("name"),
            "color_name": s.get("color_name"),
            "color_hex": s.get("color_hex"),
            "level_pct": s.get("level_pct"),
            "level_text": s.get("level_text"),
            **fc,
        })

    return {
        "device_ip": device_ip,
        "device_name": printer.get("device_name") or device_ip,
        "supplies": out,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.put("/{client_id}/{device_ip}/metadata")
async def update_printer_metadata(
    client_id: str, device_ip: str,
    payload: PrinterMetadata,
    current_user: dict = Depends(get_current_user),
):
    """Aggiorna i metadata utente della stampante (asset, location, CPP, ecc.).

    Tutti i campi sono opzionali; vengono salvati solo quelli passati esplicitamente
    (i None vengono interpretati come "cancella valore").
    """
    set_fields = {}
    unset_fields = {}
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is None or v == "":
            unset_fields[k] = ""
        else:
            set_fields[k] = v
    set_fields["metadata_updated_at"] = datetime.now(timezone.utc).isoformat()
    set_fields["metadata_updated_by"] = current_user.get("email") or current_user.get("id")

    update_doc: Dict[str, Any] = {"$set": set_fields}
    if unset_fields:
        update_doc["$unset"] = unset_fields

    res = await db.printer_status.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        update_doc,
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Stampante non trovata")

    return {"ok": True, "updated_fields": list(data.keys())}


@router.get("/{client_id}/dashboard-extended")
async def printer_dashboard_extended(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Estensione del dashboard con KPI cost/usage/forecast aggregati.

    Aggiunge rispetto al `printer_dashboard` esistente:
      - total_color_pages, total_bw_pages, total_duplex
      - estimated_monthly_cost (sommando cpp * pagine ultimi 30gg)
      - cost_breakdown per stampante (top 10)
      - supplies_critical (≤10gg)
      - locations_summary (per multi-sede)
    """
    printers = await db.printer_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)

    # Counter breakdown aggregato
    total_pages = sum(p.get("page_count", 0) for p in printers)
    total_color = sum(p.get("color_page_count", 0) for p in printers)
    total_bw = sum((p.get("page_count", 0) - p.get("color_page_count", 0)) for p in printers)
    total_duplex = sum(p.get("duplex_count", 0) for p in printers)
    total_large = sum(p.get("large_format_count", 0) for p in printers)
    total_scan = sum(p.get("scan_count", 0) for p in printers)
    total_fax = sum(p.get("fax_count", 0) for p in printers)

    # Calcolo pagine ultimi 30gg per stampante + costo stimato
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    monthly_cost_total = 0.0
    cost_breakdown = []
    for p in printers:
        device_ip = p.get("device_ip")
        if not device_ip:
            continue
        # Prendi snapshot piu' vecchio negli ultimi 30gg
        oldest_hist = await db.printer_history.find_one(
            {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff_30d}},
            {"_id": 0, "page_count": 1, "timestamp": 1},
            sort=[("timestamp", 1)],
        )
        if not oldest_hist:
            continue
        pages_30d = max(0, (p.get("page_count") or 0) - (oldest_hist.get("page_count") or 0))
        # Stima ratio color/bw uguale alla ratio totale
        color_ratio = (p.get("color_page_count") or 0) / max(p.get("page_count") or 1, 1)
        color_30d = round(pages_30d * color_ratio)
        bw_30d = pages_30d - color_30d
        cpp_bw = float(p.get("cpp_bw") or 0)
        cpp_color = float(p.get("cpp_color") or 0)
        cost_30d = (bw_30d * cpp_bw) + (color_30d * cpp_color)
        monthly_cost_total += cost_30d
        if pages_30d > 0:
            cost_breakdown.append({
                "device_ip": device_ip,
                "device_name": p.get("device_name") or device_ip,
                "location": p.get("location"),
                "asset_tag": p.get("asset_tag"),
                "pages_30d": pages_30d,
                "bw_pages_30d": bw_30d,
                "color_pages_30d": color_30d,
                "cost_30d": round(cost_30d, 2),
            })
    cost_breakdown.sort(key=lambda x: x["cost_30d"], reverse=True)

    # Supplies critici (forecast ≤ 10gg)
    supplies_critical = []
    for p in printers:
        device_ip = p.get("device_ip")
        if not device_ip:
            continue
        history = await db.printer_history.find(
            {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff_30d}},
            {"_id": 0},
        ).sort("timestamp", 1).to_list(200)
        for s in p.get("supplies", []) or []:
            fc = _compute_supply_forecast(s.get("level_pct"), history, s.get("name") or "")
            if fc.get("days_remaining") is not None and fc["days_remaining"] <= 10:
                supplies_critical.append({
                    "device_ip": device_ip,
                    "device_name": p.get("device_name") or device_ip,
                    "supply_name": s.get("name"),
                    "level_pct": s.get("level_pct"),
                    "days_remaining": fc["days_remaining"],
                    "color_hex": s.get("color_hex"),
                })
    supplies_critical.sort(key=lambda x: x.get("days_remaining") or 999)

    # Locations summary (multi-sede)
    loc_map: Dict[str, Dict[str, Any]] = {}
    for p in printers:
        loc = p.get("location") or "—"
        if loc not in loc_map:
            loc_map[loc] = {"location": loc, "count": 0, "total_pages": 0}
        loc_map[loc]["count"] += 1
        loc_map[loc]["total_pages"] += p.get("page_count") or 0
    locations_summary = sorted(loc_map.values(), key=lambda x: -x["count"])

    return {
        "total_printers": len(printers),
        "page_breakdown": {
            "total": total_pages,
            "bw": total_bw,
            "color": total_color,
            "duplex": total_duplex,
            "large_format": total_large,
            "scan": total_scan,
            "fax": total_fax,
            "color_ratio": round(total_color / max(total_pages, 1) * 100, 1),
        },
        "estimated_monthly_cost": round(monthly_cost_total, 2),
        "cost_breakdown_top10": cost_breakdown[:10],
        "supplies_critical": supplies_critical[:20],
        "locations_summary": locations_summary,
    }


@router.get("/{client_id}/export-csv")
async def export_printers_csv(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Esporta CSV completo del parco stampanti del cliente."""
    printers = await db.printer_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)

    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    buf = io.StringIO()
    cols = [
        "device_name", "device_ip", "model", "serial", "asset_tag",
        "location", "cost_center", "contract_ref",
        "status", "online",
        "total_pages", "bw_pages", "color_pages", "duplex_pages",
        "large_format_pages", "scan_count", "fax_count",
        "pages_last_30d", "cpp_bw_eur", "cpp_color_eur", "cost_last_30d_eur",
        "supplies",
        "last_poll",
    ]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()

    for p in printers:
        device_ip = p.get("device_ip") or ""
        # Pagine ultimi 30gg
        oldest_hist = await db.printer_history.find_one(
            {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff_30d}},
            {"_id": 0, "page_count": 1},
            sort=[("timestamp", 1)],
        )
        pages_30d = 0
        if oldest_hist:
            pages_30d = max(0, (p.get("page_count") or 0) - (oldest_hist.get("page_count") or 0))
        total_pages = p.get("page_count") or 0
        color_pages = p.get("color_page_count") or 0
        bw_pages = max(0, total_pages - color_pages)
        cpp_bw = float(p.get("cpp_bw") or 0)
        cpp_color = float(p.get("cpp_color") or 0)
        color_ratio = color_pages / max(total_pages, 1)
        color_30d = round(pages_30d * color_ratio)
        bw_30d = pages_30d - color_30d
        cost_30d = round((bw_30d * cpp_bw) + (color_30d * cpp_color), 2)
        supplies_str = "; ".join(
            f"{s.get('name','?')}={s.get('level_pct','?')}%"
            for s in (p.get("supplies") or [])
        )
        w.writerow({
            "device_name": p.get("device_name") or device_ip,
            "device_ip": device_ip,
            "model": p.get("model") or "",
            "serial": p.get("serial") or "",
            "asset_tag": p.get("asset_tag") or "",
            "location": p.get("location") or "",
            "cost_center": p.get("cost_center") or "",
            "contract_ref": p.get("contract_ref") or "",
            "status": p.get("printer_status") or "",
            "online": "yes" if p.get("reachable") else "no",
            "total_pages": total_pages,
            "bw_pages": bw_pages,
            "color_pages": color_pages,
            "duplex_pages": p.get("duplex_count") or 0,
            "large_format_pages": p.get("large_format_count") or 0,
            "scan_count": p.get("scan_count") or 0,
            "fax_count": p.get("fax_count") or 0,
            "pages_last_30d": pages_30d,
            "cpp_bw_eur": cpp_bw,
            "cpp_color_eur": cpp_color,
            "cost_last_30d_eur": cost_30d,
            "supplies": supplies_str,
            "last_poll": p.get("last_poll") or "",
        })

    csv_data = buf.getvalue()
    filename = f"argus_stampanti_{client_id[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
