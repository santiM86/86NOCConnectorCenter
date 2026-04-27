"""
NOC Alert Command Center - Redfish iLO Direct Polling & Failover Service
Polls HPE iLO devices directly from the SOC backend when:
  1) Configured for direct polling (external URL available)
  2) Connector goes offline (automatic failover)
"""
import os
import json
import uuid
import logging
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("redfish")

FAILOVER_THRESHOLD_SECONDS = 120  # 2 minutes without heartbeat = connector offline


class RedfishPoller:
    """
    Direct Redfish poller for HPE iLO devices.
    Supports:
    - Always-on direct polling (when iLO is reachable from backend via NAT/VPN)
    - Automatic failover when the Windows connector goes offline
    - Manual test connection from the SOC dashboard
    """

    def __init__(self, db, notification_service=None):
        self.db = db
        self.notification_service = notification_service
        self.scheduler = AsyncIOScheduler()
        self.security_manager = None

    def set_security_manager(self, sm):
        self.security_manager = sm

    async def start_scheduler(self, interval_minutes: int = 5):
        self.scheduler.add_job(
            self.poll_cycle,
            IntervalTrigger(minutes=interval_minutes),
            id='redfish_poll',
            name='Redfish Polling Job',
            replace_existing=True
        )
        self.scheduler.start()
        logger.info(f"Redfish polling scheduler started (interval: {interval_minutes} minutes)")

    def stop_scheduler(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    # ==================== MAIN POLL CYCLE ====================

    async def poll_cycle(self):
        """Main polling cycle: find devices to poll and poll them."""
        if not self.security_manager:
            return

        # Get all iLO credentials from the vault that have an external_url
        ilo_creds = await self.db.device_credentials.find(
            {"credential_type": "ilo"},
            {"_id": 0}
        ).to_list(500)

        if not ilo_creds:
            return

        # Determine which devices need direct polling.
        # === Enterprise policy (2026-04-21) ===
        # Regola: se external_url e' configurato, ARGUS POLLA SEMPRE DIRETTO.
        # Il connector resta come canale ridondante per eventuali device senza external_url
        # o per SNMP/Syslog. In questo modo, se il connector cade, i dati iLO continuano
        # ad arrivare direttamente dall'URL pubblico (requisito NOC enterprise non negoziabile).
        # Il flag "direct_poll" ora determina solo se FORZARE direct anche senza external_url
        # (caso: iLO esposto solo via connector LAN). Il flag "connector_only" (nuovo, opzionale)
        # permette di disattivare il direct e usare SOLO il connector per quel device.
        devices_to_poll = []
        for cred in ilo_creds:
            external_url = cred.get("external_url")
            direct_poll_forced = cred.get("direct_poll", False)
            connector_only = cred.get("connector_only", False)
            device_ip = cred.get("device_ip")

            if connector_only:
                # Explicit opt-out: solo connector, mai diretto
                continue
            if external_url:
                # external_url presente -> polla diretto SEMPRE (enterprise default)
                devices_to_poll.append({
                    "cred": cred,
                    "reason": "direct" if direct_poll_forced else "direct_default",
                })
            elif direct_poll_forced:
                # Forzato anche senza external_url -> prova con device_ip (LAN raggiungibile?)
                devices_to_poll.append({
                    "cred": cred,
                    "reason": "direct_forced_lan",
                })
            else:
                # Nessun external_url + non forzato -> connector-only (polling lato connector)
                # Ma se il connector e' offline, facciamo failover a... nulla. L'unica speranza
                # e' che l'admin configuri external_url.
                should_failover = await self._should_failover(device_ip)
                if should_failover:
                    logger.warning(f"Redfish {device_ip}: connector offline ma external_url non configurato, polling impossibile")

        if not devices_to_poll:
            return

        logger.info(f"Redfish direct polling: {len(devices_to_poll)} devices")

        for item in devices_to_poll:
            dev_ip = item["cred"].get("device_ip")
            dev_name = item["cred"].get("device_name") or dev_ip
            try:
                await self._poll_device(item["cred"], item["reason"])
                # Success: reset direct failure counter
                await self.db.ilo_channel_health.update_one(
                    {"device_ip": dev_ip},
                    {"$set": {
                        "device_ip": dev_ip,
                        "device_name": dev_name,
                        "client_id": item["cred"].get("client_id"),
                        "direct_last_success": datetime.now(timezone.utc).isoformat(),
                        "direct_consecutive_failures": 0,
                    }},
                    upsert=True
                )
                # Check if we should auto-resolve a "both channels down" alert
                await self._resolve_both_channels_alert(dev_ip)
            except Exception as e:
                logger.error(f"Redfish poll error for {dev_ip}: {e}")
                await self.db.ilo_channel_health.update_one(
                    {"device_ip": dev_ip},
                    {"$set": {
                        "device_ip": dev_ip,
                        "device_name": dev_name,
                        "client_id": item["cred"].get("client_id"),
                        "direct_last_failure": datetime.now(timezone.utc).isoformat(),
                        "direct_last_error": str(e)[:300],
                    }, "$inc": {"direct_consecutive_failures": 1}},
                    upsert=True
                )
                # Check both-channels-down
                await self._check_both_channels_down(item["cred"])

    async def _check_both_channels_down(self, cred: dict) -> None:
        """Crea alert critical se DIRECT poll fallisce >=3 volte consecutive
        E allo stesso tempo il connector e' offline/stale per lo stesso device.
        Thresholds: 3 failures direct (=3 min con poll 1/min) + connector stale >5 min.
        """
        device_ip = cred.get("device_ip")
        device_name = cred.get("device_name") or device_ip
        client_id = cred.get("client_id")

        health = await self.db.ilo_channel_health.find_one({"device_ip": device_ip}, {"_id": 0})
        if not health:
            return
        direct_failures = int(health.get("direct_consecutive_failures") or 0)
        if direct_failures < 3:
            return

        # Check connector-side health: stale > 5 min OR never polled
        stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        dps = await self.db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})
        connector_stale = True
        if dps and dps.get("last_update"):
            connector_stale = str(dps["last_update"]) < stale_cutoff

        if not connector_stale:
            return  # Connector is active, we only have a direct-path issue (not critical yet)

        # Dedup: only raise if no active alert in last 6h
        since = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        existing = await self.db.alerts.find_one({
            "device_ip": device_ip,
            "type": "ilo_both_channels_down",
            "status": "active",
            "created_at": {"$gte": since},
        })
        if existing:
            return

        alert_doc = {
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_ip": device_ip,
            "device_name": device_name,
            "device_type": "ilo",
            "severity": "critical",
            "type": "ilo_both_channels_down",
            "title": f"iLO TOTAL LOSS: {device_name} — nessun canale risponde",
            "message": (
                f"CRITICAL: iLO {device_ip} ({device_name}) non risponde da entrambi i canali. "
                f"Direct poll WAN fallito {direct_failures} volte consecutive (ultimo errore: {health.get('direct_last_error','n/a')[:150]}). "
                f"Connector LAN stale o offline. Possibili cause: management board iLO in down hardware, "
                f"rack network isolation, alimentazione staccata, firewall che blocca sia WAN che LAN. "
                f"Intervento on-site richiesto."
            ),
            "source_type": "redfish_health_monitor",
            "status": "active",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "resolved_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_data": "",
        }
        await self.db.alerts.insert_one(alert_doc)
        # Broadcast + push
        try:
            import webpush as _wp
            await _wp.notify_new_alert(self.db, alert_doc)
        except Exception:
            pass
        logger.critical(f"iLO BOTH CHANNELS DOWN: {device_name} ({device_ip})")

    async def _resolve_both_channels_alert(self, device_ip: str) -> None:
        """Auto-resolve l'alert 'ilo_both_channels_down' quando il direct poll torna a funzionare."""
        res = await self.db.alerts.update_many(
            {"device_ip": device_ip, "type": "ilo_both_channels_down", "status": "active"},
            {"$set": {
                "status": "resolved",
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolved_by": "auto-recovery",
                "resolution_note": "iLO direct channel back online",
            }}
        )
        if res.modified_count > 0:
            logger.info(f"iLO both-channels alert auto-resolved for {device_ip}")

    async def _should_failover(self, device_ip: str) -> bool:
        """Check if the connector responsible for this device is offline."""        # Find which client owns this device
        device = await self.db.device_poll_status.find_one(
            {"device_ip": device_ip},
            {"_id": 0, "client_id": 1}
        )
        if not device:
            # No poll status = never been polled by connector. Check managed_devices
            managed = await self.db.managed_devices.find_one(
                {"ip": device_ip},
                {"_id": 0, "client_id": 1}
            )
            if not managed:
                return True  # No connector assigned, poll directly
            client_id = managed["client_id"]
        else:
            client_id = device.get("client_id")

        if not client_id:
            return True

        # Check connector heartbeat
        connector = await self.db.connector_status.find_one(
            {"client_id": client_id},
            {"_id": 0, "last_seen": 1}
        )
        if not connector or not connector.get("last_seen"):
            return True  # No connector ever connected

        try:
            last_seen = datetime.fromisoformat(connector["last_seen"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
            return elapsed > FAILOVER_THRESHOLD_SECONDS
        except Exception:
            return True

    async def _poll_device(self, cred: dict, reason: str):
        """Poll a single iLO device via Redfish REST API."""
        device_ip = cred.get("device_ip", "")
        external_url = cred.get("external_url", "")
        device_name = cred.get("device_name", device_ip)

        # Decrypt credentials
        try:
            username = self.security_manager.decrypt_credential(cred["username_enc"])
            password = self.security_manager.decrypt_credential(cred["password_enc"])
        except Exception as e:
            logger.error(f"Cannot decrypt credentials for {device_ip}: {e}")
            return

        port = cred.get("port") or 443
        base_url = external_url.rstrip("/") if external_url else f"https://{device_ip}:{port}"

        logger.info(f"Polling {device_name} ({device_ip}) via {base_url} [reason={reason}]")

        result = {
            "redfish_ok": False,
            "power_watts": None,
            "bios_version": None,
            "server_model": None,
            "serial_number": None,
            "uuid": None,
            "ilo_firmware": None,
            "ilo_license": None,
            "total_memory_gb": None,
            "memory_dimms": [],
            "network_adapters": [],
            "storage_controllers": [],
            "health_status": None,
            "temperatures": [],
            "fans": [],
            "power_supplies": [],
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                auth = (username, password)

                # 1. System Info
                sys_data = await self._get(client, f"{base_url}/redfish/v1/Systems/1/", auth)
                if sys_data:
                    result["redfish_ok"] = True
                    result["server_model"] = sys_data.get("Model")
                    result["serial_number"] = sys_data.get("SerialNumber")
                    result["uuid"] = sys_data.get("UUID")
                    result["bios_version"] = sys_data.get("BiosVersion")
                    if sys_data.get("MemorySummary"):
                        result["total_memory_gb"] = sys_data["MemorySummary"].get("TotalSystemMemoryGiB")
                    health = sys_data.get("Status", {}).get("Health", "Unknown")
                    result["health_status"] = health.lower() if health else "unknown"

                # 2. Power (try multiple URIs as HP/HPE changes them across iLO versions)
                power_data = None
                for power_uri in [
                    f"{base_url}/redfish/v1/Chassis/1/Power/",
                    f"{base_url}/redfish/v1/Chassis/1/Power",
                    f"{base_url}/redfish/v1/Chassis/Self/Power/",
                ]:
                    power_data = await self._get(client, power_uri, auth)
                    if power_data:
                        break
                if power_data and power_data.get("PowerControl"):
                    pc_list = power_data.get("PowerControl", [])
                    pc = pc_list[0] if pc_list else {}
                    # HP iLO sometimes uses PowerConsumedWatts, sometimes PowerMetrics.AverageConsumedWatts
                    result["power_watts"] = (
                        pc.get("PowerConsumedWatts")
                        or (pc.get("PowerMetrics") or {}).get("AverageConsumedWatts")
                        or pc.get("PowerRequestedWatts")
                    )
                    # Power supplies
                    for ps in power_data.get("PowerSupplies", []):
                        result["power_supplies"].append({
                            "name": ps.get("Name") or ps.get("Model") or "PSU",
                            "condition": (ps.get("Status", {}).get("Health") or "Unknown").lower(),
                            "state": (ps.get("Status", {}).get("State") or "Unknown"),
                            "watts": ps.get("PowerCapacityWatts") or ps.get("PowerOutputWatts"),
                            "model": ps.get("Model"),
                            "firmware": ps.get("FirmwareVersion"),
                            "serial": ps.get("SerialNumber"),
                        })
                else:
                    logger.warning(f"Redfish {device_ip}: PowerControl not found at any URI")

                # 3. Thermal (multi-URI fallback: Thermal legacy + ThermalSubsystem Redfish 2020.4+)
                # Retry up to 2 volte per device con WAN instabile (sintomo: temp/fan N/D intermittente)
                thermal = None
                for _attempt in range(2):
                    try:
                        thermal = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/Thermal/", auth, timeout=20.0)
                        if thermal and (thermal.get("Temperatures") or thermal.get("Fans")):
                            break
                    except Exception as _te:
                        logger.debug(f"Thermal fetch attempt {_attempt+1} failed for {device_ip}: {_te}")
                    if _attempt == 0:
                        import asyncio as _a
                        await _a.sleep(1.0)
                # ML350 Gen10 + iLO5 3.x moderno: /ThermalSubsystem/ con sotto-endpoint separati
                if not thermal or (not thermal.get("Temperatures") and not thermal.get("Fans")):
                    ts = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/ThermalSubsystem/", auth)
                    if ts:
                        merged = {"Temperatures": [], "Fans": []}
                        # Fans collection
                        fans_col = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/ThermalSubsystem/Fans/", auth)
                        if fans_col and fans_col.get("Members"):
                            for ref in fans_col["Members"][:20]:
                                f = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                                if f:
                                    # Normalize ThermalSubsystem.Fans (new schema) to legacy shape
                                    reading_pct = None
                                    if isinstance(f.get("SpeedPercent"), dict):
                                        reading_pct = f["SpeedPercent"].get("Reading")
                                    elif isinstance(f.get("Reading"), (int, float)):
                                        reading_pct = f.get("Reading")
                                    merged["Fans"].append({
                                        "Name": f.get("Name", "Fan"),
                                        "Reading": reading_pct,
                                        "Status": f.get("Status", {}),
                                    })
                        # Temperature sensors: ThermalSubsystem esposto come /Sensors/
                        sensors_col = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/Sensors/", auth)
                        if sensors_col and sensors_col.get("Members"):
                            for ref in sensors_col["Members"][:80]:
                                s = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                                if not s:
                                    continue
                                rtype = (s.get("ReadingType") or "").lower()
                                if rtype == "temperature":
                                    merged["Temperatures"].append({
                                        "Name": s.get("Name", "Sensor"),
                                        "ReadingCelsius": s.get("Reading"),
                                        "Status": s.get("Status", {}),
                                    })
                        thermal = merged
                        logger.info(f"Redfish {device_ip}: ThermalSubsystem fallback found {len(merged['Temperatures'])} temp, {len(merged['Fans'])} fans")
                if thermal:
                    for t in thermal.get("Temperatures", []):
                        # iLO omette sensori "absent" con ReadingCelsius=null. Skippiamo SOLO null/missing.
                        reading = t.get("ReadingCelsius")
                        if reading is None:
                            reading = t.get("CurrentReading")  # fallback iLO4
                        if reading is None:
                            continue
                        # State "Absent" -> skip. Ma "Enabled" con reading 0 e' valido (es. DIMM idle).
                        state = (t.get("Status", {}).get("State") or "Enabled")
                        if state.lower() in ("absent", "disabled"):
                            continue
                        result["temperatures"].append({
                            "locale": t.get("Name", "Sensor"),
                            "value": reading,
                            "condition": (t.get("Status", {}).get("Health") or "OK").lower(),
                        })
                    for f in thermal.get("Fans", []):
                        state = (f.get("Status", {}).get("State") or "Enabled")
                        if state.lower() in ("absent", "disabled"):
                            continue
                        speed = f.get("Reading")
                        if speed is None:
                            speed = f.get("CurrentReading")
                        result["fans"].append({
                            "locale": f.get("Name", "Fan"),
                            "speed": speed,
                            "condition": (f.get("Status", {}).get("Health") or "OK").lower(),
                        })
                    logger.info(f"Redfish {device_ip}: Thermal found {len(result['temperatures'])} temp, {len(result['fans'])} fans")
                else:
                    logger.warning(f"Redfish {device_ip}: /Chassis/1/Thermal/ returned None")

                # 4. iLO Manager info (try multiple URIs)
                mgr = None
                for mgr_uri in [
                    f"{base_url}/redfish/v1/Managers/1/",
                    f"{base_url}/redfish/v1/Managers/1",
                    f"{base_url}/redfish/v1/Managers/Self/",
                ]:
                    mgr = await self._get(client, mgr_uri, auth)
                    if mgr:
                        break
                if mgr:
                    result["ilo_firmware"] = (
                        mgr.get("FirmwareVersion")
                        or mgr.get("firmwareVersion")
                        or (mgr.get("Oem", {}).get("Hpe") or mgr.get("Oem", {}).get("Hp") or {}).get("FirmwareVersion")
                    )
                    oem = mgr.get("Oem", {})
                    hpe = oem.get("Hpe") or oem.get("Hp") or {}
                    lic = hpe.get("License", {}) or {}
                    result["ilo_license"] = lic.get("LicenseString") or lic.get("LicenseType") or lic.get("Name")
                else:
                    logger.warning(f"Redfish {device_ip}: Manager info not found")

                # 5. Memory DIMMs
                mem_col = await self._get(client, f"{base_url}/redfish/v1/Systems/1/Memory/", auth)
                if mem_col and mem_col.get("Members"):
                    for ref in mem_col["Members"][:32]:
                        dimm = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if dimm and dimm.get("Status", {}).get("State") == "Enabled":
                            result["memory_dimms"].append({
                                "name": dimm.get("DeviceLocator", "DIMM"),
                                "size_gb": round(dimm.get("CapacityMiB", 0) / 1024, 1),
                                "speed_mhz": dimm.get("OperatingSpeedMhz"),
                                "type": dimm.get("MemoryDeviceType"),
                                "status": dimm.get("Status", {}).get("Health", "OK"),
                            })

                # 6. Network Adapters — due fonti:
                #    a) /Systems/1/EthernetInterfaces/ (livello OS, mostra IP/MAC ma spesso non LinkStatus su ML350)
                #    b) /Chassis/1/NetworkAdapters/.../Ports/ (livello hardware, mostra LinkStatus reale)
                # Aggreghiamo entrambi usando MAC come chiave (fallback indice).
                hw_ports_by_mac = {}
                try:
                    chassis_nics = await self._get(client, f"{base_url}/redfish/v1/Chassis/1/NetworkAdapters/", auth)
                    if chassis_nics and chassis_nics.get("Members"):
                        for adr_ref in chassis_nics["Members"][:10]:
                            adp = await self._get(client, f"{base_url}{adr_ref['@odata.id']}", auth)
                            if not adp:
                                continue
                            ports_ref = (adp.get("NetworkPorts") or adp.get("Ports") or {}).get("@odata.id")
                            if not ports_ref:
                                continue
                            ports_col = await self._get(client, f"{base_url}{ports_ref}", auth)
                            if not ports_col or not ports_col.get("Members"):
                                continue
                            for p_ref in ports_col["Members"][:10]:
                                p = await self._get(client, f"{base_url}{p_ref['@odata.id']}", auth)
                                if not p:
                                    continue
                                # LinkStatus viene esposto in modi diversi a seconda dello schema
                                l = (p.get("LinkStatus") or p.get("linkStatus") or
                                     (p.get("Status", {}).get("State") if p.get("Status") else None))
                                # MAC key
                                macs = []
                                for m_field in ("AssociatedNetworkAddresses", "NetAddressMediaMAC", "NetworkAddresses"):
                                    v = p.get(m_field)
                                    if isinstance(v, list):
                                        macs.extend([m.upper() for m in v if isinstance(m, str)])
                                    elif isinstance(v, str):
                                        macs.append(v.upper())
                                for mac_k in macs:
                                    if mac_k:
                                        hw_ports_by_mac[mac_k] = {"link_status": l, "health": (p.get("Status", {}) or {}).get("Health")}
                except Exception as e:
                    logger.debug(f"Redfish {device_ip}: NetworkAdapters fallback skipped: {e}")

                nics = await self._get(client, f"{base_url}/redfish/v1/Systems/1/EthernetInterfaces/", auth)
                if nics and nics.get("Members"):
                    for ref in nics["Members"][:16]:
                        nic = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if nic:
                            # LinkStatus: "LinkUp"/"LinkDown"/"NoLink"
                            link_status = nic.get("LinkStatus") or nic.get("linkStatus") or (nic.get("Oem", {}).get("Hpe", {}) or {}).get("LinkStatus")
                            state = (nic.get("Status", {}).get("State") or "Unknown")
                            health = (nic.get("Status", {}).get("Health") or "N/A")
                            mac_key = (nic.get("MACAddress") or "").upper()
                            # Fallback su hardware port data se disponibile
                            if (not link_status or link_status.lower() == "unknown") and mac_key in hw_ports_by_mac:
                                hw = hw_ports_by_mac[mac_key]
                                link_status = hw.get("link_status") or link_status
                                if hw.get("health") and health == "N/A":
                                    health = hw["health"]
                            # Se stato NIC e' Enabled + LinkStatus LinkUp -> health = OK
                            if health in ("N/A", "?", None) and state == "Enabled" and str(link_status).lower() in ("linkup", "up"):
                                health = "OK"
                            result["network_adapters"].append({
                                "name": nic.get("Name", "NIC"),
                                "mac": nic.get("MACAddress"),
                                "speed_mbps": nic.get("SpeedMbps"),
                                "status": health,
                                "state": state,
                                "link_status": link_status or "unknown",
                                "ipv4": (nic.get("IPv4Addresses", [{}])[0].get("Address") if nic.get("IPv4Addresses") else None),
                                "fqdn": nic.get("FQDN"),
                            })

                # 7. Storage (SmartStorage + Storage DMTF + physical drives)
                # Try multiple URI patterns — iLO 4/5/6 differ:
                # - iLO 4 Gen9: /Systems/1/SmartStorage/ArrayControllers/
                # - iLO 5 Gen10+: /Systems/1/Storage/ (DMTF) OR /Systems/1/SmartStorage/
                # - iLO 6 Gen11: /Systems/1/Storage/
                storage_uris = [
                    f"{base_url}/redfish/v1/Systems/1/SmartStorage/ArrayControllers/",
                    f"{base_url}/redfish/v1/Systems/1/Storage/",
                    f"{base_url}/redfish/v1/Systems/1/Storage",           # no trailing slash
                    f"{base_url}/redfish/v1/Chassis/1/Storage/",
                    f"{base_url}/redfish/v1/Systems/1/SmartStorage/",     # wrapper index
                ]
                storage_found_any = False
                for st_uri in storage_uris:
                    if storage_found_any and len(result["storage_controllers"]) >= 2:
                        # Already got good data from previous URI, skip redundant ones
                        break
                    storage = await self._get(client, st_uri, auth)
                    if not (storage and storage.get("Members")):
                        continue
                    for ref in storage["Members"][:8]:
                        ctrl = await self._get(client, f"{base_url}{ref['@odata.id']}", auth)
                        if not ctrl:
                            continue
                        # For SmartStorage index ("/SmartStorage/") follow ArrayControllers link
                        if "ArrayControllers" in (ctrl.get("Links") or {}):
                            arr_uri = ctrl["Links"]["ArrayControllers"].get("@odata.id")
                            if arr_uri:
                                arr_coll = await self._get(client, f"{base_url}{arr_uri}", auth)
                                if arr_coll and arr_coll.get("Members"):
                                    for arr_ref in arr_coll["Members"][:8]:
                                        arr_ctrl = await self._get(client, f"{base_url}{arr_ref['@odata.id']}", auth)
                                        if arr_ctrl:
                                            ctrl = arr_ctrl
                                            ref = arr_ref
                                            break
                        ctrl_info = {
                            "name": ctrl.get("Model") or ctrl.get("Name") or "Controller",
                            "firmware": (ctrl.get("FirmwareVersion") or {}).get("Current", {}).get("VersionString") if isinstance(ctrl.get("FirmwareVersion"), dict) else ctrl.get("FirmwareVersion"),
                            "status": (ctrl.get("Status", {}).get("Health") or "OK"),
                            "health": (ctrl.get("Status", {}).get("Health") or "OK").lower(),
                            "logical_drives": [],
                            "drives": [],
                        }
                        # Logical drives (HP SmartStorage + DMTF Volumes)
                        for ld_sub in ["LogicalDrives/", "Volumes/"]:
                            ld_path = ref['@odata.id'].rstrip('/') + '/' + ld_sub
                            lds = await self._get(client, f"{base_url}{ld_path}", auth)
                            if lds and lds.get("Members"):
                                for ldref in lds["Members"]:
                                    ld = await self._get(client, f"{base_url}{ldref['@odata.id']}", auth)
                                    if ld:
                                        cap_mib = ld.get("CapacityMiB")
                                        cap_bytes = ld.get("CapacityBytes")
                                        cap_gb = round(cap_mib / 1024, 1) if cap_mib else (round(cap_bytes / (1024**3), 1) if cap_bytes else None)
                                        ctrl_info["logical_drives"].append({
                                            "name": ld.get("LogicalDriveName") or ld.get("Name") or "LUN",
                                            "capacity_gb": cap_gb,
                                            "raid": ld.get("Raid") or ld.get("RAIDType"),
                                            "status": (ld.get("Status", {}).get("Health") or "OK"),
                                        })
                        # Physical drives (HP DiskDrives + DMTF Drives)
                        # Also honor controller-level Drives[] reference array
                        drive_refs = []
                        for dr_sub in ["DiskDrives/", "Drives/"]:
                            dr_path = ref['@odata.id'].rstrip('/') + '/' + dr_sub
                            drives = await self._get(client, f"{base_url}{dr_path}", auth)
                            if drives and drives.get("Members"):
                                drive_refs.extend(drives["Members"])
                        # DMTF: controller may have Drives[] inline
                        for dr_inline in (ctrl.get("Drives") or []):
                            if isinstance(dr_inline, dict) and "@odata.id" in dr_inline:
                                drive_refs.append(dr_inline)
                        # Dedupe by @odata.id
                        seen_ids = set()
                        unique_refs = []
                        for dref in drive_refs:
                            did = dref.get("@odata.id")
                            if did and did not in seen_ids:
                                seen_ids.add(did)
                                unique_refs.append(dref)
                        for drref in unique_refs[:32]:
                            dr = await self._get(client, f"{base_url}{drref['@odata.id']}", auth)
                            if not dr:
                                continue
                            cap_gb = dr.get("CapacityGB") or (round(dr.get("CapacityBytes", 0) / (1024**3), 1) if dr.get("CapacityBytes") else None) or (round(dr.get("CapacityMiB", 0) / 1024, 1) if dr.get("CapacityMiB") else None)
                            ctrl_info["drives"].append({
                                "slot": dr.get("Location") or dr.get("PhysicalLocation", {}).get("PartLocation", {}).get("LocationOrdinalValue") or dr.get("Id"),
                                "model": dr.get("Model"),
                                "serial": dr.get("SerialNumber"),
                                "capacity_gb": cap_gb,
                                "media_type": dr.get("MediaType"),
                                "interface_type": dr.get("InterfaceType") or dr.get("Protocol"),
                                "health": (dr.get("Status", {}).get("Health") or "ok").lower(),
                                "state": dr.get("Status", {}).get("State"),
                                "failure_predicted": dr.get("FailurePredicted", False),
                                "rotation_rpm": dr.get("RotationSpeedRPM"),
                                "hours_used": dr.get("PowerOnHours") or (dr.get("Oem", {}).get("Hpe", {}) or {}).get("PowerOnHours"),
                                "temp_celsius": (dr.get("Oem", {}).get("Hpe", {}) or {}).get("CurrentTemperatureCelsius") or dr.get("Temperature"),
                            })
                        # Only append if we actually got at least 1 drive or logical_drive
                        # (avoid empty controller shells that happen on timeouts mid-request)
                        if ctrl_info["drives"] or ctrl_info["logical_drives"] or ctrl_info["name"] != "Controller":
                            result["storage_controllers"].append(ctrl_info)
                            storage_found_any = True

        except httpx.TimeoutException:
            logger.warning(f"Timeout polling {device_ip}")
        except httpx.ConnectError:
            logger.warning(f"Connection refused for {device_ip}")
        except Exception as e:
            logger.error(f"Unexpected error polling {device_ip}: {e}")

        # Save results to device_poll_status (same as connector does)
        now_iso = datetime.now(timezone.utc).isoformat()
        if result["redfish_ok"]:
            # Stale-fallback pre-persistence: se Thermal sub-endpoint ha fallito (temperatures/fans vuoti)
            # MA il poll principale e' andato a buon fine (power_watts presente), riusa l'ultimo snapshot
            # valido per evitare UI N/D intermittente su WAN instabile.
            if (not result.get("temperatures") or not result.get("fans")) and result.get("power_watts") is not None:
                try:
                    last = await self.db.ilo_telemetry.find_one(
                        {"device_ip": device_ip, "$or": [{"temperatures.0": {"$exists": True}}, {"fans.0": {"$exists": True}}]},
                        {"_id": 0, "temperatures": 1, "fans": 1, "timestamp": 1},
                        sort=[("timestamp", -1)]
                    )
                    if last:
                        last_ts = last.get("timestamp")
                        age_min = 999
                        if isinstance(last_ts, datetime):
                            if last_ts.tzinfo is None:
                                last_ts = last_ts.replace(tzinfo=timezone.utc)
                            age_min = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0
                        if age_min < 30:
                            if not result.get("temperatures") and last.get("temperatures"):
                                result["temperatures"] = [
                                    {"locale": t.get("name"), "value": t.get("celsius"), "condition": t.get("health") or "OK", "stale": True}
                                    for t in last["temperatures"] if t.get("celsius") is not None
                                ]
                                logger.info(f"Redfish {device_ip}: Thermal stale-fallback applied ({len(result['temperatures'])} sensors, age {age_min:.1f}min)")
                            if not result.get("fans") and last.get("fans"):
                                result["fans"] = [
                                    {"locale": f.get("name"), "speed": f.get("rpm_percent"), "condition": f.get("health") or "OK", "stale": True}
                                    for f in last["fans"] if f.get("rpm_percent") is not None
                                ]
                                logger.info(f"Redfish {device_ip}: Fans stale-fallback applied ({len(result['fans'])} fans, age {age_min:.1f}min)")
                except Exception as _fbe:
                    logger.debug(f"stale-fallback error for {device_ip}: {_fbe}")

            update_doc = {
                "device_ip": device_ip,
                "device_name": device_name,
                "reachable": True,
                "monitor_type": "redfish_direct",
                "polling_source": reason,
                "device_class": "hpe-ilo",
                "redfish": {
                    "power_watts": result["power_watts"],
                    "bios_version": result["bios_version"],
                    "server_model": result["server_model"],
                    "serial_number": result["serial_number"],
                    "uuid": result["uuid"],
                    "ilo_firmware": result["ilo_firmware"],
                    "ilo_license": result["ilo_license"],
                    "total_memory_gb": result["total_memory_gb"],
                    "memory_dimms": result["memory_dimms"],
                    "network_adapters": result["network_adapters"],
                    "storage_controllers": result["storage_controllers"],
                },
                "hardware": {
                    "health_status": result["health_status"],
                    "temperatures": result["temperatures"],
                    "fans": result["fans"],
                    "power_supplies": result["power_supplies"],
                },
                "last_poll": now_iso,
                "updated_at": now_iso,
            }

            # Find client_id for this device (3-layer lookup + smart fallback)
            # 1) Prefer client_id from the vault credential (most reliable for new devices)
            # 2) Fallback to existing device_poll_status client_id
            # 3) Fallback to managed_devices client_id
            # 4) Fallback to discovered_endpoints (LLDP/MAC table from any connector)
            # 5) Last resort: if only one client exists in the system, use that one
            client_id_to_set = cred.get("client_id")
            if not client_id_to_set:
                existing = await self.db.device_poll_status.find_one(
                    {"device_ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if existing and existing.get("client_id"):
                    client_id_to_set = existing["client_id"]
            if not client_id_to_set:
                md = await self.db.managed_devices.find_one(
                    {"ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if md and md.get("client_id"):
                    client_id_to_set = md["client_id"]
            if not client_id_to_set:
                # Look in discovered endpoints (LLDP/MAC table from any connector's topology)
                ep = await self.db.discovered_endpoints.find_one(
                    {"ip": device_ip}, {"_id": 0, "client_id": 1}
                )
                if ep and ep.get("client_id"):
                    client_id_to_set = ep["client_id"]
            if not client_id_to_set:
                # Last resort: single-client installation -> auto-assign
                all_clients = await self.db.clients.find({}, {"_id": 0, "id": 1}).to_list(10)
                if len(all_clients) == 1:
                    client_id_to_set = all_clients[0]["id"]
                    logger.info(f"Redfish {device_ip}: auto-assigned to single client {client_id_to_set}")
            if client_id_to_set:
                update_doc["client_id"] = client_id_to_set
                update_doc["device_type"] = "ilo"
                # Auto-heal: also update the Vault credential so next polls don't need fallback logic
                if not cred.get("client_id"):
                    try:
                        await self.db.device_credentials.update_one(
                            {"device_ip": device_ip, "credential_type": "ilo"},
                            {"$set": {"client_id": client_id_to_set}}
                        )
                        logger.info(f"Vault cred for {device_ip} auto-assigned to client {client_id_to_set}")
                    except Exception as e:
                        logger.warning(f"Vault cred auto-heal failed: {e}")
            else:
                logger.warning(f"Redfish {device_ip}: could not determine client_id — alerts will be orphan")

            # === STALE-BUT-GOOD fallback for storage/memory/network ===
            # Redfish endpoints /Storage /Memory /EthernetInterfaces sometimes timeout
            # or return empty payloads intermittently (especially iLO 5 Gen10 under load).
            # Never overwrite last-good data with empty — keep stale with a flag.
            prev = await self.db.device_poll_status.find_one(
                {"device_ip": device_ip},
                {"_id": 0, "redfish": 1, "hardware": 1}
            ) or {}
            prev_rf = (prev.get("redfish") or {})

            def _keep_if_empty(new_list, prev_list, label):
                """Return new_list if not empty; else return prev_list with stale flag."""
                if new_list and len(new_list) > 0:
                    return new_list
                if prev_list and len(prev_list) > 0:
                    # Mark each item as stale
                    stale_list = []
                    for item in prev_list:
                        item_copy = dict(item)
                        item_copy["stale"] = True
                        stale_list.append(item_copy)
                    logger.info(f"Redfish {device_ip}: {label} empty, keeping {len(stale_list)} stale items")
                    return stale_list
                return new_list  # both empty → really no data

            update_doc["redfish"]["storage_controllers"] = _keep_if_empty(
                result["storage_controllers"], prev_rf.get("storage_controllers") or [], "storage"
            )
            update_doc["redfish"]["memory_dimms"] = _keep_if_empty(
                result["memory_dimms"], prev_rf.get("memory_dimms") or [], "memory"
            )
            update_doc["redfish"]["network_adapters"] = _keep_if_empty(
                result["network_adapters"], prev_rf.get("network_adapters") or [], "network"
            )

            # Track when each subsystem was last fully fresh (so UI can show "fresh vs N min ago")
            if result["storage_controllers"]:
                update_doc["redfish"]["storage_last_good_at"] = now_iso
            if result["memory_dimms"]:
                update_doc["redfish"]["memory_last_good_at"] = now_iso
            if result["network_adapters"]:
                update_doc["redfish"]["network_last_good_at"] = now_iso

            await self.db.device_poll_status.update_one(
                {"device_ip": device_ip},
                {"$set": update_doc},
                upsert=True
            )

            # Historical metrics (compact, per backward compat con charts esistenti)
            main_temp = result["temperatures"][0]["value"] if result["temperatures"] else None
            await self.db.device_metrics_history.insert_one({
                "client_id": client_id_to_set,
                "device_ip": device_ip,
                "timestamp": now_iso,
                "power_watts": result["power_watts"],
                "temperature": main_temp,
            })

            # NEW: Full telemetry snapshot per grafici real-time enterprise.
            # Storage completo di temperature[], fans[], power_supplies[], health,
            # per permettere grafici multi-sensore in frontend (sparklines).
            # Nota: stale-fallback gia' applicato a result sopra.
            try:
                now_dt = datetime.now(timezone.utc)
                temp_src = result.get("temperatures") or []
                fan_src = result.get("fans") or []
                any_stale = any(t.get("stale") for t in temp_src) or any(f.get("stale") for f in fan_src)
                telemetry_doc = {
                    "client_id": client_id_to_set,
                    "device_ip": device_ip,
                    "device_name": device_name,
                    "source": "REDFISH_DIRECT" if reason == "direct" else "REDFISH_FAILOVER",
                    "timestamp": now_dt,
                    "power_watts": result.get("power_watts"),
                    "health_status": result.get("health_status"),
                    "temperatures": [
                        {"name": t.get("locale"), "celsius": t.get("value"), "health": t.get("condition"), "stale": bool(t.get("stale"))}
                        for t in temp_src if t.get("value") is not None
                    ],
                    "fans": [
                        {"name": f.get("locale"), "rpm_percent": f.get("speed"), "health": f.get("condition"), "stale": bool(f.get("stale"))}
                        for f in fan_src if f.get("speed") is not None
                    ],
                    "power_supplies": result.get("power_supplies") or [],
                    "thermal_fetch_failed": any_stale,
                }
                await self.db.ilo_telemetry.insert_one(telemetry_doc)
            except Exception as _e:
                logger.warning(f"ilo_telemetry insert failed for {device_ip}: {_e}")

            # Generate alerts for critical conditions
            await self._check_alerts(device_ip, device_name, result, client_id_to_set)

            # Firmware compliance check (iLO + BIOS vs catalog)
            try:
                from routes.firmware_catalog import check_firmware_compliance
                fc = await check_firmware_compliance(
                    result.get("server_model"),
                    result.get("ilo_firmware"),
                    result.get("bios_version"),
                )
                # Store compliance summary on device_poll_status for frontend badge
                await self.db.device_poll_status.update_one(
                    {"device_ip": device_ip},
                    {"$set": {"firmware_compliance": fc}}
                )
                # Upsert patch_status row for Patch Compliance dashboard integration
                critical_count = sum(1 for c in (fc.get("components") or []) if c.get("status") == "critical_outdated")
                outdated_count = sum(1 for c in (fc.get("components") or []) if c.get("status") in ("outdated", "critical_outdated"))
                all_cves = []
                for c in (fc.get("components") or []):
                    all_cves.extend(c.get("cve_list") or [])
                await self.db.patch_status.update_one(
                    {"device_ip": device_ip},
                    {"$set": {
                        "device_ip": device_ip,
                        "client_id": client_id_to_set,
                        "os_name": result.get("server_model"),
                        "firmware_version": f"iLO {result.get('ilo_firmware')} / BIOS {result.get('bios_version')}",
                        "pending_patches": outdated_count,
                        "critical_patches": critical_count,
                        "cve_count": len(all_cves),
                        "cve_list": all_cves[:50],
                        "last_check_at": now_iso,
                        "source": "redfish_firmware_compliance",
                    }, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now_iso}},
                    upsert=True
                )
                # If critical, create a specific alert (dedupe via fingerprint)
                if fc.get("overall_status") == "critical":
                    from datetime import timedelta as _td
                    since = (datetime.now(timezone.utc) - _td(hours=6)).isoformat()
                    existing = await self.db.alerts.find_one({
                        "device_ip": device_ip,
                        "type": "firmware_critical_outdated",
                        "created_at": {"$gte": since},
                    })
                    if not existing:
                        alert_doc = {
                            "id": str(uuid.uuid4()),
                            "client_id": client_id_to_set,
                            "device_ip": device_ip,
                            "device_name": device_name,
                            "device_type": "ilo",
                            "severity": fc.get("severity", "high"),
                            "type": "firmware_critical_outdated",
                            "title": f"Firmware critical outdated — {device_name}",
                            "message": f"Versione iLO/BIOS sotto min_safe_version. CVE aperte: {len(all_cves)}. Aggiornamento raccomandato urgente.",
                            "source_type": "redfish",
                            "status": "active",
                            "acknowledged_by": None,
                            "acknowledged_at": None,
                            "resolved_at": None,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "raw_data": "",
                        }
                        await self.db.alerts.insert_one(alert_doc)
            except Exception as _fe:
                logger.warning(f"firmware compliance check failed for {device_ip}: {_fe}")

            logger.info(f"Redfish OK: {device_name} | {result['server_model']} | {result['power_watts']}W | Health: {result['health_status']}")
        else:
            logger.warning(f"Redfish failed for {device_name} ({device_ip})")

    async def _check_alerts(self, device_ip: str, device_name: str, result: dict, client_id: Optional[str] = None):
        """Generate alerts for critical iLO conditions."""
        alerts = []

        # Overall health
        if result["health_status"] and result["health_status"] not in ("ok", "unknown"):
            alerts.append({
                "severity": "critical",
                "title": f"iLO Health {result['health_status'].upper()}",
                "message": f"Server {device_name} ({device_ip}) stato salute: {result['health_status']}",
            })

        # Temperature sensors
        for t in result["temperatures"]:
            if t["value"] > 75:
                alerts.append({
                    "severity": "critical",
                    "title": f"Temperatura critica: {t['value']}C",
                    "message": f"{t['locale']} su {device_name} ({device_ip}): {t['value']}C",
                })
            elif t["value"] > 65:
                alerts.append({
                    "severity": "high",
                    "title": f"Temperatura elevata: {t['value']}C",
                    "message": f"{t['locale']} su {device_name} ({device_ip}): {t['value']}C",
                })

        # Fans
        for f in result["fans"]:
            if f["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "high",
                    "title": f"Ventola {f['condition']}",
                    "message": f"{f['locale']} su {device_name} ({device_ip}): {f['condition']}",
                })

        # Power supplies
        for ps in result["power_supplies"]:
            if ps["condition"] not in ("ok", "n/a"):
                alerts.append({
                    "severity": "critical",
                    "title": f"Alimentatore {ps['condition']}",
                    "message": f"{ps['name']} su {device_name} ({device_ip}): {ps['condition']}",
                })

        # Storage controllers + drives
        for ctrl in (result.get("storage_controllers") or []):
            ctrl_health = (ctrl.get("health") or "").lower()
            ctrl_status = (ctrl.get("status") or "").lower()
            if ctrl_health and ctrl_health not in ("ok", "unknown", ""):
                alerts.append({
                    "severity": "critical",
                    "title": f"Controller RAID {ctrl_health.upper()}",
                    "message": f"Controller '{ctrl.get('name','?')}' su {device_name} ({device_ip}): stato {ctrl_health}" +
                               (f" ({ctrl_status})" if ctrl_status else ""),
                })
            for dr in (ctrl.get("drives") or []):
                drive_health = (dr.get("health") or "").lower()
                drive_state = (dr.get("state") or "").lower()
                drive_failed = bool(dr.get("failure_predicted"))
                label = dr.get("model") or dr.get("name") or "disco"
                if drive_health and drive_health not in ("ok", "unknown", ""):
                    alerts.append({
                        "severity": "critical",
                        "title": f"Disco {drive_health.upper()}: {label}",
                        "message": f"Disco {label} (slot {dr.get('slot','?')}) su {device_name} ({device_ip}): health={drive_health}, state={drive_state or 'n/a'}",
                    })
                elif drive_failed:
                    alerts.append({
                        "severity": "high",
                        "title": f"Disco guasto previsto: {label}",
                        "message": f"Disco {label} (slot {dr.get('slot','?')}) su {device_name} ({device_ip}): SMART prevede guasto imminente",
                    })

        # Memory DIMMs
        for dimm in (result.get("memory_dimms") or []):
            dimm_health = (dimm.get("health") or "").lower()
            if dimm_health and dimm_health not in ("ok", "unknown", "") and dimm.get("capacity_mb", 0) > 0:
                alerts.append({
                    "severity": "critical",
                    "title": f"DIMM Memoria {dimm_health.upper()}",
                    "message": f"DIMM '{dimm.get('name','?')}' ({dimm.get('capacity_mb',0)}MB) su {device_name} ({device_ip}): {dimm_health}",
                })

        # Network adapters (NIC link status)
        for nic in (result.get("network_adapters") or []):
            nic_health = (nic.get("health") or "").lower()
            link_status = (nic.get("link_status") or "").lower()
            nic_name = nic.get("name") or nic.get("id") or "NIC"
            # Alert only on configured/connected NICs that went down
            if link_status == "linkdown" and nic.get("speed_mbps"):
                alerts.append({
                    "severity": "high",
                    "title": f"Link LAN DOWN: {nic_name}",
                    "message": f"Interfaccia {nic_name} ({nic.get('mac','?')}) su {device_name} ({device_ip}): link DOWN",
                })
            elif nic_health and nic_health not in ("ok", "unknown", ""):
                alerts.append({
                    "severity": "high",
                    "title": f"NIC {nic_health.upper()}: {nic_name}",
                    "message": f"Interfaccia {nic_name} su {device_name} ({device_ip}): health={nic_health}",
                })

        for alert in alerts:
            existing = await self.db.alerts.find_one({
                "device_ip": device_ip,
                "source_type": "redfish_direct",
                "title": alert["title"],
                "status": "active",
            })
            if not existing:
                _rf_alert = {
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "device_ip": device_ip,
                    "device_name": device_name,
                    "device_type": "ilo",
                    "severity": alert["severity"],
                    "source_type": "redfish_direct",
                    "title": alert["title"],
                    "message": alert["message"],
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await self.db.alerts.insert_one(_rf_alert)
                try:
                    import webpush as _wp
                    await _wp.notify_new_alert(self.db, _rf_alert)
                except Exception:
                    pass
                # CRITICAL: broadcast WebSocket per UI live-refresh (altrimenti gli
                # alert iLO appaiono solo al prossimo refresh manuale della pagina).
                # Gli altri moduli (alerts, ingestion, backup) fanno gia' questo.
                try:
                    from deps import manager as _mgr
                    _broadcast_alert = dict(_rf_alert)
                    _broadcast_alert.pop("_id", None)
                    await _mgr.broadcast({"type": "new_alert", "alert": _broadcast_alert})
                except Exception as _e:
                    logger.debug(f"WS broadcast failed: {_e}")

    async def _get(self, client: httpx.AsyncClient, url: str, auth: tuple, timeout: float = None) -> Optional[dict]:
        """Safe GET request with error handling. Optional per-call timeout override."""
        try:
            if timeout is not None:
                r = await client.get(url, auth=auth, timeout=timeout)
            else:
                r = await client.get(url, auth=auth)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    # ==================== PUBLIC API ====================

    async def test_connection(self, url: str, username: str, password: str) -> dict:
        """Test Redfish connection from the SOC backend."""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                r = await client.get(f"{url}/redfish/v1/", auth=(username, password))
                if r.status_code == 200:
                    data = r.json()
                    # Also try to get system info
                    sys_r = await client.get(f"{url}/redfish/v1/Systems/1/", auth=(username, password))
                    sys_info = sys_r.json() if sys_r.status_code == 200 else {}
                    return {
                        "success": True,
                        "redfish_version": data.get("RedfishVersion"),
                        "product": data.get("Product", sys_info.get("Manufacturer", "Unknown")),
                        "model": sys_info.get("Model"),
                        "serial": sys_info.get("SerialNumber"),
                        "health": sys_info.get("Status", {}).get("Health"),
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}
        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout connessione"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_failover_status(self, client_id: Optional[str] = None) -> list:
        """Get failover status for all iLO devices (or for a single client when
        `client_id` is set — used by the Credenziali tab inside ClientOverviewPage).

        Enterprise policy (2026-04-21): external_url presente = polling diretto SEMPRE.
        Connector = canale ridondante passivo.
        """
        query: dict = {"credential_type": "ilo"}
        if client_id:
            query["client_id"] = client_id
        ilo_creds = await self.db.device_credentials.find(
            query,
            {"_id": 0, "device_ip": 1, "device_name": 1, "external_url": 1, "direct_poll": 1, "connector_only": 1, "id": 1, "client_id": 1}
        ).to_list(500)

        result = []
        for cred in ilo_creds:
            device_ip = cred.get("device_ip")
            connector_offline = await self._should_failover(device_ip)
            external_url = cred.get("external_url")
            direct_poll = cred.get("direct_poll", False)
            connector_only = cred.get("connector_only", False)

            # New 3-state polling mode:
            # - direct: external_url configurato + non connector_only = diretto enterprise
            # - connector: nessun external_url + connector attivo = solo via connector
            # - failover: forced direct o connector offline + external_url presente
            # - offline: tutto down
            if connector_only and external_url:
                polling_mode = "connector"
            elif external_url and not connector_only:
                polling_mode = "direct"  # enterprise default: diretto sempre
            elif direct_poll and not external_url:
                polling_mode = "failover"  # forced, ma rischia di non funzionare (LAN unreachable)
            elif connector_offline and not external_url:
                polling_mode = "offline"
            else:
                polling_mode = "connector"

            result.append({
                "device_ip": device_ip,
                "device_name": cred.get("device_name"),
                "external_url": external_url,
                "direct_poll": direct_poll,
                "connector_only": connector_only,
                "connector_offline": connector_offline,
                "polling_mode": polling_mode,
            })

        return result


    # ==================== POWER CONTROL ====================

    async def power_action(self, url: str, username: str, password: str, action: str) -> dict:
        """
        Execute a power action on a server via iLO Redfish.
        Actions: On, ForceOff, GracefulShutdown, ForceRestart, PushPowerButton
        """
        valid_actions = ["On", "ForceOff", "GracefulShutdown", "ForceRestart", "PushPowerButton"]
        if action not in valid_actions:
            return {"success": False, "error": f"Azione non valida. Valide: {valid_actions}"}

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                # First get current power state
                sys_r = await client.get(
                    f"{url}/redfish/v1/Systems/1/",
                    auth=(username, password)
                )
                power_state = "Unknown"
                if sys_r.status_code == 200:
                    power_state = sys_r.json().get("PowerState", "Unknown")

                # Execute the reset action
                r = await client.post(
                    f"{url}/redfish/v1/Systems/1/Actions/ComputerSystem.Reset/",
                    auth=(username, password),
                    json={"ResetType": action},
                    headers={"Content-Type": "application/json"}
                )

                if r.status_code in (200, 204):
                    return {
                        "success": True,
                        "action": action,
                        "previous_state": power_state,
                        "message": f"Comando '{action}' inviato con successo",
                    }
                elif r.status_code == 400:
                    # iLO returns 400 if the action is not applicable (e.g., PowerOn when already On)
                    error_body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                    msg = error_body.get("error", {}).get("@Message.ExtendedInfo", [{}])
                    detail = msg[0].get("MessageId", "") if msg else str(error_body)
                    return {
                        "success": False,
                        "error": f"Azione non applicabile (stato attuale: {power_state}): {detail}",
                        "power_state": power_state,
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}

        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout connessione iLO"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata - iLO non raggiungibile"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_power_state(self, url: str, username: str, password: str) -> dict:
        """Get the current power state of a server via iLO Redfish."""
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                r = await client.get(
                    f"{url}/redfish/v1/Systems/1/",
                    auth=(username, password)
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "success": True,
                        "power_state": data.get("PowerState", "Unknown"),
                        "health": data.get("Status", {}).get("Health", "Unknown"),
                        "model": data.get("Model"),
                    }
                elif r.status_code == 401:
                    return {"success": False, "error": "Credenziali non valide"}
                else:
                    return {"success": False, "error": f"HTTP {r.status_code}"}
        except httpx.TimeoutException:
            return {"success": False, "error": "Timeout"}
        except httpx.ConnectError:
            return {"success": False, "error": "Connessione rifiutata"}
        except Exception as e:
            return {"success": False, "error": str(e)}
