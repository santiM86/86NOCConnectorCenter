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

### Phase 1 - MVP (DONE)
- [x] Auth JWT con registrazione/login + 2FA TOTP
- [x] Dashboard tempo reale con WebSocket
- [x] Gestione clienti CRUD con API key per ogni cliente
- [x] Gestione dispositivi CRUD
- [x] Alert con severita' (critical, high, medium, low)
- [x] Ingestione SNMP Traps + Syslog (con auth API Key)
- [x] Polling Redfish API (APScheduler)
- [x] Crittografia AES-256-GCM

### Phase 2 - Enterprise (DONE)
- [x] RBAC con 5 ruoli
- [x] SLA tracking + compliance + breach detection
- [x] Finestre di manutenzione
- [x] Correlazione alert e deduplicazione
- [x] Report automatici (PDF/CSV)
- [x] Audit logging

### Phase 3 - UI Redesign (DONE)
- [x] Dashboard intuitiva (banner urgenze, card severita', trend, live stream)
- [x] Pagina Enterprise (SLA, RBAC, Manutenzione, Report)
- [x] Design dark theme NOC professionale
- [x] Localizzazione italiana

### Phase 4 - 86NocConnector (DONE)
- [x] 100% PowerShell nativo
- [x] Wizard installazione GUI con pagina Dispositivi da Monitorare
- [x] Icona system tray
- [x] SNMP Trap listener + Syslog listener
- [x] Inoltro automatico al NOC Center via HTTPS + API Key
- [x] Heartbeat connector
- [x] Avvio automatico con Windows
- [x] Fix finestra nera + launcher VBS
- [x] Pacchetto ZIP scaricabile dal web

### Phase 5 - Mobile PWA + Connectors Page (DONE)
- [x] PWA manifest.json + service worker
- [x] Bottom navigation bar per mobile
- [x] Meta tags Apple per iOS
- [x] Pagina Connettori con stato real-time
- [x] Sezione Download con guida installazione 3 step

### Phase 6 - SNMP Polling + Auto-Update (DONE - 22 Mar 2026)
- [x] Client SNMP v2c nativo (raw UDP, BER encoding/decoding)
- [x] Polling attivo stato porte switch (ifOperStatus)
- [x] Rilevamento cambiamenti porte (up→down = critical, down→up = low)
- [x] Rilevamento dispositivo non raggiungibile
- [x] Pagina installer "Dispositivi da Monitorare" con aggiungi/rimuovi
- [x] Intervallo polling configurabile (default 60s)
- [x] Sistema auto-update centralizzato per 300+ connector
- [x] Backend: upload ZIP, check versione, download endpoint
- [x] Connector: check aggiornamenti ogni 6 ore, download, backup, aggiornamento, riavvio
- [x] Frontend: sezione "Aggiornamento Automatico" con upload, versione, changelog, contatore aggiornati
- [x] Alert con titoli leggibili (es. "Porta DOWN - HPE 1820 48G")

## Architettura
```
[Switch HPE 1820] ←SNMP polling→ [86NocConnector su Windows] →HTTPS→ [NOC Center Cloud]
                                  ↑ Auto-update ogni 6h ↑
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
- [ ] Integrazione AI per SOC (correlazione intelligente alert)
- [ ] Telefonate automatiche Twilio per alert critici
