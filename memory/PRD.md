# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo (v2.1.0)
- **Auth**: JWT + MFA (TOTP)
- **Cifratura**: AES-256-GCM con ENCRYPTION_KEY persistente in .env
- **Redfish Engine**: Polling diretto iLO + failover automatico + power control

## Funzionalita Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Metriche Estese (DONE)
- HPE 5130, HPE iLO, Zyxel USG, Generico HOST-RESOURCES-MIB

### Vault Credenziali AES-256-GCM (DONE)
- CRUD cifrato, solo admin, URL esterna per iLO, audit log

### Redfish iLO Direct Polling & Failover (DONE)
- Polling diretto dal backend quando iLO esposta via NAT/VPN
- Failover automatico quando connettore offline >2 min
- Multi-connettore supportato
- Metriche: power, BIOS, serial, UUID, firmware, licenza, DIMM, NIC, storage

### Power Control & Wake-on-LAN (DONE - 27 mar 2026)
- **Power Control via Redfish**: Accendi (On), Spegni (GracefulShutdown), Riavvia (ForceRestart), Spegnimento forzato (ForceOff) direttamente via API iLO
- **Power State**: Lettura stato corrente (On/Off) via Redfish
- **Wake-on-LAN classico**: Il SOC accoda il comando WoL, il connettore invia il magic packet UDP sulla LAN
- **Flusso WoL**: SOC -> pending_commands DB -> heartbeat response -> connettore -> UDP broadcast
- **Frontend**: PowerControlPanel con pulsanti Accendi/Riavvia/Spegni, badge stato Power On/Off
- **Audit**: Ogni azione di power control viene loggata

### Security Enterprise (DONE)
- Headers, CORS, Rate limiting, Refresh Tokens, WS Auth
- Audit Dashboard, IP Auto-Ban, Account Lockout, Argon2id, TOTP 2FA

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

## Key API Endpoints (nuovi)
- `POST /api/devices/{ip}/power-action` - Power control via Redfish
- `GET /api/devices/{ip}/power-state` - Stato power via Redfish
- `POST /api/devices/{ip}/wake-on-lan` - Accoda WoL per il connettore
- `GET /api/connector/pending-commands` - Connettore recupera comandi pendenti
- `PUT /api/vault/credentials/{id}/direct-poll` - Toggle polling diretto
- `GET /api/redfish/failover-status` - Stato failover tutti i dispositivi iLO
- `POST /api/redfish/test-connection` - Test connessione Redfish
- `POST /api/redfish/poll-now` - Polling manuale

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Notifiche Push Firebase (serve API Key utente)
- Notifiche Email SendGrid (serve API Key utente)
- Test connettore v2.1.0 sul server del cliente

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS per alert critici
- LDAP integration, SNMP v3

### P3
- Refactoring server.py (~3100 righe) in moduli route separati
