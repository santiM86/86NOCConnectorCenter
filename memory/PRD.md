# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: FastAPI modulare, MongoDB (Motor), AES-256-GCM
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
- [x] Nomi dispositivi abbreviati, MAC address visibili

### Enterprise Features
- [x] Pannello Dettagli: Click su nodo -> info, alert, porte 10G, endpoint, LLDP, MAC
- [x] Aggiornamento Real-time: Auto-refresh 30s + timestamp + pulsante manuale
- [x] Ricerca: Cerca per nome/IP/MAC con highlight/dim
- [x] Filtri Tipo/Stato: Switch, Firewall, Server, Endpoint, AP WiFi / Online, Offline, Con Alert
- [x] Export PNG: Esporta mappa come immagine
- [x] Alert Badge/Correlazione Impatto: Badge rosso + figli offline marcati "Impattato"

### Dashboard Metriche Zabbix-style
- [x] SLA Gauge Widget: Uptime % per dispositivo con gauge visivo
- [x] Change Timeline Widget: Rilevamento modifiche rete
- [x] Uptime Heatmap Widget: Griglia disponibilita 24h
- [x] Latency Chart Widget: Grafico a barre latenza 24h

### Report PDF (Ispirato a PRTG)
- [x] Generazione report PDF professionale per cliente con logo 86BIT
- [x] Include: Riepilogo Esecutivo, SLA per Dispositivo, Lista Dispositivi, Alert, Modifiche Rete
- [x] Selezione periodo (7/30/90 giorni) e cliente

### Inventario Dispositivi (Ispirato a PRTG Device Tree)
- [x] Vista tabellare completa di tutti i dispositivi
- [x] Filtri per tipo, stato, ricerca testuale, ordinamento

### Gestione Incidenti (Ispirato a CloudFire SOC/NOC)
- [x] CRUD completo incidenti con titolo, descrizione, cliente, priorita
- [x] Timeline incidente con note operative

### Monitor Servizi TCP (Ispirato a PRTG Port Sensor)
- [x] Monitoraggio porte TCP su dispositivi (HTTP, SSH, RDP, etc.)
- [x] 18 porte comuni preconfigurate

### Dashboard Pubblica Condivisibile (Ispirato a PRTG)
- [x] URL unico per cliente accessibile SENZA login
- [x] Auto-refresh 30 secondi

### Template Notifiche Multi-Canale
- [x] Template personalizzabili per severita
- [x] Canali: Email, SMS, Push, Webhook HTTP, Microsoft Teams
- [x] Regole di escalation configurabili

### TV Dashboard NOC (30/03/2026 - NUOVA, MIGLIORATA)
- [x] Pagina fullscreen a /tv accessibile SENZA login per monitor a parete
- [x] Header con logo NOC, titolo 86BIT, orologio in tempo reale, badge stato globale (TUTTI OPERATIVI/ATTENZIONE)
- [x] 8 stat block grandi: Dispositivi, Online, Offline, Critici, Alert, Incidenti, Stampanti, Toner
- [x] **Layout 3 colonne**: Clienti+Connettori | Offline+Incidenti | Alert+Toner
- [x] **Dispositivi Offline**: pallino rosso pulsante, nome, IP, cliente, "da Xh Ym fa"
- [x] **Incidenti Aperti**: badge priorita P1-P4 colorati, stato APERTO/IN CORSO
- [x] **Alert Arricchiti**: nome dispositivo, IP, nome cliente, messaggio, time_ago
- [x] **Stato Connettori**: chip con hostname, versione, stato online/offline, ultimo heartbeat
- [x] **Consumabili Bassi**: barre toner con colori reali e percentuali
- [x] **Ticker Scorrevole**: badge LIVE rosso + ultimi eventi che scorrono in basso
- [x] Link "TV Dashboard" nel menu laterale sotto SISTEMA con icona Monitor e apertura in nuova tab
- [x] Utente TV dedicato (tv@86bit.it / Tv86bit!2026, ruolo viewer)
- [x] **Sistema allarme sonoro**: beep tramite Web Audio API quando un nuovo dispositivo va offline (triplo beep) o arriva un alert critico (doppio beep)
- [x] **Pulsante Audio ON/OFF**: nell'header, click per abilitare/disabilitare i suoni (rispetta la policy autoplay del browser)
- [x] **Banner allarme**: notifica visiva con animazione slide-in quando scatta l'allarme, scompare dopo 30s
- [x] Auto-refresh ogni 15 secondi, dark theme ottimizzato per TV
- [x] Layout responsivo (1080p/4K), nessun sidebar

