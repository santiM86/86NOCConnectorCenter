# 2026-02-12 — Argus Desktop v5.0.0 — REWRITE TOTALE GUI CONNECTOR

## 🚀 Bye `nocagent-ui.exe`, hello `ArgusDesktop.exe`

L'app GUI desktop del connector è stata **buttata e riscritta da zero**
con stack moderno per risolvere il "freeze totale" del vecchio
`nocagent-ui.exe` (basato su lxn/walk Win32, abbandonato 2021).

**Stack nuovo**:
- Backend: **Go 1.23** + **Wails v2.12** (tutto async, zero blocking)
- Frontend: **React 18** + **TypeScript strict** + **Vite 6** + **Tailwind 3**
  + 13 Radix UI primitives (Button, Card, Tooltip, ScrollArea, Switch, …)
- Animazioni: **Framer Motion** (page transitions, hover, pulse-dot)
- WebView nativo: **WebView2** (Edge Chromium, preinstallato Win10 21H2+)
- Bundle: **3.7 MB** binario Windows, **397 KB** JS minified

## ✨ Features MVP (6 pagine complete)

| Pagina | Status |
|---|---|
| **Dashboard** | ✅ 4 KPI cards animate, stato agent, activity feed live |
| **Dispositivi** | ✅ Tabella filtrabile, search, chip-filter colorati, tasto Ping per device |
| **Auto-Discovery** | ✅ Tabella endpoint ARP/mDNS/PTR con vendor |
| **Scanner LAN** | 🟡 UI completa, backend `forceLanScan` da agganciare |
| **Diagnostica** | ✅ Log live auto-scroll, filter per livello, export NDJSON |
| **Impostazioni** | ✅ Agent ID, Client ID, Token mascherato + copy, service start/stop/restart |

## 🎨 Design system

- **Dark mode signature** (Linear/Cursor-style): sfondo `#0b0d14`, accent ciano `#38bdf8`
- **Light mode** alternativo + **System** che segue OS
- **Theme cycle** dal bottom-left (Dark → Light → System)
- **Status pills** animate (CENTER ONLINE / AGENT RUN) in topbar drag-region
- **Custom window controls** (minimize / maximize / close-to-tray)
- **DPI-aware** (sharp su 4K)
- **`data-testid` su ogni elemento interattivo** → 100% testabile via Playwright

## 🔧 File creati (29 nuovi)

```
noc-agent/cmd/nocui-v5/
├── main.go              (Wails App opts, lifecycle, tray)
├── app.go               (Bindings esposti a JS, async)
├── helpers.go           (parser agent.yaml, sc.exe wrapper, HTTP JSON)
├── wails.json
└── frontend/ (24 file)
    ├── package.json, tsconfig.json, tailwind.config.js, vite.config.ts
    ├── postcss.config.js, index.html, src/vite-env.d.ts
    └── src/
        ├── main.tsx, App.tsx, styles.css
        ├── lib/{bridge.ts, theme.tsx, utils.ts}
        ├── components/AppShell.tsx
        ├── components/ui/{button, card, badge, input, tooltip, scroll-area, switch, progress}.tsx
        └── pages/{Dashboard, Devices, Discovery, Scanner, Logs, Settings}Page.tsx
```

## 📦 Distribuzione

- **Bundle**: `/app/deploy_patches/v5.0.0/ArgusDesktop.exe` (3.7 MB)
- **Preview live** (no install): https://device-poller-ws.preview.emergentagent.com/argus-desktop-preview/
- **README deploy**: `/app/deploy_patches/v5.0.0/README.md` (PowerShell one-liner per SOCIALSRV)

## ⚠️ Note

- `ArgusDesktop.exe` **non sostituisce** `nocagent.exe` (servizio). È una
  GUI separata che gli utenti lanciano quando vogliono — il servizio
  continua a girare in background indipendentemente.
