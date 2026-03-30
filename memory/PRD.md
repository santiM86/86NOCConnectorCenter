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
- [x] **Topologia Enterprise 6-Layer** (Verificata 30/03/2026):
  - Internet -> Firewall -> Core Switch -> Distribution -> Access -> Endpoints
  - Edge LLDP con etichette porta-per-porta
  - Edge MAC Table con etichette velocita (10G) - SOLO su connessioni confermate
  - Edge inferiti generici (senza falsi 10G)
  - Health score (reachability, latency, port health)
- [x] **Albero Completo con Endpoint Scoperti** (Aggiunto 30/03/2026):
  - Tutti i MAC address trovati nelle MAC Table vengono mostrati come nodi foglia
  - Ogni endpoint mostra: hostname, IP, MAC address, porta dello switch, VLAN
  - Classificazione automatica tipo endpoint (server, stampante, camera, AP, NAS, generico)
  - Edge da switch a endpoint con label porta e velocita
  - Collection MongoDB: discovered_endpoints
- [x] **Bug Fix 10G Labels** (Corretto 30/03/2026):
  - Le etichette 10G ora appaiono SOLO su connessioni confermate dalla MAC Table
  - Connessioni inferite usano label generiche (non piu basate sul nome del modello)
  - Stile visivo: 10G = arancione spesso animato, 1G = grigio sottile

## Key API Endpoints
- POST `/api/connector/network-discovery` - MAC tables + port speeds + device MACs + discovered_endpoints
- GET `/api/network/topology/{client_id}` - Topologia completa con endpoint scoperti
- POST `/api/network/topology/{client_id}/layout` - Salva layout
- DELETE `/api/network/topology/{client_id}/layout` - Reset layout

## DB Collections
- `discovered_endpoints`: Tutti i MAC trovati per switch/porta (NEW)
- `lldp_neighbors`: neighbor LLDP per cliente
- `mac_connections`: connessioni inferite da MAC table
- `port_speeds`: porte high-speed per switch
- `topology_layouts`: layout personalizzati per cliente

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
- [ ] Polling ARP Table nel connettore per risolvere MAC->IP di endpoint sconosciuti
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery

## Test Reports
- iteration_25: React Flow Enterprise Map (100%)
- iteration_26: LLDP Discovery Backend + Frontend (100%)
- iteration_27: Enterprise Topology 6-Layer (100% - 21/21 backend)
- iteration_28: Discovered Endpoints + 10G Bug Fix (100% - 18/18 backend)
