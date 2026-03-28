# NOC Alert Command Center - PRD

## Descrizione Prodotto
Piattaforma NOC enterprise-grade per il monitoraggio in tempo reale di dispositivi di rete (switch, firewall, server) tramite SNMP, Syslog e Redfish. Include un connettore Windows nativo (PowerShell) per l'installazione sui server dei clienti.

## Architettura
- **Backend**: Python 3.11, FastAPI, MongoDB, AES-256-GCM encryption
- **Frontend**: React, TailwindCSS, Shadcn UI, PWA
- **Windows Connector**: PowerShell 5.1+, Raw UDP/BER per SNMP, Redfish API
- **Database**: MongoDB

### Struttura Backend (Post-Refactoring v2.3.0)
```
/app/backend/
├── server.py (193 righe - app init, middleware, router includes)
├── database.py (connessione MongoDB)
├── deps.py (dipendenze condivise: auth, JWT, services, IP blocking)
├── models.py (modelli Pydantic)
├── security.py (AES-256-GCM, Argon2id, TOTP)
├── audit.py (audit logging)
├── notifications.py (notifiche)
├── redfish.py (polling iLO diretto)
├── correlation.py (correlazione alert)
├── maintenance.py (finestre di manutenzione)
├── sla.py (SLA management)
├── security_hardening.py (account lockout)
├── enterprise_routes.py (route enterprise)
├── routes/
│   ├── auth.py (autenticazione, 2FA, refresh tokens)
│   ├── admin.py (gestione utenti admin)
│   ├── clients.py (CRUD clienti)
│   ├── devices.py (CRUD dispositivi + credenziali)
│   ├── alerts.py (CRUD alert + statistiche + trend)
│   ├── audit_routes.py (audit logs, security dashboard, IP blocking)
│   ├── vault.py (Credential Vault AES-256-GCM)
│   ├── redfish_routes.py (Redfish/iLO + Power Control + WoL)
│   ├── settings.py (impostazioni notifiche/Redfish)
│   ├── ingestion.py (ingestione SNMP/Syslog)
│   ├── connector.py (heartbeat, auto-update, gestione dispositivi)
│   ├── discovery.py (network discovery)
│   └── web_proxy.py (web console proxy)
```

## Funzionalita Implementate

### Core Platform
- [x] Autenticazione JWT con 2FA (TOTP/Microsoft Authenticator)
- [x] Gestione utenti con ruoli (admin/operator/viewer)
- [x] Gestione clienti con API key
- [x] Gestione dispositivi SNMP/Ping/Redfish
- [x] Alert management con correlazione intelligente
- [x] Dashboard statistiche in tempo reale
- [x] WebSocket per alert live
- [x] Audit logging completo
- [x] Security Dashboard con IP blocking
- [x] Rate limiting enterprise
- [x] Security headers middleware

### Credential Vault (AES-256-GCM)
- [x] Cifratura militare delle credenziali
- [x] CRUD credenziali dal SOC
- [x] Accesso sicuro dal connettore via API key

### Metriche Avanzate
- [x] PING: min/avg/max/jitter, packet loss, TTL
- [x] TCP port scan (15 porte)
- [x] HTTP deep check (response time, SSL cert, server header)
- [x] DNS resolution time
- [x] SNMP: CPU, memoria, temperatura, porte
- [x] Redfish iLO: stato hardware, temperature, alimentatori

### Power Control
- [x] Redfish iLO: power on/off/reset/graceful shutdown
- [x] Wake-on-LAN per dispositivi generici

### Windows Connector (v2.3.0)
- [x] Auto-update con updater.ps1 dedicato
- [x] Force update dal SOC con barra progresso
- [x] Export/Import dispositivi CSV
- [x] Diagnostica SNMP dalla system tray
- [x] Finestra Informazioni con logo 86BIT
- [x] Menu Start Windows "86BIT Connector"
- [x] Versioning dinamico da version.json
- [x] Fix compatibilita PowerShell 5.1

### Sicurezza Enterprise
- [x] AES-256-GCM per credenziali
- [x] Argon2id per password hashing
- [x] IP auto-banning su login falliti
- [x] Account lockout temporaneo
- [x] Security headers (HSTS, CSP, X-Frame-Options)

## Backlog

### P1 - Prossimi
- [ ] Notifiche Push Firebase (MOCKED - serve API Key utente)
- [ ] Notifiche Email SendGrid (MOCKED - serve API Key utente)

### P2 - Futuri
- [ ] SOC AI: correlazione intelligente, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS per alert critici
- [ ] Auto-discovery rete
- [ ] LDAP integration
- [ ] SNMP v3

## Test Reports
- iteration_16.json: Vault Connector Integration
- iteration_17.json: Direct iLO Backend Polling & Failover
- iteration_18.json: Power Control & WoL
- iteration_19.json: Advanced PING Metrics
- iteration_20.json: Server.py Refactoring Validation (100% pass)

## Credenziali Test
- Admin: admin@86bit.it
- Test: test_refactor@86bit.it / Test1234!