- WebView2 è preinstallato su Win10 21H2+ / Win11 / Server 2022. Su
  Server 2016/2019 va installato manualmente (50 MB, link diretto
  Microsoft, scarico automatico al primo run dell'app).

## 🧪 Test

- ✅ `tsc -b && vite build` — 1981 modules, 0 errors, 2.4s
- ✅ `GOOS=windows go build` — clean cross-compile, 3.7 MB output
- ✅ Smoke test browser (Playwright via preview): rendering OK, fonts OK,
  dark mode OK, animazioni OK, sidebar nav OK
- 🟡 Test nativo WebView2 sul server Windows: pending utente

---


# 2026-02-12 — Agent Go v4.2.0 — LIVE POLLING (ICMP + SNMP)

## 🚀 Feature P0
- **Live Polling nativo nell'Agent Go**: il binario ora effettua autonomamente
  ICMP ping (e SNMP basic) verso i device gestiti del tenant e invia i
  risultati via WebSocket. Sostituisce completamente il polling del vecchio
  Connector PowerShell per i device approvati via Auto-Discovery.
- **3-failure threshold anti-flapping**: i device passano a `offline` solo
  dopo 3 fallimenti ICMP consecutivi (~3 min con interval 60s). Reset
  automatico al primo successo. Nuovo campo `consecutive_ping_failures`
  in `managed_devices`.
- **Hot-push config su approval**: appena un device viene approvato dalla
  pagina Auto-Discovery, il backend ri-pusha `server.welcome` a tutti gli
  agent del tenant → l'agent aggiunge il target alla coda di polling
  entro pochi secondi (zero restart richiesto).

## ✨ Nuovi file
- `noc-agent/internal/poller/icmp.go` — PingPoller (cross-platform via
  comando `ping` nativo OS, concorrenza limitata a 32 probe simultanei,
  parser RTT/loss per Windows EN+IT e Linux/macOS).
- `noc-agent/internal/poller/icmp_windows.go` + `icmp_other.go` — build
  tags per nascondere la finestra console su Windows.
- `noc-agent/internal/poller/icmp_test.go` — 3 unit test parser.
- `backend/tests/test_agent_v4_live_polling.py` — 3 scenari pytest.
- `deploy_patches/v4.2.0/` — bundle deploy (2 .py + nocagent.exe + README).

## 🔧 File modificati
- `noc-agent/pkg/proto/messages.go` — `EventPingPoll` + `PingPollResult`.
- `noc-agent/internal/config/config.go` — `PingConfig` + `PingTarget`,
  default Interval=60s, Count=1.
- `noc-agent/cmd/agent/main.go` — istanzia PingPoller, registra
  `force_ping_poll`, parsa il blocco `ping` nel `server.welcome`.
- `backend/routes/agent_ws.py` — `_build_poller_config` emette anche
  `ping`; nuovo `_bridge_ping_poll` con threshold; nuovo
  `push_config_to_client` (re-usa `server.welcome`).
- `backend/routes/advanced_features.py` — `/api/discovery/approve` chiama
  `push_config_to_client` post-insert.

## 🧪 Test
- `go test ./internal/poller/...` → 3/3 PASS (parser Linux/Win-IT/Win-EN).
- `pytest backend/tests/test_agent_v4_live_polling.py` → 1/1 PASS
  (3 scenari coperti).
- `pytest backend/tests/test_advanced_features.py` → 24/24 PASS (nessuna
  regressione su `/api/discovery/approve`).

## ⚠️ Deploy
Patch file in `/app/deploy_patches/v4.2.0/` (README incluso). NON usare
`sync-argus.sh` (rompe venv). `scp` mirato dei 2 .py + nocagent.exe.

---


# 2026-02-13 — v3.8.1 SCANNER STABILITY & UX

## 🐛 Bug Fix Critici
1. **Scanner faceva sparire il Master** (Bug #5): il filtro upsert su `connector_status` usava `(client_id, hostname)`. Quando Master e Scanner giravano sulla stessa macchina (stesso hostname), lo Scanner sovrascriveva la riga del Master.  
   → Fix: indice unique esteso a `(client_id, hostname, mode)` in `server.py`. Heartbeat e tutti gli `update_one` di `connector.py` ora filtrano la chiave composita completa. Force-update e refresh-requested mirati al `mode=master`.
2. **Scanner si scollegava continuamente** (Bug #3): `argus-scanner.ps1` usava `ForEach-Object -Parallel` (PS7+ only). Con `$ErrorActionPreference="Stop"` su Windows PS 5.1 lo script terminava al primo loop.  
   → Fix: ARP scan riscritto con `Start-Job` batch (compatibile PS5.1+). `ErrorActionPreference=Continue` nel loop. Try/catch difensivi su ARP e mDNS. Logging completo in `C:\ProgramData\86NocConnector\scanner.log`.

## ✨ Feature
- **Pulsante "Scansiona LAN e Importa Dispositivi"** nel wizard installer (visibile solo modalità Scanner). Apre dialog modale con:
  - ListView IP / MAC / Rilevato via / Hostname
  - Checkbox per selezione granulare
  - Pulsante "Importa selezionati al Center" → POST `/api/connector/lan-scan`
- **Hostname auto-suffix**: lo Scanner durante setup verifica via `/api/connector/by-hostname/...` se esiste già un Master con lo stesso hostname e si registra come `{HOSTNAME}-scanner` per evitare conflitti.
- **Switch CLI `-ScanOnce` / `-AsLibrary`** in argus-scanner.ps1 per uso esterno (tray, wizard).

## 🎨 UI/UX
- Badge SCANNER cambiato da fucsia → **azzurro (sky-500)** (richiesta utente).
- Connector Scanner ora visualizzato come `Connector Scanner — {hostname}` nella lista.
- Border-l indentazione dei child connector cambiato da fucsia → azzurro.

## 📦 File modificati
- `backend/server.py` — indice composito esteso a 3 campi
- `backend/routes/connector.py` — heartbeat, force-update, request-refresh, update-progress, reset-update-status, lan-scan filtri composti
- `frontend/src/pages/ConnectorsPage.js` — colore azzurro + label "Connector Scanner"
- `frontend/public/sw.js` — bump cache `noc-center-v15`
- `noc-connector/prg/src/argus-scanner.ps1` — riscritto con compat PS5.1, logging, library mode
- `noc-connector/prg/src/installer_gui.ps1` — aggiunto `Show-LanScanDialog` + pulsante "Scansiona LAN e Importa"
- `noc-connector/prg/version.json` — v3.8.1
- `connector_updates/86NocConnector_v3.8.1.zip` — pacchetto pubblicato (auto-update attivo)
- `frontend/public/86NocConnector.zip` — download diretto aggiornato

## 🧪 Validazione
- **Backend**: heartbeat duplicato (master+scanner stesso hostname) crea 2 righe distinte in `connector_status` ✅
- **Frontend**: screenshot conferma badge azzurro, etichetta "Connector Scanner — ...", indentazione corretta ✅
- **Indice DB**: `client_hostname_mode_unique` creato e funzionante ✅

---


# CHANGELOG — 86BIT ARGUS Center

## 2026-02-13 (sessione successiva) — Mini-scanner cross-VLAN + Fingerbank + auto-rinomina

### MULTI-MODE Connector v3.8.0
**Problema affrontato**: discovery cross-VLAN bloccata da firewall/ACL. Senza
deployare un agente RMM su ogni device, era impossibile sapere modello/categoria
delle stampanti/AP/IPCam in VLAN diverse da quella del Connector master.

**Soluzione**: stesso bundle Windows del Connector con due modalita' di
funzionamento (master polling completo vs scanner discovery locale). Wizard
installer (Windows.Forms) invariato per UX, con step "Modalita" + Subnet/VLAN
nella pagina Config gia' esistente.

### File modificati / creati
- `noc-connector/prg/src/installer_gui.ps1` — nuovi radio MASTER/SCANNER + Subnet/VLAN
- `noc-connector/prg/src/connector.ps1` — branch entry-point sulla base config.mode + heartbeat esteso
- `noc-connector/prg/src/argus-scanner.ps1` (nuovo, 230 righe) — loop ARP+mDNS+SNMP, DPAPI per API key
- `noc-connector/prg/src/tray_app.ps1` — tooltip e status mostrano modalita' corrente
- `noc-connector/prg/version.json` — bump a 3.8.0
- `backend/models.py` — `LanScanReport`, `LanScanEndpoint`, heartbeat esteso (mode/subnet/vlan_id)
- `backend/routes/connector.py` — endpoint POST /api/connector/lan-scan, chiave composita (client_id, hostname)
- `backend/server.py` — drop unique index legacy + create composite (client_id, hostname)
- `frontend/src/pages/ConnectorsPage.js` — raggruppamento master+scanner per cliente, badge MASTER/SCANNER, indentazione visuale

### Fingerbank API integration (Fase 2)
- `backend/services/fingerbank_service.py` (nuovo) — API client + cifratura + cache 30gg
- `backend/routes/admin_integrations.py` (nuovo) — endpoint admin GET/PUT/DELETE/POST test
- `frontend/src/pages/FingerbankSettingsPage.js` (nuovo) — pannello gestione API key con masking
- API key fornita dall'utente (`69fe2f73...402b`) salvata cifrata AES-256-GCM v2

### Device classification (Fase 1)
- `backend/routes/oui_lookup.py` — `classify_device()` + 50 vendor single-purpose hint
  - Categorie: printer, voip_phone, ip_camera, access_point, ups, firewall, router, server, iot
  - Multi-segnale: sysDescr -> LLDP-MED -> LLDP-caps -> hostname pattern -> OUI + PoE class
- `backend/routes/topology.py` — neighbor "unknown" arricchiti con device_category/confidence/source

### Test passati
- 3 connector dello stesso cliente (1 master + 2 scanner VLAN diverse) convivono in DB
- UI raggruppa scanner indentati sotto master con bordo fucsia (▶ ╰─)
- Heartbeat scanner + lan-scan POST con 3 endpoint stored 3/3
- Fingerbank API: salvataggio cifrato + masked key (••••402b) + test reale OK
- classify_device: 9 test (printer/voip/camera/AP/UPS/firewall/HPE+PoE/unknown/LLDP-cap) passati

### Auto-rinomina device (bonus richiesto utente)
- `backend/routes/connector.py` — auto-promote name da sys_name SNMP se nome ancora `Auto-{ip}`
- `backend/routes/devices.py` — PATCH device setta `name_user_locked=true` per evitare override



## 2026-02-13 — Fix definitivo "schermata nera" su Porte Switch + auto-promote nome device

### Problema
Cliccando "Porte switch" dentro il modal "Scheda Dispositivo" l'utente vedeva
schermata nera: il modal Radix Dialog non si smontava in tempo, lasciando
overlay + `pointer-events:none` + `data-scroll-locked` sul body, che
oscurava la `SwitchPortsPage` appena montata. Il problema si manifestava
solo nel flusso modal -> Porte switch (URL diretto invece funzionava).

### Fix frontend (chirurgico, 1 useEffect)
**File: `frontend/src/pages/SwitchPortsPage.js`**
- `useEffect` di cleanup al mount: reset `body.style.pointerEvents`,
  `body.style.overflow`, rimozione `data-scroll-locked`, rimozione overlay
  Radix orfani. Ripetuto dopo 400ms per coprire close-animation lente.
- Test simulato (body lockato + overlay): pagina si auto-pulisce in <400ms
  e diventa interattiva.

### Fix backend (auto-rinomina device da sys_name SNMP)
**File: `backend/routes/connector.py`**
- Nel ciclo di polling, se `dev.sys_name` valido + device con nome default
  (`Auto-{ip}`, `Manuale-{ip}`, ""), aggiorna `name` in `db.devices` e
  `db.managed_devices`. Flag `name_auto_promoted: true`.
- Rispetta `name_user_locked` per non sovrascrivere rinomine manuali.

**File: `backend/routes/devices.py`**
- `PATCH /devices/{id}` ora setta `name_user_locked: true` quando l'admin
  cambia il nome via UI. Cascade su `managed_devices` per coerenza.

### Test passati
- Pulsante "Porte switch" nella tabella device: 3 icone su switch detectati.
- Click -> naviga a `/switch-ports/<ip>`, body sbloccato.
- Simulazione body lock + overlay forzato: cleanup automatico funziona.
- Auto-promote nome: 3 casi (default -> sys_name OK, locked rispettato, custom non toccato).

### Lezione
L'utente testava su `argus.86bit.it` (produzione) mentre i fix erano nel
preview Emergent. Discrepanze risolte solo dopo Deploy + Service Worker
Unregister + Ctrl+Shift+R.



## 2026-02-13 — FIX URGENTE: ripristino pulsante "Porte switch" nella tabella device

### Problema
L'utente ha segnalato che il pulsante "Porte switch" non funzionava piu' come
prima nella lista dispositivi del cliente (`ClientOverviewPage` > tab Dispositivi).
Una sessione precedente aveva rimosso interamente il blocco JSX che renderizzava
l'icona `NetworkSlash` accanto a ogni riga device (commit `43bb07a`, 58 righe
eliminate da `ClientOverviewPage.js`). Rimaneva solo il pulsante nella scheda
info popup (`DeviceInfoCard`), ma non era quello che l'utente usava quotidianamente.

### Fix
- `frontend/src/pages/ClientOverviewPage.js` — ripristinato il blocco di detection
  multi-segnale (device_type / model / hostname / profile_key / vendor) e il
  pulsante icona `NetworkSlash` che naviga a `/switch-ports/:ip`. Inserito tra
  l'icona "Info" e l'icona "Trend" come era prima.
- Nessuna modifica a `SwitchPortsPage.js`, `App.js`, routing o `ErrorBoundary`.

### Verifica
- Login admin@86bit.it su preview → Clienti → 86BIT_Office → Dispositivi.
- 3 icone `Porte switch` visibili accanto agli switch (switch-test, Auto-192.168.1.3,
  TestSwitch). I device unknown non mostrano l'icona. Click → naviga correttamente
  a `/switch-ports/:ip` e mostra la pagina completa (empty state amber nel preview
  perche' non ci sono dati SNMP; in produzione con Connector attivo appariranno
  tutti i dati).



## 2026-02-13 — v3.7.6 FIX DOS box + pulsante OK tagliato (DPI 125%/150%)

### Problemi risolti
1. **DOS Box all'apertura dal menu Start**: ogni volta che l'utente cliccava
   "ARGUS Center Connector" dal menu Start si apriva brevemente una finestra
   console PowerShell/CMD. Chiudendola si killava il tray. Root cause: lo
   shortcut puntava a `86NocConnector.bat`, che obbliga Windows a lanciare
   `cmd.exe`.
2. **Pulsante OK tagliato nella popup "Informazioni"** a DPI 125% su Windows 11.
   I precedenti tentativi (Anchor Bottom+Right, AutoScaleMode=None, ClientSize
   dinamico) non bastavano perche' Windows applica "DPI virtualization" sui
   processi non-DPI-aware e sfalsa le coordinate in pixel assoluti.
3. **Tray non ripartiva al reboot**: nessuno shortcut di autostart al logon,
   quindi dopo ogni riavvio l'utente doveva riaprirlo manualmente.

### Fix
- `installer_gui.ps1`: shortcut del menu Start ora punta a
  `wscript.exe "tray_launcher.vbs"` (100% silenzioso, nessun cmd.exe flash).
  HKCU Run fallback idem.
- `installer_gui.ps1`: creato shortcut nella cartella Startup common con
  stesso target wscript+VBS per auto-avvio tray al logon utente.
- `update_check.ps1` (Step 9.5): MIGRAZIONE AUTOMATICA. Al primo update
  ogni installazione esistente (con shortcut pre-3.7.6 puntato a .bat)
  viene riscritta puntando a wscript+VBS. Crea anche lo shortcut Startup
  se mancante. Idempotente.
- `tray_app.ps1` (About): popup "Informazioni" riscritta con layout
  **Dock-based** (Panel Bottom per il bottone + Panel Fill per il contenuto).
  Il bottone OK e' gestito nativamente dal layout manager di WinForms,
  NON piu' tramite coordinate assolute -> impossibile tagliarlo.
- `tray_app.ps1`: aggiunto `SetProcessDpiAwareness(1)` all'avvio (prima di
  qualsiasi chiamata Windows.Forms). Rimuove la DPI virtualization su
  Windows 11 a scale 125/150%.
- `86NocConnector.bat`: riscritto per delegare a wscript+VBS (retrocompat
  autostart residui pre-migrazione).

### File modificati
- `noc-connector/prg/version.json` -> 3.7.6
- `noc-connector/prg/86NocConnector.bat`
- `noc-connector/prg/src/tray_app.ps1` (About form + DPI awareness)
- `noc-connector/prg/src/installer_gui.ps1` (shortcut wscript + Startup)
- `noc-connector/prg/src/update_check.ps1` (Step 9.5 migrazione shortcut)

### Test suggerito su GALVANSRV
1. Dal NOC Center: `/connectors` -> "Forza aggiornamento"
2. Attendere che update_check.ps1 registri `tray_restart.flag`
3. Logoff/logon (per triggerare la nuova Startup entry)
4. Avviare da menu Start "ARGUS Center Connector": NESSUNA finestra console
5. Tray -> "Informazioni": pulsante OK completamente visibile anche a 125% DPI


## 2026-02-12 — v3.6.8 Connector SNMP: fix crash cast decimal su switch HPE

### Problema
`Poll-SwitchPortDetails` crashava in toto a linea 2513 con:
`Impossibile convertire il valore "" nel tipo "System.Decimal"`.

Gli switch HPE Comware restituiscono stringhe vuote `""` o `null` su alcuni
contatori (`ifInOctets`, `ifOutOctets`, `ifHCInOctets`, `ifHighSpeed`,
`ifLastChange`) per porte disabilitate o non attive. Il cast diretto
`[decimal]$val` trovava una stringa vuota e faceva fallire TUTTO il loop,
lasciando `$result.ports` sempre vuoto.

### Fix
In `snmp_poller.ps1` (`Poll-SwitchPortDetails`):
- Aggiunto helper `_SafeNum($val, $type)` che converte in modo difensivo
  qualsiasi valore SNMP in `decimal`/`long`/`int`, ritornando 0 su vuoti,
  null o formati non validi (con fallback culture-safe per locale italiano).
- Sostituiti tutti i cast diretti `[decimal]`/`[long]`/`[int]` alle righe
  2506-2518 con chiamate a `_SafeNum`.
- Protetti anche i cast `[int]` dei valori PoE (`pethPsePortAdminEnable`,
  `pethPsePortDetectionStatus`, `pethPsePortPowerClassifications`) alle
  righe 2488-2492.

### File modificati
- `/app/noc-connector/prg/src/snmp_poller.ps1` (2486-2545)
- `/app/noc-connector/prg/version.json` → 3.6.8

### Test atteso
```powershell
. "C:\Program Files\86NocConnector\src\snmp_poller.ps1"
$r = Poll-SwitchPortDetails "10.100.61.220" "Argus"
"Porte: $($r.ports.Count)"
# Atteso: Porte: 48 (o simile, non piu' 0)
```


## 2026-05-01 (sera) — Bootstrap Installer Wizard self-elevating

### Installer "doppio-click" per setup nuovi connector
Richiesta utente: link con wizard UI cliccabile per installazione, non ZIP da
estrarre manualmente.

**Nuovo file** `/app/noc-connector/installer/Install-ArgusConnector.ps1`:
single-file bootstrap installer che fa:
1. Auto-elevazione UAC (rileva privilegi e si rilancia come admin)
2. Download dell'ultima versione attiva del connector ZIP dal Center
3. Estrazione in `$env:TEMP\argus_bootstrap_<timestamp>`
4. Lancio del wizard GUI esistente (`installer_gui.ps1` con WinForms native)
5. Cleanup tmp dir

**Companion** `/app/noc-connector/installer/Install-ArgusConnector.bat`:
launcher .bat per chi non sa eseguire .ps1 da PowerShell. Doppio click parte.

**Backend** (`routes/connector.py`):
- `GET /api/connector/install-bootstrap.ps1`: serve il bootstrap script con
  iniezione dinamica del `$CenterUrl` derivato da `x-forwarded-host` +
  `x-forwarded-proto` (così funziona sia su preview che su prod argus.86bit.it
  qualunque sia il dominio del Center).
- `GET /api/connector/install-bootstrap.bat`: serve il companion launcher
  con `Content-Disposition: attachment` per il download diretto.

**UX flow per nuovo cliente:**
1. Admin manda al cliente: `https://argus.86bit.it/api/connector/install-bootstrap.ps1`
2. Cliente scarica → tasto destro → Esegui con PowerShell
3. UAC prompt → accept → script scarica ZIP, estrae, lancia wizard GUI
4. Wizard chiede URL Center + API Key + percorso install → installazione NSSM
   completa con Defender exclusions + Task Scheduler updater
5. Connector parte come servizio Windows + tray icon



## 2026-05-01 — Switch Port Monitor Nebula-style + Connector v3.6.0

### Vista porta-per-porta in stile HPE Instant On / Cisco Meraki
Richiesta utente: "vorrei come vedi questo esempio quali sono le porte accese,
funzionanti, poe acceso, e dove sono collegate a cosa" (3 screenshot HPE Instant
On del cellulare allegati).

