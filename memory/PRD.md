# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo
- **Auth**: JWT + MFA (TOTP)
- **Cifratura**: AES-256-GCM con ENCRYPTION_KEY persistente in .env

## Funzionalita Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Monitoraggio Dispositivi (DONE)
- SNMP polling (porte, sysDescr, uptime, trap)
- Ping+HTTP per dispositivi senza SNMP (switch smart managed)
- Auto-Discovery rete (ping sweep + port scan)
- Cambio tipo monitoraggio cliccando badge SNMP/PING

### Metriche Estese SNMP v1.8.0 (DONE)
- HPE 5130 (Comware): CPU, Memoria, Temperatura
- HPE ILO (ProLiant): Salute generale, temperature, ventole, alimentatori, dischi
- Generico: CPU tramite HOST-RESOURCES-MIB
- Traffico interfacce: Bandwidth IN/OUT, velocita, errori per porta

### Metriche Zyxel USG Firewall v1.9.0 (DONE)
- CPU (current/5s/1m/5m), RAM, sessioni attive, VPN IPSec, flash usage
- Firmware, product name, serial number
- Alert automatici su sessioni >50k e flash >90%

### Integrazione Redfish iLO v2.0.0 (DONE - 27 mar 2026)
- **Backend**: Endpoint `/api/connector/vault/credentials` per il connettore
- **Connector**: Funzione `Poll-RedfishMetrics` per iLO 4/5/6 via API REST
- **Connector**: `Fetch-VaultCredentials` recupera credenziali cifrate dal SOC
- **Frontend**: Sezione Redfish in DeviceDetailPanel (power, BIOS, RAM DIMM, NIC, storage)
- **Metriche Redfish**: Consumo Watt, BIOS version, server model, serial, UUID, iLO firmware, licenza, DIMM (size/speed), NIC (MAC/IP/speed), Storage controller + Logical Drive (RAID/capacity)

### Vault Credenziali AES-256-GCM (DONE - 27 mar 2026)
- CRUD completo: crea, lista, rivela, modifica, elimina
- Cifratura AES-256-GCM con chiave persistente in .env
- Accesso riservato solo ad admin (403 per altri ruoli)
- Auto-hide password dopo 30 secondi
- Filtri per tipo (iLO, SSH, SNMP, Web, VPN, Altro) e ricerca
- Audit log su ogni accesso alle credenziali
- Endpoint connector per fetch credenziali decifrate via API key
- **BUG FIX CRITICO**: ENCRYPTION_KEY ora persistente in .env (prima si rigenerava ad ogni riavvio)

### Security Enterprise (DONE)
- Security Headers, CORS, Rate limiting, Refresh Tokens, WS Auth
- Security Audit Dashboard con auto-refresh 15s
- IP Auto-Ban system (configurable thresholds)
- Account Lockout, NoSQL Injection protection
- Argon2id password hashing, TOTP 2FA

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

### Web Console Proxy v1.7.3 (DONE)
- Accesso alla web interface dei dispositivi direttamente dal SOC

### Connector v2.0.0 (DONE)
- SNMP Trap + Syslog, Polling SNMP esteso + Ping/HTTP
- Auto-Discovery, Web Console Proxy
- Heartbeat, auto-update, force update
- System tray con Mutex, diagnostica, import/export CSV
- Metriche estese HPE 5130, ILO, Zyxel USG
- **NUOVO**: Redfish iLO polling con credenziali dal Vault

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
