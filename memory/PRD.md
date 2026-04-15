# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade "ARGUS Center" per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell) con servizio NSSM.

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

### Monitor WAN con Gateway ISP (AGGIORNATO - 15/04/2026)
- [x] Probe Ping ICMP + TCP Port Check verso IP pubblici
- [x] Campo Gateway ISP opzionale per diagnosi avanzata linea
- [x] Diagnosi 3 livelli: Gateway ISP → Router → Firewall
- [x] Test Connection pre-salvataggio (TCP + Gateway Ping)
- [x] Risultato test dettagliato: porte OPEN/CLOSED, Gateway ONLINE/OFFLINE
- [x] Diagnosi automatica: ISP down vs Router down vs Firewall down
- [x] Alert automatici su status change

### Sistema Auto-Update (NUOVO - 15/04/2026)
- [x] Endpoint GET /api/app-version con hash SHA256 codice
- [x] Frontend polling ogni 60s, banner aggiornamento
- [x] Auto-reload frontend stale, cache-busting completo
- [x] VersionBadge V.2.0.XXXX nell'header sidebar

### Navigazione Sidebar (AGGIORNATO - 15/04/2026)
- [x] 6 sezioni: Panoramica, Monitoraggio, Clienti & Rete, Operazioni, Sicurezza, Amministrazione

### Gestione Utenti
- [x] CRUD + Toggle attivo/disattivato + Sblocca brute force
- [x] 4 utenti registrati, stats Totale/Attivi/MFA/Admin

### Login Page Branding
- [x] Icona ARGUS scudo, Footer Verdana, layout 100vh responsive
- [x] Banner notifiche nascosto su login/2fa, footer mobile compatto

### Tutto il resto (COMPLETATO)
- [x] Mappa Enterprise, Dashboard, Report PDF, TV Dashboard
- [x] Stampanti SNMP, VA, Trend, Discovery, Soglie, Manutenzione
- [x] Bandwidth, SOC AI Gemini, Portale Cliente, Backup
- [x] Security 21 protezioni, SNMP v3, Connector Hardening
- [x] Scalabilita (65 indici, 12 TTL, GZip, Task Coordinator)
- [x] Mobile Dashboard, PWA

## Key API Endpoints
- GET `/api/app-version` - Versione e hash codice
- POST `/api/external-monitor/test-connection` - Test TCP + Gateway pre-salvataggio
- POST `/api/external-monitor/targets` - Crea target WAN (con gateway_ip)
- GET `/api/external-monitor/status` - Stato con diagnosi gateway

## Backlog
### P1
- [ ] Template SNMP specifici Zyxel (VPN, sessioni, temperatura)
- [ ] Notifiche Telegram (quando utente fornira bot token)
- [ ] Notifiche Push Firebase / Email SendGrid (sostituzione mock)
### P2
- [ ] Multi-tenant e White-labeling (SaaS)
- [ ] LDAP/Active Directory
### P3
- [ ] Zyxel Nebula Cloud API
- [ ] App Mobile React Native

## Credenziali Test
- Admin: admin@86bit.it / password
- Admin: info@86bit.it / password (Marco Santinelli)
- TV Monitor: tv@86bit.it / Tv86bit!2026
- TV Dashboard Test: tvdash@86bit.it / Tv86bit!2026
