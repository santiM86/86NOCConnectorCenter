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
- Monitoraggio Ping+HTTP: per switch smart managed e dispositivi senza SNMP
- **Auto-Discovery Rete (NUOVO v1.7.2)**: scansione automatica della subnet
  - Ping sweep parallelo (50 thread) per trovare host attivi
  - Port scan (HTTP, HTTPS, SNMP, SSH, Telnet, RDP, HTTP-Alt, HTTPS-Alt)
  - Risoluzione hostname DNS
  - Suggerimento automatico tipo monitoraggio (SNMP/Ping)
  - Classificazione dispositivi (switch/router, server-windows, server-linux, web-device)
  - Aggiunta one-click dal pannello discovery al monitoraggio
  - Badge "Monitorato" per dispositivi gia' aggiunti

### Gestione Utenti (DONE)
- CRUD utenti con ruoli (admin/operator/viewer)
- MFA (TOTP) con QR code per Microsoft Authenticator

### Windows Connector v1.7.2 (DONE)
- Raccolta SNMP Trap + Syslog (UDP 162/514)
- Polling SNMP attivo + Ping/HTTP per dispositivi non-SNMP
- Auto-Discovery rete con ping sweep + port scan
- Heartbeat periodico, auto-aggiornamento, force update
- System tray, diagnostica SNMP, info aziendali, esportazione/importazione CSV
- Script diagnostica.ps1 per troubleshooting
- updater.ps1 per aggiornamento unificato

### Enterprise Security (DONE)
- Rate limiting, Audit logging, RBAC

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key 86BIT_Office: noc_35cf39b4d68740b1a981aedef2ee293d

## Integrazioni Mockate
- Firebase Cloud Messaging (Push) - richiede API Key utente
- SendGrid (Email) - richiede API Key utente

## Backlog Prioritizzato

### P1 - Prossime
- Aggiornare connettore a v1.7.2 sul server del cliente (scarica ZIP dal SOC)
- Notifiche Push via Firebase (richiede API Key)
- Notifiche Email via SendGrid (richiede API Key)

### P2 - Future
- SOC AI Transformation (correlazione, auto-triage, anomaly detection via LLM)
- Integrazione Twilio Voice/SMS per alert critici
- Integrazione LDAP
- Supporto SNMP v3

### P3 - Backlog
- Refactoring server.py in route modulari (>1900 righe)
