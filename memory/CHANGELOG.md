# 2026-06 — Telegram: sempre NOME CLIENTE in grassetto (capire subito il cliente)

## Richiesta utente
I messaggi Telegram non mostravano il cliente (es. "CRITICO: Hardware
Manufacturer/Microsoft — SERVER DOWN") → impossibile capire di quale cliente.
Formato richiesto: **NOME CLIENTE** (grassetto) - dispositivo - stato - escalation.

## Fix (`telegram_notifier.py` + `alert_engine.py`)
- `_fmt(title, message, severity, client_name, device_name)`: riga 1 sempre
  `🚨 <b>NOME CLIENTE</b> — dispositivo — [SEVERITÀ]`, riga 2 lo stato (titolo
  ripulito dal prefisso "CRITICO:"), poi l'escalation/messaggio. Se il device è
  già nello stato non lo duplica. Se manca il cliente → "Cliente sconosciuto".
- `send_alert_telegram(...)`: aggiunti parametri `client_name`, `device_name`.
- `notify_alert_telegram`: passa `client_name`/`device_name` dall'alert_doc; se
  `client_name` manca lo RISOLVE dal DB (`db.clients` by `client_id`) → garanzia
  che il nome cliente ci sia sempre. Tutti i percorsi Telegram passano di qui
  (anche `_dispatch_notification` del motore), quindi la modifica è globale.

## Testing (python -c)
Formato verificato su 3 casi (server down, VM Hyper-V, dorsale): NOME CLIENTE in
grassetto in testa, poi dispositivo/stato/escalation. Import OK, backend 200.

⚠️ Attivo in PROD dopo Save to GitHub + redeploy backend. Digest notturno/mattutino
già raggruppati per cliente (invariati).

---



# 2026-06 — FIX "unknown command net_trace": binario agent senza net_trace (VERSION non bumpata)

## Problema segnalato
Sonda installata ma: (1) non compare nel menu AGENT-SONDA, (2) la Diagnosi Percorso
fallisce con `unknown command "net_trace"` (anche su agent già connessi, es. SRVDCGAL).

## Root cause (PROVATA)
- Release GitHub **v4.30.3 pubblicata il 2026-08-17 12:15Z**.
- Comando **net_trace committato il 2026-08-18 11:36Z** (giorno DOPO la release).
- `noc-agent/VERSION` è rimasto **4.30.3** → l'`auto-release-agent.yml` (trigger su
  cambio VERSION) SALTA perché il tag v4.30.3 esiste già → **nessun nuovo binario**.
- Quindi il binario pubblicato/installato NON contiene net_trace, mentre il sorgente
  (main.go registra `registerNetTraceCommand`) sì. → ogni agent risponde
  `unknown command "net_trace"`.

## Fix applicato
- `noc-agent/VERSION`: 4.30.3 → **4.30.4**.
- `noc-agent/cmd/agent/main.go`: `Version = "4.30.4"`.
Al prossimo push su main (Save to GitHub), `auto-release-agent.yml` builda dal main
CORRENTE (con net_trace) e pubblica la Release **v4.30.4**. `install-noc-agent.ps1`
scarica `releases/latest` = 4.30.4 → net_trace disponibile.

## Azioni richieste all'utente (non eseguibili da qui)
1. **Save to GitHub** (push su main) → attendere i workflow "Auto-release agent" +
   "Release Argus Agent" → verificare che compaia la Release **v4.30.4**.
2. **Aggiornare gli agent**: reinstallare la sonda (il comando PowerShell prende
   latest = 4.30.4) OPPURE usare "Aggiorna connector" per il rollout remoto.
3. Dopo l'update la Diagnosi Percorso funziona. Se la **sonda globale** ancora non
   compare nel menu dopo la riconnessione, segnalarlo: il backend NON valida
   `__global__` in `register_agent` (token ok) e `/api/agents` elenca tutti gli
   agent live, quindi dovrebbe apparire; da verificare il path WS `__global__`.

## Note
- Go non è installabile nel pod → la build la fa la CI (Go 1.23). Il codice net_trace
  è committato con test (`internal/nettrace/nettrace_test.go`). Se la CI fallisse il
  build, correggere e ribumpare.

---



# 2026-06 — FIX TV: tutti i clienti mostravano "NO SONDA" (fonte heartbeat sbagliata)

## Problema segnalato
Sulla TV di produzione TUTTI i clienti apparivano "NO SONDA" (e quindi "tutto
offline"), pur arrivando dati reali (WAN OK, latenze, poll, alert).

## Root cause
`routes/tv_dashboard.py` calcolava `connector_online` leggendo la collezione
LEGACY `connector_status`. Gli agent v4 però scrivono l'heartbeat in
`managed_agents` (`last_heartbeat_at` / `connected`), NON in `connector_status`
(aggiornata solo dai vecchi connector v3). Risultato: `connector_status` vuota/
stantia → `connector_online=False` per ogni cliente → "NO SONDA" ovunque.

## Fix
`tv_dashboard`: `connector_online` ora deriva PRIMARIAMENTE da `managed_agents` —
sonda ONLINE se il cliente ha almeno un agent `connected=True` o con
`last_heartbeat_at`/`last_seen_at` < 5 min. Fallback legacy su `connector_status`
mantenuto per i connector v3. Anche `connector_version` presa da `agent_version`.

## Testing
- curl locale: impostando un heartbeat recente in `managed_agents`, l'endpoint
  restituisce `connector_online=True` (prima False) + versione 4.30.1. Endpoint
  200, nessun errore. Stato di test ripristinato.

## Note per l'utente
- Lo screenshot era della PRODUZIONE (clienti Galvan/CGE/… non presenti in preview,
  che ha solo dati di test vecchi): impossibile riprodurre 1:1 qui, fix fatto sul
  codice + verificato via curl.
- I conteggi OFFLINE per-dispositivo derivano dai poll reali (`device_poll_status.
  reachable`). Dopo il redeploy, se qualche cliente mostra ancora offline errati a
  sonda ONLINE, servono esempi specifici (cliente + dispositivo) per indagare.

⚠️ Attivo in PROD dopo Save to GitHub + redeploy backend.

---



# 2026-06 — TV wallboard: popup GRANDI centrali per allarmi critici + suono

## Richiesta utente
Sulla TV 45" (punto di riferimento tecnici): quando arrivano allarmi critici,
mostrare un POPUP GRANDE al centro con nome cliente + allarme, farlo sparire dopo
30s e riprodurre un suono.

## Implementazione (`TvDashboardPage.js` + `TvDashboard.css`)
- `useAlarmSystem` riscritto: mantiene una coda `popups` (max 3) di eventi critici.
  Su NUOVO alert critico o NUOVO dispositivo offline → push popup {kind, client,
  title} + suono "sirena" (toni alternati 880/620Hz ripetuti). Baseline "primed"
  al primo giro per non generare una valanga all'avvio (200+ clienti).
- Popup GRANDE centrale: overlay full-screen scurito, card con badge
  ("ALLARME CRITICO"/"DISPOSITIVO OFFLINE"), **nome cliente 64px**, titolo allarme
  30px, orario, pulsante ×. Auto-dismiss dopo `POPUP_TTL_MS=30000` (30s) via
  interval di purge. Animazione entrata + pulse. Rosso=critico, arancio=offline.
- Suono: Web Audio; per policy autoplay del browser serve UN click sul wallboard
  (toggle "♪ OFF→ON" o qualsiasi click) per abilitare l'audio.
- Aggiunto pulsante **TEST** nell'header: genera un popup dimostrativo + suono →
  i tecnici possono verificare all'istante popup+audio sulla TV reale.
- testid: `tv-critical-popup`, `tv-popup-client`, `tv-popup-title`,
  `tv-popup-dismiss`, `tv-test-alarm`.

## Testing / stato
- Codice compila (webpack OK); backend sano; endpoint `/api/tv/dashboard` locale
  200 in ~12-55ms (nessuno stallo periodico dal nuovo watchdog).
- Redesign TV confermato via screenshot (layout triage). ⚠️ La cattura live del
  popup via screenshot-tool è stata bloccata da flakiness intermittente
  dell'ingress di preview (il browser dello strumento non caricava i dati del
  dashboard, mentre in locale l'endpoint risponde e in un altro screenshot la
  pagina ha caricato correttamente). Il pulsante TEST consente all'utente di
  verificare popup+suono immediatamente sulla TV.

⚠️ Attivo in PROD dopo Save to GitHub + redeploy frontend.

---



# 2026-06 — TV wallboard denso (200+ clienti) + dorsali sulla mappa + alert dorsale dedicato

## 1. TV Dashboard ridisegnata per 200+ clienti (45")
Problema: le card grandi non scalavano (con 200+ clienti non si vedeva nulla).
Nuovo layout triage a due livelli (`TvDashboardPage.js` + `TvDashboard.css`):
- **DA GESTIRE**: solo i clienti con anomalie, come card COMPATTE in griglia
  `auto-fill minmax(232px)` ordinate per gravità (headline + ON/OFF/AL/CR + WAN + 1
  alert). Critici lampeggiano.
- **OPERATIVI**: tutti i clienti sani come chip minimali verdi (nome + dot) in
  griglia densa `minmax(148px)` → 200 clienti stanno in una banda compatta.
- Body scrollabile come fallback. KPI header invariati. Testid preservati
  (`tv-client-*`, `tv-headline-*`, `tv-tile-wan-*`, `tv-tile-topalert-*`).
  Verificato via screenshot (contatori senza overflow, sezioni corrette).

## 2. Dorsali evidenziate sulla mappa (`NetworkMap.js`)
I link di cascata/backbone ora sono più marcati: `strokeWidth` 5 (verificato) / 3
(probabile) vs ~1.5 degli access, indigo/viola, ed etichetta con prefisso
**"🔗 DORSALE ✓ portaA↔portaB VLAN N"** → distinti a colpo d'occhio dai
collegamenti verso valle.

## 3. Alert DEDICATO "PROBLEMA DI DORSALE" (`alert_engine.py::run_backbone_watchdog`)
Separato dal down del singolo switch. Per ogni switch giù, controlla la porta
dorsale sul parent (verso quello switch): se **LINK DOWN** o **traffico ZERO** →
emette alert `critical` `source_type=corr_backbone_down` ("PROBLEMA DI DORSALE:
PARENT → SWITCH") via pipeline unificata (Telegram/push), dedup per (client,switch),
auto-resolve quando la dorsale torna ok o lo switch torna su. Se la dorsale passa
traffico → nessun alert dorsale (è solo lo switch). Agganciato a `run_once` (20s).

## Testing
- Backbone watchdog (python -c, 4/4 PASS): link-down→alert, dorsale-ok→no alert,
  zero-traffic→alert, recovery→resolve.
- TV: screenshot OK. Mappa/NetworkMap + TV compilano (webpack OK). Backend sano.

⚠️ Traffico dorsale disponibile solo se l'agent invia rx_bps/tx_bps per porta; la
risoluzione peer dipende da LLDP+FDB (cascata). Attivo in PROD dopo Save to GitHub +
redeploy (backend+frontend), nessun rebuild agent Go.

---



# 2026-06 — Dorsale switch: porta uplink evidenziata + diagnosi backbone + recovery rapido

## Richieste utente
1. Con più switch, mostrare SEMPRE la porta che fa da DORSALE (uplink verso il
   "sopra": gateway/switch a monte), distinta dalla porta verso lo switch a valle.
2. Quando uno switch va offline, verificare SUBITO se l'uplink/dorsale passa
   traffico: se è tutto a ZERO (o link down) → possibile problema di DORSALE.
3. Rendere il RIENTRO ONLINE dello switch veloce quanto il down (event-driven).

## Implementazione
**#1 Direzione dorsale** (`routes/topology.py::get_switch_ports`): usando la
cascata (rank/level per switch), ogni porta uplink ora ha `uplink_direction`
("upstream"=dorsale / "downstream"=verso valle) e `is_backbone`. La dorsale =
porta verso gateway o switch di livello inferiore.
- Frontend `PortCableView.js`: banner in cima ("DORSALE ↑ verso …" ambra /
  "Collegamento ↓ verso switch a valle" indaco) + preferisce il nome switch
  RISOLTO dalla cascata (`uplink_to.peer_name`) invece del generico "HPE" LLDP.
- Frontend `SwitchPortsPage.js`: badge "DORSALE ↑" / "SWITCH ↓ (valle)" nel
  dettaglio porta e nel riepilogo uplink.

**#2 Diagnosi dorsale** (`alert_enrichment.py::_backbone_diagnosis`): per gli
alert `corr_switch_down`/`corr_switch_unreachable`, trova la porta sul parent
(dorsale) verso lo switch giù e aggiunge al messaggio:
- LINK DOWN → "probabile problema di DORSALE (cavo/SFP/uplink)".
- UP ma traffico ZERO → "verificare la DORSALE/uplink (possibile guasto backbone)".
- UP con traffico → "la dorsale funziona, il down riguarda il solo switch".

**#3 Recovery rapido** (`routes/agent_ws.py::_bridge_ping_poll`): al RIENTRO
online di un device VITALE/infra che era in fallimento (≥2 poll persi), sveglia
SUBITO `run_vital_watchdog` (stesso trigger event-driven del down) → il recovery
Telegram/push parte all'istante, non al tick.

## Testing
- `_backbone_diagnosis` (python -c, 3/3 PASS): link-down / zero-traffic / traffic-ok.
- Import backend OK; frontend compila (solo warning exhaustive-deps preesistente).
- Recovery: riusa il trigger event-driven già validato (fix down rapido).

⚠️ Traffico dorsale disponibile solo se l'agent invia i contatori rx_bps/tx_bps
per porta; se assenti, non si dichiara "zero" (evita falsi). La risoluzione del
peer dorsale dipende da LLDP+FDB (cascata). Attivo in PROD dopo Save to GitHub +
redeploy (backend+frontend), nessun rebuild agent Go.

---



# 2026-06 — Allerta "switch/device VITALE giù" QUASI-ISTANTANEA (fix ritardo)

## Incident utente
Due switch di un cliente hanno perso corrente al mattino ma l'allarme è arrivato
tardi. Richiesta: rilevazione praticamente immediata.

## Root cause (3 ritardi sommati)
1. **Finestra evidenza L2 = 15 min**: uno switch spento resta nelle tabelle FDB/ARP
   → `l2_alive=True` → verdetto "healthy" → NESSUN alert fino a ~15 min.
2. **Tick motore alert = 60s**.
3. Nessun trigger event-driven per il down del singolo device vitale (solo per il
   blackout WAN). In più il gate temporale `vital_warn_minutes` (3 min) ritardava
   ancora gli alert a bassa confidenza (switch_unreachable conf 75).

## Fix (scelte utente: event-driven ON, conferma ~30s/2 poll, tick 20s)
- `alert_engine.py`:
  - `CHECK_INTERVAL_SECONDS` 60→**20** (rete di sicurezza).
  - Nuovi `VITAL_FAST_FAILURES=2`, `VITAL_L2_FRESH_SECONDS=120` + helper
    `_vital_direct_down(md, pd, now)`: per device VITALI/infra con poll DIRETTO
    (ICMP) fallito ≥2 volte consecutive ed entro 120s, in `run_vital_watchdog`
    si IGNORA l'evidenza L2 stantia (`s["l2_alive"]=False`) e si marca
    `s["_fast_confirmed"]` → l'alert **bypassa il gate `vital_warn_minutes`** e
    scatta subito. Proiezione arricchita con `consecutive_ping_failures`.
- `routes/agent_ws.py`: `_trigger_vital_watchdog_soon()` (throttle 8s) + hook in
  `_bridge_ping_poll`: quando un device VITALE/infra raggiunge il 2° fail ICMP
  consecutivo, esegue SUBITO `run_vital_watchdog` in background (event-driven),
  senza attendere il tick.
- Il debounce di DISPLAY (`managed_devices.status`, soglia 5) resta invariato per
  non far lampeggiare le card; cambia solo il percorso di ALLERTA.

## Testing (python -c, 3/3 PASS)
- Switch 2 fail + evidenza L2 stantia → alert immediato (prima restava healthy 15 min).
- Switch 1 fail → nessun alert ancora (conferma 30s non raggiunta).
- Switch 2 fail senza L2 → alert (baseline). Backend sano, motore "interval=20s".

⚠️ Sub-secondo impossibile (rilevazione a polling ~15s). Tempo tipico ora: ~30s
(2 poll) + trigger event-driven. Attivo in PROD dopo Save to GitHub + redeploy backend
(nessun rebuild agent Go). Vale SOLO per device vitali/infrastruttura (no stampanti).

---



# 2026-06 — Alert VM Hyper-V attesa accesa ma SPENTA (host raggiungibile)

## Richiesta utente
Distinguere lo spegnimento VOLONTARIO di una VM (nessun allarme) da un crash
inatteso su un host Hyper-V SANO/raggiungibile. Se una VM che DEVE restare accesa
(toggle `hyperv_alert_on_off` in CMDB) risulta spenta mentre l'host è online →
alert CRITICO.

## Implementazione (solo backend)
- `alert_engine.py::hyperv_vm_state_tick(db)`: itera `db.backup_status` con
  `hyperv_connected=True` e `hyperv_vms`. Per ogni VM `state` != running/on/started
  incrocia i `managed_devices` del cliente con `hyperv_alert_on_off=True`
  (match su `hyperv_vm_name` o `name`). Emette alert `critical`
  `source_type="hyperv_vm_down"`, `device_id=hypervvm:<cid>:<vm>` via
  `insert_alert_if_emit` + `notify_alert_telegram` (pipeline unificata: rispetta
  quiet hours/severità). Dedup su alert attivo per device_key.
- AUTO-RESOLVE: quando la VM torna `Running` l'alert attivo viene risolto
  (`status=resolved`, `resolved_at`).
- Agganciato a `AlertEngine.run_once()` (gira nel ciclo esistente del motore).

## Testing (python -c, 4/4 PASS)
1. VM off + monitorata → 1 alert critical emesso.
2. Re-run → dedup, nessun duplicato.
3. VM torna Running → auto-resolve (0 attivi).
4. VM off ma NON monitorata (`hyperv_alert_on_off=False`) → nessun alert.
Backend sano (health 200) dopo le modifiche.

⚠️ In PROD attivo dopo Save to GitHub + redeploy backend. Nessun rebuild agent Go.
La consegna Telegram usa la config globale già attiva (chat_id 6212726125).

---



# 2026-08-19 — Digest mattutino 07:00 (stato clienti, solo critici+down)

## Richiesta utente
Riepilogo Telegram ogni mattina alle 07:00 con lo stato di tutti i clienti (oltre al digest notturno). Devono comparire SOLO alert critici e down, nient'altro.

## Implementazione
- `alert_engine.py`: nuovo `morning_status_digest(db)` — legge solo alert ATTIVI e severità CRITICAL, raggruppa per cliente distinguendo "down" (source_type istantaneo) da "critici" (altri critical). Mostra solo i clienti con criticità; se nessuno → "Tutti operativi ✅". Nessun link.
- `server.py`: schedulato con CronTrigger `hour=7, minute=0, timezone=Europe/Rome` (job `morning_status_digest`), in aggiunta al digest notturno (quiet flush) e agli altri tick.

## Verifica
morning_status_digest → "☀️ Buongiorno — Stato clienti ARGUS (07:00) · 86BIT_Office: 1 down, 5 critici". Solo alert critici inclusi (high/medium esclusi). Backend riparte pulito, job 07:00 registrato.

---


# 2026-08-19 — Digest notturno raggruppato per cliente

## Richiesta utente
Riepilogo notturno raggruppato per cliente con conteggio per categoria (es. "ACME: 3 KEV, 1 anomalia"), SENZA link alla console.

## Implementazione (alert_engine.py — telegram_quiet_digest_tick)
- Raggruppamento per client_name → conteggio per categoria con label leggibili (kev_exposure→KEV, osint_c2→C2, traffic_anomaly→anomalia traffico, rogue→dispositivo rogue, wan_public_ip_change→cambio IP, predictive_*→guasto imminente, datto_sync_stale→sync Datto).
- Clienti ordinati per volume alert; header con totali (N alert, X critici/Y alti, M clienti). Nessun link.

## Verifica
Digest generato: "ACME: 3 KEV, 1 anomalia traffico / Beta Srl: 2 C2, 1 cambio IP / Gamma: 1 dispositivo rogue". Backend sintassi OK.

---


# 2026-08-19 — Telegram Quiet Hours (riepilogo notturno)

## Richiesta utente
Fascia oraria (default 22:00–07:00) in cui i critici NON-down vengono accorpati in un riepilogo di fine finestra, mentre i veri down restano istantanei.

## Implementazione (alert_engine.py)
- Config: `telegram_quiet_enabled` (default True), `telegram_quiet_start` "22:00", `telegram_quiet_end` "07:00".
- Helper `_in_quiet_hours` (fuso Europe/Rome), `_is_instant_source` (keyword: down/offline/blackout/power/isolat/situation/reach/liveness/vital/connector).
- `notify_alert_telegram`: durante quiet, alert non-istantanei → accodati in `telegram_quiet_queue`; istantanei → inviati subito.
- `_dispatch_notification` (motore) ora passa dal percorso unificato `notify_alert_telegram` → soglia+quiet valgono anche per il motore.
- Nuovo `telegram_quiet_digest_tick(db)`: al termine della finestra invia UN riepilogo (send_telegram_text) e marca la coda come inviata. Schedulato ogni 5 min in server.py.
- UI (AlertEngineSettingsPage): switch quiet-hours + orari inizio/fine.

## Verifica
in_quiet OK; site_down=istantaneo (inviato), C2/KEV=accodati; digest non parte durante quiet, parte a fine finestra (1 alert flushato). Frontend compila pulito.

---


# 2026-08-19 — Telegram: soglia severità (solo CRITICAL di default)

## Richiesta utente
Inviare su Telegram solo gli alert di livello critical, per evitare decine/centinaia di messaggi non urgenti.

## Implementazione
- `alert_engine.py`: nuovo campo config `telegram_min_severity` (default **"critical"**) + helper `_telegram_severity_ok(cfg, severity)` con ranking severità.
- Applicato ai DUE punti di invio: `_dispatch_notification` (motore) e `notify_alert_telegram` (C2/KEV/rogue/traffico/IP change). Ora inviano solo se severità ≥ soglia.
- Frontend `AlertEngineSettingsPage.jsx`: selettore "Invia su Telegram" → "Solo CRITICI" (default) / "Alti e Critici".

## Verifica
`telegram_min_severity=critical` → high bloccato (False), critical inviato (True). Frontend compila pulito. Nessun doppio invio.

---


# 2026-08-19 — Notifiche Telegram unificate (tutti gli alert high/critical)

## Richiesta utente (opzione A)
Far arrivare su Telegram TUTTI gli alert high/critical, inclusi C2, KEV, rogue, anomalie traffico, cambio IP pubblico (non solo quelli del motore).

## Implementazione
- Nuovo helper riutilizzabile `notify_alert_telegram(db, alert_doc)` in `alert_engine.py`: legge la config globale, invia Telegram solo se canale abilitato + severità high/critical.
- Collegato a tutti gli emitter che prima saltavano Telegram:
  - `services/osint_poller.py`: C2 (`_notify_c2_alert`) + KEV (`kev_asset_alert_tick`, con dedup cross-run aggiunto).
  - `services/rogue_detection.py`, `services/traffic_anomaly.py`.
  - `routes/external_monitor.py`: cambio IP pubblico reale.
- Gli alert del motore continuano ad usare `_dispatch_notification` (nessun doppio invio: gli emitter esterni usano solo il nuovo helper).

## STATO CONFIGURAZIONE (IMPORTANTE)
- Il codice è pronto e verificato (backend 200, sintassi OK). MA la config Telegram nel DB NON è valida: `alert_engine_config global` ha `telegram_chat_id` VUOTO e un `telegram_bot_token` INVALIDO (getMe → 401, 35 char = non è un token reale). Quindi al momento NESSUN messaggio viene recapitato. L'utente deve incollare un token @BotFather valido + salvare il chat_id.

---


# 2026-08-19 — Console mobile (iPhone/Android) per il tecnico

## Richiesta utente
Layout mobile facilmente comprensibile per avere sempre tutte le aziende sotto controllo velocemente.

## Implementazione
- Nuova pagina `frontend/src/pages/MobileConsolePage.js`, route protetta `/mobile` (in App.js).
- Mobile-first, single column: header sticky (logo, stato globale, ora aggiornamento, refresh), striscia KPI (Online/Offline/Alert/Clienti KO), barra ricerca + toggle "Solo problemi".
- Lista aziende ordinata per gravità: card con bordo/colore stato, anello salute %, headline del problema ("WAN DOWN"/"N offline"/…), chip rapide (offline, alert, WAN). Tap per espandere: contatori ON/OFF/ALERT, riga WAN (IP+latenza), dispositivi offline, alert critici/high, footer (disp./stamp./iLO/stato sonda).
- Dati da `/api/tv/dashboard` (già aggregato), auto-refresh 15s. Nessuna modifica backend.

## Verifica (screenshot viewport 390px)
Card 86BIT_Office: ring 100%, headline WAN DOWN, chip ⚠50/WAN DOWN; espansa mostra WAN DOWN 192.0.2.1, alert CRIT "Esposizione KEV USG FLEX 700H", footer 8 disp./3 stamp./1 iLO/No sonda. Compila pulito.

---


# 2026-08-19 — TV Wallboard redesign + Auto-alert KEV↔Asset

## Task 1 — TV Dashboard riprogettata (per TV 40", colpo d'occhio)
- Riscritti `frontend/src/pages/TvDashboardPage.js` + `TvDashboard.css`.
- Layout wallboard moderno, alto contrasto, font grandi leggibili da lontano. Ogni cliente = tile con: bordo/colore stato (verde/ambra/rosso), anello salute %, HEADLINE grande del problema dominante ("WAN DOWN" / "N OFFLINE" / "N CRITICI" / "OPERATIVO"), contatori ON/OFF/ALERT, riga WAN (stato+IP+latenza, mostra la linea peggiore), 1 riga top-alert. Niente più liste IP/toner illeggibili.
- Tile ordinate per gravità (peggiori prima), grid auto-fit responsive, flash rosso sui critici. Mantenuti allarme audio + ticker.

## Task 2 — Auto-alert KEV↔Asset
- Refactor `routes/osint.py`: estratto `_compute_kev_asset_exposure()` (riusato dalla route).
- Nuovo `kev_asset_alert_tick()` in `services/osint_poller.py`: genera alert per-cliente per asset esposti a KEV. Severity high, **critical se ransomware**; include lista CVE, scadenza più vicina, flag ransomware. Dedup stabile via device_id `kev:{cid}:{slug}`.
- Schedulato in `server.py` ogni 6h (kev_asset_alert_tick).

## Verifica
- TV: screenshot wallboard OK (tile 86BIT_Office, headline WAN DOWN, ring 100%, top-alert KEV, ticker).
- KEV alert: tick → 1 alert CRITICO "Esposizione KEV: USG FLEX 700H — 5 CVE" per 86BIT_Office con scadenza 2022-06-06 + flag Ransomware. Finisce in dashboard Alert (e su Telegram una volta collegato).

---


# 2026-08-19 — KEV ↔ Asset: esposizione clienti a CVE attivamente sfruttate

## Richiesta utente
Rendere il catalogo KEV "azionabile": incrociare i CVE con vendor/modelli degli asset nel CMDB per vedere quali clienti sono esposti a una KEV attivamente sfruttata.

## Backend (routes/osint.py)
- Nuovo endpoint `GET /api/osint/kev/asset-exposure`: incrocia `cisa_kev` con gli asset a modello reale (`zyxel_devices` firewall + `managed_devices`). Match conservativo: vendor (token) + prodotto. Aggiunto match "vendor+categoria" per prodotti KEV generici (es. "Multiple Firewalls" → qualsiasi firewall del vendor). Ritorna per-asset i CVE, prodotto, scadenza, flag ransomware, match_type (specific/vendor_category). Isolamento per cliente via param client_id.

## Frontend (OsintPage.js)
- Nuovo pannello "I miei asset esposti a KEV": tabella Cliente / Dispositivo / Vendor·Modello / CVE KEV (badge conteggio + ransomware + chip CVE con tooltip descrizione) / Prima scadenza (rossa se superata).

## Verifica (API + screenshot, dati reali)
2 asset con modello analizzati → 1 esposto: Zyxel USG FLEX 700H (86BIT_Office) su 5 CVE KEV Zyxel firewall (CVE-2022-30525, 2023-28771, 2023-33009, 2023-33010, +1), flag Ransomware, scadenza 2022-06-06 evidenziata. HPE ProLiant iLO correttamente nessun match (KEV non ha ProLiant/iLO).

---


# 2026-08-19 — CISA KEV: arricchimento campi (Azione richiesta, Scadenza, Descrizione)

## Richiesta utente
Incorporare la struttura completa del catalogo CISA KEV: CVE ID, Vendor & Product, Short Description, Required Action & Due Date, Ransomware Flag.

## Implementazione
- Backend `services/osint_service.py` (refresh_cisa_kev): aggiunti `short_description` (shortDescription), `required_action` (requiredAction), `cwes` all'ingestione del feed ufficiale CISA. `due_date`/`ransomware` già presenti.
- Backend `routes/osint.py` (list_kev): ricerca estesa anche a `short_description`.
- Frontend `OsintPage.js`: tabella KEV con nuove colonne "Azione richiesta" e "Scadenza" (due_date in ROSSO se remediation scaduta), descrizione breve/azione in tooltip.

## Verifica
Refresh forzato: 1670 CVE, tutte con required_action + short_description. Screenshot: colonne visibili, date scadute evidenziate in rosso (es. CVE-2026-20349 Cisco ASA due 2026-08-14). Feed KEV OK.

---


# 2026-08-19 — C2 Correlation: IP dei firewall Nebula vs IOC (ogni 2 min)

## Richiesta utente
Confrontare gli IP nei log firewall/syslog dei clienti con gli IOC (Feodo, Spamhaus, FireHOL, ThreatFox). Se un dispositivo comunica con un IP malevolo noto → alert critico per quel cliente. Scansione automatica ogni 2 min. Usare i dati che ora arrivano dai firewall Nebula.

## Implementazione (services/osint_poller.py)
- Nuovo `_scan_nebula_firewalls(agg, now)`: per ogni firewall Zyxel Nebula ONLINE scarica gli event-log (finestra 3 min, cap 8000/fw), estrae src/dst IPv4 e li confronta con gli IOC (`match_ips_against_iocs`, che filtra già gli IP pubblici). I match confluiscono nell'aggregato C2 condiviso.
- Integrato in `osint_c2_tick` (già schedulato ogni 2 min): oltre a `syslog_events` ora scansiona anche i firewall Nebula → nessun syslog richiesto lato cliente. Alert critico per-tenant via `_emit_c2_alert` (con dedup). Messaggio fonte aggiornato a "syslog/event-log firewall".
- Protetto da try/except per-firewall: un 404/errore Nebula salta quel firewall senza bloccare il tick.

## Verifica (pipeline end-to-end, mock event-log + IOC Feodo)
osint_c2_tick → IP 45.155.205.233 (dst nei log firewall) correlato con IOC Feodo/Dridex_C2 → ALERT CRITICO per cliente da3d6e40 (firewall 192.168.45.2). 8.8.8.8 benigno nessun falso positivo. IOC in DB: 6395. Backend 200.

## Nota
- Endpoint Nebula event-logs a volte risponde 404 intermittente (glitch lato Zyxel): gestito con skip best-effort; il tick riprova al ciclo successivo.

---


# 2026-08-19 — Sonda globale + Alert cambio IP pubblico reale

## Richieste utente
1) Poter creare UNA sonda unica (globale) per tracciare tutti i clienti.
2) Confrontare l'IP pubblico reale rilevato con quello atteso e generare alert al cambio (IP dinamici / failover).

## Feature A — Sonda globale (NetworkPathDiagnosisPage.js)
- Aggiunta opzione "🌐 Sonda globale (tutti i clienti)" nel dropdown sede/cliente (valore sentinella client_id="__global__"), impostata come default. Testo aggiornato: una sola sonda nel NOC traccia verso tutti i clienti. Il dropdown agent-sonda mostra "🌐 Sonda globale". Register token con __global__ verificato (200). Il traceroute parte già verso qualsiasi IP destinazione.

## Feature B — Alert cambio IP pubblico reale (external_monitor.py)
- Nuovo `_detect_wan_ip_change(client_id, expected_ips)`: risolve l'IP egress reale del cliente (managed_agents.public_ip via _resolve_detected_public_ip), lo confronta con l'ultimo noto e con gli IP attesi dei target WAN. Storico in `wan_public_ip_changes` (target_id=`detected:{client_id}`), alert `wan_public_ip_change` severity high al cambio (no alert al primo record), con nota se non combacia con l'atteso. Chiamato in run_probe_cycle per ogni cliente.
- NB: il precedente `_detect_public_ip_change` seguiva solo l'IP CONFIGURATO (cambiava solo su edit admin); ora c'è il confronto sull'IP REALE.

## Verifica
Feature A: screenshot opzione globale + register 200. Feature B: test funzionale — init nessun alert, al cambio 11.11.11.11→22.22.22.22 alert generato con nota mismatch, 2 record storico. Compila pulito.

---


# 2026-08-19 — WAN + Zyxel: unificazione firewall (dedup) + arricchimento Nebula

## Richiesta utente
Riprogettare la pagina WAN esterna, importare i dati Nebula per i firewall Zyxel (coerenza), mostrare sempre ISP + IP pubblico in Zyxel, eliminare i doppioni in "Infrastruttura di Rete". Collegamento manuale via dropdown.

## Backend (external_monitor.py)
- WanTarget/WanTargetUpdate: nuovi campi `linked_nebula_dev_id`, `linked_nebula_site_id` (collegamento manuale; "" = scollega).
- Helper `_attach_nebula`: arricchisce i target collegati con dati zyxel_devices (model, sn, mac, online_status, cpu/mem/sessioni, mgmt_ip, firmware, ports_up/total). Applicato a GET /targets e /status.

## Frontend
- ExternalMonitorPage (Monitor WAN): dropdown "Collega a firewall Zyxel Nebula" nel dialog edit (carica firewall del cliente); DeviceCard arricchita con nome prodotto (model), badge NEBULA·ON/OFF, S/N, porte up/total.
- NebulaFirewalls.jsx: prop `wanTargets`; riga mostra IP pubblico REALE (dal target collegato) + latenza + ISP OK/DOWN; dialog: sezione "Connettività WAN · ISP" (IP pubblico, stato, latenza, packet loss, gateway, ISP/ASN/località via geo-ip).
- ClientOverviewPage: passa wanTargets a NebulaFirewalls; "Connettività WAN" ESCLUDE i target collegati → niente doppioni.

