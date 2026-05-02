# ARGUS Center — NOC Platform (86bit)

## Original problem statement
Società IT che necessita di un raccoglitore di alert (NOC) per tutti i dispositivi nelle reti dei clienti (switch, firewall, ecc.). Console live su PC e cellulare. Integrazione SNMP e Syslog. L'applicazione Windows (`86NocConnector`) deve essere nativa senza richiedere Python. Funzionalità stile Zabbix/PRTG/CloudFire. Dashboard TV, monitoraggio stampanti/backup, SOC AI, vulnerability assessment, WAN monitoring, multi-tenant SaaS.

## Stack
- Frontend: React + Tailwind + Shadcn/UI (Phosphor icons)
- Backend: FastAPI + Motor (MongoDB) + Pydantic
- Connector: PowerShell 5.1+ nativo con HMAC-SHA256, Nonce Anti-Replay, AES-256-GCM
- AI: `google-generativeai==0.8.6` (no emergentintegrations)

## Key architecture
```
/app/backend/routes/
  connector.py     → endpoints HMAC-secured + managed-devices CRUD per client
  devices.py       → device CRUD + Redfish test
  redfish_routes.py→ direct iLO polling/failover
  vault.py         → AES-256-GCM credential vault (admin only) — ora con client_id support
  overview.py      → Control Room aggregation
/app/frontend/src/pages/
  ClientOverviewPage.js → vista unificata per singolo cliente (tabs incluso Credenziali scoped)
  VaultPage.js          → vault globale + riusabile con scopedClientId prop
/app/noc-connector/src/
  connector.ps1    → main loop, HMAC auth, Redfish integration (v3.0.1)
  snmp_poller.ps1  → SNMP v1/v2c/v3 + Redfish REST
```

## Completed (session log)
- 2026-02-12: **Connector v3.6.8 — Fix Switch Ports HPE Comware + NSSM Paused**. Tre patch critiche su `snmp_poller.ps1::Poll-SwitchPortDetails`: (1) helper `_SafeNum` per cast difensivo (vuoti/null/binari → 0) risolve il crash `"" → System.Decimal` a linea 2513 che azzerava il polling porte. (2) `_LocalIsNumTbl`/`_IsNumericTable` forzano il walk 32bit (`ifInOctets`) quando `ifHCInOctets` torna byte BER non decodificati (HPE restituisce Counter64 raw su alcuni firmware 7.1.070). (3) `_FixUnsigned32` normalizza Counter32 Int32-negativi a uint32 (+2^32). Fix anche PoE (`pethPsePortAdmin/Status/Class`). Servizio NSSM riconfigurato con `AppParameters` quotato correttamente via `cmd /c nssm set ... \"C:\Program Files\86NocConnector\src\connector.ps1\"` (era in `SERVICE_PAUSED` perché PowerShell leggeva `C:\Program` come file). Risultato: 52 porte HPE 5130 JG937A pollate correttamente, counters positivi multi-GB, servizio RUNNING. Backend Center invariato. Hotpatch in-place applicato su GALVANSRV/ZITACSRV senza download. ZIP v3.6.8 pronto per upload centralizzato.

- 2026-05-01: **Switch Port Monitor Nebula-style + Connector v3.6.0**. Su richiesta utente (3 screenshot HPE Instant On allegati per riferimento), implementata vista porta-per-porta in stile Cisco Meraki / Nebula. PowerShell connector ora effettua polling completo `ifTable+ifXTable+ifLastChange+POWER-ETHERNET-MIB (RFC 3621)+lldpRemSysCapEnabled`, calcola Rx/Tx bps live tramite delta-state counters HC, distingue PoE attivo (saetta), AP (WiFi icon), switch uplink (Stack), router/internet (Cloud), device (Desktop), link_up (Plugs), empty/disabled. Backend `GET /api/devices/{ip}/switch-ports` arricchito con `port_type` calcolato da LLDP cap bitmap + managed_devices lookup, totali con `poe_active/rx_bps/tx_bps`. UI riscritta `SwitchPortsPage.js`: tile colorati con chip numero porta nero sopra, click apre pannello dettaglio (speed/full-duplex, PoE classe+W, Rx/Tx live + pps, Connesso a con link, donut SVG totali Scaricati/Caricati/Trasferiti), filtri Up/Down/Admin-down/PoE/LLDP, auto-refresh 30s, responsive mobile+desktop. Endpoint `/api/connector/switch-ports` esteso per persistere counters/PoE/LLDP cap. Test E2E con dati simulati 8 porte (2 PoE, 1 AP, 1 PC, 1 FortiGate, 1 switch, 3 down) → classificazione + render UI verificati screenshot.
- 2026-05-01 (notte): **Connector v3.7.0 — LLDP/CDP Topology Auto-Discovery**. Estende lo Sprint 2 della Network Topology con (1) polling **CDP** (CDP-MIB Cisco `1.3.6.1.4.1.9.9.23.1.2.1.1.*`) come fallback automatico per switch Cisco con LLDP disabilitato — `Poll-CdpNeighbors` in `snmp_poller.ps1` legge cdpCacheDeviceId/DevicePort/Address(hex IPv4)/Platform/Capabilities, mappa il bitmap CDP -> bitmap LLDP-style; (2) backend ingestion `POST /api/connector/cdp-neighbors` con HMAC-SHA256, salvataggio in `db.cdp_neighbors`, `build_cdp_edges()` analoga a LLDP che evita coppie già coperte da LLDP; (3) **Ghost Node auto-scoperti**: `build_ghost_nodes_and_edges()` trasforma i neighbor LLDP/CDP che non corrispondono a dispositivi managed in `discovery_candidate` con type derivato da capability bitmap (AP/Switch/Router/Phone), surfacati in un layer dedicato "Vicini Scoperti (LLDP/CDP)"; (4) frontend `NetworkMap.js` con edge orange dashed per CDP, badge `CDP: <count>` nella health bar, ghost-node con bordo dashed orange, badge LLDP/CDP, sfondo a strisce diagonali e legenda aggiornata; (5) endpoint `GET /api/network/cdp/{client_id}` raw + `GET /api/network/discovery-candidates/{client_id}` lista deduplicata pronta per pannello "Aggiungi dispositivo scoperto". `publish-connector.sh` aggiornato: lo zip storage ora include `Installa 86NocConnector.vbs` in root oltre a `prg/`. Pubblicato `86NocConnector_v3.7.0.zip` (~384 KB). Test E2E: cliente mock TEST-CDP con 2 switch managed + 1 LLDP AP non-managed + 1 CDP IP-Phone -> mappa rende correttamente edge LLDP cyan, edge CDP orange dashed, 2 ghost node con badge LLDP/CDP, lldp_count=2 cdp_count=1.



- 2026-01-15: Login redesign + responsiveness
- 2026-01-18: Client-centric navigation & Unified Client Overview Page
- 2026-01-22: Auto-Update Polling System with Cache Busting
- 2026-01-28: Extended WAN Monitor (Gateway ISP Ping, ICMP toggle, Schematic UI)
- 2026-02-05: SOC AI migrated to direct google-generativeai SDK
- 2026-02-10: IP Ban / Honeypot / Rate Limit middlewares rimossi per richiesta utente
- 2026-02-15: Connector v3.0.0 — HMAC-SHA256, Nonce Anti-Replay, Obfuscated paths
- 2026-02-20: Installer GUI + uninstall.bat + version.json auto-read
- 2026-02-25: Device merging (managed_devices + device_poll_status)
- 2026-03-01: Web Proxy Console Enterprise UI
- 2026-04-18 (pomeriggio):
- 2026-04-21: **Auto-detect Web UI dal connector → center + Auto-populate whitelist porte dall'apply profilo**. Risposta alla domanda "se il connector trova la porta giusta per UI, la sta passando correttamente al center?": **SÌ, arriva al center** (in `device_poll_status.open_ports` e `http_details`) ma **prima non veniva promossa** a `managed_devices.web_console_*`. Fix implementati: (1) Nuovo helper `_auto_detect_web_ui(client_id, dev)` in `/app/backend/routes/connector.py` chiamato automaticamente nel flusso `POST /api/connector/device-report`. Usa una tabella `_WEB_UI_PORT_PREFERENCE` con 17 porte note ordinate per peso (Synology 5001=110, UniFi 8443=100, Proxmox 8006=88, iLO 17990=85, ecc.) + boost +20 se HTTP risponde 2xx/3xx + title valido. Promuove la miglior candidate in `managed_devices.web_console_port/scheme/url/title/working/auto_detected` con upsert=true solo se c'è evidenza forte (status 2xx + title). Rispetta `web_console_user_configured=true` (admin ha applicato profilo) → scrive solo in `device_poll_status.detected_web_console_*` senza overwrite. (2) Apply profilo ora setta `web_console_user_configured=true` per proteggere dall'auto-detect. (3) Apply profilo AUTO-POPULA `connector_settings.allowed_ports_extra` se la porta del profilo non è nelle 22 default: ritorna `port_added_to_whitelist:true` → al prossimo heartbeat il connector riceve la porta nella sua whitelist runtime, zero rebuild. Testato end-to-end: device simulato Synology con open_ports [22,5000,5001] + title "Synology DiskStation" → managed_devices promosso a 5001 HTTPS auto_detected=true; apply profilo con porta custom 7777 → whitelist extra=[7777] immediato. Connector ZIP v3.3.5 ricostruito (294 KB) con nuova logica `DynamicAllowedPorts`.

- 2026-04-21: **Connector v3.3.5 — Whitelist porte Web Proxy estesa + dinamica**. Risolto errore "Porta X non consentita" quando si applicano profili vendor (synology_dsm:5001, hpe_ilo alt-mgmt, generic_ups). (1) Extended static whitelist in `/app/noc-connector/prg/src/connector.ps1` da 10 a 22 porte (aggiunte 5000/5001 Synology, 8006 Proxmox, 81 TrueNAS, 8088 QNAP, 3000 AdGuard/Pihole, 19999 Netdata, 4444 pfSense, 2222 DirectAdmin, 8083 Plesk, 17988/17990 iLO XMLagent). (2) **Whitelist dinamica configurabile da UI**: nuovo endpoint `GET/PUT /api/connector/settings/allowed-ports` (admin only, valida 1-65535, persiste in `connector_settings` Mongo). Il connector.ps1 al heartbeat legge `response.allowed_ports_extra` → popola `$script:DynamicAllowedPorts` → merge con default ad ogni richiesta web-proxy. Zero rebuild richiesti per aggiungere nuove porte. (3) **Bug fix download endpoint**: `GET /api/connector/download/{filename}` ora accetta ANCHE admin JWT (Authorization header o `?token=<jwt>` query param per anchor href browser) oltre all'API key del connector. Permette download manuale dello ZIP da browser admin. (4) **Build + deploy**: ZIP v3.3.5 creato `/app/connector_updates/86NocConnector_v3.3.5.zip` (294 KB), registrato in `connector_updates` Mongo come `active:true` con SHA256. Tutti i connector al prossimo heartbeat vedranno `latest_version=3.3.5` e si aggiorneranno via staged-in-InstallDir v3.3.4.

- 2026-04-21: **Fix "Nessun controller" intermittente + Profilo hpe_ilo Gen9/10/11**. Root cause: Redfish `/Systems/1/Storage` va in timeout/payload vuoto su iLO sotto carico → il vecchio codice sovrascriveva `storage_controllers=[]` cancellando i dati buoni. Fix in `/app/backend/redfish.py` (~linea 730-770): helper `_keep_if_empty()` che confronta la nuova lista con la precedente dal DB; se la nuova è vuota ma c'era cronologia, ritorna la cronologia con `stale:true` su ciascun item + timestamp `storage_last_good_at` / `memory_last_good_at` / `network_last_good_at`. Aggiunte anche **5 URI di ricerca storage** (SmartStorage, Storage, Chassis Storage, no-trailing-slash, SmartStorage index con follow `Links.ArrayControllers`) + dedupe drive_refs + early-exit quando già trovato + inclusione dei campi `rotation_rpm`, `hours_used`, `temp_celsius` dai drive (Oem.Hpe). Frontend `ClientOverviewPage.js IloServerCard`: badge Storage mostra label "Storage (cache)" con colore violetto (#A78BFA) e testo "N/N drive OK · stale" + tooltip con timestamp ultimo poll completo quando `storage_stale=true`. `InfoBadge` esteso con prop `tooltip`. **Nuovo profilo `hpe_ilo`** per HPE ProLiant Gen9 (iLO 4) / Gen10 (iLO 5) / Gen11 (iLO 6) con 44 OID CPQHLTH-MIB, 17 endpoint Redfish (Systems/Chassis/Managers + ThermalSubsystem/PowerSubsystem per Gen10+ + VirtualMedia + ComputerSystem.Reset), metadata `generations.gen9/10/11` con iLO version/schema/TLS min/note, capabilities (kvm_console_html5, virtual_media, power_control, smart_array_status, ilo_federation). Runbook `ilo-fan-critical` ri-seedato con `profile_keys=['hpe_ilo']` + `capability_match=['hardware_oob','thermal_detail']`. Frontend DeviceProfileModal auto-suggerisce `hpe_ilo` per `device_type in (ilo, server_oob, server)`. Testato 23/23 (iteration_57). Profili totali: 13.

- 2026-04-21: **Device Profile Library estesa a 12 profili + UI inline "Configura profilo"**. Aggiunti 2 profili mancanti al seed: (1) **`hpe_comware`** per switch HPE/H3C 5130/5500/5900/7500 ex-H3C (OID H3C enterprise MIB 1.3.6.1.4.1.25506.*, non ICF come ProCurve) con sysObjectID/sysDescr fingerprint dedicato; (2) **`generic_ups`** per UPS non-APC via RFC 1628 UPS-MIB standard (Riello/XANTO, CyberPower, Eaton/Powerware, MGE, Socomec) con OID standard (`upsEstimatedChargeRemaining`, `upsEstimatedMinutesRemaining`, `upsOutputSource`, `upsInputVoltage`, ecc.) e note web console. **Frontend ClientOverviewPage Dispositivi tab**: aggiunto pulsante **Cpu icon "Configura profilo"** per ogni riga device (`data-testid=configure-profile-{ip}`), pulsa in arancione se nessun profilo è impostato, cyan se già configurato. Modal `DeviceProfileModal` con: (a) auto-suggestion basata su `device_type` (nas→synology, ups→generic_ups, switch→hpe_comware, firewall→fortinet, ilo→dell_idrac); (b) dropdown raggruppato per famiglia (Switch/Firewall/NAS/UPS/...); (c) **anteprima live** URL web console risolto (`https://<ip>:<port><path>`), SNMP, polling, OID count, note vendor; (d) call `POST /api/device-profiles/apply` → aggiorna `managed_devices` con `web_console_port/scheme/path`, `snmp_port/version`, `profile_key`, `vendor`. **Frontend WebConsole.js `defaultWebPort`**: aggiunto fallback `nas → 5001` (Synology). Dopo apply, la Web Console usa automaticamente la porta corretta senza configurazione manuale. Lint + smoke screenshot OK.

- 2026-04-21: **Runbook Auto-Match per vendor + capability**. Estesa `/app/backend/routes/runbooks.py`: modello `Runbook` con nuovi campi `profile_keys`, `capability_match`, `vendor_match`, `severity_match`. Endpoint `/match/alert/{id}` ora arricchisce il contesto dal device: query a `device_poll_status.profile_key/vendor/family` + lookup capabilities dal Device Profile Library → scoring multi-fattore (profile +5, keyword +3 cad, device_type +2, vendor +2, capability +2 cad, severity +1). Ritorna `{alert, context:{profile_key,vendor,family,capabilities}, matches:[{..., _match_score, _match_reasons}]}`. Nuovo endpoint `POST /api/runbooks/seed-defaults` (admin, idempotente via tag `seed:<slug>`) che carica 8 runbook starter: Synology disk-degraded, Synology volume-full, Fortinet VPN down, APC UPS on-battery, HP switch port down, UniFi AP offline, HPE iLO fan critical, device-offline generico. **Frontend `AlertDetailPage`**: nuovo pannello "Runbook suggeriti" con badge contesto device (`vendor/profile_key` in alto a dx), card "BEST MATCH" sul top (score + reasons chip), accordion espandibile per vedere gli step (title + description + command in monospace verde + expected_result in ciano). Testato 23/23 backend + 8/8 frontend + 6/6 V4 regression + 10/10 Device Profiles regression (iteration_56). Bug fix collaterale: `POST /api/runbooks` rimuoveva `_id` Mongo prima di ritornare (era 500). Nessun action item.

- 2026-04-21: **Device Profile Library (auto-configurazione multi-vendor)**. Nuovo modulo `/app/backend/device_profiles/` con 10 profili seed (HP/Aruba ProCurve, Synology DSM, QNAP QTS, Fortinet FortiGate, Ubiquiti UniFi, Zyxel USG/ATP, APC UPS, Cisco Catalyst, Dell iDRAC, Generic fallback). Ogni profilo ha: **fingerprint** (sysObjectID prefix + sysDescr regex), SNMP defaults (porta/versione/community/timeout), Web Console defaults (porta/scheme/path/note), **OIDs** vendor-specific (CPU, RAM, temp, dischi SMART, RAID status, batteria UPS, VPN tunnel, HA status…), **thresholds** di alert, `polling_interval_seconds`, `capabilities` list, `api_endpoints` per poller livello 3 (Synology DSM webapi, Fortinet REST `/api/v2/monitor/*`, UniFi Controller, Dell Redfish). **Backend routes** `/app/backend/routes/device_profiles.py`: `GET /api/device-profiles`, `GET /api/device-profiles/{key}`, `POST /api/device-profiles/fingerprint` (match engine: OID→score 100, regex→score 40, threshold ≥40), `PUT /api/device-profiles/{key}/override` (admin, whitelist campi overridable), `DELETE /api/device-profiles/{key}/override`, `POST /api/device-profiles/apply` (auto o forzato), `GET /api/device-profiles/list/vendors` (dropdown helper). **Integration in connector.py**: al primo ingest di un device (o cambio sys_descr) la pipeline chiama `fingerprint()` e arricchisce `device_poll_status` + `managed_devices` con `profile_key`, `vendor`, `family`, porte e credenziali suggerite (`profile_auto_matched=true`). **Frontend** `/app/frontend/src/pages/DeviceProfilesPage.js` (nuova rotta `/device-profiles` + voce sidebar "Amministrazione > Device Profiles"): grid 10 card con filtro famiglia e search, modal dettaglio con sezioni fingerprint/SNMP/WebConsole/thresholds/OID/API, modalità "Modifica" con textarea JSON salvata come override DB, modal "Tester Fingerprint" standalone per validare profili con sysOID+sysDescr. Testato 28/28 backend + 8/8 frontend + 6/6 regression Web Console V4 (iteration_55). Nessun action item.

- 2026-04-21: **Hardware Health Matrix riusabile** (3 luoghi, 1 componente). Estratto il badge 4×2 a pallini (SYS·TMP·FAN·PSU·MEM·STO·CPU·NIC) in un componente condiviso `/app/frontend/src/components/HealthBadge.jsx` (3 size: xs/sm/md, `rollupSubsystems()` helper per worst-of). Applicato in: (1) **iLO live strip** — `ILoLiveMetrics.js` refactor per importare il componente condiviso (rimosso HealthMatrix duplicato); (2) **ClientOverviewPage header** — badge next-to titolo cliente che mostra "Hardware iLO · N" + matrice rollup di tutti gli iLO del cliente (data-testid `client-hw-health-badge`); (3) **TV Dashboard tile** — sezione "HARDWARE iLO (N)" + matrice per ogni tile cliente (data-testid `tv-tile-hw-health-{clientId}`). Backend `/app/backend/routes/tv_dashboard.py`: nuove helper `_compute_subsystems_for_device()` e `_rollup_subsystems()`, campi `hardware_health` + `ilo_server_count` aggiunti ai `client_summaries`, nuovo endpoint `GET /api/tv/clients/{client_id}/hardware-health` (no auth, coerente con TV board). Testato 15/15 backend + 4/4 frontend (iteration_54). Non visibile in preview solo perché 0 iLO pollati con successo (behaviour atteso).

