"""Connector watchdog — detects connectors that stopped sending heartbeats and generates alerts."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from alert_filter import insert_alert_if_emit

logger = logging.getLogger("connector_watchdog")

# A connector is considered offline if no heartbeat for this many seconds.
OFFLINE_THRESHOLD_SECONDS = 180  # 3 minutes (heartbeat happens every ~60s)
RECOVERY_GRACE_SECONDS = 60       # After recovery, wait this long before closing the alert


def _parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


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
        self.scheduler.add_job(
            self.check_all_agents,
            IntervalTrigger(seconds=interval_seconds),
            id="agent_watchdog",
            name="Agent v4 heartbeat watchdog",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),
        )
        self.scheduler.start()
        logger.info(f"Connector + Agent watchdog started (check every {interval_seconds}s)")

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
                    await insert_alert_if_emit(self.db, alert_doc)
                    try:
                        import webpush as _wp
                        await _wp.notify_new_alert(self.db, alert_doc)
                    except Exception:
                        pass
                    # Telegram ISTANTANEO: connettore offline = perdita totale
                    # visibilità sito. "OFFLINE" è già keyword instant (bypassa quiet hours).
                    try:
                        from alert_engine import notify_alert_telegram
                        alert_doc["instant"] = True
                        await notify_alert_telegram(self.db, alert_doc)
                    except Exception as _te:
                        logger.debug(f"connector telegram dispatch failed: {_te}")
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
                        # Recovery = evento POSITIVO: salvato come 'resolved'
                        # (storico), mai come alert attivo (no rumore appeso).
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
                            "status": "resolved",
                            "raw_data": "",
                            "acknowledged_by": None,
                            "acknowledged_at": None,
                            "resolved_at": now.isoformat(),
                            "created_at": now.isoformat(),
                        })
                        await self.db.connector_status.update_one(
                            {"client_id": client_id},
                            {"$set": {"is_offline": False, "offline_since": None}}
                        )
                        # Rientro su Telegram (1 solo msg) se l'offline era stato notificato
                        if existing_alert.get("telegram_notified"):
                            try:
                                from alert_engine import notify_recovery_telegram
                                await notify_recovery_telegram(self.db, existing_alert)
                            except Exception as _re:
                                logger.debug(f"connector recovery telegram failed: {_re}")
                        logger.info(f"Connector recovery: {hostname} (client={client_name})")
        except Exception as e:
            logger.error(f"Connector watchdog error: {e}", exc_info=True)


    async def check_all_agents(self):
        """Watchdog Agent v4 (collection managed_agents). Se un cliente resta senza
        alcun agent con heartbeat fresco (> OFFLINE_THRESHOLD_SECONDS) genera UN
        SOLO alert critico 'AGENT OFFLINE'. Copre il caso STALE (agent_offline)
        che il watchdog connector_status legacy NON intercetta (gli agent v4 non
        scrivono su connector_status). Auto-resolve al ripristino heartbeat."""
        try:
            now = datetime.now(timezone.utc)
            threshold = now - timedelta(seconds=OFFLINE_THRESHOLD_SECONDS)
            agents = await self.db.managed_agents.find(
                {}, {"_id": 0, "client_id": 1, "hostname": 1, "role": 1,
                     "last_heartbeat_at": 1, "uninstall_status": 1},
            ).to_list(5000)

            by_client: dict = {}
            for a in agents:
                cid = a.get("client_id")
                if not cid:
                    continue
                # Escludi agent disinstallati → non devono generare falsi 'offline'
                if a.get("uninstall_status") == "completed":
                    continue
                by_client.setdefault(cid, []).append(a)

            clients = await self.db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
            client_names = {c.get("id"): c.get("name") for c in clients}

            for cid, alist in by_client.items():
                hbs = [(_parse_dt(a.get("last_heartbeat_at")), a) for a in alist]
                hbs = [(dt, a) for dt, a in hbs if dt]
                if not hbs:
                    continue  # mai visto heartbeat → stato incerto, non allarmiamo
                latest_dt, latest_agent = max(hbs, key=lambda x: x[0])
                is_offline = latest_dt < threshold
                elapsed = (now - latest_dt).total_seconds()
                cname = client_names.get(cid, cid[:8])
                host = latest_agent.get("hostname") or "agent"

                existing = await self.db.alerts.find_one({
                    "client_id": cid, "source_type": "agent_watchdog", "status": "active",
                })

                if is_offline:
                    if existing:
                        continue
                    minutes_down = int(elapsed / 60)
                    n_agents = len(alist)
                    alert_doc = {
                        "id": str(uuid.uuid4()),
                        "client_id": cid,
                        "device_id": "",
                        "device_ip": "",
                        "device_name": host,
                        "device_type": "agent",
                        "severity": "critical",
                        "source_type": "agent_watchdog",
                        "title": f"AGENT OFFLINE: {cname}",
                        "message": (
                            f"Nessun Agent v4 del cliente {cname} invia heartbeat da "
                            f"{minutes_down} minuti ({n_agents} agent monitorati, ultimo host: {host}). "
                            f"I dispositivi risultano STALE: il monitoraggio LAN è fermo. "
                            f"Riavviare il servizio 86NocAgent sul sito."
                        ),
                        "status": "active",
                        "raw_data": "",
                        "acknowledged_by": None,
                        "acknowledged_at": None,
                        "resolved_at": None,
                        "created_at": now.isoformat(),
                    }
                    await insert_alert_if_emit(self.db, alert_doc)
                    try:
                        import webpush as _wp
                        await _wp.notify_new_alert(self.db, alert_doc)
                    except Exception:
                        pass
                    try:
                        from alert_engine import notify_alert_telegram
                        alert_doc["instant"] = True
                        await notify_alert_telegram(self.db, alert_doc)
                    except Exception as _te:
                        logger.debug(f"agent telegram dispatch failed: {_te}")
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
                            logger.warning(f"Agent notification send failed: {e}")
                    logger.warning(
                        f"Agent offline alert raised: client={cname} down {minutes_down}min"
                    )
                else:
                    if existing and elapsed < RECOVERY_GRACE_SECONDS:
                        await self.db.alerts.update_one(
                            {"id": existing["id"]},
                            {"$set": {"status": "resolved", "resolved_at": now.isoformat()}},
                        )
                        await self.db.alerts.insert_one({
                            "id": str(uuid.uuid4()),
                            "client_id": cid,
                            "device_id": "",
                            "device_ip": "",
                            "device_name": host,
                            "device_type": "agent",
                            "severity": "low",
                            "source_type": "agent_recovery",
                            "title": f"Agent ONLINE (ripristinato): {cname}",
                            "message": f"Gli Agent v4 del cliente {cname} hanno ripreso a inviare heartbeat.",
                            "status": "resolved",
                            "raw_data": "",
                            "acknowledged_by": None,
                            "acknowledged_at": None,
                            "resolved_at": now.isoformat(),
                            "created_at": now.isoformat(),
                        })
                        if existing.get("telegram_notified"):
                            try:
                                from alert_engine import notify_recovery_telegram
                                await notify_recovery_telegram(self.db, existing)
                            except Exception as _re:
                                logger.debug(f"agent recovery telegram failed: {_re}")
                        logger.info(f"Agent recovery: client={cname}")
        except Exception as e:
            logger.error(f"Agent watchdog error: {e}", exc_info=True)
