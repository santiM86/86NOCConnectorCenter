# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: FastAPI modulare (18 file route), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12
- Connector: PowerShell 5.1+, SNMP, Redfish, LLDP, MAC Table, Port Speed, NSSM Service

### Architettura Connector (v2.5.0)
```
NSSM Windows Service -> connector.ps1 (LocalSystem, Session 0)
                        |-> SNMP Trap listener (UDP 162)
                        |-> Syslog listener (UDP 514)
                        |-> SNMP Polling (60s interval)
                        |-> Network Discovery (LLDP + MAC + Speed, ogni 10 cicli)
                        |-> scrive status.json
RDP Session (opzionale) -> tray_app.ps1 (monitoring/controllo)
```

## Funzionalita Implementate
- [x] Auth JWT + 2FA TOTP + Ruoli
- [x] SNMP/Ping/Redfish monitoring
- [x] Alert + correlazione + WebSocket
- [x] Credential Vault AES-256-GCM
- [x] Mappa Enterprise React Flow (drag-drop, save/reset layout)
- [x] **Network Discovery Potenziato (v2.5.0)**:
  - LLDP neighbor discovery (connessioni porta-per-porta)
  - MAC Address Table polling (Bridge-MIB) per rilevare connessioni fisiche
  - Port Speed detection (ifHighSpeed) per identificare uplink 10G
  - Combinazione LLDP + MAC + Speed per ricostruzione topologia reale
  - Badge LLDP e MAC sulla mappa
- [x] **Servizio Windows NSSM**:
  - Il connettore gira come vero Servizio Windows (LocalSystem)
  - Sopravvive a disconnessione RDP
  - Riavvio automatico su crash
  - Integrato nell'installer GUI
  - installa_servizio.bat per installazione standalone

## Key API Endpoints (Discovery)
- POST `/api/connector/lldp-neighbors` - Dati LLDP dal connettore
- POST `/api/connector/network-discovery` - MAC tables + port speeds
- GET `/api/network/lldp/{client_id}` - LLDP raw data
- GET `/api/network/topology/{client_id}` - Topologia (LLDP + MAC + inferred)

## DB Collections (Discovery)
- `lldp_neighbors`: neighbor LLDP per cliente
- `network_discovery`: MAC tables + port speeds raw
- `mac_connections`: connessioni inferite da MAC table (from_ip, from_port, to_ip)
- `port_speeds`: porte high-speed per switch
- `topology_layouts`: layout personalizzati per cliente

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery

## Test Reports
- iteration_25: React Flow Enterprise Map (100%)
- iteration_26: LLDP Discovery Backend + Frontend (100%)
