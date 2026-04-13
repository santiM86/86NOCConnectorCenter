# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

## Architettura
- Backend: Python 3.11, FastAPI, MongoDB (Motor), AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, Recharts, PWA
- Connector: PowerShell 5.1+, SNMP, Redfish, LLDP, MAC Table

## Funzionalita Implementate

### Core
- [x] Auth JWT + 2FA TOTP + Ruoli (admin/operator/viewer)
- [x] SNMP/Ping/Redfish monitoring
- [x] Alert + correlazione + WebSocket
- [x] Credential Vault AES-256-GCM

### Mappa Enterprise React Flow
- [x] Drag-and-drop interattivo con salvataggio layout
- [x] Topologia 6-Layer + LLDP/MAC Discovery + Port Speed

### Dashboard Metriche Zabbix-style
- [x] SLA Gauge, Change Timeline, Uptime Heatmap, Latency Chart

### Report PDF (PRTG-style)
- [x] Report professionale per cliente

### TV Dashboard NOC
- [x] Pagina fullscreen /tv, layout 3 colonne, allarmi sonori

### Gestione Stampanti SNMP
- [x] Dashboard stampanti, barre toner, avvisi automatici

### Vulnerability Assessment (COMPLETATO)
- [x] Dashboard VA con Security Score, Knowledge Base, Remediation
- [x] Scansione Remota via heartbeat pending_commands
- [x] Report PDF esaustivo 11 pagine
- [x] Progresso real-time con barra animata

### Grafici Trend (NUOVO - 13/04/2026)
- [x] Pagina /trends con 4 grafici Recharts
- [x] Disponibilita Rete (AreaChart), Latenza Media (LineChart)
- [x] Score VA nel tempo (AreaChart), Alert per giorno (BarChart)
- [x] Selettore periodo: 24h, 3gg, 7gg, 30gg

### Auto-Discovery Rete (NUOVO - 13/04/2026)
- [x] Pagina /discovery con scansione rete da connettore
- [x] Approvazione/Ignora dispositivi scoperti
- [x] Polling automatico stato durante scansione
- [x] Visualizzazione dispositivi gia gestiti

### Soglie Alert Personalizzabili (NUOVO - 13/04/2026)
- [x] Pagina /thresholds con 4 gruppi (Connettivita, Hardware, Bandwidth, Stampanti)
- [x] Soglie configurabili per cliente: ping, packetloss, CPU, RAM, toner, bandwidth
- [x] Pulsante Salva con feedback visivo

### Manutenzione Programmata (NUOVO - 13/04/2026)
- [x] Pagina /maintenance con CRUD completo
- [x] Creazione finestre con titolo, date, dispositivi coinvolti
- [x] Soppressione automatica alert durante manutenzione
- [x] Stato visivo: In Corso (amber), Programmata (blue), Completata (gray)
- [x] API /api/maintenance/active/{client_id} per alert engine

### Monitoraggio Bandwidth (NUOVO - 13/04/2026)
- [x] Pagina /bandwidth con riepilogo interfacce per dispositivo
- [x] Metriche: IN/OUT bps, utilizzo %, velocita interfaccia
- [x] Grafici storici AreaChart per interfaccia
- [x] Backend: raccolta ifInOctets/ifOutOctets, retention 7 giorni

### SOC AI Correlation (NUOVO - 13/04/2026)
- [x] Pagina /correlation con analisi intelligente rule-based
- [x] 5 pattern di correlazione: guasto upstream, degradazione performance, flapping, WAN failure, cluster sicurezza
- [x] Indicatore di confidenza (%) per ogni correlazione
- [x] Azione consigliata per ogni pattern rilevato
- [x] Banner manutenzione attiva

### Portale Cliente Multi-tenant (NUOVO - 13/04/2026)
- [x] Pagina pubblica /portal (no auth)
- [x] Dashboard dedicata con SLA 30gg, dispositivi, alert
- [x] Accesso tramite ID cliente
- [x] Vista dispositivi + alert recenti

### Connettore Windows (v2.5.0+)
- [x] Servizio NSSM + Network Discovery + Auto-aggiornamento
- [x] Polling stampanti + Esecuzione remota VA Scan

## Key API Endpoints
- GET `/api/trends/{client_id}` - Trend storici
- GET/POST `/api/thresholds/{client_id}` - Soglie personalizzabili
- CRUD `/api/maintenance/{client_id}` - Finestre manutenzione
- GET `/api/maintenance/active/{client_id}` - Check manutenzione attiva
- GET `/api/correlation/{client_id}` - Analisi correlazione
- GET `/api/bandwidth/summary/{client_id}` - Riepilogo bandwidth
- GET `/api/bandwidth/{client_id}/{device_ip}` - Storico bandwidth
- POST `/api/bandwidth/process-poll` - Ricezione dati dal connettore
- POST `/api/discovery/approve` - Approva dispositivo scoperto
- POST `/api/discovery/dismiss` - Ignora dispositivo scoperto
- GET `/api/portal/{client_id}` - Portale cliente (pubblico)

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
- [ ] Notifiche Telegram (quando utente fornira bot token)
### P2
- [ ] SOC AI con LLM (GPT/Claude/Gemini) per correlazione avanzata
- [ ] Twilio Voice/SMS per alert critici
- [ ] SNMP v3, LDAP
- [ ] App Mobile React Native collegata al backend

## Test Reports
- iteration_37: Remote VA Scan (100%)
- iteration_38: VA PDF Report (100%)
- iteration_39: 7 nuove feature (100% - Backend 24/24, Frontend 7/7)