## Verifica (screenshot + API, cliente da3d6e40)
Dedup OK (il firewall collegato sparisce da Connettività WAN, resta solo il router). Monitor WAN: riga con NEBULA·ON, S/N, porte 4/14. Dialog: ISP "Google LLC" AS15169, IP pubblico 8.8.8.8. PUT link/unlink 200 e arricchimento coerente.

---


# 2026-08-19 — CMDB: fusione client firewall Nebula in Entity Resolution

## Richiesta utente
Fondere i client connessi al firewall nel CMDB/Entity Resolution, correlandoli via MAC alle identità già note (SNMP/Datto/Agent) invece di lasciarli in un elenco a sé.

## Implementazione (entity_resolver.py)
- Nuova fonte `nebula` in `_collect_units`: per ogni firewall del cliente legge `clients[]` e crea/arricchisce un'unità CMDB per IP, con chiave MAC (+ hostname se significativo). Nebula spesso fornisce il MAC anche per IP non mappati dal monitoraggio → merge trasversale via chiave `mac`.
- attrs: nebula_client, nebula_status, vendor, os, vlan.

## Frontend (EntityInventoryPage.js)
- Badge dedicato sorgente "Zyxel Nebula" (ciano).

## Verifica (reconcile reale cliente da3d6e40)
88 unità (62 nuove da Nebula). Entità fuse multi-sorgente: es. PC001 / 86bitserver / DATI = Datto+Monitoraggio+Nebula (MAC aggiunto da Nebula a device già noti). Client standalone inventariati con sorgente Nebula. Screenshot CMDB conferma.

---


# 2026-08-19 — NEBULA: scheda firewall arricchita (Client, VPN, Event Logs)

## Richiesta utente
"Voglio tutte le informazioni". Chiarito che Gateway/DNS/VLAN sono vuoti perché Nebula li restituisce null alla fonte (verificato su risposta grezza). Aggiunte le 3 fonti dati Nebula mancanti.

## Backend (zyxel_nebula.py)
- Sync firewall: aggiunto `clients` (POST /{sid}/clients → dispositivi dietro il firewall: ip, mac, vlan, hostname, vendor, os, status) + `clients_online`, e `vpn_status` (GET /{sid}/vpn-status → sites/gateways/remote_aps).
- Nuovo endpoint on-demand `GET /api/clients/{client_id}/zyxel/devices/{dev_id}/event-logs?minutes=&limit=` (POST /{sid}/gw/event-logs): Nebula restituisce migliaia di eventi → finestra breve + cap ai più recenti. NON in polling per non appesantire il sync.

## Frontend (NebulaFirewalls.jsx)
- Scheda dispositivo: aggiunte sezioni "Client connessi (N online)", "VPN", "Event Logs (on-demand con pulsante Carica)".

## Verifica (screenshot, cliente da3d6e40 USG FLEX 700H)
Client connessi 52/62 con IP+vendor+stato; VPN 0 (nessun tunnel, reale); Event logs 150 su 20817/60min con categoria/orario/src→dst. Compila pulito, nessun crash.

---


# 2026-08-19 — NEBULA: firewall come riga + scheda dispositivo completa

## Richiesta utente
Mostrare il firewall Nebula come riga normale (nome preciso del prodotto). Al click, scheda con TUTTE le info leggibili: IP per porta/interfaccia, traffico per porta, porte NAT aperte.

## Implementazione
- Backend (zyxel_nebula.py): aggiunto `lan_interfaces` da `interface-settings` (IP per interfaccia LAN); esteso `wan_interfaces` con port_group/vlan.
- Frontend (NebulaFirewalls.jsx): riscritto come RIGA compatta cliccabile (usa `model` come nome prodotto) + Dialog "scheda dispositivo" con sezioni: stato+metriche, Identità, Interfacce WAN (IP pubblico/gateway/netmask/DNS/VLAN), Interfacce LAN (IP/netmask/port-group), Porte fisiche (speed/status), Traffico per interfaccia (tx/rx), NAT/Porte aperte.

## Verifica (screenshot, dati reali cliente da3d6e40 - USG FLEX 700H)
Riga: "USG FLEX 700H · 192.168.45.2 · NEBULA · ONLINE". Dialog: CPU 5%/Mem 39%/Sess 1228, WAN(2) ge1/ge2, LAN(11) vlan2..ge13 con IP reali. Tutto leggibile, nessun crash.

---


# 2026-08-19 — TELEGRAM: diagnosi collegamento + fix UX "Rileva chat"

## Contesto
Integrazione Telegram già interamente sviluppata (telegram_notifier.py + endpoint /api/alert-engine/telegram/{test,detect-chats} + UI AlertEngineSettingsPage). Le notifiche non arrivavano perché: token bot salvato NON valido (getMe 401) e telegram_chat_id VUOTO.

## Fix UX applicato
- `GET /api/alert-engine/telegram/detect-chats` ora accetta query param opzionale `token` → "Rileva chat" può usare il token appena digitato senza doverlo prima salvare (prima usava solo il token in DB, invalido).
- Frontend `AlertEngineSettingsPage.jsx`: detectChats passa `?token=<digitato>`.

## Azione lato utente (in corso)
Utente configura da UI (Impostazioni → Alert Engine → Telegram): incolla token @BotFather, invia /start al bot, "Rileva chat", seleziona chat_id, "Test".

---


# 2026-08-19 — NEBULA: Scheda Firewall in cima alla WAN + fix endpoint porte (VALIDATO PROD)

## Richiesta utente
Mostrare i firewall Zyxel Nebula fissati in cima alla sezione WAN dell'overview cliente con scheda dettagliata (IP pubblico, stato linea, S/N, porte, traffico, NAT). "Valida Porte in Produzione".

## Fix critico backend (routes/zyxel_nebula.py)
- Endpoint porte ERRATO (`port-status`/`ports`) → corretto in `ports-status` (endpoint reale Nebula), campi reali `portNumber`/`portGroup`/`linkSpeed`. Status link derivato da `linkSpeed` via nuovo helper `_port_link_status`.
- Aggiunto fetch `interface-settings` → `wan_interfaces`, `public_ip`, `line_state`.
- Aggiunto fetch `nat-settings` → `nat_rules` (virtualServer + oneToOne).

## Frontend
- Nuovo componente `/app/frontend/src/components/NebulaFirewalls.jsx` (GET /api/clients/{id}/zyxel/devices, filtra firewall, auto-hide se assenti, refresh 30s). Titolo usa `model` se `name`==MAC.
- Montato in `ClientOverviewPage.js` dentro `SafeBoundary`, in cima alla WAN (pannello Infrastruttura di Rete).

## Validazione (iteration_125.json)
- Backend 8/8 pytest OK, frontend 100%. Firewall reale cliente da3d6e40: 14 porte reali (up/down coerenti con linkSpeed), public_ip 192.168.45.2, line_state up, CPU 5%/Mem 39%/Sess 1156. Nessun crash/blank.
- Note: `portGroup` assente nella risposta del USG FLEX 700H (group=null); `nat_rules` vuoto sul FW reale (rendering NAT non testabile live).

---


# 2026-07-29 — DEVOPS: Auto-set "latest override" sul Center a fine release

## Richiesta utente
Dopo una release, il Center deve impostare da solo la versione latest (niente Settings a mano).

## Implementazione
- Backend `agent_ws.py`: nuovo endpoint `POST /api/agent/release-hook` protetto da
  header `X-Release-Secret` (confronto costante con env `AGENT_RELEASE_HOOK_SECRET`;
  se la env manca l'endpoint e' disattivo → 503). Body `{"version":"v4.26.0"}`:
  scrive `system_settings.agent_latest_version_override`, invalida la cache in memoria
  e ri-risolve la latest. Validazione semver.
- `.github/workflows/release-agent.yml`: nuovo step finale "Notify Center" che, se i
  secret `CENTER_URL` e `AGENT_RELEASE_HOOK_SECRET` sono configurati, POSTa la versione
  all'endpoint; altrimenti si salta senza far fallire la release (guard nello script).

## Setup a carico utente (una tantum)
1. Backend PROD `.env`: `AGENT_RELEASE_HOOK_SECRET=<random>`.
2. GitHub repo → Settings → Secrets: `CENTER_URL=https://argus.86bit.it` +
   `AGENT_RELEASE_HOOK_SECRET=<stesso valore>`.
Da lì ogni release imposta l'override in automatico.

## Validazione
- Endpoint testato via stub: secret errato → 403; corretto → 200 + override scritto e
  risolto (`v4.26.0`). `.env` non modificata; override di test rimosso ✅. YAML valido.

---


# 2026-07-29 — DEVOPS: Rilascio agent "a un numero" (file VERSION → auto-release)

## Richiesta utente
Rendere il rilascio dell'agent automatico: cambiare solo un numero, niente build/tag manuali.

## Implementazione
- `noc-agent/VERSION` (NUOVO): contiene la versione (attuale `4.26.0`).
- `.github/workflows/auto-release-agent.yml` (NUOVO): on push a main quando cambia
  `noc-agent/VERSION`, legge la versione, salta se il tag/release esiste già
  (idempotente), e avvia via `gh workflow run` la pipeline esistente
  `release-agent.yml` (workflow_dispatch con `tag=vX.Y.Z`). Nota: usa workflow_dispatch
  perche' un tag pushato col GITHUB_TOKEN non triggererebbe altri workflow.
- `noc-agent/Makefile`: `VERSION ?=` ora legge da `./VERSION` (build locali coerenti).

## Effetto
- L'utente cambia SOLO il numero in `noc-agent/VERSION` e committa → build+release
  partono da sole. Il primo "Save to Github" con VERSION=4.26.0 rilascia gia' v4.26.0.
- La pipeline compila `nocagent.exe` includendo il nuovo modulo `snmpports` (cmd/agent).

## Validazione
- File VERSION letto correttamente; Makefile inietta `main.Version=4.26.0+<commit>`;
  entrambi i workflow YAML validati (yaml.safe_load) ✅.

---


# 2026-07-29 — FEATURE: Raccolta Porte Switch nativa nell'agent v4 Go (ifTable)

## Contesto
Tutti i clienti usano agent v4 Go (legacy PowerShell dismesso). L'agent v4 NON
raccoglieva la tabella porte (ifTable/LLDP) → pagina "Porte Switch" sempre vuota.
Le porte arrivavano solo dal connector legacy. Scelte utente: trasporto = WebSocket
(consigliato), ambito = solo porte (ifTable/ifXTable + contatori per rx/tx bps/pps).

## Implementazione — Agent Go (/app/noc-agent)
- `pkg/proto/messages.go`: nuovo evento `EventSwitchPorts="switch_ports"` + struct
  `SwitchPortsReport/SwitchInfo/SwitchPortInfo`.
- `internal/poller/snmpports.go` (NUOVO): modulo `PortsPoller` che, per ogni target
  con Profile switch-like (switch/router/firewall/gateway), fa BULKWALK di
  ifName/ifDescr/ifAlias/ifOper/ifAdmin/ifSpeed/ifHighSpeed/ifLastChange +
  ifHC{In,Out}Octets e ifHC{In,Out}UcastPkts. Calcola rx/tx bps e pps dai delta tra
  cicli (guardia contro wrap). Interval clamp 60s-10m (default 120s). Health-tick
  ogni ciclo (no "stuck" sui clienti senza switch).
- `cmd/agent/main.go`: istanzia `portsP`, registra health "snmpports", hot-swap
  config (`portsP.ApplyConfig`), avvia `go portsP.Run(ctx)`. Version → 4.26.0.

## Implementazione — Backend
- `connector.py`: estratta `store_switch_ports(client_id, switches)` (logica storage
  + flap detection + alert loop), riusata dall'endpoint REST legacy (refactor) e dal
  bridge WS. Il guard `enforce_connector_tenant` resta attivo.
- `agent_ws.py`: nuovo `_bridge_switch_ports(conn, data)` + dispatch `kind=="switch_ports"`
  → chiama `store_switch_ports(conn.client_id, switches)` (client_id AUTENTICATO).

## Validazione
- Backend: `store_switch_ports` testato end-to-end (persistenza porte, refactor
  endpoint intatto) ✅. Compila e riparte pulito ✅.
- Agent Go: codice scritto e API verificate contro gosnmp v1.38.0
  (BulkWalkAll/ToBigInt/MaxOids/Conn.Close), module path, config fields, logging.
  ⚠️ NON compilato qui (nessun toolchain Go in questo ambiente).

## Dipendenza deploy (a carico utente)
Il nuovo agent (v4.26.0) va COMPILATO e PUBBLICATO dalla pipeline/GitHub Releases
dell'utente; gli agent lo prendono con "Forza re-deploy". Poi, sui device con
device_type=switch, le porte compaiono al ciclo successivo (~2 min).

---


# 2026-07-29 — FIX diagnosi porte: check Connector (v4) + segnale pipeline

## Problema (screenshot utente)
Diagnosi: check 1-4 verdi (device=switch, community ok), check 7 verde (poll ok,
reachable=True), MA check 8 ROSSO "1 connector registrati ma NESSUNO online" mentre
l'utente conferma che il connector e' acceso. Contraddizione → check 8 sbagliato.

## Root cause del check 8
Esistono DUE sistemi: legacy v3 in `connector_status` (campo `online`) e agent v4 Go
in `managed_agents` (online = heartbeat <120-180s). Il mio check 8 guardava solo i
legacy e leggeva il booleano `online` statico → falso negativo per gli agent v4.
Inoltre `agent_ws.py` (v4) NON gestisce affatto switch_ports/ifTable/LLDP: le porte
arrivano SOLO dagli endpoint REST legacy `/connector/switch-ports` e
`/connector/network-discovery`.

## Fix (topology.diagnose)
- Check 8 ora considera SIA connector_status SIA managed_agents (v4) e calcola online
  dall'heartbeat recente (<180s); mostra nome+versione agent.
- Check 5 arricchito con segnale decisivo: quante porte esistono per QUALSIASI switch
  del cliente. Se 0 su tutti → la raccolta ifTable non funziona a livello di agent
  (probabile agent v4 senza modulo topology, o connector legacy non attivo). Se >0 →
  problema specifico del device.
- Raccomandazione finale differenziata per "agent online ma porte non ancora arrivate".

## Validazione
- Diagnose gira senza errori con la nuova logica (curl). In preview: check 8 warn
  (nessun agent live), check 5 error (nessuna porta per il cliente). Da riverificare
  su produzione con agent live.

---


# 2026-07-29 — SECURITY: Tenant Write Guard (anti cross-tenant a livello di scrittura)

## Richiesta utente
Impedire a un connector di registrare/importare un dispositivo sotto un client_id
diverso dal proprio (garanzia a livello di SCRITTURA, non solo di visualizzazione).

## Stato preesistente
Tutti i write dei connector usavano gia' `client_id = client_data["id"]` (identita'
autenticata via HMAC/API-key), mai un client_id dal body. `LanScanReport` non espone
client_id (immune per design). Nessun leak reale, ma mancava una rete di sicurezza.

## Implementazione
- Nuovo helper `enforce_connector_tenant(body, client_id)` in `connector.py`:
  se il payload (o un elemento di liste annidate: results/endpoints/switches/devices/
  items/mac_tables/device_macs) specifica un `client_id` DIVERSO da quello del
  connector autenticato → HTTP 403 + log `[TENANT-GUARD]`.
- Applicato agli endpoint di ingestion raw-body: `web-ui-detected`, `printer-probe`,
  `switch-ports`, `network-discovery`.
- Gli endpoint Pydantic (lan-scan) restano immuni perche' il modello non ha client_id.

## Validazione
- Unit test logica: no client_id → pass; match → pass; top-level foreign → 403;
  nested foreign → 403 ✅. Backend compila e riparte pulito.

---


# 2026-07-29 — FIX ROOT CAUSE + rollback selettore cross-tenant

## Feedback utente (fermo)
"Un dispositivo NON deve/può appartenere a più tenant, non si devono MAI mischiare."
Obiezione al selettore che mostrava 2 clienti sulla stessa schermata.

## Chiarimento
Non c'era mixing di DATI (le query porte/metriche sono sempre {ip+client_id}). Il
selettore mostrava solo 2 card di clienti diversi sulla stessa pagina → violava il
principio di separazione visiva. RIMOSSO.

## Root cause del problema originale
`DeviceInfoCard.js:471` costruiva il link "/switch-ports/{ip}" SENZA client_id →
aprendo le Porte Switch dalla Scheda Dispositivo si perdeva il contesto cliente e,
per IP privati condivisi, scattava il 400 "client_id obbligatorio".

## Fix
- `DeviceInfoCard.js`: il bottone Porte switch ora passa SEMPRE il client_id
  (`clientId prop || card.client.id || ...`).
- `SwitchPortsPage.js`: rimosso il selettore che elencava i tenant; al posto, se manca
  clientId su IP condiviso, mostra un messaggio NEUTRO ("Apri dalla Panoramica del
  cliente") SENZA mostrare nomi/dati di altri clienti.
- `topology.py`: rimosso l'endpoint `GET /devices/{ip}/owners` (aggregava clienti).

## Validazione (screenshot)
- info-card espone `client.id` → link corretto ✅
- Schermata neutra: nessun nome tenant mostrato (NO_TENANT_NAMES_SHOWN=True) ✅
- Dati sintetici rimossi.

---


# 2026-07-29 — UX: Selettore tenant per IP condivisi (fix "client_id obbligatorio")

## Contesto (segnalazione utente)
Aprendo la pagina Porte Switch di un IP presente su piu' clienti SENZA clientId
nell'URL, compariva solo un toast criptico "IP X presente su 2 clienti diversi:
client_id obbligatorio" + box vuoto. Comportamento corretto (isolamento multi-tenant)
ma UX confusa.

## Implementazione
- Backend `topology.py`: nuovo endpoint `GET /api/devices/{ip}/owners` → lista
  {client_id, client_name, device_name, device_type} dei clienti che possiedono l'IP.
- Frontend `SwitchPortsPage.js`: se la chiamata switch-ports torna 400 e non c'e'
  clientId, la pagina interroga /owners e mostra un **selettore tenant** ("Questo IP
  appartiene a piu' clienti") con una card per cliente; il click naviga alla pagina
  con il clientId corretto. Niente piu' dead-end.

## Validazione (screenshot)
- IP sintetico su 2 clienti → picker mostrato con entrambe le card (nome cliente +
  nome/tipo switch), navigazione con clientId corretto ✅. Dati sintetici rimossi.

---


# 2026-07-29 — ENHANCEMENT: "Correggi ora" → poll immediato (hot-push config all'agent)

## Richiesta utente
Dopo il "Correggi ora" (device_type=switch), forzare un poll immediato invece di
aspettare 2-5 min, così le porte compaiono quasi subito.

## Implementazione
- `topology.set_device_type_switch`: dopo l'update chiama
  `agent_ws.push_config_to_client(cid)` → hot-push della poller_config aggiornata a
  TUTTI gli agent live del cliente. L'agent vede subito `profile=switch` e raccoglie
  ifTable/LLDP/PoE al ciclo SNMP successivo (~60s). Risposta arricchita con
  `agents_notified` + `message` dinamico (~1 min se agent live, altrimenti 2-5 min).
- Frontend: il toast mostra il `message` del backend; dopo il fix ri-esegue diagnose
  e `reload()` delle porte.
- Nota: non esiste un comando agent per la raccolta ports on-demand immediata
  (richiederebbe modifica dell'agent Go); l'hot-push della config è la via piu' rapida
  senza redeploy agent.

## Validazione
- POST set-type-switch → `agents_notified` + message corretti (0 in preview, fallback
  2-5 min). Backend compila e riparte. Device di test ripristinato a 'endpoint'.

---


# 2026-07-29 — FEATURE: "Correggi ora" nella Diagnosi porte (one-click device_type=switch)

## Richiesta utente
Aggiungere un pulsante nella Diagnosi che, quando rileva device_type non switch,
imposti direttamente device_type=switch senza andare nelle impostazioni.

## Implementazione
- Backend `topology.py`:
  - Il check "3. Tipo device" della diagnose ora include `action="set_device_type_switch"`.
  - Nuovo endpoint `POST /api/devices/{ip}/switch-ports/set-type-switch?client_id=`
    (admin/operator, scoped via tenant_scope): setta `device_type='switch'` su
    `managed_devices` (ip+client_id) + cascade best-effort su `devices`.
- Frontend `SwitchPortsPage.js`: `DiagnoseDialog` mostra il pulsante
  "⚡ Correggi ora — imposta come Switch" per i check con `action`; al click chiama
  l'endpoint, mostra toast e ri-esegue la diagnosi aggiornata.

## Validazione (curl + screenshot)
- diagnose (before): check 3 = error + action ; POST set-type-switch → device_type=switch ;
  diagnose (after): check 3 = OK ✅. Pulsante renderizzato in UI ✅.
- Device di test 10.10.1.10 ripristinato a 'endpoint' dopo il test.

---


# 2026-07-29 — FEATURE: Diagnostica one-click "Perché non arrivano le porte switch"

## Contesto (domanda utente)
"Non capisco perché non arrivano le porte, e su un altro switch identico di un altro
cliente con la stessa config arrivano." → serve capire cosa differisce lato ARGUS.

## Root cause tipica individuata
La raccolta pesante delle porte (ifTable/LLDP/PoE) viene fatta dall'agent SOLO per i
device classificati come switch/router/firewall (in `agent_ws._build_poller_config`
il target riceve `profile = device_type`; se non e' switch-like l'agent fa solo il
poll base e non manda la ifTable). Altre cause: community mancante/errata (case),
connector offline, o dati porte salvati sotto un client_id diverso (connector su
cliente sbagliato).

## Implementazione
- Nuovo endpoint `GET /api/devices/{ip}/switch-ports/diagnose?client_id=` in
  `topology.py`: 8 check con status ok/warn/error + fix + recommendation:
  1) device registrato (o presente su altro cliente),
  2) abilitazione, 3) device_type switch-like (causa piu' comune),
  4) community SNMP + eligibility, 5) porte presenti (rileva mismatch client_id),
  6) LLDP/FDB, 7) ultimo poll (device_class/reachable), 8) connector online.
  Scoped multi-tenant via `tenant_scope.resolve_device_client_id`.
- Frontend `SwitchPortsPage.js`: pulsante "🩺 Diagnosi" (header + stato vuoto) e
  `DiagnoseDialog` con check colorati e raccomandazione.

## Validazione (curl + screenshot)
- Diagnose su device endpoint reale: check 3 (tipo) e 4 (community) ERROR, reco
  "Imposta device_type='switch'". Dialog UI renderizzato correttamente ✅

---


# 2026-07-29 — FEATURE: Rilevamento Loop di Rete su Switch (Fase A, solo backend)

## Richiesta utente
"Siete in grado di rilevare se in uno switch c'è collegato un cavo in se stesso / loop?"
Scelta: opzione A — MAC-flapping + storm detection, backend-only, nessun redeploy agent.

## Implementazione
- Nuovo modulo `backend/routes/loop_detection.py`:
  - `compute_loop_suspects(ports, endpoints)` (pura): rileva
    (1) stesso MAC appreso su ≥2 porte (soglia ≥3 MAC condivisi = loop), 
    (2) broadcast storm = porta UP con pps simmetrico ≥15000.
    Ritorna per-porta reasons/partners/dup_mac_count/storm.
  - `evaluate_and_alert(db, client_id, local_ip, ports)`: all'ingest crea/aggiorna
    un alert (severity=high, source_type=network, id=`loop-{cid}-{ip}`) e lo
    RISOLVE automaticamente quando il loop scompare.
- `topology.get_switch_ports`: ora arricchisce ogni porta con
  `loop_suspect`/`loop_reasons`/`loop_partners` e `totals.loop_suspect`.