**Connector PowerShell v3.6.0** (`snmp_poller.ps1`):
- Nuova funzione `Poll-SwitchPortDetails` che effettua polling completo
  ifTable/ifXTable/ifLastChange + POWER-ETHERNET-MIB (RFC 3621) per dati PoE
- Counters HC (HCInOctets/HCOutOctets/HCInUcastPkts/HCOutUcastPkts) con
  delta-state in `$script:PortCounters` per calcolo **Rx/Tx bps live + pps**
- PoE per porta: `pethPsePortAdminEnable` + `pethPsePortDetectionStatus` +
  `pethPsePortPowerClassifications` (Class 1..4 mappata a 4/7/15.4/30 W)
- LLDP arricchito con `lldpRemSysCapEnabled` (bitmap WLAN AP=0x08, Bridge=0x04,
  Router=0x10) per discriminare AP / Switch uplink / Internet
- Chiamata aggiunta in `Run-FullDiscovery` che invia tutto a `connector/switch-ports`
- Fallback a counter 32-bit se HC vuoti, skip Vlan/Loopback/Tunnel automatico

**Backend** (`routes/connector.py`, `routes/topology.py`):
- Endpoint `/sp` esteso per persistere: `descr/alias/rx_bps/tx_bps/rx_pps/tx_pps/`
  `in_octets/out_octets/poe_admin/poe_status/poe_class`
