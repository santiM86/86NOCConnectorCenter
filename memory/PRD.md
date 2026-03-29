# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: FastAPI modulare (18 file route), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish API

### Navigazione (4 gruppi)
```
MONITORAGGIO    -> Dashboard, Alert (badge), Stato Rete (mappa topologica + lista), Dispositivi
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
- [x] **Mappa Topologica Gerarchica** con inferenza automatica dei collegamenti:
  - Engine backend: classifica dispositivi (firewall/switch/server/iLO) e inferisce topologia
  - Layout: Internet -> Firewall -> Core Switch -> Access/Server/Management
  - 4 tipi collegamento: WAN, Trunk, Accesso, Management (MGMT)
  - Health Score 0-100% per cliente (reachability 50% + latency 25% + port health 25%)
  - Animazioni pulse sulle connessioni attive
  - Legenda tipi collegamento + gauge health score

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS
- [ ] LLDP/CDP neighbor discovery per topologia reale (attualmente inferita)
- [ ] Auto-discovery rete, LDAP, SNMP v3

## Test Reports
- iteration_20: Backend refactoring (100%)
- iteration_21: Menu restructuring (100%)
- iteration_22: Page split Stato Rete/Connettori (100%)
- iteration_23: Network Map basic (100%)
- iteration_24: Hierarchical Topology + Health Score (100%)
