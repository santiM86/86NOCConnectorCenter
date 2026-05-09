# 86NocAgent — Quickstart deploy (produzione)

Per portare un cliente in produzione bastano **3 step**.

## 1. (Admin) Generare il token per il cliente

Login come admin sul backend, poi:

```bash
curl -X POST https://argus.86bit.it/api/agents/register \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"acme-spa","label":"sede-milano"}'
```

Risposta:
```json
{
  "client_id": "acme-spa",
  "token": "k7gh-...........",
  "backend_url": "wss://argus.86bit.it/api/agent/ws",
  "issued_at": "2026-..."
}
```

> Il token è il bearer dell'agent: tutto quello che serve. Non si scade automaticamente; per revocarlo basta `db.agent_tokens.update_one({...}, {"$set": {"revoked": true}})` (Sprint 2 introdurrà l'endpoint REST `/api/agents/revoke`).

## 2. (Tecnico on-site) Eseguire l'installer

### Windows (server o PC del cliente)

PowerShell come **Administrator**, una sola riga:

```powershell
iwr -UseBasicParsing "https://argus.86bit.it/api/agent/install/windows.ps1?token=<TOKEN>" | iex
```

Cosa fa:
1. Chiama `GET /api/agent/install/manifest` per ricavare `client_id`, URL backend, template config.
2. Stoppa eventuali servizi `86NocAgent` / `86NocWatchdog` esistenti (idempotente).
3. Scarica `nocagent.exe` + `nocwatchdog.exe` da `/api/agent/binary/windows-amd64/...`.
4. Scrive `C:\ProgramData\86NocAgent\agent.yaml` con token + client_id + URL.
5. Registra entrambi come Windows Service con **Service Recovery** (`restart/5s/restart/5s/restart/15s`).
6. Avvia tutto.

### Linux (server o appliance del cliente)

```bash
curl -fsSL "https://argus.86bit.it/api/agent/install/linux.sh?token=<TOKEN>" | sudo bash
```

Cosa fa:
1. Auto-detect arch (amd64/arm64).
2. Scarica binari in `/usr/local/bin/`.
3. Scrive `/etc/86nocagent/agent.yaml`.
4. Crea unit systemd `86nocagent.service` + `86nocwatchdog.service` con `Restart=always`.
5. `systemctl enable` + start.

## 3. (Admin) Verificare che l'agent sia online

```bash
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  https://argus.86bit.it/api/agents
```

Risposta:
```json
{
  "agents": [
    {
      "agent_id": "...",
      "client_id": "acme-spa",
      "hostname": "DC01",
      "os": "windows",
      "agent_version": "4.0.0+...",
      "live": true,
      "last_heartbeat_at": "2026-...",
      "modules_alive": ["transport","discovery","poller","watchdog"],
      "modules_stuck": []
    }
  ],
  "live_count": 1
}
```

Comandi real-time (la killer feature vs il legacy):

```bash
# Forza una scansione LAN ora — niente più "aspetta il polling"
curl -X POST -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"name":"force_lan_scan"}' \
  https://argus.86bit.it/api/agents/<AGENT_ID>/command

# Snapshot live di metriche e moduli
curl -X POST -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"name":"get_metrics"}' \
  https://argus.86bit.it/api/agents/<AGENT_ID>/command

# Diagnostica completa
curl -X POST -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"name":"run_diagnostics"}' \
  https://argus.86bit.it/api/agents/<AGENT_ID>/command
```

## Convivenza col legacy v3.8.x

Il connector PowerShell continua a funzionare in parallelo. La migrazione va fatta cliente per cliente:

1. Installa l'agent v4 sulla macchina.
2. Verifica che gli endpoint scoperti siano coerenti (`source_connector_mode: "agent_v4"` nelle collection `discovered_endpoints`).
3. Dopo 24h di parallelismo, ferma i servizi del connector legacy.

L'UI esistente continua a funzionare senza modifiche perché l'agent v4 popola le **stesse collection** del legacy.

## Troubleshooting

| Sintomo | Diagnosi |
|---|---|
| `live: false` su `/api/agents` | Service non parte. `Get-Service 86NocAgent` (Windows) / `systemctl status 86nocagent` (Linux). Controlla `agent.yaml` e backend URL raggiungibile. |
| `modules_stuck` non vuoto | Un worker ha smesso di tickare. Il watchdog uccide+respawn entro 90s. Logs in Event Viewer (Win) o `journalctl -u 86nocagent` (Linux). |
| Heartbeat fermi a Nh | Watchdog non parte / processo zombie. `systemctl restart 86nocwatchdog` o equivalente Win. |
| Token rifiutato (close 1008) | Token revocato o `client_id` non corrisponde. Rigenera con `/api/agents/register`. |