- `lldp_neighbors` ora salva anche `remote_sys_cap`
- `GET /api/devices/{ip}/switch-ports` arricchito con classificazione **port_type**
  (`poe`/`ap`/`switch`/`cloud`/`device`/`link_up`/`empty`/`disabled`) calcolata
  da LLDP capabilities + lookup in `managed_devices` (device_type)
- `totals` restituisce anche `poe_active`, `rx_bps`, `tx_bps` totali

**Frontend** (`pages/SwitchPortsPage.js` riscritto):
- Tile Nebula-style: chip nero col numero porta sopra, riquadro 11×11 con icona
  contestuale (`Lightning` PoE, `WifiHigh` AP, `Stack` switch uplink, `Cloud`
  internet/router, `Desktop` device, `Plugs` link up generico, `Prohibit` off)
- Click su porta → pannello dettaglio: `1 Gbps / Full-duplex` + badge
  `PoE attivo · Classe N (X W)`, traffico Rx/Tx bps + pps con frecce, "Connesso a"
  con link al device remoto se presente nel NOC, **donut SVG 24h** con totali
  Scaricati/Caricati/Trasferiti
- Filtri: Tutte / Up / Down / Admin-down / **PoE** / LLDP
- Tabella riepilogo collassabile ↓ con colonna PoE Class chip ambra
- Auto-refresh ogni 30s per traffico live, responsive nativo (tile 11×11 mobile,
  12×12 desktop), legenda icone in fondo

**Test end-to-end con dati simulati** (8 porte: 2 PoE attivo, 1 AP=Casa Mamma,
1 PC, 1 FortiGate uplink, 1 Switch01, 3 down): API restituisce
classificazione corretta `port_type` per ogni porta, UI render screenshot OK
con tile colorati e selection ring cyan, dettaglio porta 4 mostra "PoE attivo
Classe 2 · 15.4 W · Connesso a AP2 - Casa Mamma".

**Per testare in produzione:** il connector v3.6.0 deve essere installato sui
client (auto-update via `update_check.ps1`); ad ogni "Full Network Discovery"
(default 10 cicli ≈ 10 min) gli switch SNMP verranno pollati per le porte.



## 2026-04-30 — Host-level mapping VM Backup (simmetria con 365 sub-groups)

### Dentro un customer puoi agganciare ogni host alla sua azienda
Richiesta utente: "anche per VM mostrami e lasciami agganciare gli host che
diventano l'azienda". Esempio: `giambarinigroup.onmicrosoft.com` ha 6 host
HyperV (CAMBIANOSRV, GALVANSRV, METALJUMBOSRV, ODSTRASPORTISRV, OLFEZSRV2,
ZITACSRV) ognuno fisicamente in un'azienda diversa del gruppo.

**Backend** `routes/hornetsecurity_vmbackup.py`:
- `_client_vm_filters()` ritorna (customer, hosts), `_matches_vm_filter()` +
  `_build_vm_mongo_filter()` simmetrici alla 365 sub-group
- `GET /admin/hornetsecurity-vm/customers/{customer}/hosts` → aggregazione
  host con stats (vms_total/failed/stale/warning/success) e mapped_clients
- `PUT /mapping` accetta `[{customer, hosts: [...]}]` oltre a stringhe legacy
- Fan-out alert rispetta il filtro host (scelta utente: filtraggio stretto)

**Backend** `routes/overview.py`: dashboard aggregata rispetta il filtro host.

**Frontend** `pages/HornetsecuritySettingsPage.js`:
- Chevron expand su riga customer + badge "N 👥" se `hosts_count > 1`
- `HostsPanel`/`HostRow` con auto-suggestion per nome (GALVANSRV → Galvan)
- Badge "(ereditato)" se customer intero gia` mappato

**Test reali**: mapping `CAMBIANOSRV` su 86BIT_Office → 35 VM filtrate (30 OK
+ 5 stale), 5 alert sincronizzati; gli altri 5 host non toccano quel cliente.

**Build artifacts**:
- Backend: `argus-backend-latest.tar.gz` 2.5 MB, SHA256 `f433036c…`
- Frontend: `argus-frontend-latest.tar.gz` 4.7 MB, SHA256 `e3ce3162…`

---


## 2026-04-30 — Backup aggregati nelle card Dashboard + Quick Stats cliente

### Le card esistenti ora includono 365 + VM Backup (non più solo legacy)
Su richiesta dell'utente, la card **Backup** nella dashboard principale e nel
Quick Stats del cliente mostra i contatori aggregati di tutti e 3 i provider:
`db.backup_status` (legacy) + `db.backup_job_status` (365 Total) + `db.vmbackup_jobs`
(VM Altaro), filtrati per cliente via i rispettivi mapping.

**Backend** `routes/overview.py` — endpoint `/api/overview/clients`:
- Nuova aggregazione `m365_by_client`: legge i workload 365 e li fan-out sui
  clienti secondo il mapping `hornetsecurity_tenants` (stringhe o dict con
  sub_groups), sommando totale/ok/error per-cliente
- Nuova aggregazione `vm_by_client`: legge le VM Altaro e le fan-out secondo
  `hornetsecurity_vm_customers`, aggiungendo `warning` e `stale`
- I 3 totali vengono fusi in `backup_by_client[cid]` con schema
  `{total, ok, warning, error, stale}`
- `health = "warning"` ora viene triggerato anche da `backup_warnings > 0`
  o `backup_stale > 0` (prima solo `error > 0`)

**Frontend** `pages/DashboardPage.js` — SvcLine "Backup":
- Priorità di display: error > warning > stale > OK
- Stringhe: `"N ERR"` (rosso) / `"N WARN"` (arancio) / `"N STALE"` (arancio) / `"OK"` (verde)
- Sub-label mostra `ok/total` solo quando tutto OK

**Frontend** `pages/ClientOverviewPage.js` — Quick Stats "Backup":
- Nuovo stato `backupSummary` con fetch paralleli di `/backup/hornetsecurity/status`
  e `/backup/vmbackup/status`
- Card mostra `"N KO"` se ci sono failed, sub dettaglia `365:X · VM:Y`
- Stato WARN/STALE/OK con contatori `ok/total` nel sub

**Test**: cliente 86BIT_Office con mapping galvan.it (365) + ifalegnami.eu (VM):
aggrega a **123 backup totali** (50 ok galvan + 16 VM + 57 legacy), **1 error**
(365), **12 stale** (VM + legacy). `health="warning"` come da policy.

**Build artifacts**:
- Backend: `argus-backend-latest.tar.gz` 2.5 MB, SHA256 `d14913cb…`
- Frontend: `argus-frontend-latest.tar.gz` 4.7 MB, SHA256 `8cf17e22…`

---

## 2026-04-30 — UI Config globale VM Backup nella pagina Hornetsecurity Settings

### Pagina `/settings/hornetsecurity` ora ha tab "VM Backup (Altaro)"
Prima l'utente doveva chiamare gli endpoint via curl per configurare la
chiave API del portal MSP Altaro. Ora e` tutto UI-driven:

**Frontend** `pages/HornetsecuritySettingsPage.js`:
- Tab switcher in alto: `365 Total Backup` / `VM Backup (Altaro)`
- Nuovo componente `VMBackupSettingsSection`:
  - Form config (API URL + User ID + API Key + polling interval + enabled),
    chiave in campo password, mai mostrata in chiaro (solo maschera ****xxxx)
  - Pulsanti "Poll Ora" (trigger manuale) e "Sync Alert" (riemette gli alert)
  - Stato connessione con ultimo polling, conteggi customers/VM/failed/stale
  - Tabella 47 customer con stats (VM totali, hosts, failed, stale)
  - Filtri: Tutti / Da mappare / Mappati / Con problemi
  - Mapping customer↔cliente ARGUS con **auto-suggestion** (es. dominio
    `86bit.it` → suggerisce automaticamente cliente "86BIT_Office") e
    dropdown Cambia/Assegna/Rimuovi

