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
- Cambio tipo monitoraggio cliccando badge SNMP/PING

### Metriche Estese SNMP v1.8.0 (DONE - 27 mar 2026)
- **HPE 5130 (Comware)**: CPU, Memoria, Temperatura tramite OID H3C
- **HPE ILO (ProLiant)**: Salute generale, temperature sensori, ventole, alimentatori, dischi fisici
- **Generico**: CPU tramite HOST-RESOURCES-MIB (hrProcessorLoad)
- **Traffico interfacce**: Bandwidth IN/OUT (bps), velocita negoziata, errori IN/OUT per porta
- **Alert automatici**: CPU>90%, Memoria>90%, Temperatura>75C, disco guasto, ventola guasta, salute ILO degradata
- **Storico metriche**: Ultimi 24h salvati in MongoDB per trend
- **Frontend**: Gauge widgets (CPU/RAM/Temp), pannello hardware health (ventole/PSU/dischi/temperature), tabella traffico porte con bandwidth e errori, mini-chart trend 24h
- Device class auto-detection: `hpe-comware`, `hpe-ilo`, `generic`

### Web Console Proxy v1.7.3 (DONE)
- Accesso alla web interface dei dispositivi direttamente dal SOC
- Nessuna VPN necessaria: SOC -> Backend -> Connettore -> Dispositivo

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

### Connector v1.8.0 (DONE)
- SNMP Trap + Syslog, Polling SNMP esteso + Ping/HTTP
- Auto-Discovery, Web Console Proxy
- Heartbeat, auto-update, force update
- System tray con Mutex (fix doppie icone), diagnostica, import/export CSV
- Metriche estese HPE 5130 e ILO

### Enterprise Security (DONE)
- Rate limiting, Audit logging, RBAC

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Aggiornare connettore a v1.8.0 sul server del cliente
- Notifiche Push Firebase (serve API Key utente)
- Notifiche Email SendGrid (serve API Key utente)

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS per alert critici
- LDAP integration
- SNMP v3

### P3
- Refactoring server.py (>2100 righe) in moduli route separati
