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
- [x] LLDP Discovery + MAC Table Discovery + Port Speed Detection
- [x] Albero completo con endpoint scoperti (MAC -> IP -> hostname)
- [x] Bug fix 10G: Solo connessioni confermate da MAC Table
- [x] **Nomi dispositivi abbreviati** (es. "NETGEAR GS110EMX - Under Counter 5m")
- [x] **MAC address visibili** sui nodi gestiti (enrichment da device_macs)

### Enterprise Features
- [x] **Pannello Dettagli**: Click su nodo -> info, alert, porte 10G, endpoint, LLDP, MAC
- [x] **Aggiornamento Real-time**: Auto-refresh 30s + timestamp + pulsante manuale
- [x] **Ricerca**: Cerca per nome/IP/MAC con highlight/dim
- [x] **Filtri Tipo/Stato**: Switch, Firewall, Server, Endpoint, AP WiFi / Online, Offline, Con Alert
- [x] **Export PNG**: Esporta mappa come immagine
- [x] **Alert Badge/Correlazione Impatto**: Badge rosso + figli offline marcati "Impattato"
- [x] **Animazione Blinking**: Nodi offline lampeggiano

### Azioni Endpoint (Aggiunto 30/03/2026)
- [x] **Apri Pagina Web**: Pulsante per aprire http://{ip} in nuova tab (per tutti i dispositivi con IP)
- [x] **Aggiungi al Monitoraggio**: Promuovi discovered endpoint a dispositivo monitorato
  - Selettore tipo PING/SNMP con campo community
  - Protezione duplicati (HTTP 409)
  - Aggiornamento automatico: endpoint marcato is_managed, scompare dai discovered
  - Refresh mappa dopo aggiunta

### Connettore Windows (v2.5.0)
- [x] Servizio NSSM (sopravvive disconnessione RDP)
- [x] Network Discovery (LLDP + MAC + Speed)
- [x] Auto-aggiornamento robusto

## Key API Endpoints
- GET `/api/network/topology/{client_id}` - Topologia completa con MAC enrichment
- GET `/api/network/device-detail/{client_id}/{device_ip}` - Dettagli dispositivo
- GET `/api/network/alerts-summary/{client_id}` - Alert per device IP
- POST `/api/network/add-to-monitoring` - Promuovi endpoint a monitorato
- POST/DELETE `/api/network/topology/{client_id}/layout` - Salva/Reset layout

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED)
- [ ] Notifiche Email SendGrid (MOCKED)
- [ ] Polling ARP Table per MAC->IP
### P2
- [ ] SOC AI: correlazione, auto-triage
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery
- [ ] Vista Multi-Sito, Storico Topologia, Traffic monitoring

## Test Reports
- iteration_25-29: Tutte passate (100%)
- iteration_30: Nomi abbreviati + MAC enrichment + Azioni Endpoint (100% - 12/12 backend)