**Build artifacts**:
- Frontend: `argus-frontend-latest.tar.gz` 4.7 MB, SHA256 `42a43eed…`

Testato: config salvata → badge ATTIVA → 47 rows customer caricate.

---

## 2026-04-30 — Integrazione Hornetsecurity VM Backup (ex-Altaro)

### 2ª fonte backup: Altaro VM Backup via API portal MSP
Aggiunta integrazione completa con l'API del portal MSP (Hornetsecurity VM
Backup / Altaro). Supporta 47 customer reali gestiti, 242 VM, polling 10 min.

**Backend** — nuovi file:
- `routes/hornetsecurity_vmbackup.py`:
  - Config globale cifrata (api_url + api_key + userId) a `/admin/hornetsecurity-vm/config`
  - Parser payload `hornetSecurityReport → installations → hosts → VMs`
  - Storage `vmbackup_jobs` (key: customer+host+vm_id), persiste per ogni VM
    status onsite, offsite, 2nd offsite, tempo, durata, dimensione, cdpEnabled
  - Mapping `clients.hornetsecurity_vm_customers: [customerName]` (list[str])
  - Endpoint admin `/admin/hornetsecurity-vm/customers` (stats per customer)
  - Endpoint client `/clients/{id}/backup/vmbackup/status` + `/mapping`
  - Endpoint admin `/admin/hornetsecurity-vm/sync-all-alerts` + `/poll-now`
- `services/hornetsecurity_vmbackup_poller.py`: scheduler APS separato (tick 1 min,
  rispetta `polling_interval_minutes` default 10)

**Severity smart escalation**:
- `Failed` → **high** (intervento richiesto)
- `Warning` → **medium**
- Backup **stale** > 48h anche se Success → **medium** (anomalia operativa)
- `Unknown` con tempo null → skip (installazione vuota, no signal)

**Alert fan-out**: per ogni cliente mappato al customer, alert in `db.alerts`
con id deterministico `vmbackup-{client_id}-{customer}-{vm_id}`, auto-resolve
quando il backup torna OK. Sync immediato alla modifica mapping.

**Frontend** `pages/ClientOverviewPage.js`:
- `BackupTab` rifattorizzato con sub-tabs "365 Total Backup" / "VM Backup (Altaro)"
- Nuovo `VMBackupPanel` con:
  - Header mapping + polling info + pulsante "Poll Ora" + "Modifica mapping"
  - 5 stat box (VM totali / Success / Failed / Warning / Stale >48h)
  - Filtri Vista: Tutte / Solo problemi / Solo stale
  - Tabella VM con colonne: VM, Host, Hypervisor, Customer, Onsite, Offsite,
    2° Offsite, Ultimo backup, Dim. Badge colorati FAILED/WARN/STALE
  - Modal checkbox multi-select dei customer disponibili, con stats inline

**Test reali**: config con API prod → poll 242 VM su 47 customer, 5 failed, 67
stale, 208 success. Mapping `86bit.it + ifalegnami.eu` su cliente test:
sync di 3 alert immediato, severity medium (stale).

**Build artifacts**:
- Backend: `argus-backend-latest.tar.gz` 2.5 MB, SHA256 `0c094b59…`
- Frontend: `argus-frontend-latest.tar.gz` 4.7 MB, SHA256 `8eab2b03…`

### 🚀 Deploy in produzione (ordine consigliato)
1. Self-update backend (via Center → WireGuard → Aggiorna Backend)
2. Self-update frontend
3. UI: `Amministrazione → Hornetsecurity VM Backup → Configura` (incolla api_key
   + userId dal tuo portal MSP)
4. Click "Poll Ora" per popolare subito i dati (o attendi 10 min)
5. Per ogni cliente ARGUS: scheda cliente → Backup → tab "VM Backup (Altaro)"
   → Modifica mapping → seleziona il customer corrispondente → Salva
6. Gli alert backup falliti/stale appariranno automaticamente in `/alerts`

---



### I backup falliti ora compaiono nella pagina Alert e nel badge sidebar
Su richiesta dell'utente, gli alert dei backup Hornetsecurity falliti sono
stati integrati nel sistema di alert principale (`db.alerts`), in modo da
essere visibili a colpo d'occhio nella pagina `/alerts` e contribuire al
contatore della sidebar.

**Backend** `routes/hornetsecurity_backup.py`:
- Nuovo helper `_matches_client_filter()` per matching mapping tenant+sub_group
- Nuovo `_fanout_backup_alert()`: per ogni workload `failed`, fa fan-out su
  TUTTI i clienti il cui mapping copre la coppia (tenant, sub_group),
  creando/aggiornando un record in `db.alerts` con id deterministico
  (`backup-hornet-{client_id}-{tenant}-{workload_id}`) per dedup
- Nuovo `_resolve_backup_alerts()`: auto-resolve degli alert quando il
  workload torna OK (`success`) — aggiorna `status: resolved` + `resolved_at`
- Severity = `high`, source_type = `backup`, device_type = `backup`
- Title formato "Backup fallito: {workload_name}", message include contesto
  (utente, tenant, sub_group)
- Nuovo `_sync_alerts_for_client()` chiamato automaticamente dal PUT
  `/api/clients/{client_id}/backup/hornetsecurity/mapping`: quando cambi un
  mapping, gli alert vengono sincronizzati immediatamente (no attesa del
  prossimo poll)
- Nuovo endpoint admin `POST /api/admin/hornetsecurity/sync-all-alerts` per
  sincronizzare in massa dopo il deploy

**Backend** `routes/alerts.py`:
- Fix filtro `device_type`: ora usa il campo `device_type` dell'alert stesso
  come fallback (prima leggeva solo dal device referenziato, escludendo gli
  alert backup che non hanno device_id)

**Frontend** `pages/AlertsPage.js`:
- Nessuna modifica: il filtro "Tipo: Backup" era già presente e ora funziona

**Test**: mapping cliente → "Europizzi" sincronizza 193 backup alert nel
sistema principale; severity stats `high: 5 → 198`; ACK/Resolve operano
correttamente; cambio mapping triggera sync immediato.

**Build artifacts**:
- `/app/frontend/public/downloads/argus-backend-latest.tar.gz` (2.5 MB,
  SHA256 `862eb46d…`)

### 🚀 Deploy in produzione (oltre al normale self-update backend):
Dopo aver aggiornato il backend, lanciare una sola volta:
```bash
curl -X POST https://argus.86bit.it/api/admin/hornetsecurity/sync-all-alerts \
     -H "Authorization: Bearer <ADMIN_TOKEN>"
```
per popolare gli alert per i clienti già mappati.

---



### UX: filtri rapidi nel pannello Backup cliente
Su richiesta dell'utente, aggiunto toggle prominente sopra la tabella workload
per filtrare velocemente la vista con tre presets:

- **Tutti (N)** — mostra tutti i workload (default)
- **Solo protetti (N)** — mostra solo `status=success` (verde)
- **Solo problemi (N)** — mostra solo `failed + warning + in_progress`

I conteggi nei pulsanti aggiornano dinamicamente in base ai dati. I vecchi
filtri dettagliati (status: success/failed/warning/in_progress/not_applicable/
excluded + tipo + tenant) sono stati spostati in un `<details>` collassabile
"Filtri avanzati" per non saturare la UI.

**File**: `pages/ClientOverviewPage.js` — `HornetsecurityBackupPanel`.
- Test selectors: `data-testid="hornetsecurity-quickfilter-{all|protected_only|issues_only}"`

**Build artifacts**:
- `/app/frontend/public/downloads/argus-frontend-latest.tar.gz` (4.7 MB, SHA256 `562b36b3…`)

---

## 2026-04-30 — Fix Backup Panel Sub-Group Recognition (P0 hotfix)

### Bug: ClientOverviewPage backup tab non riconosceva i mapping per sotto-gruppo
Dopo il deploy della feature Sub-Group Mapping, mappando un cliente solo a uno
o piu` sotto-gruppi (es. galvan.it dentro Gruppo Giambarini), il pannello
Backup nella scheda cliente mostrava ancora "Mapping tenant non configurato"
con CTA "Configura mapping" — perche` controllava solo il vecchio campo
`mapping.tenants` (whole-tenant string list) invece di anche `mapping.filters`
(formato dettagliato con sub_groups).

