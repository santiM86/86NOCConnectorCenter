# CHANGELOG — 86BIT ARGUS Center

## 2026-04-22 — RMT Phase 1 (Remote Browser scaffolding) + Connector v3.3.7
- **Backend** `/app/backend/routes/console_rmt.py`:
  - `POST /api/console-rmt/session` crea JWT session, verifica versione connector (required: v3.4.0+), ritorna `{token, ws_url, connector_supported, connector_offline}`.
  - `WS /api/console-rmt/ws/{token}` endpoint operator (browser del Center).
  - `WS /api/console-rmt/connector-ws/{token}` endpoint connector (lato server cliente).
  - Relay JSON bidirezionale via in-memory registry `_CLIENT_WS/_CONNECTOR_WS`.
  - Dispatch `pending_commands.type=remote_browser_start` al connector via polling.
  - Audit in `rmt_sessions` collection.
- **Frontend** `/app/frontend/src/components/RemoteBrowserModal.js`:
  - Modal full-screen fuchsia/magenta con canvas HTML5.
  - Stati: connecting → ready → streaming; upgrade/error/closed.
  - Mouse events (move/down/up/wheel) + keyboard con modifiers → WebSocket.
  - Schermata "Upgrade Required" con link a /connectors.
  - Pulsante **RMT** (fuchsia) in `WebConsoleTabs.js` accanto a PRB/DBG/V4.
  - `data-testid="web-console-rmt"`, `data-testid="rmt-canvas"`, `data-testid="rmt-modal"`.
- **SW cache** bumped v7→v8.
- **Connector v3.3.7** (published, SHA `9cf91b5e...070a2bcf`, 296 KB):
  - `Register-ServiceWatchdog` — scheduled task Windows ogni 5 min che riavvia il servizio se Stopped. Self-heal da update bloccati.
  - Fix regex HTML5 unquoted per inline CSS/JS/IMG (fix Web Console iLO pagina bianca).
  - `Install-Update` con Start-Process come primary + WMI/schtasks/cmd fallback, ciascuno con verifica PID-alive dopo 3s + flag `updater_started.flag` check entro 8s.
  - schtasks $runTime con +60s invece di +45s (fix "orario nel passato").
  - Nuovo progress 47% "spawning" per distinguere extract da launch updater.
- **Device Probe** `/api/diag/web-console-probe` — scansiona 12 path comuni via connector + pulsante **PRB** (cyan) nella toolbar.

## 🔜 Fase 2 (v3.4.0 connector) — TODO
- `/app/noc-connector/prg/src/remote_browser.ps1` — client CDP PowerShell (WebSocket + JSON dispatch).
- Lancio `msedge.exe --headless=new --remote-debugging-port=<random>` con `--ignore-certificate-errors`, `--disable-gpu`, `--disable-web-security`, `--user-data-dir=<temp>`.
- `Page.navigate` al device URL, `Page.startScreencast` (JPEG quality=70, maxWidth=1600, everyNthFrame=1).
- Handler `Page.screencastFrame` → base64 JPEG → WS relay.
- Handler messages dal Center: `Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`, `Input.insertText`.
- Auto-cleanup Edge process + user-data-dir dopo sessione.
- Version bump version.json → 3.4.0.

## 2026-04-21 Sessione precedente (Vendor Alerts Phase A + Device Profiles + Runbook Auto-Match + Web Console V4 + Port Whitelist Dynamic)
(Vedi sezione originale PRD per dettagli. Include: Fase A vendor alerts backend (vendor_oids send + vendor_metrics receive), 13 device profiles, runbook auto-match, V4 popup proxy.)
