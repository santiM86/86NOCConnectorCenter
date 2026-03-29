# NOC Alert Command Center - PRD

## Descrizione
Piattaforma NOC enterprise-grade per monitoraggio dispositivi di rete tramite SNMP, Syslog e Redfish. Connettore Windows nativo (PowerShell).

## Architettura
- Backend: FastAPI modulare (18 file route in `/app/backend/routes/`), MongoDB, AES-256-GCM
- Frontend: React, TailwindCSS, Shadcn UI, PWA, React Flow v12 (@xyflow/react)
- Connector: PowerShell 5.1+, SNMP, Redfish API, LLDP Discovery, **Windows Scheduled Task**

### Architettura Connector (v2.4.0 - NUOVA)
```
Windows Task Scheduler -> connector.ps1 (gira come SYSTEM, sopravvive a disconnessione RDP)
                          |-> scrive status.json ogni 60s
RDP Session (opzionale) -> tray_app.ps1 (legge status.json, controlla via Task Scheduler)
```

### Navigazione (4 gruppi)
```
MONITORAGGIO    -> Dashboard, Alert (badge), Stato Rete (mappa topologica + lista), Dispositivi
INFRASTRUTTURA  -> Clienti, Connettori (solo agent)
SICUREZZA       -> Vault Credenziali, Audit & Compliance, Gestione Utenti
SISTEMA         -> Impostazioni
```

## Funzionalita Implementate
- [x] Auth JWT + 2FA TOTP + Refresh tokens + Ruoli
- [x] SNMP/Ping/Redfish device monitoring
- [x] Alert management + correlazione + WebSocket live
- [x] Security Dashboard + IP blocking + audit logs
- [x] Credential Vault AES-256-GCM
- [x] Metriche PING avanzate (jitter, packet loss, TCP scan, HTTP check)
- [x] Power Control Redfish iLO + Wake-on-LAN
- [x] Menu 4 gruppi + Stato Rete / Connettori separati
- [x] Backend Refactoring: server.py da 3247 a 193 righe, 17 route modulari
- [x] **Mappa Topologica Enterprise con React Flow v12**
- [x] **LLDP Discovery (Link Layer Discovery Protocol)**
- [x] **FIX: Connettore sopravvive a disconnessione RDP (v2.4.0)**:
  - connector.ps1 ora gira come Windows Scheduled Task (utente SYSTEM)
  - Non dipende piu dalla sessione RDP interattiva
  - Status file condiviso (status.json) per comunicazione engine <-> tray app
  - Tray app diventa puro tool di monitoraggio/controllo (opzionale)
  - Installer aggiornato per registrare Scheduled Task
  - Uninstaller aggiornato per rimuovere Scheduled Task
  - Fallback a processo diretto se Task Scheduler non disponibile
  - Riavvio automatico su crash (3 tentativi, intervallo 1 minuto)

## Files Modificati (v2.4.0)
- `/app/noc-connector/src/connector.ps1`: Aggiunto Write-StatusFile/Remove-StatusFile
- `/app/noc-connector/src/tray_app.ps1`: Riscritto gestione processi via Scheduled Task + status file
- `/app/noc-connector/src/installer_gui.ps1`: Registra Scheduled Task invece di HKCU\Run
- `/app/noc-connector/uninstall.bat`: Rimuove Scheduled Task
- `/app/noc-connector/version.json`: v2.4.0

## Backlog
### P1
- [ ] Notifiche Push Firebase (MOCKED - richiede API Key utente)
- [ ] Notifiche Email SendGrid (MOCKED - richiede API Key utente)
### P2
- [ ] SOC AI: correlazione, auto-triage, anomaly detection via LLM
- [ ] Twilio Voice/SMS
- [ ] Auto-discovery rete, LDAP, SNMP v3

## Test Reports
- iteration_25: React Flow Enterprise Map + Layout Save/Reset (100%)
- iteration_26: LLDP Discovery Feature - Backend + Frontend (100%)
