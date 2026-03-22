# NOC Alert Command Center - PRD

## Problema Originale
Societa' IT necessita di un raccoglitore di alert per tutti i dispositivi nelle reti dei clienti: backup falliti, firewall, switch, server ILO. Console live in tempo reale su mobile e PC.

## Stack Tecnologico
- Backend: FastAPI + MongoDB + WebSockets + APScheduler
- Frontend: React + TailwindCSS + Shadcn UI + Recharts (PWA)
- Connector: PowerShell nativo (86NocConnector) con GUI wizard + system tray
- Mobile: PWA (Progressive Web App) con bottom navigation
- Sicurezza: Argon2id, AES-256-GCM, JWT, TOTP 2FA

## Funzionalita' Implementate

### Phase 1-3 (DONE)
- Auth JWT + 2FA TOTP, Dashboard tempo reale WebSocket, CRUD clienti/dispositivi/alert
- Enterprise: RBAC, SLA, manutenzione, correlazione, report PDF/CSV, audit
- UI: Dark theme NOC, localizzazione italiana, responsive

### Phase 4 - 86NocConnector (DONE)
- 100% PowerShell nativo, wizard GUI, system tray, SNMP/Syslog listener
- Auto-start Windows, disinstallazione pulita, fix finestra nera, launcher VBS

### Phase 5 - Mobile PWA + Connectors Page (DONE)
- PWA manifest + service worker, bottom nav mobile, Apple meta tags
- Pagina Connettori con download, guida installazione 3 step

### Phase 6 - SNMP Polling + Auto-Update (DONE)
- Client SNMP v2c nativo raw UDP + BER encoding
- Polling attivo porte switch, rilevamento cambiamenti, alert automatici
- Auto-update centralizzato: upload ZIP dal NOC, connector si aggiorna ogni 6h

### Phase 7 - Stato Dispositivi + Gestione Centralizzata (DONE - 22 Mar 2026)
- Report completo stato dispositivi dopo ogni ciclo di polling
- Mappa visuale 48 porte con colori (UP verde, DOWN rosso) nella dashboard NOC
- Badge stato OK/NON RAGGIUNGIBILE con ora ultimo check
- Info switch: sysDescr, uptime, contatori porte up/down
- Gestione centralizzata dispositivi dal NOC: aggiungi/rimuovi switch senza accesso al server
- Connector scarica lista dispositivi dal backend ogni 10 cicli di polling
- Aggiornamento automatico in tempo reale ogni 15 secondi

## Architettura
```
[Admin NOC] --gestione dispositivi--> [Backend] --fetch devices--> [Connector]
[Connector] --polling SNMP--> [Switch HPE] 
[Connector] --device report--> [Backend] --websocket--> [Dashboard NOC]
[Connector] --check update ogni 6h--> [Backend] --download ZIP--> [Auto-update]
```

## Test Credentials
- Admin: admin@test.it / TestAdmin123!

## Backlog P1
- [ ] Notifiche push Firebase (richiede API key)
- [ ] Notifiche email SendGrid (richiede API key)

## Backlog P2
- [ ] LDAP integration
- [ ] SNMP v3 nel connector
- [ ] Auto-discovery dispositivi rete
- [ ] Refactoring server.py in moduli
- [ ] AI per SOC (correlazione intelligente, auto-triage)
- [ ] Telefonate Twilio per alert critici