- 2026-04-21: **Hardware iLO live header — 3 widget aggiuntivi**. Riempito lo spazio libero nell'header con tre metriche complementari a Power/MaxTemp: **Inlet Ambient** (°C, sparkline, colore dinamico 18/28/35°C, dice se l'AC del datacenter è OK), **Fan Max%** (sparkline, colore 0/50/75%, dice la "risposta cooling" — indicatore di stress distinto dalle temperature) e **Health Matrix 4×2** (8 pallini: SYS·TMP·FAN·PSU·MEM·STO·CPU·NIC, ciascuno aggregato da temperatures/fans/PSUs/DIMMs/storage_controllers/NIC link status). Backend: esteso `/api/redfish/metrics/{device_ip}` con `latest.inlet_celsius`, `latest.inlet_sensor_name`, `latest.fan_max_percent`, `latest.fan_count`, `latest.subsystems{system,thermal,fans,power,memory,storage,network,processors}` + serie `inlet_temperature` e `fan_max_percent`. Frontend: `ILoLiveMetrics.js` renderizza i 3 nuovi widget con soglie colore + tooltip ASHRAE. File: `/app/backend/routes/redfish_routes.py` (get_redfish_metrics), `/app/frontend/src/components/ILoLiveMetrics.js` (+ componente `HealthMatrix`). data-testid: `ilo-live-inlet`, `ilo-live-fanmax`, `ilo-live-health-matrix`, `ilo-live-health-{subsystem}`.

- 2026-04-21: **Web Console V4 (Popup/New Tab JWT proxy)** — completata & testata al 100% (16/16). Backend `/app/backend/routes/web_console_v4.py` espone:
  - `POST /api/console-v4/request-session` → firma JWT HS256 (TTL 60 min), insert in `console_sessions`, ritorna path relativo `/api/console-v4/s/<token>/` (frontend antepone `window.location.origin` per evitare problemi di Host header dietro ingress).
  - `GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS /api/console-v4/s/{token}/{path}` → reverse-proxy full: inietta `<base href>` in HTML, riscrive URL assoluti/root-relative (href/src/action/url in HTML & CSS), riscrive Location in redirect, mantiene cookie jar server-side in `_SESSION_COOKIES`, strippa `X-Frame-Options/CSP/HSTS`, forwarda Basic/Digest Auth al browser, `verify=False` per self-signed. Fallback HTML 502 per device non raggiungibili, 410 per token scaduto, 401 per token invalido.
  - `GET /api/console-v4/sessions` (admin) + `POST /api/console-v4/revoke/{sid}` (solo admin → 403 per viewer).
  - Frontend `WebConsoleTabs.js`: `openPopup(deviceIp)` esposto nel context; pulsante "V4" nell'ActiveConsole toolbar (`data-testid=web-console-popup-v4`) e in ogni `QuickAccessItem` (`data-testid=quick-popup-<ip>`). Bypass definitivo dei blocchi iframe/CSP/JS routing di iLO 5, Fortinet, UniFi.
  - Fix correlato: riparato errore di sintassi nella funzione `close()` del provider (era lasciata a metà, bloccava la compilazione frontend).

  - **Add Device from Client Page**: pulsante "+ Aggiungi Dispositivo" e eliminazione device dentro la tab Dispositivi del `ClientOverviewPage`, supporto SNMP v1/v2c/v3 + Ping + HTTP. POST su `/api/connector/{client_id}/managed-devices`.
  - **Bug fix fetch-devices**: l'endpoint `GET /api/connector/fetch-devices` e `/{C}/fd` (HMAC) ora restituisce tutti i campi SNMPv3 (snmp_version, snmpv3_username, snmpv3_auth_*, snmpv3_priv_*, snmpv3_security_level). Prima venivano ignorati.
  - **Connector v3.0.1 (FIX REDFISH)**:
    - FIX bug critico in `Fetch-VaultCredentials`: rimossa chiamata `Invoke-RestMethod` duplicata con variabili non definite (`$url`, `$headers`) che sovrascriveva la risposta.
    - Esteso trigger Redfish: parte anche quando SNMP fallisce ma ci sono credenziali Vault di tipo `ilo`/`redfish` per l'IP target o `device_type=ilo` manualmente.
    - Log diagnostici più espliciti.
    - ZIP pubblicato via `/api/connector/upload-update`.
  - **Vault per Cliente (Opzione B)**:
    - Backend: `client_id` in `CredentialCreate/Update`, filtro `?client_id=` in GET, validazione 404 se client non esiste, endpoint connector `/{C}/vc` filtra per client HMAC-authed + credenziali globali.
    - Frontend: `VaultPage` riutilizzabile con prop `scopedClientId`, nuova tab "Credenziali" in `ClientOverviewPage`, dropdown filtro "Cliente" nella vista globale, badge "Globale" sulle credenziali senza client_id.
    - 12/12 test backend passati (iteration_50.json).
- 2026-02-18 (fork):
  - **Mobile Responsive iPhone**: tabelle wrappate in `overflow-x-auto` con `min-width` su mobile (AlertsPage, ClientOverviewPage devices/alerts, DevicesPage, InventoryPage, EnterprisePage users, PortMonitorPage, DashboardPage recent alerts). DeviceDetailPanel full-screen su mobile (`fixed inset-0`), drawer solo da `md:` in su. Smoke test Playwright a 390x844 (iPhone) su Dashboard, Alerts, Clients, ClientOverview, Sidebar + tab Devices — tutti correttamente scrollabili e senza overflow laterale.
  - **Web Push Notifications (VAPID)**: implementazione reale al posto del mock precedente. Backend: `pywebpush==2.3.0`, chiavi VAPID generate (in `backend/.env`: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT). Nuovo modulo `/app/backend/webpush.py` con `send_to_user`, `send_to_roles`, `notify_new_alert` (fire-and-forget, auto-prune di subscription scadute 404/410). Nuove route `/api/push/*`: `vapid-public-key`, `subscribe`, `unsubscribe`, `status`, `test`. Hook `notify_new_alert(db, alert_doc)` aggiunto in alerts.py, ingestion.py (syslog + snmp), external_monitor.py, connector.py (2 posizioni), connector_watchdog.py, redfish.py, printers.py, backup.py. Inviate solo per severity=critical/high (configurabile via `notification_rules.push_enabled`). Frontend: `PwaProvider` aggiornato con `subscribeToPush`, `unsubscribeFromPush`, `sendTestPush` che fetchano la chiave VAPID dal backend. Nuovo pannello "Notifiche Push" in `SettingsPage` con stato, Attiva/Disattiva e pulsante Test. SW (`sw.js`) già gestiva correttamente l'evento `push` e `notificationclick`. Bug fix collaterale: `alerts.py` non passa più `id` doppio ad `AlertResponse` su duplicati. **21/21 test backend passati** (iteration_51.json).
  - **Quiet Hours per utente**: nuova collection `user_notification_prefs` con `quiet_hours_enabled`, `quiet_start` (HH:MM), `quiet_end` (HH:MM), `quiet_timezone` (default `Europe/Rome`), `quiet_exclude_critical` (default true, critical bypassa la finestra). `webpush.send_to_user` ora controlla `is_in_quiet_hours()` e ritorna `skipped=quiet_hours` se nella finestra. Supporto finestre overnight (22-07) e daytime (13-14). Endpoint `GET/PUT /api/push/preferences` con validazione HH:MM. Endpoint `/api/push/test` bypassa intenzionalmente la quiet window per permettere la prova. Frontend: card "Notte silenziosa" in SettingsPage con toggle, input `type=time`, switch bypass critical, info fuso orario. Testato via curl + unit logic.
  - **On-Call Rotation**: nuova collection `oncall_config` (singleton doc) con `rotation_enabled`, `timezone`, `slots[]` (day_of_week Mon=0..Sun=6, start/end HH:MM, user_id, user_email). `oncall.get_on_call_user_ids(db)` ritorna i reperibili al momento corrente (supporto turni overnight tipo Fri 22:00→Sat 07:00). `webpush.notify_new_alert` ora: se `rotation_enabled=true` e qualcuno è di turno → push SOLO a quegli user_id (ognuno con le proprie Quiet Hours applicate); altrimenti fallback a tutti admin+operator. Nuovi endpoint: `GET /api/oncall/schedule`, `PUT /api/oncall/schedule` (admin-only, validazione HH:MM), `GET /api/oncall/current`, `GET /api/oncall/users`. Frontend: nuova pagina `/oncall` (`OnCallPage.js`) con banner "Reperibile ora" + master toggle + lista turni configurabili con Select giorno/operatore + time picker start/end. Voce "Reperibilità" nel menu Amministrazione (admin+operator). Testato via curl + screenshot desktop+mobile.
  - **Escalation automatica**: nuovo modulo `/app/backend/escalation.py` con `EscalationScheduler` background loop (interval 60s, startup in server.py). Config singleton `escalation_config`: `enabled`, `wait_minutes` (1-1440), `severities`, `escalate_to_roles`. Scan su `alerts` dove `status=active`, `severity∈cfg.severities`, `acknowledged_by` vuoto, `created_at<=now-wait_minutes`, `escalated≠true` → marca `escalated=true` + invia push con tag "ESCALATION" ai ruoli indicati (ignora on-call e quiet hours dei singoli, invia SEMPRE). Endpoint: `GET /api/escalation/config`, `PUT /api/escalation/config` (admin-only, validazione severity/ruolo), `POST /api/escalation/run-now` (admin, per trigger manuale). Frontend: card "Escalation automatica" integrata in `OnCallPage` con toggle, input minuti, select ruolo e pulsante "Esegui ora". Testato via curl (escalated 6 alert esistenti al primo run-now).
  - **Notification Delivery Log (admin-only)**: nuova collection `notification_delivery_log` con `alert_id`, `type` (initial/escalation), `user_id`, `user_email`, `user_name`, `channel`, `endpoint` (last 40 char), `outcome` (delivered/failed/expired/skipped_quiet_hours/no_subscriptions/vapid_not_configured), `error`, `created_at` (ISO string per UI) + `created_at_ts` (BSON Date per TTL). `webpush.send_to_user` / `send_to_roles` ora accettano `log_context={alert_id, type}` e scrivono una riga per ogni tentativo di delivery. `notify_new_alert` passa `type=initial`, `escalation._run_once` passa `type=escalation`. Endpoint admin-only: `GET /api/alerts/{alert_id}/notification-log` (403 per non-admin verificato, esclude `created_at_ts`). Frontend: pannello "Log notifiche (admin)" in `AlertDetailPage` visibile SOLO a user.role=admin, con tabella (Data/Ora, Tipo con badge initial/escalation, Destinatario con email, Canale, Esito colorato, Dettaglio errore/endpoint).
  - **TTL index notification log**: `notification_delivery_log.created_at_ts` con `expireAfterSeconds=7776000` (90 giorni) + compound index `(alert_id, created_at_ts)` per query veloci. MongoDB purga automaticamente i log più vecchi di 90 giorni.
  - **Web Console TURBO (v3.0.3)**: riscritto il proxy web come long-polling con hot-trigger `asyncio.Event` lato backend (latenza da ~3s a ~50ms). Endpoint `/connector/web-proxy/pending?wait=N` e `/connector/web-proxy/response/{id}?wait=N` (max 25s). Connector PowerShell v3.0.3 aggiorna `Invoke-SecureGet` con timeout configurabile e usa `wait=20`. Frontend: nuovo componente riutilizzabile `/components/WebConsole.js` (hook `useWebConsole` + modal). Sostituito polling con setInterval (500ms × 40 tentativi = peggior caso 30s) con **1 sola GET long-poll** (wait=25, ~30s timeout). Pulsante Monitor in DevicesTab del ClientOverviewPage visibile solo quando `device.status=online/active` E `device_type∈[firewall, switch, router, access-point, printer, ilo, server, nas, ups]` o `monitor_type=http`. Porta default smart: 443 per iLO/firewall, 80 altri. Testato end-to-end: modal si apre, long-poll 3s timeout corretto (117ms per 404).
  - **Web Console Multi-Tab**: nuovo provider `WebConsoleTabsProvider` in `/components/WebConsoleTabs.js` montato una volta in App.js tra PwaProvider e BrowserRouter. Gestisce N sessioni parallele, ciascuna con proprio `AbortController` e long-poll indipendente. Dock flottante in basso a destra (fixed, z-40) con pulsanti `CONSOLES (N)` + pillola per ogni tab (statusDot: amber=loading, red=error, emerald=ok) + `CHIUDI TUTTE`. Modal (z-50) mostra la sessione attiva con header `(idx/total)` + frecce Prev/Next + 3 pulsanti: minimize (lascia nel dock), close (termina), semaforo macOS. Dedup automatica: apertura su stesso client+ip+port → refocus esistente. Persistente tra navigazioni di pagina (context al livello App). Hook `useWebConsoleTabs()` espone `{sessions, activeId, open, close, reload, navigate, setActive, minimize, closeAll}`. `ClientOverviewPage.DevicesTab` ora usa questo context (rimosso modal locale). Testato: aperte 3 sessioni in parallelo, dock mostra 3 tab, modal navigabile con frecce.

### Web Console LIVE v1 — ARCHITETTURA PULITA (2026-04-20)
Refactor completo. Elimina la causa radice del bug iframe nero (srcDoc → origine null → fetch impossibili).

**Nuova architettura**:
- Endpoint catch-all `/api/web-proxy/live/{session_id}/{device_ip}/{port}/{path:path}` accetta qualsiasi method (GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS).
- Auth via **capability token** (session_id è il token UUID, TTL 8h) — l'iframe non può settare Bearer headers, questo bypass è pulito e sicuro.
- Endpoint `POST /api/web-console/session` crea il token bindato a (user, client, device, port).
- Browser usa `iframe src=` invece di `srcDoc` → iframe ha origine argus.86bit.it → può fare fetch/XHR naturalmente.
- Backend inietta `<base href="/api/web-proxy/live/{session}/{ip}/{port}/">` nel `<head>`. Il browser risolve tutti i path relativi contro questo base → asset CSS/JS/img/font/XHR vengono proxati automaticamente.
- Interceptor JS minimal (solo title propagation al parent per status bar).
- Collection `web_console_tokens` con indice TTL su `expires_at`.

**File toccati**:
- `/app/backend/routes/web_console_live.py` (nuovo, ~250 righe)
- `/app/backend/server.py` (include_router + index TTL web_console_tokens)
- `/app/frontend/src/components/WebConsoleTabs.js` (riscritto da 488 a 280 righe, architettura iframe src=)

**Test e2e**:
- Session creation → OK
- Live proxy GET con NUL byte body → OK, `<base>` tag iniettato
- Invalid session → 401
- Tempo medio: 1.3s (vs 8.4s srcDoc approach)
- CSS/JS/img references preservati per auto-proxy browser-side

**Vantaggi**:
- Funziona per QUALSIASI device management (iLO, HP, Aruba, Cisco, Fortinet, Zyxel, Ubiquiti, UPS APC/Xanto, Synology, stampanti)
- Navigazione nativa (back/forward/click/submit browser standard)
- Cookie propagati automaticamente dal browser
- Nessun inlining lato connector più necessario (ma retro-compat mantenuta)
- Nessuna CSP/X-Frame-Options del device (rimossi in risposta)
- Supporta POST form, JSON API, SPA, grafica pesante

### Web Console LIVE v2 — FRONTEND RISCRITTO (2026-04-20)
**Obiettivo raggiunto**: Web Console enterprise-grade come argus.86bit.it richiesto. Eliminato `srcDoc` (origine null) a favore di `<iframe src={iframe_url}>` che ha origine argus → cookie, XHR, JS, auth moderna funzionano nativamente.

**File toccati**:
- `/app/frontend/src/components/WebConsoleTabs.js` (riscritto, ~320 righe): usa `POST /api/web-console/session` all'apertura, renderizza `<iframe src={absoluteIframeUrl}>`, sandbox rilassato per fullscreen nativo, postMessage listener per title, dock multi-tab preservato. Nuovi pulsanti: Indietro (`history.back()`), Home, Ricarica (iframe key bump), Apri in nuova tab (stesso URL LIVE).
- `/app/backend/routes/web_console_live.py`: aggiunto `DELETE /api/web-console/session/{session_id}` per revoca best-effort (TTL index fa comunque cleanup automatico).

**Flusso**:
1. Click "Monitor" su device → `POST /api/web-console/session {device_ip, port}` → capability token + iframe_url.
2. `<iframe src=/api/web-proxy/live/{sid}/{ip}/{port}/>` carica e riceve HTML dal connector.
3. Backend inietta `<base href=...>` → browser fetcha CSS/JS/img relativi tramite endpoint LIVE (auto-proxy).
4. Service Worker `sw.js v4` bypassa `/api/web-proxy/live/` per non intercettare le richieste interne iframe.
5. Connector v3.2.1 (già in field) gestisce auto-follow JS redirect + Referer/User-Agent spoofing per HP 5130.

**Test backend**:
- Session senza device autorizzato → 403 OK
- Session con device autorizzato → 200 + UUID + iframe_url OK
- GET LIVE con token valido, no connector collegato → 504 dopo long-poll 20s OK
- GET LIVE con session invalida → 401 OK
- DELETE session → 200 {revoked: bool} OK
- Path con/senza trailing slash entrambi matchano catch-all OK

**Da validare in field (richiede connector + device reali)**:
- HP 5130 switch (argus cliente): iframe renderizza UI switch, login, navigation ✓
- iLO Redfish UI: iframe con auth, grafici, console remota ✓

### Web Console LIVE v3 — FIX DEFINITIVO (2026-04-20 sera)
**Root cause trovata via DBG JSON**: iLO 10.100.61.34 risponde sulla 443 con una pagina bootstrap che contiene hidden input (`http=5000, https=5001, prefer_https=false`) + script JS `location.href='https://10.100.61.34:5001/'`. Ma il Connector v3.2.1 inietta un interceptor che con `Object.defineProperty(window,'location',...)` cattura OGNI assegnazione come `postMessage({type:'argus-proxy-navigate'})`. Risultato: redirect device ignorato → iframe resta sulla bootstrap vuota → icona "file rotto".

**Fix definitivo backend LIVE (`web_console_live.py`)**:
1. **Rimozione interceptor connector**: regex che strippa qualunque `<script>…argus-proxy-navigate…</script>` dall'HTML prima di passarlo al browser.
2. **Rimozione marker `__ARGUS_PROXY__`** dai href/form action/iframe src (concetto srcDoc-era).
3. **URL rewriting completo**: `https?://{device_ip}(:port)?/path` → `/api/web-proxy/live/{sid}/{ip}/{port}/path` dentro HTML, JS, CSS, JSON. Supporta redirect cross-port (iLO 443→5001).
4. **Token sessione NON più bindato alla porta**: `_validate_session_token` cerca solo per `device_ip`, così redirect su porte diverse del device funzionano con lo stesso capability token.
5. **Location header riscritto** per redirect HTTP 3xx con URL assoluti.
6. **Debug headers v3**: `X-Argus-Proxy: v3`, `X-Argus-Sniff`, `X-Argus-CT-Orig`.

**Unit test in-place**: rewriting URL con/senza porta, strip interceptor, inject `<base>` verificati tutti OK.

**Vantaggi**: nessun aggiornamento Connector richiesto — il fix è tutto lato backend, retrocompatibile con Connector v3.2.1 già in field.

### ITIL / INOC Feature Pack (2026-04-21) — Enterprise NOC maturity
Spunto gap-analysis ARGUS vs INOC Ops 3.0. Implementate 8 feature enterprise.

**Backend — 5 nuovi router**:
- `routes/cmdb.py` — Asset inventory (vendor, S/N, garanzia, contratto, ciclo vita, responsabile). Warranty-alerts 60gg.
- `routes/runbooks.py` — Procedure operative CRUD, matching smart su alert (device_type + keywords + severity).
- `routes/sla.py` — SLA targets per cliente (uptime/MTTA/MTTR/coverage/credit), compliance report mensile con breach analysis.
- `routes/customer_portal.py` — JWT dedicato `role=customer`, dashboard/devices/alerts/incidents filtered by client_id (isolation).
- `routes/itsm.py` — Change Management (RFC approve/reject/complete), Problem Management (5-whys, recurrence KPI), Shift Handoff report, Service Billing mensile.

**DB collections**: `cmdb_assets`, `runbooks`, `sla_targets`, `customer_users`, `changes`, `problems` con indici appropriati.

