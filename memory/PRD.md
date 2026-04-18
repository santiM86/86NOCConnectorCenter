# ARGUS Center — NOC Platform (86bit)

## Original problem statement
Società IT che necessita di un raccoglitore di alert (NOC) per tutti i dispositivi nelle reti dei clienti (switch, firewall, ecc.). Console live su PC e cellulare. Integrazione SNMP e Syslog. L'applicazione Windows (`86NocConnector`) deve essere nativa senza richiedere Python. Funzionalità stile Zabbix/PRTG/CloudFire. Dashboard TV, monitoraggio stampanti/backup, SOC AI, vulnerability assessment, WAN monitoring, multi-tenant SaaS.

## Stack
- Frontend: React + Tailwind + Shadcn/UI (Phosphor icons)
- Backend: FastAPI + Motor (MongoDB) + Pydantic
- Connector: PowerShell 5.1+ nativo con HMAC-SHA256, Nonce Anti-Replay, AES-256-GCM
- AI: `google-generativeai==0.8.6` (no emergentintegrations)

## Key architecture
```
/app/backend/routes/
  connector.py     → endpoints HMAC-secured + managed-devices CRUD per client
  devices.py       → device CRUD + Redfish test
  redfish_routes.py→ direct iLO polling/failover
  vault.py         → AES-256-GCM credential vault (admin only)
  overview.py      → Control Room aggregation
/app/frontend/src/pages/
  ClientOverviewPage.js → vista unificata per singolo cliente (tabs)
  VaultPage.js          → vault globale
/app/noc-connector/src/
  connector.ps1    → main loop, HMAC auth, Redfish integration
  snmp_poller.ps1  → SNMP v1/v2c/v3 + Redfish REST
```

## Completed (session log)
- 2026-01-15: Login redesign + responsiveness
- 2026-01-18: Client-centric navigation & Unified Client Overview Page
- 2026-01-22: Auto-Update Polling System with Cache Busting
- 2026-01-28: Extended WAN Monitor (Gateway ISP Ping, ICMP toggle, Schematic UI)
- 2026-02-05: SOC AI migrated to direct google-generativeai SDK
- 2026-02-10: IP Ban / Honeypot / Rate Limit middlewares rimossi per richiesta utente
- 2026-02-15: Connector v3.0.0 — HMAC-SHA256, Nonce Anti-Replay, Obfuscated paths
- 2026-02-20: Installer GUI + uninstall.bat + version.json auto-read
- 2026-02-25: Device merging (managed_devices + device_poll_status)
- 2026-03-01: Web Proxy Console Enterprise UI
- 2026-04-18: **Add Device from Client Page** — pulsante "+ Aggiungi Dispositivo" e eliminazione dispositivo dentro la tab Dispositivi del ClientOverviewPage. Supporto completo SNMP v1/v2c/v3 (auth/priv), Ping, HTTP. POST su `/api/connector/{client_id}/managed-devices`. Cestino rimozione chiama `DELETE /api/connector/{client_id}/managed-devices/{id}` o `DELETE /api/connector/device-poll-status/{ip}` per connector-discovered.

## Pending / In Progress
### P0 — Redfish polling non funzionante
L'utente ha inserito credenziali iLO nel Vault per `10.100.61.35` ma il connector non sta facendo polling Redfish. Sospetti principali:
1. **Gating SNMP**: in `connector.ps1` il Redfish parte solo se `device_class == "hpe-ilo"` via SNMP. Se l'iLO non ha SNMP abilitato, il polling Redfish non viene mai attivato.
2. **Versione connector**: utente potrebbe avere versione pre-v3.0.0 in produzione.
3. **Device censito?**: l'iLO deve essere presente in `managed_devices` o discovered via polling.

Next step: modificare il connector per forzare il polling Redfish quando esistono credenziali Vault di tipo `ilo`/`redfish` per quell'IP, indipendentemente dalla classificazione SNMP.

### P1 — Vault per cliente
Utente ha richiesto di spostare tutta la pagina "Vault Credenziali" (incluso Stato Polling iLO Diretto/Failover) dentro la pagina del singolo cliente come nuova tab. Domande aperte: mantenere vista globale per super-admin? Migrazione credenziali esistenti?

### P1 — Notifiche Telegram
In attesa di bot token dall'utente.

### P1 — Sostituire mock Push/Email con integrazioni reali

## Backlog / Future
- P2: Multi-tenant + White-label SaaS (workspace isolation)
- P2: LDAP/Active Directory integration
- P3: Zyxel Nebula Cloud API

## Constraints
- NON re-introdurre IP Ban/Honeypot middlewares (richiesta esplicita utente)
- NON usare `emergentintegrations` per AI
- Linguaggio: rispondere SEMPRE in Italiano
- Utente fa deploy in produzione via "Save to GitHub" + "Re-deploy"

## Key credentials (test)
- Admin: `admin@86bit.it` / `password`
- Admin: `info@86bit.it` / `password`
- TV Viewer: `tv@86bit.it` / `Tv86bit!2026`

## Key DB collections
- `managed_devices` — device manuali per cliente (con `community`, `snmp_version`, `snmpv3_*`)
- `device_poll_status` — device scoperti via heartbeat connector
- `device_credentials` — Vault AES-256-GCM (iLO/SSH/SNMP/Web/VPN)
- `wan_probe_results` — Ping/TCP WAN
- `clients`, `devices`, `alerts`, `users`, `audit_logs`
