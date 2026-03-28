# NOC Alert Command Center - PRD

## Descrizione Prodotto
Piattaforma NOC enterprise-grade per il monitoraggio in tempo reale di dispositivi di rete (switch, firewall, server) tramite SNMP, Syslog e Redfish. Include un connettore Windows nativo (PowerShell) per l'installazione sui server dei clienti.

## Architettura
- **Backend**: Python 3.11, FastAPI, MongoDB, AES-256-GCM encryption
- **Frontend**: React, TailwindCSS, Shadcn UI, PWA
- **Windows Connector**: PowerShell 5.1+, Raw UDP/BER per SNMP, Redfish API

### Struttura Backend (Post-Refactoring v2.3.0)
```
/app/backend/
├── server.py (193 righe - app init, middleware, router includes)
├── database.py (connessione MongoDB)
├── deps.py (dipendenze condivise: auth, JWT, services, IP blocking)
├── models.py (modelli Pydantic)
├── security.py / audit.py / notifications.py / redfish.py
├── routes/
│   ├── auth.py, admin.py, clients.py, devices.py
│   ├── alerts.py, audit_routes.py, vault.py
│   ├── redfish_routes.py, settings.py, ingestion.py
│   ├── connector.py, discovery.py, web_proxy.py
```

### Navigazione Frontend (Ristrutturata)
```
MONITORAGGIO      → Dashboard, Alert (con badge), Dispositivi
INFRASTRUTTURA    → Clienti, Connettori
SICUREZZA         → Vault Credenziali, Audit & Compliance, Gestione Utenti
SISTEMA           → Impostazioni
```
Gruppi collassabili, visibilita basata sul ruolo, badge alert live, indicatore attivo indigo.

## Funzionalita Implementate
- [x] Autenticazione JWT con 2FA (TOTP/Microsoft Authenticator)
- [x] Gestione utenti con ruoli (admin/operator/viewer)
- [x] Gestione clienti con API key
- [x] Gestione dispositivi SNMP/Ping/Redfish
- [x] Alert management con correlazione intelligente
- [x] Dashboard statistiche in tempo reale + WebSocket
- [x] Audit logging + Security Dashboard + IP blocking
- [x] Credential Vault AES-256-GCM
- [x] Metriche PING avanzate (jitter, packet loss, TCP scan, HTTP check)
- [x] Power Control Redfish iLO + Wake-on-LAN
- [x] Windows Connector v2.3.0 con auto-update
- [x] Menu ristrutturato con 4 gruppi logici

## Backlog

### P1 - Prossimi
- [ ] Notifiche Push Firebase (MOCKED - serve API Key utente)
- [ ] Notifiche Email SendGrid (MOCKED - serve API Key utente)

### P2 - Futuri
- [ ] SOC AI: correlazione intelligente, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS per alert critici
- [ ] Auto-discovery rete, LDAP, SNMP v3

## Test Reports
- iteration_20.json: Server.py Refactoring Validation (100%)
- iteration_21.json: Navigation Menu Restructuring (100%)
