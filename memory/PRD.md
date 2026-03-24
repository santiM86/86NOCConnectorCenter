# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti (switch, firewall, ecc.). Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. L'applicazione Windows ("86NocConnector") deve essere nativa senza richiedere installazione di Python.

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo (.bat/.ps1)
- **Auth**: JWT + MFA (TOTP via Microsoft Authenticator)

## Utenti
- **Admin**: Gestione completa (utenti, clienti, connettori, aggiornamenti)
- **Operator**: Monitoraggio e gestione alert
- **Viewer**: Sola lettura

## Funzionalita' Implementate

### Core Platform (DONE)
- Dashboard panoramica con alert live, trend 24h, connettori attivi
- Gestione alert SNMP Trap + Syslog con livelli di severita'
- Gestione clienti con API Key dedicate
- Gestione dispositivi monitorati con polling SNMP attivo
- WebSocket per alert in tempo reale
- PWA per accesso mobile

### Gestione Utenti (DONE)
- CRUD utenti con ruoli (admin/operator/viewer)
- MFA (TOTP) con QR code per Microsoft Authenticator
- Setup/Reset 2FA per utente

### Windows Connector v1.7.1 (DONE)
- Raccolta SNMP Trap (UDP/162) e Syslog (UDP/514)
- Polling SNMP attivo con report stato dispositivi
- Heartbeat periodico (60s) con versione e statistiche
- Auto-aggiornamento (ogni 6 ore) + force update dal SOC
- System tray con icona, menu, gestione dispositivi
- Esportazione/Importazione CSV dispositivi
- Diagnostica SNMP (Ping + Get) dalla tray
- Finestra "Informazioni" con dati aziendali 86BIT
- Script diagnostica.ps1 per troubleshooting connettivita'
- updater.ps1 per aggiornamento unificato senza doppia icona
- Versioning dinamico da version.json

### Enterprise Security (DONE)
- Rate limiting su endpoint sensibili
- Audit logging
- RBAC (Role-Based Access Control)

## Problema P0 Risolto (24 mar 2026)
**Issue**: Il connettore sul server del cliente era OFFLINE e il SOC mostrava v1.6.1 invece di v1.7.0.
**Root Cause**: Il pacchetto ZIP v1.7.0 conteneva ancora il vecchio file .bat complesso (591 bytes) che poteva causare errori di avvio, invece del .bat semplificato (104 bytes).
**Fix**: Ricostruito il ZIP come v1.7.1 con il .bat corretto e aggiunto script diagnostica.ps1. L'utente deve scaricare la nuova versione e installarla sul server.
**Status**: Fix deployato, attesa test dell'utente sul server Windows.

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key 86BIT_Office: noc_35cf39b4d68740b1a981aedef2ee293d

## Integrazioni Mockate
- Firebase Cloud Messaging (Push) - richiede API Key utente
- SendGrid (Email) - richiede API Key utente

## Backlog Prioritizzato

### P1 - Prossime
- Notifiche Push via Firebase (richiede API Key)
- Notifiche Email via SendGrid (richiede API Key)
- Feedback utente su connettore v1.7.1 e dispositivi SNMP

### P2 - Future
- SOC AI Transformation (correlazione, auto-triage, anomaly detection via LLM)
- Integrazione Twilio Voice/SMS per alert critici
- Auto-discovery nel connettore
- Integrazione LDAP
- Supporto SNMP v3

### P3 - Backlog
- Refactoring server.py in route modulari (>1800 righe)

## File Principali
- `/app/backend/server.py` - API backend monolite
- `/app/frontend/src/pages/ConnectorsPage.js` - Pagina connettori
- `/app/noc-connector/` - Pacchetto connector Windows
- `/app/noc-connector/version.json` - Single source of truth versione
