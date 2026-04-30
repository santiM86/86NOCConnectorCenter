# CHANGELOG — 86BIT ARGUS Center

## 2026-04-30 — Tenant→Client Mapping Reverse View (backend v3.5.32)

### 🔄 Modalita` "Per tenant Hornetsecurity"
Aggiunta vista alternativa per il mapping cliente↔tenant: tabella centrata sui
44 tenant Hornetsecurity rilevati, con dropdown "Associa cliente ARGUS" per
ciascuno. Piu` rapida quando hai molti tenant da mappare (vs flow per-cliente).

**Frontend** `pages/HornetsecuritySettingsPage.js`:
- Nuovo toggle vista: **"Per tenant Hornetsecurity"** (default) | "Per cliente ARGUS"
- Componente `TenantMappingTable` con:
  - Filtri: Tutti / Da mappare / Mappati / Con backup falliti
  - Colonne: Tenant + dominio + workload count + falliti + cliente associato + azioni
  - Auto-suggerimento cliente Argus (★ in dropdown) per nome simile/identico
  - Edit inline con `<select>` (lista clienti ordinata, suggested in cima)
  - Action button "Associa" (se non mappato) o "Modifica/Cestino" (se mappato)
  - Reverse mapping internamente: tenant → client_id derivato dalla lista mappings
- Componente `TenantMappingRow` gestisce add/remove tenant da clients in modo
  transazionale: rimuove dal vecchio cliente + aggiunge al nuovo

## 2026-04-30 — Hornetsecurity Global Config + Tenant Mapping (backend v3.5.31)

### 🌍 Refactor a config globale + mapping multi-tenant
Una sola API key copre tutti i tenant del partner Hornetsecurity (1 chiamata API
ogni 30 min vs N chiamate per cliente). Mapping cliente ARGUS ↔ tenant
Hornetsecurity multi-valore con auto-suggest fuzzy.

**Backend** `routes/hornetsecurity_backup.py`:
- Nuova collection `hornetsecurity_global_config` (singolo doc `_id="global"`)
- Endpoint admin: `GET/PUT/DELETE /api/admin/hornetsecurity/global-config`,
  `POST /api/admin/hornetsecurity/test`, `POST /api/admin/hornetsecurity/poll`,
  `GET /api/admin/hornetsecurity/tenants` (lista tenant con stats aggregate)
- Endpoint mapping: `GET/PUT /api/clients/{id}/backup/hornetsecurity/mapping`
  salva `clients.hornetsecurity_tenants` (lista nomi tenant)
- Funzione `_resolve_client_tenants()`: filtro a lettura tramite mapping
- `_persist_poll_results_global()`: persistenza globale (chiave: tenant + workload_id)
- Parser aggiornato per layout reale Hornetsecurity Operational Report:
  `{statistics: [{customerName, office365Organisation, objectTypeBackedUp,
  objectName, objectDetails, backupState, backupStateEnum, lastBackup,
  lastErrorMessage}]}`
- Status mapping: Protected→success, Last Backup Failed→failed,
  First Backup In Progress→in_progress, Excluded→excluded,
  No <workload>→not_applicable
- Backward compat: endpoint per-cliente legacy mantenuti

**Backend** `services/hornetsecurity_poller.py`:
- Tick gestisce sia config globale (preferita) che config per-cliente legacy
- Solo "failed" reali generano alert (non "not_applicable" / "excluded" /
  "in_progress")

**Frontend** `pages/HornetsecuritySettingsPage.js` (NEW):
- Pagina admin Settings → Hornetsecurity 365 Backup
- Connessione API (URL + key cifrata + polling interval) con Test/Poll Now
- Tabella mapping clienti ARGUS ↔ tenant: dropdown multi-select con
  auto-suggest fuzzy (nome cliente vs nome tenant)
- Sezione "tenant non mappati" per scoprire clienti Hornetsecurity senza
  controparte ARGUS
- Stats real-time per tenant: workload totali, falliti, protetti

**Frontend** `pages/ClientOverviewPage.js` (BackupTab refactor):
- Ora legge config globale invece di per-cliente
- Stati: backend obsoleto / config assente (CTA Settings) / mapping mancante
  (CTA mapping) / dati visibili
- Filtro multi-tenant nella pagina cliente (utile per clienti con piu` domini)

**Risultato test E2E con dati reali utente**:
- 4377 workload, 44 tenant rilevati, 196 backup falliti reali, 1231 protetti
- Mapping cliente ↔ tenant "Aldegani" → 111 workload filtrati correttamente
- Storage trend non disponibile (Operational Report Hornetsecurity non include
  size per workload — limite del prodotto)

## 2026-04-30 — Hornetsecurity 365 Total Backup Integration (backend v3.5.30)

### 🛡️ Fase 1 — Cloud Microsoft 365 Backup Monitoring
Integrazione end-to-end con Hornetsecurity 365 Total Backup REST API (custom-generated
endpoint + X-API-KEY header), per monitorare backup di Mailbox, OneDrive,
SharePoint, Teams attraverso tutti i tenant clienti registrati nel Control Panel MSP.

