# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete (switch, firewall, server) tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: Python 3.11, FastAPI, MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish API

### Backend modulare (17 file)
server.py (193 righe), database.py, deps.py, models.py, routes/{auth, admin, clients, devices, alerts, audit_routes, vault, redfish_routes, settings, ingestion, connector, discovery, web_proxy}.py

### Navigazione Frontend (4 gruppi + 2 pagine separate)
```
MONITORAGGIO    -> Dashboard, Alert (badge), Stato Rete (NUOVO), Dispositivi
INFRASTRUTTURA  -> Clienti, Connettori (solo agent management)
SICUREZZA       -> Vault Credenziali, Audit & Compliance, Gestione Utenti
SISTEMA         -> Impostazioni
```

### Pagine separate
- **Stato Rete** (/network-status): Monitoraggio dispositivi per cliente, discovery, export/import CSV, web console
- **Connettori** (/connectors): Gestione agent 86NocConnector, download, auto-update, force update

## Funzionalita Implementate
- [x] Auth JWT + 2FA TOTP + Refresh tokens
- [x] Gestione utenti (admin/operator/viewer)
- [x] Gestione clienti con API key
- [x] SNMP/Ping/Redfish device monitoring
- [x] Alert management + correlazione + WebSocket live
- [x] Security Dashboard + IP blocking + audit logs
- [x] Credential Vault AES-256-GCM
- [x] Metriche PING avanzate (jitter, packet loss, TCP scan, HTTP check)
- [x] Power Control Redfish iLO + Wake-on-LAN
- [x] Connector v2.3.0 con auto-update
- [x] Menu ristrutturato 4 gruppi + pagine separate Stato Rete/Connettori

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS
- [ ] Auto-discovery, LDAP, SNMP v3

## Test Reports
- iteration_20: Backend refactoring (100%)
- iteration_21: Menu restructuring (100%)
- iteration_22: Page split Stato Rete/Connettori (100%)
