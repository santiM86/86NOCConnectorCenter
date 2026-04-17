# ARGUS Center - PRD

## Descrizione
Piattaforma NOC enterprise "ARGUS Center" per monitoraggio dispositivi di rete. Connettore Windows nativo PowerShell.

## Architettura
- Backend: Python 3.11, FastAPI, MongoDB, google-generativeai (Gemini)
- Frontend: React, TailwindCSS, Shadcn UI, Recharts, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish

## Funzionalita Implementate

### Dashboard NOC Control Room (NUOVO - 17/04/2026)
- [x] Griglia clienti con card compatte: WAN, Dispositivi, Connettore, Backup, Stampanti, ISP
- [x] KPI globali: Clienti, Problemi, Alert, Dispositivi
- [x] Banner alert critici urgenti
- [x] Ricerca + filtri (Tutti/Problemi/OK)
- [x] Auto-refresh 30s, griglia adattiva (1-5 colonne), problemi in cima
- [x] Endpoint GET /api/overview/clients aggregato

### Monitor WAN con Gateway ISP
- [x] Ping ICMP (SOCK_DGRAM unprivileged) + TCP Port Check
- [x] Gateway ISP per diagnosi linea
- [x] Test Connection pre-salvataggio
- [x] Card ridisegnate con metriche in pill

### Sistema Auto-Update
- [x] Versioning V.2.0.XXXX, polling 60s, banner aggiornamento
- [x] Badge versione su Login Page e Sidebar

### Gestione Utenti
- [x] CRUD + Toggle attivo/disattivato + Sblocca brute force
- [x] Seed automatico 4 utenti all'avvio

### Security (senza IP banning)
- [x] Brute Force (per email), Rate Limiting, 2FA/TOTP, Argon2id
- [x] AES-256-GCM, Security Headers, CORS, Audit Logging
- [x] Rimosso: IP Ban, Honeypot, IPBlockMiddleware

### Tutto il resto (COMPLETATO)
- [x] SNMP v3, Mappa Enterprise, Report PDF, TV Dashboard
- [x] VA, SOC AI Gemini (google-generativeai diretto), Backup Monitoring
- [x] PWA, Mobile Dashboard, Sidebar Framer Motion

## Zero dipendenze Emergent
- emergentintegrations RIMOSSO
- Usa google-generativeai diretto con GEMINI_API_KEY

## Credenziali
- admin@86bit.it / password
- info@86bit.it / password (Marco Santinelli)
- tv@86bit.it / Tv86bit!2026
- tvdash@86bit.it / Tv86bit!2026

## Backlog
### P1
- [ ] Template SNMP Zyxel (VPN, sessioni, temperatura)
- [ ] Notifiche Telegram
### P2
- [ ] Multi-tenant / SaaS
- [ ] LDAP/Active Directory
### P3
- [ ] Zyxel Nebula Cloud API
