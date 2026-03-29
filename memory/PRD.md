# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: FastAPI modulare (17 file route), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish API

### Navigazione (4 gruppi)
```
MONITORAGGIO    -> Dashboard, Alert (badge), Stato Rete (mappa+lista), Dispositivi
INFRASTRUTTURA  -> Clienti, Connettori (solo agent)
SICUREZZA       -> Vault Credenziali, Audit & Compliance, Gestione Utenti
SISTEMA         -> Impostazioni
```

## Funzionalita Implementate
- [x] Auth JWT + 2FA TOTP + Refresh tokens + Ruoli
- [x] SNMP/Ping/Redfish device monitoring
- [x] Alert management + correlazione + WebSocket live
- [x] Security Dashboard + IP blocking + audit logs
- [x] Credential Vault AES-256-GCM
- [x] Metriche PING avanzate (jitter, packet loss, TCP scan, HTTP check)
- [x] Power Control Redfish iLO + Wake-on-LAN
- [x] Connector v2.3.0 con auto-update
- [x] Menu 4 gruppi + Stato Rete / Connettori separati
- [x] **Mappa Rete visuale** (topologia radiale SVG, animazioni pulse, legenda, tooltip, toggle Lista/Mappa)

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
- iteration_23: Network Map visualization (100%)
