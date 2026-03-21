# NOC Alert Command Center - PRD

## Problema Originale
Società IT necessita di un raccoglitore di alert per tutti i dispositivi nelle reti dei clienti: backup falliti, firewall, switch, server ILO. Console live in tempo reale su mobile e PC.

## Utenti
- Operatori NOC: monitorano alert in tempo reale
- Admin IT: gestiscono clienti, dispositivi, ruoli, SLA
- Tecnici sul campo: ricevono notifiche su mobile

## Stack Tecnologico
- Backend: FastAPI + MongoDB (Motor) + WebSockets + APScheduler
- Frontend: React + TailwindCSS + Shadcn UI + Recharts
- Mobile: React Native (Expo) - scaffolded
- Sicurezza: Argon2id, AES-256-GCM, JWT, TOTP 2FA

## Funzionalità Implementate

### Phase 1 - MVP (DONE)
- [x] Auth JWT con registrazione/login
- [x] 2FA con TOTP
- [x] Dashboard tempo reale con WebSocket
- [x] Gestione clienti CRUD
- [x] Gestione dispositivi CRUD
- [x] Alert con severità (critical, high, medium, low)
- [x] Ingestione SNMP Traps
- [x] Ingestione Syslog
- [x] Polling Redfish API (APScheduler)
- [x] Crittografia AES-256-GCM per credenziali dispositivi

### Phase 2 - Enterprise (DONE)
- [x] RBAC con 5 ruoli (admin, manager, operator, viewer, api_client)
- [x] SLA tracking con compliance e breach detection
- [x] Finestre di manutenzione (crea, elimina, soppressione alert)
- [x] Correlazione alert e deduplicazione
- [x] Report automatici (PDF SLA, CSV alert, CSV dispositivi)
- [x] Audit logging

### Phase 3 - UI Redesign (DONE - 21 Mar 2026)
- [x] Dashboard intuitiva con banner urgenze, card severità, trend 24h, live stream
- [x] Design dark theme NOC professionale
- [x] Pagina Enterprise con tabs (SLA, RBAC, Manutenzione, Report)
- [x] Filtri avanzati nella pagina alert
- [x] Dettaglio alert con dati grezzi
- [x] Sidebar navigazione con gestione utente
- [x] Primo utente registrato diventa admin automaticamente
- [x] Localizzazione completa in italiano

## Test Credentials
- Admin: admin@test.it / TestAdmin123! (role: admin)

## Backlog P1
- [ ] App mobile React Native (login, dashboard, alert list)
- [ ] Notifiche push Firebase (richiede API key utente)
- [ ] Notifiche email SendGrid (richiede API key utente)

## Backlog P2
- [ ] Integrazione LDAP
- [ ] Refactoring server.py in moduli separati (auth, alerts, devices, ingestion)
- [ ] Dashboard analytics avanzata

## API Mocked
- Firebase Cloud Messaging: MOCKED (nessuna API key fornita)
- SendGrid Email: MOCKED (nessuna API key fornita)
