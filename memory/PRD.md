# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: Python 3.11, FastAPI, MongoDB (Motor), AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, Recharts, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish, LLDP, MAC Table

## Funzionalita Implementate

### Core
- [x] Auth JWT + 2FA TOTP + Ruoli (admin/operator/viewer)
- [x] SNMP/Ping/Redfish monitoring
- [x] Alert + correlazione + WebSocket
- [x] Credential Vault AES-256-GCM

### Mappa Enterprise React Flow
- [x] Drag-and-drop interattivo con salvataggio layout
- [x] Topologia 6-Layer + LLDP/MAC Discovery + Port Speed

### Dashboard Metriche Zabbix-style
- [x] SLA Gauge, Change Timeline, Uptime Heatmap, Latency Chart

### Report PDF (PRTG-style)
- [x] Report professionale per cliente

### TV Dashboard NOC
- [x] Pagina fullscreen /tv, layout 3 colonne, allarmi sonori

### Gestione Stampanti SNMP
- [x] Dashboard stampanti, barre toner, avvisi automatici

### Vulnerability Assessment (COMPLETATO)
- [x] Dashboard VA con Security Score, Knowledge Base, Remediation
- [x] Scansione Remota via heartbeat pending_commands
- [x] Report PDF esaustivo 11 pagine
- [x] Progresso real-time con barra animata

### Grafici Trend (NUOVO - 13/04/2026)
- [x] Pagina /trends con 4 grafici Recharts
- [x] Disponibilita Rete (AreaChart), Latenza Media (LineChart)
- [x] Score VA nel tempo (AreaChart), Alert per giorno (BarChart)
- [x] Selettore periodo: 24h, 3gg, 7gg, 30gg

### Auto-Discovery Rete (NUOVO - 13/04/2026)
- [x] Pagina /discovery con scansione rete da connettore
- [x] Approvazione/Ignora dispositivi scoperti
- [x] Polling automatico stato durante scansione
- [x] Visualizzazione dispositivi gia gestiti

### Soglie Alert Personalizzabili (NUOVO - 13/04/2026)
- [x] Pagina /thresholds con 4 gruppi (Connettivita, Hardware, Bandwidth, Stampanti)
- [x] Soglie configurabili per cliente: ping, packetloss, CPU, RAM, toner, bandwidth
- [x] Pulsante Salva con feedback visivo

### Manutenzione Programmata (NUOVO - 13/04/2026)
- [x] Pagina /maintenance con CRUD completo
- [x] Creazione finestre con titolo, date, dispositivi coinvolti
- [x] Soppressione automatica alert durante manutenzione
- [x] Stato visivo: In Corso (amber), Programmata (blue), Completata (gray)
- [x] API /api/maintenance/active/{client_id} per alert engine

### Monitoraggio Bandwidth (NUOVO - 13/04/2026)
- [x] Pagina /bandwidth con riepilogo interfacce per dispositivo
- [x] Metriche: IN/OUT bps, utilizzo %, velocita interfaccia
- [x] Grafici storici AreaChart per interfaccia
- [x] Backend: raccolta ifInOctets/ifOutOctets, retention 7 giorni

### SOC AI Correlation (NUOVO - 13/04/2026)
- [x] Pagina /correlation con analisi intelligente rule-based (5 pattern)
- [x] **Integrazione Gemini AI** (gemini-2.5-flash via emergentintegrations)
- [x] Pulsante "Analisi Gemini AI" che analizza: dispositivi, alert, backup, manutenzione
- [x] Risposta strutturata: overall_status, risk_score, correlazioni, raccomandazioni, pattern
- [x] Campo domanda libera per interrogare l'AI sulla rete
- [x] Storico analisi AI con persistenza MongoDB
- [x] Persona SOC analyst in italiano con raccomandazioni operative
- [x] Pannello risultati con badge severita, confidenza %, azioni consigliate

### Portale Cliente Multi-tenant (NUOVO - 13/04/2026)
- [x] Pagina pubblica /portal (no auth)
- [x] Dashboard dedicata con SLA 30gg, dispositivi, alert
- [x] Accesso tramite ID cliente
- [x] Vista dispositivi + alert recenti

### Monitoraggio Backup (NUOVO - 13/04/2026)
- [x] Integrazione Hornetsecurity VM Backup (ex Altaro) v9.1 via REST API locale
- [x] PowerShell `backup_monitor.ps1`: Auth API, lista VM, stato backup, fallback Event Log
- [x] Hyper-V info: stato VM, CPU, RAM, uptime, checkpoint, replica
- [x] Dashboard `/backup`: card riepilogative (5 VM, OK/Warning/Falliti/Mancanti)
- [x] Lista VM con stato backup, dimensione, date, stato Hyper-V
- [x] Modal dettaglio VM con storico alert
- [x] Grafico storico backup (stacked BarChart 7gg)
- [x] Alert automatici su backup falliti (critical) o mancanti (high)
- [x] Auto-resolve alert quando backup torna OK
- [x] Endpoint `/api/backup/summary-all` per integrazione TV Dashboard

### Connettore Windows (v2.5.0+)
- [x] Servizio NSSM + Network Discovery + Auto-aggiornamento
- [x] Polling stampanti + Esecuzione remota VA Scan

## Key API Endpoints
- GET `/api/trends/{client_id}` - Trend storici
- GET/POST `/api/thresholds/{client_id}` - Soglie personalizzabili
- CRUD `/api/maintenance/{client_id}` - Finestre manutenzione
- GET `/api/maintenance/active/{client_id}` - Check manutenzione attiva
- GET `/api/correlation/{client_id}` - Analisi correlazione
- GET `/api/bandwidth/summary/{client_id}` - Riepilogo bandwidth
- GET `/api/bandwidth/{client_id}/{device_ip}` - Storico bandwidth
- POST `/api/bandwidth/process-poll` - Ricezione dati dal connettore
- POST `/api/discovery/approve` - Approva dispositivo scoperto
- POST `/api/discovery/dismiss` - Ignora dispositivo scoperto
- GET `/api/portal/{client_id}` - Portale cliente (pubblico)

