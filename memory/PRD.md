# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: FastAPI modulare (18 file route in `/app/backend/routes/`), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12 (@xyflow/react)
- Connector: PowerShell 5.1+, SNMP, Redfish API, LLDP Discovery

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
- [x] Backend Refactoring: server.py da 3247 a 193 righe, 17 route modulari
- [x] **Mappa Topologica Enterprise con React Flow v12**:
  - Drag-and-drop libero dei nodi
  - Creazione/eliminazione manuale dei collegamenti
  - Salvataggio layout personalizzato per cliente (MongoDB: topology_layouts)
  - Reset al layout auto-generato
  - Auto-layout gerarchico, Minimap, zoom/pan, snap-to-grid
  - Health Score 0-100% per cliente
- [x] **LLDP Discovery (Link Layer Discovery Protocol)**:
  - Polling LLDP-MIB (1.0.8802.1.1.2) su tutti gli switch SNMP managed
  - Raccolta neighbor table con: sistema remoto, porte locali/remote, chassis ID, IP management
  - Invio dati al backend via POST /api/connector/lldp-neighbors
  - Sostituzione intelligente: edge LLDP (reali) sostituiscono edge inferiti dove si sovrappongono
  - Etichette porta-per-porta sugli edge LLDP (es. "GigabitEthernet 48 <-> GigabitEthernet 1")
  - Badge "LLDP: X connessioni" nella mappa quando dati LLDP sono disponibili
  - Edge LLDP animati in cyan nella mappa, distinti visivamente dagli altri tipi
  - Esecuzione ogni 10 cicli di polling (insieme al refresh dispositivi)

## Key API Endpoints (Topology + LLDP)
- GET `/api/network/topology/{client_id}` - Nodi/edges + health + LLDP
- POST `/api/network/topology/{client_id}/layout` - Salva layout personalizzato
- DELETE `/api/network/topology/{client_id}/layout` - Reset layout
- POST `/api/connector/lldp-neighbors` - Riceve dati LLDP dal connettore (auth: X-API-Key)
- GET `/api/network/lldp/{client_id}` - Dati LLDP raw (auth: JWT)

## DB Collections (LLDP)
- `lldp_neighbors`: {client_id, local_ip, local_port_id, local_port_desc, remote_ip, remote_sys_name, remote_port_id, remote_port_desc, remote_sys_desc, remote_chassis_id, updated_at}

## LLDP OID Reference
- lldpRemSysName: 1.0.8802.1.1.2.1.4.1.1.9
- lldpRemPortId: 1.0.8802.1.1.2.1.4.1.1.7
- lldpRemPortDesc: 1.0.8802.1.1.2.1.4.1.1.8
- lldpRemSysDesc: 1.0.8802.1.1.2.1.4.1.1.10
- lldpRemChassisId: 1.0.8802.1.1.2.1.4.1.1.5
- lldpRemManAddr: 1.0.8802.1.1.2.1.4.2.1.4
- lldpLocPortId: 1.0.8802.1.1.2.1.3.7.1.3
- lldpLocPortDesc: 1.0.8802.1.1.2.1.3.7.1.4

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED - richiede API Key utente)
- [ ] Notifiche Email SendGrid (MOCKED - richiede API Key utente)
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS
- [ ] Auto-discovery rete, LDAP, SNMP v3

## Test Reports
- iteration_25: React Flow Enterprise Map + Layout Save/Reset (100%)
- iteration_26: LLDP Discovery Feature - Backend + Frontend (100%)
