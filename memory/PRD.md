# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo
- **Auth**: JWT + MFA (TOTP)

## Funzionalita' Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Monitoraggio Dispositivi (DONE)
- SNMP polling (porte, sysDescr, uptime, trap)
- Ping+HTTP per dispositivi senza SNMP (switch smart managed)
- Auto-Discovery rete (ping sweep + port scan)
- **Cambio tipo monitoraggio** cliccando badge SNMP/PING

### Web Console Proxy (NUOVO v1.7.3) (DONE)
- Accesso alla web interface dei dispositivi direttamente dal SOC
- Nessuna VPN necessaria: SOC → Backend → Connettore → Dispositivo
- Sicurezza: solo admin/operator, whitelist dispositivi gestiti, audit log
- CSS e immagini inlined per rendering completo
- Navigazione intercettata per proxy trasparente
- Loop veloce (3s) per bassa latenza

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

### Connector v1.7.3 (DONE)
- SNMP Trap + Syslog, Polling SNMP + Ping/HTTP
- Auto-Discovery, Web Console Proxy
- Heartbeat, auto-update, force update
- System tray, diagnostica, import/export CSV

### Enterprise Security (DONE)
- Rate limiting, Audit logging, RBAC

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Aggiornare connettore a v1.7.3 sul server
- Notifiche Push Firebase (serve API Key)
- Notifiche Email SendGrid (serve API Key)

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS, LDAP, SNMP v3

### P3
- Refactoring server.py (>2000 righe)
