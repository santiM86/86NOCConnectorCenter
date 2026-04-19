"""Printer Management - SNMP-based printer monitoring with toner, page counts, status."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from database import db
from deps import get_current_user

logger = logging.getLogger("printers")
router = APIRouter(prefix="/api/printers", tags=["printers"])

# Printer status codes (HR-MIB .1.3.6.1.2.1.25.3.5.1.1)
PRINTER_STATUS = {
    1: {"label": "Altro", "severity": "warning"},
    2: {"label": "Sconosciuto", "severity": "warning"},
    3: {"label": "Idle", "severity": "ok"},
    4: {"label": "In Stampa", "severity": "ok"},
    5: {"label": "Riscaldamento", "severity": "ok"},
}

# Supply type codes
SUPPLY_TYPES = {
    1: "altro", 3: "toner", 4: "inchiostro", 5: "cartuccia_inchiostro",
    6: "cartuccia_toner", 7: "drum", 8: "nastro_trasferimento",
    9: "waste_toner", 12: "fuser", 13: "opc_drum",
}

SUPPLY_COLORS = {
    "black": "#1a1a1a", "nero": "#1a1a1a",
    "cyan": "#00bcd4", "ciano": "#00bcd4",
    "magenta": "#e91e63",
    "yellow": "#ffc107", "giallo": "#ffc107",
    "blue": "#2196f3", "blu": "#2196f3",
}


def detect_color(name: str) -> dict:
    """Detect toner color from supply name."""
    name_lower = name.lower()
    for key, hex_color in SUPPLY_COLORS.items():
        if key in name_lower:
            return {"color_name": key, "hex": hex_color}
    return {"color_name": "unknown", "hex": "#9e9e9e"}


@router.get("/dashboard/{client_id}")
async def printer_dashboard(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get printer dashboard summary for a client."""
    printers = await db.printer_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(200)

    total = len(printers)
    online = sum(1 for p in printers if p.get("reachable", False))
    offline = total - online

    low_toner = []
    errors = []
    for p in printers:
        for supply in p.get("supplies", []):
            level = supply.get("level_pct", 100)
            if level is not None and 0 < level <= 15:
                low_toner.append({
                    "printer_name": p.get("device_name", p.get("device_ip")),
                    "printer_ip": p.get("device_ip"),
                    "supply_name": supply.get("name", "?"),
                    "level_pct": level,
                })
        status = p.get("printer_status_code")
        if status and status not in [3, 4, 5]:
            errors.append({
                "printer_name": p.get("device_name", p.get("device_ip")),
                "printer_ip": p.get("device_ip"),
                "status": p.get("printer_status", "Errore"),
                "alerts": p.get("alert_messages", []),
            })

    total_pages = sum(p.get("page_count", 0) for p in printers)

    return {
        "total": total,
        "online": online,
        "offline": offline,
        "low_toner_count": len(low_toner),
        "low_toner": low_toner,
        "error_count": len(errors),
        "errors": errors,
        "total_pages": total_pages,
        "printers": printers,
    }


