# CHANGELOG — 86BIT ARGUS Center

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
