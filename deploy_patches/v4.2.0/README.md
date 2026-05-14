# Deploy patch v4.2.0 — Live Polling dall'Agent Go

Questa patch aggiunge il **live polling ICMP + SNMP** nativo dell'Agent Go,
sostituendo definitivamente il polling del vecchio Connector PowerShell per
i device approvati via Auto-Discovery.

## Cosa cambia

### Backend (FastAPI, su VM Linux 10.30.0.201)
- **`routes/agent_ws.py`**
  - `_build_poller_config()` ora emette **due blocchi**: `snmp` (come prima)
    e `ping` (NUOVO, contiene TUTTI i device abilitati del tenant).
  - Nuovo handler `_bridge_ping_poll()` con **threshold 3 fallimenti
    consecutivi** prima di marcare un device come `offline`. Reset
    automatico al primo successo. Campo `consecutive_ping_failures` in
    `managed_devices`.
  - Nuova funzione **`push_config_to_client(client_id)`** che hot-pusha la
    config aggiornata a tutti gli agent del tenant (re-usa il frame
    `server.welcome` → l'agent fa hot-swap senza restart).
- **`routes/advanced_features.py`**
  - L'endpoint `/api/discovery/approve` ora chiama `push_config_to_client()`
    subito dopo l'insert → l'Agent Go inizia a pollare il nuovo device
    entro pochi secondi (vs aspettare il riavvio del servizio Windows).

### Agent Go (su SOCIALSRV — Windows)
- **`internal/poller/icmp.go`** (NUOVO): ping nativo via `ping.exe` Windows
  (zero raw socket, zero dipendenze esterne). Concorrenza limitata a 32
  probe simultanei. Parser RTT/loss multilingua (EN/IT Windows + Linux).
- **`pkg/proto/messages.go`**: aggiunto `EventPingPoll` + `PingPollResult`.
- **`internal/config/config.go`**: aggiunto `PingConfig` (Enabled, Interval,
  Timeout, Count, Targets).
- **`cmd/agent/main.go`**: istanzia e avvia il `PingPoller` in goroutine,
  registra il comando `force_ping_poll`, parsa il blocco `ping` nel
  `server.welcome`.
- **Versione binario**: `4.2.0+<commit>`

---

## Procedura di deploy in produzione

### A. Backend (VM Linux Ubuntu, IP 10.30.0.201)

> ⚠️ **NON** usare `sync-argus.sh` — distrugge il `venv`. Solo `scp` dei
> 2 file modificati. Non toccare `requirements.txt`.

Da locale (o da dovunque hai questi file):

```bash
# Upload mirato
scp /app/deploy_patches/v4.2.0/agent_ws.py          arslan@10.30.0.201:/tmp/
scp /app/deploy_patches/v4.2.0/advanced_features.py arslan@10.30.0.201:/tmp/
```

Sulla VM 10.30.0.201:

```bash
# Backup defensivo
sudo cp /opt/argus/backend/routes/agent_ws.py          /opt/argus/backend/routes/agent_ws.py.bak-v4.1.4
sudo cp /opt/argus/backend/routes/advanced_features.py /opt/argus/backend/routes/advanced_features.py.bak-v4.1.4

# Apply
sudo install -o arslan -g arslan -m 644 /tmp/agent_ws.py          /opt/argus/backend/routes/agent_ws.py
sudo install -o arslan -g arslan -m 644 /tmp/advanced_features.py /opt/argus/backend/routes/advanced_features.py

# Riavvia uvicorn (porta 8186) — systemd
sudo systemctl restart argus-backend

# Verifica
sudo journalctl -u argus-backend -n 30 --no-pager
curl -fsS http://localhost:8186/api/health || curl -fsS http://localhost:8186/api/agents
```

Risultato atteso nei log: `Application startup complete.` e nessun
`ImportError`/`SyntaxError`.

### B. Agent Go (SOCIALSRV, Windows)

Da locale:

```powershell
# Carica il nuovo binario sul server (es. via SMB, RDP, o /api/agent/binary endpoint)
# Path tipico: C:\Program Files\86NocAgent\nocagent.exe
```

Sul server Windows, in **PowerShell come Administrator**:

```powershell
# Stop service
Stop-Service 86NocAgent -Force

# Backup
Copy-Item "C:\Program Files\86NocAgent\nocagent.exe" "C:\Program Files\86NocAgent\nocagent.exe.bak-v4.1.4"

# Replace (path file appena scaricato)
Copy-Item -Force "C:\Users\Administrator\Downloads\nocagent.exe" "C:\Program Files\86NocAgent\nocagent.exe"

# Verify version + restart
& "C:\Program Files\86NocAgent\nocagent.exe" --version
Start-Service 86NocAgent

# Log
Get-Content "C:\ProgramData\86NocAgent\nocagent.log" -Tail 50 -Wait
```

Atteso: la riga `agent started ... agent_version=4.2.0+...` + dopo qualche
secondo `ping config hot-swapped enabled=true targets=N`.

### C. Verifica end-to-end (dashboard argus.86bit.it)

1. Approva un device dalla pagina Auto-Discovery (es. una stampante o un
   pc).
2. Aspetta ~60 secondi.
3. Il device deve passare da `PENDING` → `ONLINE` con RTT (es. `2ms`).
4. Stacca un cavo / spegni quel device: dopo 3 cicli (~3 min) → `OFFLINE`.
5. Riattacca: torna `ONLINE` al primo ciclo successivo.

### D. Rollback rapido

```bash
# Backend
sudo cp /opt/argus/backend/routes/agent_ws.py.bak-v4.1.4          /opt/argus/backend/routes/agent_ws.py
sudo cp /opt/argus/backend/routes/advanced_features.py.bak-v4.1.4 /opt/argus/backend/routes/advanced_features.py
sudo systemctl restart argus-backend

# Agent (Windows)
Stop-Service 86NocAgent -Force
Copy-Item -Force "C:\Program Files\86NocAgent\nocagent.exe.bak-v4.1.4" "C:\Program Files\86NocAgent\nocagent.exe"
Start-Service 86NocAgent
```

---

## Test eseguiti

- ✅ `go build ./...` — clean (cross-compile windows-amd64, linux-amd64,
  linux-arm64)
- ✅ `go test ./internal/poller/...` — 3 test (parser ping output IT/EN/Linux)
- ✅ `pytest backend/tests/test_agent_v4_live_polling.py` — 3 scenari:
  1. `_build_poller_config` emette `snmp` + `ping` con i device giusti
  2. Threshold 3 fallimenti consecutivi rispettato + reset on recovery
  3. `push_config_to_client` no-op safe con 0 agent connessi
- ✅ `pytest backend/tests/test_advanced_features.py` — 24/24 (nessuna
  regressione su `/api/discovery/approve`)

## Note

- Il `nocagent.exe` deve essere eseguito con privilegi sufficienti per
  fare `ping.exe`. Windows Service = `LocalSystem` = OK out of the box.
- Su Linux, `ping` come non-root richiede `CAP_NET_RAW`. Se gira da
  systemd con `User=root` o `AmbientCapabilities=CAP_NET_RAW` funziona.
- `consecutive_ping_failures` è un nuovo campo in `managed_devices`,
  inizializzato a 0 alla prima risposta.
- I dispositivi `disabled: true` o `enabled: false` sono **esclusi sia
  da snmp che da ping** — backwards-compatible con il filtro esistente.