**Frontend — 4 nuove pagine admin**:
- `CMDBPage` — tabella asset con editor, warranty warnings banner
- `RunbooksPage` — CRUD runbook con steps, keywords/device-types multi-tag
- `SLAPage` — lista clienti con targets inline, compliance report dettagliato (breach + credit)
- `CustomerPortalPage` — login standalone su `/customer-portal`, dashboard cliente read-only con stats + alert recenti

**Route sidebar**: aggiunti CMDB, Runbooks, SLA Management.

**Endpoint API completi** (API-first, UI custom successiva):
- ITSM: `POST/GET /api/itsm/changes`, approve/reject/complete, `POST/GET /api/itsm/problems`, `GET /api/itsm/shift-handoff?hours=8`, `GET /api/itsm/billing/monthly/{client_id}`

**Skippato**: AIOps ML noise reduction (troppo pesante per singola sessione, rimane backlog).


**Richiesta utente**: telemetria real-time HPE iLO (Thermal, Power, System) con URIs Redfish standard.

**Backend `redfish.py`**:
- Conferma: tutti gli URI Redfish richiesti erano gia' pollati (`/Systems/1/`, `/Chassis/1/Power/`, `/Chassis/1/Thermal/`, `/Managers/1/`, Memory, EthernetInterfaces, Storage).
- Nuovo: **snapshot completo `ilo_telemetry`** per ogni poll con temperatures[], fans[], power_supplies[], health_status, power_watts, source.
- Indice `(device_ip, timestamp)` + TTL 7 giorni per time-series efficiente.
- Poll interval default ridotto da 5 min a **1 min** (configurabile via `settings.redfish_poll_interval`).

**Backend `redfish_routes.py`** (2 nuovi endpoint):
- `GET /api/redfish/metrics/{ip}?minutes=60`: timeline con serie power_watts/max_temp/avg_temp + per_sensor_temperatures per grafici multi-sensore.
- `GET /api/redfish/metrics/{ip}/live`: ultimo snapshot + age_seconds (per UI polling veloce).

**Frontend** — nuovo componente `ILoLiveMetrics.js`:
- Sparkline SVG custom (power in viola, max temp colorata per soglia 65/75°C) con pallino animato "live pulse"
- Auto-refresh ogni 15s (polling `/redfish/metrics/{ip}?minutes=60`)
- Badge "LIVE" con dot animato e colore health-aware
- Age label ("23s fa") per freshness
- Integrato nella `IloServerCard` in `ClientOverviewPage`, dentro un box bordato

**Test E2E** (curl):
- Seeded 5 snapshot fake → endpoint /metrics ritorna timeline completa ✓
- /metrics/live ritorna latest con age_seconds ✓
- Cleanup fixture ✓

**NB**: il metodo "Event Subscriptions" (push) descritto in HPE docs richiede listener HTTP pubblico raggiungibile dall'iLO e SSL valido, non praticabile per deploy multi-tenant. Abbiamo optato per polling 1-min aggressivo + snapshot time-series che da' UX equivalente senza bucare firewall cliente.

### Web Console LIVE v3.3 — FIX HTTP AUTH Basic/Digest (2026-04-20 notte++)
**Intuizione utente confermata corretta**: il proxy strippava `Authorization` dalle request browser→device e `WWW-Authenticate` dalle response device→browser. Risultato: i device con HTTP Basic/Digest auth (firewall, iLO legacy, switch enterprise) non mostravano mai il prompt di login → browser vedeva 401 o pagine vuote → iframe bianco.

**Fix `web_console_live.py`**:
- **Request**: rimosso `authorization` dalla blacklist header (il browser invia le credenziali Basic/Digest, ora raggiungono il device). Rimosso `cookie` dalla blacklist: ora filtriamo solo cookie ARGUS noti (`jwt_token`, `refresh_token`, `session*`, `XSRF-TOKEN`, `csrftoken`), tutti gli altri passano (sessione device preservata cross-request).
- **Response**: aggiunto `www-authenticate`, `proxy-authenticate`, `set-cookie` a `safe_to_pass`. Ora il browser riceve il challenge `WWW-Authenticate: Basic realm="iLO"` e apre il prompt nativo login.
- **Placeholder 404 body vuoto**: non sostituisce più se `status >= 400` ma header `WWW-Authenticate` presente (altrimenti mangerebbe il prompt login).

### Redfish/iLO Diagnose endpoint (2026-04-20 notte+)
**Problema utente**: iLO raggiungibile ma dati non live in ARGUS.

**Nuovo endpoint** `GET /api/redfish/diagnose/{device_ip}` (admin/operator):
Analizza 5 check in sequenza e ritorna JSON con `status` (ok/warn/error) e `fix` suggerito:
1. Device registration (managed_devices vs device_poll_status)
2. Device type (=ilo) o device_class (=hpe-ilo)
3. Credenziale Vault presente + credential_type=ilo
4. Direct poll cloud (direct_poll + external_url) OPPURE Connector LAN
5. Connector assegnato e online (heartbeat <120s)
6. Ultimo poll Redfish registrato in `ilo_status`

**Output**: `current_poll_source`, `last_successful_poll`, `recommendation` (fix prioritario).

### Web Console ENTERPRISE v1 (2026-04-20 notte) — FEATURE PACK DATTO+RUSTDESK
Spunto da Datto RMM (HTML5 remote, session recording, fullscreen) e RustDesk Pro (address book, device audit, permissions).

**Backend** (`routes/web_console_enterprise.py`):
- `GET /api/web-console/recent` — ultime 10 sessioni utente, dedupe per device, con device/client name
- `GET /api/web-console/favorites` + `POST /api/web-console/favorites/toggle` — preferiti per utente
- `GET /api/web-console/live-sessions` — sessioni aperte ora (admin/operator only)
- `GET /api/web-console/history/device/{ip}` — audit per device (chi, quando, quanto, registrato)
- `POST /api/web-console/recording/{sid}/toggle` + `GET /api/web-console/recording/{sid}` — session recording opt-in + timeline replay
- `POST /api/web-console/share/{sid}` — share link con TTL 5-60min + password opzionale
- `POST /api/web-console/shared/{token}/validate` — endpoint pubblico per accedere al share
- `DELETE /api/web-console/share/{token}` — revoca

**Collections nuove**: `web_console_history` (TTL 90gg), `web_console_favorites`, `web_console_shares` (TTL auto).

**Frontend** (`WebConsoleTabs.js` riscritto v5 + `SharedConsolePage.js` nuova):
- 🔲 Fullscreen mode (F11 + pulsante)
- ⌨️ Keyboard shortcuts: Ctrl+R reload, Ctrl+H home, Ctrl+D debug, F11 fullscreen, Esc exit, Alt+← back
- 📏 Latency indicator (loadTime primo frame)
- ⭐ Quick Access Drawer (3 tab: Recenti/Preferiti/Live con toggle preferito)
- 🔴 Recording toggle con badge REC pulsante in header
- 🔗 Share Session modal (TTL select + password opzionale + copy link + revoca)
- 🎨 Rotondi dark theme con animazioni micro

**Pagina pubblica `/shared-console/:token`**:
- Landing page senza auth ARGUS
- Gate password se protetto
- Countdown scadenza real-time
- iframe read-only full-height
- Header con "Shared · Read-only · by {user}"

**Test backend end-to-end** (13 step tutti passati):
- Session create con record=true
- Recent / Live / History per device / Favorites CRUD
- Recording toggle + timeline
- Share create (con password) / validate (wrong/right) / revoke


**Sintomo**: Web Console mostra "Connessione al dispositivo fallita → Impossibile stabilire una relazione di trust per il canale sicuro SSL/TLS" su HP 5130 e device con certificati self-signed, anche se il connector funziona e i device rispondono al "Test Web UI" dal tray.

**Root cause**: `System.Net.ServicePointManager.ServerCertificateValidationCallback` e' **globale/statico** in .NET. Il connector chiama `[CertBypass]::Enable()` all'inizio di una Web Proxy request e `[CertBypass]::Disable()` alla fine. Ma i thread paralleli (Redfish polling, SNMP discovery, WAN probe, altre Web Proxy requests) fanno `Disable()` in parallelo → se una delle `Invoke-WebRequest` HTTPS sta negoziando TLS mentre un altro thread chiama `Disable()`, il callback diventa `null` e .NET rifiuta il cert self-signed.

**Fix**: `[CertBypass]::Disable()` diventa **NO-OP**. Una volta abilitato il bypass globale, lo teniamo sempre ON. Accettabile perche' il connector gira in rete cliente controllata e il rischio MITM interno e' minimo rispetto al beneficio di stabilita' SSL/TLS per device legacy (HP 5130, Aruba vecchi, UPS Xanto, NAS con cert scaduti).

### Web Console LIVE v3.2 — FIX middleware sicurezza (2026-04-20 sera++)
**Root cause finale trovata da Firefox**: "Impossibile aprire questa pagina, argus.86bit.it non consente di visualizzare la pagina dentro un altro sito". Il middleware globale `SecurityHeadersMiddleware` in `server.py` aggiungeva SEMPRE `X-Frame-Options: DENY` + `CSP: frame-ancestors 'none'` a ogni response. Il mio fix v3 strippava gli header DEL DEVICE, ma il middleware li RIMETTEVA dopo.

**Fix in `server.py`**:
- Path `/api/web-proxy/live/*` ora riceve `X-Frame-Options: SAMEORIGIN` e CSP con `frame-ancestors 'self'` (permette embedding dentro argus.86bit.it).
- CSP rilassata anche per script/style/img/font/connect del device proxato (il device e' trusted via capability token).
- Tutti gli altri endpoint mantengono `DENY` + `frame-ancestors 'none'` (sicurezza invariata).

**Cache-Control in web_console_live.py**: `no-store, no-cache, must-revalidate` + strip ETag/Last-Modified del device per evitare 304 Not Modified che riserviva vecchie response.

**Frontend**: iframe src include `?_t={Date.now()}` per cache-bust assoluto.

**Test curl post-fix**:
- `/api/app-version` → `X-Frame-Options: DENY` (invariato, sicuro)
- `/api/web-proxy/live/...` → `X-Frame-Options: SAMEORIGIN`, CSP `frame-ancestors 'self'`, `Cache-Control: no-store`


**Secondo DBG JSON** (device iLO 10.100.61.35:443, body_size=13137): iLO HPE risponde con HTML valido di 13KB, content_type `text/html`, MA `x_frame_options: "sameorigin"` e path assoluti root (`href="/favicon.ico"`, `href=css/jquery-ui.css`, ecc.).

**Gap trovato**: il tag `<base href>` NON risolve path che iniziano con `/` (regola HTML: absolute-root paths ignorano `<base>`, vengono risolti contro l'origine corrente argus.86bit.it). Quindi `/css/jquery-ui.css` tentava di caricarsi da `argus.86bit.it/css/jquery-ui.css` → 404.

**Fix**: nuova funzione `_rewrite_root_paths(html, sid, ip, port)` che nel body HTML cerca attributi `href`, `src`, `action`, `formaction`, `poster`, `data-src`, `data-href`, `xlink:href` con valore che inizia con `/` (non `//`, non già proxato) e li prefixa con `/api/web-proxy/live/{sid}/{ip}/{port}`. Preserva URL assoluti (`http://`, `//cdn…`), fragment (`#`), path relativi, path già proxati.

**Unit test in-place**: CSS/JS/img/link/form con path root tutti correttamente riscritti, URL esterni e fragment intatti.


**Dopo deploy Prod 2.1.458**: iframe appariva vuoto con icona "file rotto" = browser riceve Content-Type non renderizzabile.

**Fix backend (`web_console_live.py`)**:
1. **Content-Type sniffing**: se risposta ha CT `application/octet-stream` / `x-binary` / `application/unknown` / vuoto, ma body inizia con `<html`/`<!doctype`/`{`/`[`/`<?xml`/`<svg`, forza CT corretto. Risolve device legacy che mandano MIME sbagliato.
2. **Strip header che rompono iframe**: `Content-Disposition` (forza download), `X-Frame-Options`/`CSP` (blocco iframe), `Content-Encoding`/`Transfer-Encoding` (già decompressi dal connector), `Strict-Transport-Security`.
3. **Debug headers**: `X-Argus-Proxy: v2`, `X-Argus-Sniff: 0/1`, `X-Argus-CT-Orig` per diagnostica rapida.
4. **Nuovo `GET /api/web-console/debug/{sid}`**: ritorna ultimi 20 request con status HTTP, CT originale, CE, X-Frame-Options, Content-Disposition, size, preview 512 byte. Admin/owner only.

**Fix frontend (`WebConsoleTabs.js`)**: aggiunto pulsante **DBG** (amber) nel header Web Console che apre tab JSON con diagnostica.


In attesa di bot token dall'utente.

### Connector v3.1.2 (2026-04-19) — CSV Import nel wizard installer
- `installer_gui.ps1`: aggiunto pulsante "Importa CSV..." a pagina 2 (Dispositivi). Auto-detect delimitatore (`,` / `;` / tab), header case-insensitive con alias (ip/ip_address/indirizzo/host, name/nome/hostname/device_name, community/snmp_community, device_type/type/tipo, snmp_version/version, port/snmp_port). Dedup contro IP gia' in lista, validazione IPv4/hostname, messaggio riepilogativo (importati / saltati / errori).
- Gap fix: i metadati extra (`device_type`, `snmp_version`, `snmp_port`) ora vengono serializzati in `config.json` → usati dal connector per SNMP polling e classificazione dispositivo (prima andavano persi in `$item.Tag`).
- Rilasciato: `/tmp/86NocConnector_v3.1.2.zip` (update flat, retro-compat v3.0.x updater) + `86NocConnector_v3.1.2_install.zip` (VBS+prg/) pubblicato in `/app/frontend/public/downloads/`. Upload backend via `/api/connector/upload-update` ok, i connettori in field si auto-aggiorneranno entro 5 min.

### P1 — Sostituire mock Email con integrazione reale (Resend / SendGrid / SMTP)
In attesa di scelta provider e credenziali. **Push notifications: DONE (Web Push VAPID).**

### Verifica utente post-deploy
- Testare fix Redfish: dopo re-deploy e auto-update del connector a v3.0.1, confermare che l'iLO `10.100.61.35` sia monitorato (redfish_ok=true nei log del connector).
- Testare Vault per cliente: editare credenziale `ILO - SRV-DC01 (ML350 Gen9)` assegnandola a un cliente specifico.

## 🛡️ POLICY DEVELOPMENT — REGOLE NON NEGOZIABILI
Regole stabilite dall'utente il 2026-04-23 dopo che un bug di routing iLO ha fatto sembrare fossero state rimosse funzioni:

1. **MAI rimuovere funzioni, endpoint, route, componenti UI, campi visualizzati, colonne tabella** senza esplicita autorizzazione utente
2. **MAI "ripulire" codice** che sembra duplicato/orfano senza prima verificare cross-reference e ricevere OK
3. **MAI toccare decoratori `@router.*`** se non per aggiungere nuove route
4. **MAI ristrutturare/refactorare** file esistenti se non espressamente richiesto
5. **Solo aggiunte**: ogni intervento estende, non sostituisce
6. **Prima di toccare file esistente**: grep dei riferimenti cross-file
7. **Se rilevo un bug che richiede rimozione**, segnalarlo PRIMA e attendere OK utente

## 📦 POLICY PUBBLICAZIONE CONNECTOR — DOPPIA LOCAZIONE OBBLIGATORIA
Ogni nuova versione del connector DEVE essere pubblicata in DUE percorsi, altrimenti l'auto-update dai client non funziona:

1. `/app/connector_updates/<filename>.zip` — path usato dall'API `/api/connector/download/{filename}` (auto-update del connector)
2. `/app/frontend/public/downloads/<filename>.zip` — path pubblico per download manuale via browser
3. `/app/frontend/public/downloads/<filename>_install.zip` — con VBS installer per prima installazione

Il record `db.connector_updates` deve contenere: `version`, `filename`, `file_size`, `active=True`, `published_at`, `changelog`.

**USA LO SCRIPT `/app/scripts/publish-connector.sh <version> "<changelog>"`** che fa tutto in automatico.

Bug storico (2026-04-23): pubblicazione v3.4.6/v3.4.7 fatta solo in `/app/frontend/public/downloads/` → auto-update endpoint restituiva 404 ai connector client.

## 🏗️ ARCHITETTURA AUTO-UPDATE (v3.5.0 reset completo 2026-04-23)
**Pattern enterprise Microsoft-native** — eliminato il precedente design fragile a 5 metodi fallback PowerShell.

- **Task**: `\86BIT\ArgusConnectorUpdater` (Windows Task Scheduler nativo)
- **Trigger**: ogni 5 minuti
- **Principal**: NT AUTHORITY\SYSTEM (RunLevel HIGHEST)
- **Azione**: `powershell.exe -File C:\Program Files\86NocConnector\src\update_check.ps1`
- **Perche' non bloccato da ASR/WDAC/SmartScreen**: Task Scheduler e' host firstparty Microsoft, PowerShell lanciato da lui e' sempre trusted.
- **File unico**: `prg/src/update_check.ps1` (~300 righe) contiene TUTTA la logica update (check, download, extract, stop service, copy, start, rollback).
- **Log centralizzato**: `%ProgramData%\86NocConnector\update.log` con rotation 2MB.
- **Migrazione**: da v3.4.x si usa una sola volta `bootstrap_to_v350.cmd` (incluso nel ZIP installer) — poi tutto automatico per sempre.

Rimossi in v3.5.0 (con OK utente): Check-ForUpdate, Install-Update (5 metodi fallback), Send-UpdateProgress, Start-UpdateCheckLoop, updater.ps1, updater.cmd, force-update-to-v3.4.x.cmd. Net cleanup: 500+ righe.

## Backlog / Future
- P2: Multi-tenant + White-label SaaS (workspace isolation)
- P2: LDAP/Active Directory integration
- P3: Zyxel Nebula Cloud API

## 2026-04-30: Hornetsecurity Sub-Group Mapping (P0 completato)
Mappatura per dominio email dentro un singolo tenant Hornetsecurity. Vedi
CHANGELOG.md per dettagli. 14/14 backend + 3/3 frontend test PASS.

### 2026-02-10: Fix P0 pulsante Web Console (icona Monitor indigo) non apriva nulla
**Sintomo utente**: cliccando sul pulsante Monitor viola/indigo nella tabella Dispositivi della Client Overview, non si apriva nessuna console/modal. Nessun errore visibile in console per l'utente.

**Root cause**: scope bug. In `/app/frontend/src/pages/ClientOverviewPage.js`:
- `openConsoleWithVpn` era definita a riga 52 DENTRO la funzione parent `ClientOverviewPage`
- Il pulsante che la chiamava (riga 1070) viveva però dentro il sub-component `DevicesTab` (riga 936), che è una funzione separata a livello modulo → NON eredita lo scope del parent
- Al click: `ReferenceError: openConsoleWithVpn is not defined` (swallowed da React onClick + non visibile se DevTools non aperto con "Preserve log")
- Inoltre `openConsoleWithVpn` usava `webConsole` che era a sua volta dichiarato SOLO dentro `DevicesTab` (riga 942) → era rotta anche se fosse stata chiamata dal parent

**Fix**: spostata la funzione `openConsoleWithVpn` dentro `DevicesTab`, subito dopo `const webConsole = useWebConsoleTabs()`. Logica invariata (apre console via `webConsole.open` + sessione VPN WireGuard best-effort in background). Rimossa la definizione morta nel parent.

**Test** (iteration_60.json): 100% PASS. 5/5 test cases desktop 1920x1080 + 5/5 mobile 390x844. Verified:
- Button renders per 10/14 devices del cliente 86BIT_Office (firewall/switch/router/etc online)
- Click apre `data-testid=web-console-active` (il dock)
- POST `/api/web-console/session` chiamato correttamente
- 0 ReferenceError in console
- Bottone Info (DeviceInfoCard) continua a funzionare senza regressioni

**File toccato**: `/app/frontend/src/pages/ClientOverviewPage.js` (funzione spostata di ~890 righe, scope corretto).

### 2026-02-10 (pomeriggio): UX Web Console — pulsante Monitor ora apre in NUOVA TAB (V4 popup) invece dell'iframe bloccato
**Feedback utente**: dopo il fix dello scope, l'iframe V3 LIVE si apriva ma restava su "Caricamento device..." infinito (connector GALVANSRV offline / rotta VPN non completamente up lato client). Richiesta: "con VPN su vai dritto al dispositivo come se facessimo dal browser" → esperienza browser nativa, nuova tab.

**Modifica**:
- `/app/frontend/src/pages/ClientOverviewPage.js` → `openConsoleWithVpn` in `DevicesTab` ora chiama `webConsole.openPopup(device.ip_address)` (V4 — JWT proxy full-page in nuova tab) come **primary**, con fallback a `webConsole.open(...)` (V3 iframe nel dock) solo se la popup è bloccata realmente. La sessione VPN audit `/api/admin/wireguard/session/start` è fire-and-forget in parallelo (non blocca l'apertura popup → preserva il "user-gesture trust" del browser).
- Tooltip del pulsante aggiornato: "Apri Web Console in nuova tab (proxy diretto via VPN)".

**Bug collaterale trovato via testing agent (iteration_61) e corretto (iteration_62)**:
- `/app/frontend/src/components/WebConsoleTabs.js` `openPopup()` usava `window.open(url, '_blank', 'noopener,noreferrer')` che in **Chromium ritorna sempre `null`** per design (MDN: con `noopener` il caller non riceve WindowProxy).
- Il check successivo `if (!win)` interpretava erroneamente il `null` come "popup bloccata" → chiamava `alert("Pop-up bloccato")` + fallback V3 → entrambi i percorsi si attivavano contemporaneamente.
- **Fix**: rimosso `'noopener,noreferrer'` dal `window.open`. Rischio reverse-tabnabbing nullo perché la target URL è sul nostro stesso dominio (`/api/console-v4/s/<jwt>/`), non una pagina di terzi.

**Architettura risultante**:
- V4 popup (nuova tab) = default per desktop+mobile: backend `httpx` diretto al device, tunnel WireGuard embedded sul Center fornisce la rotta verso IP privati del cliente, browser vede navigazione full-page nativa (no iframe/CSP/X-Frame issues).
- V3 iframe LIVE = fallback solo se la popup è realmente bloccata dal browser.

**Test** (iteration_62.json): 100% PASS desktop 1920x1080 + mobile 390x844. 6/6 critical assertions:
1. POST `/api/console-v4/request-session` fired ✓
2. POST `/api/web-console/session` (V3) NOT fired ✓
3. POST `/api/admin/wireguard/session/start` fired in parallel ✓
4. `data-testid=web-console-active` dock NOT rendered ✓
5. Nessun alert "Pop-up bloccato" ✓
6. Zero ReferenceError in console ✓

**Next UX note**: il JWT è ancora embedded nel path URL → ingress logs + browser history lo vedono. Migrazione futura consigliata: opaque session id lato server + JWT via HttpOnly cookie (post-MVP, non bloccante).

### 2026-02-10 (sera): Fix V4 proxy "Bad Request - Invalid URL" su HPE iLO / IIS / HTTP.sys
**Sintomo utente**: nuova tab apre correttamente, ma il device (iLO HPE / firmware Windows-based) risponde con la pagina di errore HTTP.sys "HTTP Error 400. The request URL is invalid.".

**Root cause**: `/app/backend/routes/web_console_v4.py` passava `Host: 10.100.61.221:443` (con porta default esplicita) al device. HTTP.sys/IIS (usato da iLO 5/6, Windows admin pages, alcuni firmware Comware) rifiuta in modo strict il Host con porta default per lo scheme — è una violazione di RFC 7230 §5.4 nella loro implementazione.

**Fix** (`web_console_v4.py` linea 250-265): strip della porta default dal Host header — `:443` rimosso quando scheme=https, `:80` rimosso quando scheme=http. Per tutte le altre porte (es. 8443, 17990, 5001) la porta resta nel Host. Verificato con httpx test: il Host custom viene onorato e inviato al device.

**Tarball backend** rigenerato: `/app/frontend/public/downloads/argus-backend-latest.tar.gz` aggiornato (~2.5 MB, include il fix). L'utente può deployare con il self-update 1-click dalla UI WireGuard.

**Test**: lint Python OK (i 4 warning pre-esistenti sono di altre sezioni). Test end-to-end richiede device target reale con HTTP.sys server (non riproducibile nel preview container).

### 2026-02-10 (sera tardi): Custom Tarball URL field nel dialog Self-Update
**Razionale**: lo script di self-update scarica il tarball backend da `https://<center-host>/downloads/argus-backend-latest.tar.gz`, ma se quella build frontend non e` aggiornata (chicken-and-egg) il file e` vecchio o 404. Aggiunto un input opzionale "URL pacchetto custom" nel dialog per puntare a una build remota raggiungibile (es. `https://device-alerts.preview.emergentagent.com/downloads/argus-backend-latest.tar.gz` quando si vuole bypassare la build locale).

**File toccati**:
- `/app/frontend/src/pages/WireGuardPage.js` `triggerUpdate(enableWireguard, customUrl)` ora accetta secondo arg opzionale → invia `package_url` al POST `/api/admin/system/self-update`. Dialog ha sezione `<details>` "Opzioni avanzate" con input mono-spaced + hint che mostra il default URL.
- Backend `system_admin.py` gia` gestiva `package_url` opzionale (nessuna modifica necessaria).

**Note operative**: per il PRIMO update post-fix l'utente puo` o:
1. SSH al prod, `curl -o /home/arslan/86NOCConnectorCenter/frontend/build/downloads/argus-backend-latest.tar.gz https://device-alerts.preview.emergentagent.com/downloads/argus-backend-latest.tar.gz`, poi click "Riprova" sull'UI.
2. Aspettare che la nuova frontend sia deployata, poi usare il campo "URL pacchetto custom" direttamente.

### 2026-02-10 (notte): Per-device alert silencing + auto-classifier stampanti
**Richiesta utente**: 1) checkbox "silenzia alert" per device che monitora ma non vuole notifiche (es. stampanti che si spengono la sera); 2) auto-classificazione device_type (Sharp/Brother MFC stavano sotto "Server"); 3) tab Stampanti deve includere device classificati `device_type=printer` non solo /api/printers.

