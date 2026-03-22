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

### Phase 4 - 86NocConnector (DONE - 22 Mar 2026)
- [x] 100% PowerShell nativo - ZERO installazioni sul server del cliente
- [x] Wizard installazione GUI (Windows Forms nativo)
- [x] Icona system tray vicino all'orologio con menu tasto destro
- [x] SNMP Trap listener (porta 162) + Syslog listener (porta 514)
- [x] Inoltro automatico al NOC Center via HTTPS + API Key
- [x] Heartbeat connector visibile nella dashboard NOC
- [x] Avvio automatico con Windows
- [x] Disinstallazione pulita (uninstall.bat)
- [x] Fix finestra nera console (install.bat usa -WindowStyle Hidden + exit)
- [x] Launcher VBS per installazione senza flash di console
- [x] Pacchetto ZIP scaricabile dal web

### Phase 5 - Mobile PWA + Connectors Page (DONE - 22 Mar 2026)
- [x] PWA manifest.json + service worker per installazione su home screen
- [x] Bottom navigation bar per mobile (Home, Alert, Clienti, Dispositivi, Altro)
- [x] Meta tags Apple per iOS (standalone, status bar, touch icon)
- [x] Touch-friendly targets (min 44px) e safe area support
- [x] Pagina "Connettori" con stato real-time dei 86NocConnector installati
- [x] Card sommario (Totale, Online, Offline) + dettagli per connector
- [x] Refresh automatico ogni 15 secondi
- [x] Sezione Download Connector con guida installazione in 3 step
- [x] Download ZIP diretto dalla pagina Connettori

## Installazione Mobile
### Android (Chrome): Menu > "Installa app" o "Aggiungi alla schermata Home"
### iOS (Safari): Condividi > "Aggiungi alla schermata Home"

## Architettura Connessione
```
[HPE 5130 / Firewall / ILO] --SNMP/Syslog--> [86NocConnector su Windows] --HTTPS--> [NOC Center Cloud]
```

## Test Credentials
- Admin: admin@test.it / TestAdmin123! (role: admin)

## Files Chiave
- `/app/noc-connector/` - Pacchetto 86NocConnector completo
- `/app/backend/server.py` - Backend principale
- `/app/frontend/src/pages/` - Pagine frontend
- `/app/frontend/src/components/Layout.js` - Layout con mobile nav
- `/app/frontend/public/manifest.json` - PWA manifest
- `/app/frontend/public/sw.js` - Service Worker

## Backlog P1
- [ ] Notifiche push Firebase (richiede API key utente)
- [ ] Notifiche email SendGrid (richiede API key utente)

## Backlog P2
- [ ] LDAP integration
- [ ] SNMP v3 nel connector
- [ ] Auto-discovery dispositivi rete
- [ ] Refactoring server.py in moduli