### Gestione Stampanti SNMP (30/03/2026 - NUOVA)
- [x] Dashboard stampanti con statistiche (online/offline/toner basso/pagine totali)
- [x] Card stampante espandibile con dettagli consumabili, vassoi carta, contatori
- [x] Barre toner con colori reali (nero, cyan, magenta, giallo)
- [x] Avvisi automatici per toner basso (<= 15%) con alert DB
- [x] Sezione "AVVISI TONER BASSO" con livelli colorati
- [x] Endpoint process-poll per ricezione dati dal connettore (senza JWT, con API key opzionale)
- [x] Seed demo per 4 stampanti di test
- [x] Storico consumabili (supply_history) con TTL 90 giorni
- [x] Opzione "Stampante SNMP" nel form di aggiunta dispositivi
- [x] device_type nel modello ManagedDevice (network/printer)
- [x] Connettore PowerShell aggiornato con Poll-PrinterData e Poll-AllPrinters (OID Printer-MIB)
- [x] Indici MongoDB ottimizzati per printer_status e printer_history

### Vulnerability Assessment (30/03/2026 - NUOVA, ispirata a Nethesis VA)
- [x] Dashboard VA con Security Score (0-100) per dispositivo e per cliente
- [x] Knowledge base di 18+ porte pericolose con severita e remediation
- [x] Rilevamento automatico: porte pericolose (Telnet, FTP, RDP, SMB, VNC), SNMP community di default, HTTP senza HTTPS, SNMPv1/v2c
- [x] Barra distribuzione severita colorata (Critico/Alto/Medio/Basso)
- [x] 3 tab: Dispositivi (con score individuale), Vulnerabilita (lista ordinata), Piano di Remediation (azioni numerate)
- [x] Dettaglio vulnerabilita per dispositivo con espansione inline
- [x] Pulsante "Avvia Scansione" per registrare assessment
- [x] Storico scansioni con trend temporale
- [x] Remediation Summary con azioni raggruppate per priorita e dispositivi interessati
- [x] Navigazione sotto SICUREZZA con icona ShieldCheck

### Connettore Windows (v2.5.0+)
- [x] Servizio NSSM (sopravvive disconnessione RDP)
- [x] Network Discovery (LLDP + MAC + Speed)
- [x] Auto-aggiornamento robusto
- [x] Polling stampanti SNMP con Printer-MIB OIDs

## Key API Endpoints
- GET `/api/network/topology/{client_id}` - Topologia completa con MAC enrichment
- GET `/api/metrics/sla/{client_id}` - SLA per dispositivo
- GET `/api/reports/generate/{client_id}` - Genera report PDF
- GET `/api/inventory/{client_id}` - Inventario dispositivi
- GET/POST/PATCH/DELETE `/api/incidents` - Gestione incidenti
- GET/POST/DELETE `/api/port-monitor/services` - Monitor servizi TCP
- GET `/api/public/dashboard/{token}` - Dashboard pubblica (NO AUTH)
- GET/POST/PUT/DELETE `/api/notifications/templates` - Template notifiche
- **GET `/api/vulnerability/dashboard/{client_id}`** - Dashboard VA con score, vulnerabilita, remediation
- **GET `/api/vulnerability/device/{client_id}/{device_ip}`** - Dettaglio VA per dispositivo
- **POST `/api/vulnerability/run-scan/{client_id}`** - Registra scansione VA
- **GET `/api/vulnerability/history/{client_id}`** - Storico scansioni VA
- **GET `/api/tv/dashboard`** - Dashboard TV aggregata (NO AUTH)
- **GET `/api/printers/dashboard/{client_id}`** - Dashboard stampanti
- **GET `/api/printers/{client_id}`** - Lista stampanti
- **GET `/api/printers/{client_id}/{device_ip}`** - Dettaglio stampante con storico
- **POST `/api/printers/process-poll`** - Ricezione dati polling dal connettore
- **POST `/api/printers/seed-demo/{client_id}`** - Seed dati demo stampanti

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
- iteration_31: Report PDF + Inventario + Incidenti + Port Monitor + Dashboard Pubblica + Notifiche + Widget Zabbix (100%)
- iteration_32: Gestione Stampanti SNMP (100% - Backend 14/14, Frontend 100%)
- iteration_33: TV Dashboard NOC (100% - Backend 8/8, Frontend 11/11)
- iteration_34: Sidebar link TV + Utente TV (100% - Backend 3/3, Frontend 10/10)
- iteration_35: TV Dashboard Migliorata 3-colonne (100% - Backend 17/17, Frontend 13/13)
- iteration_36: Vulnerability Assessment (100% - Backend 24/24, Frontend 95%)
