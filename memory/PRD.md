# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo (v2.0.0)
- **Auth**: JWT + MFA (TOTP)
- **Cifratura**: AES-256-GCM con ENCRYPTION_KEY persistente in .env
- **Redfish Engine**: Polling diretto iLO dal backend + failover automatico

## Funzionalita Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Metriche Estese (DONE)
- HPE 5130 (Comware): CPU, Memoria, Temperatura
- HPE ILO (ProLiant): Health, temperature, ventole, alimentatori, dischi
- Zyxel USG Firewall: CPU, RAM, sessioni, VPN IPSec, flash
- Generico: CPU via HOST-RESOURCES-MIB, traffico interfacce

### Vault Credenziali AES-256-GCM (DONE - 27 mar 2026)
- CRUD con cifratura AES-256-GCM persistente
- Accesso solo admin, auto-hide password 30s
- Supporto URL esterna per iLO (NAT/VPN)
- Integrazione con Redfish direct polling
- Audit log su ogni accesso

### Redfish iLO Direct Polling & Failover (DONE - 27 mar 2026)
- **Opzione A (Polling Diretto)**: Il backend SOC interroga direttamente le iLO via Redfish REST API quando configurate con URL esterna (NAT/VPN)
- **Opzione B (Multi-Connettore)**: Supporto per piu connettori sulla stessa rete
- **Opzione C (Failover Automatico)**: Quando il connettore e offline >2 min, il backend prende il controllo automaticamente
- **Metriche Redfish**: Power watts, BIOS, modello, seriale, UUID, iLO firmware, licenza, DIMM RAM, NIC, storage controller + logical drive
- **Frontend**: Pannello failover nel Vault, badge stato polling, test connessione, polling manuale
- **Endpoint**: `/api/redfish/failover-status`, `/api/redfish/test-connection`, `/api/redfish/poll-now`, `/api/vault/credentials/{id}/direct-poll`

### Connector v2.0.0 (DONE)
- SNMP Trap + Syslog + Polling esteso + Ping/HTTP
- Auto-Discovery, Web Console Proxy
- Redfish iLO polling con credenziali dal Vault
- Heartbeat, auto-update, force update
- System tray con diagnostica, import/export CSV

### Security Enterprise (DONE)
- Security Headers, CORS, Rate limiting, Refresh Tokens
- Security Audit Dashboard, IP Auto-Ban
- Account Lockout, NoSQL Injection protection
- Argon2id hashing, TOTP 2FA

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

## DB Collections
- `device_credentials`: Vault cifrato (id, device_ip, credential_type, username_enc, password_enc, external_url, direct_poll)
- `device_poll_status`: Stato polling (device_ip, reachable, redfish, hardware, polling_source)
- `connector_status`: Heartbeat connettori
- `audit_logs`: Log di sicurezza
- `alerts`: Alert attivi
- `device_metrics_history`: Storico metriche

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Notifiche Push Firebase (serve API Key utente)
- Notifiche Email SendGrid (serve API Key utente)
- Test connettore v2.0.0 sul server del cliente

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS per alert critici
- LDAP integration
- SNMP v3

### P3
- Refactoring server.py (~3000 righe) in moduli route separati
