# NOC Alert Command Center - PRD

## Original Problem Statement
Siamo una società IT, abbiamo bisogno di creare un raccoglitore di alert di tutti i dispositivi nelle reti dei clienti - alert provenienti da backup falliti, firewall, switch, server ILO. Console live in tempo reale sia su cellulare che su PC.

## User Personas
- **IT System Administrator**: Gestisce infrastrutture di più clienti, necessita di visione centralizzata degli alert
- **NOC Operator**: Monitora alert 24/7, conferma e risolve problemi in tempo reale

## Core Requirements (Static)
1. Raccolta alert multi-sorgente (SNMP Traps, Syslog, API/Webhook)
2. Dashboard real-time con WebSocket
3. Gestione clienti e dispositivi
4. Sistema di priorità alert (Critico, Alto, Medio, Basso)
5. Workflow acknowledge/resolve
6. Responsive design mobile/desktop
7. Autenticazione JWT

## What's Been Implemented (21 Jan 2026)

### Backend (FastAPI + MongoDB)
- ✅ Auth system (JWT register/login)
- ✅ Clients CRUD API
- ✅ Devices CRUD API (backup, firewall, switch, ilo)
- ✅ Alerts CRUD API con filtri
- ✅ Stats/Trends aggregation endpoints
- ✅ SNMP Trap ingestion endpoint
- ✅ Syslog ingestion endpoint
- ✅ WebSocket real-time broadcast

### Frontend (React + Shadcn UI)
- ✅ Login/Register page
- ✅ Dashboard con metriche, grafici trend, live stream
- ✅ Alerts list con filtri e ricerca
- ✅ Alert detail con dati grezzi
- ✅ Clients management
- ✅ Devices management
- ✅ Mobile responsive layout
- ✅ Dark NOC theme

## P0 (Done)
- [x] Core alert management system
- [x] Real-time WebSocket updates
- [x] Multi-tenant client/device structure

## P1 (Backlog)
- [ ] Email/SMS notifications per alert critici
- [ ] Dashboard personalizzabile
- [ ] Report periodici automatici
- [ ] Export CSV/PDF alert history

## P2 (Future)
- [ ] SNMP agent nativo per ricevere trap direttamente
- [ ] Integrazione con sistemi ticketing (ServiceNow, Jira)
- [ ] Machine learning per correlazione alert
- [ ] Mobile app nativa

## Next Tasks
1. Configurare notifiche push/email per alert critici
2. Aggiungere più filtri e statistiche avanzate
3. Implementare roles (admin, operator, viewer)
