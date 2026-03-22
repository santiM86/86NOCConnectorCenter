# NOC Alert Command Center - PRD

## Problema Originale
Societa' IT necessita di un raccoglitore di alert per tutti i dispositivi nelle reti dei clienti: backup falliti, firewall, switch, server ILO. Console live in tempo reale su mobile e PC.

## Stack Tecnologico
- Backend: FastAPI + MongoDB + WebSockets + APScheduler
- Frontend: React + TailwindCSS + Shadcn UI + Recharts
- Connector: Python standalone (86NocConnector) con GUI wizard + system tray
- Mobile: React Native (Expo) - scaffolded
- Sicurezza: Argon2id, AES-256-GCM, JWT, TOTP 2FA

## Funzionalita' Implementate

### Phase 1 - MVP (DONE)
- [x] Auth JWT con registrazione/login + 2FA TOTP
- [x] Dashboard tempo reale con WebSocket
- [x] Gestione clienti CRUD con API key per ogni cliente
- [x] Gestione dispositivi CRUD
- [x] Alert con severita' (critical, high, medium, low)
- [x] Ingestione SNMP Traps + Syslog (con auth API Key)
- [x] Polling Redfish API (APScheduler)
- [x] Crittografia AES-256-GCM

### Phase 2 - Enterprise (DONE)
- [x] RBAC con 5 ruoli
- [x] SLA tracking + compliance + breach detection
- [x] Finestre di manutenzione
- [x] Correlazione alert e deduplicazione
- [x] Report automatici (PDF/CSV)
- [x] Audit logging

### Phase 3 - UI Redesign (DONE)
- [x] Dashboard intuitiva (banner urgenze, card severita', trend, live stream)
- [x] Pagina Enterprise (SLA, RBAC, Manutenzione, Report)
- [x] Design dark theme NOC professionale
- [x] Localizzazione italiana

### Phase 4 - 86NocConnector (DONE - 22 Mar 2026)
- [x] Applicazione standalone Windows con Python embedded (zero installazioni)
- [x] Wizard installazione GUI (4 pagine: Benvenuto, Config, Installazione, Completamento)
- [x] Icona system tray (vicino all'orologio) con menu: Stato, Avvia/Ferma, Log, Config
- [x] SNMP Trap listener (porta 162) + Syslog listener (porta 514)
- [x] Inoltro automatico al NOC Center via HTTPS + API Key
- [x] Heartbeat connector → stato visibile nella dashboard NOC
- [x] Avvio automatico con Windows
- [x] Guida configurazione HPE 5130 JG941A
- [x] Riutilizzabile per qualsiasi dispositivo
- [x] Disinstallazione pulita (uninstall.bat)

## Architettura Connessione
```
[HPE 5130 / Firewall / ILO] --SNMP/Syslog--> [86NocConnector su Windows] --HTTPS--> [NOC Center Cloud]
```

## Test Credentials
- Admin: admin@test.it / TestAdmin123! (role: admin)

## Files Chiave
- `/app/noc-connector/` - Pacchetto 86NocConnector completo
- `/app/backend/server.py` - Backend principale
- `/app/frontend/src/pages/` - Pagine frontend

## Backlog P1
- [ ] App mobile React Native
- [ ] Notifiche push Firebase (richiede API key)
- [ ] Notifiche email SendGrid (richiede API key)

## Backlog P2
- [ ] LDAP integration
- [ ] SNMP v3 nel connector
- [ ] Auto-discovery dispositivi rete
- [ ] Refactoring server.py in moduli