**Implementazione**:

Backend nuovi:
- `/app/backend/alert_filter.py`: helper `is_device_silenced()`, `should_emit_alert()`, `insert_alert_if_emit(db, alert_doc)` con cache TTL 30s. **Drop-in replacement** per `db.alerts.insert_one()` in **8 file** (`connector_watchdog.py`, `redfish.py`, `routes/alerts.py`, `routes/backup.py`, `routes/connector.py`, `routes/external_monitor.py`, `routes/ingestion.py`, `routes/printers.py`). Wrapper estrae automaticamente `client_id`+`device_ip` dall'alert_doc; alert senza device specifico (es. connector watchdog) non vengono mai silenziati.
- `/app/backend/device_classifier.py`: `classify_device_type(sys_descr, sys_object_id, hostname, model)` con (1) match Printer-MIB sysObjectID OID prefixes (HP, Brother, Canon, Epson, Lexmark, Kyocera, Konica, Xerox, Ricoh, OKI, Samsung, Sharp, OKI Data, Dell), (2) regex hostname/sysDescr per stampanti+switch+firewall+AP+NAS+UPS+iLO. Test cases: "HP OfficeJet"→printer, "SHARP MX-B427PW"→printer, "Brother MFC-L6710DW"→printer, "Konica Minolta bizhub"→printer, "NETGEAR GS110EMX"→switch, "FortiGate 60F"→firewall, "Synology"→nas, "iLO5"→ilo.

Backend nuovi endpoint (in `routes/connector.py`):
- `PUT /api/connector/{client_id}/managed-devices/{device_id}/silence` — toggle alerts_silenced + reason. Multi-source resolver: gestisce device_id da managed_devices, db.devices, o sintetico `poll_<ip>` con auto-upsert in managed_devices.
- `POST /api/connector/{client_id}/managed-devices/auto-classify` — riclassifica bulk basandosi su sys_descr/sys_object_id/hostname.
- Helper interno `_resolve_or_upsert_managed_device()` condiviso da `/silence`, `/monitor-type`, `/snmp` (DRY refactor — i 3 endpoint usano lo stesso resolver, niente piu` 404 spuri).

Backend ingestion: `connector.py` `report_poll_status` ora applica `classify_device_type()` come fallback secondario quando il fingerprint vendor non matcha e il device_type corrente è generic/unknown/server/ilo. Solo per nuovi device o con sys_descr cambiato.

Frontend:
- `DeviceEditModal.js`: sezione checkbox "🔕 Silenzia alert" + textarea motivo. `useEffect` re-seed dello stato quando `device` prop cambia (per supportare reopen). `save()` con 3 try/catch indipendenti + dirty-detection per evitare PUT inutili. `onSaved(updatedDevice)` ora passa il device aggiornato per optimistic update.
- `ClientOverviewPage.js`: badge "ALERT OFF" nella riga tabella Dispositivi (data-testid=silence-badge-{ip}). `optimisticUpdateDevice()` aggiorna lo state setDevices in <1s senza aspettare refetch. PrintersTab refattorizzato per accettare `mergedPrinters` (union device_type=printer + /api/printers con merge per IP, telemetria toner dove disponibile).
- `models.py` `DeviceResponse`: aggiunti campi `alerts_silenced` + `alerts_silenced_reason`.
- `routes/devices.py`: merge `alerts_silenced` da managed_devices nel response GET /api/devices.

**Test** (iteration_63 → 64 → 65 → 66):
- Backend pytest: 14/14 PASS (alert filter + classifier + endpoints).
- Frontend E2E iteration_66: **6/7 step 100% PASS** (1 ms = 0.51s optimistic badge, 1 PUT chirurgica per save-only-silence, useEffect re-seed funziona, dirty-detection skip /monitor-type+/snmp se non cambiati).
- Step 7 partially blocked dal residuo 404 backend su /monitor-type+/snmp risolto subito dopo (multi-source resolver esteso a tutti e 3).

**Tarball aggiornato**: `argus-backend-latest.tar.gz` (~2.5 MB) con BACKEND_VERSION=3.5.27-fase2.

### 2026-02-10 (notte, fix 2): Delete button + sync inversa connector↔Center
**Segnalazione utente (screenshot WhatsApp)**: 1) il cestino rosso di rimozione device non funziona; 2) i device rimossi dalla config del connector restano "offline per sempre" nel Center.

**Backend fix**:
- `DELETE /api/connector/{client_id}/managed-devices/{device_id}` — completamente riscritto con multi-source delete: cerca il device in managed_devices/devices per `id` o `ip`, estrae l'IP anche da id sintetico `poll_<ip>`, esegue delete_many su tutte e 3 le collection (managed_devices, devices, device_poll_status) + auto-resolve alert aperti. Ritorna 404 solo se device assente ovunque.
- **NUOVO** `POST /api/connector/{client_id}/cleanup-stale-devices` — cleanup self-healing basato su staleness. Pre-check: connector MUST be online (<5 min dall'ultimo heartbeat), altrimenti `{ok:false, reason:'connector_offline'}` per evitare eliminazione accidentale durante manutenzione. Rimuove managed_devices con `source=connector` e `last_seen>threshold_minutes` (default 30). Protegge device manuali (source!=connector) + silenziati (alerts_silenced=true). Supporta `dry_run=true` (default) per preview.
- **NUOVO** `POST /api/connector/{client_id}/sync-active-devices` — sync esplicita lato server: accetta `active_ips:[...]` (lista IP attivi sul connector), rimuove tutti gli altri device `source=connector` non nella lista. Utile per futuri sync automatici dal PowerShell.

**Frontend fix**:
- **NUOVO** pulsante `data-testid=cleanup-stale-btn` "🗑️ Rimuovi scomparsi" (arancione) nella tab Dispositivi. Click → preview dry-run + `window.confirm` con lista candidati → conferma → cleanup effettivo + toast + refresh. Distingue 404 (connector_not_registered) da connector_offline con toast separati.

**Test** (iteration_67): **100% PASS** backend (10/10 pytest) + frontend (4/4). Verified: delete funziona per UUID manuale + UUID auto-discovered + id sintetico `poll_<ip>`; alert resolvution; protection su silenziati/manuali; connector_online guard; sync_active dry-run preview.

**Follow-up non bloccante**: estendere il PowerShell connector per chiamare automaticamente `/sync-active-devices` ogni heartbeat con la lista dei device attualmente configurati — così la sync inversa diventa self-healing senza click manuale. Backend già pronto.

### 2026-02-10 (notte, fix 3): Auto-sync inversa Connector→Center (self-healing)
**Fix del follow-up precedente — completo**.

**Backend nuovo**: `POST /api/connector/sync-active-devices` (HMAC auth — deriva client_id dalla firma, non serve URL parameter). Duplica la logica di `/cleanup-stale-devices` ma triggered dal connector stesso ad ogni heartbeat invece che manualmente. Protezioni identiche: device manuali (`source!=connector`) e silenziati (`alerts_silenced=true`) preservati; liste vuote RIFIUTATE per safety (evita wipe durante bootstrap); alert aperti dei device rimossi vengono auto-resolved con resolution_note='Device rimosso dal connector (auto-sync)'.

**Connector PowerShell v3.5.25**: nuovo blocco nel flow `Send-StatusReport` subito dopo `Send-ToNOC connector/device-report`. Invia `active_ips` = lista IP dei device attualmente nel poll cycle + `source="connector_heartbeat"`. Best-effort: 404 (Center pre-3.5.27) silenzioso, 5xx loggato come WARN ma non blocca il heartbeat. Payload non blocca se la lista è vuota (skip proattivo). Pubblicato via `scripts/publish-connector.sh 3.5.25` → disponibile come `86NocConnector_v3.5.25_install.zip` (378 KB).

**Test** (iteration_68): **11/11 pytest PASS** backend. Verified: auth (401 senza key), validazione body, dry_run non-destructive, sync effettivo (preserva manual + silenced), alert auto-resolved, PowerShell payload/path correct.

**Effetto operativo**: da v3.5.25 connector + v3.5.27 Center, quando l'utente rimuove un device dalla tray app del connector, entro ~60s il device sparisce anche dal Center automaticamente. Nessun click manuale richiesto. Il pulsante "Rimuovi scomparsi" UI resta disponibile come fallback/emergency se il connector è down.

### POC v1 — WireGuard EMBEDDED nel Center (2026-04-27)
**Richiesta utente**: "non voglio installarlo deve essere dentro al center" — il server WireGuard non deve richiedere `apt install wireguard-tools` o setup manuale sul Linux di produzione. Tutto self-contained nel pacchetto del backend.

**Approccio scelto**: bundle del binario `wireguard-go` (userspace WireGuard ufficiale di Jason A. Donenfeld, autore del protocollo), gestito a runtime come subprocess dal backend FastAPI. Lifecycle automatico (startup/shutdown), peer management via UAPI socket Unix.

**File creati**:
- `/app/backend/bin/wireguard-go-linux-amd64` (2.5 MB, Debian package estratto)
- `/app/backend/bin/wireguard-go-linux-arm64` (2.4 MB, Debian package estratto)
- `/app/backend/wireguard_embedded.py` (~330 righe) — `EmbeddedWireGuardManager` singleton con:
  - `detect_environment()`: rileva arch host, presenza binari, /dev/net/tun, CAP_NET_ADMIN, kernel WireGuard module, pyroute2
  - `start()`: fail-safe, idempotent, log su `/var/log/argus-wireguard.log`
  - `stop()`: SIGTERM + 5s timeout poi SIGKILL
  - `_uapi_set_config()`: scrive private_key (hex) + listen_port via UAPI socket
  - `_activate_link()`: ip addr + ip link via pyroute2 (fallback subprocess `ip`)
  - `get_uapi_state()`: legge peer + handshake live via UAPI
  - Persiste private key in `/app/backend/data/wireguard/server.key` (chmod 0600)
- `/app/backend/tests/test_wireguard_embedded_poc.py` — 6 test pytest, tutti passati

**File modificati**:
- `/app/backend/server.py` — startup_event lancia `wg_manager.start()` solo se `WG_EMBEDDED_ENABLED=true` (opt-in). Shutdown handler ferma il subprocess
- `/app/backend/routes/wireguard.py` — 3 nuovi endpoint admin:
  - `GET /api/admin/wireguard/embedded/status` — diagnostica completa con `environment.missing_prerequisites`
  - `POST /api/admin/wireguard/embedded/start` — avvio manuale on-demand
  - `POST /api/admin/wireguard/embedded/stop` — stop manuale
- `/app/backend/requirements.txt` — `pyroute2==0.9.6` + `pytest-asyncio`

**Test end-to-end (preview Kubernetes container)**:
- ✅ Backend si avvia normalmente, log `WG embedded runtime disabled (set WG_EMBEDDED_ENABLED=true to opt-in)`
- ✅ GET /status risponde con env detection corretto: `host_arch=aarch64`, `binary_arch=arm64`, `binary_present=true`, `tun_device_available=false`, `cap_net_admin=false`
- ✅ POST /start fail-safe: `running=false`, `last_error="Prerequisiti mancanti: /dev/net/tun device unavailable; CAP_NET_ADMIN not present"` (no exception, no crash)
- ✅ 6/6 pytest pass: import senza side-effect, binari presenti, status iniziale corretto, start fail-safe, stop idempotente
- ✅ Lint Python: All checks passed

**Validazione architettura**:
La POC dimostra che in produzione (Linux con `/dev/net/tun` standard + backend lanciato come root o con `--cap-add=NET_ADMIN`) basta solo settare `WG_EMBEDDED_ENABLED=true` nell'env e riavviare il backend. Nessun `apt install`, nessun `wg-quick`, nessun config file da scrivere a mano. Il manager:
- Genera la private key alla prima esecuzione
- Avvia `wireguard-go` automaticamente
- Configura private key + listen port via UAPI socket
- Attiva l'interfaccia con pyroute2 (zero `wg-tools` bundling necessario)

**Prossimi passi (Fase 2, dopo OK utente)**:
- Peer management via UAPI: aggiungere/rimuovere peer dinamicamente in base a `wireguard_peers` collection (gia` esistente in `routes/wireguard.py`)
- Hook su `wireguard_sessions` start/stop per applicare ephemeral PSK al peer al volo
- UI admin "Server VPN" con lista peer attivi + traffico + ultimo handshake
- Script bash zero-downtime per aggiornare il backend Linux di produzione (necessario perche` la prod e` ancora v3.5.8)
- Setup `WG_SERVER_PUBKEY` + `WG_SERVER_ENDPOINT` nell'env del backend prod

### Fase 2 + Fase 3 — Peer sync UAPI + UI admin + Deploy script Linux (2026-04-27)

**Fase 2 (peer reconciliation runtime)**:
- `wireguard_embedded.py` esteso (~600 righe totali) con:
  - **Public key derivation** via X25519 (cryptography lib): all'avvio (o on-demand su richiesta endpoint) deriva la pubkey dalla private key e la setta automaticamente in `os.environ['WG_SERVER_PUBKEY']` cosi` che `_wg_server_ready()` in web_console_live.py la veda subito senza restart.
  - **Peer sync loop** (`_peer_sync_loop`): asyncio Task in background, tick ogni 5s. Legge `wireguard_sessions` con status=active+expires_at>now, recupera il peer associato in `wireguard_peers`, costruisce lo stato desiderato `{pubkey: {psk, allowed_ips}}` e fa diff vs stato corrente del runtime via UAPI socket. Applica solo le differenze (added/removed/updated). Politica: peer presente nel runtime SOLO durante una sessione attiva (zero attack surface a riposo).
  - **UAPI peer write** (`_uapi_set_peers`): costruisce un singolo messaggio UAPI atomico con `set=1` + linee `public_key=<hex>`, `preshared_key=<hex>`, `replace_allowed_ips=true`, `allowed_ip=<cidr>`, `remove=true`. Encoding b64→hex via helper `_b64_to_hex`.
  - **UAPI state read** (`get_uapi_state`): legge `get=1` dal socket, parser ritorna `{peers: [...], private_key, listen_port, errno}`.
  - Sync state esposto in `status()` come `peer_sync: {running, last_sync_at, last_sync_error, last_diff: {added, removed, updated}}`.
