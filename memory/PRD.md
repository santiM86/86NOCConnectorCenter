# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: FastAPI modulare, MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12, html-to-image
- Connector: PowerShell 5.1+, SNMP, Redfish, LLDP, MAC Table, Port Speed, NSSM Service

## Funzionalita Implementate

### Core
- [x] Auth JWT + 2FA TOTP + Ruoli (admin/operator/viewer)
- [x] SNMP/Ping/Redfish monitoring
- [x] Alert + correlazione + WebSocket
- [x] Credential Vault AES-256-GCM

### Mappa Enterprise React Flow
- [x] Drag-and-drop interattivo con salvataggio layout
- [x] Topologia 6-Layer: Internet -> Firewall -> Core -> Distribution -> Access -> Endpoint
- [x] LLDP Discovery (connessioni porta-per-porta)
- [x] MAC Address Table Discovery (connessioni fisiche, 10G)
- [x] Port Speed Detection (ifHighSpeed)
- [x] **Albero completo con endpoint scoperti** (MAC -> IP -> hostname su ogni switch)
- [x] **Bug fix 10G**: Solo connessioni confermate da MAC Table mostrano 10G

### Enterprise Features (Aggiunto 30/03/2026)
- [x] **Pannello Dettagli Dispositivo**: Click su nodo -> pannello laterale con:
  - Info dispositivo (stato, nome, monitor type, latenza, sys description)
  - Alert (count + lista con severity e timestamp)
  - Porte High-Speed (10G ports)
  - Endpoint connessi (MAC discovered)
  - LLDP Neighbors
  - Connessioni MAC
- [x] **Aggiornamento Real-time**: Auto-refresh ogni 30s + timestamp visibile
- [x] **Barra di Ricerca**: Cerca per nome, IP, MAC con highlight/dim
- [x] **Filtri Tipo**: Tutti, Switch, Firewall, Server, Endpoint, AP WiFi
- [x] **Filtri Stato**: Tutti, Online, Offline, Con Alert
- [x] **Export PNG**: Esporta mappa come immagine ad alta risoluzione
- [x] **Alert Badge sui Nodi**: Numero alert con colore rosso animato
- [x] **Correlazione Impatto**: Nodi figli di device offline marcati "Impattato" (amber)
- [x] **Animazione Blinking**: Nodi offline lampeggiano

### Connettore Windows (v2.5.0)
- [x] Servizio NSSM (sopravvive disconnessione RDP)
- [x] Network Discovery (LLDP + MAC + Speed)
- [x] Auto-aggiornamento robusto

## Key API Endpoints
- GET `/api/network/topology/{client_id}` - Topologia completa
- GET `/api/network/device-detail/{client_id}/{device_ip}` - Dettagli dispositivo
- GET `/api/network/alerts-summary/{client_id}` - Alert per device IP
- POST `/api/network/topology/{client_id}/layout` - Salva layout
- DELETE `/api/network/topology/{client_id}/layout` - Reset layout
- POST `/api/connector/network-discovery` - Dati MAC/Speed dal connettore

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
- [ ] Polling ARP Table nel connettore per risolvere MAC->IP
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery
- [ ] Vista Multi-Sito (mappa generale con tutti i clienti)
- [ ] Storico Topologia (confronto nel tempo, notifiche cambiamenti)
- [ ] Monitoring traffico sugli edge (ifInOctets/ifOutOctets con colori saturazione)

## Test Reports
- iteration_25: React Flow Enterprise Map (100%)
- iteration_26: LLDP Discovery Backend + Frontend (100%)
- iteration_27: Enterprise Topology 6-Layer (100%)
- iteration_28: Discovered Endpoints + 10G Bug Fix (100%)
- iteration_29: Enterprise Features (Search/Filter/Detail/Real-time/Export) (100%)
