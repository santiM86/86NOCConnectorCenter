"""
NOC Alert Command Center - Notification Service
Multi-channel notifications: Email, Push, Webhook
"""
import os
import json
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from enum import Enum

logger = logging.getLogger("notifications")

class NotificationChannel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    WEBHOOK = "webhook"
    TEAMS = "teams"
    SLACK = "slack"
    TELEGRAM = "telegram"

class NotificationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class NotificationService:
    """Multi-channel notification service for alert delivery."""
    
    def __init__(self, db):
        self.db = db
        self.sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        self.firebase_credentials = os.environ.get('FIREBASE_CREDENTIALS_PATH')
        self.telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        
    async def send_notification(
        self,
        channels: List[NotificationChannel],
        title: str,
        message: str,
        priority: NotificationPriority,
        alert_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        recipients: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Send notification through multiple channels.
        
        Args:
            channels: List of channels to send through
            title: Notification title
            message: Notification message body
            priority: Alert priority level
            alert_id: Related alert ID
            data: Additional data payload
            recipients: List of recipient identifiers (emails, tokens, etc.)
            
        Returns:
            Dictionary with results for each channel
        """
        results = {}
        
        for channel in channels:
            try:
                if channel == NotificationChannel.EMAIL:
                    results["email"] = await self._send_email(title, message, recipients, priority)
                elif channel == NotificationChannel.PUSH:
                    results["push"] = await self._send_push(title, message, data, priority)
                elif channel == NotificationChannel.TEAMS:
                    results["teams"] = await self._send_teams(title, message, priority, alert_id)
                elif channel == NotificationChannel.SLACK:
                    results["slack"] = await self._send_slack(title, message, priority, alert_id)
                elif channel == NotificationChannel.TELEGRAM:
                    results["telegram"] = await self._send_telegram(title, message, priority)
                elif channel == NotificationChannel.WEBHOOK:
                    results["webhook"] = await self._send_webhook(title, message, data, priority)
            except Exception as e:
                logger.error(f"Failed to send {channel.value} notification: {e}")
                results[channel.value] = {"success": False, "error": str(e)}
        
        # Log notification
        await self._log_notification(channels, title, priority, results)
        
        return results
    
    async def _send_email(
        self,
        title: str,
        message: str,
        recipients: Optional[List[str]],
        priority: NotificationPriority
    ) -> Dict[str, Any]:
        """Send email notification via SendGrid."""
        if not self.sendgrid_api_key:
            # Mock mode
            logger.info(f"[MOCK EMAIL] To: {recipients}, Subject: {title}")
            return {"success": True, "mock": True, "recipients": recipients}
        
        try:
            async with httpx.AsyncClient() as client:
                for recipient in (recipients or []):
                    response = await client.post(
                        "https://api.sendgrid.com/v3/mail/send",
                        headers={
                            "Authorization": f"Bearer {self.sendgrid_api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "personalizations": [{"to": [{"email": recipient}]}],
                            "from": {"email": os.environ.get('SENDER_EMAIL', 'noc@yourdomain.com')},
                            "subject": f"[{priority.value.upper()}] {title}",
                            "content": [{"type": "text/html", "value": self._format_email_html(title, message, priority)}]
                        }
                    )
                    
            return {"success": True, "recipients": recipients}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _format_email_html(self, title: str, message: str, priority: NotificationPriority) -> str:
        """Format email as HTML."""
        colors = {
            NotificationPriority.CRITICAL: "#F87171",
            NotificationPriority.HIGH: "#FBBF24",
            NotificationPriority.MEDIUM: "#60A5FA",
            NotificationPriority.LOW: "#4ADE80"
        }
        color = colors.get(priority, "#71717A")
        
        return f"""
        <html>
        <body style="font-family: 'IBM Plex Sans', Arial, sans-serif; background-color: #0A0A0A; color: #FAFAFA; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #050505; border: 1px solid #27272A; padding: 24px;">
                <div style="border-left: 4px solid {color}; padding-left: 16px; margin-bottom: 20px;">
                    <h1 style="margin: 0; font-size: 20px; color: {color};">[{priority.value.upper()}] {title}</h1>
                </div>
                <p style="color: #A1A1AA; line-height: 1.6;">{message}</p>
                <hr style="border: none; border-top: 1px solid #27272A; margin: 20px 0;">
                <p style="font-size: 12px; color: #71717A;">
                    NOC Command Center | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
                </p>
            </div>
        </body>
        </html>
        """
    
    async def _send_push(
        self,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]],
        priority: NotificationPriority
    ) -> Dict[str, Any]:
        """Send push notification via Firebase Cloud Messaging."""
        if not self.firebase_credentials:
            # Mock mode
            logger.info(f"[MOCK PUSH] Title: {title}, Priority: {priority.value}")
            return {"success": True, "mock": True}
        
        # Firebase implementation would go here
        # For now, return mock response
        return {"success": True, "mock": True}
    
    async def _send_teams(
        self,
        title: str,
        message: str,
        priority: NotificationPriority,
        alert_id: Optional[str]
    ) -> Dict[str, Any]:
        """Send notification to Microsoft Teams via webhook."""
        webhook_url = await self._get_webhook_url("teams")
        if not webhook_url:
            logger.info(f"[MOCK TEAMS] {title}: {message}")
            return {"success": True, "mock": True}
        
        colors = {
            NotificationPriority.CRITICAL: "FF0000",
            NotificationPriority.HIGH: "FFA500",
            NotificationPriority.MEDIUM: "0078D4",
            NotificationPriority.LOW: "00FF00"
        }
        
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": colors.get(priority, "808080"),
            "summary": title,
            "sections": [{
                "activityTitle": f"🚨 [{priority.value.upper()}] {title}",
                "facts": [
                    {"name": "Message", "value": message},
                    {"name": "Time", "value": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')},
                ],
                "markdown": True
            }]
        }
        
        if alert_id:
            payload["potentialAction"] = [{
                "@type": "OpenUri",
                "name": "View Alert",
                "targets": [{"os": "default", "uri": f"/alerts/{alert_id}"}]
            }]
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=payload)
                return {"success": response.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_slack(
        self,
        title: str,
        message: str,
        priority: NotificationPriority,
        alert_id: Optional[str]
    ) -> Dict[str, Any]:
        """Send notification to Slack via webhook."""
        webhook_url = await self._get_webhook_url("slack")
        if not webhook_url:
            logger.info(f"[MOCK SLACK] {title}: {message}")
            return {"success": True, "mock": True}
        
        emojis = {
            NotificationPriority.CRITICAL: "🔴",
            NotificationPriority.HIGH: "🟠",
            NotificationPriority.MEDIUM: "🔵",
            NotificationPriority.LOW: "🟢"
        }
        
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emojis.get(priority, '⚪')} [{priority.value.upper()}] {title}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*NOC Command Center* | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        }
                    ]
                }
            ]
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=payload)
                return {"success": response.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_telegram(
        self,
        title: str,
        message: str,
        priority: NotificationPriority
    ) -> Dict[str, Any]:
        """Send notification to Telegram."""
        if not self.telegram_bot_token:
            logger.info(f"[MOCK TELEGRAM] {title}: {message}")
            return {"success": True, "mock": True}
        
        chat_id = await self._get_webhook_url("telegram")  # Stores chat_id
        if not chat_id:
            return {"success": True, "mock": True}
        
        emojis = {
            NotificationPriority.CRITICAL: "🚨",
            NotificationPriority.HIGH: "⚠️",
            NotificationPriority.MEDIUM: "ℹ️",
            NotificationPriority.LOW: "✅"
        }
        
        text = f"{emojis.get(priority, '📢')} *[{priority.value.upper()}] {title}*\n\n{message}"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown"
                    }
                )
                return {"success": response.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_webhook(
        self,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]],
        priority: NotificationPriority
    ) -> Dict[str, Any]:
        """Send notification to generic webhook."""
        webhook_url = await self._get_webhook_url("generic")
        if not webhook_url:
            logger.info(f"[MOCK WEBHOOK] {title}: {message}")
            return {"success": True, "mock": True}
        
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "priority": priority.value,
            "title": title,
            "message": message,
            "data": data or {}
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=payload)
                return {"success": response.status_code in [200, 201, 202]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _get_webhook_url(self, webhook_type: str) -> Optional[str]:
        """Get webhook URL from database settings."""
        setting = await self.db.settings.find_one(
            {"key": f"webhook_{webhook_type}"},
            {"_id": 0}
        )
        return setting.get("value") if setting else None
    
    async def _log_notification(
        self,
        channels: List[NotificationChannel],
        title: str,
        priority: NotificationPriority,
        results: Dict[str, Any]
    ):
        """Log notification to database."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channels": [c.value for c in channels],
            "title": title,
            "priority": priority.value,
            "results": results
        }
        await self.db.notification_logs.insert_one(log_entry)


class NotificationRules:
    """Rules engine for determining when and how to send notifications."""
    
    def __init__(self, db):
        self.db = db
    
    async def get_notification_config(self, severity: str) -> Dict[str, Any]:
        """Get notification configuration for a severity level."""
        config = await self.db.notification_rules.find_one(
            {"severity": severity},
            {"_id": 0}
        )
        
        if not config:
            # Default configuration
            return {
                "severity": severity,
                "channels": ["email", "push"] if severity == "critical" else ["email"],
                "delay_seconds": 0 if severity == "critical" else 60,
                "repeat_interval_minutes": 15 if severity == "critical" else 0,
                "escalate_after_minutes": 30 if severity == "critical" else None
            }
        
        return config
    
    async def should_notify(self, alert_id: str, severity: str) -> bool:
        """Determine if a notification should be sent for an alert."""
        config = await self.get_notification_config(severity)
        
        # Check if we've already notified recently
        recent = await self.db.notification_logs.find_one({
            "alert_id": alert_id,
            "timestamp": {"$gte": (datetime.now(timezone.utc) - 
                                   __import__('datetime').timedelta(minutes=config.get("repeat_interval_minutes", 0))).isoformat()}
        })
        
        return recent is None
