# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: FastAPI modulare, MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12, html-to-image, Recharts
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
- [x] Nomi dispositivi abbreviati (es. "NETGEAR GS110EMX - Under Counter 5m")
- [x] MAC address visibili sui nodi gestiti

### Enterprise Features
- [x] Pannello Dettagli: Click su nodo -> info, alert, porte 10G, endpoint, LLDP, MAC
- [x] Aggiornamento Real-time: Auto-refresh 30s + timestamp + pulsante manuale
- [x] Ricerca: Cerca per nome/IP/MAC con highlight/dim
- [x] Filtri Tipo/Stato: Switch, Firewall, Server, Endpoint, AP WiFi / Online, Offline, Con Alert
- [x] Export PNG: Esporta mappa come immagine
- [x] Alert Badge/Correlazione Impatto: Badge rosso + figli offline marcati "Impattato"
- [x] Animazione Blinking: Nodi offline lampeggiano

### Azioni Endpoint
- [x] Apri Pagina Web: Pulsante per aprire http://{ip} in nuova tab
- [x] Aggiungi al Monitoraggio: Promuovi discovered endpoint a dispositivo monitorato

### Dashboard Metriche Zabbix-style (30/03/2026)
- [x] SLA Gauge Widget: Uptime % per dispositivo con gauge visivo e filtri 7/30/90 giorni
- [x] Change Timeline Widget: Rilevamento modifiche rete (device added/removed/status/ports)
- [x] Uptime Heatmap Widget: Griglia disponibilita 24h per dispositivo con colori
- [x] Latency Chart Widget: Grafico a barre latenza 24h per dispositivo selezionato

### Report PDF (30/03/2026 - Ispirato a PRTG)
- [x] Generazione report PDF professionale per cliente con logo 86BIT
- [x] Include: Riepilogo Esecutivo, SLA per Dispositivo, Lista Dispositivi, Alert, Modifiche Rete
- [x] Selezione periodo (7/30/90 giorni) e cliente
- [x] Download diretto del PDF dal browser

### Inventario Dispositivi (30/03/2026 - Ispirato a PRTG Device Tree)
- [x] Vista tabellare completa di tutti i dispositivi: IP, MAC, modello, firmware, uptime, porte
- [x] Filtri per tipo (switch/firewall/server/AP), stato (online/offline), ricerca testuale
- [x] Ordinamento per qualsiasi colonna
- [x] Statistiche aggregate (totale, online, offline, tipi)

### Gestione Incidenti (30/03/2026 - Ispirato a CloudFire SOC/NOC)
- [x] CRUD completo incidenti con titolo, descrizione, cliente, priorita
- [x] Stati: Aperto, In Corso, Risolto, Chiuso
- [x] Timeline incidente: ogni azione tracciata con utente e timestamp
- [x] Aggiunta note operative all'incidente
- [x] Statistiche (aperti, in corso, risolti, totale, per priorita)

### Monitor Servizi TCP (30/03/2026 - Ispirato a PRTG Port Sensor)
- [x] Monitoraggio porte TCP su dispositivi (HTTP, SSH, RDP, SMTP, ecc.)
- [x] 18 porte comuni preconfigurate
- [x] Controllo connettivita con tempo di risposta in ms
- [x] Aggiunta/rimozione servizi da monitorare

### Dashboard Pubblica Condivisibile (30/03/2026 - Ispirato a PRTG)
- [x] URL unico per cliente accessibile SENZA login
- [x] Mostra: SLA uptime, dispositivi online/offline, alert attivi
- [x] Auto-refresh 30 secondi
- [x] Attivabile/disattivabile dall'admin

### Template Notifiche Multi-Canale (30/03/2026 - Ispirato a PRTG)
- [x] Template personalizzabili per severita (critico/alto/medio/basso)
- [x] Canali: Email, SMS, Push, Webhook HTTP, Microsoft Teams
- [x] Regole di escalation configurabili (minuti, destinatario)
- [x] CRUD completo template (invio reale MOCKATO - richiede API key esterne)

### Connettore Windows (v2.5.0)
- [x] Servizio NSSM (sopravvive disconnessione RDP)
- [x] Network Discovery (LLDP + MAC + Speed)
- [x] Auto-aggiornamento robusto

## Key API Endpoints
- GET `/api/network/topology/{client_id}` - Topologia completa con MAC enrichment
- GET `/api/network/device-detail/{client_id}/{device_ip}` - Dettagli dispositivo
- POST `/api/network/add-to-monitoring` - Promuovi endpoint a monitorato
- GET `/api/metrics/sla/{client_id}` - SLA per dispositivo
- GET `/api/metrics/changes/{client_id}` - Modifiche rete
- GET `/api/metrics/heatmap/{client_id}` - Heatmap disponibilita
- GET `/api/reports/generate/{client_id}` - Genera report PDF
- GET `/api/inventory/{client_id}` - Inventario dispositivi
- GET/POST/PATCH/DELETE `/api/incidents` - Gestione incidenti
- GET/POST/DELETE `/api/port-monitor/services` - Monitor servizi TCP
- POST `/api/port-monitor/check/{client_id}` - Controlla porte
- GET `/api/public/dashboard/{token}` - Dashboard pubblica (NO AUTH)
- GET/POST/PUT/DELETE `/api/notifications/templates` - Template notifiche

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
### P2
- [ ] SOC AI: correlazione intelligente, auto-triage tramite LLM
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery
- [ ] Vista Multi-Sito, Storico Topologia, Traffic monitoring
- [ ] Vista Sunburst/Raggiera della rete
- [ ] Reportistica Predittiva (trend utilizzo, previsioni)
- [ ] Monitoraggio Bandwidth/Traffic reale (ifInOctets/ifOutOctets)

## Test Reports
- iteration_25-30: Topologia mappa enterprise (100%)
- iteration_31: Report PDF + Inventario + Incidenti + Port Monitor + Dashboard Pubblica + Notifiche + Widget Zabbix (100% - 36/36 backend, 100% frontend)
