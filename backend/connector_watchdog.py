"""Connector watchdog — detects connectors that stopped sending heartbeats and generates alerts."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("connector_watchdog")

# A connector is considered offline if no heartbeat for this many seconds.
OFFLINE_THRESHOLD_SECONDS = 180  # 3 minutes (heartbeat happens every ~60s)
RECOVERY_GRACE_SECONDS = 60       # After recovery, wait this long before closing the alert


class ConnectorWatchdog:
    def __init__(self, db, notification_service=None):
        self.db = db
        self.notification_service = notification_service
        self.scheduler = AsyncIOScheduler()

    async def start(self, interval_seconds: int = 60):
        self.scheduler.add_job(
            self.check_all_connectors,
            IntervalTrigger(seconds=interval_seconds),
            id="connector_watchdog",
            name="Connector heartbeat watchdog",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),  # fire once at startup
        )
        self.scheduler.start()
        logger.info(f"Connector watchdog started (check every {interval_seconds}s)")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    async def check_all_connectors(self):
        """Periodic check: find connectors that stopped heartbeating and raise/clear alerts."""
        try:
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(seconds=OFFLINE_THRESHOLD_SECONDS)
            connectors = await self.db.connector_status.find({}, {"_id": 0}).to_list(1000)
            for c in connectors:
                client_id = c.get("client_id")
                if not client_id:
                    continue

                # Expire stuck "queued" force-updates if connector stayed offline too long (>10min)
                update_status = c.get("update_status")
                if update_status == "queued" and c.get("update_timestamp"):
                    try:
                        ts = datetime.fromisoformat(c["update_timestamp"].replace("Z", "+00:00"))
                        if (now - ts).total_seconds() > 600:
                            await self.db.connector_status.update_one(
                                {"client_id": client_id},
                                {"$set": {
                                    "update_status": "error",
                                    "update_progress": 0,
                                    "update_message": "Timeout: il connector non e' tornato online entro 10 minuti",
                                    "force_update": False,
                                }}
                            )
                            logger.warning(f"Update force timed out on {c.get('hostname', client_id)}")
                    except Exception:
                        pass

                hostname = c.get("hostname") or c.get("connector_hostname") or "unknown"
                client_name = c.get("client_name") or client_id[:8]
                last_seen_raw = c.get("last_seen")
                if not last_seen_raw:
                    continue
                try:
                    last_seen = datetime.fromisoformat(last_seen_raw.replace("Z", "+00:00"))
                except Exception:
                    continue
                elapsed = (now - last_seen).total_seconds()
                is_offline = last_seen < threshold

                # Find any existing active offline alert
                existing_alert = await self.db.alerts.find_one({
                    "client_id": client_id,
                    "source_type": "connector_watchdog",
                    "status": "active",
                })

                if is_offline:
                    if existing_alert:
                        continue  # already alerted
                    minutes_down = int(elapsed / 60)
                    # Create alert
                    alert_doc = {
                        "id": str(uuid.uuid4()),
                        "client_id": client_id,
                        "device_id": "",
                        "device_ip": "",
                        "device_name": hostname,
                        "device_type": "connector",
                        "severity": "critical",
                        "source_type": "connector_watchdog",
                        "title": f"CONNETTORE OFFLINE: {hostname}",
                        "message": (
                            f"Il connettore '{hostname}' del cliente {client_name} "
                            f"non invia heartbeat da {minutes_down} minuti. "
                            f"Ultimo contatto: {last_seen_raw}. "
                            f"Failover Redfish diretto attivo per eventuali iLO con URL esterna configurata."
                        ),
                        "status": "active",
                        "raw_data": "",
                        "acknowledged_by": None,
                        "acknowledged_at": None,
                        "resolved_at": None,
                        "created_at": now.isoformat(),
                    }
                    await self.db.alerts.insert_one(alert_doc)
                    try:
                        import webpush as _wp
                        await _wp.notify_new_alert(self.db, alert_doc)
                    except Exception:
                        pass
                    # Mark connector as offline in its status doc (so UI shows it too)
                    await self.db.connector_status.update_one(
                        {"client_id": client_id},
                        {"$set": {"is_offline": True, "offline_since": last_seen_raw}}
                    )
                    logger.warning(
                        f"Connector offline alert raised: {hostname} (client={client_name}, down {minutes_down}min)"
                    )
                    # Send notification if service is wired
                    if self.notification_service:
                        try:
                            from notifications import NotificationChannel, NotificationPriority
                            await self.notification_service.send_notification(
                                channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
                                title=alert_doc["title"],
                                message=alert_doc["message"],
                                priority=NotificationPriority.CRITICAL,
                                alert_id=alert_doc["id"],
                            )
                        except Exception as e:
                            logger.warning(f"Notification send failed: {e}")
                else:
                    # Connector is healthy now — auto-resolve any active offline alert
                    if existing_alert and elapsed < RECOVERY_GRACE_SECONDS:
                        await self.db.alerts.update_one(
                            {"id": existing_alert["id"]},
                            {"$set": {
                                "status": "resolved",
                                "resolved_at": now.isoformat(),
                            }}
                        )
                        # Create a low-severity recovery notice
                        await self.db.alerts.insert_one({
                            "id": str(uuid.uuid4()),
                            "client_id": client_id,
                            "device_id": "",
                            "device_ip": "",
                            "device_name": hostname,
                            "device_type": "connector",
                            "severity": "low",
                            "source_type": "connector_recovery",
                            "title": f"Connettore ONLINE (ripristinato): {hostname}",
                            "message": f"Il connettore '{hostname}' del cliente {client_name} ha ripreso a inviare heartbeat.",
                            "status": "active",
                            "raw_data": "",
                            "acknowledged_by": None,
                            "acknowledged_at": None,
                            "resolved_at": None,
                            "created_at": now.isoformat(),
                        })
                        await self.db.connector_status.update_one(
                            {"client_id": client_id},
                            {"$set": {"is_offline": False, "offline_since": None}}
                        )
                        logger.info(f"Connector recovery: {hostname} (client={client_name})")
        except Exception as e:
            logger.error(f"Connector watchdog error: {e}", exc_info=True)
