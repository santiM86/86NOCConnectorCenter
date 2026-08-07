"""PDF Report Generation for clients — multi-pagina professionale.

Struttura del report:
  1. Copertina (brand, nome cliente, data, KPI riepilogo)
  2. Inventario dispositivi (raggruppato per tipo)
  3. Porte switch + consumo PoE (per switch)
  4. Adiacenze LLDP (mappa di rete tabellare)
  5. SLA per dispositivo + ultimi alert + modifiche rete
"""
import io
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from database import db
from deps import get_current_user, require_admin
from display_name import best_display_name
from device_type_resolver import best_device_type

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak
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

# Etichette italiane per i device_type canonici
TYPE_LABELS = {
    "firewall": "Firewall",
    "router": "Router",
    "switch": "Switch",
    "server": "Server",
    "ilo": "iLO / BMC",
    "nas": "NAS / Storage",
    "access-point": "Access Point",
    "printer": "Stampanti",
    "voip": "Telefoni VoIP",
    "tvcc": "Videosorveglianza",
    "ups": "UPS",
    "workstation": "Workstation",
    "endpoint": "Endpoint",
    "endpoint-private": "Endpoint (privacy)",
    "mobile": "Dispositivi mobili",
    "iot": "IoT",
    "generic": "Altri dispositivi",
}
# Ordine di presentazione dei gruppi nell'inventario
TYPE_ORDER = [
    "firewall", "router", "switch", "server", "ilo", "nas",
    "access-point", "printer", "voip", "tvcc", "ups",
    "workstation", "endpoint", "endpoint-private", "mobile", "iot", "generic",
]


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
        name="SubHeader", fontName="Helvetica-Bold", fontSize=10,
        textColor=BRAND_DARK, spaceBefore=10, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name="BodyText2", fontName="Helvetica", fontSize=9,
        textColor=BRAND_DARK, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name="SmallGray", fontName="Helvetica", fontSize=8,
        textColor=BRAND_GRAY
    ))
    # Stili copertina
    styles.add(ParagraphStyle(
        name="CoverBrand", fontName="Helvetica-Bold", fontSize=14,
        textColor=BRAND_INDIGO, spaceAfter=2, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="CoverTitle", fontName="Helvetica-Bold", fontSize=30,
        textColor=BRAND_DARK, spaceAfter=6, alignment=TA_CENTER, leading=34
    ))
    styles.add(ParagraphStyle(
        name="CoverClient", fontName="Helvetica-Bold", fontSize=20,
        textColor=BRAND_INDIGO, spaceAfter=4, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="CoverMeta", fontName="Helvetica", fontSize=11,
        textColor=BRAND_GRAY, alignment=TA_CENTER, spaceAfter=2
    ))
    return styles


def make_table(headers, rows, col_widths=None, align="LEFT"):
    data = [headers] + rows
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), align),
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


def _fmt_speed(mbps):
    try:
        m = int(mbps or 0)
    except (TypeError, ValueError):
        return "-"
    if m <= 0:
        return "-"
    if m >= 1000 and m % 1000 == 0:
        return f"{m // 1000}G"
    if m >= 1000:
        return f"{m / 1000:.1f}G"
    return f"{m}M"


def _make_footer(brand_name, generated_str):
    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(BRAND_GRAY)
        canvas.drawString(2 * cm, 1.2 * cm,
                          f"{brand_name} — Report di Rete · Generato {generated_str} UTC")
        canvas.drawRightString(19 * cm, 1.2 * cm, f"Pagina {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#e4e4e7"))
        canvas.line(2 * cm, 1.5 * cm, 19 * cm, 1.5 * cm)
        canvas.restoreState()
    return _on_page