### Security Hardening - 21 Protezioni (COMPLETATO - 13/04/2026)
**Fase 1 - 11 Protezioni Base:**
- [x] Brute Force Protection (10 tentativi/5min per IP → 429, lockout 5 min → 423)
- [x] Rate Limiting Globale (Sliding Window 600 req/min per IP)
- [x] 2FA/TOTP (pyotp, Google Authenticator)
- [x] Password Security (Argon2id, 64MB, parallelismo 4)
- [x] Session Management (TTL 5 min, max 500 sessioni in-memory)
- [x] Crittografia Dati Sensibili (AES-256-GCM)
- [x] Security Headers (HSTS, CSP, X-Frame-Options, X-Permitted-Cross-Domain-Policies)
- [x] CORS (no wildcard *, preflight cache 600s)
- [x] Request Timeout (20s/45s/120s/180s → 504)
- [x] Audit Logging (pulizia auto >90 giorni)
- [x] Cache Control Headers (no-store auth, private max-age=0 altri)
**Fase 2 - 10 Protezioni Avanzate:**
- [x] IP Whitelist Admin (configurabile da UI)
- [x] Session Invalidation Remota (kill sessioni con un click)
- [x] Notifiche Login Sospetti (alert su IP nuovi)
- [x] Password Policy Enforcement (min 12 char, scadenza 90gg)
- [x] CSRF / Origin Verification (POST/PUT/DELETE)
- [x] API Key Rotation (scadenza 90gg, rotazione da dashboard)
- [x] Rilevamento IP Anomali (traccia IP noti per utente)
- [x] Honeypot Endpoints (20+ percorsi fake → auto-ban 24h)
- [x] Request Body Size Limit (10MB/50MB → 413)
- [x] SIEM Log Export (JSON/CSV per Splunk/ELK)
- [x] Security Dashboard frontend con gestione IP Whitelist e Sessioni

### SNMP v3 Support (COMPLETATO - 13/04/2026)
- [x] Modello ManagedDevice esteso con campi SNMPv3 (snmp_version, USM credentials)
- [x] API PUT /connector/{client_id}/managed-devices/{device_id}/snmp per switch v1/v2c/v3
- [x] Connettore PowerShell: Engine Discovery, Key Localization (RFC 3414)
- [x] Auth: HMAC-MD5, HMAC-SHA1 con password-to-key 1MB expansion
- [x] Privacy: DES-CBC (RFC 3414), AES-128-CFB (RFC 3826)
- [x] Poll-DeviceV3 con supporto completo interfacce e metriche
- [x] Frontend SnmpConfigPanel con selector v1/v2c/v3 e campi USM condizionali
- [x] Pannello integrato nel DeviceDetailPanel per dispositivi managed

### Navigazione Sidebar Redesign (COMPLETATO - 13/04/2026)
- [x] Framer Motion per animazioni smooth collapsible groups (height 0→auto)
- [x] Active state blue (#007AFF) con indicatore 2px left border
- [x] Icon opacity transitions (0.6→1 su active)
- [x] Badge pulse animation per alert critici (>10)
- [x] Auto-open del gruppo contenente la pagina attiva
- [x] Touch target ottimizzati mobile (min 44px)
- [x] Overlay mobile con blur 8px e animazione fade
- [x] Scrollbar custom sottile nella nav
- [x] data-testid su tutti gli elementi interattivi

### PWA Migliorata (COMPLETATO - 13/04/2026)
- [x] Icona professionale NOC (radar/shield) per 192x192, 512x512, apple-touch-icon, favicon
- [x] Service Worker v3: Push notifications handler, stale-while-revalidate, offline fallback
- [x] Pagina offline dedicata con auto-reload su riconnessione
- [x] Manifest con shortcuts (Dashboard, Alert, Stato Rete) e display standalone
- [x] PwaProvider context (install, notifiche, online/offline detection)
- [x] Banner installazione PWA interattivo
- [x] Banner richiesta permesso notifiche
- [x] Indicatore offline visivo (barra ambra fissa)
- [x] Background sync per azioni pendenti offline

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
- [ ] Notifiche Telegram (quando utente fornira bot token)
### P2
- [ ] SOC AI con LLM avanzato (fine-tuning su dati specifici del cliente)
- [ ] Twilio Voice/SMS per alert critici
- [ ] SNMP v3, LDAP
- [ ] App Mobile React Native collegata al backend

## Test Reports
- iteration_37: Remote VA Scan (100%)
- iteration_38: VA PDF Report (100%)
- iteration_39: 7 nuove feature (100% - Backend 24/24, Frontend 7/7)
- iteration_40: Backup Monitoring (100% - Backend 13/13, Frontend completo)
- iteration_41: SOC AI Gemini (100% - Backend 10/10, Frontend verificato)
- iteration_42: Security Hardening 11 protezioni (100% - Backend 11/11, Frontend verificato)
- iteration_43: Security Hardening 21 protezioni totali (100% - Backend 25/25, Frontend verificato)
- iteration_44: SNMP v3 Support (100% - Backend 12/12, Frontend componente verificato)
- iteration_45: PWA Migliorata (100% - Tutti gli asset e componenti verificati)
- iteration_46: Sidebar Navigation Redesign (100% - Framer Motion, active states, badges verificati)