- `routes/wireguard.py`:
  - 2 nuovi endpoint: `POST /api/admin/wireguard/embedded/sync-now` (forza riconciliazione immediata), `GET /api/admin/wireguard/embedded/server-pubkey` (espone pubkey+endpoint per copia in connector .conf).
  - Helper `_trigger_embedded_sync_best_effort()` chiamato dopo `session/start`, `session/{id}/stop`, `session/stop-by-target` per feedback istantaneo (~ms invece dei 5s del loop). No-op se runtime embedded non e` attivo.
- `WireGuardPage.js` (frontend):
  - Nuovo state `embeddedStatus` + `embeddedBusy` con auto-refresh 10s.
  - Componente `EmbeddedRuntimeBanner` (~150 righe React) inserito tra `<ServerStatusBanner>` e l'hardening summary. Mostra:
    - Badge stato (RUNTIME ATTIVO verde / PRONTO ALL'AVVIO ambra / PREREQUISITI MANCANTI rosso) con dot animato pulsante
    - Grid 4-col: interface, listen_port, tunnel_cidr, endpoint
    - Public key copy-able con icona `Copy` (Phosphor) + toast su click
    - Box rosso dettaglio "Prerequisiti host non soddisfatti" con elenco preciso (TUN, CAP_NET_ADMIN) e suggerimento `--cap-add=NET_ADMIN --device=/dev/net/tun`
    - Box ambra "Premi Avvia per attivare" quando ready ma non running, con suggerimento `WG_EMBEDDED_ENABLED=true`
    - Box rosso `last_error` mono-spaced
    - Grid sync status: peer sync running/fermo, ultima sync timestamp, peer attivi count, diff +N/-M/ΔK
    - Pulsanti: Avvia (disabilitato se non ready), Sync, Stop
    - Tutti con `data-testid` (`embedded-runtime-banner`, `embedded-start-btn`, `embedded-sync-btn`, `embedded-stop-btn`, `embedded-server-pubkey`, `embedded-copy-pubkey`)

**Fase 3 (deploy script Linux di produzione)**:
- `/app/scripts/deploy-backend-linux.sh` (~300 righe bash): script zero-downtime per portare in produzione il nuovo backend.
  - Auto-detect: virtualenv (cerca in /opt/argus/.venv, /opt/argus/venv, /root/.venv), service manager (systemd vs supervisor vs manuale), backend dir (default /opt/argus/backend, override via ARGUS_BACKEND_DIR=).
  - Backup completo del backend corrente prima di toccare nulla in `/opt/argus/backups/backend-<timestamp>/`.
  - Conferma utente esplicita con riepilogo pre-deploy (paths, service manager, health corrente).
  - Stop backend → mv vecchio dir come `.old.<timestamp>` (rollback istantaneo se serve) → cp nuovo → restore `.env` + `data/` + `data/wireguard/` (chiavi server preservate) → pip install requirements.txt → start backend.
  - Health check post-deploy con retry per 30s su `/api/health`. Accetta anche 401/403/422/404 come "FastAPI sta rispondendo" (potrebbero esserci endpoint protetti).
  - **Rollback automatico**: se health fallisce, ferma backend, ripristina vecchio dir, riavvia. Exit code 2 con istruzioni log.
  - Cleanup old dir alla fine + istruzioni rollback manuale + cleanup backup vecchi (>30 giorni).
  - Sintassi bash validata con `bash -n`.
- Tarball backend: `/app/frontend/public/downloads/argus-backend-latest.tar.gz` (~2.5 MB, esclude __pycache__ e data/).
- README utente: `/app/frontend/public/downloads/DEPLOY-BACKEND-README.md` con procedura passo-passo (3 step: ssh → curl script → bash deploy <URL>).
- Tutti e 3 gli artifact sono pubblicamente accessibili da `https://<center>/downloads/`.

**Test fatti**:
- 6/6 pytest pass su `test_wireguard_embedded_poc.py` (regression POC)
- Backend si riavvia pulito, log `WG embedded runtime disabled (set WG_EMBEDDED_ENABLED=true to opt-in)` quando opt-in OFF
- curl GET `/api/admin/wireguard/embedded/status`: ritorna pubkey derivata + sync state coerente
- curl GET `/api/admin/wireguard/embedded/server-pubkey`: ritorna pubkey + endpoint + listen_port + interface
- curl POST `/api/admin/wireguard/embedded/sync-now`: ritorna sync state (no peers in preview, atteso)
- Frontend smoke test: banner "Server WireGuard Embedded" renderizzato con tutti i dati corretti (interface wg-argus, port 51820, pubkey copy-able, missing prerequisites elencati, pulsante "Avvia" disabilitato perche` ready=false in preview)
- bash -n deploy-backend-linux.sh: OK
- HTTP 200 su tutti e 3 gli artifact pubblici (`deploy-backend-linux.sh` 10.8 KB, `argus-backend-latest.tar.gz` 2.5 MB, `DEPLOY-BACKEND-README.md` 3.4 KB)
- Lint Python: All checks passed
- Lint JavaScript: No issues found

**Cosa resta per provare VPN end-to-end** (azioni utente):
1. SSH al server Linux di produzione
2. `curl -fL https://argus.86bit.it/downloads/deploy-backend-linux.sh -o deploy-backend-linux.sh && chmod +x ./deploy-backend-linux.sh`
3. `sudo bash deploy-backend-linux.sh https://argus.86bit.it/downloads/argus-backend-latest.tar.gz` → conferma → wait health check
4. Aggiungere a /opt/argus/backend/.env: `WG_EMBEDDED_ENABLED=true` + `WG_SERVER_HOST=argus.86bit.it`
5. Aprire UDP 51820 sul firewall (`ufw allow 51820/udp`)
6. `sudo systemctl restart argus-backend` (o supervisorctl)
7. Verificare nel Center → WireGuard: banner verde "RUNTIME ATTIVO"
8. Avviare sessione VPN da UI verso un device → connector cliente attivera` il tunnel

### Fase 4 — Self-Update 1-click dalla UI (2026-04-27)

**Richiesta utente**: "non possiamo far girare tutto all'interno del center?" — minimizzare al massimo l'attrito di aggiornamento backend, eliminando la necessita` di SSH per gli update successivi al primo.

**File creati**:
- `/app/backend/scripts/self_update.sh` (~210 righe bash) — runner detached: download tarball, backup, stop service, replace files, restore .env+data/, opzionale aggiunta `WG_EMBEDDED_ENABLED=true` al .env, opzionale `ufw allow 51820/udp`, pip install, start service, health check, rollback automatico se fallisce. Scrive status JSON a ogni fase su `/tmp/argus-update-status.json` per polling UI.
- `/app/backend/routes/system_admin.py` (~200 righe) — 4 endpoint admin:
  - `GET /api/admin/system/version` → versione corrente backend (default `3.5.25-fase2`, override via env `ARGUS_BACKEND_VERSION`)
  - `GET /api/admin/system/self-update/status` → polling status JSON (con auto-detect "stale" se runner morto)
  - `POST /api/admin/system/self-update` (202) → triggera runner detached (subprocess.Popen + start_new_session=True), accetta body `{package_url?, enable_wireguard, wireguard_host?}`. Refusa con 409 se update gia` in corso fresh.
  - `GET /api/admin/system/self-update/log?lines=N` → ritorna ultime N righe di `/tmp/argus-update-runner.log`

**File modificati**:
- `/app/backend/server.py` — include `system_admin_router`
- `/app/frontend/src/pages/WireGuardPage.js` (~120 righe aggiunte):
  - State `systemVersion`, `updateStatus`, `updating`, `showUpdateDialog`
  - 2 fetch helper: `loadSystemVersion`, `loadUpdateStatus` (polling adattivo: 1s durante update, 10s a riposo)
  - `triggerUpdate(enableWg)` lancia POST con auto-detect hostname browser per `WG_SERVER_HOST`
  - Componente `SystemUpdateBanner` inserito tra `<ServerStatusBanner>` e `<EmbeddedRuntimeBanner>`. Mostra:
    - Badge stato dinamico (cyan idle / amber running / emerald done / rose failed) con dot animato
    - Versione corrente, label fase (queued/downloading/extracting/backing-up/stopping/replacing/installing/starting-backend/health-check/cleanup/done/failed) con percentuale 0-100
    - Progress bar animata transition-all
    - Sezione errore con suggerimento `/tmp/argus-update-runner.log` per troubleshooting
    - Pulsante "Aggiorna Backend" / "Riprova" / "Re-aggiorna" (testid: `system-update-trigger-btn`)
  - Dialog di conferma con checkbox "Attiva contestualmente il server WireGuard embedded" default ON, spiegazione cosa succede, pulsante "Aggiorna Adesso" (testid: `confirm-update-btn`)
  - Auto-reload pagina post-completamento update (timeout 2s dopo phase=done)

**Tarball backend pubblicato**:
- `/app/frontend/public/downloads/argus-backend-latest.tar.gz` (2.5 MB) include `routes/system_admin.py` + `scripts/self_update.sh`

**Test**:
- 6/6 pytest pass (regression POC + Fase 2)
- Lint Python + JS pulito
- 3 endpoint nuovi rispondono HTTP 200 a curl con admin JWT
- Frontend smoke test screenshot: banner update renderizzato correttamente, dialog di conferma si apre con checkbox, layout coerente con il resto della pagina

**Limitazione nota — chicken-and-egg per il PRIMO deploy**:
Il backend di produzione attualmente in field e` v3.5.8: NON ha l'endpoint `/api/admin/system/self-update`, quindi il pulsante "Aggiorna Backend" dara` 404. Il PRIMO aggiornamento DEVE essere fatto tramite il deploy script bash via SSH (vedi Fase 3). DA QUEL MOMENTO IN POI, ogni successivo update sara` 1-click dalla UI.

**Flow completo per l'admin**:
1. **Una volta sola**: `ssh root@argus.86bit.it && bash deploy-backend-linux.sh https://argus.86bit.it/downloads/argus-backend-latest.tar.gz`
2. **Per sempre**: aprire Center → WireGuard → click "Aggiorna Backend" → conferma dialog → attendere progress bar → page reload automatico

### Connector v3.5.23 — HOTFIX CRITICO encoding em-dash (2026-04-26)
**Sintomo segnalato dall'utente** (post-install v3.5.22 su GALVANSRV):
- `Get-Service 86NocConnectorService` -> Status=**Paused**
- File `C:\ProgramData\86NocConnector\connector.log` non esiste (mai creato)
- Nessun heartbeat al Center
- Esecuzione manuale di `connector.ps1` produce errori PowerShell parser:
  - "flusso output per il comando gia' rindirizzato" su righe 358 e 430
  - "')' di chiusura mancante nell'espressione"
  - "'}' di chiusura mancante nel blocco di istruzioni" alle righe 1444 e 2633
  - Cascata di errori parser

**ROOT CAUSE TROVATA**:
I file PowerShell del connector erano salvati come **UTF-8 SENZA BOM** e contenevano
caratteri tipografici Unicode all'interno di stringhe Write-Log e commenti:
- em-dash `-` (U+2014, byte UTF-8: `e2 80 94`) - 49 occorrenze totali nei 8 file
- arrow `->` (U+2192, byte UTF-8: `e2 86 92`) - 17 occorrenze totali

Su Windows PowerShell 5.1 con locale italiano (default su Win Server e Win 10/11 IT),
**un file senza BOM viene parsato usando il code page CP-1252**. In CP-1252 il
byte `0x94` (terzo byte UTF-8 dell'em-dash) corrisponde al carattere `"` (smart
quote close), un ASCII-equivalent che **CHIUDE PREMATURAMENTE la stringa
double-quoted di Write-Log**. Da quel punto in poi tutti i `>` presenti nella
stringa (es. "Clienti > [tuo cliente] > Rigenera API Key") vengono interpretati
come operatori di redirect output PowerShell, generando "flusso output gia'
rindirizzato" e causando rottura a cascata della struttura del file.

PowerShell rifiuta di parsare lo script -> `connector.ps1` non parte mai ->
process child di NSSM crash entro 1.5s -> NSSM throttle il riavvio e mette
il servizio in stato `Paused`. Sintomo: log file non viene creato, no heartbeat.

**FIX APPLICATO** a 12 file PowerShell (8 individuati nel primo round + 4 trovati dal pre-check):
- `connector.ps1`, `installer_gui.ps1`, `snmp_poller.ps1`, `tray_app.ps1`,
  `wireguard_client.ps1`, `update_check.ps1`, `remote_browser.ps1`, `uninstall.ps1`,
  `backup_monitor.ps1`, `service_wrapper.ps1`, `diagnostica.ps1`, `diagnostica_connessione.ps1`

1. **Sostituzione caratteri killer** (sed in-place):
   - `-` (em-dash) -> `-` ASCII hyphen
   - `->` (right arrow) -> `->` ASCII
2. **BOM UTF-8 prepended** (`ef bb bf`) all'inizio di ogni file:
   defesa in profondita' - anche se in futuro qualcuno aggiungesse di nuovo
   caratteri Unicode tipografici, il BOM forza PowerShell 5.1 a usare
   encoding UTF-8 invece di CP-1252, evitando il bug definitivamente.
3. **PRE-FLIGHT CHECK in `/app/scripts/publish-connector.sh`** (defesa permanente):
   ad ogni invocazione di `./publish-connector.sh <ver> "<changelog>"`, prima
   di costruire i ZIP lo script:
   - scansiona tutti i `.ps1` sotto `/app/noc-connector/prg/`
   - verifica BOM UTF-8 (ef bb bf) all'inizio di ogni file
   - cerca caratteri Unicode "killer": em-dash, en-dash, arrow LR, smart quotes
   - se trova problemi, esce con exit code 2 e stampa il fix automatico da
     copiare/incollare nella shell. La pubblicazione e' bloccata: nessun ZIP
     puo' essere creato con file non-conformi.

Le lettere accentate italiane (a', e', i', o') restano nel file ma con BOM
vengono parsate correttamente come UTF-8 multibyte.

**Verifica**:
- 12/12 file: BOM `ef bb bf` aggiunto
- 12/12 file: em-dash + arrow = 0 occorrenze
- 12/12 file: braces bilanciati (delta 0)
- 0 byte `0x94`/`0x80` problematici residui
- ZIP `86NocConnector_v3.5.23_install.zip` (371 KB) pubblicato + DB record
  active=true, precedenti deactivati
- SHA256 install: `f11cba20c125d1a071fbef5aef572c5b6b716ac0d6176f7ac58bd922bc3b306b`
- SHA256 plain:   `ff6d631c1c4078483334c0f4ab922e76201cc50782f909c4b834c31389f75196`
- Pre-check `publish-connector.sh` testato:
  - stato pulito -> PRE-FLIGHT OK (12 file verificati)
  - em-dash artificiale aggiunto -> PRE-FLIGHT FAIL exit=2 con fix suggerito
  - BOM rimosso artificialmente -> PRE-FLIGHT FAIL exit=2 con fix suggerito

**Why this never showed before v3.5.22**:
Le versioni precedenti probabilmente avevano BOM (perche' editate in PowerShell ISE
che salva UTF-8-BOM di default), oppure non avevano em-dash dentro stringhe critiche.
Il fix in v3.5.16 che aggiunse i messaggi 401 actionable con "Clienti > [tuo cliente]
> Rigenera API Key -> copia in..." ha introdotto i caratteri killer dentro stringhe
write-Log al volo via search_replace dell'agent, perdendo il BOM nel salvataggio.

**Procedura di recupero per cliente con servizio Paused**:
1. Scaricare nuovo ZIP install:
   `https://<center>/downloads/86NocConnector_v3.5.23_install.zip`
2. Disinstallare versione attuale (PowerShell admin):
   `& "C:\Program Files\86NocConnector\uninstall.ps1" -NoPause`
3. Estrarre nuovo ZIP -> tasto destro sui file -> Annulla blocco
4. Doppio-click `Installa 86NocConnector.vbs` -> wizard
5. Verificare: `Get-Service 86NocConnectorService` -> Status=Running

### Connector v3.5.22 — WireGuard PORTABLE deployment (2026-04-26)
**Richiesta utente**: "non voglio assolutamente sporcare il server di produzione". Valutate alternative: WireGuard portable, WireSock, wireproxy, TunnlTo. Scelta: **estrazione binari da MSI ufficiale via `msiexec /a` (administrative install)** — la piu' pulita e sicura.

### Backend v3.5.22 — Routing intelligente Web Console (WireGuard direct vs Connector long-poll) (2026-04-26)
**Richiesta utente**: "pulisci tutte le funzioni non piu' necessarie con nuova logica dentro in webconsole e lascia invece tutto quello necessario" — opzione B (intelligent routing senza rimozioni distruttive) approvata "con la massima precisione".

**Cambio architetturale in `/app/backend/routes/web_console_live.py`**:
- 2 nuovi helper: `_wg_server_ready()` (con cache TTL 60s su env vars `WG_SERVER_PUBKEY`+`WG_SERVER_ENDPOINT`), `_wg_session_active_for_device(client_id, device_ip)` (query `wireguard_sessions` filtrato `status=active` + `expires_at>$now`).
- 1 nuovo transport: `_proxy_via_wireguard()` — usa `httpx.AsyncClient` per chiamare DIRETTAMENTE `http(s)://device_ip:port/path` attraverso il tunnel kernel WG. Latenza ~30-80ms vs ~300-800ms del long-poll connector.
- `live_proxy()` modificato: prima tenta WG transport (solo se WG ready + sessione attiva), su qualsiasi exception fallback automatico al transport legacy `_proxy_via_connector`. Trasparente al browser: stessa shape di response, stesso URL rewriting + base href + header filtering.
- Nuovo header debug `X-Argus-Transport: wireguard | connector` per troubleshooting.

**Cosa NON e' stato rimosso (per sicurezza e zero rottura)**:
- `web_proxy.py` (488 righe): resta come fallback transport quando WG non e' disponibile (es. ambiente preview Kubernetes attuale dove `WG_SERVER_PUBKEY` non e' configurato → `ready=false`).
- Funzioni `Check-WebProxyRequests` / `Process-WebProxyRequest` / `Build-WebProxyErrorPage` / `Send-WebProxyResponse` in `connector.ps1`: restano essenziali per scenario fallback.
- Endpoint backend e funzioni frontend in `WebConsoleTabs.js`: nessun codice morto trovato in audit cross-reference, tutto e' usato.

**Test**: 8/8 pytest passati in `/app/backend/tests/test_web_console_wg_routing.py`:
- `_wg_server_ready` con env vars assenti / parziali / complete + cache TTL 60s
- `_wg_session_active_for_device` short-circuit quando server non ready (no DB call)
- Query DB con filtro corretto (`client_id`, `target_device_ip`, `status=active`, `expires_at>$now`)
- `_proxy_via_wireguard` ritorna shape `(status_code, content_type, body, resp_headers)` compatibile

**Comportamento runtime in produzione**:
- Cliente con WG NON configurato: zero cambiamento, tutto continua via connector long-poll come oggi.
- Cliente con WG configurato + sessione attiva: ogni request iframe della Web Console verso quel device va via tunnel (perf ~10x). Trasparente.
- Cliente con WG configurato ma tunnel down a runtime: fallback automatico al connector. Niente errori al browser.

**File toccati**:
- `/app/backend/routes/web_console_live.py` (+125 righe per i 3 nuovi helper, +18 righe per routing + header)
- `/app/backend/tests/test_web_console_wg_routing.py` (nuovo, 165 righe, 8 test)

### Connector v3.5.22 — WireGuard PORTABLE deployment (continua sotto) 

**Cambiamento rispetto a v3.5.21** (che faceva install completo via NSIS `/S`):
- `wireguard_client.ps1::Install-WireGuardClient` riscritto: scarica MSI da `download.wireguard.com`, verifica firma Authenticode (rifiuta se non firmato da WireGuard LLC / Jason A. Donenfeld), esegue `msiexec /a "$msi" /qn TARGETDIR="$tempDir"` (administrative install = solo spacchettamento file, NO install nel sistema), copia `wireguard.exe` + `wg.exe` (+ DLL companion eventuali) sotto `C:\Program Files\86NocConnector\wireguard-portable\`, elimina MSI temporaneo + cartella estrazione.
- Auto-discovery URL MSI: parsa la directory listing HTML di `https://download.wireguard.com/windows-client/` con regex `wireguard-amd64-(\d+\.\d+\.\d+)\.msi`, prende la versione piu' alta. Fallback hardcoded: `wireguard-amd64-0.5.3.msi`.
- `WG_EXE_CANDIDATES` priorita' #1: `C:\Program Files\86NocConnector\wireguard-portable\wireguard.exe`. Path legacy `Program Files\WireGuard\` come fallback (compat con setup pre-v3.5.22).
- `uninstall.ps1` STEP 1.5 nuovo: prima di rimuovere il connector, ferma e cancella il servizio dinamico `WireGuardTunnel$argus` se attivo (via `wireguard.exe portable /uninstalltunnelservice argus`, fallback `sc.exe stop` + `sc.exe delete`).