@router.get("/generate/{client_id}")
async def generate_client_report(
    client_id: str,
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Genera un report PDF multi-pagina per un cliente."""
    require_admin(current_user)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    client_name = client.get("name", client_id)
    # White-label: usa il brand configurato per il cliente/tenant se presente
    brand_name = (
        client.get("brand_name")
        or client.get("white_label_name")
        or "86BIT NOC"
    )
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    # ---- Raccolta dati ----
    managed = await db.managed_devices.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(5000)

    poll = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(5000)
    poll_by_ip = {p.get("device_ip"): p for p in poll if p.get("device_ip")}

    switch_ports = await db.switch_ports.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("idx", 1).to_list(20000)

    lldp = await db.lldp_neighbors.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(2000)

    alerts = await db.alerts.find(
        {"client_id": client_id, "created_at": {"$gte": cutoff}}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    changes = await db.network_changes.find(
        {"client_id": client_id, "timestamp": {"$gte": cutoff}}, {"_id": 0}
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
    sla_data = await db.metrics_history.aggregate(sla_pipeline).to_list(5000)

    # ---- Normalizza inventario (display name + device_type canonico) ----
    inventory = []
    for md in managed:
        ip = md.get("ip") or md.get("ip_address") or ""
        pd = poll_by_ip.get(ip, {})
        name = best_display_name(md, pd, ip)
        dtype = best_device_type(md, pd, name)
        reachable = bool(pd.get("reachable")) or md.get("status") in ("online", "active")
        inventory.append({
            "ip": ip,
            "name": name,
            "type": dtype,
            "vendor": md.get("vendor") or pd.get("vendor") or "",
            "model": md.get("model") or "",
            "reachable": reachable,
        })

    total_devices = len(inventory)
    online = sum(1 for d in inventory if d["reachable"])
    offline = total_devices - online
    n_switches = sum(1 for d in inventory if d["type"] == "switch")
    total_ports = len(switch_ports)
    ports_up = sum(1 for p in switch_ports if int(p.get("oper", 0) or 0) == 1)
    poe_ports = [p for p in switch_ports if int(p.get("poe_status", 0) or 0) == 3]
    total_poe_watt = round(sum(float(p.get("poe_watt", 0) or 0) for p in poe_ports), 1)
    total_alerts = len(alerts)
    critical_alerts = sum(1 for a in alerts if a.get("severity") == "critical")

    overall_sla = 0
    if sla_data:
        total_up = sum(s["up"] for s in sla_data)
        total_checks = sum(s["total"] for s in sla_data)
        overall_sla = round((total_up / total_checks * 100), 2) if total_checks > 0 else 0

    # ---- Build PDF ----
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Report di Rete — {client_name}",
        author=brand_name,
    )
    styles = get_styles()
    story = []

    # ===== PAGINA 1 — COPERTINA =====
    story.append(Spacer(1, 55 * mm))
    story.append(Paragraph(brand_name, styles["CoverBrand"]))
    story.append(HRFlowable(width="40%", thickness=2, color=BRAND_INDIGO,
                            spaceBefore=6, spaceAfter=18, hAlign="CENTER"))
    story.append(Paragraph("Report di Rete", styles["CoverTitle"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(client_name, styles["CoverClient"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        f"Periodo: {(now - timedelta(days=days)).strftime('%d/%m/%Y')} — {now.strftime('%d/%m/%Y')}",
        styles["CoverMeta"]))
    story.append(Paragraph(
        f"Generato il {now.strftime('%d/%m/%Y %H:%M')} UTC", styles["CoverMeta"]))
    story.append(Spacer(1, 16 * mm))

    kpi_data = [
        ["Dispositivi", "Online", "Offline", "SLA"],
        [str(total_devices), str(online), str(offline), f"{overall_sla}%"],
    ]
    kpi_tbl = Table(kpi_data, colWidths=[4 * cm, 4 * cm, 4 * cm, 4 * cm], hAlign="CENTER")
    kpi_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_GRAY),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 20),
        ("TEXTCOLOR", (0, 1), (0, 1), BRAND_DARK),
        ("TEXTCOLOR", (1, 1), (1, 1), BRAND_GREEN),
        ("TEXTCOLOR", (2, 1), (2, 1), BRAND_RED if offline else BRAND_GRAY),
        ("TEXTCOLOR", (3, 1), (3, 1), BRAND_INDIGO),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#e4e4e7")),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, colors.HexColor("#e4e4e7")),
    ]))
    story.append(kpi_tbl)
    story.append(PageBreak())

    # ===== SEZIONE — RIEPILOGO ESECUTIVO =====
    story.append(Paragraph(f"Report di Rete — {client_name}", styles["ReportTitle"]))
    story.append(Paragraph(
        f"Periodo {(now - timedelta(days=days)).strftime('%d/%m/%Y')} - {now.strftime('%d/%m/%Y')}",
        styles["ReportSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_INDIGO, spaceAfter=12))

    story.append(Paragraph("Riepilogo Esecutivo", styles["SectionHeader"]))
    summary_rows = [
        ["Dispositivi Monitorati", str(total_devices)],
        ["Online", str(online)],
        ["Offline", str(offline)],
        ["SLA Complessivo", f"{overall_sla}%"],
        ["Switch gestiti", str(n_switches)],
        ["Porte switch (totali / attive)", f"{total_ports} / {ports_up}"],
        ["Porte PoE attive", str(len(poe_ports))],
        ["Consumo PoE totale", f"{total_poe_watt} W"],
        ["Adiacenze LLDP", str(len(lldp))],
        ["Alert nel periodo (di cui critici)", f"{total_alerts} ({critical_alerts})"],
        ["Modifiche rete rilevate", str(len(changes))],
    ]
    story.append(make_table(["Metrica", "Valore"], summary_rows, col_widths=[10 * cm, 6 * cm]))

    # ===== SEZIONE — INVENTARIO DISPOSITIVI =====
    story.append(PageBreak())
    story.append(Paragraph("Inventario Dispositivi", styles["SectionHeader"]))
    if inventory:
        by_type = {}
        for d in inventory:
            by_type.setdefault(d["type"], []).append(d)
        ordered_types = [t for t in TYPE_ORDER if t in by_type]
        ordered_types += [t for t in by_type if t not in TYPE_ORDER]

        for t in ordered_types:
            group = sorted(by_type[t], key=lambda x: x.get("ip", ""))
            label = TYPE_LABELS.get(t, t.title())
            rows = []
            for d in group:
                rows.append([
                    d["name"][:40],
                    d["ip"],
                    (d["vendor"] or "-")[:20],
                    (d["model"] or "-")[:20],
                    "Online" if d["reachable"] else "OFFLINE",
                ])
            block = [
                Paragraph(f"{label} ({len(group)})", styles["SubHeader"]),
                make_table(
                    ["Nome", "IP", "Vendor", "Modello", "Stato"], rows,
                    col_widths=[5.5 * cm, 3 * cm, 3 * cm, 3 * cm, 2.5 * cm],
                ),
                Spacer(1, 4 * mm),
            ]
            story.append(KeepTogether(block) if len(group) <= 20 else block[0])
            if len(group) > 20:
                story.extend(block[1:])
    else:
        story.append(Paragraph("Nessun dispositivo in inventario.", styles["BodyText2"]))

    # ===== SEZIONE — PORTE SWITCH + PoE =====
    story.append(PageBreak())
    story.append(Paragraph("Porte Switch e Consumo PoE", styles["SectionHeader"]))
    ports_by_switch = {}
    for p in switch_ports:
        ports_by_switch.setdefault(p.get("local_ip"), []).append(p)

    if ports_by_switch:
        name_by_ip = {d["ip"]: d["name"] for d in inventory}
        for sw_ip in sorted(ports_by_switch.keys()):
            sw_ports = sorted(ports_by_switch[sw_ip], key=lambda x: int(x.get("idx", 0) or 0))
            sw_name = name_by_ip.get(sw_ip, sw_ip)
            sw_poe_ports = [p for p in sw_ports if int(p.get("poe_status", 0) or 0) == 3]
            sw_poe_watt = round(sum(float(p.get("poe_watt", 0) or 0) for p in sw_poe_ports), 1)
            sw_up = sum(1 for p in sw_ports if int(p.get("oper", 0) or 0) == 1)

            story.append(Paragraph(
                f"{sw_name} — {sw_ip}", styles["SubHeader"]))
            story.append(Paragraph(
                f"Porte: {len(sw_ports)} · Attive: {sw_up} · PoE attive: {len(sw_poe_ports)} · "
                f"Consumo PoE: {sw_poe_watt} W",
                styles["SmallGray"]))
            story.append(Spacer(1, 2 * mm))

            rows = []
            for p in sw_ports:
                oper = int(p.get("oper", 0) or 0)
                admin = int(p.get("admin", 0) or 0)
                oper_lbl = "UP" if oper == 1 else ("DOWN" if admin == 1 else "adm-down")
                poe_st = int(p.get("poe_status", 0) or 0)
                poe_cls = int(p.get("poe_class", 0) or 0)
                poe_w = float(p.get("poe_watt", 0) or 0)
                poe_lbl = "-"
                if poe_st == 3:
                    poe_lbl = f"{poe_w:.1f} W"
                    if poe_cls:
                        poe_lbl += f" (cl.{poe_cls})"
                rows.append([
                    p.get("name", "")[:16],
                    (p.get("alias") or p.get("descr") or "-")[:26],
                    oper_lbl,
                    _fmt_speed(p.get("speed_mbps")),
                    poe_lbl,
                ])
            story.append(make_table(
                ["Porta", "Descrizione", "Stato", "Velocità", "PoE"], rows,
                col_widths=[2.8 * cm, 6.2 * cm, 2.2 * cm, 2.3 * cm, 3.5 * cm],
            ))
            story.append(Spacer(1, 6 * mm))
    else:
        story.append(Paragraph(
            "Nessun dato SNMP sulle porte switch disponibile. "
            "Attivare SNMP sugli switch per popolare questa sezione.",
            styles["BodyText2"]))

    # ===== SEZIONE — ADIACENZE LLDP (mappa tabellare) =====
    story.append(PageBreak())
    story.append(Paragraph("Adiacenze di Rete (LLDP)", styles["SectionHeader"]))
    if lldp:
        name_by_ip = {d["ip"]: d["name"] for d in inventory}
        lldp_rows = []
        for n in sorted(lldp, key=lambda x: (x.get("local_ip", ""), x.get("local_port_id", ""))):
            local_ip = n.get("local_ip", "")
            local_name = name_by_ip.get(local_ip, local_ip)
            local_port = n.get("local_port_desc") or n.get("local_port_id") or "-"
            remote_name = n.get("remote_sys_name") or n.get("remote_ip") or n.get("remote_chassis_id") or "-"
            remote_port = n.get("remote_port_desc") or n.get("remote_port_id") or "-"
            lldp_rows.append([
                local_name[:24], str(local_port)[:16],
                str(remote_name)[:24], str(remote_port)[:16],
            ])
        story.append(make_table(
            ["Dispositivo locale", "Porta locale", "Dispositivo remoto", "Porta remota"],
            lldp_rows,
            col_widths=[5 * cm, 3.5 * cm, 5 * cm, 3.5 * cm],
        ))
    else:
        story.append(Paragraph(
            "Nessuna adiacenza LLDP rilevata. Gli switch devono avere LLDP "
            "attivo e SNMP accessibile per popolare la topologia.",
            styles["BodyText2"]))

    # ===== SEZIONE — SLA / ALERT / MODIFICHE =====
    story.append(PageBreak())
    story.append(Paragraph("SLA per Dispositivo", styles["SectionHeader"]))
    if sla_data:
        sla_rows = []
        for s in sorted(sla_data, key=lambda x: x.get("_id", "")):
            ip = s["_id"]
            name = s.get("device_name", "") or ip
            pct = round((s["up"] / s["total"] * 100), 2) if s["total"] > 0 else 0
            avg_p = round(s["avg_ping"], 1) if s.get("avg_ping") else "-"
            status = "OK" if pct >= 99.9 else "ATTENZIONE" if pct >= 95 else "CRITICO"
            sla_rows.append([name[:32], ip, f"{pct}%", f"{avg_p} ms", status])
        story.append(make_table(
            ["Dispositivo", "IP", "Uptime %", "Ping Medio", "Stato SLA"], sla_rows,
            col_widths=[5 * cm, 3 * cm, 2.5 * cm, 2.5 * cm, 3 * cm],
        ))
    else:
        story.append(Paragraph("Nessun dato SLA disponibile per il periodo selezionato.", styles["BodyText2"]))

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
            ["Sev.", "Titolo", "Dispositivo", "Data"], alert_rows,
            col_widths=[2 * cm, 6 * cm, 4 * cm, 4 * cm],
        ))

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
            ["Tipo", "Sev.", "Dettaglio", "Data"], change_rows,
            col_widths=[3 * cm, 2 * cm, 7 * cm, 4 * cm],
        ))

    on_page = _make_footer(brand_name, now.strftime('%d/%m/%Y %H:%M'))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)

    safe_name = "".join(ch for ch in client_name if ch.isalnum() or ch in (" ", "-", "_")).strip().replace(" ", "_")
    filename = f"Report_{safe_name}_{now.strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/list")
async def list_available_reports(current_user: dict = Depends(get_current_user)):
    """Elenca i clienti disponibili per la generazione del report."""
    require_admin(current_user)
    clients = await db.clients.find({}, {"_id": 0}).to_list(100)
    result = []
    for c in clients:
        cid = c.get("id", "")
        dev_count = await db.managed_devices.count_documents({"client_id": cid})
        if not dev_count:
            dev_count = await db.device_poll_status.count_documents({"client_id": cid})
        result.append({
            "client_id": cid,
            "client_name": c.get("name", ""),
            "device_count": dev_count,
        })
    return result
