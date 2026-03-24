# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti (switch, firewall, ecc.). Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. L'applicazione Windows ("86NocConnector") deve essere nativa senza richiedere installazione di Python.

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo (.bat/.ps1)
- **Auth**: JWT + MFA (TOTP via Microsoft Authenticator)

## Funzionalita' Implementate

### Core Platform (DONE)
- Dashboard panoramica con alert live, trend 24h, connettori attivi
- Gestione alert SNMP Trap + Syslog con livelli di severita'
- Gestione clienti con API Key dedicate
- WebSocket per alert in tempo reale, PWA per accesso mobile

### Gestione Dispositivi (DONE)
- Monitoraggio SNMP: polling porte, sysDescr, uptime, trap
- **Monitoraggio Ping+HTTP** (NUOVO v1.7.2): per switch smart managed e dispositivi senza SNMP
  - Ping periodico con latenza (ms)
  - Verifica porta HTTP/HTTPS management
  - Alert su device up/down
  - Badge visivo SNMP/PING nel frontend
  - Form aggiunta dispositivo con selezione tipo (SNMP o Ping+HTTP)
  - Sezione espansa con metriche Ping/HTTP (latenza, stato HTTP, raggiungibilita')

### Gestione Utenti (DONE)
- CRUD utenti con ruoli (admin/operator/viewer)
- MFA (TOTP) con QR code per Microsoft Authenticator

### Windows Connector v1.7.2 (DONE)
- Raccolta SNMP Trap + Syslog (UDP 162/514)
- Polling SNMP attivo + Ping/HTTP per dispositivi non-SNMP
- Heartbeat periodico, auto-aggiornamento, force update
- System tray con menu, diagnostica SNMP, info aziendali
- Esportazione/Importazione CSV dispositivi
- Script diagnostica.ps1 per troubleshooting
- updater.ps1 per aggiornamento unificato

### Enterprise Security (DONE)
- Rate limiting, Audit logging, RBAC

## Problemi Risolti (24 mar 2026)
- **P0 Connettore OFFLINE**: Il config.json sul server del cliente aveva l'API Key nel campo noc_center_url. Corretto dall'utente. Connettore ora ONLINE v1.7.1.
- **P0 ZIP errato**: Il ZIP v1.7.0 conteneva il vecchio .bat complesso. Ricostruito con .bat semplificato nella v1.7.1.
- **Ping+HTTP monitoring**: Implementato supporto completo per monitorare dispositivi senza SNMP (switch smart managed).

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
- Aggiornamento connettore a v1.7.2 sul server del cliente

### P2 - Future
- SOC AI Transformation (correlazione, auto-triage, anomaly detection via LLM)
- Integrazione Twilio Voice/SMS per alert critici
- Auto-discovery nel connettore
- Integrazione LDAP
- Supporto SNMP v3

### P3 - Backlog
- Refactoring server.py in route modulari (>1900 righe)
