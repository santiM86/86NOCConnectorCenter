# NOC Alert Command Center - PRD

## Problema Originale
Societa' IT necessita di un raccoglitore di alert per tutti i dispositivi nelle reti dei clienti: backup falliti, firewall, switch, server ILO. Console live in tempo reale su mobile e PC.

## Utenti
- Operatori NOC: monitorano alert in tempo reale
- Admin IT: gestiscono clienti, dispositivi, ruoli, SLA
- Tecnici sul campo: ricevono notifiche su mobile

## Stack Tecnologico
- Backend: FastAPI + MongoDB (Motor) + WebSockets + APScheduler
- Frontend: React + TailwindCSS + Shadcn UI + Recharts
- Connector: Python standalone (SNMP + Syslog collector)
- Mobile: React Native (Expo) - scaffolded
- Sicurezza: Argon2id, AES-256-GCM, JWT, TOTP 2FA

## Funzionalita' Implementate

### Phase 1 - MVP (DONE)
- [x] Auth JWT con registrazione/login
- [x] 2FA con TOTP
- [x] Dashboard tempo reale con WebSocket
- [x] Gestione clienti CRUD
- [x] Gestione dispositivi CRUD
- [x] Alert con severita' (critical, high, medium, low)
- [x] Ingestione SNMP Traps
- [x] Ingestione Syslog
- [x] Polling Redfish API (APScheduler)
- [x] Crittografia AES-256-GCM per credenziali dispositivi

### Phase 2 - Enterprise (DONE)
- [x] RBAC con 5 ruoli (admin, manager, operator, viewer, api_client)
- [x] SLA tracking con compliance e breach detection
- [x] Finestre di manutenzione
- [x] Correlazione alert e deduplicazione
- [x] Report automatici (PDF SLA, CSV alert, CSV dispositivi)
- [x] Audit logging

### Phase 3 - UI Redesign (DONE - 21 Mar 2026)
- [x] Dashboard intuitiva con banner urgenze, card severita', trend 24h, live stream
- [x] Pagina Enterprise con tabs (SLA, RBAC, Manutenzione, Report)
- [x] Primo utente registrato diventa admin
- [x] Localizzazione completa in italiano

### Phase 4 - NOC Connector (DONE - 22 Mar 2026)
- [x] Applicazione standalone Python per raccolta SNMP Traps + Syslog
- [x] Autenticazione API Key per ingestione dati
- [x] API Key visibile nelle card clienti con copia/rigenera
- [x] Dashboard web locale connector (http://localhost:9090)
- [x] Heartbeat connector con stato visibile in dashboard
- [x] Guida configurazione HPE 5130 JG941A
- [x] Supporto installazione come servizio Windows
- [x] Riutilizzabile per qualsiasi dispositivo (firewall, ILO, backup, etc.)

## Architettura Connessione
```
[Switch HPE 5130] --SNMP/Syslog--> [NOC Connector su Windows] --HTTPS--> [NOC Center Cloud]
```

## Test Credentials
- Admin: admin@test.it / TestAdmin123! (role: admin)

## Files Chiave
- `/app/noc-connector/noc_connector.py` - Applicazione collector
- `/app/noc-connector/README.md` - Guida installazione + comandi HPE 5130
- `/app/backend/server.py` - Backend principale
- `/app/backend/enterprise_routes.py` - Endpoint enterprise

## Backlog P1
- [ ] App mobile React Native (login, dashboard, alert list)
- [ ] Notifiche push Firebase (richiede API key utente)
- [ ] Notifiche email SendGrid (richiede API key utente)

## Backlog P2
- [ ] Integrazione LDAP
- [ ] Refactoring server.py in moduli separati
- [ ] Dashboard analytics avanzata
- [ ] SNMP v3 support nel connector (attualmente v2c)
- [ ] Auto-discovery dispositivi nella rete

## API Mocked
- Firebase Cloud Messaging: MOCKED
- SendGrid Email: MOCKED