**Backend** `routes/hornetsecurity_backup.py` (NEW):
- `GET/PUT/DELETE /api/clients/{client_id}/backup/hornetsecurity/config` — CRUD
  configurazione per cliente. API key crittografata via `security_manager` (Fernet)
  e mai esposta in chiaro. Mostrata UI come `****1234`.
- `POST /api/clients/{client_id}/backup/hornetsecurity/test` — chiamata di test
  senza persistenza, ritorna count workload + sample.
- `POST /api/clients/{client_id}/backup/hornetsecurity/poll` — forza polling
  immediato (rispetta rate limit 5min Hornetsecurity, ritorna 429 se troppo presto).
- `GET /api/clients/{client_id}/backup/hornetsecurity/status` — lista ultimi
  workload + aggregati per status/type + count alert attivi.
- `GET /api/clients/{client_id}/backup/hornetsecurity/storage-trend?days=N` — trend
  storage per tenant negli ultimi N giorni (default 30).
- `GET /api/clients/{client_id}/backup/hornetsecurity/alerts` — alert backup falliti.
- Parser JSON robusto su 3 layout possibili (camelCase nested, PascalCase flat,
  generic data array). Verificato in unit test in-session.

**Backend** `services/hornetsecurity_poller.py` (NEW):
- APScheduler job ogni minuto che itera `hornetsecurity_configs`, calcola se
  `poll_interval_minutes` è scaduto da `last_polled_at`, esegue HTTP GET e
  persiste workload/storage/alert.
- Auto-deduplicate alerts: 1 alert aperto per workload, auto-resolve quando lo
  status torna success.
- Failed-poll tracking: salva `last_poll_status` + `last_poll_error` per UI.

**MongoDB collections** (NEW):
- `hornetsecurity_configs` — { client_id, api_url, api_key_enc, poll_interval_minutes, enabled, last_polled_at, last_poll_status }
- `backup_job_status` — { client_id, tenant, workload_id, workload_type, status, last_backup_time, size_bytes, error, captured_at }
- `backup_storage_history` — { client_id, tenant, size_bytes, recorded_at }
- `backup_alerts` — { client_id, tenant, workload_id, severity, message, resolved, last_seen }

**Frontend** `ClientOverviewPage.js`:
- Tab **Backup** completamente riprogettata:
  - Setup wizard se non configurato (CTA con istruzioni Control Panel)
  - Header config con URL mascherato, key preview, polling interval, last poll
  - 4 stat box (OK, Failed, Active alerts, Workload types)
  - Storage trend card per tenant con delta % e size in MB/GB/TB
  - Filtri stato + tipo workload (mailbox/onedrive/sharepoint/teams)
  - Tabella workload con stato colorato, last backup, size, error message
- Pulsanti "Poll Ora" + "Test" + "Modifica" + "Elimina" con permission check admin
- Dialog config: URL + key (password input) + polling interval + enabled
- Fallback graceful se backend non aggiornato (banner amber con istruzioni update)

**Rate limit safety**:
- Schedule minimo 5 min, default 30 min
- Anti-flood manuale 300s tra `/poll` consecutivi
- HTTP 429 esplicito al frontend con messaggio chiaro

## 2026-04-30 — Profile Re-match Engine (backend v3.5.29)

### 🎯 Auto-aggancio profili vendor dopo fix SNMP
Risolve il caso in cui i device erano stati ingestati prima che lo SNMP funzionasse
correttamente (sysObjectID/sysDescr vuoti): ora che i metadati arrivano popolati, il
fingerprint veniva saltato perché il matcher richiedeva `prev_status is None`.

**Backend** `routes/connector.py` (device-report ingest):
- Retry policy estesa: il fingerprint si attiva ora anche quando `profile_key`
  è assente E il device ha un identificatore (sys_object_id o sys_descr). NON
  sovrascrive profili impostati manualmente (`profile_auto_matched=false`).
- Log esplicita la ragione: `[new]` | `[descr-changed]` | `[missing-profile-retry]`

**Backend** `routes/devices.py` — nuovi endpoint:
- `POST /api/clients/{client_id}/rematch-profiles` — bulk rematch su tutti i device
  del cliente. Ritorna summary `{total, matched, skipped, details[]}`.
- `POST /api/clients/{client_id}/devices/{device_ip}/rematch-profile` — rematch
  singolo device.
- Funzione interna `_rematch_one()` con safety: skip profili manuali, skip device
  senza identificatori.

**Frontend** `ClientOverviewPage.js`:
- Nuovo pulsante **"🔎 Riconosci profili"** (cyan) accanto a "Rimuovi scomparsi",
  chiama il bulk endpoint e mostra toast dettagliato con nomi/vendor matchati.

**Fingerprint verification** (unit test in-session):
- Switch HP 5130 EI (sysObjectID 1.3.6.1.4.1.11.2.3.7.11.161) → `hpe_comware` ✓
- UPS Xanto S 3000 (sysDescr) → `xanto_ups` ✓
- Synology NAS DSM 7.2 → `synology_dsm` ✓

## 2026-04-30 — Self-Updater hardening P1 (backend v3.5.28)

