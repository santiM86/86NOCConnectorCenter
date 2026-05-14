"""PDF Report Generation for clients."""
import io
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from database import db
from deps import get_current_user

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

logger = logging.getLogger("reports")
router = APIRouter(prefix="/api/reports", tags=["reports"])

BRAND_DARK = colors.HexColor("#0a0a0a")
BRAND_INDIGO = colors.HexColor("#6366f1")
BRAND_GREEN = colors.HexColor("#10b981")
BRAND_RED = colors.HexColor("#ef4444")
BRAND_AMBER = colors.HexColor("#f59e0b")
BRAND_GRAY = colors.HexColor("#71717a")
BRAND_LIGHT = colors.HexColor("#fafafa")


def get_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", fontName="Helvetica-Bold", fontSize=22,
        textColor=BRAND_DARK, spaceAfter=4, alignment=TA_LEFT
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", fontName="Helvetica", fontSize=11,
        textColor=BRAND_GRAY, spaceAfter=16, alignment=TA_LEFT
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader", fontName="Helvetica-Bold", fontSize=13,
        textColor=BRAND_INDIGO, spaceBefore=18, spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="BodyText2", fontName="Helvetica", fontSize=9,
        textColor=BRAND_DARK, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name="SmallGray", fontName="Helvetica", fontSize=8,
        textColor=BRAND_GRAY
    ))
    return styles


def make_table(headers, rows, col_widths=None):
    data = [headers] + rows
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e4e4e7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(style)
    return t


@router.get("/generate/{client_id}")
async def generate_client_report(
    client_id: str,
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Generate a PDF report for a client."""
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    client_name = client.get("name", client_id)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)

    alerts = await db.alerts.find(
        {"client_id": client_id, "created_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    changes = await db.network_changes.find(
        {"client_id": client_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(200)

    sla_pipeline = [
        {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$device_ip",
            "device_name": {"$first": "$device_name"},
            "total": {"$sum": 1},
            "up": {"$sum": {"$cond": ["$reachable", 1, 0]}},
            "avg_ping": {"$avg": "$ping_ms"},
        }},
    ]
    sla_data = await db.metrics_history.aggregate(sla_pipeline).to_list(500)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    styles = get_styles()
    story = []

    story.append(Paragraph("86BIT NOC", styles["SmallGray"]))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(f"Report di Rete — {client_name}", styles["ReportTitle"]))
    story.append(Paragraph(
        f"Periodo: {(now - timedelta(days=days)).strftime('%d/%m/%Y')} - {now.strftime('%d/%m/%Y')} | "
        f"Generato: {now.strftime('%d/%m/%Y %H:%M')} UTC",
        styles["ReportSubtitle"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_INDIGO, spaceAfter=12))

    online = sum(1 for d in devices if d.get("reachable"))
    offline = len(devices) - online
    total_alerts = len(alerts)
    critical_alerts = sum(1 for a in alerts if a.get("severity") == "critical")

    summary_data = [
        ["Metrica", "Valore"],
        ["Dispositivi Monitorati", str(len(devices))],
        ["Online", str(online)],
        ["Offline", str(offline)],
        ["Alert nel Periodo", str(total_alerts)],
        ["Alert Critici", str(critical_alerts)],
        ["Modifiche Rete", str(len(changes))],
    ]

    overall_sla = 0
    if sla_data:
        total_up = sum(s["up"] for s in sla_data)
        total_checks = sum(s["total"] for s in sla_data)
        overall_sla = round((total_up / total_checks * 100), 2) if total_checks > 0 else 0
    summary_data.append(["SLA Complessivo", f"{overall_sla}%"])

    story.append(Paragraph("Riepilogo Esecutivo", styles["SectionHeader"]))
    story.append(make_table(
        summary_data[0], summary_data[1:],
        col_widths=[10*cm, 6*cm]
    ))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("SLA per Dispositivo", styles["SectionHeader"]))
    if sla_data:
        sla_rows = []
        for s in sorted(sla_data, key=lambda x: x.get("_id", "")):
            ip = s["_id"]
            name = s.get("device_name", "")
            pct = round((s["up"] / s["total"] * 100), 2) if s["total"] > 0 else 0
            avg_p = round(s["avg_ping"], 1) if s["avg_ping"] else "-"
            status = "OK" if pct >= 99.9 else "ATTENZIONE" if pct >= 95 else "CRITICO"
            sla_rows.append([name or ip, ip, f"{pct}%", f"{avg_p} ms", status])
        story.append(make_table(
            ["Dispositivo", "IP", "Uptime %", "Ping Medio", "Stato SLA"],
            sla_rows,
            col_widths=[5*cm, 3*cm, 2.5*cm, 2.5*cm, 3*cm]
        ))
    else:
        story.append(Paragraph("Nessun dato SLA disponibile per il periodo selezionato.", styles["BodyText2"]))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Dispositivi Monitorati", styles["SectionHeader"]))
    if devices:
        dev_rows = []
        for d in sorted(devices, key=lambda x: x.get("device_ip", "")):
            status = "Online" if d.get("reachable") else "OFFLINE"
            mtype = d.get("monitor_type", "PING").upper()
            name = d.get("device_name", "-")
            dev_rows.append([name, d.get("device_ip", ""), mtype, status])
        story.append(make_table(
            ["Nome", "IP", "Tipo", "Stato"],
            dev_rows,
            col_widths=[6*cm, 4*cm, 3*cm, 3*cm]
        ))
    story.append(Spacer(1, 6*mm))

    if alerts:
        story.append(Paragraph("Ultimi Alert", styles["SectionHeader"]))
        alert_rows = []
        for a in alerts[:30]:
            ts = a.get("created_at", "")[:16].replace("T", " ")
            alert_rows.append([
                a.get("severity", "").upper()[:4],
                a.get("title", "")[:40],
                a.get("device_name", ""),
                ts,
            ])
        story.append(make_table(
            ["Sev.", "Titolo", "Dispositivo", "Data"],
            alert_rows,
            col_widths=[2*cm, 6*cm, 4*cm, 4*cm]
        ))
        story.append(Spacer(1, 6*mm))

    if changes:
        story.append(Paragraph("Modifiche Rete Rilevate", styles["SectionHeader"]))
        change_rows = []
        for c in changes[:20]:
            ts = c.get("timestamp", "")[:16].replace("T", " ")
            change_rows.append([
                c.get("type", "").replace("_", " ").title(),
                c.get("severity", "").upper(),
                c.get("message", "")[:50],
                ts,
            ])
        story.append(make_table(
            ["Tipo", "Sev.", "Dettaglio", "Data"],
            change_rows,
            col_widths=[3*cm, 2*cm, 7*cm, 4*cm]
        ))

    story.append(Spacer(1, 15*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_GRAY, spaceAfter=4))
    story.append(Paragraph(
        f"Report generato automaticamente da 86BIT NOC Command Center | {now.strftime('%d/%m/%Y %H:%M')} UTC",
        styles["SmallGray"]
    ))

    doc.build(story)
    buf.seek(0)

    filename = f"Report_{client_name}_{now.strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/list")
async def list_available_reports(current_user: dict = Depends(get_current_user)):
    """List clients available for report generation."""
    clients = await db.clients.find({}, {"_id": 0}).to_list(100)
    result = []
    for c in clients:
        cid = c.get("id", "")
        dev_count = await db.device_poll_status.count_documents({"client_id": cid})
        result.append({
            "client_id": cid,
            "client_name": c.get("name", ""),
            "device_count": dev_count,
        })
    return result
