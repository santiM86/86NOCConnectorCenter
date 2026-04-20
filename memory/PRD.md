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

## Backlog / Future
- P2: Multi-tenant + White-label SaaS (workspace isolation)
- P2: LDAP/Active Directory integration
- P3: Zyxel Nebula Cloud API

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