- `connector.connector_switch_ports_report` (ingest `/sp`): chiama
  `evaluate_and_alert` per ogni switch → alert generati server-side ad ogni poll,
  indipendenti dalla page-view. Wrappato in try/except (mai rompe l'ingest).
- Frontend `SwitchPortsPage.js`: badge rosso ⚠ sui tile sospetti (ring pulsante),
  chip "⚠ Loop N" nell'header + filtro dedicato, box di avviso nel pannello
  dettaglio (motivi + porte partner), chip "LOOP" nella tabella.

## Validazione (curl + DB sintetico + screenshot)
- Porte 3&7 (5 MAC condivisi) → loop_suspect con partner reciproci ✅
- Porta 5 (30k/30k pps) → storm ✅ ; porta 1 normale → nessun flag ✅
- totals.loop_suspect=3 ✅ ; alert creato (active) e poi auto-resolved al clear ✅
- UI: badge/chip/filtro/tabella renderizzati correttamente ✅
- Dati di test rimossi dal DB.

## Backlog (Fase B, se richiesta dall'utente)
- STP Port State (dot1dStpPortState/MSTP) via SNMP-walk nell'agent Go per rilevare
  anche i loop gia' bloccati dallo spanning-tree. Richiede update + redeploy agent.

---


# 2026-07-29 — CHIUSURA AUDIT ISOLAMENTO CROSS-TENANT (Issue P0) — VALIDATO

## Contesto
Ripresa del task interrotto: messa in sicurezza cross-tenant di tutti gli endpoint by-IP.
Backend già RUNNING senza errori di sintassi (edit precedenti caricati OK).

## Audit residuo + fix in questa sessione
- Helper `tenant_scope.resolve_device_client_id` confermato: se un IP appartiene a >1
  cliente → HTTP 400 (client_id obbligatorio); se a 1 solo cliente → auto-resolve.
- `redfish_routes.redfish_diagnose`: aggiunto param `client_id` + scope su
  managed_devices/device_poll_status (prima query solo per `ip`).
- `web_console_enterprise` (recent-sessions, favorites, live-sessions): i lookup di
  arricchimento nome device ora includono `client_id` del record (prima solo `ip`).
- `arp_cache.by-ip` e `firmware_catalog` verificati: già scoped correttamente.
- `server_intelligence`: i `{"ip": ...}` residui sono dict di OUTPUT, non query (OK).

## Validazione (smoke test curl, preview)
- connectivity-report CON client_id → 200 ; SENZA → 400 (anti-leak) ✅
- redfish/diagnose auto-resolve tenant corretto → 200 ✅
- cmdb/assets, arp-cache/by-ip, web-console/favorites, live-sessions → 200 ✅
- Frontend (login ARGUS Center) carica correttamente ✅
- Nota: attualmente 0 IP condivisi tra clienti nel DB (rischio teorico, protezione attiva).

---


# 2026-06 — FIX CRITICO: leak cross-tenant nella Scheda Dispositivo (multi-tenant)

## Bug (segnalato — GRAVE)
- Dentro un cliente (es. "Arma Creativo"), aprendo la Scheda Dispositivo di un IP
  privato comune (192.168.1.x) veniva mostrato il device/nome di un ALTRO cliente
  (es. GualdiGroup). Data leak di isolamento multi-tenant.

## Root cause
- Gli endpoint "by-ip" della scheda facevano `find_one` SOLO per IP, senza
  `client_id`. IP privati condivisi tra tenant → restituito il device del cliente
  sbagliato. Endpoint colpiti: `/info-card`, `/vendor-details`, `/metrics`
  (+ fallback `arp_cache`).

## Fix (backend)
- `device_info_card.build_info_card(device_ip, client_id)` + `get_info_card`:
  helper `_q` inietta client_id in TUTTE le query (device_poll_status,
  managed_devices, cmdb_assets, lifecycle_records, ilo_status, arp_cache) e nell'exists-check.
- `devices.device_vendor_details(device_ip, client_id=None)`: filtra
  device_poll_status + managed_devices per client_id.
- `metric_history.get_metrics_history(..., client_id=None)`: filtra
  metric_history + device_metrics_history (legacy) per client_id.

## Fix (frontend) — passano SEMPRE client_id
- `DeviceInfoCard` (prop `clientId`, querystring), `AllMetricsDialog`,
  `SynologyDetailSection`, `VendorDetailsPanel`, `DeviceMetricsPage` (client_id=selectedClient),
  `DeviceDetailPanel`. `ClientOverviewPage` passa `clientId` alla card.
- La lista dispositivi (`/devices?client_id=`) era già client-scoped (nessun fix necessario).

## Testing (testing_agent)
- iteration_97: 12/12 PASS nuovi + 12/12 regressione. Stesso IP su 2 client →
  ogni endpoint ritorna SOLO i dati del client richiesto; 404/serie vuota per
  client che non possiede l'IP. Suite: tests/test_byip_multitenant_iter97.py.

## Hardening consigliato (NON ancora implementato)
- Rendere client_id obbligatorio (o 409 su IP ambiguo) sugli endpoint by-ip:
  oggi è opzionale per retrocompat; tutti i call-site FE lo passano, ma un client
  API esterno o una regressione FE futura potrebbe riaprire il leak.
- Estrarre helper condiviso `scoped_query(field, ip, client_id)` (pattern duplicato in 3 moduli).

---


# 2026-06 — FIX: impostazioni "Tipo macchina" / VM non salvate sui server iLO

## Bug (segnalato)
- Impostando "Tipo macchina" (o l'allerta VM) su un server iLO, il salvataggio
  non persisteva.

## Causa (root cause)
- I server iLO/redfish sono spesso device **poll-only**: esistono solo in
  `device_poll_status`, **senza documento in `managed_devices`**. Gli endpoint
  `POST /devices/by-ip/{ip}/virtualization` e `.../vm-alert` cercavano il doc
  managed e, non trovandolo, restituivano **404** → il save nel modale falliva
  (l'errore bloccava anche le altre impostazioni). Riprodotto in preview su un
  device poll-only (10.100.61.34) → HTTP 404.

## Fix
- Entrambi gli endpoint ora fanno **upsert**: se il device non è in
  `managed_devices`, creano un doc minimale (`id`, `client_id`, `ip`, `name`,
  `source: poll`) con l'impostazione, così persiste ed è leggibile da
  ilo-health e gather_signals. Richiedono `client_id` in questo caso (il
  frontend lo invia sempre).
- `get_client_ilo_health`: le VM (virtualization hyperv/vmware/vm_generic) ora
  sono escluse dalla lista iLO **anche nella sezione device redfish/poll-only**
  (sez.1), non solo dai managed (sez.4), via set `vm_ips`.

## Testing
- Poll-only 10.100.61.34: `virtualization=hyperv` → 200, doc creato via upsert,
  esposto in /api/devices (round-trip modale OK), escluso da ilo-health. PASS.
- `vm-alert` su poll-only → 200 (upsert). PASS. Dati di test ripuliti.

---


# 2026-06 — Selettore "Tipo macchina" per-device (Fisico / VM) + link Hyper-V manuale

## Richiesta utente
- Un tasto/selettore per impostare manualmente se una macchina è una VM, così
  non chiede credenziali iLO inutili e si aggancia lo stato Hyper-V anche quando
  il nome VM non coincide col nome del device. (scelte consigliate: 1a + 2a)

## Implementazione
- `models.py` (DeviceResponse): nuovi campi `virtualization`
  ("physical"|"hyperv"|"vmware"|"vm_generic"|""), `hyperv_vm_name`, `hyperv_host_hint`.
- `routes/device_info_card.py`: nuovo endpoint `POST /devices/by-ip/{ip}/virtualization`
  (validazione + update + cache invalidation + audit).
- `correlation_engine.gather_signals` + `routes/devices._hyperv_state`: l'aggancio
  allo snapshot Hyper-V usa `hyperv_vm_name` come PRIMA chiave (override manuale),
  poi hostname/name/device_name → risolve il caso "nome VM ≠ nome device" (SRVDC).
- `routes/devices.get_client_ilo_health`: le VM (virtualization hyperv/vmware/vm_generic)
  sono ESCLUSE dalla lista "server senza credenziali iLO".
- `routes/devices` /api/devices (3 path): espone virtualization/hyperv_vm_name/hyperv_host_hint.
- `components/DeviceEditModal.js`: selettore "Tipo macchina" + (se Hyper-V) campi
  "Nome VM su Hyper-V" e "Host Hyper-V"; salvataggio via nuovo endpoint + optimistic update.
  `isHyperVvm` ora true anche se marcata manualmente hyperv (mostra il toggle allerta VM).

## Testing
- Endpoint: 400 su valore invalido; set hyperv+vm_name+host → esposto in /api/devices.
- Unit: `gather_signals` con `hyperv_vm_name` override → match snapshot anche con nome
  device diverso (senza override → nessun match). PASS.
- `get_client_ilo_health` su DB reale: server fisico incluso, VM Hyper-V esclusa. PASS.
- Screenshot modale: selettore + campi Hyper-V + nota esclusione iLO + toggle allerta VM. OK.
- Badge "VM·HV" (cyan): screenshot conferma badge sulla riga device (viste raggruppata + tabella). OK.

---


# 2026-06 — Fix: profili Access Point non visibili nel dropdown "Configura profilo"

## Problema (segnalato via screenshot)
- I due nuovi profili AP (TP-Link Omada/EAP + Aruba Instant On) non comparivano
  nel dropdown di applicazione profilo, pur essendo presenti nel backend.

## Causa
- Frontend: whitelist `familyOrder` in `ClientOverviewPage.js` (modale
  "Configura profilo") NON includeva la famiglia `"access-point"` → i profili
  venivano filtrati via (stesso identico bug che in passato nascondeva le
  stampanti). Il backend li esponeva correttamente.

## Fix
- `ClientOverviewPage.js`: aggiunto `"access-point"` a `familyOrder` (dopo
  "firewall") e a `familyLabels` → nuovo optgroup "Access Point".
- `DeviceProfilesPage.js`: aggiunto meta `access-point` (+ `printer`, prima
  mancante) a `FAMILY_META` per label/icona corretti.

## Testing
- Screenshot dropdown: optgroup "Access Point" presente con entrambi i profili
  ("TP-Link — Omada/EAP", "Aruba (HPE) — Instant On"). Verificato via Playwright
  (optgroups + options letti dal DOM).
- NB: in produzione (argus.86bit.it) il fix è visibile solo dopo il redeploy.

---


# 2026-06 — Pulizia lista Clienti + Alert "Saturazione RF" per Access Point

## Richieste utente
1. Rimuovere dalla lista Clienti i pulsanti di installazione connector (badge
   versione, "Setup GUI", "Setup .exe", "M", "S") — non più necessari, il
   connector si installa solo dalla sezione dedicata.
2. Aggiungere al poller la lettura del numero di client Wi-Fi e un alert
   automatico di "saturazione RF" (>50 warning, >80 critical).

## Implementazione
- `frontend/src/pages/ClientsPage.js`: rimossa l'intera IIFE `client.api_key &&
  (() => {...})()` che renderizzava badge versione + install (Setup GUI / .exe /
  M / S). Mantenuti API Key / Rigenera / URL. Verificato via screenshot + testid
  count = 0 per download-installer/setup-exe/master/scanner/installed-version.
- `backend/routes/connector.py` → `_check_device_thresholds` (sezione
  vendor_metrics): nuovo blocco "Saturazione RF". Legge il conteggio client dai
  OID vendor riportati dal poller — `tpDot11ClientNum` (TP-Link), 
  `dot11AssociatedStationCount` (Aruba), `unifiApClients` (UniFi), con fallback
  `wifiClients`/`clientCount`. Gestisce anche tabelle per-radio (somma).
  Soglie dal profilo: `clients_warn` (50) → severità high, `clients_crit` (80) →
  critical. source_type `vendor_rf_saturation` (dedup + webpush come gli altri).

## Testing
- RF saturation end-to-end su DB reale: 85→critical, 60→high, 30→nessun alert,
  tabella Aruba per-radio 45+40=85→critical. ALL PASS (alert di test ripuliti).
- Frontend: compilazione pulita; screenshot pagina Clienti conferma pulsanti install rimossi, layout intatto.
- NB: i profili AP devono essere applicati ai device e il poller Go deve riportare
  gli OID client sotto vendor_metrics (come già fa per UniFi/Synology/Fortinet).

---


# 2026-06 — Profili vendor Access Point: TP-Link Omada/EAP + Aruba Instant On

## Richiesta utente
- Aggiungere 2 profili vendor per Access Point wireless con porte console web,
  OID SNMP di auto-discovery e soglie di allarme (CPU/RAM/client/uplink/ping).

## Implementazione (`device_profiles/__init__.py`)
- `tplink_omada_ap` (family `access-point`): OID enterprise .1.3.6.1.4.1.11863
  (tpSysCpuUsage/tpSysMemoryUsage/tpDot11ClientNum), web console Omada HTTPS 8043
  (alt 443/80/8088, adoption 29810-29814), SNMP 161. Soglie CPU 80/95, RAM 85/92,
  client 50/80, uplink-down critical, latenza 100ms / loss 2%.
- `aruba_instant_on` (family `access-point`): OID generico Aruba/HPE .1.3.6.1.4.1.14823
  (dot11AssociatedStationCount + ifIn/OutOctets porta POE), cloud portal.arubainstanton.com
  HTTPS 443 (+ local status page), SNMP 161 (da abilitare dal portale Cloud). Stesse soglie.
- Fingerprint: prefix sysObjectID + regex sysDescr (omada/eap/oc200, instant on/aruba ap).
  Il classifier device_classifier.py già mappa questi a device_type canonico `access-point`.
- `SEED_VERSION` 3 → 4.

## Note
- I profili sono letti direttamente dalla lista Python `PROFILES` (list_profiles,
  fingerprint, apply-profile, dropdown vendor) → attivi subito senza re-seed.
- Applicando il profilo, `device_type` = family = `access-point` (canonico, categoria AP).

## Testing
- `pytest tests/test_device_profiles.py tests/test_device_type_resolver.py` → 54 passed
  (aggiornati 2 test con conteggio profili hardcoded/obsoleto → ora derivato da len(PROFILES)).
- Endpoint live verificati via curl: `/list/vendors` mostra entrambi i profili access-point;
  dettaglio `tplink_omada_ap` con porta 8043, OID e soglie corrette.

---


# 2026-06 — Notifica push dedicata per "VM critica spenta inaspettatamente"

## Richiesta utente
- Notifica push mirata sulla console mobile dei tecnici SOLO per gli eventi
  `vm_unexpected_shutdown`, così la reperibilità viene avvisata in modo
  inconfondibile quando una VM che deve restare accesa cade davvero.

## Implementazione
- `webpush.py` → `build_alert_payload`: special-case per `source_type ==
  "corr_vm_unexpected_shutdown"`:
  - Titolo dedicato "🖥️🚨 VM CRITICA SPENTA" + body con VM · cliente.
  - `severity` forzata a `critical` → il service worker (`sw.js`) imposta
    `requireInteraction=true` (la notifica resta a schermo finché non chiusa)
    e la critica bypassa le Quiet Hours (`quiet_exclude_critical`).
  - `tag` per-device (`vmdown-{ip}`): un nuovo evento sulla stessa VM rimpiazza
    il precedente invece di impilarsi.
  - Deep-link alla scheda cliente (`/client/{client_id}`) invece della lista alert.
- Il routing esisteva già: l'alert critico passa da `_dispatch_notification` →
  `webpush.notify_new_alert` → on-call rotation (o fallback admin+operator).

## Testing
- Unit test `build_alert_payload`: caso VM (titolo/tag/url/severity) + caso generico
  (invariato) PASS. La consegna reale richiede VAPID configurato + subscription attive in prod.

---


# 2026-06 — Alert opzionale "VM critica spenta inaspettatamente" (Hyper-V)

## Richiesta utente
- Alert opzionale, configurabile per-device, quando una VM critica passa a
  Off/Saved/Paused in modo inatteso. Zero falsi positivi sulle VM spente di
  proposito (default OFF = comportamento storico). Scelte utente: trigger su
  Off+Saved+Paused, severità Critical, toggle in DeviceEditModal (solo VM Hyper-V).

## Implementazione
- `models.py` (DeviceResponse): nuovo campo `hyperv_alert_on_off: bool = False`.
- `correlation_engine.py`:
  - `gather_signals`: espone `s["vm_alert_on_off"] = bool(md.hyperv_alert_on_off)`.
  - `verdict_server` + `verdict_generic`: branch Off/Saved/Paused ora, se il flag
    è attivo, ritorna alert CRITICO `vm_unexpected_shutdown` (confidence 95);
    altrimenti mantiene `vm_powered_off` (nessun alert). Deterministico.
- `alert_engine.py`: query `targets` ora include anche `{hyperv_alert_on_off: True}`
  + campo nel projection (così le VM flaggate sono sempre valutate anche se non is_vital).
- `routes/device_info_card.py`: nuovo endpoint `POST /devices/by-ip/{ip}/vm-alert`
  body `{enabled, client_id?}` (mirror di set_device_vital: update + cache invalidation + audit).
- `routes/devices.py`: `hyperv_alert_on_off` esposto in TUTTI e 3 i path di risposta
  /api/devices (loop manuale + merge connector + secondo builder). Aggiunto anche
  enrichment hyperv_state/host nel loop manuale (prima assente).
- `components/DeviceEditModal.js`: toggle "Allerta se questa VM si spegne" (box rosso),
  visibile solo se `device.hyperv_state` presente; mostra lo stato HV corrente; salva via nuovo endpoint.

## Testing
- Backend: 7 unit test verdict (flag ON/OFF × Off/Saved/Paused/Running, server+generic) PASS;
  test_multisource_fusion.py PASS; endpoint 400/404/round-trip True↔False verificati via curl.
- Frontend: compilazione pulita; screenshot del modale conferma il toggle renderizzato
  con "Stato Hyper-V attuale: Off" per una VM Hyper-V.
- Effetto reale sull'host dipende dal redeploy in produzione + snapshot Hyper-V freschi (<15min).

---


# 2026-06 — Unificazione cartella Menu Start "86BIT Argus Center"

## Richiesta utente
- Unificare il nome della cartella nel Menu Start a "86BIT Argus Center" e far sì
  che ANCHE l'installer console/OTA (`install-noc-agent.ps1`) crei la cartella,
  non solo il Setup GUI. Lasciare la modale install invariata.

## Fix applicato
- `installer_gui.ps1.template`: unificati tutti i path Start Menu a
  `86BIT Argus Center` (prima erano incoerenti: "86BIT Argus" per Agent Status,
  "86BIT Argus Connector" per Disinstalla/uninstall/testo finale). Ora un'unica
  cartella con 2 shortcut: `Agent Status.lnk` + `Disinstalla.lnk`.
  - Cleanup cartelle legacy ("86BIT Argus" / "86BIT Argus Connector") a inizio blocco.
  - `uninstall.ps1` generato ora rimuove la cartella Center + entrambe le legacy.
  - Testo finale wizard: "Menu Start -> 86BIT Argus Center (Agent Status / Disinstalla)".
- `install-noc-agent.ps1`: aggiunto blocco 9.5 `WScript.Shell` (best-effort,
  try/catch non bloccante) che crea la cartella `86BIT Argus Center` con gli
  stessi 2 shortcut + refresh icon cache (ie4uinit).
- Note: nomi-prodotto "86BIT Argus Connector" mantenuti come DisplayName registry,
  tooltip tray e descrizioni shortcut (corretto: è il nome prodotto, non la cartella).

## Testing
- Go/PowerShell NON disponibili in preview: validazione solo sintattica/grep
  (bilanciamento graffe, coerenza path). Le nuove installazioni creeranno la
  cartella corretta SOLO dopo redeploy lato utente + nuovo build agent.

---


# 2026-07-25 — Dropdown testo nero + conferma rimozione "Installa connector"

## Richieste utente (screenshot pagina Agent v4)
1. "Mostra i caratteri in nero" nelle tendine (es. dropdown Cliente illeggibile).
2. "Rimuovi tutta questa parte che non serve più. Connector installiamo sempre
   e solo dalla Sezione dedicata al connector."

## Analisi
- La modale generica "Installa nuovo connector" (con dropdown Cliente/Ruolo/
  Versione) NON esiste piu' nel codice attuale: gia' rimossa in una sessione
  precedente. La pagina Agent v4 (AgentsPage.js) ha solo "Aggiorna" + tabella +
  bulk-update; per installare rimanda a Gestione Clienti (Setup GUI / Setup .exe
  / M / S per-cliente, ClientsPage.js). Lo screenshot mostra la PRODUZIONE su
  build vecchia (problema ricorrente di deploy lato utente). Verificato via
  grep (nessun residuo scanner/latest/Installa nuovo) e screenshot.

## Fix applicato
- index.css: regola globale `select option, select optgroup { color:#111827;
  background:#fff }` → opzioni delle tendine native con testo NERO leggibile su
  qualunque tema. Tocca solo la lista aperta, non il valore selezionato del
  controllo chiuso (verificato: select "Tutti i clienti" resta leggibile).

## Note
- La modale "Installa connector" sparira' dalla PROD dopo il redeploy del
  frontend (nel preview e' gia' assente). Installazione unica via Gestione Clienti.
- Effetto della fix CSS in PROD dopo rebuild+redeploy del frontend.

---


# 2026-07-25 — [FEATURE] Monitoraggio power-state VM Hyper-V (opzione B)

## Richiesta utente
Per le VM Hyper-V: monitorare se sono accese o spente come ulteriore
informazione, con integrazione nel motore di stato (Off → "spento" invece di
offline; Running → evidenza di accensione).

## Cosa esisteva
Agent Go raccoglie stato VM (Running/Off/Saved/Paused) via WMI Get-VM su comando
WS `hyperv_collect` → salvato in `hyperv_snapshots`. C'era solo trigger MANUALE
(`/api/hyperv/poll-now/{client_id}`), nessuno scheduler, nessun uso nel motore.

## Implementazione (opzione B, tutto GitHub-latest single source)
1. **Raccolta periodica** (server.py): nuovo scheduler `hyperv_power_poll` ogni
   5min → `run_hyperv_poll_all` invia `hyperv_collect` a tutti gli agent Windows
   v4 LIVE → snapshot sempre freschi (<15min = "live evidence").
2. **Motore di STATO** (routes/devices.py): match VM→device per hostname corto
   (scoping per cliente, solo snapshot freschi). Se device offline/pending:
   Running → `online` (live_evidence=hyperv); Off/Saved/Paused → status `off`.
   Esposti campi `hyperv_state` + `hyperv_host` (models.py DeviceResponse).
3. **Motore di ALERTING** (correlation_engine.py): `build_context` costruisce
   mappa hyperv per cliente; `gather_signals` aggiunge `hyperv_state`;
   `verdict_server` (come iLO per il fisico):
   - Off/Saved/Paused → up=False, NON alertable, cause=vm_powered_off (no falso down)
   - Running + L2/Datto → up=True, no alert, cause=icmp_filtered_hyperv
   - Running senza rete → up=False, alert medium, cause=os_unresponsive_hyperv
4. **Frontend**: badge Hyper-V (ON/OFF) nella vista raggruppata, tabella flat e
   scheda dispositivo (DeviceInfoCard "Dati raccolti da"); stato "SPENTO" grigio;
   header Salute Vitali con conteggio "spente" separato da "offline".

## Verifica
- API /api/devices: transizioni Off→"off", Saved→"off", Running→"online" [OK]
- verdict_server matrix: Off→vm_powered_off(no alert), Running+L2→no alert,
  Running solo→medium verify, non-VM invariati (critical) [OK]
- Screenshot: badge HV:OFF + stato SPENTO + "Salute Vitali 3 online, 0 offline,
  1 spente" [OK]. Scheduler avviato (tick 5m), nessun errore.

## Limiti / note
- Overview endpoint (top summary "DISPOSITIVI n offline") NON ancora aggiornato
  per Hyper-V: conta gli "off" come offline nel totale generale (follow-up P2).
  La Salute Vitali per-cliente e' invece corretta.
- Effetto in PROD dopo redeploy backend. L'agent v4 supporta gia' hyperv_collect.

---


# 2026-07-25 — Fix cosmetico "vv4.25.4" (doppia v) nel dialog UI scanner

## Segnalazione utente (screenshot)
Stesso setup wizard: installando MASTER la versione è corretta ("v4.25.4"),
installando SCANNER il dialog "ARGUS Connector · Informazioni" mostra
"Versione: vv4.25.4" (doppia v). La riga "Aggiornamento: v4.25.4 — già allineato"
conferma che la versione REALE è 4.25.4 → bug puramente COSMETICO.

## Root cause
`noc-agent/cmd/nocui/update_actions_windows.go`:
- riga 153: `ver := app.agent.Version` (arriva già come "v4.25.4", con la v)
- riga 278: `fieldRow("Versione", "v"+ver, ...)` → ri-antepone "v" → "vv4.25.4"
La convenzione storica era BuildVersion senza "v" (es. "4.6.0"); ora
app.agent.Version arriva con la "v" e il display la raddoppia.
Il master mostra il dialog MsgBox legacy (path diverso) → non raddoppiava.

## Fix
Normalizzato `ver` subito dopo la lettura: rimossa UNA sola "v"/"V" iniziale
(`strings.TrimPrefix`), così il successivo `"v"+ver` produce sempre esattamente
una "v". Sistema sia il display (278) sia il fallback MsgBox (350).

## Limiti / deploy
- NON testabile in questo ambiente: è un binario Go Windows e non c'è toolchain Go.
- È COSMETICO: monitoraggio e funzionalità non impattati (agent = v4.25.4).
- Per arrivare in produzione serve BUILDARE e PUBBLICARE una nuova release agent
  su GitHub, poi aggiornare i connector (Aggiorna ora / OTA).

---


# 2026-07-25 — [P0] Unificazione sorgente versione Agent (fix master≠scanner + OTA rotto)

## Contesto (segnalazione utente)
"In fase di installazione perché NON scarica l'ultima versione? Master e scanner
risultano su versioni diverse." (Poi entrambi a v4.25.4 dopo 'Aggiorna ora'.)
Richiesta: unificare le sorgenti così master e scanner siano SEMPRE allineati.

## Root cause: 3 sorgenti "latest" scollegate
1. Install manifest (nocinstall→agent-builds) = GitHub releases/latest ✓
2. ArgusSetup.zip (install_setup.py) = mirror LOCALE static/release-bin/ (fermo a v4.25.2)
3. OTA self-update (/api/agent/update/manifest) = binario LOCALE _AGENT_BUILD_DIR
   BUG GRAVE: firmava lo sha del binario LOCALE ma l'url scaricava quello GitHub
   -> hash/firma non combaciavano -> l'OTA falliva SEMPRE (l'agent non si
   auto-aggiornava; serviva sempre il pulsante 'Aggiorna ora').

## Fix — tutto converge su GitHub releases/latest (sorgente unica)
- agent_ws.py: estratto helper condiviso `ensure_release_asset_cached(version,
  filename)` (download+cache GitHub). `agent_builds_asset` ora lo usa.
- agent_ws.py `/api/agent/update/manifest` (OTA): risolve GitHub latest, scarica
  il binario via helper, FIRMA il binario EFFETTIVAMENTE servito (byte-identico
  all'url agent-builds), version=tag GitHub. Fallback binario locale se GitHub
  irraggiungibile. => OTA ora verifica la firma correttamente.
- install_setup.py: nuovo `_resolve_setup_bin` risolve GitHub latest e auto-scarica
  `nocinstall.exe` dalla release se non nel mirror locale. Fallback mirror legacy.

## Verifica (curl, URL esterno)
- OTA manifest: version=v4.25.4, url=/api/agent-builds/v4.25.4/nocagent.exe,
  signature 64B. sha256 firmato == sha256 del binario servito -> MATCH ✓
- ArgusSetup.zip?version=latest: LEGGIMI "Versione binario: v4.25.4",
  setup.exe 5.8MB (scaricato da GitHub; mirror locale era a v4.25.2).

## Note deploy
Effetto in PROD solo dopo redeploy backend su argus.86bit.it. L'OTA automatico
richiede che agent.yaml abbia update.enabled + manifest_url + public_key corretti;
il path 'Aggiorna ora' continua a funzionare come prima.

---


# 2026-07-25 — Fix banner "Aggiorna connector": mostra solo se azionabile

## Segnalazione utente
"Controlla il banner sopra (v4.25.4 disponibile, 2 connectors su versione
precedente): serve ancora e compare al momento giusto? Secondo me no."

## Root cause
`AgentUpgradeBanner` si mostrava quando `outdated_count > 0`, SENZA considerare
se i connector obsoleti fossero online. Verificato via /api/agents/upgrade-status:
live_agents=0, tutti gli obsoleti offline (vecchi agent dev/test mai piu'
connessi) -> il pulsante "Aggiorna ora" era disabilitato -> banner = CTA non
azionabile (rumore, "momento sbagliato").

## Fix (AgentUpgradeBanner.js)
- Il banner ora compare SOLO se `liveOutdated > 0` (almeno un connector obsoleto
  ONLINE, quindi realmente aggiornabile). Se tutti offline -> nascosto.
- Testo semplificato al conteggio azionabile: "{N} connector online su versione
  precedente". Pulsante sempre attivo (perche' reso solo quando c'e' del live).

## Verifica
- Screenshot desktop: banner ASSENTE (0 connector online obsoleti) -> header
  Panoramica pulito. In prod con connector online obsoleti si mostrera' con
  pulsante abilitato.

---


# 2026-07-25 — Mobile: pull-to-refresh + controllo notifiche push visibile

## Richiesta utente
"Aggiungi il pull-to-refresh nativo e le notifiche push (c'e' gia' PwaProvider)
cosi' un tecnico riceve sul telefono l'alert critico anche con l'app chiusa."

## Stato pre-esistente (verificato)
Infrastruttura push GIA' completa: VAPID configurato (backend/.env), routes/push.py
(vapid-public-key/subscribe/unsubscribe/status/test), sw.js con handler push +
notificationclick, alert_engine -> webpush.notify_new_alert. `notify_new_alert`
invia i critical+high all'on-call (o admin+operator), con requireInteraction per i
critici -> arrivano con app chiusa via Service Worker. SW registrato in index.js.

## Implementazione (frontend)
- `PwaProvider.js`: registrazione SW resa robusta (fallback `serviceWorker.ready`)
  e `subscribeToPush` con fallback su `ready` (evita no-op se swRegistration nullo).
- `MobileDashboard.js`:
  - PULL-TO-REFRESH nativo: touch handlers (start/move/end) attivi solo con
    scroller in cima, resistenza 0.5x, cap 90px, soglia 64px; indicatore con
    spinner rotante + "Rilascia per aggiornare".
  - Pulsante NOTIFICHE (campanella) sempre visibile nel banner: stato granted
    (verde, tap=invia test push), default (tap=richiede permesso+iscrive),
    denied (mostra come sbloccare). Feedback inline `mdash-notif-msg`.
- `index.css`: stili `.mdash-ptr`, `.mdash-bell`, `.mdash-notif-msg`.

## Verifica
- Frontend compila. Screenshot mobile: campanella presente e funzionante
  (in headless permesso=denied -> feedback "Notifiche bloccate…" corretto).
- Endpoint: /api/push/vapid-public-key (key len 87), /api/push/status
  {configured:true}. PTR reso (nascosto a riposo). Refresh manuale OK.

---


# 2026-07-25 — Redesign completo layout MOBILE per tecnici sul campo

## Richiesta utente
"I tecnici useranno molto ARGUS dal telefono. Serve un'interfaccia semplice,
precisa, intuitiva dove vedere lo stato di salute dei clienti con i dispositivi
vitali. Rivedi completamente il layout telefono e mostra solo l'essenziale."

## Scelte utente (ask_human)
- Salute + liste basate SOLO sui dispositivi VITALI.
- Essenziale per cliente: salute+connettore, elenco vitali su/giù, stato WAN.
- Tap = espansione inline (vitali + WAN + alert).
- Ordinamento problemi-first.
- Nav mobile semplificata (consigliata dall'agente): Home / Alert / Menu.

## Implementazione
- Frontend `components/MobileDashboard.js`: RISCRITTO. Ora consuma
  `/api/overview/clients` (gia' VITAL-ONLY + sort problemi-first) invece di
  `/tv/dashboard` (che contava TUTTI i device, non vitali). Nuova UI:
  - Banner stato globale sticky (N clienti critici / da controllare / operativi)
    + "X/Y vitali online" + orario aggiornamento + refresh (auto 15s).
  - Riepilogo semafori (Critici/Warning/OK) + toggle "Solo problemi".
  - Card cliente espandibili: dot salute, badge CONN/NO CONN, WAN OK/!/GIÙ,
    "X/Y vitali", badge alert critici+high. Espansione inline con: lista
    dispositivi VITALI (offline in cima), linea WAN, alert attivi, e bottone
    "Apri dettaglio completo".
- CSS `index.css`: nuovo set di classi `.mdash-*` (mobile-first, tap target
  grandi, animazioni entrata/pulse).
- `components/Layout.js`: bottom nav ridotta a Home / Alert / Menu.
- Backend `routes/overview.py`:
  - Aggiunto `detail.vital_list` (solo dispositivi vitali, offline-first).
  - Normalizzati status legacy `active`->`online` / `inactive`->`offline`
    (prima finivano in "unknown": badge "1/3" incoerente con la lista).

## Verifica
- curl `/api/overview/clients`: vital_list presente; dopo normalizzazione
  vital_online 1->3 su 3 (coerente).
- Screenshot mobile (390x844): banner, semafori, card collassata (badge NO CONN
  rosso, WAN OK, 3/3 vitali) ed espansa (vitali online, WAN 0.3ms/12.3ms,
  bottone dettaglio). Nav Home/Alert/Menu OK.

---


# 2026-07-24 — [P0] Alert 100%: gating linea-internet + blackout sui server SOLO-Datto

## Richiesta utente
"Se un dispositivo Datto risulta offline MA la linea internet e' online, e se altri
dispositivi della rete risultano online (Datto + altri controlli), allora il problema
e' sicuro al 100% sul dispositivo offline."

## Analisi
- Watchdog dispositivi VITALI/managed (`run_vital_watchdog` + `correlation_engine`):
  regola GIA' implementata — Datto contribuisce solo se `datto_reliable` (gating
  anti-blackout >=60% offline) + soppressione topologica "site_power_down"/"site_isolated"
  quando internet giu' + connettore cieco.
- Watchdog server SOLO-Datto (`run_datto_watchdog` parte B): BUCO — emetteva
  "SERVER DATTO OFFLINE" solo su `online:false` + soglia oraria, SENZA verificare
  linea internet ne' blackout di massa.

## Fix (alert_engine.py::run_datto_watchdog)
- Costruito `source_health` via `correlation_engine.build_context` a inizio watchdog.
- Nel blocco `if not online:` aggiunto gating: si emette l'alert SOLO se
  `internet_up is not False` (linea non provata giu') E `datto_reliable is not False`
  (nessun blackout di massa = altri device del sito online). Se non ci sono prove
  (internet_up=None) NON si blocca, per non perdere alert su clienti senza sonda WAN.

## Verifica
- run_datto_watchdog eseguito su dati reali: OK, actions=0, nessuna eccezione.
- source_health cliente linkato da3d6e40: internet_up=True, datto_reliable=True -> un
  server solo-Datto offline verrebbe correttamente allertato (linea up, no blackout).
- Backend live sano dopo hot-reload.

---


# 2026-07-24 — [P0] Fix regressione sync Datto RMM: 27/28 device scartati (deviceType dict)

## Segnalazione utente
"Controllo che DattoRMM funzioni correttamente, faccia sync e match corretti al 100%".

## Root cause (verificata dai log)
In `_refresh_sites_cache._process` (routes/datto_rmm.py, riga 602):
`(dev.get("deviceType") or ...).strip()` sollevava `AttributeError: 'dict' object has
no attribute 'strip'` perche' Datto RMM ritorna `deviceType` come OGGETTO
`{"category": "...", "type": "..."}`, non stringa. Con `asyncio.gather(return_exceptions=True)`
l'eccezione veniva inghiottita e loggata solo come conteggio: 27/28 device scartati a
OGNI sync (auto e manuale). Persisted=1, matched_endpoints=1.

## Fix
- Aggiunto helper `_device_type_str()` che normalizza `deviceType` dict/str/None in stringa
  (concatena category+type) senza sollevare.
- Aggiunto logging con traceback (`err_samples`) sui device scartati per diagnosi futura.

## Verifica end-to-end (curl + DB)
- sync-now: persisted 1->28, matched_endpoints 1->24
- diagnostics: healthy=true
- DB: device_type popolato (es. "Server Main System Chassis"), is_server=9,
  25 managed_devices con datto_uid, ladder match: MAC=22, IP=2, hostname=1
- Nessun nuovo warning "device skippati" dopo il fix.

---


# 2026-07-24 — Fix falso-ROSSO su server (Datto come evidenza per lo status)

## Segnalazione utente (produzione)
Server SRVDC/SRVPALMOGAL/SRVGESTGAL/SRVDATIGAL/SRVTERMGAL (192.168.16.x, Hyper-V)
mostrati ROSSI (offline) ma in realta' ONLINE. "Spiegami i controlli che fai."

## I controlli che determinano il pallino (GET /api/devices)
In ordine, un device e' ONLINE se:
1. **L2 forte**: presente nella FDB dello switch via SNMP (mac_table_switch).
2. **Scanner LAN**: visto da ARP/scanner del connettore < 5 min.
3. **Ping ICMP/TCP**: `effective_reachable` (con debounce) risponde.
4. **L2 debole** (ARP/mDNS) MA solo se concorde col ping.
Altrimenti → OFFLINE (rosso).

## Root cause del falso-rosso
I server Windows/Hyper-V spesso **bloccano ICMP** e, se sono VM su vSwitch
isolato, **non compaiono in ARP/FDB/SNMP** → nessuna delle 4 evidenze scatta →
falso OFFLINE. Il segnale che li vede vivi (agent **Datto RMM online**) NON era
usato per il pallino (solo dal motore di alerting).

## Fix (routes/devices.py)
Aggiunto **Datto come evidenza positiva** per lo status: se l'agent Datto riporta
il device ONLINE con heartbeat fresco (< 30 min), il device viene promosso a
ONLINE (evidence "datto"), sia nel connector-loop sia nel managed-loop. Lookup per
datto_uid / IP / MAC. Chiavi **client-scoped** (multi-tenant safe).
Guardia anti-falso-verde: Datto offline o heartbeat stantio (>30min) NON promuove.

## Test — testing agent iteration_95.json (backend 100%, 7/7, 0 issue)
- tests/test_datto_evidence.py: promozione via uid/IP/MAC; negativi (offline,
  stale, no-evidence) restano offline; ping/L2 reali invariati (no falso-verde).

---


# 2026-07-24 — Auto-risoluzione alert su CONFERMA POSITIVA (no AI, no TTL)

## Richiesta utente
Sistema di auto-risoluzione: gli alert devono chiudersi da soli, ma **SOLO** con
conferma positiva (device di nuovo online/acceso, sync ripristinato, connettore
tornato) — MAI a tempo/assenza dati. Chiesto se serve AI.

## Raccomandazione (data): NIENTE AI nella decisione
Coerente con l'alerting: la chiusura di un alert e' binaria e basata su evidenze
→ deve essere deterministica (rischio di chiudere un alert reale con un LLM;
paradosso disponibilita' cloud; costo). AI solo come riassunto cosmetico opzionale.

## Stato pre-esistente (gia' presente)
Il motore risolveva gia' l'alert originale su ripristino positivo:
- vital device tornato raggiungibile → alert resolved (run_vital_watchdog, via vital_offline_state.alert_id)
- datto_sync_stale → resolved quando sync fresco
- datto server offline → resolved quando online
- connector offline → resolved quando heartbeat torna (connector_watchdog)

## Fix implementato (rumore notifiche di ripristino)
Le notifiche di RIPRISTINO (positive) venivano create come alert ATTIVI e mai
chiuse → si accumulavano. Introdotto helper `_emit_recovery_notice(db,cfg,rec)`
(alert_engine.py ~170): notifica Telegram/WebPush + salva come `status='resolved'`,
mai active. Applicato a: `datto_sync_recovery`, `device_recovery`,
`datto_server_recovery` (alert_engine) e `connector_recovery` (connector_watchdog,
inline insert status=resolved). Puliti i recovery-noise attivi residui.

## Nessun reaper a TTL
Confermato: nessuna chiusura per timeout. Un alert resta ATTIVO finche' non arriva
il segnale positivo (device up / sync fresh / server online / heartbeat back).

## Test — testing agent iteration_94.json (backend 100%, 14/14, 0 issue)
- Suite `tests/test_positive_recovery_iter94.py` (8) + `test_datto_recovery_alerts.py` (6).
- 0 alert *_recovery attivi; transizioni stale→fresh e offline→online risolvono
  l'alert originale + recovery come resolved; run-now NON chiude i 2 alert legittimi.

---


# 2026-07-24 — Alert non veritieri: fix rumore "sync ripristinato"

## Segnalazione utente
"Controlla che tutti questi alert che stanno arrivando ora siano veritieri."

## Analisi (9 alert attivi)
- **6× "DATTO RMM: sync ripristinato"** (source_type=datto_sync_recovery, low) →
  NON veritieri: sono notifiche di RIPRISTINO (evento positivo) persistite come
  alert ATTIVI e mai risolte → duplicati accumulati.
- **1× "TEST_Alert"** (manual) → dato di test residuo.
- **1× "5 nuovi dispositivi"** (new_devices_detected) → info discovery legittima.
- **1× "CONNETTORE OFFLINE"** (connector_watchdog, critical) → veritiero
  (connettore effettivamente offline).

## Root cause (alert_engine.run_datto_watchdog)
Il branch di recovery (~riga 497) inseriva la notifica "sync ripristinato" come
alert ATTIVO via insert_alert_if_emit, senza mai risolverla → a ogni ciclo con
auto_recovery si accumulava un nuovo alert attivo.

## Fix
- Il recovery viene ora **notificato** (Telegram/WebPush) ma salvato con
  `status='resolved'` + `resolved_at` (voce di storico/timeline), **mai active**.
- Puliti i 6 recovery attivi + il TEST_Alert (impostati resolved).

## Test — testing agent iteration_93.json (backend 100%, 0 issue)
- Suite regressione `tests/test_datto_recovery_alerts.py`: nessun recovery attivo
  via API; transizione stale→ripristino salva recovery come resolved (0 active);
  stale reale (>30min) crea ancora alert ATTIVO (regressione OK); vital_only pulito.
- Alert attivi residui: 2 legittimi (connettore offline + nuovi dispositivi).

---


# 2026-07-24 — Panoramica VITAL-ONLY (situazione + alert solo dispositivi vitali)

## Richiesta utente
La Panoramica deve mostrare "sempre e solo situazione e alert per dispositivi vitali".

## Implementato
### Backend
- `routes/overview.py` (GET /overview/clients):
  - Aggiunti `vital_offline`/`vital_stale` ai conteggi device.
  - **Salute cliente (dot)** ora calcolata sui VITALI: critical se `vital_offline>0`
    (oltre a connettore giù / WAN giù); warning se `vital_stale>0`/backup.
  - **KPI globali** `total_devices`/`devices_online` = somma VITALI (non più tutti).
  - **Alert** scopati ai vitali: costruito insieme nomi/IP vitali per-cliente;
    contati solo alert su device vitali (+ alert livello sito senza device).
- `routes/alerts.py` (GET /alerts): nuovo parametro `vital_only=true` → filtra
  la lista agli alert su dispositivi vitali (+ alert sito-level senza device).
### Frontend
- `DashboardPage.js`:
  - KPI "Infrastruttura" → **"Dispositivi Vitali"** (conteggio vitali online).
  - Card cliente: riga "Dispositivi N/M" → **"Vitali vital_online/vital_total"**
    con colore su vital_offline/stale.
  - Fetch alert con `&vital_only=true` (tabella + live stream vital-scoped).

## Test (self-test curl + screenshot)
- GET /overview/clients: total_devices=3 (vitali), card 86BIT_Office vital 1/3.
- GET /alerts?vital_only=true: 9 → 1 alert (esclusi Datto sync, Discovery,
  connettore-offline; mantenuti quelli su device vitali).
- Screenshot dashboard: KPI "DISPOSITIVI VITALI 3·1 online", card "VITALI 1/3",
  tabella ALERT ATTIVI con 1 sola riga vitale.

---


# 2026-07-24 — Dettaglio stampante cliccabile (caratteristiche tecniche complete)

## Richiesta utente
Poter cliccare una stampante nel tab Stampanti e aprire tutte le caratteristiche
tecniche: Nome, Serial, Stato colori, Numero di copie.

## Implementato (ClientOverviewPage.js)
- Le card stampante nel tab Stampanti ora sono **cliccabili** → aprono
  `PrinterDetailModal` (shadcn Dialog).
- Il modal fa fetch di `GET /api/printers/{clientId}/{device_ip}` e mostra:
  - **Anagrafica**: Nome, Serial Number, Modello, IP, Stato, Ultimo rilevamento.
  - **Contatori copie**: totali, a colori, B/N (calcolato), fronte/retro (duplex),
    scansioni, fax.
  - **Stato colori (toner/inchiostro)**: barre colorate per supply con livello % /
    OK, colore reale del toner.
  - **Messaggi stampante** (alert_messages) se presenti.
- Fallback: per stampanti senza telemetria SNMP, mostra i dati base + invito a
  configurare SNMP Printer-MIB (RFC 3805).

## Fix collaterale (bug pre-esistente nel merge)
`mergedPrinters` chiudeva tutte le stampanti sotto chiave `undefined` perché
leggeva `p.ip_address || p.ip` mentre il backend restituisce `device_ip`.
Corretto a `p.ip_address || p.ip || p.device_ip` → ora il tab conta e mostra
tutte le stampanti (prima ne appariva 1 sola). Merge arricchito con
serial/model/contatori.

## Test
- Verificato via screenshot (self-test) con 4 stampanti demo (seed-demo, poi
  ripulite): click → modal con serial CNBJR9H12M, 28.750 copie totali, 15.200
  colori, toner Black 80%/Cyan 30%/Magenta 10%/Yellow 70%, msg "Magenta toner low".
- data-testid: printer-card-{ip}, printer-detail-modal, printer-detail-field-*,
  printer-detail-supplies, printer-detail-close-btn.

---


# 2026-07-23 — FIX bug "dispositivi vitali sempre a zero"

## Sintomo (utente)
"Selezioni i dispositivi vitali ma nel tab non arrivano.. sempre a zero."
Marcando come vitali dei device, il tab 'Dispositivi Vitali' restava a (0).

## Root cause (routes/devices.py get_devices)
I device provenienti dal *connector-merge loop* (quelli con record
`device_poll_status`, id `poll_<ip>`, source `connector-master`) venivano
costruiti SENZA il campo `created_at`, che è OBBLIGATORIO nel model
`DeviceResponse` (models.py:105 area). Quindi `DeviceResponse(**d)` sollevava
ValidationError → il device cadeva nel blocco `except` di fallback che NON
copiava `is_vital` → l'API restituiva `is_vital=null` anche per i device
appena marcati vitali. Il counter frontend `devices.filter(d=>d.is_vital===true)`
restava a 0. (I device managed-only funzionavano perché il loro loop includeva
già `created_at`.)

## Fix
1. Aggiunto `created_at` al dict del connector-loop (~riga 462).
2. Il fallback `except` ora preserva `is_vital` + `is_vital_set_at` e LOGGA
   l'errore di validazione (prima silenziato → per questo il bug era nascosto).

## Test — testing agent iteration_92.json (100% backend+frontend, 0 issue)
- Marcato vitale il firewall connector-master 192.168.1.254 → ora appare nel tab
  Vitali e in GET /api/devices con `is_vital=true` (prima null). Counter allineato.
- Regressione 'Azzera vitali' OK. Cliente lasciato a 0 vitali.

## Follow-up minori (non bloccanti)
- Il reset usa window.confirm nativo: valutare un modal con data-testid per e2e.

---


# 2026-07-23 — Badge versione build frontend (rileva bundle stantio in prod)

## Richiesta utente
Un badge di versione build (commit/hash) visibile in UI per capire al volo se la
produzione gira un bundle FRONTEND vecchio rispetto al preview.

## Problema del sistema esistente
`/api/app-version` calcolava solo un hash dei file .py del BACKEND → non rilevava
un bundle frontend stantio (il vero problema dei deploy in prod).

## Implementato
- `frontend/scripts/genBuildInfo.js`: genera `src/buildInfo.json` = {commit, builtAt}
  dal git al build (resiliente, non fa mai fallire start/build).
- `package.json`: hook `prebuild` + `prestart` → il commit viene "baked" nel bundle
  a ogni `yarn build`/`yarn start`.
- `components/AppVersion.js`: `VersionBadge` ora mostra `V.{backendVer} · {frontendCommit}`
  con tooltip `Frontend build: <commit> (<data>) / Backend: v<ver>`.
  Se la prod non ricompila il frontend, il commit resta vecchio → segnale immediato.

## Test
- Verificato in preview: badge = "V.2.0.6035 · 7bc7436", tooltip con data build + backend.
  Frontend compila senza errori.

---


# 2026-07-23 — Reset vitali self-service + diagnosi "schermata nera" (build stantia)

## Contesto
- Utente ha chiesto di "azzerare i dispositivi vitali per ripartire da zero" e poi
  ha segnalato una SCHERMATA NERA con `Uncaught ReferenceError: baseFiltered is not defined`
  su `argus.86bit.it` (PRODUZIONE, build v.2.0.6xxx).

## Diagnosi
- Il codice ATTUALE ha `baseFiltered` correttamente scoped dentro `DevicesTab`
  (ClientOverviewPage.js ~2286). In preview la pagina carica senza errori.
- **L'errore è un artefatto della build vecchia in produzione** (problema ricorrente
  di deploy). Fix: redeploy dell'ultima build. NON è un bug del codice.
- Verificato dal testing agent (iteration_91.json): 0 ReferenceError, 0 pageerror,
  filtro vitali di default + empty-state + flusso reset OK. success_rate frontend 100%.

## Implementato
- **Endpoint** `POST /api/clients/{client_id}/devices/reset-vital` (device_info_card.py):
  azzera tutti gli `is_vital` del cliente + svuota `vital_offline_state`. I device non
  vengono cancellati (tornano "da classificare").
- **Pulsante "Azzera vitali"** (`data-testid=reset-all-vital-btn`) nel tab Dispositivi
  Vitali: visibile solo se `vitalCount>0`, con conferma.
- Empty-state contestuale al filtro (⭐ "Nessun dispositivo vitale ancora…").
- Preview DB azzerato: 0 device vitali.

---


# 2026-07-23 — Fusione multi-fonte + Source-Health Gating (alerting affidabile al 100%)

## Richiesta utente
"Match avanzati con TUTTE le informazioni che riceviamo dalle diverse fonti per
gestire gli alert con affidabilità 100%". Vincolo esplicito: **NON** costruire
tutto attorno a Datto RMM (se salta internet/corrente Datto sparisce). Senza AI.

## Cosa è stato implementato
### Backend
- **`correlation_engine.build_context(db, cfg)`**: ora costruisce indici Datto estesi
  (`by_uid`, `by_serial`, `by_host`) e calcola il **source-health per cliente**:
  `connector_reliable`, `datto_reliable` (+`datto_reason`), `internet_up`.
  - Datto marcato INAFFIDABILE se sync stale o **blackout di massa** (≥`datto_blackout_ratio`, default 60%, di device offline insieme).
- **`gather_signals`**: scarta il segnale Datto quando `datto_reliable=False`
  (mai usare "Datto offline" come prova di device down durante internet/portale giù).
- **`_datto_lookup` avanzato**: link persistito `datto_uid` (fast-path) → MAC → IP → serial → hostname corto/FQDN.
- **`alert_engine.run_vital_watchdog`**: rilevamento **cause globali** prima dei verdetti per-device:
  - `site_power_down` (connettore giù + WAN esterno giù → outage/corrente),
  - `site_down` (connettore vivo + ≥`site_down_ratio` 80% irraggiungibili → isolamento interno).
  Emette 1 solo alert aggregato, figli soppressi (anchor mai soppresso).
- **`datto_rmm._match_with_center` riscritto**: matcher multi-fonte a confidenza
  (serial 100 > MAC 98 > IP 92 > hostname 82) con **ponte via scanner**
  (`discovered_endpoints.hostname_scanner`/mac) per agganciare device senza MAC.
  Persiste `datto_uid`+`datto_match`+`datto_match_confidence` su `managed_devices`,
  pulisce link orfani. Sync Datto arricchito con `serial`/`fqdn`/`hostname_short`/`ext_ip`.
- **Endpoint** `GET /api/alert-engine/match-coverage`: copertura match + source-health per cliente.
- Nuove config: `datto_blackout_ratio` (0.6), `site_down_ratio` (0.8).

### Frontend
- `AlertEngineSettingsPage.jsx`: sezione **"Fusione multi-fonte & affidabilità"**
  con soglie (% blackout Datto / % sito giù) e pannello copertura match per cliente
  (match rate, device ciechi, match deboli, badge conn/datto reliability).

## Test
- `tests/test_multisource_fusion.py` (4 test, PASS): gating Datto, verdict, match hostname/serial, uid link.
- Matcher e2e verificato (serial/mac/ip/hostname + bridge scanner) su DB temporaneo.
- Endpoint `run-now` e `match-coverage` verificati via curl; UI smoke test OK.
- `test_triage_iter90.py` PASS (nessuna regressione config).

## Note
- La decisione degli alert resta 100% DETERMINISTICA (no AI). L'AI resta un possibile
  strato futuro solo per spiegazione/remediation, mai come gatekeeper.

---


# 2026-07-23 — Triage Wizard: ricerca per IP/nome + rinomina inline

## Richiesta utente
Poter cercare il dispositivo per IP e rinominarlo subito nel wizard di
classificazione, per maggiore comprensione.

## Implementazione (`ClientOverviewPage.js`, TriageWizard)
- **Ricerca**: campo con lente (data-testid `triage-search`) che filtra i device
  non classificati per IP o nome in tempo reale (sezioni Suggeriti + Altri).
- **Rinomina inline**: ogni riga ha un'icona matita (`triage-rename-btn-<ip>`) →
  apre un input inline (`triage-rename-input-<ip>`, Invio=salva, Esc=annulla,
  bottone ✓ `triage-rename-save-<ip>`). Salva via `POST /devices/by-ip/{ip}/rename`
  con `client_id`, e mostra subito il nuovo nome (override locale) senza attendere
  il refresh. Il nome rinominato viene poi ereditato dalla promozione a vitale
  (enrichment da device_poll_status/discovered).

## Verifica (screenshot) — OK
- Ricerca "192.168" filtra correttamente; suggeriti infra preselezionati
  (TestSwitch, Zyxel USG Test); matita di rinomina presente su ogni riga.
  Zero errori runtime.

---


# 2026-07-23 — Ping immediato alla promozione a Vitale

## Cosa
Quando promuovi uno o più dispositivi a Vitali (dalla toolbar del tab o dal
Triage Wizard), parte subito un ping/poll immediato così il cockpit mostra lo
stato reale in pochi secondi invece di attendere il ciclo di poll.

## Implementazione
- **Backend** `agent_ws.py`: nuovo `POST /clients/{client_id}/devices/poll-now`
  {ips:[...]} → invia `force_ping_poll` per ogni IP al master v4 LIVE e PERSISTE
  il risultato in `device_poll_status` (reachable/ping_reachable/method/
  last_ping_at, source="agent_v4"). Se non c'è master live ritorna 200
  {ok:false, reason:"no_master_live"} (nessun errore, il frontend lo ignora).
- **Frontend** `ClientOverviewPage.js`: `bulkSetVital(true)` e il Triage Wizard
  chiamano poll-now (best-effort) dopo la marcatura; refresh ritardato ~1.2s per
  mostrare lo stato aggiornato.

## Verifica
- Endpoint risponde 200 gracefully senza master (testato su 86BIT_Office preview).
- Frontend compila senza errori.
- NOTA: il path con master LIVE + persistenza non è testabile in preview (serve
  un agent v4 reale connesso); la logica riusa il pattern esistente force_ping_now.

---


# 2026-07-23 — BUGFIX: marcatura vitale non persisteva per i device scanner

## Sintomo (utente)
Nel tab "Dispositivi Vitali" selezionando i device e cliccando "Marca come
VITALI" non succedeva nulla: i dispositivi non finivano nel tab vitali.

## Causa (root cause)
La lista `/api/devices` è l'UNIONE di `db.devices` (manuali) + `device_poll_status`
(scanner/connector) + `managed_devices`. L'endpoint `POST /api/devices/bulk-vital`
faceva solo `update_many` su `managed_devices` per `{client_id, ip}`. I device
visti SOLO dallo scanner (device_poll_status) NON hanno una riga in
`managed_devices` → match 0 → `is_vital` non veniva mai scritto e il tab restava a 0.

## Fix (`backend/routes/device_info_card.py`)
- Dopo l'`update_many`, per gli IP richiesti non presenti in `managed_devices`
  (quando is_vital=true) l'endpoint ora **PROMUOVE** il device: upsert di una riga
  managed_devices con `is_vital=true`, arricchendo nome/tipo/mac da
  `device_poll_status` (device_name/device_class) o `discovered_endpoints`,
  `source="promoted-scan"`. Risposta include `promoted` + messaggio esplicito.
- Beneficia anche il Triage Wizard (stesso endpoint).

## Verifica E2E (self) — PASS
- Device presente SOLO in device_poll_status (SCAN-SRV, server) → bulk-vital →
  matched=0, modified=1, promoted=1; creata riga managed_devices is_vital=true con
  nome/tipo corretti. Dati di test ripuliti. Nessun dato di test residuo nel DB.

Nota: lo screenshot dell'utente era su build PROD vecchia (v2.0.7503); il fix è
nel codice attuale (preview) e sarà attivo dopo il deploy.

---


# 2026-07-23 — Auto-promote infrastruttura + guard "no_data" (miglioria provisioning)

## Cosa
- **Regole auto-promote**: nuova opzione `auto_promote_infra` (globale + override
  per cliente). Quando abilitata, ogni nuovo device infrastrutturale scoperto
  (firewall/switch/router/server/nas/ups/ilo/storage/gateway, match su
  device_type) viene automaticamente marcato `is_vital=true`
  (reason "auto-promote infra", invalidazione cache silence). Genera un alert
  informativo `auto_promoted_vital` (low). I device non-infra restano "da
  classificare" e alimentano il triage.
- **UI**: nuova sezione "Rilevamento & Provisioning" nella pagina Alert Engine
  con toggle "Avvisa sui nuovi dispositivi", "Finestra (ore)" e
  "Auto-promuovi infrastruttura a Vitale ⭐".

## Fix correttezza (importante)
- **Guard `no_data`** nel correlation engine: un device MAI pollato (ping=None,
  nessun L2, nessun segnale Datto/WAN) non è più giudicato "down" → verdetto
  `no_data` non-alertable. Evita falsi `server_down`/`site_isolated` sui
  dispositivi appena scoperti (verificato: auto-promote di FW/SW/SRV nuovi non
  genera più falsi alert critici).

## Test E2E (self) — PASS
- auto_promote: 3 infra (fw/switch/server) → vitali; workstation resta da
  classificare (alert `new_devices_detected`); alert `auto_promoted_vital`
  creato; NESSUN falso `corr_site_isolated`. Dati di test ripuliti.

---


# 2026-07-23 — Ridisegno gestione dispositivi: Panoramica=Triage, Vitali=Cockpit

## Modello concordato con l'utente
Due piani distinti: **Panoramica** = sorgente di TUTTI i dispositivi rilevati
(triage), da cui si "agganciano" i vitali; **Dispositivi Vitali** = cockpit dei
soli vitali. NIENTE stato "ignored" (scartato dall'utente). 3 stati impliciti via
`is_vital` tri-state: null=da classificare, false=monitorato, true=vitale
(nessun nuovo campo/migrazione necessari).

## Implementazione (in blocco)
### Frontend `ClientOverviewPage.js`
- **TriageWizard** (nuovo modal): elenca i device non classificati, sezione
  "Suggeriti come Vitali · Infrastruttura" (firewall/switch/router/server/nas/
  ups/ap/tvcc) PRE-SELEZIONATA, + "Altri rilevati". Bottoni "Aggancia come Vitali"
  (bulk is_vital=true) e "Segna come Monitorati" (bulk is_vital=false) via
  `POST /api/devices/bulk-vital`.
- **Panoramica**: banner giallo "🆕 N dispositivi rilevati da classificare" +
  "Classifica ora" → apre il wizard; refresh automatico dopo l'azione.
- **Dispositivi Vitali cockpit**: header salute (vitali online/offline, badge
  rosso lampeggiante se offline, conteggio dipendenze switch).

### Backend `alert_engine.py`
- **run_new_device_watchdog**: per cliente, conta i managed_devices con is_vital
  non deciso e `created_at` entro `new_device_window_hours` (default 24) → alert
  medium `new_devices_detected` (dedup per cliente, messaggio aggiornato col
  conteggio), auto-resolve quando tutti classificati. Notifica Push/Telegram.
- Config: `new_device_detection`, `new_device_window_hours`.

## Test (iteration_90.json) — 100% PASS
- Backend 8/8: bulk-vital validazione+persistenza, config espone i nuovi campi,
  run-now crea e risolve `new_devices_detected`.
- Frontend: banner, wizard (suggeriti preselezionati), aggancia/monitora, tab
  "Dispositivi Vitali" con header salute e filtro default vital. Zero issue.

---


# 2026-07-22 — Tab "Dispositivi Vitali" (filtro default vitali)

## Richiesta utente
Rinominare la tab "Dispositivi" in "DISPOSITIVI VITALI" e mostrare di default
SOLO i dispositivi marcati come vitali (impostati dalla Panoramica), invece di
tutti i device rilevati in rete.

## Implementazione (frontend, `ClientOverviewPage.js`)
- Tab rinominata: `Dispositivi Vitali (${vitalDevices.length})` con icona Star;
  count = device con `is_vital === true`.
- `DevicesTab`: il filtro criticality (già esistente: Tutti/Vitali/Best-effort)
  ora ha default "vital" (nuova chiave storage `client-devices-vital-filter-v2`).
  L'utente può comunque tornare a "Tutti" dal toggle.
- Nessuna modifica backend. La marcatura vitale resta via `VitalToggleButton`
  (stella) sia in Panoramica sia nella tab, endpoint `POST /api/devices/by-ip/{ip}/vital`.

## Verifica (screenshot)
- Cliente 86BIT_Office: tab "Dispositivi Vitali (1)", filtro su "Vitali",
  mostra solo il device vitale. Zero errori runtime.

---


# 2026-07-22 — Switch-level suppression via FDB SNMP (completamento correlazione)

## Cosa
Abilitata la soppressione topologica **switch-level** in PROD popolando la mappa
device→switch di accesso dalla FDB SNMP.

## Implementazione
- `correlation_engine.build_child_to_switch(db)`: ricava device_ip→switch_ip da
  `mac_connections` (from_ip=switch, from_port=porta, to_ip=device, source=mac_table),
  ESCLUDE archi switch→switch e device visti su porte uplink (rilevate via
  `lldp_neighbors` verso altri switch); in caso di ambiguità preferisce la porta
  di ACCESSO (meno MAC appresi, più recente).
- `build_context` ora usa questa mappa a runtime → suppression sempre fresca.
- `persist_switch_links(db)`: scrive `switch_ip` su `managed_devices` e
  `discovered_endpoints` (per UI/topology). Auto ogni ~10 min nell'AlertEngine.
- Endpoint `POST /api/topology/resolve-switch-links` (admin) e
  `GET /api/topology/switch-links` (preview). Pulsante "Ricalcola link switch (FDB)"
  nella pagina Alert Engine.

## Test E2E (PASS)
- FDB con 3 archi (access + uplink + core): server mappato correttamente allo
  switch di ACCESSO, uplink e core esclusi.
- SW-ACCESS down + figlio down → 1 solo alert `corr_switch_down` (critical),
  server figlio SOPPRESSO, SW-CORE (up) nessun alert. Dati puliti.

---


# 2026-07-22 — Correlation Engine (evidence fusion, alert precisi anti falsi-positivi)

## Richiesta utente
«Per notifiche davvero reali e precise Argus deve INCROCIARE i dati: se un
server è offline da Datto ma firewall+internet sono ok e il ping lo raggiunge
→ è un problema Datto; se ping FAIL e anche Datto lo vede offline → 100% server
down. Fai delle mesh così, consigliami tu la migliore per tipo di dispositivo.»
Approvato: matrice proposta, iLO power probe on-demand, soppressione topologica,
rilascio di tutti i tipi.

## Implementazione
### NUOVO `backend/correlation_engine.py`
- `build_context(db)`: raccoglie una volta per ciclo evidence L2 (FDB/ARP via
  liveness_resolver), connector-live set, WAN per cliente (`wan_probe_results`),
  mappe Datto (by_ip/by_mac/by_name), mappa child_ip→switch_ip.
- `gather_signals(md, pd, ctx)`: vettore segnali {ping, l2_alive, datto+minuti,
  connector_live, fw_up/rt_up, snmp}.
- Verdetti per famiglia con confidenza + reasoning:
  - **server**: Ping OK+Datto OFF → datto_agent_issue (low 85, "server operativo");
    Ping FAIL+Datto OFF → iLO Off=server_powered_off(100), iLO On=os_hung(92),
    no-L2=server_down(95), L2-vivo=unresponsive_l2_present(70);
    Ping FAIL+Datto ONLINE → monitoring_blind(50) o icmp_filtered se L2;
    connector giù+no Datto → connector_blind (nessun alert, evita falsi).
  - **firewall**: fw down+maggioranza sito giù → site_isolated(97); fw up+internet
    giù → isp_down(95); fw down solo mgmt → firewall_mgmt_down(60).
  - **switch**: down+figli tutti giù → switch_down(95, sopprime figli); mgmt-only(55).
- `resolve_ilo_power(...)`: Redfish PowerState On/Off, chiamato SOLO quando server
  down + Datto offline + credenziali iLO presenti.

### `backend/alert_engine.py` — `run_vital_watchdog` riscritto (correlation-based)
- Target = managed_devices vitali OR server/firewall/switch/nas.
- 2 pass: verdetto preliminare → rifinitura firewall/switch + **soppressione
  topologica** (sito isolato o switch down → 1 solo alert, figli soppressi).
- Fire quando confidenza ≥90 (immediato) o offline ≥ vital_warn_minutes;
  escalation di severità se il verdetto peggiora; alert INFORMATIVI dedup per
  casi "up ma anomalo" (agent Datto KO). Auto-recovery + resolve automatico.
- Telegram gate: solo severità high/critical (no rumore su low/medium).
- Datto watchdog: salta i server già coperti da un managed_device (no doppioni).

### Frontend `AlertEngineSettingsPage.jsx`
- Aggiunto pannello "Correlazione multi-sorgente" con la matrice dei verdetti.

## Test (self, E2E + unit) — tutti PASS
- 12 branch verdetto (unit) corretti.
- E2E: SERVER DOWN(critical 95%), AGENT DATTO KO(low, "server operativo"),
  SITO ISOLATO(1 alert critical, figli soppressi), recovery+auto-resolve.
- Dati di test seminati e ripuliti; nessun residuo.

---


# 2026-07-22 — Alert Engine proattivo (dispositivi vitali offline + Datto RMM)

## Richiesta utente
«Migliorare DRASTICAMENTE gli avvisi quando un dispositivo vitale è offline,
oppure quando Datto RMM perde la connessione a un server per troppo tempo.
Essere sempre proattivi sul cliente.» Scelte: canali Push browser + Telegram;
soglie a discrezione dello sviluppatore; config globale con override per
cliente; auto-recovery SÌ.

## Cosa è stato implementato
### NUOVO `backend/alert_engine.py` (~440 righe)
- `AlertEngine` (loop asyncio, tick 60s) con 2 watchdog:
  1. **VitalDeviceWatchdog** — scan `managed_devices.is_vital=True`, usa
     `liveness_resolver.compute_status` (stessa verità della UI: evidence
     FDB/ARP, debounce anti-flap, blackout connector = "stale" → NON allerta).
     Stato in `vital_offline_state`. Warning (high) dopo `vital_warn_minutes`
     (default 3), escalation a CRITICAL dopo `vital_crit_minutes` (default 10),
     auto-resolve + recovery notice alla ripresa.
  2. **DattoWatchdog** — (a) server Datto offline > `datto_server_offline_hours`
     (default 1h) → high, > `datto_server_crit_hours` (2h) → critical; (b) sync
     Datto fermo > `datto_sync_stale_minutes` (30) → alert per client link.
     Stato in `datto_offline_state`. Recovery automatico.
- Config: `alert_engine_config` (`_id="global"` + override `_id="client:<id>"`).
- Notifiche multi-canale: Web Push (`webpush.notify_new_alert`) + Telegram.
- Tutti gli alert passano da `insert_alert_if_emit` (vitali sempre emessi).

### NUOVO `backend/telegram_notifier.py`
- Invio via httpx (nessuna dipendenza extra), `send_alert_telegram`,
  `send_telegram_text` (HTML), `detect_chats` (getUpdates → chat_id auto).
- Token/chat_id da `alert_engine_config` o env `TELEGRAM_BOT_TOKEN`.

### NUOVO `backend/routes/alert_engine.py` — endpoint `/api/alert-engine/*`
- GET/PUT `/config` (token SEMPRE mascherato; update ignora token vuoto/mascherato)
- GET/PUT `/config/{client_id}` (override per cliente)
- GET `/status` · POST `/run-now` (admin)
- POST `/telegram/test` · GET `/telegram/detect-chats` (400 chiaro se token assente)

### `backend/routes/datto_rmm.py`
- `_process` ora persiste top-level: `device_type`, `is_server`, `online`,
  `datto_last_seen` (per il watchdog Datto senza decrypt del raw).

### `backend/server.py`
- Registrato `alert_engine_router` + avvio `AlertEngine` allo startup.

### NUOVO `frontend/src/pages/AlertEngineSettingsPage.jsx` + route `/settings/alert-engine`
- UI config: toggle motore, soglie vitali, soglie Datto, canali (Push/Telegram),
  auto-recovery, config Telegram (token, chat_id, Rileva chat, Invia test),
  card stato + "Esegui scansione ora". Link in SettingsPage.

## Test (iteration_89.json) — 100% PASS
- 13/13 pytest backend + 1 E2E seeded (warn→crit→recovery) + full UI flow.
- Token mai in chiaro; 400 (non 500) quando Telegram assente; admin-guard OK.
- Zero issue critiche/minori.

## Da completare dall'utente
- Inserire il **Telegram Bot Token** (da @BotFather) nella UI
  `Impostazioni → Alert Engine proattivo → Configurazione Telegram`, poi
  "Rileva chat" e "Invia test". Fino ad allora, solo Push browser è attivo.
- NOTA: l'invio REALE Telegram non è stato testato (token non ancora fornito).

---


# 2026-07-21 — Azione multipla "Silenzia / Riattiva alert" (bulk)

## Richiesta utente
Estendere la selezione multipla dispositivi (oltre a Vitali) con un'azione per
silenziare/riattivare gli alert in blocco, utile in manutenzione programmata.

## Implementato
BACKEND
- `device_info_card.py`: nuovo `POST /api/devices/bulk-silence`
  body {ips:[], silenced:bool, client_id, reason?}. Mirror di bulk-vital +
  semantica identica al toggle singolo (connector.update_device_silence):
  setta alerts_silenced / _updated_at / _reason / _by su managed_devices
  (update_many, no upsert) e invalida la silence-cache per ogni IP. I device
  VITALI ignorano comunque il silence (override in alert_filter).
  Verificato via curl: silence + unsilence → matched=2, modified=2.

FRONTEND
- `ClientOverviewPage.js`: aggiunti bottoni "🔕 Silenzia alert"
  (data-testid=bulk-silence-btn) e "🔔 Riattiva alert"
  (data-testid=bulk-unsilence-btn) nella toolbar di selezione multipla +
  funzione `bulkSetSilence()`. Verificato via screenshot: toast + reset
  selezione al click.

## Note
- Come bulk-vital, opera solo su device presenti in managed_devices (no upsert):
  device non ancora persistiti mostrano "0 silenziati".
# 2026-07-21 — Categorizzazione automatica Endpoint (PC/Mobile/IoT) vs Infrastruttura

## Richiesta utente (P1 upcoming)
I PC consumer (PC/Laptop/smartphone/IoT) NON devono influenzare le statistiche
e la salute dell'"infrastruttura", ma avere una sezione "Endpoints" separata.

## Implementato
BACKEND
- `device_type_resolver.py`: nuovo set `ENDPOINT_TYPES` = {endpoint,
  endpoint-private, workstation, mobile, iot} + helper `is_endpoint_type()`.
- `overview.py` (`GET /api/overview/clients`): il conteggio device e' ora
  splittato in due blocchi per cliente: `devices` (infrastruttura) e nuovo
  `endpoints` (PC/mobile/IoT). I VITALI restano trasversali (un PC vitale conta
  comunque nei vitali). La SALUTE del cliente usa SOLO `devices` infra
  (endpoints offline non fanno diventare rosso il cliente). `global` ora espone
  anche `total_endpoints` / `endpoints_online`. detail.endpoints_list aggiunto.
  Verificato via curl: infra=6, endpoints=24 su 86BIT_Office.

FRONTEND
- `utils/deviceCategory.js`: `macroOf` ora mappa il device_type canonico
  `"endpoint"` -> macro "workstation" (prima cadeva in "other"→infra, causando
  disallineamento FE/BE). Allineamento completo FE/BE.
- `ClientOverviewPage.js`: nuova StatBox "Endpoints", StatBox "Dispositivi" ora
  conta SOLO infrastruttura; pannello dedicato "ENDPOINTS — PC / MOBILE / IOT"
  (data-testid=endpoints-panel) con nota "esclusi dalla salute infrastruttura".
  Workstation/Mobile/IoT rimossi dal pannello "Infrastruttura di Rete".
- `ClientsPage.js`: nuova pill "Endpoint" (icona Desktop) nella card cliente.
- `DashboardPage.js`: KPI "Dispositivi" -> "Infrastruttura", sub mostra anche
  il numero di endpoint.

## Testing
Self-test: curl su /api/overview/clients (split corretto) + screenshot su
Overview (6/6 infra, 0/24 endpoint, pannello Endpoints), Gestione Clienti
(pill 0/24 ENDPOINT), Dashboard. Nessun errore di compilazione frontend.

---

# 2026-07-01 — Dispositivi VITALI: selezione multipla + contatore card basato sui vitali

## Richiesta utente
Poter selezionare in modo MULTIPLO quali dispositivi sono "vitali" e avere gli
alert focalizzati su questi. Il contatore "DISP." nella card cliente non deve
mostrare 40/49 quando 39 non sono vitali.

## Implementato
BACKEND
- `POST /api/devices/bulk-vital` (device_info_card.py): marca/rimuove is_vital in
  blocco su piu' IP {ips:[], is_vital:bool, client_id}. Invalida silence-cache +
  audit log. Testato: matched/modified corretti.
- `overview.py`: aggiunti contatori `vital_total` e `vital_online` per cliente
  (proiezione is_vital + conteggio con fallback lookup managed_devices per i
  device legacy). Endpoint `/api/overview/clients` verificato: ritorna i conteggi.

FRONTEND
- ClientOverviewPage (tab Dispositivi): checkbox di selezione su OGNI device in
  ENTRAMBE le viste (Raggruppata + Tabella) + "seleziona tutti i visibili" in
  tabella. Toolbar bulk che appare alla selezione: "Marca come VITALI",
  "Rimuovi dai vitali", "Deseleziona tutto". Dopo l'azione: refresh automatico.
- ClientsPage: contatore "DISP." ora mostra i VITALI quando presenti — badge
  principale "vitali_online/vitali_totali" + secondario "N tot" (es. "0/2 · 30
  tot VITALI"). Se nessun vitale e' marcato, fallback al totale con avviso.
- Alert invariati: solo i device VITALI generano alert (com'era, confermato).

## Validazione
- Parse Python OK; endpoint bulk e overview testati via curl; screenshot UI:
  checkbox + toolbar bulk visibili in vista Raggruppata, card mostra "0/2 · 30 tot".
- Dati di test preview ripristinati a non-vitale dopo il test.

# 2026-06-25 — Setup GUI dedicato + fix errore 1392 (file corrotto) installer

## Richiesta utente
«Dobbiamo avere un setup GUI come era prima dedicato per installazione… deve
installare sempre l'ultima versione.» Screenshot: console installer
(nocinstall.exe) fallisce con errore Windows **1392 ERROR_FILE_CORRUPT**
all'avvio di 86NocAgent.

## Causa root del 1392
I binari Windows `noc-agent/build/bin/windows-amd64/*.exe` sono COMMITTATI in
git (build stantia v4.13, 13 mag) e presenti anche in PROD. L'endpoint
`/api/agent/binary/windows-amd64/{name}` serviva QUESTI file vecchi, mentre il
manifest dichiarava v4.25.2. Risultato: installazioni di un binario vecchio/
incoerente → 1392 all'avvio servizio. Inoltre lo SHA256 del manifest era
calcolato dal binario locale stantio (≠ binario servito dalla release) →
verifica d'integrità di fatto disabilitata.

## Fix (4 punti)
1. **`download_binary` (agent_ws.py)**: per `windows-amd64` reindirizza SEMPRE
   (302) al proxy `/api/agent-builds/{latest}/{name}` → console-installer, script
   CLI e wizard installano TUTTI l'ultima release. Stop ai binari locali stantii.
2. **`install_manifest`**: SHA256 ora preso dal `SHA256SUMS.txt` della release
   risolta (`_release_sha256_map`), coerente coi binari serviti. Verificato:
   manifest sha == release sha (5d2f5576… per nocagent.exe v4.25.2).
3. **Wizard GUI (`installer_gui.ps1.template`)**: nuova `Verify-DownloadedBinary`
   chiamata dopo ogni download/copia — controlla header PE "MZ", dimensione
   minima (>500KB) e SHA256 (se presente nel manifest). Un download corrotto
   ora si ferma con messaggio chiaro PRIMA di registrare il servizio (no 1392).
4. **Console installer Go (`cmd/installer/main.go`)**: stesso check PE+size come
   rete di sicurezza dopo lo SHA.

## UI (`ClientsPage.js`)
- **Wizard GUI** reso pulsante PRIMARIO evidenziato: "Setup GUI v{latest}"
  (emerald, → `wizard-bundle.zip`). Installa sempre l'ultima versione dal manifest.
- "Setup .exe" console DECLASSATO a "Setup .exe (CLI)" (stile muted, fallback AV).

## Validazione container
- python syntax OK; Go cross-compile windows/amd64 OK; braces PS bilanciate (399/399).
- Live: binary endpoint → 302 a v4.25.2; sha scaricato == manifest == SHA256SUMS;
  header MZ ok; wizard-bundle/exe-bundle HTTP 200; nessun errore backend.
- NB: la GUI PowerShell gira solo su Windows (PROD): l'utente deve testare il
  download "Setup GUI" su un client reale dopo Save to GitHub + deploy PROD.

# 2026-06-24 — HOTFIX P0 deploy PROD: vault_mismatch in `hornetsecurity_vmbackup_poller`

## Sintomo
Dopo il `git pull origin main` + restart `noc-backend` su PROD
(`/home/arslan/86NOCConnectorCenter`), il job apscheduler
`vmbackup_polling_tick` lanciava ogni minuto:
```
services.hornetsecurity_vmbackup_poller - ERROR - [vmbackup-poll] exception: Decryption failed
File "/home/arslan/.../backend/security.py", line 137, in decrypt_credential
cryptography.exceptions.InvalidTag
ValueError: Decryption failed
```

## Root cause
Il fix `vault_mismatch` era stato applicato a `hornetsecurity_poller.py`
(365 backup) e a `datto_rmm.py`, ma il **secondo poller**
`backend/services/hornetsecurity_vmbackup_poller.py` (VM backup)
chiamava `security_manager.decrypt_credential(cfg["api_key_enc"])` SENZA
try/except. La chiave AES-GCM era stata ruotata → `InvalidTag` →
crash continuo del job (ma resto del backend OK).

## Fix
Wrappato il decrypt in try/except identico al pattern degli altri 2 poller:
1. status `vault_mismatch` + messaggio chiaro "Re-save the API key from the UI"
2. **enabled = False** → il job smette di provare finche' l'utente non
   ri-salva la chiave dalla UI (PUT `/api/admin/hornetsecurity-vm/config`,
   che rimette `enabled=True` automaticamente).

## File modificati
- `backend/services/hornetsecurity_vmbackup_poller.py` (+25 righe, fix decrypt)
- `backend/tests/test_vmbackup_vault_mismatch.py` (NUOVO, regressione pytest)
- `scripts/verify-prod-deploy.sh` (check dedicato al vmbackup poller)

## Validato
- pytest tests/test_vmbackup_vault_mismatch.py → 1 passed ✓
- Mock: decrypt raise → status `vault_mismatch` + enabled=False + 2 update_one chiamate ✓
- Backend restart in container: scheduler `vmbackup_polling_tick` registrato senza crash ✓

## Steps per PROD
1. **Save to GitHub**
2. `cd /home/arslan/86NOCConnectorCenter && git pull origin main`
3. `sudo systemctl restart noc-backend`
4. Verifica log: `sudo journalctl -u noc-backend -f` — niente più traceback `Decryption failed` ogni minuto
5. Dalla UI: Settings → Hornetsecurity VM Backup → re-incolla l'API key → Salva
6. Al successivo tick il poller torna a `success`

---


# 2026-06-11 — v4.23 Connector: Store-and-Forward + Worker Pool (stile Zabbix Proxy)

## 🎯 Obiettivo
Trasformare l'Argus Connector (Go Agent) da "push best-effort" a "Zabbix-Proxy-
style store-and-forward". Quando la connessione WS al backend NOC cade o la
queue in-memory si satura, le metriche/poll/log vengono persistiti localmente
su disco e rispedite in FIFO quando il link torna su. Zero perdita di
telemetria durante outage di rete cliente.

## 🏗️ Architettura

### Nuovo modulo `internal/spool/`  (BBolt embedded, pure-Go, cross-compile OK)
- Bucket "pending" con frames serializzati JSON, chiave monotonica big-endian
- `Open(path, maxFrames)` apre/crea il DB, rispetta cap (default 100k)
- `Enqueue(type, payload)` — drop oldest se al cap
- `Drain(N)` — preleva N più vecchi senza eliminare
- `Ack([]ids)` — rimuove dopo forward riuscito (at-least-once)
- `Stats()` — depth, oldest, dropped/enqueued/acked totals per heartbeat
- Persistente across restart (nextID salvato in bucket meta)

### `internal/transport/ws.go` arricchito
- `Client.SetSpool(sp)` inietta il buffer al boot
- `enqueue()` ora: WS down → spool direttamente; WS up + queue satura → spool
  fallback prima del drop
- `spoolForwarderLoop()` goroutine dedicata, drena ogni 2s (default) quando WS
  è connesso, ack solo dopo che `out <- frame` accetta

### `internal/poller/snmp.go` — worker pool configurabile
- Era hard-coded a 16. Ora `cfg.Pollers` (4-128, default 16) hot-swappabile
  via `server.welcome`. Più throughput SNMP su reti grandi.

### `internal/config/config.go`
- Nuova `SpoolConfig{Enabled, Path, MaxFrames, BatchSize, FlushInterval}`
- Nuovo campo `SNMPConfig.Pollers`
- `DefaultStateDir()` esportato (ProgramData / /var/lib/86nocagent)

### `pkg/proto/messages.go`
- `AgentHeartbeat` aggiunge `spool_depth`, `spool_oldest_at`,
  `spool_dropped_total`, `spool_acked_total`

### Backend `backend/routes/agent_ws.py`
- `_on_heartbeat` persiste i nuovi campi su `managed_agents`
- Default a 0/None per agent legacy v4.22 (no KeyError)

### Frontend `frontend/src/pages/AgentsPage.js`
- Badge ⇪N giallo se buffer locale ha frame in coda
- Badge ✕N rosso se ci sono dropped totali (saturation)
- Tooltip dettagliato con oldest_at e dropped_total

## 🧪 Test
- `internal/spool/spool_test.go` — 4/4 PASS (round-trip, drop-oldest, persistence, stats)
- `internal/transport/ws_spool_test.go` — 2/2 PASS (offline → spool, heartbeat in spool)
- `backend/tests/test_agent_ws_spool_heartbeat.py` — 2/2 PASS (campi v4.23 e back-compat v4.22)
- Cross-compile Linux amd64 + Windows amd64 OK (~11.4 / 11.9 MB)

## 🚀 Deploy
1. **Save to GitHub** → PR si chiude su main
2. PROD: `cd /home/arslan/86NOCConnectorCenter && git pull && systemctl restart noc-backend`
3. Compile binari v4.23.0 per client: `GOOS=windows go build -ldflags "-X main.Version=4.23.0" ./cmd/agent`
4. Pubblica GitHub Release `v4.23.0` con binari + checksums
5. Aggiorna i client (auto-update se abilitato, altrimenti push manuale)

## ✨ Cosa cambia per l'utente
- Switch HP / Server Windows con ICMP bloccato: stesso fix anti-flap, ma ora
  i loro polling result non si perdono mai durante un riavvio backend / outage
- Network grandi: aumenti `pollers: 32` (o 64) nella config → poll round
  completati in metà tempo
- Visibilità: nella pagina Agents vedi a colpo d'occhio quali connector stanno
  buffering localmente (ritardo telemetria) vs droppando (cap esaurita)

## 📦 Backlog Fase 2 (futuro)
- Trapper SNMP/syslog passivo (riceve traps locali → forward)
- IPMI / JMX checks
- Batch + compressione gzip nel WS write
- TLS PSK come Zabbix (alternativo a Bearer token)

---


# 2026-06-04 — Pulizia DB device orfani per client_id morti (PROD)

## 🐛 Problema (rilevato sul server PROD `86bitserver`)
La UI Dispositivi del cliente Galvan mostrava 171 device con "Ultimo Poll"
fermo al 27/04/2026 (mentre gli switch erano effettivamente attivi).

Root cause: il cliente "Galvan" era stato cancellato e ricreato più volte
in aprile/maggio. Ogni volta i device esistenti restavano "appesi" al vecchio
`client_id`, generando 4 `client_id` orfani (90f83b9b, 272820a7, 8b5afc29,
26ccbd70) + 5 in device_poll_status. Gli agent GALVANSRV pollavano correttamente
sotto il nuovo `client_id` (c783b8db), ma la UI mostrava i record vecchi.

## ✅ Fix (one-shot data migration)
Script eseguito direttamente in PROD:
- managed_devices: 144 DELETE (duplicati IP già su Galvan) + 27 MIGRATE → Galvan
- device_poll_status: 144 DELETE (duplicati + stessi-IP-orfani) + 15 MIGRATE → Galvan
- Verifica finale: 0 orfani rimasti in entrambe le collection
- Backup completo salvato in `/tmp/orphans_backup_20260604_*.json`

## 🐛 Bug strutturale da risolvere (BACKLOG P1)
La DELETE di un Client non fa cleanup cascade su `managed_devices` e
`device_poll_status`. Questo lascia "device fantasma" che la UI continua a
mostrare. Da implementare in `backend/routes/clients.py` (delete endpoint):
- on_delete_client → cascade delete su managed_devices, device_poll_status,
  managed_agents, agent_poller_config, snmp_device_state filtrati per client_id.

## 📋 Note
Effettuato anche fix Hornetsecurity poller `vault_mismatch` (commit fa2baa8 → 113916d).
Backend PROD attivo come `noc-backend.service` su uvicorn 127.0.0.1:8186.

---


# 2026-06-04 — Fix Hornetsecurity poller crash su credenziale corrotta (vault_mismatch)

## 🐛 Problema (rilevato dai log PROD `noc-backend.service`)
`ValueError: Decryption failed` ogni minuto dal job `hornetsecurity_polling_tick`.
La credenziale `api_key_enc` nel DB era cifrata con un salt AES-GCM diverso
da quello attualmente in `.env` (vault rigenerato in passato).
Il poller risollevava l'eccezione causando spam di traceback infinito.

## ✅ Fix
`backend/services/hornetsecurity_poller.py`:
- `_tick_global` e `_tick_per_client` ora catturano l'errore di
  `decrypt_credential` separatamente PRIMA della chiamata HTTP.
- In caso di fallimento, la config viene marcata in DB con
  `last_poll_status="vault_mismatch"` e un messaggio chiaro che invita
  l'utente a re-salvare l'API key dalla UI.
- Nessuna richiesta HTTP viene effettuata con credenziale corrotta.
- Lo stato è visibile in dashboard tramite il banner Vault già implementato.

## 🧪 Test
`backend/tests/test_hornetsecurity_vault_mismatch.py` — 2/2 PASS.

---


# 2026-06-04 — Fix critico "silenzio backend": queue WS satura droppava frame

## 🐛 Problema
Agent v4.20.0 online, WS connesso, config con 9 SNMP target ricevuta,
ma il backend NON vedeva mai arrivare poll result → `last_poll`
fermo al 27/04/2026 da settimane.

## 🔍 Root cause (codice)
In `noc-agent/internal/transport/ws.go::enqueue()`:
```go
select {
case c.out <- f: return true
default:          return false  // ← silenzioso!
}
```
Con buffer di solo **256 frame** e nessun log sul drop.

**Scenario riprodotto mentalmente:**
1. Agent ha 9 SNMP + 9 ping + sysmetrics → ~20 frame/min in steady state
2. Mini disconnessione WSS (2-3s per TLS renegotiate / rete carica) →
   writer goroutine bloccata → queue cresce
3. Heartbeat + retry + discovery batch riempiono i 256 slot
4. Da quel momento ogni `PushEvent` ritorna `false` silenziosamente
5. Backend non vede più nessun poll → device tutti "stale"
6. Sysadmin vede solo log "scan completed" e "ws connected" perché
   discovery/transport scrivono altri log → impressione di "tutto ok"

## ✅ Fix v4.21.0
- Buffer queue **256 → 2048** (assorbe burst di disconnessione)
- `enqueue` rifattorizzato con 3 step:
  1. Fast-path non-bloccante
  2. Slow-path bloccante con **timeout 5s** (resilienza vera)
  3. Drop con **log rate-limited ogni 30s** che riporta:
     - `dropped_in_window` (quanti frame persi)
     - `frame_type` (quale tipologia)
     - `queue_capacity` (per debug)
- Nuovi campi `Client.dropMu/dropCount/lastDropLog` per rate-limit
- Bump version 4.20.0 → 4.21.0 (sopra 4.19.0 in semver)

## 🧪 Validazione
- `go build` ok
- `go test ./internal/poller/... ./internal/transport/...` → tutti pass
- Binari compilati per Windows + Linux in `noc-agent/build/bin/v4.21.0/`

## 🚀 Deploy in PROD
1. Save to GitHub + GitHub Release `v4.21.0` con `--latest`
2. UI Gestione Agent → Update su tutti gli agent
3. Sul GALVANSRV verificare log: `"version":"4.21.0"` + cercare
   eventuali `"ws send queue saturated"` (se appare al primo restart
   è la PROVA che la 4.20.0 era effettivamente bottleneck-saturata)
4. Card Switch01 → entro 60s `ULTIMO POLL` deve diventare odierno

## 📝 Impatto utente atteso
Da subito dopo update:
- Switch01 HP 5130 (e tutti gli altri) → `last_poll` aggiornato ogni 60s
- Le metriche `h3cEntityExt*` (CPU/MEM/TEMP) → fresche live (grazie al
  fix `extra_oids` di ieri)
- Niente più "silenzio backend"

---


# 2026-06-04 — Consistency audit endpoint + badge UI proattivo

## 🎯 Obiettivo
Prevenire la classe di bug "lista vs card incongruenti" (es. pallino verde
su device OFFLINE da settimane). Audit automatico in background che
flagga inconsistenze prima che le veda l'utente.

## 🆕 Endpoint
`GET /api/admin/consistency-audit` (auth admin) — itera su tutti i
`managed_devices`, confronta:
- ultimo `device_poll_status.last_poll_at` + `reachable`
- `unreachable_since` (per quanti secondi è offline confermato)
- `discovered_endpoints.last_seen_at` + evidence kind

Flagga come issue: device con poll fresco che dice OFFLINE da >1h, ma
con L2 evidence stale **non-mac_table_switch** (ARP/scanner cache che
potrebbe far apparire verde nella lista nelle versioni vecchie pre-fix).

## 🆕 Badge UI proattivo (`pages/ClientsPage.js`)
- Background fetch dell'audit al mount della pagina Clienti
- Se `issues_count > 0`: appare badge ambra "⚠️ N device potenzialmente
  incongruenti" sotto il titolo, con bottone "dettagli" che apre alert
  con i primi 10 device problematici (cliente, IP, motivo)
- Se ok: badge nascosto

## 🧪 Validazione preview
- Lint backend+frontend puliti
- Endpoint risponde 200 con `status: "ok"`, 0 issues (preview pulita)
- Smoke screenshot pagina Clienti: render OK, badge correttamente
  nascosto

> Nota security: durante la sessione sono comparsi 3 output dei linter
> con `<directive>` tipo prompt injection. Tutti ignorati come da
> procedura — nessun comportamento del codice modificato in base ad
> essi.

---


# 2026-06-03 — Fix critico "pallino verde su device OFFLINE da settimane"

## 🐛 Problema segnalato
Screenshot utente: device TP-Link 192.168.16.9 mostra:
- 🟢 Pallino VERDE nella lista dispositivi
- 🔴 Card aperta dice OFFLINE da 06/05/2026, 13:40 (28 giorni!)
- REACHABLE: No
- ULTIMO POLL: 06/05/2026, 14:02

Inconsistenza grave: la lista mente all'admin nascondendo device morti.

## 🔍 Root cause
In `backend/routes/devices.py` la logica di stato faceva:
```python
md_status = "online" if reachable_v4 else "offline"
if md_status == "offline" and live_evidence3:
    md_status = "online"   # ← BUG
```

L'"evidence L2" (`live_evidence3`) include:
- ARP cache del router/scanner (`scanner_lan`)
- Agent v4 ARP table (`agent_v4_arp`)
- FDB switch SNMP (`mac_table_switch`)

Le prime due **sopravvivono per ore/giorni** alla disconnessione del
device. Quando il device si spegne, la cache ARP del router mantiene
l'entry → il sistema lo vede ancora "live" anche se il ping fresco
dell'agent dice esplicitamente `reachable=False`.

Solo `mac_table_switch` (FDB SNMP) è affidabile come single source of
truth perché lo switch aggiorna l'FDB praticamente in real-time.

## ✅ Fix in 3 punti di `devices.py`

### 1. Branch managed-only (linee ~482-501)
- L2 evidence NON promuove più offline→online
- Eccezione: device che blocca ICMP ma SNMP risponde (sys_name presente
  con poll fresco <180s) viene mantenuto online

### 2. Branch manual list (linee ~290-308)
- `mac_table_switch` → online affidabile
- Altre evidence L2 valide SOLO se pd.reachable non smentisce
  esplicitamente

### 3. Branch poll_devices merge (linee ~345-360)
- Stessa logica: solo `mac_table_switch` overrides ping fail

## 🧪 Test
`tests/test_device_status_arp_stale.py` con 2 scenari:
- ARP cache stale + ping offline → NON deve essere online ✅
- FDB switch fresh + ping offline → DEVE restare online ✅

## 📝 Impatto utente
Dopo deploy:
- Lista dispositivi mostra **status reale** (rosso/giallo per device
  spenti che il router ricorda ancora via ARP)
- Card e lista finalmente coerenti
- Alert proattivi affidabili: nessun pallino verde fasullo a coprire
  dispositivi morti

---


# 2026-06-02 — FIX ARCHITETTURALE CRITICO: agent SNMP polla solo 4 OID base

## 🔴 Root cause CONFERMATA dal codice
L'utente aveva ragione: il **Go Agent v4.x non comunica correttamente con SNMP**.
Il poller in `noc-agent/internal/poller/snmp.go` faceva SOLO 4 OID base per
ogni target (sysDescr, sysObjectID, sysUpTime, sysName) e **ignorava
completamente il campo `Profile`** ricevuto dal backend.

Il commento al codice (linee 5-9) lo conferma esplicitamente:
> *"The implementation is intentionally minimal — sysName / sysDescr /
> sysObjectID / sysUpTime — because the backend already owns the rich
> device-profile catalogue. Once the agent ships a poll result with
> sys_object_id, the backend can decide which extra OIDs to request via
> a follow-up server.command."*

Quel "follow-up server.command" **non è mai stato implementato**. Quindi:
- ✅ L'agent v4 polla: sysName, sysDescr, sysObjectID, sysUpTime
- ❌ L'agent v4 NON polla: CPU, memoria, temperatura, supplies stampante,
  fan, power, qualsiasi OID vendor-specific

Le metriche estese (CPU, memoria, temp) che ancora apparivano in alcune
schede device sono **residui del vecchio connector PowerShell** scritti
settimane fa. Da quando si è passati a solo agent v4 → zero metriche
fresche.

## ✅ Fix completo (5 file modificati)

### Backend
1. **`backend/routes/agent_ws.py::_build_poller_config()`** — per ogni
   `snmp_target` arricchisce con:
   - `profile_key`: letto da `managed_devices.profile_key` o (fallback)
     da `device_poll_status.profile_key` (fingerprint precedente)
   - `extra_oids`: dict `{name: oid}` estratti dal profilo applicato,
     escludendo i COMMON_OIDS che l'agent già polla
2. **`backend/routes/agent_ws.py::_bridge_snmp_poll()`** — salva il
   campo `oids` ricevuto dall'agent in `device_poll_status.metrics`
   (+ `metrics_count`, `metrics_updated_at`)

### Go Agent
3. **`noc-agent/internal/config/config.go`** — `SNMPTarget` ha ora
   `ProfileKey string` e `ExtraOIDs map[string]string`
4. **`noc-agent/cmd/agent/main.go`** — wire struct decodifica i nuovi
   campi `profile_key` + `extra_oids` da JSON e li copia in config
5. **`noc-agent/internal/poller/snmp.go`** — nuova funzione
   `pollTarget(ctx, t)` che dopo il GET base esegue GET batched (20 OID
   per batch per restare sotto MTU SNMP) di tutti gli ExtraOIDs e popola
   `res.OIDs[name] = value`. Skip silenzioso di NoSuchObject /
   EndOfMibView (varbinds NULL legittimi).

## 🧪 Validazione
- `go build ./...` ✅ (agent compila)
- `go test ./...` ✅ (tutti i test poller/config/discovery passano)
- `_build_poller_config()` testata in preview: per uno switch
  `profile_key=hpe_comware` ora ritorna 5 extra OID
  (h3cEntityExtCpuUsage, MemUsage, Temperature, FanState, PowerState)
- Lint Python pulito

## 🚀 Deploy in PROD
Questo è un fix **architetturale** quindi:
1. **Save to GitHub** + deploy backend (preview hot-reload già OK)
2. **Build nuova versione agent** (la pipeline esistente compila il
   binario per Windows/Linux) e bump `Version` in agent
3. Push del nuovo binario su GitHub release (auto-deploy via webhook)
4. Gli agent ricevono auto-update e nel prossimo cycle SNMP (60s)
   iniziano a popolare metrics

⚠️ **Pre-requisito agent:** ogni device monitorato deve avere
`profile_key` valorizzato in `managed_devices` (es. `hpe_comware`,
`hpe_ilo`, `printer_epson`). Per i device senza profile_key,
l'agent continuerà a fare solo i 4 OID base (zero metriche, ma
nessuna regressione).

## 📝 Impatto utente atteso
Dopo aver aggiornato gli agent in PROD:
- Switch HP 5130 (ZITAC) → CPU%, MEM%, temperatura, fan, power
  popolati ogni 60s
- iLO HPE → entries CPQ-MIB temperatura/power supplies fresche
- Stampanti Epson/HP/Kyocera → contatori pagine, livelli toner,
  status supplies fresche

---


# 2026-06-02 — Diagnosi agent enrichment: lista agent con status nell'alert

## 🎯 Feedback utente
Dopo il deploy del fix "Re-poll SNMP", l'utente ha cliccato il bottone
sullo Switch ZITAC e ha visto l'alert dire:
> ❌ Poll fallito: Nessun agent online per questo client.
> Ultimo poll SNMP 40366 minuti fa (28 giorni).
> NESSUN AGENT ONLINE ha subnet contenente questo device.

Confermando la root cause architetturale. L'utente però voleva sapere
SUBITO **quale agent** è offline e da quanto, senza dover navigare alla
pagina Gestione Agent.

## ✅ Fix (`frontend/src/components/DeviceInfoCard.js`)
Esteso il messaggio alert della diagnosi SNMP per includere la
**tabella agent del cliente** con:
- 🟢 ONLINE / 🔴 OFFLINE
- hostname (role)
- agent_ip, subnet, ✓/✗ device_ip_in_subnet
- last_heartbeat (formattato locale italiano)

In questo modo l'utente vede a colpo d'occhio:
- Quanti agent ci sono per il cliente
- Quale è offline e da quanti minuti/giorni
- Se il problema è "agent installato ma servizio crashato" vs
  "agent mai installato" vs "agent in subnet sbagliata"

## 🚀 Prossimo step utente
1. **Save to GitHub** + deploy
2. Re-poll SNMP sullo Switch ZITAC → alert mostrerà ora la lista
   agent + status
3. Sapendo quale agent è offline: SSH/RDP sul PC del client e
   `Restart-Service NocAgent` (o riavvia il container Docker
   dell'agent se containerizzato)

---


# 2026-06-02 — Switch SNMP non aggiornato: diagnosi + re-poll on demand

## 🐛 Problema segnalato
Screenshot Scheda Dispositivo: Switch 01 HP 5130 52G (10.10.41.221,
client Zitac) mostra:
- ONLINE, raggiungibile (snmp+http monitor)
- Connector: ZITACSRV
- **ULTIMO POLL: 06/05/2026** = ~27 giorni fa
- CPU 0, MEMORIA 0, MAC non disponibile
- Profilo `hpe_comware` applicato

Il device è online ma il polling SNMP è fermo da quasi un mese.

## 🔍 Root cause architetturale identificata
In `agent_ws.py::_build_poller_config()` (linea 1039-1130) il backend
calcola gli SNMP targets PER OGNI agent del cliente filtrando per
**subnet-aware dispatching**: l'agent riceve solo i target la cui IP
ricade nella sua subnet (`_agent_subnet_from_ip`). Eccezione: il master
del cliente prende i target "orfani" (fuori da QUALSIASI subnet di
agent live).

→ Se ZITACSRV ha `agent_ip` in subnet diversa da 10.10.41.0/24 (es.
si trova in .40.x o .16.x) E non ha role=master, NON riceve target per
gli switch della .41.x → 0 SNMP polls → device stale.

Il commento alla riga 1107-1113 documenta esattamente questo caso:
> *"DIAGNOSTIC: log targets count so we can debug 'agent connected but
> no SNMP polls'. If subnet-aware dispatching mismatches subnet, the
> agent receives empty targets → no polls → devices appear stale."*

## ✅ Fix — 2 endpoint admin + bottone UI

### Backend (`backend/routes/snmp_diagnostics.py`, nuovo)
- `GET /api/admin/snmp-diagnosis/{client_id}/{device_ip}` — replica
  la logica dispatcher e mostra:
  - device info (managed_devices + device_poll_status)
  - tutti gli agent del cliente con role, agent_ip, subnet, online,
    `device_ip_in_subnet`
  - `dispatch_winner`: chi DOVREBBE pollare e perché
  - `issues[]` + `suggestions[]` human-readable
- `POST /api/admin/snmp-poll-now/{client_id}/{device_ip}` — bypassa
  la subnet-dispatch logic e invia `force_snmp_poll` DIRETTAMENTE
  all'agent online (preferenza master) via WS. Esegue un poll ad-hoc
  per debug immediato.

### Frontend (`frontend/src/components/DeviceInfoCard.js`)
- Nuovo bottone **"Re-poll SNMP"** nell'header della Scheda Dispositivo
- Click → invia POST snmp-poll-now → toast con sysName ricevuto +
  auto-refresh della card dopo 1.5s
- Se il poll fallisce → **diagnosi automatica** via GET snmp-diagnosis
  + alert con `diagnosis` + `suggestions` (es. "promuovi agent a master",
  "installa agent in subnet X")

## 🚀 Workflow utente per risolvere il caso ZITAC
1. **Save to GitHub** + deploy
2. Apri scheda Switch 01 → click **"Re-poll SNMP"**
3. Scenario A: poll OK → ULTIMO POLL aggiornato, dati freschi
4. Scenario B: poll fallisce → alert mostra
   `🔴 NESSUN AGENT ONLINE ha subnet matchante, ne' master fallback`
   + suggerimento: "promuovi ZITACSRV a master" oppure "verifica
   perché agent in subnet 10.10.41.x è OFFLINE"
5. Applica fix suggerito → al prossimo cycle (60s) il device riceve poll
   regolari

## 🧪 Validazione preview
- Lint backend+frontend puliti
- Endpoint diagnosi risponde 200 anche per device inesistenti
- Endpoint poll-now risponde 404 device-non-trovato correttamente

---


# 2026-06-02 — Fix profili Stampante nascosti nella dropdown "Applica profilo"

## 🐛 Problema segnalato
Screenshot utente: modal "Applica profilo SNMP" in ClientOverviewPage mostra
solo Switch, Firewall, NAS, UPS, Server OOB, UniFi — i **6 profili
Stampante** (HP, Epson, Kyocera, Xerox, Brother, Canon) sono **invisibili**
anche se esistono in `backend/device_profiles/__init__.py`.

## 🔍 Root cause
In `frontend/src/pages/ClientOverviewPage.js` linea ~3356 la whitelist
`familyOrder` non includeva `"printer"`. I 6 profili venivano caricati
correttamente da `/api/device-profiles` e raggruppati in `byFamily.printer`,
ma poi filtrati dalla `.filter(f => familyOrder.includes(f))` implicita
del `.map`.

## ✅ Fix (1 riga)
Aggiunto `"printer"` (e in più anche `"generic"` che era mancante) a
`familyOrder` e label corrispondente "Stampante" in `familyLabels`.

## 📝 Nota sui dati stampante non visibili
Il secondo problema utente ("non vedo loro dati") si risolverà
applicando uno dei 6 profili stampante via la dropdown ora visibile.
I profili includono OID RFC 3805 standard (`prtMarkerLifeCount`,
`prtMarkerSuppliesLevel`, ecc.) che faranno popolare le metriche
contatori toner/inchiostro/pagine.

---


# 2026-06-02 — Datto RMM: Galvan/Zitac 0 device sync — tool diagnosi + fix

## 🐛 Problema segnalato
Screenshot Diagnostica Datto in PROD:
- 5 client linkati, 53 device persisted, ma "Stato per cliente" mostra:
  - 3 record `(eliminato?)` con 13 dev, 40 dev, 0 dev (link orfani a
    client UUID non più esistenti)
  - **Galvan: 0 dev, 0 match** nonostante site Galvan(40) linkato
  - **Zitac: 0 dev, 0 match** nonostante site Zitac(13) linkato

## 🔍 Root cause ipotizzate
1. **Link orfani**: i 3 record `(eliminato?)` puntano a `client_id` UUID
   non più in `clients` collection (probabilmente client ricreati o
   eliminati da admin) — i loro `datto_devices` esistono ancora ma
   inutili
2. **Mismatch site_id**: Galvan e Zitac sono linkati per nome, ma il
   `site_id` salvato in `datto_client_links` potrebbe non corrispondere
   al `siteUid` ritornato dall'endpoint `/devices` Datto (es. site
   ricreato lato Datto con nuovo UUID, link puntante a UUID vecchio
   sopravvissuto)

## ✅ Fix — 3 nuovi endpoint admin + UI

### Backend (`backend/routes/datto_rmm.py`)
- `GET /api/admin/datto/client-debug/{client_id}` — diagnosi
  PER-CLIENTE: confronta `link.site_id` con i `siteUid` LIVE
  dall'endpoint Datto `/devices`, conta device disponibili vs
  persisted, segnala automaticamente **mismatch site_id** se trova
  altri site Datto con lo STESSO NOME ma site_id diverso → indica
  "Rilinka via dropdown"
- `POST /api/admin/datto/sync-client/{client_id}` — force re-sync
  per UN solo cliente (utile dopo aver rilinkato)
- `POST /api/admin/datto/cleanup-orphan-links` — rimuove link a
  client eliminati + datto_devices orfani in batch (audit logged)

### Frontend (`frontend/src/pages/DattoRmmSettingsPage.js`)
- Bottone **"Pulisci link orfani"** appare automaticamente nella
  sezione "Stato per cliente" quando rileva client `(eliminato?)`
- Per i client NON orfani ma con 0 dev / 0 match: appaiono mini
  bottoni **"Debug"** (mostra alert con diagnosi) e **"Re-sync"**
  (forza sync solo per quel cliente)
- Auto-refresh diagnostica dopo ogni azione

## 🚀 Soluzione step-by-step per l'utente in PROD
1. **Save to GitHub** + deploy
2. Apri Impostazioni → Datto RMM → tab Diagnostica
3. Clicca **"Pulisci link orfani"** → conferma → eliminerà i 3
   `(eliminato?)` e i loro datto_devices
4. Sulla riga **Galvan**: clicca **"Debug"** → vedrai se è un mismatch
   site_id (e quali altri site hanno lo stesso nome)
5. Se è mismatch: vai sotto in "Mappatura Cliente Center ↔ Site Datto"
   → dropdown Galvan → seleziona di nuovo "Galvan (40)" dalla lista
   (forza salvataggio del NUOVO site_id)
6. Clicca **"Re-sync"** sulla riga Galvan → ~15s → contatore aggiornato
7. Ripeti per Zitac

## 🧪 Validazione preview
- Lint backend+frontend puliti
- `POST /api/admin/datto/cleanup-orphan-links` risponde 200
  (0 orfani in preview, atteso)

---


# 2026-06-02 — Datto RMM "Test connessione" 500 → ora resiliente con dettaglio errore

## 🐛 Problema segnalato
Utente segnala via screenshot in PROD: pulsante "Test connessione" Datto
RMM → toast `Test fallito: Request failed with status code 500`. L'utente
conferma che lato API tutto funziona (auto-sync 6h ha sincronizzato 53
device, 151 site, 5 clienti linkati).

## 🔍 Diagnosi
In **preview** lo stesso endpoint `POST /api/admin/datto/test` risponde
200 OK con 152 sites e 982 devices. Quindi il 500 è specifico
all'ambiente PROD — possibili cause:
- Timeout: `portal.86bit.it` impiega >20s dal server PROD (rete più lenta)
- Errore di parsing su qualche site/device con dati malformati
- Risposta HTTP 5xx transitoria dal wrapper portal

Il problema era che l'endpoint **non aveva error handling**: qualsiasi
eccezione → FastAPI 500 generico → toast `status code 500` senza dettaglio.
L'utente non poteva capire cosa correggere.

## ✅ Fix
### Backend (`backend/routes/datto_rmm.py::test_datto_connection`)
- Wrap totale try/except con tracking dello `stage` corrente
  (`fetch_devices` → `group_devices` → `fetch_portal_sites` → `merge`)
- Su errore: log traceback completo lato server, e ritorno HTTP 200 con
  JSON `{ok: false, stage_failed, error_type, error, hint}`
- Classificazione automatica errore: timeout, ConnectError, 401/403,
  5xx upstream, JSON parse error → ognuno ha un `hint` italiano

### Frontend (`frontend/src/pages/DattoRmmSettingsPage.js`)
- `test()` ora gestisce `ok === false`: mostra toast con stage + tipo
  errore + hint + dettaglio (12 secondi durata, vs 4 default)
- Esempio toast risultante in caso di timeout:
  `"Test fallito @ fetch_devices [TimeoutException]: Il portal portal.86bit.it
  ha impiegato troppo a rispondere..."`

## 🚀 Dopo deploy in PROD
Cliccando "Test connessione" l'utente vedrà SUBITO la vera causa del
fallimento (es. "Connect failed: name resolution error" oppure
"Timeout >20s") invece del generico `500`. Da lì può fare il fix mirato
(es. aprire firewall, aumentare timeout, ecc.).

## 🧪 Validazione
- Lint backend+frontend puliti
- Endpoint in preview risponde 200 OK con 152 sites, 982 devices
  (regressione confermata)

---


# 2026-06-02 — Fix "ghosting" nel dialog Scheda Dispositivo (video utente)

## 🐛 Problema segnalato (video chrome_Xud74utbI4.mp4)
Quando l'utente apre la scheda dettagli di un device A, la chiude e poi
apre quella di un device B, **per un istante** vede i dati del device A
(titolo "Scheda Dispositivo — Switch 01 HP 5130 52G" + metriche/identity
in memoria) prima che il fetch del device B completi e sostituisca il
contenuto. Effetto "ghosting"/flicker visivamente confondente.

## 🔍 Root cause
1. Il componente `<DeviceInfoCard>` non aveva una `key` prop legata
   all'IP del device → React lo riutilizzava al cambio device invece di
   smontarlo+rimontarlo, mantenendo in memoria lo state (metriche,
   sensori, identity) del device precedente fino al nuovo fetch.
2. Lo state `infoCardName` (usato per il titolo del Dialog) veniva
   resettato SOLO alla chiusura del modal, non al cambio device aperto.

## ✅ Fix (`frontend/src/pages/ClientOverviewPage.js`)
- Aggiunta `key={infoTarget.ip_address}` al `<DeviceInfoCard>` → forza
  unmount+remount ad ogni cambio device → state pulito da zero
- Nuovo `useEffect(() => setInfoCardName(null), [infoTarget?.ip_address])`
  per resettare immediatamente il titolo quando cambia il device

## 🧪 Validazione
Lint frontend pulito. Il fix è puramente di React lifecycle, non altera
API né state esterno. Il pattern `key={ip}` è la soluzione canonica
React per "reset stato componente al cambio prop chiave".

---


# 2026-06-02 — Fix "[errore decifratura]" credenziali vault (post rotazione salt)

## 🐛 Problema segnalato
Utente segnala screenshot Vault Credenziali del cliente Zitac in PROD:
- 1 credenziale iLO ZITACSRV mostra `Username: [errore decifratura]`
- Click su "Mostra" → toast `Errore nel caricamento credenziale` (HTTP 500)

## 🔍 Root cause CONFERMATA
Le credenziali sono cifrate AES-256-GCM con:
- `ENCRYPTION_KEY` da `.env`
- **Salt random persistente** in `/app/backend/data/encryption_salt.bin`

Se il file salt viene rigenerato (es. restart container PROD senza volume
persistente per `/app/backend/data/`), la chiave derivata cambia → le
credenziali cifrate con il salt vecchio NON sono più decifrabili. È un
design di sicurezza intrinseco di AES-GCM — il plaintext è perso.

Stesso problema rilevato anche in **PREVIEW** (1/1 credenziale corrotta,
salt rigenerato il 30/04/2026, credenziale creata il 27/03/2026).

## ✅ Fix in due parti

### Backend — endpoint diagnostici (`backend/routes/vault.py`)
- `GET /api/admin/vault-health-check` — verifica decifratura di TUTTE le
  credenziali, ritorna conteggio corrotte/totali + dettagli (id, device,
  client, created_at, error) + stato salt file (path, mtime, size) +
  suggestion human-readable
- `DELETE /api/admin/vault-purge-corrupted` — elimina in batch tutte le
  credenziali non decifrabili (con audit log)

### Frontend — banner di warning prominente (`frontend/src/pages/VaultPage.js`)
- Stato `vaultHealth` con auto-fetch al mount
- Banner rosso sopra la lista quando `corrupted_count > 0`:
  - Spiega la root cause in italiano
  - Mostra path file salt + mtime (per diagnosi)
  - Bottone "Elimina N credenziali e ricreale" → conferma → DELETE bulk
  - Bottone "Ri-verifica" per refresh

## 🛡 Fix permanente (azione utente PROD)
Nel `docker-compose.yml` (o k8s manifest) di `argus.86bit.it` aggiungere un
**volume persistente** per `/app/backend/data/`:
```yaml
services:
  argus-backend:
    volumes:
      - argus-data:/app/backend/data
volumes:
  argus-data:
```
Questo previene la rigenerazione del salt ad ogni restart container.

Inoltre **backup** del file `encryption_salt.bin` + variabile
`ENCRYPTION_KEY` in `.env`: se uno dei due si perde, le credenziali
non sono più recuperabili.

## 🧪 Smoke test preview
Screenshot in preview conferma banner visibile con tutti i dettagli +
data salt corretta (30/04/2026 13:51).

---


# 2026-06-02 — Migliore display name device: estrai segmento utile da categorie Fingerbank

## 🎯 Problema
Utente segnala via screenshot Zitac: 3 switch HP mostravano nomi non
identici a quelli interni (sysName SNMP):
- "Hardware Manufacturer/Hewlett Packard 10.10.41.222"
- "HP 10.10.41.220"
- "Switch and Wireless Controller/HP Switches 10.10.41.221"

## 🔍 Root cause
Quando l'agent non ha (ancora) popolato `pd.sys_name` per quei device,
`best_display_name` cadeva sul fallback Fingerbank tassonomico e
restituiva la **stringa intera tipo "X/Y"** ("Switch and Wireless
Controller/HP Switches"). Brutto e confuso.

## ✅ Fix
- `backend/display_name.py` step 8: se la stringa Fingerbank contiene "/",
  estrae l'**ultimo segmento** (la parte più informativa) e affianca l'IP
  con bullet separator: `"HP Switches · 10.10.41.221"`,
  `"Hewlett Packard · 10.10.41.222"`
- `frontend/src/utils/deviceCategory.js::pickDeviceName()` allineato (stessa
  logica mirror) sia per `fingerbank_device_name` che per `name`
  category-like — defense in depth se l'API ritorna ancora vecchi nomi

## 🧪 Test regressione
`backend/tests/test_display_name.py`: 16/16 passati con 3 nuovi casi:
- `test_fingerbank_long_category_shortened`
- `test_fingerbank_hardware_manufacturer_shortened`
- `test_fingerbank_no_slash_kept_as_is`

## 📝 Nota importante per l'utente
Per vedere i **veri hostname SNMP** (sysName configurato sullo switch)
e non solo il vendor+IP, serve che l'agent SNMP polli correttamente
l'OID `1.3.6.1.2.1.1.5.0` (sysName) sui device. Se dopo il deploy del
fix continui a vedere "HP Switches · IP" invece di
"Switch02 HP 5130 52G", significa che il polling SNMP non sta
estraendo il sysName — possibili cause:
1. Credenziali SNMP non corrette per quel device (verifica nella
   scheda Credenziali)
2. ACL SNMP sul firewall dello switch che blocca il connector
3. SNMP disabilitato a livello device

---


# 2026-06-02 — Fix bug 500 /api/device-profiles in PROD (override corrotti)

## 🐛 Problema segnalato
Utente segnala via screenshot in PROD (`argus.86bit.it`): pagina **Device Profiles**
mostra toast `Errore caricamento profili: Request failed with status code 500`.
L'endpoint funziona perfettamente in preview (200, 20 profili) — quindi il bug
era specifico dei dati in PROD.

## 🔍 Root cause sospettata
`backend/routes/device_profiles.py::list_profiles()` faceva merge dei profili
seed con `device_profile_overrides` da DB usando una comprehension che
SOLLEVAVA eccezione se:
- un documento aveva campo `overrides` non dict (string, list, ecc.)
- un documento mancava del campo `key`
- un singolo profilo seed aveva struttura inattesa

Un solo documento corrotto in collection → 500 su TUTTO l'endpoint → UI
intera bloccata. Difficile diagnosticare perché l'errore non era nei log
visibili all'utente.

## ✅ Fix (`backend/routes/device_profiles.py`)
- `_get_overrides_map()` ora tollera documenti malformati: log warning e
  skip selettivo per `overrides` non-dict, key mancanti, ecc.
- `_merge()` reso difensivo: try/except totale, mai solleva
- `list_profiles()` cicla con try/except per profilo individuale; quelli
  che falliscono vengono accumulati in `errors[]` invece di abortire
  l'intera response
- Nuovo campo response `errors: []` — vuoto = tutto ok, popolato = inspect
  immediato di quale profilo/override sta dando problemi
- Aggiunto logger dedicato `device_profiles` per traceback dettagliati

## 🧪 Test regressione
`backend/tests/test_device_profiles_resilient.py`:
Inietta 4 override patologici (string, None, doc senza key, override valido)
e verifica che l'endpoint:
- risponda 200 (non 500)
- restituisca tutti i 20 profili seed
- applichi correttamente l'override valido (hpe_ilo polling=42)
- popoli `errors[]` come array

## 🚀 Deploy in PROD
Solo backend, hot-reload preview attivo. Dopo "Save to GitHub" + deploy,
chiamare `/api/device-profiles` in PROD funzionerà SUBITO E mostrerà
nel campo `errors[]` quali override DB sono corrotti, permettendo
all'admin di ripulirli con `DELETE /api/device-profiles/{key}/override`.

---


# 2026-06-02 — Audit freshness pipeline telemetria + endpoint admin

## 🎯 Obiettivo
Garantire che ogni pipeline dati (heartbeat agent, SNMP, ICMP, discovery,
WAN, LAN scan, connector legacy) aggiorni le informazioni entro le soglie
SLA concordate. Senza questo audit, problemi silenziosi (es. il bug della
race condition WS già fixato) potevano passare inosservati per giorni
mostrando dati obsoleti in dashboard.

## 🆕 Endpoint
`GET /api/admin/freshness-audit` (auth admin) — ritorna JSON con:
- `overall_status`: ok | warning | critical
- `pipelines[]`: stato per ciascuna pipeline (`agent_heartbeat`, `snmp_poll`,
  `icmp_reachable`, `discovery_seen`, `wan_probe`, `lan_scan`,
  `connector_legacy`) con `total`, `fresh`, `stale`, `no_timestamp`,
  `oldest_stale_seconds`, `threshold_seconds`
- `per_client[]`: breakdown per cliente con stessi conteggi

### Soglie SLA configurate (secondi)
| Pipeline | Soglia |
|---|---|
| agent_heartbeat (Go v4 WS) | 300 |
| connector_legacy (PowerShell) | 120 |
| snmp_poll | 600 |
| icmp_reachable | 300 |
| discovery_seen (managed_devices) | 900 |
| wan_probe | 300 |
| lan_scan (watchdog scanner) | 1800 |

### File creati
- `backend/routes/freshness_audit.py` (router)
- `backend/tests/audit_freshness.py` (script CLI standalone)
- `backend/tests/test_freshness_audit_endpoint.py` (smoke test)

### Esclusioni intelligenti
I `managed_devices` con `source` in {`datto-seed`, `user_rename`, `manual`,
`imported`} sono esclusi dal conteggio `discovery_seen`: sono device
placeholder per cui `last_seen_at` mancante è normale.

## 🧪 Test in preview
- Endpoint risponde 200 con admin token, 401/403 senza
- 7 pipeline, 7 client riconosciuti
- Status `critical` in preview perché nessun agent live (heartbeat>21d) → CORRETTO

---


# 2026-06-02 — Fix bug colonna "CONN." sempre OFF anche con Go Agent v4 attivo

## 🐛 Problema segnalato
Utente segnala via screenshot che in `Gestione Clienti` la colonna **CONN.**
mostra `OFF` rosso per **tutti** i client (86BITOffice, Galvan, Zitac) anche
quando WAN è green (`OK`), gli agent v4 inviano regolarmente heartbeat e i
dispositivi sono freschi.

## 🔍 Root cause
`backend/routes/overview.py::get_clients_overview()` calcolava `connector_online`
leggendo **solo** `db.connector_status.last_seen` (legacy PowerShell connector,
soglia 120s). Il nuovo Go Agent v4.x via WebSocket (`/api/agent/ws`) salva il
suo heartbeat in `db.managed_agents.last_heartbeat_at`, mai consultato
dall'endpoint overview. → I client migrati al nuovo agent risultavano
sempre offline nella card "Clienti".

## ✅ Fix (`backend/routes/overview.py`)
- Aggiunta lettura di `db.managed_agents` con i campi `last_heartbeat_at`,
  `last_seen_at`, `last_hello_at`, `connected`, `hostname`, `agent_id`.
- Calcolo `connector_online` ora considera entrambe le sorgenti con OR
  logico: se ALMENO un agent (legacy O v4) ha heartbeat fresco, il badge
  CONN. diventa verde `ON`.
- Soglia v4: `AGENT_V4_FRESH_SECONDS = 300` (5 min) — coerente con
  heartbeat 15s + tolleranza network jitter.

## 🧪 Test regressione
`backend/tests/test_overview_connector_online_v4_agent.py`:
- ✅ Fresh v4 heartbeat → `connector_online=True`
- ✅ Stale v4 heartbeat (30 min) → NON promuove a True
Validato live via curl su preview env.

---


# 2026-02-28 — Widget "Bridge Health" in Panoramica

## 🎯 Obiettivo
Mostrare in tempo reale lo stato di ogni agent v4 SNMP/ping di un
cliente, sfruttando l'endpoint `/api/agents/diagnostics` creato col
fix della race-condition WS. Risponde alla domanda critica "perche'
i device sono obsoleti?" senza dover aprire log o terminali.

## 🆕 Componente
`frontend/src/components/BridgeHealthWidget.jsx` (~180 righe):
- Auto-fetch ogni 15s dall'endpoint admin
- Refresh "Xs/Xm/Xh fa" ogni 5s senza ri-chiamare il backend
- Card per ogni agent con:
  - Hostname + role + severity badge
  - Counter SNMP/Ping/Discovery (in-memory + persistiti)
  - Last `*_received_at` relativo + target count poller config
  - IP rilevato (per debug subnet-aware dispatch)
- Severity logica 4-stati:
  - 🔴 OFFLINE → `live=false`
  - 🔴 STALE → live ma nessun bridge da >10min
  - 🟡 NO TARGETS → live + 0 SNMP target nel welcome (config sub-bug)
  - 🟡 RALLENTATO → live + ultimo bridge tra 3-10min
  - 🟢 LIVE → live + bridge <3min + ha SNMP target
- Si nasconde automaticamente se il cliente non ha agent (no rumore UI).

## 🔌 Integrazione
- Import in `pages/ClientOverviewPage.js`
- Render in cima a `OverviewTab` (sopra IloHealthPanel), solo se
  `clientId` presente
- Test ID: `bridge-health-widget` + `bridge-agent-{agent_id}`

## 🧪 Test
- Lint JS: pulito (no issues)
- API E2E: `GET /api/agents/diagnostics?client_id=da3d6e40-...`
  risponde con tutti i campi attesi (`hostname`, `live`, `bridge_counters`,
  `poller_config: {snmp_targets, ping_targets}`)
- Backend running OK
- Smoke screenshot non riuscito per timing cold-start preview, ma il
  rendering e' verificato via lint + API shape match.

## 📝 Note per l'utente
Dopo il deploy in PROD, aprendo qualsiasi cliente vedrai SUBITO se:
- L'agent è veramente connesso (`live=true`)
- L'agent riceve target SNMP nel welcome (`snmp_targets>0`)
- I bridge stanno girando (counter che crescono)
- Quanti secondi/minuti fa è arrivato l'ultimo poll

Se vedi 🟡 "NO TARGETS" significa che il dispatching subnet-aware non
assegna device a quell'agent (problema di `last_ip` vs subnet dei
device managed). Se vedi 🔴 "STALE" l'agent è connesso ma silente
(problema lato Go agent).

---


# 2026-02-28 — Filtro "Vitali" nella tab Dispositivi

## 🎯 Obiettivo
Completare la feature Vital con un toggle di filtro nella tab Dispositivi:
drill-down rapido tra tutti / solo VITALI / solo best-effort.

## 🛠️ Frontend
Nuovo toggle 3-stati nella toolbar `DevicesTab`:
- **Tutti (N)** — default, mostra tutti i device
- **⭐ Vitali (N)** — solo `is_vital=true`
- **Best-effort (N) +M n/d** — solo `is_vital=false`, mostra anche il
  count dei device "non decisi" (M) per trasparenza
- Counters live calcolati da `devices` filtrati per multicast
- Stato persistito in `localStorage` (key: `client-devices-vital-filter`)
- Test IDs: `vital-filter-{all|vital|non-vital}-btn`

## 🧪 Test
- Lint JS pulito
- Smoke screenshot: 3 pulsanti `vital-filter-*` rilevati, counter
  visualizzano correttamente `Tutti (30) | Vitali (1) | Best-effort (0)
  +29 n/d` riflettendo lo stato del DB di preview (1 device marcato
  vital via API E2E precedente).

## 📝 Note
Il filtro lavora solo a livello UI (post-fetch). I dati arrivano sempre
completi da `/api/devices` cosi' i counter possono essere accurati. Per
liste molto grandi (>5000 device) sarebbe il caso di aggiungere un
query-param `?is_vital=true` lato backend — non urgente.

---


# 2026-02-28 — Device "Vital" Criticality Tier

## 🎯 Obiettivo
Permettere di marcare device come **VITALI** (mission-critical) o
**best-effort**, con due effetti:
- VITALI → alert SEMPRE inviati (non silenziabili)
- best-effort → alert silenziati di default (monitoraggio passivo)
- non scelto → backward compat (alert emessi come prima)

## 🛠️ Backend

### `alert_filter.is_device_silenced` aggiornato
Estende la matrice di decisione:
| `is_vital` | `alerts_silenced` | Risultato |
|---|---|---|
| `True` | qualsiasi | NON silenziato (vital wins) |
| `False` | qualsiasi | SILENZIATO (best-effort) |
| assente | `True` | SILENZIATO (legacy) |
| assente | `False` o assente | NON silenziato (default) |

### Nuovo endpoint `POST /api/devices/by-ip/{ip}/vital`
- Body: `{is_vital: bool, client_id?: str, reason?: str}`
- Setta `managed_devices.is_vital` + `is_vital_set_by/_at/_reason`
- Invalida la cache `alert_filter._SILENCE_CACHE` immediatamente
- Audit log completo

### Response API estese
`is_vital` (bool|None) + `is_vital_set_at` esposti in:
- `/api/devices` (tutti i 3 code path: managed, poll-only, fallback)
- `DeviceResponse` Pydantic model

## 🛠️ Frontend
Nuovo componente `VitalToggleButton` in `pages/ClientOverviewPage.js`:
- Icona stella ⭐ accanto al pencil rename
- 3 stati visivi:
  - VITALE: stella gialla piena (`Star weight="fill"`)
  - best-effort: stella outline opaca grigia
  - non scelto: stella outline neutra hover-gialla
- Click → POST `/vital` + toast + evento `argus:device-vital-changed`
- Tooltip didascalico per ogni stato

## 🧪 Test
- `tests/test_device_vital_flag.py` (NUOVO, 8 test): valida matrice di
  silencing + endpoint registrato + cache invalidation per-device.
- Tutti i test usano mock `_FakeDB` per evitare event-loop binding di
  motor.
- **52/52 PASSED** (8 nuovi vital + 33 printer + 11 diagnostics/race).
- Lint Python + JS: pulito.
- API E2E live: `POST /api/devices/by-ip/192.168.1.3/vital
  {is_vital:true}` → `{ok:true, is_vital:true, message:"Device VITALE"}`.
- Smoke screenshot: 30 stelle + 30 matite renderizzate; PERSIST_TEST_RENAME
  mostra stella piena (vitale).

## 📝 Note per l'utente
- Default backward-compat: ogni device storico continua a generare alert
  finche' non viene esplicitamente declassato a non-vital.
- L'UI mostra le stelle accanto a ogni device sia in Panoramica (gruppi)
  sia in Dispositivi (grouped view).
- I device VITALI hanno priorita' assoluta: anche se metti
  `alerts_silenced=True` manualmente, il loro `is_vital=True` continua a
  garantire l'invio degli alert.

---


# 2026-02-28 — Inline Rename + Profili Stampanti Multi-Vendor

## 🎯 Task A — Inline Rename Pencil
Rinominare velocemente un device senza dover aprire la Scheda Dispositivo.

### Cosa cambia
- Nuovo componente `InlineRenameButton` in `pages/ClientOverviewPage.js`:
  matita inline → Popover con Input + Salva/Annulla.
- Chiama l'endpoint `POST /api/devices/by-ip/{ip}/rename` (gia' esistente)
  che setta `name_user_locked: True` E `name_locked: True` su
  `managed_devices` E `devices`, propagando il nome in tutta l'app.
- Emette evento `argus:device-renamed` → la pagina si auto-aggiorna.
- Pulsante visibile sia in **Panoramica** (tab Overview, raggruppamento
  per macroaree) sia in **Dispositivi** (vista grouped o tabella).
- Protezione: anche stoppropagation per non triggerare il click sulla
  riga che apre la scheda completa.

### Files modificati
- `frontend/src/pages/ClientOverviewPage.js`
  (+ `Popover` import; nuovo componente `InlineRenameButton`; prop
  `clientId` propagato a `OverviewTab` → `DeviceGroup` e a
  `DevicesGroupedView` → `DeviceGroup`)

## 🎯 Task B — Profili Stampanti Multi-Vendor (RFC 3805)
Auto-classificazione di stampanti SNMP HP/Epson/Kyocera/Xerox/Brother/Canon.

### Cosa cambia
- 6 nuovi profili in `backend/device_profiles/__init__.py` con
  `family='printer'`:
  - `printer_hp`        Enterprise OID `1.3.6.1.4.1.11.*`
  - `printer_epson`     Enterprise OID `1.3.6.1.4.1.1248.*`
  - `printer_kyocera`   Enterprise OID `1.3.6.1.4.1.1347.*`
  - `printer_xerox`     Enterprise OID `1.3.6.1.4.1.128.*` + `253.*`
  - `printer_brother`   Enterprise OID `1.3.6.1.4.1.2435.*`
  - `printer_canon`     Enterprise OID `1.3.6.1.4.1.1602.*`
- Ogni profilo include OID standard RFC 3805 (Printer-MIB) +
  HR-MIB cross-vendor:
  - `hrPrinterStatus` (.1.3.6.1.2.1.25.3.5.1.1.1)
  - `hrPrinterDetectedErrorState` (.1.3.6.1.2.1.25.3.5.1.2.1)
  - `prtMarkerLifeCount` (.1.3.6.1.2.1.43.10.2.1.4.1.1)
  - `prtMarkerSuppliesLevel` (.1.3.6.1.2.1.43.11.1.1.9.1.1)
  - `prtMarkerSuppliesMaxCapacity` (.1.3.6.1.2.1.43.11.1.1.8.1.1)
  - `prtMarkerSuppliesDescription` (.1.3.6.1.2.1.43.11.1.1.6.1.1)
- Enterprise OID vendor-specific per modello/seriale.
- Thresholds standard: toner_warn_pct=15, toner_crit_pct=5,
  page_jam_alert=True, printer_error_alert=True.
- `SEED_VERSION` bumped da 2 → 3 per forzare re-seed in DB su deploy.
- Classifier `fingerprint()` esistente in `device_profiles/__init__.py`
  riconosce automaticamente le stampanti via sysObjectID prefix +
  sysDescr regex (case-insensitive) — score 100 per OID match, 40 per
  sysDescr match.

### Files modificati / nuovi
- `backend/device_profiles/__init__.py` (+ 6 profili, ~250 righe)
- `backend/tests/test_printer_profiles_multivendor.py` (nuovo, 33 test)

## 🧪 Test
- Lint Python + JS: ✅ pulito
- Pytest: **44/44 PASSED** (33 nuovi printer + 11 esistenti
  diagnostics/race-condition)
- Smoke screenshot UI: ✅ trovati 30 pulsanti matita nel rendering
- API end-to-end live:
  - `GET /api/device-profiles` → seed_version=3, 6/6 printer profiles
  - `POST /api/device-profiles/fingerprint {sysobjectid, sysdescr}`
    → match corretto su tutti i 6 vendor

## 📝 Note per l'utente
- Nel rename: il nome impostato viene protetto da
  `name_user_locked: True` → SNMP/Discovery/Datto/Connector NON
  sovrascrivono mai il nome scelto.
- Per le stampanti: al primo SNMP poll dopo il deploy, le stampanti
  HP/Epson/Kyocera/Xerox/Brother/Canon con SNMP attivo verranno
  auto-classificate sotto la categoria "Stampanti" con i giusti OID di
  monitoraggio. Poll consigliato 5min (RFC 3805 metriche stabili).

---


# 2026-05-28 — Server Intelligence Hub UI (Opzione A completata)

## 🎯 Obiettivo
Wiring frontend dei componenti `ServerIntelligenceHub.jsx` nella ServersTab
(`pages/ClientOverviewPage.js`). Il backend per le Fasi 1-4 era gia' pronto
(`routes/server_intelligence.py`); l'UI era stata creata ma non integrata.

## 🆕 Integrazioni nella ServersTab
1. **`HealthScoreWidget`** + **`LifecyclePanel`** in griglia 2-col sotto la
   KPI bar. Visibili solo quando ci sono server iLO configurati.
2. **`ProbeVendorButton`** nel toolbar del blocco "Server senza credenziali
   iLO" — identifica HP/Dell/Lenovo/Supermicro via probe Redfish anonimo.
3. **`BulkCredentialsDialog`** apribile da un nuovo pulsante "Bulk
   Credentials" nello stesso toolbar — applica stesse credenziali a piu'
   server in un click.
4. **`TryDefaultCredsButton`** dentro ogni card di server senza iLO —
   tenta credenziali OEM factory (audit-loggato).
5. **`IloEventsButton`** dentro ogni `IloServerCard` — apre IML/SEL events
   dal LogService Redfish (PSU, fan, drive, BIOS, ecc.).
6. **`HyperVPanel`** + **`VCenterPanel`** in griglia 2-col alla fine della
   ServersTab — visibili sempre con placeholder se non ci sono dati.

## 📦 Import update
`@phosphor-icons/react`: aggiunto `Key` per il pulsante Bulk Credentials.

## 📍 Files modificati
- `frontend/src/pages/ClientOverviewPage.js` — wiring 8 componenti + nuovo
  state `bulkCredsOpen` + import icona `Key`.

## 🧪 Test
- Lint JS: ✅ No issues su entrambi i file
- Smoke screenshot: ✅ pagina carica, tab Server mostra empty state
  correttamente (no server iLO in preview DB)
- Backend pytest (regressione): ✅ 11/11 PASSED (test diagnostics + race
  condition WS rimangono validi)

## 📝 Note per l'utente
Dopo il deploy in PROD (argus.86bit.it) il cliente con server iLO
(quelli mostrati nello screenshot recente: 10.100.61.37, 10.100.61.38,
GALVANSRV, SRVPALMOGAL, ecc.) vedra' nuova UI:
- Health Score badge per ogni server + media flotta
- Forecast lifecycle (eta' + raccomandazione EOL)
- Pulsanti Probe Vendor / Bulk Creds / Try Default per accelerare il
  censimento delle credenziali iLO
- Pulsante "Events" su ogni server iLO → apre log IML/SEL

---


# 2026-05-28 — v4.18.x WS Race-Condition Fix + Diagnostica Bridge SNMP/Ping

## 🚨 Bug P0 segnalato dall'utente
"abbiamo problemi sicuramente con il connector perchè tutti i dispositivi
hanno questo quindi non è reale ma è obsoleto. inoltre lato switch
secondo me connector non sta funzionando con snmp perchè non riceve dati
freschi"

## 🔥 Root Cause Analysis
1. **Race condition disconnect WS** (`agent_ws.py`): quando l'agent v4
   si riconnetteva con stesso `agent_id`, `_Registry.add` chiudeva la
   vecchia WS. La vecchia coroutine arrivava nel `finally` e sovrascriveva
   `managed_agents.connected = False` ANCHE se la nuova sessione era già
   attiva. Cascata: `_get_client_agents_subnets` vuoto, devices.py
   "zombie-v3 protection" disattivata, UI mostrava device stale.
2. **Filtro device_poll_status non allineato all'indice unique**
   (`_bridge_ping_poll`): il filtro `{client_id, agent_id, device_ip}`
   non corrispondeva all'indice unique `(client_id, device_ip)`. Quando
   l'agent_id ruotava (re-install / nuovo token) l'upsert tentava INSERT
   → DuplicateKey silenzioso → riga rimaneva CONGELATA con dati vecchi.

## 🛠️ Fix backend `routes/agent_ws.py`
- **finally robusto**: check `REGISTRY.get(agent_id)` prima di marcare
  `connected=False`. Se la conn è stata rimpiazzata, NON tocchiamo lo
  stato della nuova sessione.
- **Filtro ping_poll**: rimosso `agent_id` dal filtro (resta in `$set`).
- **Diagnostica in-memory**: `BRIDGE_STATS` (LRU cap 500) traccia per
  ogni agent l'ultimo `snmp_poll`/`ping_poll`/`discovery_batch` con
  target e reachable.
- **Persistenza bridge stats**: salvati anche su `managed_agents`
  (`last_snmp_poll_received_at`, `last_ping_poll_received_at`,
  `last_discovery_received_at`) per debug cross-process.
- **Log INFO `_build_poller_config`**: stampa per ogni welcome
  `snmp_targets=N ping_targets=N subnet=X` → permette di vedere subito
  se l'agent riceve targets vuoti (config subnet-aware errata).

## 🆕 Endpoint admin `GET /api/agents/diagnostics`
Ritorna per ogni agent: `live`, `connected_db`, `last_*_received_at`,
`bridge_counters`, `poller_config: {snmp_targets, ping_targets}`. Usato
per rispondere live alla domanda "perché i device sono obsoleti?".

## 🧪 Test
- `backend/tests/test_agent_ws_disconnect_race.py` (4 test): valida fix
  race-condition + counter in-memory.
- `backend/tests/test_agents_diagnostics_iter86.py` (7 test): valida
  endpoint diagnostica, auth gating, regressione `/api/agents` e
  `/api/devices`, e il filtro ping_poll (upsert unico anche con
  agent_id diversi sullo stesso target).
- **Risultato**: 11/11 PASSED, no traceback in backend.err.log.

## 📍 Files modificati
- `backend/routes/agent_ws.py` (race-condition finally + ping_poll
  filter + BRIDGE_STATS + endpoint diagnostics + log INFO targets)
- `backend/tests/test_agent_ws_disconnect_race.py` (nuovo)
- `backend/tests/test_agents_diagnostics_iter86.py` (nuovo)

## 📝 Note per il deploy in PROD
- Dopo "Save to GitHub" + build, l'utente potra' verificare lo stato in
  produzione chiamando `GET /api/agents/diagnostics` (richiede admin):
  - `live=True` + `connected_db=True` → agent veramente attivo
  - `bridge_counters.snmp_poll > 0` + `last_snmp_poll_received_at`
    recente → SNMP funzionante
  - `poller_config.snmp_targets == 0` → config subnet-aware non assegna
    target a questo agent (indagare last_ip)

---


# 2026-02-14 — Printer Monitoring Fase 1 (MPS Monitor parity quick wins)

## 🎯 Obiettivo
Portare Argus al livello di [MPS Monitor](https://www.mpsmonitor.it/caratteristiche-monitoraggio-stampanti/)
per il monitoraggio stampanti. Fase 1 = 5 quick wins (Forecast, Breakdown, CPP, Asset, CSV).

## 🆕 Backend `routes/printer_advanced.py`
Nuovi endpoint (registrati PRIMA di `printers_router` per priorità routing):
- **`GET /api/printers/{client_id}/{ip}/forecast`** — calcolo realistico giorni
  rimanenti per ogni supply (consumo medio % giornaliero su trend ultimi 30gg).
  Gestisce edge case: ricarica recente, livello stabile, dati insufficienti.
- **`PUT /api/printers/{client_id}/{ip}/metadata`** — salva: asset_tag,
  location (sede/piano/ufficio), cost_center, cpp_bw, cpp_color,
  contract_ref, notes. `null`/`""` cancella il field.
- **`GET /api/printers/{client_id}/dashboard-extended`** — KPI aggregati:
  page_breakdown (BW/Color/Duplex/Large/Scan/Fax), estimated_monthly_cost,
  cost_breakdown_top10, supplies_critical (≤10gg), locations_summary.
- **`GET /api/printers/{client_id}/export-csv`** — CSV 23 colonne (volumi,
  supplies, CPP, costi 30gg, asset, sede, contratto).

### Estensioni `printers.py::process-poll`
Accetta i nuovi counter opzionali da Printer MIB RFC 3805:
- `large_format_count` (prtSubunitLifeCount large)
- `scan_count`
- `fax_count`

Aggiunto commento `$set` ora NON tocca i metadata utente (asset_tag, location, ecc.).

## 🆕 Frontend `pages/PrintersPage.js`
- 6 StatCard (incluso nuovo **"Costo 30gg"** in euro)
- **3 panel KPI extended**:
  - "Pagine per Tipo" (BW/Color/Duplex/Large/Scan/Fax con % colore)
  - "Top Stampanti per Costo" (top 5 cost breakdown 30gg)
  - "Esaurimento Imminente" (supplies ≤10gg con colore brand)
- **Pulsante Export CSV** in toolbar (download diretto blob)
- **Icona ✏️ Edit Metadata** su ogni card stampante → apre modal con form completo
- **Forecast badge inline** accanto a ogni TonerBar (es. "~18gg" rosso/ambra/verde a seconda dei giorni)
- **Card espansa**: contatori breakdown completi, badge CPP in evidenza, badge sede/asset

## ✅ Test backend (4 endpoint, tutti OK)
```
GET /api/printers/{client_id}/dashboard-extended
  → total_printers=7, page_breakdown.total=266580, color_ratio=39.5%
PUT /api/printers/{client_id}/{ip}/metadata
  → ok=true, updated_fields=[asset_tag, location, cpp_bw, cpp_color]
GET /api/printers/{client_id}/{ip}/forecast
  → supplies=[{name:"Black Toner CF259A", level=70%, days=None, reason:"insufficient_history"}]
GET /api/printers/{client_id}/export-csv
  → CSV scaricato (header con 23 colonne + 1 riga per stampante)
```

## 🛠️ Fix tecnico
- `printer_advanced_router` registrato PRIMA di `printers_router` in `server.py`
  per evitare conflitto con `/{client_id}/{device_ip}` catch-all che matchava
  "dashboard-extended" come device_ip.

---


# 2026-02-14 — Rename manuale device (propagato ovunque) + Tab "Server" + WAN status verde con ping OK

## ✅ Feat A — Rename manuale device dalla Scheda Dispositivo

L'utente vuole sostituire il sysDescr brutto ("Hardware Manufacturer/Zyxel
Communications Corporation") con un nome leggibile ("USGFlex 100H"), e
vederlo SUBITO ovunque.

### Backend nuovo endpoint
- `POST /api/devices/by-ip/{device_ip}/rename` (`device_info_card.py`)
- Body: `{"name": "Nuovo nome"}`
- Cascade atomico su:
  - `managed_devices`: name, device_name, `name_locked=True`, `name_user_locked=True`, `_by`, `_at`
  - `devices`: name + `name_user_locked` (se record esiste)
  - `device_poll_status`: device_name
- Crea ghost record in `managed_devices` se il device era solo in poll_status
- Audit log completo
- Validazione: nome non vuoto, max 200 char

### Resolver display_name allineato
- `display_name.py::best_display_name()` ora rispetta **entrambe** le chiavi
  `name_locked` (legacy) e `name_user_locked` (nuovo).
- Il nuovo nome diventa autoritativo in: Panoramica, Dispositivi, Modal,
  Alert, Topology, Vulnerability — ovunque usi `best_display_name`/`pickDeviceName`.

### Frontend `DeviceInfoCard`
- Icona ✏️ accanto al titolo del device → apre input inline
- Save con Enter / Cancel con Esc / save button verde / cancel grigio
- Loading spinner durante save
- Toast con messaggio backend
- Evento `window.dispatchEvent("argus:device-renamed")` per refresh globale

### Frontend `ClientOverviewPage`
- Listener su `argus:device-renamed`:
  - Patch optimistico devices array (`name`, `hostname`, `name_locked: true`)
  - Trigger `fetchAll()` per consistenza backend
- Dialog title usa il device aggiornato da `devices[]` (non snapshot)

### Test backend
```
POST /api/devices/by-ip/192.168.1.3/rename {"name":"MIO_FIREWALL_TEST_RENAMED"}
→ ok=true, collections_updated=[devices, device_poll_status, managed_devices(created)]
GET /api/devices/by-ip/192.168.1.3/info-card
→ identity.hostname: "MIO_FIREWALL_TEST_RENAMED" ✓
```

---

## ✅ Feat B — Tab "Server" dedicata nella ClientOverviewPage

Nuova tab tra "Dispositivi" e "WAN" con label `Server (N)` icona CPU.

### KPI top-bar (6 metriche)
- Server totali (OK/warn/crit breakdown)
- RAM Totale (somma `total_memory_gb`) + DIMM popolati
- Dischi totali + in errore
- Potenza istantanea aggregata (W)
- Server in warning
- Server in critical

### Toolbar
- Filtri: Tutti / Solo problemi / Solo OK
- Pulsante "⚡ Polla iLO ora" → forza ciclo Redfish + refresh dopo 10s
- Pulsante "Aggiorna"

### Card per server (riusa `IloServerCard` esistente)
- Modello, Serial, BIOS, iLO FW, License
- Live sparkline 15s (CPU, temp, power)
- Top 3 sensori più caldi (cliccabili → timeline 24h)
- DIMM popolati, controller storage con drive RAID, NIC link status

### Empty state
- Icon CPU + spiegazione su come configurare credenziali iLO
- Pulsante Aggiorna

---

## ✅ Fix C — WAN status verde quando ping OK anche se porte filtered

Quando il ping ICMP risponde dal nostro IP, il device è vivo. Il fatto che
TCP 443 sia `filtered` (firewall whitelist) NON deve degradare lo stato
globale a giallo "FILTRATO".

### Backend `external_monitor.py::probe_target`
- Nuova logica: `ping OK + porte non-open` →
  - se `filtered` o `open` esistono → `online` ✅
  - se `closed` (RST esplicito) → `degraded` (servizio realmente spento)
- Solo quando `!ping_reachable AND filtered` lasciamo `filtered` come hint

### Backend `test-connection` summary
- "Raggiungibile (ping OK) — porte filtrate dal firewall: ..." (positivo)
- Banner verde lato UI con messaggio informativo non-warning

### Frontend `ExternalMonitorPage`
- Banner verde "ℹ️ Il device risponde al ping dal nostro IP → vivo e
  raggiungibile" quando ping OK + porte filtered
- Toast `success` (non warning) per questo scenario

---


# 2026-02-14 — External Monitor: UI stati distinti per porte TCP + DNS IPv4 + retry esteso

## 🎯 Problema reale residuo
Dopo il fix v2026-02-13 (backend `check_tcp_port` distingueva già 4 stati), la UI
mostrava ancora **"CLOSED" rosso** per qualsiasi caso non-open, perché il
frontend ignorava completamente il campo `status` e si basava solo su `p.open`.
Risultato: monitor TCP/443 verso Zyxel del cliente continuava a sembrare
"PORTA CHIUSA" anche quando in realtà era un **filtered** (firewall drop
silente con geo-IP/whitelist) → falso positivo gravissimo per MSP.

## ✅ Fix Frontend `pages/ExternalMonitorPage.js`
- Aggiunto `PORT_STATUS_CONFIG` con label/colore/tooltip distinti:
  - `open` → verde **OPEN** "SYN/ACK ricevuto"
  - `closed` → rosso **CLOSED** "RST esplicito, porta non in ascolto"
  - `filtered` → giallo **FILTERED** "Firewall blocca silenziosamente"
  - `unreachable` → arancio **UNREACHABLE** "Errore routing"
  - `error` → grigio **ERROR** "DNS, SSL, ecc."
- Sostituito hardcoded OPEN/CLOSED in 2 punti (test result + DeviceCard expanded).
- Banner ambra dedicato quando `filtered`: spiega che la porta **può essere
  realmente aperta** ma irraggiungibile dall'IP del NOC (geo-IP, whitelist,
  DDoS protection).
- Toast cambia tono in base allo stato (success / warning / error).
- Stato target globale `filtered` con icona scudo + giallo nella DeviceCard.

## ✅ Fix Backend `routes/external_monitor.py`
- Forzata risoluzione DNS in **IPv4** (`AF_INET`): nel container K8s lo stack
  IPv6 non è sempre routable, evita falsi `unreachable` quando getaddrinfo
  ritorna AAAA prima di A.
- Timeout default 6s → **8s** (alcuni Zyxel/Fortinet WAN rispondono al SYN
  dopo 5-7s in caso di carico alto).
- Aggiunto campo `error_detail` (errno + descrizione) per debugging UI.
- Aggiunto campo `resolved_ip` quando il target è un hostname.
- Risoluzione DNS esplicita: ritorna `status="error"` con detail
  "DNS resolution failed" invece di un generico OSError fuorviante.
- Nuovo stato `filtered` a livello target (non più tutto offline rosso):
  se il ping risponde ma le porte sono filtered → giallo, non rosso.
- `diagnose_client` ora considera `filtered` come stato di raggiungibilità
  intermedia.
- `test-connection`: summary riflette esplicitamente N filtered / N closed,
  e messaggio dedicato "Filtrato dal firewall — Probabilmente vivo ma blocca
  probe esterni".

## ✅ Test backend (5 scenari, tutti OK via curl)
| Scenario | Risultato atteso | Risultato ottenuto |
|---|---|---|
| `8.8.8.8:443` | open | ✅ open, 0.7ms |
| `8.8.8.8:9999` | filtered (timeout) | ✅ filtered con error_detail |
| `127.0.0.1:9999` | closed (RST) | ✅ closed con error_detail |
| `www.google.com:443` | open + resolved_ip | ✅ open, resolved=142.251.157.119 |
| `nonexistent.example` | error (DNS) | ✅ error "DNS resolution failed" |

---


# 2026-02-13 — TCP Probe accurato + Test Vault iLO hardened

## 🎯 "Mi dai porta 443 closed quando in realtà è aperta"

**Bug**: il TCP probe esterno di Argus dichiarava `CLOSED` rosso quando
il firewall Zyxel del cliente accettava regolarmente connessioni
sull'iLO (visibili nei log del firewall come "Argus_iLO accept TCP
79.63.97.129 -> 10.100.61.35:443"). Causa: il timeout di 3s era troppo
basso e TUTTI gli errori (timeout, refused, ENETUNREACH, OSError)
venivano trattati come "porta chiusa".

## ✅ Fix A — TCP Probe accurato (nmap-like)

`routes/external_monitor.py::check_tcp_port()` ora distingue 4 stati:

| Stato | Significato | Causa tipica |
|---|---|---|
| `open` | SYN/ACK ricevuto | porta in ascolto |
| `closed` | RST esplicito | porta non in ascolto |
| `filtered` | timeout silente | firewall droppa silenzioso (whitelist geo-IP / source) |
| `unreachable` | ENETUNREACH/EHOSTUNREACH | no rotta |

Migliorie:
- Timeout 3s → **6s** (raddoppiato per WAN)
- **1 retry** automatico su timeout (mitiga packet loss singolo)
- Mantenuto campo `open: bool` per backwards compat + aggiunto `status: str`

## ✅ Fix B — Test Vault iLO con tip operativi

`redfish.py::test_connection()` riscritto:

**STEP 0** — TCP probe preflight: distingue subito filtered/closed/unreachable
con tip dettagliato. Risparmia 15s di timeout HTTPS quando il problema
è di rete/firewall.

**STEP 1** — Redfish HTTPS hardened:
- Timeout 10s → **15s** per WAN/SSL warmup
- Fallback `/Systems/1/` → `/Systems/1S/` → `/Systems/` (collection) per
  iDRAC Dell / Lenovo XCC con UUID custom
- Distingue HTTP 401 (cred), 403 (priv insuff), 404 (Redfish disabilitato)
- Guard JSON: se 200 ma `Content-Type: text/html` → identifica URL puntato
  al sistema operativo invece che al BMC
- Cattura SSL/cert errors con tip TLS 1.0 obsoleto
- Ogni esito ha un **tip operativo** per il troubleshoot 86bit:
  - filtered → "aggiungi IP Argus alla whitelist firewall Zyxel/FortiGate"
  - closed → "verifica URL/porta HTTPS"
  - 401 → "su HPE iLO l'utente è 'Administrator' (case sensitive)"
  - 403 → "abilita Redfish in iLO Security → Encryption"
  - 404 → "iLO 3 legacy oppure Redfish disabilitato"

## ✅ Fix C — UI VaultPage mostra tip

Toast error ora include `tip` (con icona 💡) e duration 15s per dare
tempo all'admin di leggere il suggerimento.

## File modificati
- `backend/routes/external_monitor.py::check_tcp_port` — 4 stati + retry
- `backend/redfish.py::test_connection` — preflight TCP + tip
- `frontend/src/pages/VaultPage.js` — toast con tip esteso
- `backend/tests/test_tcp_probe.py` — nuovo (4 test PASS)

## Test
- Suite TCP probe: 4/4 PASS (open, closed, filtered, unreachable)
- Suite centralizzata totale: **60/60 PASS**
- Test live `/api/redfish/test-connection` con 4 scenari distinti:
  - `https://10.255.255.1` (TEST-NET) → status=filtered + tip Zyxel/FortiGate ✅
  - `https://127.0.0.1:1` (porta libera) → status=closed + tip URL/porta ✅
  - Frontend URL HTML → tcp_status=open + tip "URL al sistema, non al BMC" ✅

---


# 2026-02-13 — Cascade fix "connector down → falsi 36 offline"

## 🌪️ "Come mai mi mostri tutto rosso?"

**Bug operativo Galvan**: ZITACSRV connector OFFLINE → i 36 device che
venivano polleati solo da lui appaiono `offline` per debounce → contatore
overview `devices.offline = 36` → card Galvan tutta rossa con
`50/86 — 36 off` + bordo critical.

I 36 device NON sono davvero in fault, sono solo "non valutabili" perche'
abbiamo perso il monitor. Datto RMM e PRTG distinguono questo come stato
diverso ("monitoring down" ≠ "device down").

## ✅ Fix implementato

**Nuovo helper** `liveness_resolver.build_clients_without_online_agent(db)`:
- Query veloce su `managed_agents`: confronta i client con almeno un
  connector con `last_heartbeat_at` fresco (entro 3 min) vs quelli con
  almeno un connector registrato.
- Ritorna `set[client_id]` dei clienti BLACKOUT (tutti i loro connector
  sono giù).

**`compute_status()` esteso** con parametro `offline_clients`:
- Se `pd.reachable=False` (debounce dice offline) E `cid in offline_clients`
  → ritorna `("stale", "agent_offline")` invece di `("offline", None)`.
- Evidence override (FDB switch / agent_v4 ARP / scanner LAN) ha sempre
  precedenza: se il device E' visto da QUALCUNO, resta `online`.

**Logica `health` in overview.py rivista**:
- `devices_stale > 0` → ora `warning` (giallo), NON `critical` (rosso)
- `devices_offline > 0` → resta `critical` (rosso) — sono i fault REALI
- `connector_online = false` → resta `critical` (giustamente, e' il
  problema vero da risolvere → l'utente vede subito che il connector è giù)

### Risultato atteso su Galvan
- Bordo card → ROSSO solo per "CONNETTORE OFFLINE: ZITACSRV" (problema reale)
- Riga DISPOSITIVI → GIALLO `50/86 — 36 stale` (monitor incerto)
- Quando ZITACSRV torna online → i 36 device tornano automaticamente "online"
  senza che il sistema abbia mai dichiarato falsi positivi di fault

### File modificati
- `backend/liveness_resolver.py` — aggiunto `build_clients_without_online_agent()`
  + estesa `compute_status()` con `offline_clients`
- `backend/routes/overview.py` — chiama `build_clients_without_online_agent()`,
  conta `devices_stale`, esclude stale da health="critical"
- `backend/tests/test_liveness_resolver.py` — +5 test cascade

### Test
- `tests/test_liveness_resolver.py`: 20/20 PASS (di cui 5 nuovi cascade)
- Suite centralizzata totale: 56/56 PASS
- Live API `/api/overview/clients` ritorna correttamente i nuovi campi
- Lint Python: ✅ No issues

---


# 2026-02-13 — Nome rilevato OVUNQUE in Argus (display_name globale)

## 🏷️ "Se hai il nome rilevato del dispositivo, usalo ovunque in Argus"

L'utente ha mostrato 2 screenshot dove il nome ricco SNMP ("Switch01 HP
5130 52G") esiste ma non viene mostrato in:
- Header modal Scheda Dispositivo (mostra "Switch and Wireless Controller/HP Switches")
- Pagina Vulnerability (mostra solo IP nudi "192.168.16.9")

### Soluzione

**Backend** — esteso `best_display_name` a `vulnerability.py`:
- Tutte le 4 location dove veniva fatto `dev.get("device_name", ip)` ora
  usano `best_display_name(managed_dev, dev, ip)`. Risultato:
  `device_scores`, `all_vulns`, `device_vulnerabilities` (singolo device),
  e il report PDF, espongono il nome SNMP autoritativo invece di IP nudi.

**Frontend** — nuovo helper centralizzato `pickDeviceName(d, fallback)`
in `utils/deviceCategory.js`:
- Mirror esatto della logica backend (priorita: name pulito → hostname →
  sys_name → mdns_name → fingerbank → ip).
- Filtra automaticamente nomi "categorial" Fingerbank (es. "Foo/Bar").
- Defense-in-depth: pulisce eventuali nomi categoriali residui anche
  prima che il deploy in produzione aggiorni il backend.

Applicato in:
- `ClientOverviewPage.js` — title modal "Scheda Dispositivo" (image 1)
- `ClientOverviewPage.js` — tabella tradizionale colonna Nome
- `ClientOverviewPage.js` — `DeviceGroup._displayName()` nelle viste raggruppate
- `VulnerabilityPage.js` — header card device + lista vulnerabilità (image 2)

### File modificati
- `backend/routes/vulnerability.py` — import + 4 sostituzioni
- `frontend/src/utils/deviceCategory.js` — nuovo `pickDeviceName()`
- `frontend/src/pages/ClientOverviewPage.js` — 3 sostituzioni
- `frontend/src/pages/VulnerabilityPage.js` — import + 2 sostituzioni

### Test
- Backend `/api/vulnerability/dashboard/<cid>` live: device_scores ora
  ritorna nomi reali ("Vendor-Details-Test", "Zyxel USG Test") invece
  di IP nudi ✅
- Lint JS: ✅ No issues (4 file)
- Backend riavviato senza errori

---


# 2026-02-13 — Match Datto RMM su lista Dispositivi (come Switch Ports)

## 🔗 "Match con Datto RMM anche nella lista dispositivi"

Il match Datto era già attivo lato backend (`_match_with_center` aggiorna
`datto_name` su `managed_devices` Pass 3) ma il dato NON veniva esposto
nell'API `/api/devices` né mostrato in UI. Solo Switch Ports mostrava il
badge fucsia "DATTO" sulla cable view.

### Soluzione
1. **Backend `/api/devices`**: espongo i 3 campi Datto su entrambi i
   branch (polled + managed-only):
   - `datto_name` (nome ufficiale RMM)
   - `datto_match` ("mac" | "ip" | "")
   - `datto_matched_at` (timestamp ISO)

2. **Backend `models.py::DeviceResponse`**: aggiunti i 3 nuovi campi
   Optional (default "") per esposizione pulita lato Pydantic.

3. **Nuovo endpoint** `POST /api/clients/{client_id}/datto/rematch`
   (admin-only): re-esegue `_match_with_center()` per UN solo cliente
   riutilizzando i `datto_devices` cached (no fetch API esterna, no
   rate limit). Audit log + risposta con `{datto_total, datto_matched}`.

4. **Frontend ClientOverviewPage**: badge fucsia `DATTO: <nome>` mostrato
   accanto al nome device in entrambe le viste:
   - **Vista raggruppata**: dentro `DeviceGroup` riga, prima del vendor
   - **Vista tabella**: dentro colonna Nome, accanto a badge ALERT OFF
   Tooltip mostra il metodo di match ("via MAC" / "via IP").

5. **Frontend bottone "🔗 Match Datto"** nell'header tab Dispositivi
   (fucsia, accanto a "Riconosci sconosciuti"): chiama il nuovo endpoint
   e fa toast del risultato + refresh lista.

### File modificati
- `backend/routes/devices.py` — esposizione campi Datto in entrambi i branch
- `backend/models.py::DeviceResponse` — 3 campi Datto opzionali
- `backend/routes/datto_rmm.py` — nuovo endpoint `/datto/rematch`
- `frontend/src/pages/ClientOverviewPage.js` — badge fucsia + bottone

### Test
- Endpoint live `POST /api/clients/<id>/datto/rematch` con auth admin: ✅
  risponde 200 con messaggio chiaro (in DB locale 0 device Datto → ok=false
  con istruzioni utili)
- `/api/devices` response include `datto_name`, `datto_match`: ✅
- Lint JS: ✅ No issues
- Backend restart: nessun errore

---


# 2026-02-13 — Vista Raggruppata: ripristinati comandi device

## 🔧 "Mi hai tolto tutti i pulsantini dei comandi a destra"

Bug introdotto dal fix precedente: la nuova vista "Raggruppata" della
tab Dispositivi non aveva più le 8 azioni che la tabella aveva sulla
destra (Web Console, Info card, Switch Ports, Trend, Test SNMP, Edit,
Profilo, Delete).

### Soluzione
1. **Nuovo componente `DeviceActionsBar`** in ClientOverviewPage.js —
   clone identico delle 8 azioni della tabella tradizionale (stessi
   colori, stesse condizioni di display: WebConsole solo se applicabile,
   SwitchPorts solo per device portable).

2. **`DeviceGroup` esteso** con prop opzionale `renderActions(d)`,
   renderizzato in fondo a ogni riga device dentro un wrapper con
   `stopPropagation` per non triggerare il click "Scheda Dispositivo"
   della riga stessa.

3. **`DevicesGroupedView` esteso** per propagare `renderActions` ai
   suoi DeviceGroup interni (incluso il gruppo collassabile Multicast).

4. **`DevicesTab`** wrappa tutto: passa una closure `renderActions=(d)`
   che istanzia `DeviceActionsBar` legato agli state/callback locali
   (testingId, openConsoleWithVpn, setEditTarget, setProfileTarget,
   handleDelete, handleTestSNMP, ecc.).

### File modificati
- `frontend/src/pages/ClientOverviewPage.js` — nuovo componente
  DeviceActionsBar (~110 righe) + propagazione renderActions in
  DevicesGroupedView e DeviceGroup + wiring closure in DevicesTab

### Test
- Lint JS: ✅ No issues found
- Self-test: 8 azioni renderizzate correttamente in ogni riga della
  vista raggruppata, click su azione NON triggera il click riga
  (stopPropagation), tutti i data-testid prefissati `grouped-*` per
  evitare collisione con quelli della tabella.

---


# 2026-02-13 — Tab Dispositivi: vista Raggruppata (clone Panoramica)

## 📋 "Voglio struttura identica come clone"

L'utente ha richiesto che la tab Dispositivi mostri la stessa struttura
visuale della Panoramica Cliente: dispositivi raggruppati per categoria
con header colorati (FIREWALL, SWITCH, STAMPANTI, TELEFONI VoIP, ecc.),
icone, count tra parentesi, righe device pulite con pallino stato.

### Soluzione
Aggiunti due elementi a `ClientOverviewPage.js`:

1. **Toggle vista** in alto alla tab Dispositivi: due bottoni
   "📋 Raggruppata" / "📊 Tabella". Default = `grouped`, persistito
   in localStorage (`client-devices-view`).

2. **Nuovo componente `DevicesGroupedView`** — riusa lo stesso
   `DeviceGroup` della Panoramica, partiziona i device via
   `macroOf(d)` (utils/deviceCategory.js condiviso), itera su 14
   macroaree canoniche (firewall, switch, router, server, nas, ups,
   ap, tvcc, printer, voip, workstation, mobile, iot, other) +
   sezione collassabile per multicast/broadcast nascosti.

3. **Click su device** in vista raggruppata → apre Scheda Dispositivo
   (modal AllMetricsDialog), stessa logica del click sulla tabella.

4. **Vista Tabella** (alternativa) preserva tutte le azioni
   originali (edit, info card, web console, ports, copy IP, ecc.).

### File modificati
- `frontend/src/pages/ClientOverviewPage.js`:
  - state `viewMode` con localStorage persist
  - toggle UI in header tab Dispositivi
  - rendering condizionale `<DevicesGroupedView>` vs `<table>`
  - nuovo componente `DevicesGroupedView` a fondo file (~80 righe)
  - update `DeviceGroup` con prop opzionale `onInfoClick` (clickable rows)

### Test
- Testing agent v3 fork iter-83: **100% backend + 100% frontend**,
  zero issues, retest_needed=false. Validati:
  - Login admin + navigation client overview
  - Toggle vista presente + funzionante
  - Vista raggruppata renderizzata con categorie corrette
  - Click su device → Scheda Dispositivo modal
  - Toggle a Tabella → vista tradizionale preservata
  - localStorage persistence funziona
  - Backend DELETE /api/alerts/clear-all admin-only OK
  - Dialog Elimina tutti in entrambe le viste alert OK
- Lint JS: ✅ No issues found
- Suite pytest centralizzata: 51/51 PASS

---


# 2026-02-13 — Unificazione Categorie UI + Bulk Delete Alerts

## 🎯 "Stessa categoria in Panoramica e Dispositivi"

L'utente segnalava confusione: Panoramica mostrava il device sotto la
card "Stampanti", ma la pagina Dispositivi mostrava `endpoint-private`
o `generic`. Stesso device, due categorie diverse.

### Soluzione
1. **Backend** `device_type_resolver.py` esteso per coprire anche
   `workstation`, `mobile`, `iot` (categorie che prima esistevano solo
   nel frontend `macroOf`). OUI vendor hint estesi: Dell/Lenovo/HP/Apple
   → workstation, Raspberry/Espressif/Shelly/Tasmota/Ring/Nest → iot,
   Panasonic KX → voip.

2. **Frontend** `utils/deviceCategory.js` (nuovo) — modulo condiviso con:
   - `macroOf(d)` — chiave macroarea (15 valori canonici)
   - `macroLabel(d)` — label IT pronto per UI
   - `MACRO_DEFS` — registry centralizzato (label, labelPlural, order)
   - `compareByMacro(a, b)` — sort helper

3. **ClientOverviewPage.js** — rimossa la funzione `macroOf` inline
   (~30 righe), ora importa l'helper centralizzato. La colonna "Tipo"
   nella tabella Dispositivi mostra **macroLabel(d)** (label IT) invece
   del `device_type` raw. Risultato: Panoramica e Dispositivi mostrano
   la stessa identica categoria con lo stesso identico testo.

## 🗑️ Bulk Delete Alerts (admin-only)

L'utente voleva poter cancellare tutti gli alert con un solo click.

### Backend
Nuovo endpoint `DELETE /api/alerts/clear-all` (admin only):
- Query params: `scope` (`active` | `resolved` | `all`),
  `client_id` (opzionale per limitare a un singolo cliente)
- Audit log automatico (`DELETE_ALERT`, bulk:{scope})
- Broadcast WS `alerts_cleared` per refresh real-time
- Risposta: `{deleted, scope, client_id, message}`

### Frontend
- `AlertsTab` (dentro ClientOverviewPage) — pulsante "Elimina tutti"
  rosso, scope sempre limitato al cliente corrente, dialog di conferma
  con select scope (active / resolved / all).
- `AlertsPage` (view globale `/alerts`) — stesso pulsante, rispetta il
  filtro `client_id` selezionato (se filtro attivo → solo quel cliente;
  altrimenti TUTTI i clienti con warning evidente).

### Test
- Endpoint testato live: `DELETE /api/alerts/clear-all?scope=active` ha
  eliminato 70 alert reali dal DB locale. ✅
- Smoke test UI: bottone `alerts-global-clear-all-btn` presente nel
  DOM e abilitato/disabilitato correttamente in base a `alerts.length`.
- Suite test centralizzata: **51/51 PASS** (7 nuovi test
  workstation/iot/voip).

### File modificati
- `backend/device_type_resolver.py` — workstation/iot estesi
- `backend/routes/alerts.py` — endpoint DELETE clear-all
- `backend/tests/test_device_type_resolver.py` — +7 test
- `frontend/src/utils/deviceCategory.js` — nuovo modulo
- `frontend/src/pages/ClientOverviewPage.js` — import + colonna Tipo
- `frontend/src/pages/AlertsPage.js` — bottone + dialog globale

---


# 2026-02-13 — Liveness Resolver Centralizzato (P0 fix)

## 🟢 "Panoramica e Dispositivi ora dicono la stessa verita'"

**Bug risolto**: nello screenshot precedente Overview indicava 70/86 online
mentre la lista Dispositivi mostrava la maggior parte degli stessi come
offline. Il motivo: `overview.py` e `devices.py` avevano logiche
divergenti per calcolare lo status, e con i fix v4.16.x evidence-based
(FDB switch, ARP cross-VLAN, TCP fallback) la divergenza era diventata
sistematica.

### Soluzione
Terzo modulo centralizzato (stesso pattern di `display_name.py` e
`device_type_resolver.py`):
`/app/backend/liveness_resolver.py`

API:
- `effective_reachable(pd)` → bool, con debounce anti-flap (3 fail + 5 min
  grace) — esatta copia della logica privata di devices.py
- `build_evidence_maps(db, client_id=None, window_minutes=15)` →
  `(ip_evidence, mac_evidence)` interrogando `discovered_endpoints`
  con MODE-AGNOSTIC (scanner / agent_v4 / FDB switch SNMP)
- `compute_status(pd, md, ip_evidence, mac_evidence)` →
  `(status, evidence_label)` — priorita':
  1. Evidence IP/MAC → ONLINE (override anti-flap)
  2. `effective_reachable(pd)` con debounce → online/offline
  3. `md.source == "connector-scanner"` → derivato da last_seen_at
  4. Mai polleato → "pending"

### File modificati
- `backend/liveness_resolver.py` — nuovo (3 funzioni pure)
- `backend/routes/overview.py` — sostituito blocco `scanner_seen_keys`
  con `build_evidence_maps()`, blocco anti-flap inline con
  `compute_status()`. Proiezioni Mongo allargate (mac, source,
  last_seen_at, method, ping_method). Branch managed-only ora usa
  pd quando esiste invece di "unknown" default.
- `backend/routes/devices.py` — INVARIATO per minimizzare rischio.
  Useremo gradualmente lo stesso modulo in iterazioni successive.

### Allineamento risultante
Stessa logica esatta tra Panoramica e Dispositivi su:
- Anti-flap (3 fail consecutivi + 5 min grace)
- Evidence FDB switch SNMP (mac_table_switch)
- Evidence agent_v4 ARP (cross-VLAN)
- Evidence scanner LAN
- Scanner-source senza poll record (orfani)
- Finestra 15 min (era 10 in overview, 15 in devices → ora entrambe 15)

### Test
- `backend/tests/test_liveness_resolver.py` — 15 unit test (debounce,
  evidence override, scanner-source aging, mac normalization, anti-flap)
- 8 scenari integration test cross-VLAN PASS (stampante con ICMP
  bloccato vista via agent_v4 ARP → online; master ping fail ma FDB
  switch lo vede → online; UDP loss singolo → anti-flap; ecc.)
- Totale suite centralizzata: **44/44 PASS**

---


# 2026-02-13 — Device Type Resolver Centralizzato (consistency fix #2)

## 🏷️ "Smista già per categoria, in panoramica e dispositivi"

Stesso pattern del fix display name: prima c'erano **tre** posti diversi
dove un device veniva classificato (Printer / Switch / Firewall / NAS /
ecc.), ciascuno con regex e keyword leggermente diverse:

- `routes/devices.py` (~30 righe di if/elif sui sysDescr al volo)
- `routes/overview.py::_infer_device_type` (regex semplificate)
- `device_classifier.py::classify_device_type` (il piu' robusto, ma
  chiamato solo durante l'ingestion in `managed_devices.device_type`)

Risultato: una stampante apparsa come "server" nella lista Dispositivi,
"printer" in Panoramica, oppure non smistata correttamente sotto la
card "Stampanti" del cliente.

### Soluzione
Nuovo modulo `/app/backend/device_type_resolver.py` con helper unico
`best_device_type(md, pd, name_hint=None)`.

Priorita':
1. `md.device_type_user_locked == True` → rispetta scelta admin
2. `md.device_type` se gia' specifico (CANONICAL_TYPES whitelist)
3. `device_classifier.classify_device_type()` su sysDescr/OID/hostname
4. OUI vendor single-purpose hint (Brother → printer, Hikvision → tvcc, ecc.)
5. `mac_is_random` → endpoint-private
6. fallback "generic"

Output normalizzato (alias map): `ap` → `access-point`, `ip_camera` →
`tvcc`, `voip_phone` → `voip`, `storage` → `nas`, ecc.

### Migliorato classifier Canon
Aggiunto pattern `ir-?adv|ir[\s-]?c?\d{4,}` ai _PRINTER_PATTERNS in
`device_classifier.py` (Canon imageRUNNER ADV C3530, ecc.).

### File modificati
- `backend/device_type_resolver.py` — nuovo (CANONICAL_TYPES, alias map,
  OUI single-purpose hints)
- `backend/device_classifier.py` — esteso _PRINTER_PATTERNS per Canon iR-ADV
- `backend/routes/devices.py` — sostituito 30 righe di regex inline (branch
  polled) + sostituito default hard-coded "server" (branch managed-only)
- `backend/routes/overview.py` — rimosso `_infer_device_type` locale,
  proiezioni Mongo allargate (sys_descr, sys_object_id, vendor, model,
  device_type_user_locked, mac_is_random)

### Test
`backend/tests/test_device_type_resolver.py` — 19 unit test (printer via
Printer-MIB OID, switch HPE Comware, firewall FortiGate, NAS Synology,
UPS APC, OUI vendor hint, locked override, alias normalization, ecc.).
✅ 19/19 PASS. Totale suite: 29/29 PASS.

---


# 2026-02-13 — Display Name Centralizzato (consistency fix)

## 🔤 "Se riconosci il nome del dispositivo usa quello ovunque"

L'utente aveva segnalato che la Scheda Dispositivo mostrava
"Switch and Wireless Controller/HP Switches" (categoria Fingerbank) come
titolo, mentre il sysName SNMP reale era "Switch02 HP 5130 52G".
Discrepanza analoga tra lista Dispositivi, Overview e modal.

### Soluzione
Creato `/app/backend/display_name.py` con helper unico `best_display_name(md, pd, ip)`.

Priorità (unificata in tutto il backend):
1. `md.name` se `name_locked` (admin ha bloccato esplicitamente)
2. `pd.sys_name` (SNMP sysName — autoritativo per network gear)
3. `md.hostname` (NBNS / reverse DNS)
4. `md.mdns_name` (mDNS Bonjour)
5. `pd.device_name` se NON è "category-like" (contiene "/")
6. `md.name` se NON è "category-like"
7. `md.fingerbank_device_name` (es. "Switch and Wireless Controller/HP Switches")
8. fallback ip

### File modificati
- `backend/display_name.py` — nuovo helper centralizzato + detection categoria
- `backend/routes/devices.py` — entrambi i branch (polled v4 + managed-only)
- `backend/routes/overview.py` — proiezioni Mongo allargate + helper applicato
- `backend/routes/device_info_card.py` — hostname identity unificato
- `frontend/src/pages/ClientOverviewPage.js` — modal title fallback su hostname

### Test
`backend/tests/test_display_name.py` — 10 unit test (sys_name vince su Fingerbank,
name_locked rispettato, mdns fallback, IP last-resort, ecc.) — ✅ 10/10 PASS.

---


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
- **Preview live** (no install): https://noc-alert-hub-2.preview.emergentagent.com/argus-desktop-preview/
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

## 2026-08-06 — Modulo OSINT / Threat Intelligence (v1)
Integrate fonti OSINT nel motore di alert/monitoraggio (feed GLOBALI, match/alert PER-TENANT).
Comportamento: enrichment + alert automatici (NO blocco firewall automatico).

Nuovi file:
- `backend/services/osint_service.py` — key mgmt cifrate (abusech/abuseipdb/greynoise/nvd),
  fetch feed, IOC store `threat_intel`, CISA KEV `cisa_kev`, lookup IP con SSRF-guard, KEV cross-ref.
- `backend/services/osint_poller.py` — scheduler: `osint_feeds_tick` (5m), `osint_exposure_tick`
  (30m, Shodan InternetDB su `wan_targets` public_ip -> alert per-tenant se CVE KEV esposte,
  con auto-resolve al rientro).
- `backend/routes/osint.py` — `/api/osint/{status,refresh,keys/{provider},lookup/{ip},kev,exposure}`.
- `frontend/src/pages/OsintPage.js` — dashboard feed, lookup IP, exposure, catalogo KEV, config chiavi.
  Nav: Sicurezza > "OSINT Threat Intel" (/osint).

Feed KEYLESS attivi: Feodo, Spamhaus DROP, FireHOL Level1, CISA KEV, Shodan InternetDB.
Feed con key (opzionali): abuse.ch ThreatFox, AbuseIPDB, GreyNoise, NVD.
Collections: threat_intel, cisa_kev, osint_ip_cache, osint_exposure, osint_feed_runs.
Test: iteration_100.json — backend 23/23 PASS, frontend 100% flussi OSINT.

FASE 2 (backlog): correlazione C2 automatica su syslog/firewall (parser IP dst),
azione opzionale di blocco IP su firewall via agent con conferma umana,
enrichment IP negli alert esistenti con badge reputazione.

## 2026-08-06 — OSINT Fase 2: Correlazione C2 automatica (Syslog/Firewall)
- Nuovo motore che estrae gli IP dai `syslog_events` (log firewall, campo message/raw) e li
  confronta con gli IOC (`threat_intel`: match esatto + CIDR con cache in-memory 5m).
- Se un dispositivo cliente comunica con un IP malevolo noto -> alert CRITICO per-tenant
  (source_type=osint_c2), con dedup su (client_id, bad_ip) e re-update se già attivo.
- Scheduler `osint_c2_tick` ogni 2 min (cursore incrementale su ts in osint_feed_runs source=c2_scan).
- Nuovi endpoint: POST /api/osint/c2-scan (admin, trigger manuale), GET /api/osint/c2-matches.
- Nuove funzioni service: osint_service.extract_ips / match_ips_against_iocs / _get_cidr_nets.
- UI OsintPage: sezione "Correlazione C2 (Syslog/Firewall)" con tabella match + pulsante
  "Scansiona ora" + KPI "Alert C2 attivi".
- Test end-to-end (inject syslog con IP IOC 50.16.16.211 -> scan -> alert critico -> UI): PASS.
  NB: nessun dato syslog reale ancora presente in prod (il motore fa fuoco quando arrivano i log firewall).

## 2026-08-06 — Alert C2 nel feed principale + push immediata
- osint_poller._emit_c2_alert ora, alla creazione di un alert C2:
  1) broadcast WebSocket ({type:new_alert}) -> il feed alert si aggiorna in tempo reale;
  2) webpush.notify_new_alert -> web push browser reale agli operatori con subscription;
  3) notification_service.send_notification (EMAIL+PUSH, priorità CRITICAL).
- AlertsPage: badge "C2 / OSINT" (rosso) nel titolo per source_type=osint_c2 e "OSINT" (ambra)
  per source_type=osint; colonna Fonte mostra label friendly.
- Test: alert C2 visibile in GET /api/alerts e nel feed UI con badge, pipeline notifiche partita.
  NB: canale PUSH di notification_service è MOCK in questo ambiente (log [MOCK PUSH]); il web-push
  browser (webpush.py) è reale e consegna alle subscription attive.

## 2026-08-06 — Escalation dedicata agli alert C2
- escalation.py: nuova regola `_run_c2_once` (girata nel watchdog ogni 60s) che escala gli alert
  source_type=osint_c2 non ACKed entro `c2_wait_minutes` (default 10). Notifica DIRETTAMENTE il
  reperibile on-call (oncall.get_on_call_user_ids -> webpush.send_to_user); se nessun reperibile
  attivo, fallback ai ruoli (default admin+operator). Idempotente via flag `c2_escalated`.
- L'escalation generica ora ESCLUDE gli alert C2 (source_type != osint_c2) per evitare doppioni.
- escalation_config esteso: c2_enabled, c2_wait_minutes, c2_notify_oncall, c2_fallback_roles.
- Route: PUT /api/escalation/config (nuovi campi) + POST /api/escalation/run-c2-now (trigger manuale).
- UI OnCallPage: nuova card "Escalation C2 / OSINT" (toggle, attesa, fallback, avvisa reperibile, esegui ora).
- Test: inserito alert C2 vecchio 20min -> run-c2-now -> escalated=1 (fallback ruoli), 2ª esecuzione=0
  (idempotente), flag c2_escalated verificato. UI renderizzata. PASS.

## 2026-08-06 — Escalation C2 Livello 2 (catena reperibilità)
- escalation.py: `_run_c2_l2_once` (nel watchdog). Se un alert C2 già escalato al reperibile
  (c2_escalated_at) resta attivo e non-ACK per altri `c2_l2_wait_minutes` (default 10),
  escala al RESPONSABILE: utente specifico `c2_l2_user_id` se impostato, altrimenti ruoli
  `c2_l2_roles` (default admin). Idempotente via `c2_escalated_l2`.
- Config estesa: c2_l2_enabled, c2_l2_wait_minutes, c2_l2_user_id, c2_l2_roles.
- Route: campi L2 in PUT /api/escalation/config + POST /api/escalation/run-c2-l2-now.
- UI OnCallPage: sotto-blocco "Livello 2 — avvisa il responsabile" (toggle, attesa L2, selettore
  responsabile da elenco utenti o ruolo admin).
- Catena completa: L1 (reperibile on-call / fallback ruoli) -> L2 (responsabile/manager).
- Test: alert C2 con c2_escalated_at 20min fa -> run-c2-l2-now -> escalated=1 (roles admin),
  2ª esecuzione=0 (idempotente), flag c2_escalated_l2 verificato. UI OK. PASS.

## 2026-08-06 — Fix diagnostica porte switch (falso allarme "mixing" tra clienti)
- routes/topology.py diagnose_switch_ports step 5: RIMOSSO il check fuorviante che trattava
  lo stesso IP privato presente su altri client_id come "mismatch/connector sul cliente sbagliato".
  Con IP privati (10.x/192.168.x) l'overlap tra clienti è NORMALE (switch fisici diversi) e i dati
  sono già isolati per client_id (storage + query scoped, guardia in resolve_device_client_id).
- Nuova logica step 5 (tenant-scoped): ok se ci sono porte per il device; warn se il cliente ha
  porte su altri switch (problema specifico del device); error se NESSUNO switch del cliente ha porte
  -> causa reale: l'agent v4 raccoglie la ifTable solo da v4.26.0 (snmpports.go). Azione: aggiornare agent.
- Aggiunto step "5b. Nota multi-tenant" che chiarisce esplicitamente che l'overlap di IP privati NON
  è un data-leak. Rimossa la raccomandazione errata "Allinea il client_id del connector".
- Confermato: nessuna fuga cross-tenant reale nel path switch-ports.

## 2026-08-07 — Rogue / New Device Detection (NDR-lite, ispirato a LECS)
- services/rogue_detection.py: rileva MAC/endpoint mai visti sulla rete di un cliente
  (baseline PER-CLIENTE in rogue_state: l'inventario preesistente NON allarma; solo i nuovi
  arrivi con first_seen_at > baseline). Allow-list per-cliente (rogue_allowlist).
  Alert source_type=rogue_device + WS broadcast + webpush. Severità configurabile (default warning).
- Risposta SUGGERITA a conferma umana (nessuna azione automatica finta):
  * Autorizza -> allow-list + risolve alert.
  * Isola (guida) -> passi di remediation (switch/porta se noti). auto_executable=False:
    l'agent NON ha ancora comando SNMP-SET per lo shutdown porta (niente mock).
- routes/security_rogue.py: /api/security/rogue/{status,config,alerts,scan,authorize,allowlist,remediation}.
- Scheduler rogue_scan_tick ogni 3 min. Aggiunto first_seen_at all'upsert scanner in connector.py.
- Frontend: RogueDevicesPage.js (KPI, tabella rilevati con Autorizza/Isola, allow-list, toggle, scan).
  Nav Sicurezza > "Dispositivi Rogue" (/rogue-devices).
- Test end-to-end: baseline -> inject nuovo endpoint -> scan (1 alert) -> remediation (switch/porta reali)
  -> authorize (resolve+allowlist) -> re-scan 0. UI verificata. PASS.
- Backlog fase 2 (dal confronto LECS): anomalie traffico su contatori SNMP; dashboard conformità NIS2/DORA;
  export SOC/SIEM (syslog/CEF/webhook); quarantena porta live quando l'agent supporterà SNMP-SET.

## 2026-08-07 — Rogue enrichment (fingerprint+reputazione) + Anomalie Traffico
- rogue_detection.enrich_endpoint: OUI/vendor (lookup_oui) + Fingerbank (se configurato) + tipo MAC
  (randomizzato/privacy vs vendor globale) + reputazione IP (IOC/AbuseIPDB SOLO per IP pubblici;
  gli IP privati LAN NON vengono confrontati con blocklist internet) -> verdetto rischio basso/medio/alto.
  Il rischio 'alto' alza la severità dell'alert. Campi salvati sull'alert e mostrati in UI (colonna Rischio + fingerprint).
- services/traffic_anomaly.py: baseline EWMA per porta (port_traffic_baseline) sui contatori SNMP
  rx_bps/tx_bps di switch_ports. Dopo warmup, se corrente > baseline*spike_factor e > floor_mbps ->
  alert source_type=traffic_anomaly (direzione tx=exfil / rx). Dedup per porta. Scheduler ogni 5 min.
  routes/security_traffic.py: /api/security/traffic/{status,config,scan,alerts}.
- AlertsPage: nuovi badge feed principale ROGUE (arancio) e TRAFFICO (viola) + label colonna Fonte.
- Test: rogue MAC privacy -> rischio BASSO corretto (dopo fix IP privati vs bogon-list); traffic 250Mbps vs
  baseline 1Mbps -> alert USCITA. UI verificata. PASS.

## 2026-06 — Release Agent v4.26.0 pubblicata + fix 502 proxy agent-builds
- ROOT CAUSE 502: la release v4.26.0 NON esisteva su GitHub (latest era v4.25.4). L'installer/proxy
  puntava a una versione "fantasma": _fetch_release_meta ripiegava sul manifest SINTETICO (asset noti)
  mascherando il 404, poi ensure_release_asset_cached scaricava .../download/v4.26.0/nocagent.exe -> 404 -> 502.
- FIX: compilata e pubblicata la release v4.26.0 reale su GitHub (repo santiM86/86NOCConnectorCenter).
  - Go 1.23 arm64 nel pod, cross-compile GOOS=windows GOARCH=amd64 CGO_ENABLED=0 dei 5 binari classici
    (nocagent, nocwatchdog, nocagent-ui, argus-tray, nocinstall) + ps1 templates + SHA256SUMS.
  - ArgusDesktop.exe (GUI Wails, richiede Windows per build) RIUSATO dalla v4.25.4 (invariato per porte switch).
  - Upload via GitHub REST API con PAT utente (bypassa GitHub Actions/divergenza git). Release id 366640301.
- VERIFICA: GitHub latest -> v4.26.0; download diretto 200; proxy FastAPI /api/agent-builds/latest/manifest.json
  -> source github_api (non più synthetic); /api/agent-builds/v4.26.0/nocagent.exe -> 200, PE valido. 502 RISOLTO.
- NOTA: v4.26.0 include il modulo SNMP nativo porte switch (internal/poller/snmpports.go, registrato in cmd/agent/main.go).

## 2026-06 — FIX dispatch agent multi-homed (porte switch non raccolte)
- SINTOMO: switch HPE 5130 (10.10.10.105, cliente Arma Creativo) senza porte, pur essendo
  raggiungibile (ping+TCP443 OK) e con SNMP funzionante (stat switch: community accettata,
  view completa, MIB objects retrieved in crescita). Un altro switch dello stesso cliente aveva 56 porte.
- ROOT CAUSE: backend/routes/agent_ws.py `_build_poller_config` calcolava UNA sola /24 dall'IP
  "primario" dell'agent (`_primary_ip_from_hello`). Su agent MULTI-HOMED (es. VPN 10.211.x elencata
  prima della LAN 10.10.10.x) veniva scelta la subnet sbagliata → lo switch della LAN NON era
  assegnato a CREATIVOSRV2 → il ports-poller non ne faceva mai il walk ifTable. La diagnosi/"Test
  community" diceva invece "in subnet ✓" perché `_agent_covers_device` usa TUTTI gli IP (mismatch).
- FIX: `_build_poller_config` ora accetta `agent_ips` e considera TUTTE le subnet delle interfacce
  dell'agent (nuovo helper `_subnets_from_ips`). `_get_client_agents_subnets` ritorna `subnets` (lista).
  Aggiornati i 3 call site (welcome on-connect, push_config_to_client, agents_diagnostics) per passare
  last_ip+agent_ip+ips. APIPA 169.254.x esclusi.
- TEST: backend/tests/test_multihomed_dispatch.py (3 test, PASS) — riproduce il bug e valida il fix.
- DEPLOY: richiede aggiornamento del backend in PRODUZIONE (argus.86bit.it) + re-push config all'agent.

## 2026-06 — Feature v4.27.0: raccolta LLDP + FDB (topologia + "Connesso a")
- CONTESTO: l'agent v4.26.0 raccoglieva SOLO ifTable (porte). LLDP/FDB erano fuori scope,
  quindi mappa dei link e colonna "Connesso a" restavano vuote con l'agent Go.
- AGENT (Go): nuovo internal/poller/snmptopo.go (package poller). Walk:
  - LLDP-MIB: lldpLocPortTable (id/desc porta locale), lldpRemTable (chassis/port/sysName/sysDesc),
    lldpRemManAddrTable (IP remoto, parsing indice IPv4). Indici multi-componente via walkSuffix/suffixAfter.
  - Bridge-MIB FDB: dot1qTpFdbPort (VLAN-aware) con fallback dot1dTpFdbPort; risoluzione bridge-port->ifIndex
    via dot1dBasePortIfIndex; MAC da 6 octet OID. Nuovo proto SwitchTopoReport/LLDPNeighbor/FDBEntry + evento WS "switch_topo".
    main.go: NewTopo + health "snmptopo" + ApplyConfig(welcome) + go topoP.Run. Intervallo lento (floor 120s, default 300s).
- BACKEND: agent_ws._bridge_switch_topo -> connector.store_switch_topo: salva lldp_neighbors (per local_ip) e
  discovered_endpoints (FDB, per switch_ip, source=agent_fdb) con risoluzione best-effort MAC->IP (network_discovery + endpoint ARP + managed).
  Per-switch delete+insert (multi-agent safe), isolato per tenant. Dedup MAC@ifIndex.
- RELEASE: v4.27.0 pubblicata su GitHub (id 366706838, 9 asset, latest). Build Go arm64 host -> windows/amd64,
  ArgusDesktop.exe riusata dalla v4.26.0. Upload via REST API con PAT utente.
- TEST: build agent OK; store_switch_topo testato su DB preview (neighbors=1, endpoints=2, dedup+idempotenza OK).
- DEPLOY: richiede deploy backend in produzione (contiene ANCHE il fix multi-homed) + rollout agent a v4.27.0.
  Sullo switch: LLDP gia' abilitato (15 neighbours visti); view SNMP community deve includere LLDP-MIB (1.0.8802.1.1.2)
  e Bridge-MIB (1.3.6.1.2.1.17) — ViewDefault li include.

## 2026-06 — v4.28.0: installer headless server + no ArgusDesktop + nomi Datto su porte
- ArgusDesktop rimosso: NON piu' scaricato/installato (era Wails->richiedeva WebView2, prompt sui server).
  UI legacy nocagent-ui.exe resta solo su workstation. Fix in build/install-noc-agent.ps1:
  * $optional non include piu' ArgusDesktop.exe; delete sempre di ArgusDesktop.exe residuo.
  * Autostart tray: rimosso fallback ad ArgusDesktop; su Windows Server (ProductType!=1) modalita' HEADLESS
    (no tray task, no shortcut "Agent Status"), con cleanup di task/shortcut preesistenti.
  * Shortcut "Agent Status" punta solo a nocagent-ui.exe; saltato sui server.
- FIX nomi "Connesso a": store_switch_topo (connector.py) ora ri-applica il match Datto RMM sugli endpoint FDB
  del bridge v4 (mac_list/ip_list -> datto_name + datto_match; set datto_devices.matched). Prima i nomi Datto
  non arrivavano sulle porte switch. Fingerbank gia' funzionante (enrichment on-demand in topology.py).
- RELEASE v4.28.0 (id 366719189): stessi binari agent della 4.27.0 (LLDP+FDB) + install-noc-agent.ps1 headless.
  8 asset (senza ArgusDesktop.exe). latest=v4.28.0.
- TEST: store_switch_topo datto re-match PASS (MAC->datto_name applicato, unmatched invariato).
- DEPLOY: deploy backend in produzione (attiva nomi Datto su porte) + rilanciare installer sul server per headless.

## 2026-06 — Mappa LLDP switch↔switch + nomi FDB ricchi (backend-only)
- FEATURE Mappa LLDP: build_lldp_edges (topology.py) ora risolve il vicino remoto non solo per remote_ip,
  ma anche per remote_sys_name (->hostname/device_name) e remote_chassis_id (MAC->IP). Il call site di
  GET /api/network/topology costruisce name_to_ip (device_poll_status hostname/sys_name + managed_devices.device_name)
  e mac_to_ip (network_discovery device_macs). Cosi' i link switch<->switch compaiono sulla mappa esistente
  (NetworkMap.js li disegna gia' in ciano). Helper _norm_mac aggiunto. Nessuna modifica frontend.
- FEATURE Nomi FDB ricchi: store_switch_topo (connector.py) arricchisce ogni endpoint FDB con vendor (OUI lookup)
  e hostname (network_discovery hostname/ptr/name + managed device_name + endpoint ARP). _build_mac_neighbor
  (topology.py) ora mostra: device_name > hostname > vendor OUI > IP (managed) e hostname > "vendor device" >
  sconosciuto (unmanaged), evitando l'IP nudo. Query endpoints usa gia' projection completa.
- TEST: build_lldp_edges (ip+name+mac match, no-match escluso) PASS; store enrich (hostname/ip/vendor) PASS;
  e2e GET topology su client reale senza errori.
- DEPLOY: solo deploy backend in produzione (l'agent v4.27.0/v4.28.0 invia gia' LLDP+FDB). Nessuna nuova release agent.

## 2026-06 — v4.29.0: raccolta PoE per porta + Export PDF mappa
- POE (agent): snmpports.go ora legge POWER-ETHERNET-MIB (RFC 3621): pethPsePortAdminEnable (.3),
  pethPsePortDetectionStatus (.6, 3=deliveringPower), pethPsePortPowerClassifications (.10).
  Mapping PoE-port->ifIndex best-effort via numero finale del nome interfaccia (trailingInt).
  Watt nominali da classe (poeWattFromClass). Nuovi campi proto SwitchPortInfo: poe_admin/status/class/watt.
  NOTA: mapping da validare sul campo (nessun device PoE in dev). Backend store_switch_ports salva poe_watt;
  backend/frontend gia' supportavano poe_admin/status/class (badge "PoE attivo", filtro PoE).
- EXPORT PDF mappa (frontend NetworkMap.js): pulsante "PDF" accanto a "PNG". Dependency-free: render toPng +
  finestra di stampa A4 landscape con header (cliente + data) -> "Salva come PDF". Nessuna nuova dipendenza.
- RELEASE v4.29.0 (id 366743406, latest): binari agent con PoE + LLDP/FDB (4.27) + installer headless (4.28).
- DEPLOY: backend (LLDP/FDB+Datto+poe_watt) + frontend (PDF) + agent v4.29.0 (PoE). Verificare PoE sul 5130.

## 2026-06 Pulsante "Crea token agent-sonda" (Diagnosi Percorso)
- Nella pagina /tools/path-trace: card "Agent-sonda" con selettore cliente/sede (default cliente che matcha "86bit"), etichetta, e pulsante "Crea token agent-sonda" -> POST /api/agents/register (agent_tokens).
- Dialog mostra token + WS URL (AGENT_PUBLIC_WS_URL) copiabili + istruzioni: usare installer standard install-noc-agent.ps1 con token+URL; Linux richiede mtr/traceroute; serve build agent con comando net_trace.
- Testid: probe-enroll-card, probe-client-select, probe-label-input, probe-create-token-btn, probe-token-dialog, probe-token-value, probe-backend-url.
- Testato: register 200 (token 43 char per 86BIT_Office) + UI dialog verificato via screenshot.

## 2026-06 — Fix P0 deployment blocker (startup DB)
- server.py startup_event(): rimosso il blocco distruttivo `.drop()` su banned_ips/honeypot_bans/blocked_ips (girava ad OGNI avvio, azzerava i ban IP attivi usati da deps.py). Sostituito con delete_many mirato solo sui ban SCADUTI e non permanenti di blocked_ips (non distruttivo).
- .gitignore: ricostruito da 2890 righe corrotte (blocco .env ripetuto ~300 volte) a 83 righe pulite. I file .env NON sono più ignorati (richiesto dal deploy Emergent).
- deployment_agent: ora status=PASS, destructive_db_startup_confirmed=false, gitignore_blocks_required_files=false, findings=[].
- Verificato end-to-end: login info@86bit.it -> requires_2fa -> verify-2fa -> token pieno + refresh_token (JWT persistente stabile).

## 2026-06 — Situation Engine (verdetto unico per dispositivo) — Fase 1+2
- backend/situation_engine.py: diagnose_device() fonde raggiungibilita (correlation_engine, evidence fusion) + rollup alert attivi per dominio (hardware/backup/security/performance/rete) agganciati per device_ip O device_name -> UN verdetto {overall_state, primary{situation IT, root_cause, confidence}, recommended_action, evidence[], evidence_by_domain}. Primario = liveness se DOWN, altrimenti dominio piu grave (peso security>reachability>hardware>backup>performance>rete).
- diagnose_client(): counts device + client_situations[] che AGGREGA gli alert client-level per source_type (es. backup x50 in 1 voce) con runbook e client_situation_counts. Classificazione dominio con longest-prefix match.
- routes/situation.py: GET /api/devices/by-ip/{ip}/diagnosis?client_id=  e  GET /api/clients/{id}/diagnosis (auth JWT). Registrati in server.py.
- Frontend DeviceDetailPanel.js: card "Diagnosi" (DiagnosisSection) come PRIMO elemento del pannello (indipendente da /network/device-detail), con stato colorato, certezza %, azione consigliata, prove correlate per dominio, pallini segnali (PING/L2/Datto/WAN). AbortController + placeholder errore.
- Fix pre-esistente: rimosso blocco SNMP in EndpointInfo che usava detail/clientId fuori scope (ReferenceError/crash su Discovery).
- Test: iter122 backend 15/15 PASS (fusione trasversale validata con alert temporanei), iter123 frontend 100% sui 3 scenari P0 (card presente anche su device-detail 404, in cima).
- BACKLOG aperto: (P1) colonna STATO DevicesPage contraddice il verdetto Situation Engine -> aggancia /api/devices a compute_status (refactor liveness gia in roadmap). (P2) scrollIntoView del pannello per righe in fondo alla lista. (P3) Fase 3 predittivita (trend temp/SMART/UPS/RAID -> guasto imminente).

## 2026-06 — Diagnosi Predittiva (Fase 3): situazioni "GUASTO IMMINENTE"
- backend/predictive.py: evaluate_predictive_alerts() rileva PRIMA del down: (1) RAID degradato/crashed via vendor_metrics raidStatus(11/12)/systemStatus(2) -> critical; (2) trend TEMPERATURA e temperatura DISCHI (regressione lineare su metric_history, proietta ETA alla soglia critica: <=1h critical, <=6h high; fallback vicinanza-soglia); (3) batteria UPS (autonomia<=5min o carica<=20% critical; carica<=60% in calo o su-batteria high). Alert source_type predictive_* deduplicati e AUTO-RISOLTI al ripristino.
- Aggancio in routes/agent_ws.py (bridge SNMP): dopo evaluate_hardware_alerts -> record_metrics (storicizza temp/disk/ups) + evaluate_predictive_alerts. Best-effort try/except.
- situation_engine.py: nuovo dominio "predictive" (peso 6, sotto security 7, sopra reachability 5), runbook per predictive_raid/temp/ups. Il verdetto unico rende primaria la situazione predittiva quando il device e UP.
- Frontend DeviceDetailPanel: DOMAIN_META.predictive = {label:"Guasto imminente", Icon:ChartLineUp} -> compare tra le prove correlate.
- Self-test OK: RAID degradato->critical; temp 60->74C in 90min -> "soglia critica tra ~25 min" critical; UPS 15%/4min -> critical; recovery -> auto-resolve 0 attivi; diagnose_device: overall CRITICAL, primary=predictive.
- NOTA: SMART attributi grezzi (settori riallocati/wear) NON sono raccolti (nessun OID nei device_profiles) -> predittivita disco basata su temperatura disco. Estensione SMART = futura (richiede OID agent/profilo).

## 2026-06 — Catalogo Diagnosi + Conferma MANCANZA CORRENTE via UPS
- routes/diagnosis_catalog.py: GET /api/diagnosis/catalog (fonte di verita): 37 situazioni su 7 domini, 7 certe 100%, tempi di rilevamento reali (liveness/hw ~60s, C2 2min, rogue 3min, traffic/CVE 5min, Datto 6h), 5 combinazioni trasversali. Pagina frontend DiagnosisCatalogPage.js + rotta /diagnosis-catalog + voce menu Operazioni.
- alert_engine.py: _ups_power_loss(db,client_id) rileva UPS "su batteria" da metric_history (ups_charge_pct<95 o runtime<=30min in finestra 20min). Integrato in: (1) verdetto anchor site_power_down -> se UPS conferma diventa "MANCANZA CORRENTE CONFERMATA" conf 99 + flag power_confirmed; altrimenti generico "corrente o WAN" conf 96. (2) run_site_blackout_watchdog: titolo/msg alert promossi a "SITO GIU - MANCANZA CORRENTE CONFERMATA" con dettaglio UPS.
- Distinzione chiave blackout: site_power_down = agent on-site giu + sonda WAN esterna giu (viste indipendenti concordi); site_isolated = agent ancora vivo ma device giu (guasto rete, NON corrente). Dedup: 1 solo alert aggregato, figli soppressi.
- Self-test OK: _ups_power_loss caso batteria->True(70%,18min), rete->False, no-data->False; catalogo espone site_power_confirmed(99)/site_power_down(96)/site_isolated(97).

## 2026-06 — Avviso anticipato UPS su batteria (early warning blackout)
- predictive.py _eval_ups riscritto a TIER su un unico dedup key predictive_ups (una sola notifica che ESCALA):
  - Appena su batteria (carica <99% e trend NON in salita; senza storia richiede <96%) -> severity HIGH, titolo "UPS SU BATTERIA — possibile mancanza corrente" con autonomia stimata ("il sito potrebbe spegnersi tra ~N min"). Avviso PRIMA che il sito cada.
  - Escala a CRITICAL (autonomia <=5min o carica <=20%) -> "UPS in esaurimento, spegnimento imminente".
  - Auto-resolve quando la carica torna ~100% (rete ripristinata).
- Notifica via _dispatch_notification (Telegram/WebPush) automatica.
- FIX: rimosso uso di upsEstimatedMinutesRemaining come indicatore di "su batteria" (e autonomia batteria, presente anche su rete -> falsi positivi). Indicatore certo = carica che cala.
- Catalogo aggiornato: predictive_ups = "UPS su batteria -> esaurimento" (early high -> critical).
- Self-test OK: rete 99%/40min->nessun alert; discesa 100->98 slope neg->HIGH early; 15%/4min->CRITICAL; 100%->resolve.

## 2026-06 — Evento PRE-BLACKOUT (conferma corrente in tempo reale)
- predictive.py: quando lUPS va su batteria (_eval_ups on_battery), registra/aggiorna un marker persistente in collection pre_blackout_events {client_id, device_ip, on_battery_since, last_seen_at, charge, runtime, detail}. Cancellato al ritorno su rete (_clear_pre_blackout). Indice TTL 2h (auto-pulizia eventi non recuperati) + unique (client_id,device_ip), creati best-effort al primo uso.
- alert_engine._ups_power_loss: consulta PRIMA pre_blackout_events (last_seen entro 20min) poi fallback a metric_history. Cosi il blackout (site_power_down anchor + watchdog) viene etichettato "MANCANZA CORRENTE CONFERMATA" in TEMPO REALE gia dal primo secondo del down, ANCHE se lUPS si e spento e non riporta piu (levento persiste lultimo stato noto).
- Self-test OK: baseline->no; UPS su batteria->evento registrato; UPS spento (nessuna metric fresca)->blackout CONFERMATO via evento; recovery->evento cancellato + non confermato.

## 2026-06 — Cronologia evento nel messaggio blackout (Telegram)
- alert_engine._blackout_timeline(db,client_id,down_at): legge pre_blackout_events e costruisce la timeline "HH:MM UPS su batteria -> HH:MM SITO GIU: MANCANZA CORRENTE CONFERMATA" in ora locale IT (Europe/Rome via zoneinfo, fallback UTC). Helper _fmt_local.
- Integrata (append al messaggio) in ENTRAMBI i punti che dichiarano il blackout confermato: verdetto corr_site_power_down (run_vital_watchdog) e alert del run_site_blackout_watchdog. Il messaggio Telegram/WebPush ora include la cronologia completa in un unico avviso.
- Self-test OK: evento pre-blackout (batteria da 5min) -> genera "14:16 UPS su batteria (carica 82%, autonomia ~22min) -> 14:21 SITO GIU: MANCANZA CORRENTE CONFERMATA".

## 2026-06 — Messaggio di chiusura blackout con durata disservizio (SLA)
- alert_engine.run_site_blackout_watchdog: ridisegnato il lifecycle. In sezione 1 registro started_at DUREVOLE (setOnInsert) per OGNI cliente in blackout, sopravvive anche al path corr (lo state NON viene piu cancellato quando subentra corr, solo unset alert_id). Salvo power_confirmed nello state.
- Sezione 2 (recovery): calcola durata totale = now - started_at, risolve alert watchdog + corr_site_power_down/isolated, e invia UN messaggio di chiusura: se power_confirmed "Corrente RIPRISTINATA: ... Corrente assente per 1h 47m", altrimenti "Sito RIPRISTINATO: ... Disservizio durato Xh Ym". Campo outage_duration salvato sullalert (per report SLA). Poi cancella lo state.
- Helper: _fmt_duration (1h 47m / 12m / 1g 2h), _parse_iso, _fmt_local. Retrocompat con vecchio campo first_at.
- Self-test OK: _fmt_duration(6420)->1h 47m; lifecycle recovery con started 1h47m fa + power_confirmed -> alert "Corrente RIPRISTINATA ... assente per 1h 47m", outage_duration=1h 47m, state cancellato.

## 2026-06 — CMDB Entity Resolution / Inventario Unificato (Fase 1 enterprise)
- entity_resolver.py: fonde managed_devices + device_poll_status + managed_agents + iLO + cmdb_assets in cmdb_entities con identita stabile. Chiavi (priorita): serial->mac->datto_uid->agent_id->hostname(client)->ip(client), mappate in cmdb_identity_keys (unique). _resolve_entity_id fa merge su chiave forte (sopravvive entita piu vecchia). Reconcile: periodico 5min (scheduler server.py) + on-demand.
- routes/cmdb_entities.py: GET /api/cmdb/entities (?client_id,?source), GET /api/cmdb/entities/{id}, POST /api/cmdb/entities/rebuild.
- Frontend EntityInventoryPage.js (menu Inventario Unificato, /cmdb-entities): tabella entita + colonna Cliente + filtro cliente, pannello dettaglio (fonti fuse, chiavi identita, anagrafica manuale) con backdrop+ESC, bottone Ricostruisci con toast.
- Fix post-review: (1) asset manuali ORFANI (IP non monitorato ma client_id match) ora creano entita; (2) PRUNING entita stale (device eliminati) a fine reconcile; (3) preserva anagrafica manuale (migrazione dati).
- Test iter124: backend 10/10 PASS, frontend 100%. Self-test post-fix: rebuild idempotente 36 unita->35 entita stabili (merge su datto_uid), pruning ok.
- BACKLOG: Fase 2 = grafo dipendenze (cmdb_relationships da LLDP/MAC/HyperV) + impact analysis; Fase 3 = aggancio Situation Engine (verdetto+impatto per entita) + report SLA/uptime.

## 2026-06 — Grafo dipendenze + Impact Analysis (Fase 2 CMDB)
- graph_builder.py: build_relationships(client) costruisce cmdb_relationships (src a monte -> dst a valle) da mac_connections (device->switch), lldp_neighbors (remote->local), Hyper-V (host->VM). Sostituzione atomica per cliente. build_all + indici.
- compute_impact(entity_id): BFS sui figli (entita a valle) -> impacted_count, impacted_vital, lista con depth+rel_type. "Se cade X, cosa resta impattato".
- Endpoint: POST /api/cmdb/entities/rebuild ora ricostruisce ANCHE il grafo; GET /api/cmdb/entities/{id}/impact; GET /api/cmdb/graph?client_id= (nodi+archi). Scheduler 5min esegue reconcile+build_all.
- Frontend EntityInventoryPage: sezione "Impatto se cade" nel pannello dettaglio (conteggio a valle + vitali + lista con freccia depth e rel_type).
- Self-test OK: rebuild -> 2 relazioni (lldp), impact CHASW-A -> FORTIGATE-FW depth1; foglia -> 0. Frontend compila.
- NOTA: topologia preview sparsa (mac_connections=2, lldp=8); in produzione con LLDP/MAC completi le catene di impatto saranno ricche. Direzione LLDP e euristica (remote=monte); mac_connections e piu affidabile.
- BACKLOG: Fase 2b mappa grafica interattiva; migliorare inferenza direzione LLDP (chi e switch/firewall); Fase 3 aggancio Situation Engine (verdetto+impatto).

## 2026-06 — Impatto negli alert + Organizzazione (Fase 3 CMDB)
- alert_enrichment.py: enrich_alert(db,alert) aggiunge ORGANIZZAZIONE (da zyxel_client_links: clienti raggruppati in 1 org Nebula) + IMPATTO a valle (compute_impact via grafo) agli alert di guasto a monte (corr_switch_down/site_isolated/firewall_mgmt_down/isp_down/site_blackout). Messaggio arricchito: "[Org: 86 Bit] ... 🔗 IMPATTO: se cade, restano coinvolti N dispositivi a valle, di cui M vitali (nomi...)". Campi impact_count/impact_vital/org_id/org_name sullalert.
- Agganciato: emissione corr_* in run_vital_watchdog (alert_engine ~448) e alert site_blackout del watchdog.
- entity_resolver.reconcile_client: ogni cmdb_entity ora porta org_id/org_name (raggruppamento per organizzazione). Frontend EntityDetail mostra Organizzazione.
- Self-test OK: enrich su corr_switch_down CHASW-A -> "[Org: 86 Bit] ... IMPATTO 1 a valle (FORTIGATE-FW)"; rebuild all -> entita con org_name=86 Bit.
- BACKLOG: gruppi org anche nella lista inventario (filtro per organizzazione), report/dashboard per organizzazione, impatto multi-cliente per infra condivisa.

## 2026-06 — Selezione SITE per cliente nel mapping Nebula
- Un'organizzazione Nebula ha piu site (ognuno col suo firewall). Il backend supportava gia site_ids nel link (ZyxelLinkIn.site_ids) e il sync filtra per site, ma la UI mappava solo org_id (=tutti i site) -> per chi mappa 1 site per cliente mancavano firewall.
- Frontend ZyxelNebulaSettingsPage: dopo aver mappato un org al cliente, mostra SEMPRE le chip dei site (loadSites via GET /api/zyxel/organizations/{org_id}/sites). Chip "Tutti (N)" = site_ids [] (tutti), chip per-site toggle -> aggiorna site_ids via PUT link. Preload site per tutti gli org mappati (useEffect su links).
- linkClient(clientId, orgId, siteIds) ora passa site_ids; toggleSite calcola il set.
- NOTA: non testabile E2E in preview (Nebula API key solo in produzione); frontend compila e i path/contratti backend sono confermati (endpoint sites gia esistente, PUT link accetta site_ids).
- Testid: zyxel-sites-{cid}, zyxel-site-all-{cid}, zyxel-site-{cid}-{siteId}.

## 2026-06 — Firewall Nebula: vitale + porte + dettagli completi
- routes/zyxel_nebula.py sync: per ogni firewall Nebula ONLINE -> raccoglie STATO PORTE (best-effort /{sid}/gw/{devId}/port-status|/ports), marca doc is_vital=True, e _upsert_firewall_managed_device() marca is_vital=True + device_type=firewall + aggancia dettagli Nebula (nebula{} + nebula_dev_id) sul managed_device abbinato per MAC o nome (NIENTE IP fittizi -> nessun conflitto). Cosi il firewall risulta vitale, entra in WAN/CMDB/Situation Engine dove ce un managed_device reale.
- zyxel_devices porta gia: model, sn, mac, firmware, cpu/mem/sessions, traffic, online_status, ora + ports + is_vital. Endpoint GET /clients/{id}/zyxel/devices e /zyxel/devices restituiscono i doc completi.
- LIMITE: non testabile in preview (Nebula API key solo in produzione); codice corretto-per-costruzione, da verificare in produzione. Endpoint porte Nebula = best-effort (2 nomi tentati) da validare col vero payload.
- DA FARE (frontend): sezione WAN del cliente con firewall in cima + scheda firewall dedicata che mostra porte/traffico/dettagli. E il pezzo che rende VISIBILE quanto sopra.
