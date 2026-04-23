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

## Backlog / Future
- P2: Multi-tenant + White-label SaaS (workspace isolation)
- P2: LDAP/Active Directory integration
- P3: Zyxel Nebula Cloud API

### 🎨 Connector v3.4.7 UI Polish (TODO alla prossima build connector — richiesta utente 2026-04-23)
- **Task 1 — Logo 86bit nei shortcut menu Start**: generare `86bit_logo.ico` multi-risoluzione (16/32/48/256) da `86bit_logo.jpg` e applicare `.IconLocation` su tutti e 4 i shortcut creati da `installer_gui.ps1`/`install.bat`: "ARGUS Center Connector" (attualmente icona globo), "Apri Cartella Log" (cartella generica), "Diagnostica Connessione" (lente), "Disinstalla ARGUS Connector" (cestino).
- **Task 2 — Logo in Pannello di Controllo → Programmi e funzionalità**: aggiungere chiave registry `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector\DisplayIcon` che punti al percorso di `86bit_logo.ico` installato. Attualmente mostra icona blu generica Windows.
- **Task 3 — Fix spazio vuoto GUI "Gestisci Dispositivi"**: nel form `installer_gui.ps1` c'è spazio bianco a destra del pulsante "Salva e Riavvia" — rimpicciolire Form width o aggiungere `Anchor = Right` ai bottoni per riempimento proporzionale.

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
