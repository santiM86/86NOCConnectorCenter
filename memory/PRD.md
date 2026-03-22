# NOC Center - PRD (Product Requirements Document)

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti (switch, firewall, ecc.). Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. L'applicazione Windows ("86NocConnector") da installare sui server dei clienti deve essere nativa senza richiedere l'installazione di Python.

## Architettura
- **Backend**: FastAPI + MongoDB + WebSockets
- **Frontend**: React + TailwindCSS + Shadcn UI + PWA
- **Windows Connector**: 100% Native PowerShell 5.1+ / .NET Windows Forms

## Funzionalità Completate
- [x] Dashboard NOC con alert in tempo reale (WebSocket)
- [x] Gestione Clienti con API Key
- [x] Gestione Dispositivi  
- [x] SNMP Trap + Syslog collector nel connector
- [x] PWA per accesso mobile
- [x] SNMP Polling attivo per dispositivi senza trap (HPE 1820)
- [x] Auto-Update del connector via web
- [x] Gestione dispositivi centralizzata (web + system tray)
- [x] Vista unificata connettori/dispositivi per cliente
- [x] Installer GUI Windows senza finestre nere
- [x] **Auto-compilazione versione/changelog da zip** (22 Mar 2026)

## Task In Corso
Nessuno.

## Prossimi Task (P1)
- Push Notifications via Firebase (MOCKATE - serve API Key utente)
- Email Notifications via SendGrid (MOCKATE - serve API Key utente)
- Feedback utente su test 86NocConnector in produzione

## Task Futuri (P2)
- SOC AI Transformation (correlazione, auto-triage, anomaly detection con LLM)
- Twilio Voice/SMS per alert critici
- Auto-discovery nel connector
- LDAP integration per dashboard
- SNMP v3 nel connector

## Refactoring (P3)
- Suddivisione server.py in moduli route separati

## Integrazioni 3rd Party
- Firebase Cloud Messaging (Push) — MOCKATO
- SendGrid (Email) — MOCKATO
- Twilio (Voice/SMS) — Non iniziato