**Frontend** `pages/ClientOverviewPage.js` (`HornetsecurityBackupPanel`):
- Nuovo computed `hasAnyMapping = mappedFilters.length > 0 || mappedTenants.length > 0`
- Header del pannello attivo ora mostra distintamente i due tipi di mapping:
  - `Tenant (intero)` per whole-tenant string
  - `Tenant → sub_group_a, sub_group_b` per mapping sub-group
- Filtro tenant ora aggrega da entrambe le sorgenti (set union)

**Build artifacts riallineati**:
- `/app/frontend/public/downloads/argus-backend-latest.tar.gz` (2.5 MB)
- `/app/frontend/public/downloads/argus-frontend-latest.tar.gz` (4.7 MB)

**Test**: Mapping `galvan.it` su 86BIT_Office → tab Backup mostra correttamente
98 workload Galvan filtrati (50 Protected + 24 Excluded + 24 N/A), header
"1 mapping attivi: Gruppo Giambarini → galvan.it".

---



### Mappatura per Sotto-Gruppo (dominio email) dentro un singolo tenant
Richiesta utente: alcuni tenant Hornetsecurity (es. "Gruppo Giambarini") contengono
più aziende distinte (galvan.it, olfez.it, zincaturadicambiano.it, ecc.). Ora è
possibile mappare ciascun sotto-gruppo a un cliente ARGUS diverso.

**Backend** `routes/hornetsecurity_backup.py`:
- Nuovo helper `_extract_sub_group()` → deriva automaticamente il dominio email
  da `workload_user` (fallback su `workload_name`, default `_ungrouped_`)
- `_persist_poll_results_global()` ora salva il campo `sub_group` sia in
  `backup_job_status` che in `backup_alerts` ad ogni poll
- Nuova funzione `_resolve_client_filters()` + `_build_mongo_filter_for_client()`
  costruisce query MongoDB `$or` che combina tenant e sub_group
- `GET /api/admin/hornetsecurity/tenants/{tenant_name}/sub-groups` (admin-only)
  ritorna aggregazione dei sotto-gruppi con workloads_total/failed/protected,
  tipi workload, e `mapped_clients` (sia espliciti che ereditati da whole-tenant)
- `POST /api/admin/hornetsecurity/backfill-sub-groups` (one-shot admin)
  popola `sub_group` sui dati già ingestiti (4249 workload + 196 alert migrati)
- `PUT /api/clients/{client_id}/backup/hornetsecurity/mapping` ora accetta
  liste miste: string (whole tenant, legacy) o `{tenant, sub_groups: [...]}`
- `GET /api/clients/{client_id}/backup/hornetsecurity/mapping` espone sia
  `tenants` (legacy string list) sia `filters` (formato dettagliato)
- Endpoint `/status`, `/alerts`, `/storage-trend` ora filtrano per sub_group
  quando il mapping lo specifica. Totali includono `by_sub_group`.
- `GET /api/admin/hornetsecurity/tenants` espone `sub_groups_count` per tenant

**Frontend** `pages/HornetsecuritySettingsPage.js`:
- Nuova colonna "Sotto-gruppi" nella tabella mapping con badge ambra quando >1
- Pulsante expand (chevron) per ogni riga tenant → carica i sotto-gruppi via
  API e mostra una sotto-tabella con: sotto-gruppo, workload, falliti, tipi,
  cliente assegnato, pulsanti Assegna/Cambia/Rimuovi
- Auto-suggestion cliente per dominio (es. "galvan.it" → ★ cliente "Galvan")
- Se il tenant è mappato whole, i sotto-gruppi mostrano badge cyan "(ereditato)"
- Helper `updateSubGroupMapping()` che preserva tutti gli altri mapping del
  cliente, rimuove il sub-group dal cliente precedente e aggiunge al nuovo

**Retro-compatibilità**: i vecchi mapping string (whole-tenant) continuano a
funzionare invariati. Il payload di PUT accetta entrambe le forme, la
persistenza normalizza sulla forma più compatta (string se whole, dict se
sub-group).

**Test**: 14/14 pytest backend (`test_hornetsecurity_subgroups.py`) + 3/3
frontend E2E (iteration_69). Test con mapping mix (string + dict): 432 Europizzi
+ 8 jumboservice.it = 440 workload filtrati correttamente.

---


## 2026-04-30 — Operational Security Hardening (backend v3.5.34)

### 🛡 Brute force + HIBP + Audit Dashboard
Hardening operativo per chiudere il gap "castelli di sabbia": dal singolo
sistema cifrato a un perimetro che si difende attivamente.

**Backend** `security_hardening.py`:
- IP-based brute force detection: 20 fail in finestra `lockout_duration_minutes`
  (default 5min) → blocco IP per 3x il timeout
- Nuova collection `ip_blocks` con TTL implicito (unlock_at)
- `is_ip_blocked()` chiamato in `/api/auth/login` PRIMA del check account
- HTTP 423 "Indirizzo IP temporaneamente bloccato" (audit log severity=critical)

**Backend** `services/password_policy_check.py` (NEW):
- HIBP "Pwned Passwords" via k-anonymity (solo i primi 5 char dello SHA-1)
- API gratuita illimitata, fail-open se HIBP irraggiungibile
- Validazione locale: lunghezza min, mix maiusc/minusc/cifre/simboli, blacklist
  pattern banali (password, admin, qwerty, ...)
- `check_password()` async ritorna {ok, score 0..100, issues, pwned_count}

**Backend** `routes/security_admin.py`:
- `POST /api/admin/security/check-password` (rate-limited 30/min) — UI feedback
- `GET /api/admin/audit/recent?days=N&only_security=bool` — eventi audit con
  aggregati by_action / by_severity / top_ips / failed_logins
- `GET /api/admin/audit/blocked-ips` — IP attualmente bloccati
- `POST /api/admin/audit/unblock-ip` — sblocco manuale admin (audit logged)
- Rate limit aggiunto: rotate-master-key (2/min), migrate-to-v2 (3/min)

**Frontend** `pages/AuditPage.js` (NEW):
- Route `/settings/audit` (admin only)
- Filtri periodo (1/7/30/90 gg) + checkbox "solo eventi security"
- 5 stat box (eventi totali, login falliti, IP unique, critical, warning)
- Card "IP bloccati" con dettaglio reason + unlock_at + pulsante Sblocca manuale
- Card "Top IP per accessi" (10 IPs)
- Breakdown bar charts: eventi per azione + per severity (con color coding)
- Tabella ultimi 500 eventi: timestamp, action, severity, user, IP, resource, esito
- Voce "Audit & Security Events" aggiunta in Settings

**Test E2E in-session**:
- HIBP check: password "password" → score 0, pwned_count=52,256,179, refused ✓
- HIBP check: password forte 16 char → score 85, pwned_count=0, ok ✓
- Brute force: 22 tentativi `hacker[1-22]@evil.com` → tutti loggati come
  LOGIN_FAILED warning, slowapi rate-limit triggered (10/5min) ✓
- Audit dashboard renderizzata: 168 eventi 7gg, 22 failed login visibili,
  top 5 IP listati, breakdown azione/severity ✓

## 2026-04-30 — Encryption Hardening NIST 2024 (backend v3.5.33)

### 🔐 Schema cifratura v2 con backward-compat
Hardening della cifratura credenziali allineato a NIST SP 800-132 rev. 2024 + audit
detection + master key rotation a runtime senza downtime.

**Backend** `security.py` (riscritto):
- **Salt random per deployment**: 32 byte CSPRNG persistito in
  `data/encryption_salt.bin` (mode 0600), generato al primo avvio post-update.
  Risolve la nota legacy "use unique salt per deployment".
- **PBKDF2-HMAC-SHA256 600k iterazioni** (era 100k) — allineato NIST 2024.
- **Versioned ciphertext**: blob v2 hanno prefisso `"v2:"`, blob senza prefisso
  sono trattati come legacy v1 (salt fisso, 100k) e decifrabili in lettura.
- **Failed-decrypt counter**: tiene traccia di tentativi fallita di decrypt;
  emette `SECURITY_ALERT decrypt_failed_burst` nei log audit dopo 3 fallimenti
  in 60 secondi — pronto per ingestione SIEM/SOC engine.
- API `is_v2_ciphertext()`, `reencrypt_to_v2()` per migration tooling.

**Backend** `routes/security_admin.py` (NEW):
- `GET /api/admin/security/encryption-status` — scansione tutte le collection,
  conta blob v2 vs v1 vs invalid, breakdown per `collection.field`.
