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

### Enterprise Features
- [x] Pannello Dettagli: Click su nodo -> info, alert, porte 10G, endpoint, LLDP, MAC
- [x] Aggiornamento Real-time: Auto-refresh 30s + timestamp + pulsante manuale
- [x] Ricerca + Filtri Tipo/Stato + Export PNG
- [x] Alert Badge/Correlazione Impatto

### Dashboard Metriche Zabbix-style
- [x] SLA Gauge, Change Timeline, Uptime Heatmap, Latency Chart

### Report PDF (PRTG-style)
- [x] Generazione report PDF professionale per cliente

### Inventario Dispositivi + Incidenti + Monitor Servizi TCP + Dashboard Pubblica + Notifiche
- [x] Tutti implementati e funzionanti

### TV Dashboard NOC
- [x] Pagina fullscreen /tv, layout 3 colonne, allarmi sonori, auto-refresh 15s

### Gestione Stampanti SNMP
- [x] Dashboard stampanti, barre toner, avvisi automatici, polling connettore

### Vulnerability Assessment (COMPLETATO - 30/03/2026)
- [x] Dashboard VA con Security Score (0-100)
- [x] Knowledge base 18+ porte pericolose
- [x] Barra distribuzione severita, 3 tab (Dispositivi/Vulnerabilita/Remediation)
- [x] **Scansione Remota**: Pulsante "Avvia Scansione Remota" che invia il comando al connettore via heartbeat pending_commands
- [x] **Progresso real-time**: Barra progresso animata con polling dello stato ogni 3s
- [x] **Backend endpoints**: request-scan, scan-status, update-scan-status, process-scan-results
- [x] **PowerShell Run-VAScan**: Scansione porte pericolose TCP + check SNMP community di default
- [x] **Sicurezza**: pending_commands filtrati per client_id (fix cross-client leakage)
- [x] Storico scansioni con trend temporale
- [x] **Report PDF Esaustivo (11 pagine)**: Riepilogo esecutivo, distribuzione severita, analisi per dispositivo, vulnerabilita critiche/alte, elenco completo, analisi dettagliata con remediation, piano azioni, storico, raccomandazioni, metodologia, knowledge base porte

### Connettore Windows (v2.5.0+)
- [x] Servizio NSSM
- [x] Network Discovery (LLDP + MAC + Speed)
- [x] Auto-aggiornamento robusto
- [x] Polling stampanti SNMP
- [x] Esecuzione remota VA Scan via pending_commands

## Key API Endpoints
- GET `/api/vulnerability/dashboard/{client_id}` - Dashboard VA
- GET `/api/vulnerability/device/{client_id}/{device_ip}` - Dettaglio VA dispositivo
- POST `/api/vulnerability/request-scan/{client_id}` - Richiedi scansione remota
- GET `/api/vulnerability/scan-status/{client_id}` - Stato scansione
- POST `/api/vulnerability/update-scan-status` - Aggiorna progresso (da connettore)
- POST `/api/vulnerability/process-scan-results` - Ricevi risultati (da connettore)
- POST `/api/vulnerability/run-scan/{client_id}` - Scansione locale
- GET `/api/vulnerability/history/{client_id}` - Storico
- GET `/api/vulnerability/report/{client_id}` - Report PDF esaustivo (11 sezioni)
- POST `/api/connector/managed-devices` - Lista dispositivi (per connettore)
- POST `/api/connector/heartbeat` - Heartbeat con pending_commands filtrati per client_id

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED, serve API key)
- [ ] Notifiche Email SendGrid (MOCKED, serve API key)
### P2
- [ ] Trend grafico score VA nel tempo
- [ ] SOC AI: correlazione intelligente, auto-triage tramite LLM
- [ ] Twilio Voice/SMS
- [ ] SNMP v3, LDAP, Auto-discovery
- [ ] Reportistica Predittiva, Traffic monitoring

## Test Reports
- iteration_36: Vulnerability Assessment base (100%)
- iteration_37: Remote VA Scan (100% - Backend 17/17, Frontend 100%)
- iteration_38: VA PDF Report (100% - Backend 11/11, Frontend 100%)