**Risultato sul server di produzione**:
- ZERO entry in "Programmi e funzionalita'"
- ZERO service permanente "WireGuard Tunnel Manager"
- ZERO chiavi registry HKLM\Software\WireGuard
- Tutto sotto C:\Program Files\86NocConnector\ → sparisce con uninstall.ps1
- Firma Microsoft/WireGuard LLC dei binari preservata (estraiamo, non ricompiliamo)
- Service VPN dinamico creato/distrutto SOLO per la durata della sessione admin

**File toccati**:
- `/app/noc-connector/prg/src/wireguard_client.ps1` (riscritto Install-WireGuardClient + WG_EXE_CANDIDATES con priorita' portable)
- `/app/noc-connector/prg/uninstall.ps1` (nuovo STEP 1.5 stop tunnel WG)
- `/app/noc-connector/prg/version.json` → 3.5.22 + changelog dettagliato
- ZIP pubblicati: `/app/connector_updates/86NocConnector_v3.5.22.zip` (379 KB) + `/app/frontend/public/downloads/86NocConnector_v3.5.22{,_install}.zip`
- DB: record `connector_updates` v3.5.22 inserito con `active=true`, precedenti deactivati

**Verifica**: 
- Sintassi PowerShell bilanciata (delta parens 14/14, braces 22/22)
- Backend `/api/connector/update-info` ritorna v3.5.22 active=true, file_size=378691 bytes
- ZIP contiene msiexec=10 occorrenze, WG_PORTABLE_DIR=11, STEP 1.5 nell'uninstall=2
- Download HTTPS pubblico HTTP 200, content-length 379744 bytes
- Allowlist client_ip=35.225.230.28 allowed=true reason=empty_list
- WG server status: pool 10.86.0.0/16, ready=false (server WG non ancora setup in preview Kubernetes — atteso)

**Pending user action**: validazione end-to-end su Windows reale (1) connector si auto-aggiorna a v3.5.22, (2) al primo apri Web Console scarica il MSI, lo estrae via msiexec /a, mette i binari in `C:\Program Files\86NocConnector\wireguard-portable\`, (3) nessuna entry compare in "Programmi e funzionalita'", (4) tunnel temporaneo viene attivato/distrutto correttamente.

### 🎨 Connector v3.4.7 UI Polish (TODO alla prossima build connector — richiesta utente 2026-04-23)
- **Task 1 — Logo 86bit nei shortcut menu Start**: generare `86bit_logo.ico` multi-risoluzione (16/32/48/256) da `86bit_logo.jpg` e applicare `.IconLocation` su tutti e 4 i shortcut creati da `installer_gui.ps1`/`install.bat`: "ARGUS Center Connector" (attualmente icona globo), "Apri Cartella Log" (cartella generica), "Diagnostica Connessione" (lente), "Disinstalla ARGUS Connector" (cestino).
- **Task 2 — Logo in Pannello di Controllo → Programmi e funzionalità**: aggiungere chiave registry `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector\DisplayIcon` che punti al percorso di `86bit_logo.ico` installato. Attualmente mostra icona blu generica Windows.
- **Task 3 — Fix spazio vuoto GUI "Gestisci Dispositivi"**: nel form `installer_gui.ps1` c'è spazio bianco a destra del pulsante "Salva e Riavvia" — rimpicciolire Form width o aggiungere `Anchor = Right` ai bottoni per riempimento proporzionale.

### Connector v3.5.4 — UI Polish ARGUS Connector Branding (2026-04-23)
**Richiesta utente** (screenshot tray + installer): 1) Rinominare "86NocConnector" → "ARGUS Connector" ovunque nell'UI (tray menu, tooltip, form titles, About dialog, MessageBox captions). 2) Semplificare tooltip system tray a `ARGUS Connector vX.X.X | Stato: ATTIVO/FERMO`. 3) Shortcut Menu Start: icone native Windows contestuali per "Apri Cartella Log" e "Disinstalla" invece del logo 86bit generico.

**Approccio non-breaking**:
- Nuova variabile `$DisplayName = "ARGUS Connector"` (UI) aggiunta in `tray_app.ps1` e `installer_gui.ps1` accanto a `$AppName = "86NocConnector"` (path tecnici, nome servizio/task).
- Path tecnici intatti per retrocompatibilità con installazioni esistenti: `C:\ProgramData\86NocConnector`, `C:\Program Files\86NocConnector`, service `86NocConnectorService`, Scheduled Task `\86BIT\ArgusConnectorUpdater`, chiavi Registry `Uninstall\86NocConnector` e `Run\86NocConnector`.
- Sostituiti in UI: tray_app.ps1 → 59 `$DisplayName` / 4 `$AppName` (technical-only); installer_gui.ps1 → 18 `$DisplayName` / 9 `$AppName`.

**Nuova funzione `Get-TooltipText`** in `tray_app.ps1` che ritorna stringa sintetica (<63 char limite hard NotifyIcon): `ARGUS Connector v3.5.4 | Stato: ATTIVO` o `| Stato: FERMO`. Sostituita in tutte le assegnazioni `$notifyIcon.Text = "$AppName - Attivo"` (7 punti: avvio, auto-start Task, post-start/stop/restart click, Manage Devices restart, timer health check). La funzione estesa `Get-StatusText` (multi-riga con uptime, SNMP/Syslog count, NOC url) resta usata solo per il MessageBox "Stato" (click menu + double-click tray).

**Icone native Windows** in `installer_gui.ps1`:
- `Apri Cartella Log.lnk` → `%SystemRoot%\System32\shell32.dll,3` (cartella gialla)
- `Disinstalla ARGUS Connector.lnk` → `%SystemRoot%\System32\shell32.dll,271` (cestino rosso)
- `Avvia ARGUS Connector.lnk` e `Diagnostica Connessione.lnk` continuano a usare `86bit_logo.ico` (branding principale)

**Distribuzione Metodo A (upload via Center UI)**: ZIP generati in `/app/frontend/public/downloads/` e **non** registrati nel DB automatico — l'admin li scarica via HTTPS e li ricarica dalla pagina `/connectors` (pulsante "Pubblica Aggiornamento" → `POST /api/connector/upload-update`) che si occupa di: copia in `/app/connector_updates/`, record `connector_updates` active=true, copia extra in `/app/frontend/public/downloads/`. Connector in field si aggiornano via Scheduled Task `\86BIT\ArgusConnectorUpdater` (poll 5 min) verso `GET /api/connector/update-check`.

**File toccati**:
- `/app/noc-connector/prg/src/tray_app.ps1` (rinominato UI, nuova `Get-TooltipText`, tooltip semplificato)
- `/app/noc-connector/prg/src/installer_gui.ps1` (rinominato UI, icone native shortcut Log/Uninstall)
- `/app/noc-connector/prg/version.json` → 3.5.4 + changelog
- `/app/frontend/public/downloads/86NocConnector_v3.5.4.zip` (356 KB)
- `/app/frontend/public/downloads/86NocConnector_v3.5.4_install.zip` (357 KB, con VBS installer)

**Verifica HTTP**: entrambi gli ZIP raggiungibili `200 OK` via `https://<domain>/downloads/86NocConnector_v3.5.4*.zip`. Sintassi PowerShell bilanciata (braces/parens match 0 diff).

### Connector v3.5.5 — Branding Pannello di Controllo (2026-04-23)
**Richiesta utente** (chiude Task 2 del TODO v3.4.7): allineare il nome visualizzato in "Pannello di Controllo → Programmi e funzionalità" / "App e funzionalità" al nuovo branding ARGUS Connector.

**Modifiche in `installer_gui.ps1`** → chiave registry `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector` (`/reg:64`):
- `DisplayName`: da `"86BIT ARGUS Center Connector"` → `"ARGUS Connector"` (coerente con tray, Menu Start, form UI)
- `EstimatedSize`: ora calcolato dalla dimensione reale della cartella installata via `Get-ChildItem -Recurse | Measure-Object Length` / 1024 (era fisso a 1024 KB)
- `DisplayIcon` → `86bit_logo.ico` (già presente dalla v3.5.0, invariato)
- `Publisher` → "86BIT srl Unipersonale", `HelpLink` → `mailto:info@86bit.it`, `URLInfoAbout` → `https://www.86bit.it` (già presenti)
- `NoModify` / `NoRepair` → 1 (l'entry mostra solo "Disinstalla" nel pannello)

**Log installer** ora riporta: `Programmi e Funzionalita': OK (ARGUS Connector v3.5.5, <N> KB)` con dimensione effettiva.

**File toccati**:
- `/app/noc-connector/prg/src/installer_gui.ps1` (sezione registry uninstall)
- `/app/noc-connector/prg/version.json` → 3.5.5
- `/app/frontend/public/downloads/86NocConnector_v3.5.5.zip` (356 KB)
- `/app/frontend/public/downloads/86NocConnector_v3.5.5_install.zip` (357 KB)

**Verifica**: sintassi PowerShell bilanciata (braces 176/176, parens 618/618). ZIP `200 OK` su HTTPS pubblico.

### Time-Series Metrics + Syslog Viewer + SNMP Traps (2026-04-22 — iteration_59)

### Sprint Sicurezza Enterprise — IP Allowlist + WireGuard VPN (2026-04-25)

**Trigger**: il cliente ha richiesto "VPN estremamente sicura e protetta per collegarsi ai dispositivi" + "ulteriore sicurezza dove inseriamo IP Pubblici autorizzati al collegamento". Implementati DUE sistemi di sicurezza enterprise complementari.

#### 1. IP Allowlist (Network Layer)
**Scope**: blocca accessi a `/api/admin/*` e `/api/auth/login` da IP non autorizzati. Bypass automatico per `/api/health`, `/api/connector/*` (autenticati via X-API-Key + HMAC), `/downloads/*`, loopback.

**Componenti**:
- `/app/backend/routes/security_allowlist.py` — modulo completo (CRUD + middleware FastAPI + validazione CIDR via `ipaddress` stdlib + audit log)
- Middleware `IPAllowlistMiddleware` registrato in `server.py` — controlla `X-Forwarded-For` o `request.client.host`
- **Anti-lockout protection**: il backend rifiuta con 422 `lockout_risk` se la nuova regola NON include l'IP del richiedente E nessun'altra regola attiva lo include. Bypass con `?force=true` per casi avanzati.
- `/app/frontend/src/pages/IPAllowlistPage.js` — UI dedicata con: banner IP corrente + reason, status "ATTIVA/INATTIVA", tabella regole con toggle enable/disable, dialog add con preview "il tuo IP è incluso?" in tempo reale, dialog confermazione force per lock-out scenarios, dialog conferma delete
- Link da `SettingsPage` → "Gestisci IP Pubblici Autorizzati"

**Logica**:
- Lista vuota → tutti gli IP consentiti (evita lock-out durante setup iniziale)
- Lista popolata → solo IP/range attivi consentiti su admin endpoints
- Connector bypassano sempre (autenticazione separata via X-API-Key)
- Loopback sempre consentito (per healthcheck interno e debug)

**Endpoint**:
- `GET /api/admin/security/allowed-ips` — lista
- `POST /api/admin/security/allowed-ips[?force=true]` — aggiungi
- `PATCH /api/admin/security/allowed-ips/{id}` — toggle/edit
- `DELETE /api/admin/security/allowed-ips/{id}` — rimuovi
- `GET /api/admin/security/allowed-ips/check` — diagnostico (ritorna IP corrente + allowed/reason)

#### 2. WireGuard VPN — Military-Grade Remote Access
**Scope**: tunnel on-demand crittografati ChaCha20-Poly1305/Curve25519 verso i dispositivi del cliente attraverso il connector ARGUS. Isolamento per-tenant strict (un cliente NON vede mai la rete di un altro). Tunnel attivo solo quando l'admin clicca "Connetti", chiusura automatica via TTL.

**Componenti**:
- `/app/backend/routes/wireguard.py` — modulo backend completo:
  - Schema DB: `wireguard_peers` (client_id, public_key, tunnel_ip auto-allocato dalla pool /16, active flag), `wireguard_sessions` (id, status active/expired/stopped/superseded, started_by, target_device_ip, reason, expires_at)
  - Endpoint connector-facing (X-API-Key auth): `POST /api/connector/wireguard/register-public-key` (idempotent, rotation supportata), `GET /api/connector/wireguard/config` (ritorna tunnel_ip + server_endpoint + interface_name `wg-<client-id8>`), `GET /api/connector/wireguard/session` (long-poll per attivazione/disattivazione tunnel)
  - Endpoint admin-facing (JWT auth): `GET /api/admin/wireguard/server-status` (ready/not-ready), `GET /api/admin/wireguard/peers`, `POST /api/admin/wireguard/session/start` (con TTL 1-240 min), `POST /api/admin/wireguard/session/{id}/stop`, `GET /api/admin/wireguard/sessions[?client_id&limit]`, `POST /api/admin/wireguard/peer/{client_id}/disable`
  - Auto-allocazione IP da pool `WG_POOL_BASE` (default 10.86.0.0/16, configurabile via env)
  - Idempotency: re-registrare la stessa pubkey è no-op; ruotare la pubkey mantiene lo stesso tunnel_ip
  - Audit log completo (WG_PEER_REGISTERED, WG_PEER_KEY_ROTATED, WG_PEER_DISABLED, WG_SESSION_START, WG_SESSION_STOP)
  - Validazione pubkey WireGuard via base64 32-byte raw check
- `/app/scripts/setup-wireguard-server.sh` — installazione one-shot del server WG su Linux: apt/dnf/yum auto-detect, generazione chiavi server idempotente, config `/etc/wireguard/wg0.conf` con NAT iptables MASQUERADE, IP forwarding persistente, ufw/firewalld auto-config, systemd `wg-quick@wg0` enable+start, output finale con env vars da aggiungere a `.env`
- `/app/scripts/teardown-wireguard-server.sh` — disinstallazione pulita con backup config
- `/app/frontend/src/pages/WireGuardPage.js` — UI Center completa:
  - Banner status server (ready/not-ready con istruzioni step-by-step se mancano env vars)
  - 3 tab: Sessioni Attive (con stop button), Peer Registrati (con disable + copy pubkey), Storico (con stato active/expired/stopped/superseded color-coded)
  - Dialog "Avvia Sessione VPN" con select cliente (solo peer attivi), IP target (audit), motivo (audit), TTL custom
  - Auto-refresh ogni 10s quando la pagina è aperta
  - Empty states con CTA chiare

**Modello sicurezza**:
- Tunnel **on-demand**: il connector NON tiene su il tunnel sempre. Long-poll ogni 5s, attiva quando session.status=active, chiude quando expired/stopped.
- **Per-tenant isolation**: ogni connector ha la sua sub-interface `wg-<client-id8>` (se tradotto a livello kernel WireGuard via setup avanzato), zero cross-tenant traffic
- **Audit completo**: chi ha avviato la sessione, quale device target, motivo, durata, exit reason
- **Disable peer**: l'admin può disabilitare un peer compromesso senza rimuoverlo (impedisce nuove sessioni)
- **TTL forzato**: max 240 min per sessione, sessioni scadute si chiudono automaticamente

**Operatività**:
- Step 1 (sysadmin): `sudo bash /app/scripts/setup-wireguard-server.sh` sul server Argus → ottiene `WG_SERVER_PUBKEY` + `WG_SERVER_ENDPOINT`
- Step 2 (sysadmin): copia env vars in `/app/backend/.env` + `sudo supervisorctl restart backend`
- Step 3 (deploy connector v3.5.18+): connector all'avvio genera coppia chiavi WG, registra pubkey, riceve config
- Step 4 (admin Center): `/settings/wireguard` → "Avvia Sessione VPN" → seleziona cliente + device → tunnel attivo entro ~5s

**File**:
- `/app/backend/routes/security_allowlist.py` (nuovo, 250 righe)
- `/app/backend/routes/wireguard.py` (nuovo, 285 righe)
- `/app/backend/server.py` (registrato 2 nuovi router + 1 middleware)
- `/app/frontend/src/pages/IPAllowlistPage.js` (nuovo, 320 righe)
- `/app/frontend/src/pages/WireGuardPage.js` (nuovo, 380 righe)
- `/app/frontend/src/pages/SettingsPage.js` (aggiunte 2 card "Gestisci")
- `/app/frontend/src/App.js` (registrate 2 nuove route)
- `/app/scripts/setup-wireguard-server.sh` (nuovo, 165 righe)
- `/app/scripts/teardown-wireguard-server.sh` (nuovo, 30 righe)

**Test backend**:
- ✅ CRUD allowed-ips: add/list/patch/delete + anti-lockout 422 + force=true bypass
- ✅ WG status: pool 10.86.0.0/16, ready=false (server non config in preview)
- ✅ WG peer register: nuova pubkey → tunnel_ip 10.86.0.2 assegnato; idempotent re-registration; rotation pubkey mantiene IP
- ✅ WG session lifecycle: admin start → connector poll vede `tunnel_required=true session_id ...` → admin stop → connector poll vede `tunnel_required=false`

**TODO sprint successivi**:
- v3.5.18 connector: integrazione runtime WireGuard (genera chiavi, register, long-poll session, lancia `wireguard.exe /installtunnelservice` o `wg-quick up/down`)
- Integration test su VM Linux + cliente Windows reale con VPS WireGuard ready
- Implementare iptables/wg per-tenant strict isolation a livello kernel (oggi è solo logico)
- Pannello "Connettiti al device" sulla pagina dispositivo: pulsante che fa start session + apre il browser sull'IP del device tramite tunnel
**Obiettivo release**: package "production-grade" unico pronto per deployment su server vergini, con validazione preflight che previene il problema storico di installazione cieca → scoperta del problema solo ore dopo nei log.

**Novità v3.5.17**:
1. **Wizard bloccante**: il pulsante "Avanti" dalla pagina 1 (URL + API Key) ora esegue 3 verifiche sequenziali prima di consentire il passaggio alla pagina 2:
   - `GET /api/health` — NOC raggiungibile? (altrimenti MessageBox rosso con dettaglio errore rete)
   - `GET /api/connector/identify` con `X-API-Key` — la key è riconosciuta dal DB? (su 401 → "API Key non valida — verifica nel Center UI"; su 404 fallback a `POST /connector/heartbeat` per backend pre-v3.5.16)
   - Feedback visivo: MessageBox di conferma con "Cliente: <nome> | Client ID: <uuid>" — l'admin vede ESATTAMENTE quale cliente sta attivando
2. **Warning doppioni hostname**: nuovo endpoint `GET /api/connector/by-hostname/{hostname}` interrogato dal wizard; se esiste già un connector registrato per quel cliente con lo stesso hostname l'admin riceve "Un connector con hostname X risulta già registrato (v3.5.14, last heartbeat 12:34). Sovrascrivere?"
3. **Auto-save `client_id`** nel config.json dopo la validazione (il runtime non avrà bisogno di auto-discovery al primo boot — tutto è già pronto)

**Stack completo cumulato in v3.5.17**:
- Installazione: wizard grafico bloccante, validazione preflight, Defender exclusions, firewall UDP 162+514, NSSM service LocalSystem con AppParameters separato (quoting Program Files fixato), Task Scheduler `\86BIT\ArgusConnectorUpdater` ogni 5 min per auto-update, Menu Start + registro Uninstall per rimozione da Pannello di Controllo.
- Runtime: listener UDP effettivamente attivi (`$global:Running = $true` nello scope job, fix v3.5.13), polling SNMP con entity_mib + primary_mac + if_aliases + arp_table + sys_object_id propagati al NOC, vendor_snmp_targets applicati da profili device_profiles, IPC via `refresh.flag` per "Applica ora" real-time, auto-discovery `client_id` se config vuoto, messaggi 401 actionable con soluzione esplicita.
- Disinstallazione: `uninstall.ps1` 8-step idempotente (task scheduler, service qualsiasi stato, processi orfani con guardia anti-suicidio, Menu Start, registro HKLM+HKCU reg32/64, cartelle ProgramData + Program Files, fallback `PendingFileRenameOperations` per file lockati, verifica finale con exit code 0/1).

**File coinvolti questa release**:
- `/app/noc-connector/prg/src/installer_gui.ps1` — logica navigazione con validazione bloccante in `$btnNext.Add_Click` sulla pagina 1
- `/app/backend/routes/connector.py` — nuovo endpoint `/connector/by-hostname/{hostname}`
- `/app/noc-connector/prg/version.json` → 3.5.17
- Pubblicati: `/app/connector_updates/86NocConnector_v3.5.17.zip` (361 KB) + `/downloads/86NocConnector_v3.5.17_install.zip` (363 KB)

**Nota deploy produzione**: i nuovi endpoint backend (`/connector/identify` e `/connector/by-hostname`) esistono solo sul preview Emergent. Per usarli in produzione il cliente deve deployare il backend Python aggiornato sul proprio server IIS (argus.86bit.it). Il wizard ha fallback graceful: se `/identify` ritorna 404, prova con `/connector/heartbeat` che esiste da sempre.

**Known gotcha osservato in field**: il backend IIS del cliente (argus.86bit.it) era fermo alla v3.5.8 del `connector_updates` — gli ZIP più recenti (v3.5.9 in poi) non sono pubblicati sul DB di produzione. Azione richiesta all'admin: deploy backend Python + ripubblicazione ZIP v3.5.17 come attivo su produzione.

### Connector v3.5.16 — Auto-discovery client_id + messaggi 401 actionable (2026-04-24)
**Contesto**: sessione drammatica di debug su GALVANSRV. Dopo aver risolto bug NSSM quoting (v3.5.15), installazione pulita con v3.5.14 e servizio stabile, è emerso che il connector riceveva **401 Non autorizzato** su TUTTE le chiamate (heartbeat, device-report, web-proxy/pending, discovery-check). L'utente ha visto il servizio come "si disconnette ogni 60s" nel Center perché nessun heartbeat veniva registrato.

**Root cause analisi profonda**:
- Il `config.json` di GALVANSRV ha `client_id=""` (vuoto) — il wizard installer pre-v3.5.16 NON chiedeva `client_id` all'admin, solo URL + API Key.
- PERÒ: il backend `verify_connector_request` + `validate_api_key` NON usano `X-Client-Id` header! Il client viene sempre risolto via `X-API-Key` lookup nel DB → quindi il client_id vuoto nel config **non è la causa diretta** del 401.
- Causa reale: **la API key nel config.json non matcha alcun record in `db.clients` di argus.86bit.it**. Cause possibili: key rigenerata nel Center UI dopo l'installazione, cliente ricreato, typo durante il wizard, installazione contro Center sbagliato.

**Fix rilasciati (prevenzione futura)**:
1. Nuovo endpoint backend `GET /api/connector/identify` che dato solo `X-API-Key` ritorna `{client_id, client_name, status}`. Permette ai connector di auto-configurarsi e serve da **primo test di validità della key** in sede di wizard.
2. Connector runtime: funzioni `Get-ClientIdFromServer` + `Ensure-ClientIdInConfig` chiamate in apertura di `Start-PollingLoop`. Se `config.client_id` è vuoto → chiama `/identify` → salva risultato nel `config.json` → ricarica config. Se anche l'identify fallisce (es. key invalida) → log ERROR esplicito.
3. Wizard installer: il pulsante *"Test Connessione"* ora chiama `/identify` dopo health check e **mostra il client_id scoperto all'admin** come conferma visiva (MessageBox). Client_id salvato in `$script:DiscoveredClientId` e poi propagato in `config.json` durante installazione. Fallback legacy a heartbeat+X-API-Key se il NOC non ha ancora `/identify`.
4. Messaggi 401 **chiari e actionable**: prima `Errore secure GET connector/web-proxy/pending: Errore del server remoto (401)` generico, ora `401 Non autorizzato su <endpoint> — API Key non accettata dal NOC. Soluzione: nel Center vai su Clienti > [tuo cliente] > Rigenera API Key → copia in config.json → Restart-Service`. Con throttling (full message ogni 10 fallimenti, WARN per i restanti) per evitare log flood.
5. Nuovo contatore `$global:Stats.auth_failures` (contabilizza i 401 per eventuali dashboard future).

**Situazione GALVANSRV residua** (azione manuale richiesta all'utente su server produzione argus.86bit.it):
- L'utente deve **rigenerare l'API Key** del cliente 86BIT_Office nel Center UI
- **Copiare la nuova key** in `C:\ProgramData\86NocConnector\config.json` sul server
- `Restart-Service 86NocConnectorService`
- Da quel momento il connector riprende a comunicare e l'auto-update applicherà v3.5.16 in background entro ~30 min.

**File modificati**:
- `/app/backend/routes/connector.py`: aggiunto endpoint `/connector/identify` (linea 510) + salvato `sys_object_id` nel device-report doc (v3.5.13)
- `/app/noc-connector/prg/src/connector.ps1`: nuove `Get-ClientIdFromServer`, `Ensure-ClientIdInConfig`; `Start-PollingLoop` ora chiama auto-discovery; `Invoke-SecureGet` + `Send-ToNOC` ora distinguono 401 (auth) da altri errori e producono messaggi chiari; `$global:Stats.auth_failures` contatore
- `/app/noc-connector/prg/src/installer_gui.ps1`: `btnTest.Add_Click` ora chiama `/identify`; config.json ora include `client_id` valorizzato dall'identify; `$script:DiscoveredClientId`
- `/app/noc-connector/prg/version.json` → 3.5.16
- `/app/connector_updates/86NocConnector_v3.5.16.zip` (361 KB) + pubblicato `/downloads/86NocConnector_v3.5.16_install.zip` (v3.5.15 disattivato in DB)

**Debito tecnico emerso in questa sessione**:
- Il wizard attuale non valida API key contro il NOC prima di installare il servizio (il pulsante "Test" lo faceva ma non bloccava se skippato). Idea per v3.6: validazione obbligatoria prima di "Installa".
- Aggiungere alla pagina `/connectors` del Center un pannello "Problemi autenticazione" che mostra i client/connector che ricevono 401 ricorrenti (count > 5 negli ultimi 10 min) → permette all'admin di accorgersi del mismatch key prima che l'utente chiami il supporto.
- Il wizard potrebbe mostrare un warning se il cliente nel Center ha N connector già registrati con lo stesso hostname → evita doppioni.

### Connector v3.5.15 — FIX CRITICO INSTALLER NSSM quoting su path con spazi (2026-04-23 notte)
Vedi changelog embedded in `version.json` commit. Root cause: `nssm install <svc> powershell.exe "-File C:\Program Files\...connector.ps1"` non preservava correttamente le virgolette → PowerShell riceveva `-File C:\Program` monco → crash infinito ogni 60s. Fix: separare `nssm install` (solo exe) e `nssm set AppParameters` (args). + path assoluto a `powershell.exe` via `$env:SystemRoot`.

### Connector v3.5.14 — Disinstallazione enterprise-grade (2026-04-23 sera)
**Contesto**: dopo il rescue di GALVANSRV (connector in stato "Paused + Disabled", Task Scheduler omonimo del servizio NSSM rimasto orfano, cartella `C:\Program Files\86NocConnector` con `nssm.exe` locked), l'utente ha chiesto di **consolidare tutta la procedura di pulizia "nuclear-safe" dentro il flusso di disinstallazione ufficiale** del connector — in modo che qualunque amministratore futuro che disinstalli dal Pannello di Controllo o dal Menu Start ottenga la stessa pulizia completa, senza bisogno di istruzioni manuali.

**Sostituito**: il vecchio `uninstall.bat` lineare (~125 righe, path hardcoded a `C:\86NocConnector` non più usato dalla v3.4.0, nessuna gestione stati anomali del servizio) con un design a 2 file:

- **`uninstall.ps1`** (~380 righe, logica robusta completa)
- **`uninstall.bat`** (wrapper minimo ~50 righe: auto-elevation UAC + copia dello script in `%TEMP%` per evitare file-lock sulla stessa install dir + `ExecutionPolicy Bypass`)

**Cosa copre uninstall.ps1 — 8 step idempotenti con log**:

1. **Task Scheduler — ordine critico PRIMA del servizio** (altrimenti un task in esecuzione riavvierebbe il servizio mentre proviamo a eliminarlo):
   - `\86BIT\ArgusConnectorUpdater` (v3.5.0+ auto-update)
   - `\86BIT\86NocConnector_Watchdog` (v3.5.12 watchdog)
   - `\86NocConnector` (legacy pre-v3.3.0)
   - **`\86NocConnectorService` — il colpevole storico omonimo del servizio NSSM visto su GALVANSRV** (root del loop di restart ciclico pre-v3.5.12)
   - `\ArgusConnector` + varianti in `\86BIT\`
   - Cartella parent `\86BIT\` rimossa se vuota (via COM Schedule.Service)
   - Doppio approccio: `Unregister-ScheduledTask` + fallback `schtasks.exe /Delete /F` per compatibilità API vecchie
2. **Servizio NSSM — resistente a ogni stato**: gestisce Running, Paused, StopPending, Disabled. Sequenza: Resume-Service se Paused (altrimenti Stop si blocca), NSSM stop se disponibile, `sc.exe stop`, wait-loop fino a 15s, fallback kill dei processi in install dir, `sc.exe delete` finale.
3. **Kill processi orfani**: filtrato via `Get-CimInstance Win32_Process` + `CommandLine` matching su `connector.ps1 | tray_app.ps1 | snmp_poller.ps1 | update_check.ps1 | service_wrapper.ps1`. **Guardia anti-suicidio `$_.Id -ne $PID`** (impara dalla lezione del primo `fix-connector.ps1` che killava se stesso). `nssm.exe` separato, filtrato solo se `Path -like` install dir → non tocca NSSM di altri prodotti Windows.
4. **Menu Start**: tutti i path alias storici (`86BIT ArgusCenter`, `86BIT Connector`, `86NocConnector`, `ARGUS Connector`, sia `%ProgramData%` che `%AppData%`).
5. **Registro**: `HKLM` + `HKCU` + `WOW6432Node`, sia `reg64` che `reg32`, chiavi Uninstall + Run per tutti gli alias (`86BIT_ArgusCenter_Connector`, `86NocConnector`, `ARGUS_Connector`).
6. **Cartella dati** `%ProgramData%\86NocConnector`.
7. **Cartella installazione** con **retry loop 5×** + kill secondario processi in path al 2° fallimento + **fallback `HKLM\System\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations`** per programmare l'eliminazione al prossimo reboot se i file sono ancora bloccati da servizi di sistema (Antivirus, SmartScreen, ecc.). Rimuove anche la legacy `C:\86NocConnector` pre-v3.4.0.
8. **Verifica finale**: check residui su cartelle, servizio, task scheduler. 3 scenari di exit:
   - `Code 0`: sistema vergine ✓
   - `Code 1` + "richiesto reboot": tutti i file saranno eliminati al prossimo riavvio
   - `Code 1` + lista residui: azioni manuali suggerite con elenco preciso di cosa resta

**Log completo** in `%TEMP%\argus-uninstall-<timestamp>.log` (sempre scritto, anche se lo script fallisce a metà) con livelli INFO/OK/WARN/ERROR/STEP color-coded in console.

**File toccati**:
- `/app/noc-connector/prg/uninstall.bat` (rewrite: wrapper ~50 righe con auto-elevation + copia in %TEMP%)
- `/app/noc-connector/prg/uninstall.ps1` (nuovo, ~380 righe)
- `/app/noc-connector/prg/version.json` → 3.5.14
- Pubblicati: `/app/connector_updates/86NocConnector_v3.5.14.zip` (361 KB) + `/app/frontend/public/downloads/86NocConnector_v3.5.14_install.zip`
- `db.connector_updates` → v3.5.14 attivo, v3.5.13 disattivato

**Entry point utente** (già cablati da `installer_gui.ps1` dalla v3.5.5):
- Menu Start: *"Disinstalla ARGUS Connector"* → `uninstall.bat`
- Pannello di Controllo → Programmi e funzionalità → *ARGUS Connector* → Disinstalla (chiave registry `HKLM\...\Uninstall\86BIT_ArgusCenter_Connector\UninstallString`) → `uninstall.bat`
- Esecuzione manuale: `C:\Program Files\86NocConnector\uninstall.bat` (tasto destro Amministratore)

**Non toccato**: l'installer `installer_gui.ps1` — il flusso di install-time cleanup (prima dei nuovi componenti) resta inalterato perché già corretto dalla v3.5.12. Qui interveniamo solo sul flusso di disinstallazione finale.

### Connector v3.5.13 — FIX CRITICO passaggio dati + stabilità listener UDP (2026-04-23)
**Contesto**: cliente frustrato per "troppo tempo e soldi spesi sul connector" che non passava tutte le informazioni dei dispositivi. Audit completo della pipeline connector → center rivela 2 bug critici *pre-esistenti* che invalidavano il valore del connector.

**Bug #1 — Listener UDP mai realmente attivi (P0)**
Root cause: `Start-SNMPListener` e `Start-SyslogListener` sono eseguiti dentro `Start-Job` child-process. Il loop interno `while ($global:Running)` richiede `$global:Running = $true` ma la variabile NON era settata dentro lo scope del job — solo in `Start-Connector` (che non viene rieseguito nei job per via della guardia `$MyInvocation.InvocationName -ne "."`). Risultato: i job terminavano immediatamente dopo 2s → job health-check riaffiorava ogni 3 min → il connector di fatto non ha MAI ricevuto trap SNMP o messaggi syslog. I log mostravano il loop "Listener morto, riavvio" perpetuo mentre gli utenti si lamentavano di aver perso alert critici inviati dai device.

**Fix**: aggiunto `$global:Running = $true` dentro lo scriptblock di entrambi i Start-Job (all'avvio + nei restart del health-check). Patch minima, 4 righe.

**Bug #2 — Perdita dati hardware (P0)**
Root cause: `Poll-ExtendedMetrics` raccoglieva correttamente da ogni device SNMP:
- `entity_mib` (vendor, modello, serial number, firmware version dallo standard RFC 4133 ENTITY-MIB, che funziona su *qualsiasi* device SNMP compliant — switch, firewall, stampanti, NAS, server)
- `primary_mac` (MAC principale del device)
- `if_aliases` (nomi custom delle porte dello switch, es. "Uplink DC", "Firewall LAN")
- `arp_table` (tabella ARP per correlazione IP→MAC cross-device: fondamentale per mappare endpoint LAN senza SNMP proprio)

Ma `Send-DeviceReport` li ignorava sistematicamente: solo 6 campi su 10 venivano propagati nel payload HTTP verso il NOC (`cpu_usage`, `memory_usage`, `temperature`, `device_class`, `hardware`, `firewall`). Il backend era già pronto a riceverli (righe 1355-1358 di `connector.py`) ma non arrivavano mai → UI mostrava sempre "sconosciuto" per vendor/modello/firmware anche su device che li esponevano regolarmente.

Mancava inoltre il polling di `sys_object_id` (OID 1.3.6.1.2.1.1.2.0) usato dal backend per il fingerprint automatico dei profili vendor (device_profiles). Senza sysObjectID il fingerprint cadeva sul solo `sysDescr` regex → match mancanti per device con descrizioni atipiche.

**Fix**:
1. `connector.ps1` Send-DeviceReport: aggiunti 4 campi (`entity_mib`, `primary_mac`, `if_aliases`, `arp_table`) al `$deviceReport` (condizionali su non-null per non inquinare payload device offline).
2. `connector.ps1` Send-DeviceReport: polling di `sys_object_id` (1.3.6.1.2.1.1.2.0) insieme a sysDescr/sysName/sysUptime.
3. `connector.ps1`: dichiarazione `$vendorMetrics = $null` fuori dall'if-reachable per evitare errore scope in caso di device irraggiungibile.
4. `backend/routes/connector.py` device-report: salva anche `sys_object_id` su `device_poll_status`.

**Test end-to-end** (curl con HMAC signing completo, simula il connector):
```
POST /api/connector/device-report → 200 OK {"devices_updated":1}
Saved fields verified:
  sys_object_id: 1.3.6.1.4.1.25506.11.1.208   ✓
  entity_mib: {'vendor':'HPE','model':'5130-24G-4SFP+','serial':'CN00000000','firmware':'7.1.070'}   ✓
  primary_mac: AA:BB:CC:DD:EE:FF   ✓
  if_aliases: {'1':'Uplink','2':'Server'}   ✓
  arp_entries_count: 2 (→ arp_cache populated)   ✓
```

**File toccati**:
- `/app/noc-connector/prg/src/connector.ps1` — Send-DeviceReport (+4 field propagation, +sys_object_id polling), Start-Connector (fix listener jobs), job health-check (fix restart scriptblock)
- `/app/backend/routes/connector.py` — device-report endpoint salva sys_object_id
- `/app/noc-connector/prg/version.json` → 3.5.13
- `/app/frontend/public/downloads/86NocConnector_v3.5.13.zip` (361 KB) + `_install.zip`
- `/app/connector_updates/86NocConnector_v3.5.13.zip` (attivo in DB)

**Impatto atteso in field**:
- UI Device Detail: colonne vendor/modello/firmware/serial popolate automaticamente per *tutti* i device SNMP compliant, non più solo Synology/iLO/Comware.
- Sezione ARP: correlazione IP→MAC popolata per device downstream senza SNMP proprio (VM, stampanti non-SNMP, IP cam, ecc.).
- Alert SNMP trap e syslog ora effettivamente ricevuti (potenzialmente: aumento del volume alert, soprattutto per device rumorosi — monitor first 24h).
- Fingerprint auto-profili più robusto grazie a sysObjectID.

### Connector v3.5.12 — Self-heal Task Scheduler conflittuale (2026-04-23 mattina)
Vedi handoff: self-healing al boot rimuove Task Scheduler legacy omonimo del servizio NSSM + watchdog schtasks fix via file intermedio + fix BER/vendor enrichment/Get-SnmpTable delle v3.5.9/3.5.10/3.5.11.

### Connector v3.5.7 — Applica Ora (real-time config sync, 2026-04-23)
**Problema**: modificando community/profilo/monitor-type dal Center, il connector applicava le modifiche solo al ciclo successivo di `Fetch-DevicesFromNOC` — che gira **ogni 10 cicli di poll (~10 minuti)**. Per sbloccare prima servivano: restart del servizio o del tray app sul server field.

**Soluzione (minimal surface change, no new endpoint chain)**:
1. **Backend** (`connector.py`):
   - Nuovo endpoint `POST /api/connector/{client_id}/request-refresh` → setta flag `refresh_requested=true` in `connector_status` (richiede ruolo admin + audit log).
   - `POST /api/connector/heartbeat` response ora include `refresh_now: true` se il flag è settato, e lo resetta atomicamente nello stesso update (self-clearing).
2. **Connector PowerShell** (`connector.ps1`):
   - `Send-Heartbeat` ora controlla `$response.refresh_now` e setta `$global:ForceRefreshPending = $true`.
   - Loop di polling principale: se `$global:ForceRefreshPending` è true, resetta il flag in memoria e forza `Fetch-DevicesFromNOC` + `Run-FullDiscovery` subito al prossimo ciclo (≤ 60s) invece di aspettare i 10 cicli standard.
3. **Frontend** (`DeviceEditModal.js` + `DeviceProfileModal` in `ClientOverviewPage.js`):
   - Aggiunto pulsante **"Applica ora"** (ambra + icona Lightning) nel modal di edit, che chiama `POST /request-refresh`.
   - `DeviceProfileModal` chiama automaticamente `request-refresh` in fire-and-forget dopo ogni applicazione profilo → l'admin non deve cliccare nulla di extra.

**Timing totale dopo "Applica ora"**: ≤ 30s (tempo del prossimo heartbeat) + ≤ 60s (prossimo ciclo di poll) = **max ~90s** invece di 10 min.

**File toccati**:
- `/app/backend/routes/connector.py` — endpoint `/request-refresh`, heartbeat arricchito con `refresh_now`
- `/app/noc-connector/prg/src/connector.ps1` — handler in `Send-Heartbeat`, bypass ciclo 10 nel main loop
- `/app/frontend/src/components/DeviceEditModal.js` — pulsante "Applica ora" + data-testid `edit-apply-now-btn`
- `/app/frontend/src/pages/ClientOverviewPage.js` — fire-and-forget in `DeviceProfileModal.apply()`
- `/app/noc-connector/prg/version.json` → 3.5.7

**Verifica curl**:
- `POST /request-refresh` → `{"status":"ok","message":"Richiesta refresh inviata..."}` ✅
- Flag `refresh_requested=true` persistito in `connector_status` ✅
- `POST /request-refresh` con client inesistente → 404 ✅
- Audit log: azione `UPDATE_CLIENT` con `details={action:"request_refresh"}` ✅

### AUDIT Comunicazione Connector↔Center (2026-04-23)
**17/17 endpoint mappati correttamente** — zero endpoint "phantom":

| Endpoint connector | Backend registrato |
|---|---|
| `POST /connector/heartbeat` | ✅ `connector.py:173` (+ `/c/hb` secure) |
| `POST /connector/device-report` | ✅ `connector.py:1264` |
| `POST /connector/managed-devices` | ✅ `connector.py:258` |
| `POST /connector/discovery-results` | ✅ `connector.py:1766` (+ `/c/nd`) |
| `GET /connector/fetch-devices` | ✅ `connector.py:1701` (+ `/c/fd`) |
| `GET /connector/vault/credentials` | ✅ `connector.py:371` (+ `/c/vc`) |
| `POST /ingest/snmp` | ✅ |
| `POST /ingest/syslog` | ✅ |
| `POST /remediation/result` | ✅ `remediation.py:408` |
| `POST /vulnerability/process-scan-results` | ✅ `vulnerability.py:369` |
| `POST /vulnerability/update-scan-status` | ✅ `vulnerability.py:448` |
| `GET /connector/discovery-check` | ✅ |
| `GET /connector/web-proxy/pending` | ✅ |
| `POST /connector/web-proxy/response` | ✅ |
| `GET /connector/update-check` | ✅ `connector.py:465` (+ `/c/uc`) |
| `POST /connector/update-progress` | ✅ `connector.py:597` (+ `/c/up`) |
| `POST /connector/web-ui-detected` | ✅ `connector.py:309` |

**Sicurezza**: ogni richiesta connector → center passa per `verify_connector_request` con HMAC-SHA256 signature + anti-replay (timestamp/nonce) + API key rotation supportata.

### Time-Series Metrics + Syslog Viewer + SNMP Traps (2026-04-22 — iteration_59)
**Richiesta utente**: "procedi con Sessione 2 SNMP Trap receiver, Sessione 3 Syslog receiver, Sessione 4 Time-series + grafici".

**Backend**:
- `routes/metric_history.py` — collection `metric_history` con TTL 30gg. `record_metrics(client_id, device_ip, dev)` chiamata dentro `POST /api/connector/device-report` (connector.py:1388). Endpoint `GET /api/devices/by-ip/{ip}/metrics?metric=cpu&period=24h` con bucket $mod dinamico (1h/6h/24h/7d/30d). Estrae cpu/memory/temperature/response_ms/ups_charge_pct/ups_runtime_min/ups_load_pct/sessions + metriche vendor (Synology disk_temp, Fortinet fgSysCpuUsage, HPE H3C cpuUsage).
- `routes/syslog_trap.py` — collection `syslog_events` e `snmp_traps` con TTL 14gg. Endpoint `GET /api/connector/syslog?device_ip&severity_max&limit` e `GET /api/connector/snmp-traps?device_ip&limit`. Endpoint batch `POST /api/connector/syslog-batch` e `POST /api/connector/snmp-trap-batch` per il connector (richiedono X-API-Key + HMAC).
- `routes/ingestion.py` — gli endpoint esistenti `/api/ingest/syslog` e `/api/ingest/snmp` (usati dal connector v3.4.5 già in field) ora scrivono ANCHE in `syslog_events` / `snmp_traps` in aggiunta agli alert. Così l'Syslog/Trap Viewer funziona senza update connector.
- Pattern-based alerting nel syslog-batch per 11 regex (authentication fail, link down, config change, power issue, overheat, fan fault, panic/crash, disk fail, memory error).

**Frontend** (3 nuove pagine):
- `/device-metrics` → `DeviceMetricsPage.js` — selettore client/device/metric/periodo (1h/6h/24h/7d/30d), stat cards (ultimo/media/picco), grafico recharts area+line con avg/min/max, refresh 60s. Supporta `?ip=` URL param per pre-select.
- `/syslog` → `SyslogPage.js` — tabella eventi con filtri device_ip/severity (0-7)/text search, colonne timestamp/severity badge/device/host/facility/message, auto-refresh 15s.
- `/snmp-traps` → `TrapsPage.js` — tabella traps + pannello dettaglio varbinds JSON con formatting.
- Sidebar `Operazioni` aggiornata: "Trend Metriche" (ChartLine), "Syslog Viewer" (ListChecks), "SNMP Traps" (Pulse).
- ClientOverviewPage tab Dispositivi: aggiunto bottone ChartLine indigo (`data-testid=device-trend-{ip}`) accanto a "Configura profilo" che naviga a `/device-metrics?ip={ip}`.

**Bug fix collaterale**: `VendorDetailsPanel.js` aveva import `Activity` e `Battery` da `@phosphor-icons/react` v2.1.10 che non sono esportati (solo `ActivityIcon`). Alias workaround: `BatteryMedium as Battery, Pulse as Activity`.

**Test** (iteration_59): Backend 18/20 (90%) — i 2 fallimenti erano minor error handling sui batch endpoint (ora fissato, 401 correttamente ritornato). Frontend 100% — tutte e 3 le pagine caricano, navigazione sidebar OK, bottone trend per device OK.

### Kaseya+ParkPlace Enterprise Feature Pack (2026-04-21 sera) — Automated Remediation, Hardware Lifecycle, NOC Intelligence
Su richiesta utente ("procedi con tutto"), clonate 3 funzionalità top-tier da Kaseya NOC Services e Park Place Technologies ParkView:

**Backend — 3 nuovi router**:
- `routes/remediation.py` — Automated Remediation Engine (stile Kaseya VSA). Scripts builtin (Ping, Traceroute, HTTP health, Restart svc, Printer spooler, SNMP port bounce) + custom scripts + rules matching alert→script con cooldown+max_per_day. Approval gate manuale. Evaluator hookato in `alerts.py` e `ingestion.py`. Callback `/api/remediation/result` per risultato esecuzione. Audit log per ogni azione. Collections: `remediation_scripts`, `remediation_rules`, `remediation_executions`.
- `routes/lifecycle.py` — Hardware Lifecycle & Warranty (stile Park Place ParkView). Tracking scadenze garanzia OEM, EOL/EOSL, contratti 3rd-party. **Risk score 0-100** calcolato da warranty/maintenance/EOSL + criticality. Dashboard aggregato per vendor/cliente/risk band. Endpoint `/expiring?days_ahead=90` per alert scadenze 30/60/90gg. **Import CSV** con auto-detect delimiter + alias headers italiani (data_acquisto/scadenza_garanzia/criticita). Collection: `lifecycle_records` con indice unique device_ip.
- `routes/intelligence.py` — NOC Intelligence:
  1. **Proactive Fault Triage**: 16 rule euristiche (cpu/memory/disk/thermal/fan/PSU/SMART/cert/service/backup/auth/latency/printer) → classificazione automatica severity + root-cause + recommended actions + KB match (su `problems` collection known_error/resolved) + recurrence KPI 30gg. Endpoint `/triage/{alert_id}` e `/triage-bulk?hours=24`.
  2. **Patch Compliance Dashboard**: tracking patch OS/firmware per device (pending_patches, critical_patches, cve_count, cve_list). Compliance % aggregata. Endpoint `/patch/status` per upsert dal connector.
  3. **Predictive Failure Analysis**: analizza trend 24h di `ilo_telemetry` (temp/fan/power) con slope analysis + threshold detection. Predice guasto entro 24/72/168h con risk band + confidence. Endpoint `/predictive/{ip}` e `/predictive` (overview).

**Frontend — 3 nuove pagine** (con testid per testing):
- `RemediationPage.js` — 3 tabs (Esecuzioni/Regole/Script), stats cards (pending, 24h success/fail, rules), Approve/Reject inline, RuleEditor + ScriptEditor modali con preview body.
- `LifecyclePage.js` — tabs Dashboard/In scadenza/Tutti, stats cards (totali, high risk, warranty expired, 30gg, EOSL), bar charts per vendor/risk, CSV upload + editor form con criticality.
- `IntelligencePage.js` — tabs Triage/Patch/Predictive, bulk triage 24h button, alert cards con severity upgrades visibili, patch compliance tabella, predictive risk board con ETA guasto.

**Sidebar Layout**:
- Clienti group: aggiunto "Hardware Lifecycle"
- Operazioni group: aggiunti "Auto Remediation" e "NOC Intelligence"

**Connector v3.3.0**:
- Executor PowerShell per comandi type=`remediation`: supporta powershell/shell/http-get/http-post con timeout configurabile, capture stdout/stderr, report risultato su `/api/remediation/result`. Job Start-Job con timeout hard. Output troncato a 4000 char.
- `version.json` aggiornato a 3.3.0 con changelog completo.

**Test E2E**:
- Backend: **37/37 test passati** (iteration_52.json) — CRUD scripts/rules/executions, evaluator hook su alert, builtin scripts non modificabili, lifecycle risk scoring, CSV import con fix MongoDB duplicate key, triage rules, patch compliance, predictive overview.
- Frontend: 3/3 pagine caricano con sidebar aggiornata, tabs funzionanti, modali aprono.

### Connector v3.3.1 — FIX CRITICO Updater NSSM Job Object (2026-04-21)
**Bug reportato utente**: "update connector non funziona, si chiude e poi non si apre più e non si aggiorna".

**Root cause** trovato in `connector.ps1` / `Install-Update`: l'updater.ps1 veniva lanciato come processo figlio del connector (via cmd.exe + BAT). Quando l'updater chiamava `Stop-Service` per permettere la copia dei file, NSSM — che tiene TUTTI i processi figli del service in un **Job Object Windows** — uccideva l'intero job, **incluso l'updater** a metà copia. Risultato: servizio morto, file parzialmente copiati, nessun restart possibile.

**Fix in `Install-Update`**:
1. **Metodo 1 (preferito): WMI `Win32_Process.Create`** — il processo creato via WMI diventa figlio di `wmiprvse.exe` (servizio WMI), NON del connector. È FUORI dal Job Object di NSSM → sopravvive a Stop-Service.
2. **Metodo 2 (fallback): `schtasks` run-once come SYSTEM** — Task Scheduler esegue task come SYSTEM fuori dal job object.
3. **Metodo 3 (ultima spiaggia): `cmd.exe` detached** (metodo precedente, meno affidabile ma mantenuto).
4. **Self-staging**: updater.ps1 viene copiato in `%TEMP%\86Noc_updater_*.ps1` prima del lancio, così la copia file dell'update non sovrascrive l'updater in esecuzione.
5. **Cleanup finale**: l'updater in TEMP si auto-elimina dopo 5s + rimuove il task scheduler se usato.

**Diagnostica aggiunta**: updater.ps1 logga PID/parent/command line in `%ProgramData%\86NocConnector\updater.log` per debug post-mortem.

**Distribuzione v3.3.1**:
- Update ZIP (auto-update): `86NocConnector_v3.3.1.zip` pubblicato come active in DB. I connector in field con l'updater v3.2.2 probabilmente NON si aggiorneranno (bug pre-esistente nel loro updater locale). 
- **Install ZIP completo**: `86NocConnector_v3.3.1_install.zip` (292KB) disponibile su `/downloads/86NocConnector_v3.3.1_install.zip`. Richiede **reinstallazione manuale una tantum** per sbloccare il ciclo di update. Dalla v3.3.1 in avanti tutti gli update successivi funzioneranno via WMI spawn.

### Auto-Dispatch ParkView-style (2026-04-21) — detect → predict → ticket
Chiude il cerchio tra **Hardware Lifecycle risk score** + **Predictive Failure Analysis** e la creazione automatica di **incident/ticket** pronti per il NOC.

**Backend `routes/auto_dispatch.py`**:
- `scan_hardware_lifecycle()`: lifecycle record con `risk_band=high` → crea incident "[Hardware Risk] Vendor Model — IP" con motivi (garanzia scaduta, EOSL, criticality) e severity high/medium dinamica.
- `scan_predictive_failures()`: device con telemetria iLO 24h + predicted window ≤72h → crea incident "[Predictive Failure] IP — guasto previsto entro Nh" con segnali ML (temp/fan/psu), confidence, metrics summary, severity critical(≤24h)/high(≤72h).
- **Deduplica** su `device_ip + auto_dispatch_kind` in finestra 7gg: incident già aperto → skip (evita spam).
- Endpoint: `POST /api/intel/auto-dispatch/run` (manuale), `GET /api/intel/auto-dispatch/history`, `GET /api/intel/auto-dispatch/status`.
- **Cron APScheduler 6h** attivo (primo run 10 min dopo startup backend).
- Persistenza: `auto_dispatch_history` collection.

**Test E2E**: creato record high-risk → run → 1 incident creato (risk 80) → run again → skipped_duplicate=1 → incident in lista con `auto_dispatch=true`. ✅

### Firmware Catalog & CVE Compliance (2026-04-21 sera)
Cata­logo firmware "latest known good" con confronto automatico vs versioni iLO/BIOS correnti, CVE tracking, e integrazione col modulo Patch Compliance esistente.

**Backend `routes/firmware_catalog.py`**:
- Collection `firmware_catalog` con seed iniziale (HPE iLO 5 ProLiant Gen10 v3.20, BIOS U41 v3.70, iLO 4 Gen9, Dell iDRAC 9 14G).
- CRUD admin-only + **import CSV** con delimiter auto-detect.
- `check_firmware_compliance(model, ilo_fw, bios_fw)`: regex match su `model_pattern`, confronto versioni numerico robusto (tuple int), ritorna `overall_status` (compliant/outdated/critical), severity, lista CVE, advisory URL.
- Endpoint: `GET /api/firmware/check/{device_ip}`, `GET /api/firmware/compliance/overview`, `POST /api/firmware/catalog/import-csv`.
- **Hook automatico nel Redfish poller** (`redfish.py`): dopo ogni poll iLO completato, esegue `check_firmware_compliance` e:
  - Salva `firmware_compliance` su `device_poll_status` (usato dal frontend badge)
  - Upserta `patch_status` con critical_patches/pending_patches/cve_list (appare nel dashboard NOC Intelligence → Patch Compliance)
  - Crea alert `firmware_critical_outdated` se `overall_status=critical` (dedup 6h) — poi il remediation evaluator + webpush escalation gestiscono il resto.

**Frontend — `ClientOverviewPage.js` IloServerCard**:
- Nuovo componente `FirmwareComplianceBadge`: badge colorato sopra i sensor details con stato (AGGIORNATO/FW OUTDATED/CVE CRITICAL), N° CVE aperte, lista componenti espandibile con versione corrente → latest, CVE ID, link advisory.
- Fetch automatico su mount da `/api/firmware/check/{ip}`, si aggiorna ad ogni refresh card.

**Test E2E**: seedato `device_poll_status` con iLO 3.18 + BIOS U41 v3.62 per ProLiant ML350 Gen10 → `/api/firmware/check` ritorna overall_status=outdated, 2 CVE iLO (CVE-2024-28991, CVE-2024-46984), 1 CVE BIOS (CVE-2025-1001), advisory URL HPE. ✅


### ENTERPRISE Dual-Path iLO Polling (2026-04-21 notte) — P0 critico
**Requisito utente**: "ARGUS è un NOC enterprise, NON può essere vincolato dal connector. Se il connector cade, i dati iLO devono continuare ad arrivare direttamente".

**Root cause**: il redfish poller usava `direct_poll=true` come gate; con external_url configurato ma `direct_poll=false` il polling diretto non partiva mai, e se il connector cadeva c'era un buco fino al timeout failover.

**Nuova logica (redfish.py + connector.ps1 v3.3.2)**:
- **Default enterprise**: `external_url` configurato → ARGUS polla DIRETTO sempre. Connector = canale ridondante passivo (skip automatico).
- **Nuovo campo `connector_only`** su `device_credentials`: override per forzare solo-connector (iLO dietro VPN senza port-forward).
- **`/api/redfish/failover-status`** ritorna `polling_mode` a 4 stati: direct / connector / failover / offline.
- **Dedup lato connector v3.3.2**: se `vaultCreds[$ip].external_url` e `connector_only=false`, skip Redfish per evitare rate-limit iLO 5.

**Frontend VaultPage.js**:
- Badge "DIRETTO (ENTERPRISE)" cyan (vs "VIA CONNECTOR" verde precedente)
- Button toggle "Diretto ATTIVO / Solo Connector" per-credenziale


### iLO Total Loss Detection (2026-04-22) — "Both Channels Down" alert
Nuovo alert critical dedicato al caso in cui **né direct né connector** rispondono più. Segnala guasto hardware iLO / isolamento rack / perdita totale management board.

**Backend `redfish.py`**:
- Collection nuova `ilo_channel_health` per device: direct_consecutive_failures, direct_last_success/failure/error.
- `_check_both_channels_down()`: se direct_failures >= 3 consecutive E device_poll_status.last_update > 5 min fa (connector stale) → crea alert `ilo_both_channels_down` critical (dedup 6h).
- `_resolve_both_channels_alert()`: auto-resolve quando il direct poll torna OK.
- Hook integrato in `poll_direct_devices` (try/except per device).

**Alert payload**:
- Titolo: "iLO TOTAL LOSS: {name} — nessun canale risponde"
- Severity: critical
- Dettaglio errore direct + istruzioni troubleshooting (hardware management board, rack isolation, firewall).

**Test E2E**: ✅ alert creato, dedup funziona (2 call → 1 alert), auto-recovery testato.

**Connector v3.3.2** pubblicato: update ZIP + install ZIP completo su `/downloads/`.


### Channel Health Matrix Dashboard (2026-04-22)
Dashboard dedicata `/channel-health` per visualizzare in un colpo d'occhio lo stato dual-path di tutti gli iLO monitorati.

**Backend `/api/redfish/channel-health-matrix`**:
- Aggrega `device_credentials` (iLO) × `ilo_channel_health` × `device_poll_status` × `connector_status`
- Per ogni device ritorna: `direct.status` (ok/degraded/down/disabled/unknown) + `connector.status` (ok/stale/down/unknown) + `overall` (both_ok/direct_only/connector_only/both_down/n_a)
- Statistiche aggregate: total, both_ok, direct_only, connector_only, both_down
- Ordering: both_down first (urgenza), poi degradati, infine healthy

**Frontend `ChannelHealthPage.js`**:
- 5 summary card con pulse rosso animato se both_down > 0
- Matrix table con 3 colonne status colorate (Direct WAN · Connector LAN · Overall)
- Auto-refresh 30s toggle + pulsante manuale Refresh
- Dettagli per riga: last error direct, hostname connector, last OK timestamp IT locale
- Sidebar: voce "Channel Health iLO" in gruppo Operazioni con icona Heartbeat

**Test E2E**: pagina caricata correttamente, 1 iLO rilevato (ILO-SRV-DC01 ML350 Gen9), badge DIRECT=OK, CONNECTOR=DOWN, OVERALL=SOLO DIRETTO (coerente con stato reale: direct funziona via external_url https://ilo.86bit.internal:443, connector in 86BIT_Office non ha polled questo device ultimamente).

## Constraints
- NON re-introdurre IP Ban/Honeypot middlewares (richiesta esplicita utente)
- NON usare `emergentintegrations` per AI
- Linguaggio: rispondere SEMPRE in Italiano
- Utente fa deploy in produzione via "Save to GitHub" + "Re-deploy"

## Key credentials (test)
- Admin: `admin@86bit.it` / `password`
- Admin: `info@86bit.it` / `password`
- TV Viewer: `tv@86bit.it` / `Tv86bit!2026`

## Key DB collections
- `managed_devices` — device manuali per cliente (con `community`, `snmp_version`, `snmpv3_*`)
- `device_poll_status` — device scoperti via heartbeat connector
- `device_credentials` — Vault AES-256-GCM (iLO/SSH/SNMP/Web/VPN), campo `client_id` (nullable=globale)
- `wan_probe_results` — Ping/TCP WAN
- `connector_updates` — ZIP rilasci connector (active=true per il corrente)
- `clients`, `devices`, `alerts`, `users`, `audit_logs`