### 🔧 Fix definitivo loop 404 aggiornamento backend in produzione
**Backend** `routes/system_admin.py`:
- Nuova funzione `_resolve_package_url()`: risolve URL del tarball in cascata
  1. `payload.package_url` (custom) → 2. `https://{host}/downloads/...` (locale) → 3. `ARGUS_UPDATE_ARTIFACT_BASE_URL` (fallback remoto)
- Nuova funzione `_head_check()`: HEAD preflight con validazione content-length > 100 KB
  (intercetta le pagine HTML di errore servite come 200)
- `POST /api/admin/system/self-update` fa ora il **preflight check PRIMA** di spawnare
  il subprocess; se l'URL non è raggiungibile ritorna `424 Failed Dependency` con
  messaggio esplicito (prima restava bloccato 10s dentro `curl` del runner)
- Auto-retry sul fallback remoto se il locale fallisce (e env var è configurata)
- Nuovo endpoint `GET /api/admin/system/self-update/resolve-url?url=...`:
  mostra URL risolto, sorgente, reachable, HTTP status, content-length
- Risposta `/version` ora include `update_artifact_fallback` per UI

**Frontend** `WireGuardPage.js`:
- Dialog self-update: nuovo pulsante **"Pre-check URL"** che valida raggiungibilità
  prima di lanciare l'update, con toast dettagliato (size MB / HTTP status)
- Toast post-avvio mostra la sorgente risolta: "custom", "CDN locale" o
  "fallback CDN remoto"
- Nota esplicativa aggiornata con l'ordine di risoluzione + env var corrente

**Env var opzionale** (P1 rollout):
- `ARGUS_UPDATE_ARTIFACT_BASE_URL=https://<cdn>`: base URL fallback per artefatti
  quando il CDN locale non è ancora sincronizzato

## 2026-04-27 — Silence Alerts + Printer auto-classify + Cleanup bidirezionale
- Flag `alerts_silenced` su device, intercettato da 8 watcher backend
- Auto-classifier stampanti via regex + Printer-MIB sysObjectID
- `/sync-active-devices` (HMAC) + `/cleanup-stale-devices` per pulizia bulk
- Fix cestino unificato (poll_ip multi-source)
- Connector v3.5.25 con heartbeat reverse-sync

## 2026-04-22 — FASE B COMPLETATA: Vendor-Specific SNMP Monitoring + RMT HTTP Polling

### 🚀 Fase B — Vendor Alerts (Connector v3.4.4)
**Backend** `routes/connector.py`:
- `_check_device_thresholds` esteso con block Fase B (righe ~770-900)
- Alert auto-generati da `vendor_metrics`:
  - **Synology**: `raidStatus` (11=Degraded, 12=Crashed), `diskTemperature` (table walk)
  - **APC UPS**: `upsBatteryStatus` (3=Low, 4=Depleted), `upsOutputSource` (5=On Battery), `upsEstimatedChargeRemaining` %
  - **Fortinet**: `fgVpnTunnelStatus` (table, 1=down), `fgHaStatsSyncStatus` (0=out-of-sync)
- `vendor_metrics` salvato in `device_poll_status` per frontend
- Backend check fallback senza profilo: alert RAID/UPS critical sempre generati

**Connector v3.4.4** (SHA `c8b14ac3...06262d4`, 297 KB):
- Nuova funzione `Poll-VendorOids` in `connector.ps1`
- Legge `$dev.vendor_snmp_targets` (scalars + tables) dal heartbeat
- Esegue `Get-SnmpValue` per scalars, `Get-SnmpWalk` per tables
- Allega risultati come `vendor_metrics` in `/connector/device-report`
- Testato end-to-end via curl: 4 alert creati correttamente

### 🖥️ RMT HTTP Polling (connector v3.4.3)
- `routes/console_rmt_v2.py` — endpoint header-based auth (bypass WAF path issues)
- `routes/console_rmt_http.py` — SSE + polling fallback
- `RemoteBrowserModal.js` — EventSource + axios polling, canvas HTML5
- `remote_browser.ps1` — Edge CDP headless screencast, 2 runspace (CDP reader + input poller)
- Fix Edge SYSTEM service: `--no-sandbox`, `--disable-dev-shm-usage`, user-data-dir in `C:\Windows\Temp`

### 🔧 Fix stabilità precedenti
- `Register-ServiceWatchdog` auto-recovery (v3.3.7)
- Regex HTML5 unquoted per inline CSS/JS (v3.3.6)
- Install-Update 4 metodi fallback + verifica PID-alive (v3.3.6)

## ⏭️ Prossimi step backlog
- **UI Dashboard per vendor_metrics**: pagine device-details con tab Volumi/RAID (Synology), Battery/Load (UPS), VPN/HA (Fortinet)
- **Notifiche Telegram/Email** per alert vendor-specific
- **Analytics MTTA/MTTR/MTTD**
- **Multi-tenant white-label**
- **Vulnerability Assessment CVE/EoL**

## 📅 Storia precedente
Vedi PRD.md per Web Console V4, Device Profiles 13-vendor, Runbook Auto-Match, Dynamic Port Whitelist.