- `POST /api/admin/security/migrate-to-v2` — re-encrypt in-place dei blob
  legacy v1 → v2. Idempotente, atomico per documento. Audit log.
- `POST /api/admin/security/rotate-master-key` — rotazione master key:
  pre-flight decrypt di TUTTI i blob, generazione nuova ENCRYPTION_KEY
  (32 byte hex CSPRNG) + nuovo salt random, rebuild SecurityManager
  in-process, re-encrypt di tutti i blob, scrittura atomica `backend/.env`
  (con backup `.bak`). Richiede `confirm=true` + 2FA admin (se attivo).

**Frontend** `pages/EncryptionPage.js` (NEW):
- Route `/settings/encryption` (admin only)
- Card "Stato cifratura" con badge percentuale v2, 4 stat box,
  banner amber se serve migration (con CTA "Migra ora"), banner emerald se
  100% v2
- Breakdown collapsible per `collection.field`
- Card "Rotazione master key" con dialog modal di conferma + campo TOTP
- Voce "Cifratura & Master Key" aggiunta in Settings

**Test E2E in-session** (con dati reali):
1. Salt v2 generato al primo avvio: `data/encryption_salt.bin` mode 0600 ✓
2. Backward-compat: blob legacy v1 (Hornetsecurity API key) decifrabile → 4377
   workload tornati ✓
3. Migration v1→v2: 2/2 blob migrati, 100% v2 post-migration ✓
4. Rotation key: nuova master key generata, .env aggiornato atomicamente,
   2/2 blob re-cifrati con nuova key, decrypt continua a funzionare ✓
5. Alert burst: 3 decrypt fallite consecutive → SECURITY_ALERT in audit log ✓

**Standard di compliance allineati**:
- NIST SP 800-38D (AES-GCM) — già presente
- NIST SP 800-132 rev. 2024 (PBKDF2 600k iter) — NUOVO
- OWASP ASVS L2/L3 (encryption at rest) — già presente
- ISO 27001 A.10.1.1 (cryptographic policy) — già presente
- ISO 27001 A.10.1.2 (key management) con rotation — NUOVO

## 2026-04-30 — Tenant→Client Mapping Reverse View (backend v3.5.32)

### 🔄 Modalita` "Per tenant Hornetsecurity"
Aggiunta vista alternativa per il mapping cliente↔tenant: tabella centrata sui
44 tenant Hornetsecurity rilevati, con dropdown "Associa cliente ARGUS" per
ciascuno. Piu` rapida quando hai molti tenant da mappare (vs flow per-cliente).

**Frontend** `pages/HornetsecuritySettingsPage.js`:
- Nuovo toggle vista: **"Per tenant Hornetsecurity"** (default) | "Per cliente ARGUS"
- Componente `TenantMappingTable` con:
  - Filtri: Tutti / Da mappare / Mappati / Con backup falliti
  - Colonne: Tenant + dominio + workload count + falliti + cliente associato + azioni
  - Auto-suggerimento cliente Argus (★ in dropdown) per nome simile/identico
  - Edit inline con `<select>` (lista clienti ordinata, suggested in cima)
  - Action button "Associa" (se non mappato) o "Modifica/Cestino" (se mappato)
  - Reverse mapping internamente: tenant → client_id derivato dalla lista mappings
- Componente `TenantMappingRow` gestisce add/remove tenant da clients in modo
  transazionale: rimuove dal vecchio cliente + aggiunge al nuovo

## 2026-04-30 — Hornetsecurity Global Config + Tenant Mapping (backend v3.5.31)

### 🌍 Refactor a config globale + mapping multi-tenant
Una sola API key copre tutti i tenant del partner Hornetsecurity (1 chiamata API
ogni 30 min vs N chiamate per cliente). Mapping cliente ARGUS ↔ tenant
Hornetsecurity multi-valore con auto-suggest fuzzy.

**Backend** `routes/hornetsecurity_backup.py`:
- Nuova collection `hornetsecurity_global_config` (singolo doc `_id="global"`)
- Endpoint admin: `GET/PUT/DELETE /api/admin/hornetsecurity/global-config`,
  `POST /api/admin/hornetsecurity/test`, `POST /api/admin/hornetsecurity/poll`,
  `GET /api/admin/hornetsecurity/tenants` (lista tenant con stats aggregate)
- Endpoint mapping: `GET/PUT /api/clients/{id}/backup/hornetsecurity/mapping`
  salva `clients.hornetsecurity_tenants` (lista nomi tenant)
- Funzione `_resolve_client_tenants()`: filtro a lettura tramite mapping
- `_persist_poll_results_global()`: persistenza globale (chiave: tenant + workload_id)
- Parser aggiornato per layout reale Hornetsecurity Operational Report:
  `{statistics: [{customerName, office365Organisation, objectTypeBackedUp,
  objectName, objectDetails, backupState, backupStateEnum, lastBackup,
  lastErrorMessage}]}`
- Status mapping: Protected→success, Last Backup Failed→failed,
  First Backup In Progress→in_progress, Excluded→excluded,
  No <workload>→not_applicable
- Backward compat: endpoint per-cliente legacy mantenuti

**Backend** `services/hornetsecurity_poller.py`:
- Tick gestisce sia config globale (preferita) che config per-cliente legacy
- Solo "failed" reali generano alert (non "not_applicable" / "excluded" /
  "in_progress")

**Frontend** `pages/HornetsecuritySettingsPage.js` (NEW):
- Pagina admin Settings → Hornetsecurity 365 Backup
- Connessione API (URL + key cifrata + polling interval) con Test/Poll Now
- Tabella mapping clienti ARGUS ↔ tenant: dropdown multi-select con
  auto-suggest fuzzy (nome cliente vs nome tenant)
- Sezione "tenant non mappati" per scoprire clienti Hornetsecurity senza
  controparte ARGUS
- Stats real-time per tenant: workload totali, falliti, protetti

**Frontend** `pages/ClientOverviewPage.js` (BackupTab refactor):
- Ora legge config globale invece di per-cliente
- Stati: backend obsoleto / config assente (CTA Settings) / mapping mancante
  (CTA mapping) / dati visibili
- Filtro multi-tenant nella pagina cliente (utile per clienti con piu` domini)

**Risultato test E2E con dati reali utente**:
- 4377 workload, 44 tenant rilevati, 196 backup falliti reali, 1231 protetti
- Mapping cliente ↔ tenant "Aldegani" → 111 workload filtrati correttamente
- Storage trend non disponibile (Operational Report Hornetsecurity non include
  size per workload — limite del prodotto)

## 2026-04-30 — Hornetsecurity 365 Total Backup Integration (backend v3.5.30)

### 🛡️ Fase 1 — Cloud Microsoft 365 Backup Monitoring
Integrazione end-to-end con Hornetsecurity 365 Total Backup REST API (custom-generated
endpoint + X-API-KEY header), per monitorare backup di Mailbox, OneDrive,
SharePoint, Teams attraverso tutti i tenant clienti registrati nel Control Panel MSP.

**Backend** `routes/hornetsecurity_backup.py` (NEW):
- `GET/PUT/DELETE /api/clients/{client_id}/backup/hornetsecurity/config` — CRUD
  configurazione per cliente. API key crittografata via `security_manager` (Fernet)
  e mai esposta in chiaro. Mostrata UI come `****1234`.
- `POST /api/clients/{client_id}/backup/hornetsecurity/test` — chiamata di test
  senza persistenza, ritorna count workload + sample.
- `POST /api/clients/{client_id}/backup/hornetsecurity/poll` — forza polling
  immediato (rispetta rate limit 5min Hornetsecurity, ritorna 429 se troppo presto).
- `GET /api/clients/{client_id}/backup/hornetsecurity/status` — lista ultimi
  workload + aggregati per status/type + count alert attivi.
- `GET /api/clients/{client_id}/backup/hornetsecurity/storage-trend?days=N` — trend
  storage per tenant negli ultimi N giorni (default 30).
- `GET /api/clients/{client_id}/backup/hornetsecurity/alerts` — alert backup falliti.
- Parser JSON robusto su 3 layout possibili (camelCase nested, PascalCase flat,
  generic data array). Verificato in unit test in-session.

**Backend** `services/hornetsecurity_poller.py` (NEW):
- APScheduler job ogni minuto che itera `hornetsecurity_configs`, calcola se
  `poll_interval_minutes` è scaduto da `last_polled_at`, esegue HTTP GET e
  persiste workload/storage/alert.
- Auto-deduplicate alerts: 1 alert aperto per workload, auto-resolve quando lo
  status torna success.
