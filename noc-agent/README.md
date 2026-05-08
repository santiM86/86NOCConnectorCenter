# 86NocAgent v4.0 — Native NOC Agent

Single-binary, cross-platform NOC monitoring agent for the 86bit platform. Replaces the legacy PowerShell-based `86NocConnector` (v3.8.x).

## Why we built this

The legacy connector ran as a chain of PowerShell scripts inside a Windows Service. In production we hit recurring failure modes that no patch could really solve:

- sub-runspaces stuck on UDP socket leaks (the `lan-scan` "frozen at 12:00" bug)
- no real-time channel: the backend could only **wait** for the next polling cycle
- no way to push commands (force-scan, restart-module, run-diagnostics) without RDPing in
- no self-update — every fix required a manual installer push
- PowerShell GC + runspace state made crash diagnosis a coin flip

`86NocAgent` is a clean rewrite in **Go**, the same language Datadog, Grafana Agent, Prometheus and Telegraf use. It produces a single static binary, ~10 MB, with no runtime dependencies.

## What's in v4.0 (MVP)

- Single static binary, builds for `linux/amd64`, `linux/arm64`, `windows/amd64`, `darwin/arm64`.
- Persistent **WebSocket** connection to the backend with bearer-token auth, exponential backoff and jitter.
- **Bidirectional protocol** (see `pkg/proto`):
  - agent → server: `hello`, `heartbeat`, `event`, `reply`, `log`
  - server → agent: `welcome`, `command`, `config`, `ping`
- **Discovery** modules running in parallel goroutines:
  - ARP table reader (`/proc/net/arp` on Linux, `arp -an` elsewhere)
  - mDNS / DNS-SD browser covering 10 high-signal service types
- **SNMP poller** with per-target community override, parallel fan-out (16 concurrent), 60s default cycle.
- **Self-telemetry** in every heartbeat: uptime, goroutines, mem, CPU, error rate, **per-module liveness**, last-scan timestamps. The backend now sees a stuck module within seconds.
- **Server-initiated commands** (already wired):
  - `ping` — RTT measurement
  - `force_lan_scan` — runs a discovery sweep on demand
  - `force_snmp_poll` — polls one target or the entire pool
  - `get_metrics` — returns a heartbeat snapshot
  - `run_diagnostics` — collects environment + config introspection
  - `shutdown` — graceful exit (watchdog respawns)
- Companion **`nocwatchdog`** binary in a separate process: monitors the agent's heartbeat file (touched every 15 s) and SIGTERM/SIGKILL+restarts the agent if it stalls beyond `stale_after` (default 90 s). This is the architectural fix for the legacy "frozen poller" bug — a deadlock in the agent address space cannot block the watchdog.
- **Self-update** plumbing (Ed25519-signed manifest) wired but disabled until the backend publishes the manifest endpoint.

## Build

```bash
cd /app/noc-agent
make tidy
make build                   # host-native binaries -> build/bin/
make all-platforms           # all 4 cross-builds -> build/bin/<os>-<arch>/
```

## Run (development)

```bash
export NOCAGENT_BACKEND_URL=ws://localhost:8001/api/agent/ws
export NOCAGENT_CLIENT_ID=86bit-office
export NOCAGENT_TOKEN=dev-token
./build/bin/nocagent --config build/agent.example.yaml
```

## Deployment

| Platform | Service unit |
|---|---|
| Linux | `service/systemd/86nocagent.service` (uses `Restart=always` as a baseline; the dedicated `nocwatchdog` process is the second line of defence) |
| Windows | Windows Service via `sc.exe create 86NocAgent ...` (companion `86NocWatchdog` service) |
| macOS | launchd plist (TODO Sprint 2) |

## Wire protocol (summary)

Every message is a single JSON object:

```json
{
  "v": 1,
  "type": "agent.heartbeat",
  "seq": 42,
  "corr_id": "",
  "sent_at": "2026-02-09T12:34:56.789Z",
  "payload": { ... }
}
```

See `pkg/proto/messages.go` for the exhaustive type list.

## Backend integration

Sprint 1 ships a new endpoint on the FastAPI backend: `WS /api/agent/ws` (see `/app/backend/routes/agent_ws.py`). It validates the bearer token, records the agent in the `managed_agents` collection and bridges incoming `discovery_batch` / `snmp_poll` events into the existing `discovered_endpoints` and `device_poll_status` collections — so all UI pages keep working unchanged.

The legacy v3.8.x connector continues to run in parallel; admins migrate clients one at a time.