@router.get("/{client_id}")
async def list_printers(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get all printers for a client."""
    printers = await db.printer_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("device_name", 1).to_list(200)
    return printers


@router.get("/{client_id}/{device_ip}")
async def get_printer_detail(client_id: str, device_ip: str, current_user: dict = Depends(get_current_user)):
    """Get detailed printer info with supply history."""
    printer = await db.printer_status.find_one(
        {"client_id": client_id, "device_ip": device_ip}, {"_id": 0}
    )
    if not printer:
        raise HTTPException(status_code=404, detail="Stampante non trovata")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    history = await db.printer_history.find(
        {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(500)

    return {
        "printer": printer,
        "supply_history": history,
    }


@router.post("/process-poll")
async def process_printer_poll(request: Request):
    """Process printer SNMP poll data from the connector.
    Called by the connector after querying printer OIDs."""
    # Validate API key from connector and get client_id
    api_key = request.headers.get("X-API-Key")
    client_id = None
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if client_data:
            client_id = client_data["id"]
    
    body = await request.json()
    # Allow client_id from body (for seed/test) or from API key
    if not client_id:
        client_id = body.get("client_id", "")
    device_ip = body.get("device_ip", "")
    if not client_id or not device_ip:
        raise HTTPException(status_code=400, detail="client_id and device_ip required")

    now = datetime.now(timezone.utc).isoformat()

    supplies = body.get("supplies", [])
    for s in supplies:
        color_info = detect_color(s.get("name", ""))
        s["color_name"] = color_info["color_name"]
        s["color_hex"] = color_info["hex"]
        max_cap = s.get("max_capacity", 0)
        current = s.get("current_level", 0)
        if max_cap and max_cap > 0 and current >= 0:
            s["level_pct"] = round((current / max_cap) * 100, 1)
        elif current == -3:
            s["level_pct"] = None
            s["level_text"] = "OK"
        elif current == -2:
            s["level_pct"] = 0
            s["level_text"] = "Esaurito"
        else:
            s["level_pct"] = None

    doc = {
        "client_id": client_id,
        "device_ip": device_ip,
        "device_name": body.get("device_name", ""),
        "device_type": "printer",
        "model": body.get("model", ""),
        "serial": body.get("serial", ""),
        "reachable": body.get("reachable", True),
        "printer_status_code": body.get("printer_status_code"),
        "printer_status": body.get("printer_status", ""),
        "page_count": body.get("page_count", 0),
        "color_page_count": body.get("color_page_count", 0),
        "duplex_count": body.get("duplex_count", 0),
        "supplies": supplies,
        "trays": body.get("trays", []),
        "alert_messages": body.get("alert_messages", []),
        "last_poll": now,
        "updated_at": now,
    }

    await db.printer_status.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"$set": doc},
        upsert=True,
    )

    history_doc = {
        "client_id": client_id,
        "device_ip": device_ip,
        "timestamp": now,
        "page_count": body.get("page_count", 0),
        "supplies_snapshot": [{
            "name": s.get("name"), "level_pct": s.get("level_pct"),
            "color_name": s.get("color_name")
        } for s in supplies],
    }
    await db.printer_history.insert_one(history_doc)

    for s in supplies:
        level = s.get("level_pct")
        if level is not None and 0 < level <= 15:
            alert_doc = {
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "device_ip": device_ip,
                "device_name": body.get("device_name", device_ip),
                "title": f"Toner basso: {s.get('name', '?')} al {level}%",
                "severity": "high" if level <= 5 else "medium",
                "type": "supply_low",
                "status": "active",
                "created_at": now,
                "auto_generated": True,
            }
            existing_alert = await db.alerts.find_one({
                "client_id": client_id, "device_ip": device_ip,
                "type": "supply_low", "status": "active",
                "title": {"$regex": s.get("name", "?")}
            })
            if not existing_alert:
                await db.alerts.insert_one(alert_doc)
                try:
                    import webpush as _wp
                    await _wp.notify_new_alert(db, alert_doc)
                except Exception:
                    pass
                logger.info(f"Alert: Toner basso {s.get('name')} ({level}%) su {device_ip}")

    return {"status": "ok"}


@router.post("/seed-demo/{client_id}")
async def seed_demo_printers(client_id: str, current_user: dict = Depends(get_current_user)):
    """Seed demo printer data for testing the dashboard."""
    now = datetime.now(timezone.utc).isoformat()

    demo_printers = [
        {
            "device_ip": "192.168.1.30",
            "device_name": "HP LaserJet Pro M404dn - Reception",
            "model": "HP LaserJet Pro M404dn",
            "serial": "CNBJR8G05K",
            "reachable": True,
            "printer_status_code": 3,
            "printer_status": "Idle",
            "page_count": 45230,
            "color_page_count": 0,
            "duplex_count": 12450,
            "supplies": [
                {"name": "Black Toner CF259A", "type": "toner", "max_capacity": 3000, "current_level": 2100,
                 "level_pct": 70.0, "color_name": "black", "color_hex": "#1a1a1a"},
                {"name": "Imaging Drum CF259A", "type": "drum", "max_capacity": 10000, "current_level": 7500,
                 "level_pct": 75.0, "color_name": "unknown", "color_hex": "#9e9e9e"},
            ],
            "trays": [
                {"name": "Vassoio 1", "status": "ok", "capacity": 250, "level": 200},
                {"name": "Vassoio 2", "status": "ok", "capacity": 550, "level": 400},
            ],
            "alert_messages": [],
        },
        {
            "device_ip": "192.168.1.31",
            "device_name": "HP Color LaserJet M479fdw - Ufficio",
            "model": "HP Color LaserJet Pro MFP M479fdw",
            "serial": "CNBJR9H12M",
            "reachable": True,
            "printer_status_code": 3,
            "printer_status": "Idle",
            "page_count": 28750,
            "color_page_count": 15200,
            "duplex_count": 8900,
            "supplies": [
                {"name": "Black Toner W2030A", "type": "toner", "max_capacity": 2400, "current_level": 1920,
                 "level_pct": 80.0, "color_name": "black", "color_hex": "#1a1a1a"},
                {"name": "Cyan Toner W2031A", "type": "toner", "max_capacity": 2100, "current_level": 630,
                 "level_pct": 30.0, "color_name": "cyan", "color_hex": "#00bcd4"},
                {"name": "Magenta Toner W2033A", "type": "toner", "max_capacity": 2100, "current_level": 210,
                 "level_pct": 10.0, "color_name": "magenta", "color_hex": "#e91e63"},
                {"name": "Yellow Toner W2032A", "type": "toner", "max_capacity": 2100, "current_level": 1470,
                 "level_pct": 70.0, "color_name": "yellow", "color_hex": "#ffc107"},
            ],
            "trays": [
                {"name": "Vassoio 1", "status": "ok", "capacity": 250, "level": 180},
                {"name": "Vassoio 2", "status": "low", "capacity": 550, "level": 50},
            ],
            "alert_messages": ["Magenta toner low"],
        },
        {
            "device_ip": "192.168.1.32",
            "device_name": "Brother MFC-L8900CDW - Sala Riunioni",
            "model": "Brother MFC-L8900CDW",
            "serial": "E78234K1J",
            "reachable": True,
            "printer_status_code": 4,
            "printer_status": "In Stampa",
            "page_count": 67100,
            "color_page_count": 31500,
            "duplex_count": 22000,
            "supplies": [
                {"name": "Black Toner TN-436BK", "type": "toner", "max_capacity": 6500, "current_level": 325,
                 "level_pct": 5.0, "color_name": "black", "color_hex": "#1a1a1a"},
                {"name": "Cyan Toner TN-436C", "type": "toner", "max_capacity": 6500, "current_level": 4550,
                 "level_pct": 70.0, "color_name": "cyan", "color_hex": "#00bcd4"},
                {"name": "Magenta Toner TN-436M", "type": "toner", "max_capacity": 6500, "current_level": 5850,
                 "level_pct": 90.0, "color_name": "magenta", "color_hex": "#e91e63"},
                {"name": "Yellow Toner TN-436Y", "type": "toner", "max_capacity": 6500, "current_level": 3250,
                 "level_pct": 50.0, "color_name": "yellow", "color_hex": "#ffc107"},
                {"name": "Drum Unit DR-431CL", "type": "drum", "max_capacity": 30000, "current_level": 18000,
                 "level_pct": 60.0, "color_name": "unknown", "color_hex": "#9e9e9e"},
                {"name": "Waste Toner Box WT-320CL", "type": "waste_toner", "max_capacity": 50000, "current_level": 35000,
                 "level_pct": 70.0, "color_name": "unknown", "color_hex": "#9e9e9e"},
            ],
            "trays": [
                {"name": "Vassoio 1", "status": "ok", "capacity": 250, "level": 250},
                {"name": "Vassoio 2", "status": "ok", "capacity": 500, "level": 480},
            ],
            "alert_messages": ["Black toner critically low"],
        },
        {
            "device_ip": "192.168.1.33",
            "device_name": "Ricoh MP C3004 - Magazzino",
            "model": "Ricoh MP C3004",
            "serial": "W823N900456",
            "reachable": False,
            "printer_status_code": 1,
            "printer_status": "Offline",
            "page_count": 124500,
            "color_page_count": 58200,
            "duplex_count": 45000,
            "supplies": [
                {"name": "Black Toner", "type": "toner", "max_capacity": 29000, "current_level": 17400,
                 "level_pct": 60.0, "color_name": "black", "color_hex": "#1a1a1a"},
                {"name": "Cyan Toner", "type": "toner", "max_capacity": 18000, "current_level": 2700,
                 "level_pct": 15.0, "color_name": "cyan", "color_hex": "#00bcd4"},
                {"name": "Magenta Toner", "type": "toner", "max_capacity": 18000, "current_level": 12600,
                 "level_pct": 70.0, "color_name": "magenta", "color_hex": "#e91e63"},
                {"name": "Yellow Toner", "type": "toner", "max_capacity": 18000, "current_level": 9000,
                 "level_pct": 50.0, "color_name": "yellow", "color_hex": "#ffc107"},
            ],
            "trays": [
                {"name": "Vassoio 1", "status": "empty", "capacity": 550, "level": 0},
                {"name": "Vassoio 2", "status": "ok", "capacity": 550, "level": 300},
            ],
            "alert_messages": ["Vassoio 1 vuoto", "Stampante offline"],
        },
    ]

    for p in demo_printers:
        p["client_id"] = client_id
        p["device_type"] = "printer"
        p["last_poll"] = now
        p["updated_at"] = now
        await db.printer_status.update_one(
            {"client_id": client_id, "device_ip": p["device_ip"]},
            {"$set": p}, upsert=True
        )
        await db.printer_history.insert_one({
            "client_id": client_id, "device_ip": p["device_ip"],
            "timestamp": now, "page_count": p["page_count"],
            "supplies_snapshot": [{"name": s["name"], "level_pct": s["level_pct"], "color_name": s["color_name"]} for s in p["supplies"]],
        })

    return {"status": "ok", "seeded": len(demo_printers)}
