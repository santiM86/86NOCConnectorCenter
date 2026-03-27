# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo (v2.2.0)
- **Auth**: JWT + MFA (TOTP)
- **Cifratura**: AES-256-GCM con ENCRYPTION_KEY persistente in .env
- **Redfish Engine**: Polling diretto iLO + failover automatico + power control

## Funzionalita Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Metriche SNMP Estese (DONE)
- HPE 5130, HPE iLO, Zyxel USG, Generico HOST-RESOURCES-MIB

### Metriche PING Avanzate v2.2.0 (DONE - 27 mar 2026)
- **5 Probe Ping**: min/avg/max/jitter/packet_loss%
- **TTL**: Con rilevamento OS (Linux <64, Windows <128, Router >128)
- **TCP Port Scan**: 15 porte comuni (SSH, HTTP, HTTPS, RDP, SMB, MySQL, MSSQL, VNC, FTP, SMTP, DNS, Telnet, SNMP, 8080, 8443)
- **HTTP Deep Check**: Response time, server header, content-type, page title
- **SSL Certificate**: Scadenza con alert automatico se <30 giorni, emittente
- **DNS Resolution**: Tempo di risoluzione DNS
- **Alert automatici**: Latenza alta (>200ms), packet loss (>0%), SSL in scadenza
- **Storico metriche**: ping_avg, ping_jitter, packet_loss salvati per trending

### Vault Credenziali AES-256-GCM (DONE)
- CRUD cifrato, solo admin, URL esterna per iLO, audit log

### Redfish iLO Direct Polling & Failover (DONE)
- Polling diretto, failover automatico, multi-connettore

### Power Control & Wake-on-LAN (DONE)
- Accendi/Spegni/Riavvia via iLO Redfish, WoL classico via connettore

### Fix Aggiornamento Connettore (DONE - 27 mar 2026)
- Timeout 5 min per update bloccati
- Pulsante "Reset Stato" per aggiornamenti bloccati nel SOC
- Endpoint: POST /api/connector/{id}/reset-update-status
- Cartella Menu Start rinominata in "86BIT Connector"

### Security Enterprise (DONE)
- Headers, CORS, Rate limiting, Refresh Tokens, Audit, IP Auto-Ban, Argon2id, TOTP 2FA

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Notifiche Push Firebase (serve API Key utente)
- Notifiche Email SendGrid (serve API Key utente)
- Test connettore v2.2.0 sul server del cliente

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS per alert critici
- LDAP integration, SNMP v3

### P3
- Refactoring server.py (~3200 righe) in moduli route separati
