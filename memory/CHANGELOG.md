# CHANGELOG — 86BIT ARGUS Center

## 2026-04-22 — RMT Phase 2 (Remote Browser v3.4.0 LIVE)
- **Connector v3.4.0** published (SHA `0a422583...5e5509`, 303 KB):
  - **Nuovo modulo** `/app/noc-connector/prg/src/remote_browser.ps1` (~400 righe):
    - Auto-discover Edge (ProgramFiles, LocalAppData) / Chrome fallback
    - Lancio headless con `--headless=new --remote-debugging-port=<random>`, `--ignore-certificate-errors`, `--disable-web-security`, `--user-data-dir=<temp_per_sessione>`, `--window-size=1600,900`
    - Discovery CDP via `http://127.0.0.1:<port>/json/version` + `PUT /json/new?<deviceUrl>`
    - **Dual WebSocket simultaneo**: CDP ↔ ARGUS con 2 Runspace paralleli
    - `Page.enable` / `Runtime.enable` / `Network.enable` / `Page.startScreencast` (JPEG q=60, 1600x900, everyNthFrame=1)
    - Handler `Page.screencastFrame` con **ACK obbligatorio** (`Page.screencastFrameAck`) altrimenti screencast si ferma dopo pochi frame → relay `{type:frame, data, ts, w, h}` ad ARGUS
    - Handler inverso da ARGUS: traduce `{mouse/key/scroll}` in `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` / `Input.dispatchMouseWheel`
    - Modifiers mapping CDP: alt=1, ctrl=2, meta=4, shift=8 (bitmask sommata)
    - Watchdog inattività 30 min + max 2h sessione + cleanup user-data-dir + kill Edge orphan
  - **Handler `remote_browser_start`** in `connector.ps1` (main pending_commands loop):
    - Estrae session_id/device_ip/port/token dal payload
    - Deriva URL device (https o http su porte 80/8080/8008)
    - Lancia `remote_browser.ps1` in processo separato con `Start-Process -WindowStyle Hidden`
    - Log per sessione in `$env:ProgramData\86NocConnector\rmt_<sid>.log`
  - **Backend** `console_rmt.py` aggiornato: `pending_commands.payload.token` ora incluso esplicitamente (il connector lo usa senza parsare ws_relay_url)
  - Include TUTTI i fix v3.3.7: Watchdog auto-recovery servizio, regex HTML5 unquoted, Install-Update con 4 metodi fallback + verifica PID-alive.

## 2026-04-22 — RMT Phase 1
- Backend `/app/backend/routes/console_rmt.py` — POST /session, WS relay operator/connector, audit.
- Frontend `RemoteBrowserModal.js` + pulsante **RMT** (fuchsia) in WebConsoleTabs toolbar.
- SW cache v7→v8.

## 2026-04-21 Sessione precedente
(Vedi PRD.md per dettagli completi: Vendor Alerts Phase A, 13 Device Profiles, Runbook Auto-Match, Web Console V4, v3.3.5 Dynamic Port Whitelist, v3.3.6 HTML5 regex fix, v3.3.7 Watchdog.)
