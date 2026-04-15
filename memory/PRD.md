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

### Sistema Auto-Update (NUOVO - 15/04/2026)
- [x] Endpoint GET /api/app-version: hash SHA256 di tutti i file Python, versione 2.0.XXXX
- [x] Frontend polling ogni 60 secondi per confronto versione/hash
- [x] Banner "Nuova versione disponibile" con pulsante Aggiorna
- [x] Auto-reload per frontend stale (localStorage hash mismatch)
- [x] Cache-busting: caches.delete + localStorage clear + hard reload
- [x] VersionBadge nell'header sidebar (V.2.0.XXXX)
- [x] VersionProvider context condiviso

### Navigazione Sidebar Riorganizzata (AGGIORNATO - 15/04/2026)
- [x] 6 sezioni logiche: Panoramica, Monitoraggio, Clienti & Rete, Operazioni, Sicurezza, Amministrazione
- [x] Panoramica: Dashboard, Alert, Stato Rete (3)
- [x] Monitoraggio: Dispositivi, Stampanti, Monitor Servizi, Bandwidth, Monitor WAN, Backup, Grafici Trend (7)
- [x] Clienti & Rete: Clienti, Inventario, Connettori, Auto-Discovery (4)
- [x] Operazioni: Incidenti, Manutenzione, Report PDF (3)
- [x] Sicurezza: SOC AI, VA, Security Dashboard, Vault, Audit (5)
- [x] Amministrazione: Gestione Utenti, Soglie Alert, Impostazioni, TV Dashboard (4)

### Gestione Utenti (AGGIORNATO - 14/04/2026)
- [x] CRUD completo + Toggle attivo/disattivato + Sblocca brute force
- [x] Stats: Totale, Attivi, MFA, Admin
- [x] 4 utenti registrati

### Login Page Branding (COMPLETATO - 14/04/2026)
- [x] Icona ARGUS scudo con punto esclamativo
- [x] Footer Verdana full-width dati fiscali
- [x] Layout responsive 100vh senza scroll
- [x] Footer mobile compatto
- [x] Banner notifiche nascosto su login/2fa

### Tutto il resto (COMPLETATO)
- [x] Mappa Enterprise, Dashboard Metriche, Report PDF, TV Dashboard
- [x] Stampanti SNMP, VA, Trend, Discovery, Soglie, Manutenzione
- [x] Bandwidth, SOC AI Gemini, Portale Cliente, Backup Monitoring
- [x] Security 21 protezioni, SNMP v3, Connector Hardening
- [x] Scalabilita' (65 indici, 12 TTL, GZip, Task Coordinator)
- [x] Mobile Dashboard, WAN Esterno, PWA

## Key API Endpoints
- GET `/api/app-version` - Versione app e hash codice
- GET/POST `/api/admin/users` - CRUD utenti
- PUT `/api/admin/users/{id}/toggle-active` - Attiva/Disattiva
- PUT `/api/admin/users/{id}/unlock` - Sblocca brute force

## Backlog
### P1
- [ ] Notifiche Telegram (quando utente fornira bot token)
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
### P2
- [ ] Multi-tenant e White-labeling (SaaS)
- [ ] LDAP/Active Directory
### P3
- [ ] Zyxel Nebula Cloud API
- [ ] App Mobile React Native

## Credenziali Test
- Admin: admin@86bit.it / password
- Admin: info@86bit.it / password (Marco Santinelli)
- TV Monitor: tv@86bit.it / Tv86bit!2026
- TV Dashboard Test: tvdash@86bit.it / Tv86bit!2026
