"""
NOC Alert Command Center - Report Generation
PDF and CSV report generation for SLA and alert statistics
"""
import io
import csv
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
import logging

logger = logging.getLogger("reports")

class ReportGenerator:
    """Generate PDF and CSV reports for NOC alerts and SLA metrics."""
    
    def __init__(self, db):
        self.db = db
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles."""
        self.styles.add(ParagraphStyle(
            name='NOCTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#FAFAFA'),
            spaceAfter=30
        ))
        self.styles.add(ParagraphStyle(
            name='NOCHeading',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#A1A1AA'),
            spaceAfter=12
        ))
        self.styles.add(ParagraphStyle(
            name='NOCBody',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#FAFAFA')
        ))
    
    async def generate_sla_report_pdf(
        self,
        client_id: Optional[str] = None,
        days: int = 30,
        include_details: bool = True
    ) -> bytes:
        """Generate SLA compliance report as PDF."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4,
            rightMargin=30,
            leftMargin=30,
            topMargin=30,
            bottomMargin=30
        )
        
        elements = []
        
        # Title
        title = f"SLA Compliance Report"
        if client_id:
            client = await self.db.clients.find_one({"id": client_id}, {"_id": 0})
            if client:
                title += f" - {client['name']}"
        
        elements.append(Paragraph(title, self.styles['Title']))
        elements.append(Paragraph(
            f"Period: Last {days} days | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 20))
        
        # Get SLA stats
        from sla import SLAManager
        sla_manager = SLAManager(self.db)
        stats = await sla_manager.get_sla_stats(client_id=client_id, days=days)
        
        # Summary table
        summary_data = [
            ['Metric', 'Value'],
            ['Total Alerts', str(stats['total_alerts'])],
            ['Resolved Alerts', str(stats['resolved_alerts'])],
            ['Resolution Rate', f"{stats['resolution_rate']:.1f}%"],
            ['Response SLA Compliance', f"{stats['response_sla_compliance']:.1f}%"],
            ['Resolution SLA Compliance', f"{stats['resolution_sla_compliance']:.1f}%"],
            ['Avg Response Time', f"{stats['avg_response_time_minutes']:.1f} min"],
            ['Avg Resolution Time', f"{stats['avg_resolution_time_minutes']:.1f} min"],
        ]
        
        summary_table = Table(summary_data, colWidths=[200, 150])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27272A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#0A0A0A')),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#FAFAFA')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#27272A')),
        ]))
        
        elements.append(Paragraph("Summary", self.styles['Heading2']))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # By Severity breakdown
        if stats.get('by_severity'):
            elements.append(Paragraph("By Severity", self.styles['Heading2']))
            
            severity_data = [['Severity', 'Total', 'Resolved', 'Response Compliance', 'Resolution Compliance']]
            for severity, data in stats['by_severity'].items():
                severity_data.append([
                    severity.upper(),
                    str(data['total']),
                    str(data['resolved']),
                    f"{data['response_compliance']:.1f}%",
                    f"{data['resolution_compliance']:.1f}%"
                ])
            
            severity_table = Table(severity_data, colWidths=[80, 60, 60, 120, 120])
            severity_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27272A')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#0A0A0A')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#FAFAFA')),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#27272A')),
            ]))
            
            elements.append(severity_table)
            elements.append(Spacer(1, 20))
        
        # SLA Breaches list
        if include_details:
            elements.append(Paragraph("SLA Breaches", self.styles['Heading2']))
            
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            breaches = await self.db.sla_breaches.find(
                {"timestamp": {"$gte": cutoff}},
                {"_id": 0}
            ).sort("timestamp", -1).to_list(100)
            
            if breaches:
                breach_data = [['Time', 'Severity', 'Type', 'Elapsed (min)']]
                for breach in breaches[:50]:  # Limit to 50 for PDF
                    breach_data.append([
                        breach['timestamp'][:16].replace('T', ' '),
                        breach['severity'].upper(),
                        breach['breach_type'],
                        f"{breach['elapsed_minutes']:.0f}"
                    ])
                
                breach_table = Table(breach_data, colWidths=[120, 80, 80, 80])
                breach_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27272A')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#0A0A0A')),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#FAFAFA')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#27272A')),
                ]))
                
                elements.append(breach_table)
            else:
                elements.append(Paragraph("No SLA breaches in this period.", self.styles['Normal']))
        
        # Footer
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(
            "Generated by NOC Command Center",
            self.styles['Normal']
        ))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
    
    async def generate_alerts_csv(
        self,
        client_id: Optional[str] = None,
        days: int = 30,
        status: Optional[str] = None
    ) -> str:
        """Generate alerts export as CSV."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        query = {"created_at": {"$gte": cutoff}}
        if client_id:
            query["client_id"] = client_id
        if status:
            query["status"] = status
        
        alerts = await self.db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(100000)
        
        # Get device and client info
        device_ids = list(set(a.get("device_id") for a in alerts if a.get("device_id")))
        client_ids = list(set(a.get("client_id") for a in alerts if a.get("client_id")))
        
        devices = await self.db.devices.find({"id": {"$in": device_ids}}, {"_id": 0}).to_list(10000)
        clients = await self.db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
        
        device_map = {d["id"]: d for d in devices}
        client_map = {c["id"]: c["name"] for c in clients}
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'Alert ID', 'Created At', 'Status', 'Severity', 'Source',
            'Title', 'Message', 'Device Name', 'Device IP', 'Device Type',
            'Client Name', 'Acknowledged By', 'Acknowledged At', 'Resolved At',
            'Response SLA Breached', 'Resolution SLA Breached', 'Escalation Level'
        ])
        
        # Data rows
        for alert in alerts:
            device = device_map.get(alert.get("device_id"), {})
            writer.writerow([
                alert.get("id", ""),
                alert.get("created_at", ""),
                alert.get("status", ""),
                alert.get("severity", ""),
                alert.get("source_type", ""),
                alert.get("title", ""),
                alert.get("message", "")[:200],  # Truncate long messages
                device.get("name", ""),
                device.get("ip_address", ""),
                device.get("device_type", ""),
                client_map.get(alert.get("client_id"), ""),
                alert.get("acknowledged_by", ""),
                alert.get("acknowledged_at", ""),
                alert.get("resolved_at", ""),
                "Yes" if alert.get("sla_response_breached") else "No",
                "Yes" if alert.get("sla_resolution_breached") else "No",
                alert.get("escalation_level", 0)
            ])
        
        return output.getvalue()
    
    async def generate_devices_csv(self, client_id: Optional[str] = None) -> str:
        """Generate devices export as CSV."""
        query = {}
        if client_id:
            query["client_id"] = client_id
        
        devices = await self.db.devices.find(query, {"_id": 0}).to_list(10000)
        
        # Get client names
        client_ids = list(set(d.get("client_id") for d in devices))
        clients = await self.db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
        client_map = {c["id"]: c["name"] for c in clients}
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            'Device ID', 'Name', 'Type', 'IP Address', 'Hostname',
            'Location', 'Client Name', 'Status', 'Redfish Enabled',
            'Health Status', 'Last Poll', 'Created At'
        ])
        
        for device in devices:
            writer.writerow([
                device.get("id", ""),
                device.get("name", ""),
                device.get("device_type", ""),
                device.get("ip_address", ""),
                device.get("hostname", ""),
                device.get("location", ""),
                client_map.get(device.get("client_id"), ""),
                device.get("status", ""),
                "Yes" if device.get("redfish_enabled") else "No",
                device.get("health_status", ""),
                device.get("last_poll", ""),
                device.get("created_at", "")
            ])
        
        return output.getvalue()
    
    async def generate_daily_summary_pdf(self) -> bytes:
        """Generate daily summary report PDF."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        
        elements.append(Paragraph(
            f"Daily Alert Summary - {today.strftime('%Y-%m-%d')}",
            self.styles['Title']
        ))
        elements.append(Spacer(1, 20))
        
        # Get yesterday's stats
        start = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        
        alerts = await self.db.alerts.find({
            "created_at": {
                "$gte": start.isoformat(),
                "$lt": end.isoformat()
            }
        }, {"_id": 0}).to_list(100000)
        
        # Summary stats
        total = len(alerts)
        by_severity = {}
        by_status = {}
        for alert in alerts:
            sev = alert.get("severity", "unknown")
            status = alert.get("status", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
        
        summary_data = [
            ['Metric', 'Value'],
            ['Total Alerts', str(total)],
            ['Critical', str(by_severity.get('critical', 0))],
            ['High', str(by_severity.get('high', 0))],
            ['Medium', str(by_severity.get('medium', 0))],
            ['Low', str(by_severity.get('low', 0))],
            ['Resolved', str(by_status.get('resolved', 0))],
            ['Acknowledged', str(by_status.get('acknowledged', 0))],
            ['Active', str(by_status.get('active', 0))],
        ]
        
        table = Table(summary_data, colWidths=[150, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27272A')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        
        elements.append(table)
        
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
