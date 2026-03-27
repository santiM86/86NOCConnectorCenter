# NOC Alert Command Center - PRD

## Problema Originale
Creare un raccoglitore di alert (NOC) per dispositivi nelle reti dei clienti. Console live su PC e cellulare. Integrazione SNMP e Syslog. Sicurezza Enterprise. Connector Windows nativo (PowerShell).

## Architettura
- **Frontend**: React + TailwindCSS + Shadcn UI (porta 3000)
- **Backend**: FastAPI + MongoDB (porta 8001)
- **Connector Windows**: PowerShell 5.1+ nativo
- **Auth**: JWT + MFA (TOTP)

## Funzionalita' Implementate

### Core (DONE)
- Dashboard, alert SNMP/Syslog, gestione clienti, WebSocket, PWA

### Monitoraggio Dispositivi (DONE)
- SNMP polling (porte, sysDescr, uptime, trap)
- Ping+HTTP per dispositivi senza SNMP (switch smart managed)
- Auto-Discovery rete (ping sweep + port scan)
- Cambio tipo monitoraggio cliccando badge SNMP/PING

### Metriche Estese SNMP v1.8.0 (DONE - 27 mar 2026)
- **HPE 5130 (Comware)**: CPU, Memoria, Temperatura tramite OID H3C
- **HPE ILO (ProLiant)**: Salute generale, temperature sensori, ventole, alimentatori, dischi fisici
- **Generico**: CPU tramite HOST-RESOURCES-MIB (hrProcessorLoad)
- **Traffico interfacce**: Bandwidth IN/OUT (bps), velocita negoziata, errori IN/OUT per porta
- **Alert automatici**: CPU>90%, Memoria>90%, Temperatura>75C, disco guasto, ventola guasta, salute ILO degradata
- **Storico metriche**: Ultimi 24h salvati in MongoDB per trend
- **Frontend**: Gauge widgets (CPU/RAM/Temp), pannello hardware health (ventole/PSU/dischi/temperature), tabella traffico porte con bandwidth e errori, mini-chart trend 24h
- Device class auto-detection: `hpe-comware`, `hpe-ilo`, `generic`

### Web Console Proxy v1.7.3 (DONE)
- Accesso alla web interface dei dispositivi direttamente dal SOC
- Nessuna VPN necessaria: SOC -> Backend -> Connettore -> Dispositivo

### Gestione Utenti (DONE)
- CRUD con ruoli (admin/operator/viewer), MFA TOTP

### Connector v1.8.0 (DONE)
- SNMP Trap + Syslog, Polling SNMP esteso + Ping/HTTP
- Auto-Discovery, Web Console Proxy
- Heartbeat, auto-update, force update
- System tray con Mutex (fix doppie icone), diagnostica, import/export CSV
- Metriche estese HPE 5130 e ILO

### IP Auto-Ban System (DONE - 27 mar 2026)
- Auto-ban: IP con 10+ tentativi falliti in 30 min bloccato automaticamente (configurabile)
- Blocco/sblocco manuale IP dal pannello Security Audit
- IP Whitelist configurabile (IP che non vengono mai bloccati)
- Durata blocco configurabile (1h-permanente), default 6h
- Middleware che blocca ogni richiesta da IP bannati con cache in-memory (30s refresh)
- Storico blocchi IP con motivo, chi ha bloccato/sbloccato e quando
- Configurazione completa dal dialog: soglie, finestra temporale, durata, whitelist
- Pulsanti "Blocca" accanto a ogni IP sospetto nel pannello
- 15 endpoint testati al 100%

### Security Audit Dashboard (DONE - 27 mar 2026)
- Pannello in tempo reale nella pagina Enterprise con auto-refresh ogni 15s
- 7 stat card: Login Falliti, Login OK, Account Bloccati, Sessioni Attive, Token Revocati, Eventi Critici, Copertura 2FA
- Timeline attivita' 7 giorni con grafico a barre
- Lista IP sospetti con conteggio tentativi e email bersaglio
- Lista ultimi login falliti con email, IP e orario
- Lista eventi critici e warning
- Pannello account bloccati (visibile solo quando presenti)
- Accesso riservato solo a ruolo admin (403 per altri ruoli)
- **Security Headers**: X-Frame-Options DENY, CSP con frame-ancestors none, HSTS 1 anno, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy (camera/mic/geo/payment disabilitati)
- **CORS restrittivo**: Metodi e header specifici (non piu' wildcard *)
- **Refresh Token**: Login restituisce access token + refresh token. Rotazione automatica (vecchio revocato, nuovo emesso). Interceptor Axios per rinnovo trasparente
- **Logout sicuro**: Revoca server-side di tutti i refresh token
- **Account Lockout**: Blocco dopo 5 tentativi falliti (30 min). Sblocco automatico
- **Protezione NoSQL Injection**: Blocco operatori $ nei body delle richieste
- **Sanitizzazione input**: Validazione su endpoint di ingest (device-report)
- **WebSocket autenticato**: Token JWT via query parameter
- **Cache-Control**: no-store su endpoint sensibili (auth, admin)
- Rate limiting, Audit logging, RBAC, MFA TOTP (gia' esistenti)

## Credenziali Test
- Admin: admin@86bit.it / admin123
- API Key: noc_35cf39b4d68740b1a981aedef2ee293d

## Backlog

### P1
- Aggiornare connettore a v1.8.0 sul server del cliente
- Notifiche Push Firebase (serve API Key utente)
- Notifiche Email SendGrid (serve API Key utente)

### P2
- SOC AI (correlazione, auto-triage, anomaly detection)
- Twilio Voice/SMS per alert critici
- LDAP integration
- SNMP v3

### P3
- Refactoring server.py (>2100 righe) in moduli route separati
