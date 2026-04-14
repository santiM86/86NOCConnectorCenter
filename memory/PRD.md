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

### Grafici Trend
- [x] Pagina /trends con 4 grafici Recharts
- [x] Disponibilita Rete, Latenza Media, Score VA, Alert per giorno
- [x] Selettore periodo: 24h, 3gg, 7gg, 30gg

### Auto-Discovery Rete
- [x] Pagina /discovery con scansione rete da connettore
- [x] Approvazione/Ignora dispositivi scoperti

### Soglie Alert Personalizzabili
- [x] Pagina /thresholds con 4 gruppi configurabili per cliente

### Manutenzione Programmata
- [x] Pagina /maintenance con CRUD completo
- [x] Soppressione automatica alert durante manutenzione

### Monitoraggio Bandwidth
- [x] Pagina /bandwidth con riepilogo interfacce per dispositivo

### SOC AI Correlation
- [x] Integrazione Gemini AI (gemini-2.5-flash)
- [x] Analisi strutturata con risk_score, correlazioni, raccomandazioni

### Portale Cliente Multi-tenant
- [x] Pagina pubblica /portal (no auth)

### Monitoraggio Backup
- [x] Integrazione Hornetsecurity VM Backup + Hyper-V
- [x] Dashboard /backup con card riepilogative e grafici storici

### Security Hardening - 21 Protezioni
- [x] Brute Force, Rate Limiting, 2FA/TOTP, Argon2id, Session Management
- [x] AES-256-GCM, Security Headers, CORS, Request Timeout, Audit Logging
- [x] IP Whitelist, Session Invalidation, Login Sospetti, Password Policy
- [x] CSRF, API Key Rotation, IP Anomali, Honeypot, Body Size Limit, SIEM Export

### SNMP v3 Support
- [x] USM credentials, Auth HMAC-MD5/SHA1, Privacy DES-CBC/AES-128-CFB

### Connector Hardening
- [x] Log rotation, Memory cleanup, Job health check, Timer differenziati

### Scalabilita' Infrastruttura
- [x] 65 indici MongoDB + 12 TTL, GZip, Connection pooling, Task Coordinator

### Mobile Dashboard
- [x] Vista client-centrica per telefono con health ring e metriche

### Monitoraggio WAN Esterno
- [x] Probe Ping/TCP dal cloud, diagnosi automatica, alert su status change

### TV Dashboard "Control Room"
- [x] Layout griglia adattiva client-centrica, semaforo visivo

### Navigazione Sidebar
- [x] Framer Motion, active states, badges, touch target mobile

### PWA
- [x] Service Worker v3, offline fallback, push handler, install banner

### Login Page Branding (COMPLETATO - 14/04/2026)
- [x] Icona ARGUS: scudo con punto esclamativo (!) in indaco/cyan
- [x] Footer Verdana full-width con dati fiscali 86BIT centrati
- [x] "Alert Management System" allineato sotto "ARGUS Center"
- [x] Rimosso overlay "SYSTEM // OPERATIONAL" dal background
- [x] Easter egg (!) con font Verdana maiuscoletto

## Backlog
### P1
- [ ] Notifiche Telegram (quando utente fornira bot token)
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
### P2
- [ ] Multi-tenant e White-labeling (SaaS per rivendita MSP)
- [ ] Integrazione LDAP/Active Directory
- [ ] SOC AI con LLM avanzato (fine-tuning)
### P3
- [ ] Zyxel Nebula Cloud API
- [ ] App Mobile React Native
- [ ] Twilio Voice/SMS per alert critici

## Test Reports
- iteration_37-51: Tutte le major features passate con successo
- Login Page: Verificato via screenshot + curl (login funzionante)

## Credenziali Test
- Admin: admin@86bit.it / password
- TV Viewer: tv@86bit.it / Tv86bit!2026
