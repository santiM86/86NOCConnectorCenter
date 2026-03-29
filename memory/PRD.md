# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: FastAPI modulare (18 file route in `/app/backend/routes/`), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12 (@xyflow/react)
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
- [x] Backend Refactoring: server.py da 3247 a 193 righe, 17 route modulari
- [x] **Mappa Topologica Enterprise con React Flow v12**:
  - Drag-and-drop libero dei nodi (i tecnici posizionano i dispositivi a piacimento)
  - Creazione/eliminazione manuale dei collegamenti tra dispositivi
  - Salvataggio layout personalizzato per cliente (MongoDB: topology_layouts)
  - Reset al layout auto-generato (inferenza automatica come proposta iniziale)
  - Auto-layout gerarchico: Internet -> Firewall -> Core Switch -> Access/Server/Mgmt
  - Minimap per navigazione rapida, zoom/pan, snap-to-grid
  - Legenda tipi collegamento: WAN, Trunk, Accesso, Server, MGMT, Manuale
  - Health Score 0-100% per cliente (reachability 50% + latency 25% + port health 25%)
  - Badge "Layout personalizzato" quando il tecnico ha salvato una mappa custom
  - Toolbar: Modifica (toggle mode), Auto (ricalcola), Reset, Salva Layout

## Key API Endpoints (Topology)
- GET `/api/network/topology/{client_id}` - Restituisce nodi/edges + health. Se esiste un layout salvato, lo restituisce con i dati live dei dispositivi.
- POST `/api/network/topology/{client_id}/layout` - Salva il layout personalizzato (posizioni nodi + edges custom)
- DELETE `/api/network/topology/{client_id}/layout` - Elimina il layout personalizzato, torna all'inferenza automatica

## DB Collections (Topology)
- `topology_layouts`: {client_id, nodes: [{id, position: {x,y}, name, type, ...}], edges: [{from, to, type, label}], updated_at, updated_by}

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED - richiede API Key utente)
- [ ] Notifiche Email SendGrid (MOCKED - richiede API Key utente)
### P2
- [ ] LLDP/CDP neighbor discovery per topologia reale automatica (interrogazione SNMP LLDP-MIB OID 1.0.8802.1.1.2)
- [ ] SOC AI: correlazione, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS
- [ ] Auto-discovery rete, LDAP, SNMP v3

## Test Reports
- iteration_20: Backend refactoring (100%)
- iteration_21: Menu restructuring (100%)
- iteration_22: Page split Stato Rete/Connettori (100%)
- iteration_23: Network Map basic (100%)
- iteration_24: Hierarchical Topology + Health Score (100%)
- iteration_25: React Flow Enterprise Map + Layout Save/Reset (100%)
