# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade "ARGUS Center" per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

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

### Gestione Utenti (AGGIORNATO - 14/04/2026)
- [x] CRUD utenti completo (crea, modifica ruolo, elimina)
- [x] Toggle attivo/disattivato (is_active)
- [x] Sblocca utente (brute force unlock)
- [x] Setup/Reset 2FA (TOTP)
- [x] Check is_active al login (403 se disattivato)
- [x] Stats: Totale, Attivi, MFA Attivo, Admin
- [x] Ricerca per nome/email
- [x] Utenti registrati: 4 (Marco Santinelli admin, Admin admin, TV Monitor viewer, TV Dashboard Test viewer)

### Mappa Enterprise React Flow
- [x] Drag-and-drop interattivo con salvataggio layout
- [x] Topologia 6-Layer + LLDP/MAC Discovery + Port Speed

### Dashboard Metriche Zabbix-style
- [x] SLA Gauge, Change Timeline, Uptime Heatmap, Latency Chart

### Report PDF (PRTG-style)
- [x] Report professionale per cliente

### TV Dashboard NOC
- [x] Pagina fullscreen /tv, layout Control Room, allarmi sonori

### Gestione Stampanti SNMP
- [x] Dashboard stampanti, barre toner, avvisi automatici

### Vulnerability Assessment
- [x] Dashboard VA, Scansione Remota, Report PDF, Progresso real-time

### Grafici Trend
- [x] Pagina /trends con 4 grafici Recharts, selettore periodo

### Auto-Discovery Rete
- [x] Pagina /discovery con scansione e approvazione

### Soglie Alert Personalizzabili
- [x] Pagina /thresholds con 4 gruppi configurabili

### Manutenzione Programmata
- [x] Pagina /maintenance con CRUD e soppressione alert

### Monitoraggio Bandwidth
- [x] Pagina /bandwidth con riepilogo interfacce

### SOC AI Correlation
- [x] Integrazione Gemini AI (gemini-2.5-flash)

### Portale Cliente Multi-tenant
- [x] Pagina pubblica /portal (no auth)

### Monitoraggio Backup
- [x] Integrazione Hornetsecurity VM Backup + Hyper-V

### Security Hardening - 21 Protezioni
- [x] Brute Force, Rate Limiting, 2FA/TOTP, Argon2id, Session Management
- [x] AES-256-GCM, Security Headers, CORS, Request Timeout, Audit Logging
- [x] IP Whitelist, Session Invalidation, Login Sospetti, Password Policy
- [x] CSRF, API Key Rotation, IP Anomali, Honeypot, Body Size Limit, SIEM Export

### SNMP v3 Support
- [x] USM credentials, Auth HMAC-MD5/SHA1, Privacy DES-CBC/AES-128-CFB

### Connector Hardening
- [x] Log rotation, Memory cleanup, Job health check

### Scalabilita' Infrastruttura
- [x] 65 indici MongoDB + 12 TTL, GZip, Connection pooling, Task Coordinator

### Mobile Dashboard
- [x] Vista client-centrica per telefono

### Monitoraggio WAN Esterno
- [x] Probe Ping/TCP dal cloud

### Navigazione Sidebar + PWA
- [x] Framer Motion, Service Worker v3, offline fallback

### Login Page Branding (COMPLETATO - 14/04/2026)
- [x] Icona ARGUS scudo con punto esclamativo
- [x] Footer Verdana full-width dati fiscali
- [x] Layout responsive senza scroll (100vh)
- [x] Footer mobile compatto

## Key API Endpoints
- GET/POST `/api/admin/users` - Lista/Crea utenti
- PUT `/api/admin/users/{id}` - Aggiorna utente
- PUT `/api/admin/users/{id}/toggle-active` - Attiva/Disattiva
- PUT `/api/admin/users/{id}/unlock` - Sblocca brute force
- DELETE `/api/admin/users/{id}` - Elimina utente
- POST `/api/admin/users/{id}/reset-2fa` - Reset 2FA
- POST `/api/admin/users/{id}/force-2fa` - Setup 2FA
- POST `/api/admin/users/{id}/confirm-2fa` - Conferma 2FA

## Backlog
### P1
- [ ] Notifiche Telegram (quando utente fornira bot token)
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
### P2
- [ ] Multi-tenant e White-labeling (SaaS per rivendita MSP)
- [ ] Integrazione LDAP/Active Directory
### P3
- [ ] Zyxel Nebula Cloud API
- [ ] App Mobile React Native

## Credenziali Test
- Admin: admin@86bit.it / password
- Admin: info@86bit.it / password (Marco Santinelli)
- TV Monitor: tv@86bit.it / Tv86bit!2026
- TV Dashboard Test: tvdash@86bit.it / Tv86bit!2026