- Failed-poll tracking: salva `last_poll_status` + `last_poll_error` per UI.

**MongoDB collections** (NEW):
- `hornetsecurity_configs` — { client_id, api_url, api_key_enc, poll_interval_minutes, enabled, last_polled_at, last_poll_status }
- `backup_job_status` — { client_id, tenant, workload_id, workload_type, status, last_backup_time, size_bytes, error, captured_at }
- `backup_storage_history` — { client_id, tenant, size_bytes, recorded_at }
- `backup_alerts` — { client_id, tenant, workload_id, severity, message, resolved, last_seen }

**Frontend** `ClientOverviewPage.js`:
- Tab **Backup** completamente riprogettata:
  - Setup wizard se non configurato (CTA con istruzioni Control Panel)
  - Header config con URL mascherato, key preview, polling interval, last poll
  - 4 stat box (OK, Failed, Active alerts, Workload types)
  - Storage trend card per tenant con delta % e size in MB/GB/TB
  - Filtri stato + tipo workload (mailbox/onedrive/sharepoint/teams)
  - Tabella workload con stato colorato, last backup, size, error message
- Pulsanti "Poll Ora" + "Test" + "Modifica" + "Elimina" con permission check admin
- Dialog config: URL + key (password input) + polling interval + enabled
- Fallback graceful se backend non aggiornato (banner amber con istruzioni update)

**Rate limit safety**:
- Schedule minimo 5 min, default 30 min
- Anti-flood manuale 300s tra `/poll` consecutivi
- HTTP 429 esplicito al frontend con messaggio chiaro

## 2026-04-30 — Profile Re-match Engine (backend v3.5.29)

### 🎯 Auto-aggancio profili vendor dopo fix SNMP
Risolve il caso in cui i device erano stati ingestati prima che lo SNMP funzionasse
correttamente (sysObjectID/sysDescr vuoti): ora che i metadati arrivano popolati, il
fingerprint veniva saltato perché il matcher richiedeva `prev_status is None`.

**Backend** `routes/connector.py` (device-report ingest):
- Retry policy estesa: il fingerprint si attiva ora anche quando `profile_key`
  è assente E il device ha un identificatore (sys_object_id o sys_descr). NON
  sovrascrive profili impostati manualmente (`profile_auto_matched=false`).
- Log esplicita la ragione: `[new]` | `[descr-changed]` | `[missing-profile-retry]`

**Backend** `routes/devices.py` — nuovi endpoint:
- `POST /api/clients/{client_id}/rematch-profiles` — bulk rematch su tutti i device
  del cliente. Ritorna summary `{total, matched, skipped, details[]}`.
- `POST /api/clients/{client_id}/devices/{device_ip}/rematch-profile` — rematch
  singolo device.
- Funzione interna `_rematch_one()` con safety: skip profili manuali, skip device
  senza identificatori.

**Frontend** `ClientOverviewPage.js`:
- Nuovo pulsante **"🔎 Riconosci profili"** (cyan) accanto a "Rimuovi scomparsi",
  chiama il bulk endpoint e mostra toast dettagliato con nomi/vendor matchati.

**Fingerprint verification** (unit test in-session):
- Switch HP 5130 EI (sysObjectID 1.3.6.1.4.1.11.2.3.7.11.161) → `hpe_comware` ✓
- UPS Xanto S 3000 (sysDescr) → `xanto_ups` ✓
- Synology NAS DSM 7.2 → `synology_dsm` ✓

## 2026-04-30 — Self-Updater hardening P1 (backend v3.5.28)

### 🔧 Fix definitivo loop 404 aggiornamento backend in produzione
**Backend** `routes/system_admin.py`:
- Nuova funzione `_resolve_package_url()`: risolve URL del tarball in cascata
  1. `payload.package_url` (custom) → 2. `https://{host}/downloads/...` (locale) → 3. `ARGUS_UPDATE_ARTIFACT_BASE_URL` (fallback remoto)
- Nuova funzione `_head_check()`: HEAD preflight con validazione content-length > 100 KB
  (intercetta le pagine HTML di errore servite come 200)
- `POST /api/admin/system/self-update` fa ora il **preflight check PRIMA** di spawnare
  il subprocess; se l'URL non è raggiungibile ritorna `424 Failed Dependency` con
  messaggio esplicito (prima restava bloccato 10s dentro `curl` del runner)
- Auto-retry sul fallback remoto se il locale fallisce (e env var è configurata)
- Nuovo endpoint `GET /api/admin/system/self-update/resolve-url?url=...`:
  mostra URL risolto, sorgente, reachable, HTTP status, content-length
- Risposta `/version` ora include `update_artifact_fallback` per UI

**Frontend** `WireGuardPage.js`:
- Dialog self-update: nuovo pulsante **"Pre-check URL"** che valida raggiungibilità
  prima di lanciare l'update, con toast dettagliato (size MB / HTTP status)
- Toast post-avvio mostra la sorgente risolta: "custom", "CDN locale" o
  "fallback CDN remoto"
- Nota esplicativa aggiornata con l'ordine di risoluzione + env var corrente

**Env var opzionale** (P1 rollout):
- `ARGUS_UPDATE_ARTIFACT_BASE_URL=https://<cdn>`: base URL fallback per artefatti
  quando il CDN locale non è ancora sincronizzato

## 2026-04-27 — Silence Alerts + Printer auto-classify + Cleanup bidirezionale
- Flag `alerts_silenced` su device, intercettato da 8 watcher backend
- Auto-classifier stampanti via regex + Printer-MIB sysObjectID
- `/sync-active-devices` (HMAC) + `/cleanup-stale-devices` per pulizia bulk
- Fix cestino unificato (poll_ip multi-source)
- Connector v3.5.25 con heartbeat reverse-sync

## 2026-04-22 — FASE B COMPLETATA: Vendor-Specific SNMP Monitoring + RMT HTTP Polling

### 🚀 Fase B — Vendor Alerts (Connector v3.4.4)
**Backend** `routes/connector.py`:
- `_check_device_thresholds` esteso con block Fase B (righe ~770-900)
- Alert auto-generati da `vendor_metrics`:
  - **Synology**: `raidStatus` (11=Degraded, 12=Crashed), `diskTemperature` (table walk)
  - **APC UPS**: `upsBatteryStatus` (3=Low, 4=Depleted), `upsOutputSource` (5=On Battery), `upsEstimatedChargeRemaining` %
  - **Fortinet**: `fgVpnTunnelStatus` (table, 1=down), `fgHaStatsSyncStatus` (0=out-of-sync)
- `vendor_metrics` salvato in `device_poll_status` per frontend
- Backend check fallback senza profilo: alert RAID/UPS critical sempre generati

**Connector v3.4.4** (SHA `c8b14ac3...06262d4`, 297 KB):
- Nuova funzione `Poll-VendorOids` in `connector.ps1`
- Legge `$dev.vendor_snmp_targets` (scalars + tables) dal heartbeat
- Esegue `Get-SnmpValue` per scalars, `Get-SnmpWalk` per tables
- Allega risultati come `vendor_metrics` in `/connector/device-report`
- Testato end-to-end via curl: 4 alert creati correttamente

### 🖥️ RMT HTTP Polling (connector v3.4.3)
- `routes/console_rmt_v2.py` — endpoint header-based auth (bypass WAF path issues)
- `routes/console_rmt_http.py` — SSE + polling fallback
- `RemoteBrowserModal.js` — EventSource + axios polling, canvas HTML5
- `remote_browser.ps1` — Edge CDP headless screencast, 2 runspace (CDP reader + input poller)
- Fix Edge SYSTEM service: `--no-sandbox`, `--disable-dev-shm-usage`, user-data-dir in `C:\Windows\Temp`

### 🔧 Fix stabilità precedenti
- `Register-ServiceWatchdog` auto-recovery (v3.3.7)
- Regex HTML5 unquoted per inline CSS/JS (v3.3.6)
- Install-Update 4 metodi fallback + verifica PID-alive (v3.3.6)

## ⏭️ Prossimi step backlog
- **UI Dashboard per vendor_metrics**: pagine device-details con tab Volumi/RAID (Synology), Battery/Load (UPS), VPN/HA (Fortinet)
- **Notifiche Telegram/Email** per alert vendor-specific
- **Analytics MTTA/MTTR/MTTD**
- **Multi-tenant white-label**
- **Vulnerability Assessment CVE/EoL**

## 📅 Storia precedente
Vedi PRD.md per Web Console V4, Device Profiles 13-vendor, Runbook Auto-Match, Dynamic Port Whitelist.
