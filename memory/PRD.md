# NOC Alert Command Center - PRD v2.0

## Original Problem Statement
Console NOC per raccolta alert da dispositivi IT (backup, firewall, switch, server ILO) con supporto SNMP Traps, Syslog e Redfish API. Console live in tempo reale su mobile e PC con sicurezza enterprise-grade.

## User Personas
- **IT System Administrator**: Gestisce infrastrutture multi-cliente
- **NOC Operator**: Monitora alert 24/7, conferma e risolve problemi
- **Security Officer**: Verifica audit log e compliance

## Core Requirements (Static)
1. Raccolta alert multi-sorgente (SNMP Traps, Syslog, API/Webhook, Redfish)
2. Dashboard real-time con WebSocket
3. Gestione clienti e dispositivi
4. Sistema di priorità alert (Critico, Alto, Medio, Basso)
5. Workflow acknowledge/resolve
6. Sicurezza enterprise-grade (AES-256-GCM, Argon2id, 2FA, Rate Limiting)
7. Notifiche multi-canale (Email, Push, Webhook)
8. App mobile nativa (React Native)

## What's Been Implemented

### Phase 1 (21 Jan 2026) - MVP
- ✅ Auth JWT con bcrypt
- ✅ CRUD Clienti/Dispositivi/Alert
- ✅ Dashboard con metriche live
- ✅ WebSocket real-time
- ✅ Endpoint SNMP/Syslog ingestion
- ✅ UI responsive dark theme

### Phase 2 (21 Jan 2026) - Enterprise Security + Mobile
- ✅ **Sicurezza Enterprise:**
  - AES-256-GCM encryption per credenziali iLO
  - Argon2id password hashing
  - Rate limiting (slowapi)
  - Audit logging completo
  - 2FA TOTP (Google Authenticator)

- ✅ **Redfish API Polling:**
  - Scheduler configurabile (APScheduler)
  - Auto-discovery health status
  - Gestione credenziali crittografate
  - Test connessione iLO

- ✅ **Notifiche Multi-canale (MOCK):**
  - Email via SendGrid (mock)
  - Push via Firebase FCM (mock)
  - Webhook: Teams, Slack, Telegram, Generico
  
- ✅ **React Native Mobile App:**
  - Login/Register con 2FA
  - Dashboard live con WebSocket
  - Alert list con filtri
  - Alert detail con azioni
  - Device list
  - Settings con logout

## P0 (Done)
- [x] Core alert management
- [x] Real-time WebSocket
- [x] Multi-tenant structure
- [x] Enterprise security (AES-256, Argon2id, 2FA)
- [x] Redfish polling
- [x] Mobile app structure

## P1 (Backlog - Requires API Keys)
- [ ] SendGrid email integration (richiede API key)
- [ ] Firebase push notifications (richiede credentials)
- [ ] Build e publish app su App Store/Play Store

## P2 (Future)
- [ ] SNMP trap receiver nativo (porta 162)
- [ ] Syslog server nativo (porta 514)
- [ ] Machine learning correlazione alert
- [ ] Integrazione ticketing (ServiceNow, Jira)
- [ ] Report PDF automatici

## Tech Stack
- **Backend:** FastAPI + MongoDB + Motor
- **Security:** cryptography (AES-256-GCM), argon2-cffi, pyotp, slowapi
- **Polling:** APScheduler, httpx
- **Frontend Web:** React + Shadcn UI + Recharts
- **Frontend Mobile:** React Native + Expo

## Next Tasks
1. Fornire API keys SendGrid/Firebase per notifiche reali
2. Build e deploy app mobile su store
3. Configurare dispositivi per inviare trap/syslog
4. Aggiungere ruoli utente (admin, operator, viewer)
