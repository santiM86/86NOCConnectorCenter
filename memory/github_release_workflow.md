# 🚀 WORKFLOW RELEASE AGENT su GitHub — procedura PERMANENTE (non perdere tra sessioni)

> Direttiva utente (2026-08-11): "NON voglio più che perdi tra le sessioni questa
> modalità di aggiornamento verso GitHub, ci fa perdere un sacco di tempo."
> Questo file è la fonte di verità per pubblicare una nuova release dell'agent.

## Contesto
- Repo GitHub: **`santiM86/86NOCConnectorCenter`** (PRIVATO).
- L'agent Windows (Go) vive in `noc-agent/`. La sua versione è nel file
  **`noc-agent/VERSION`** (+ fallback `noc-agent/cmd/agent/main.go` `var Version`).
- Il Center di produzione (`https://argus.86bit.it`) NON serve i binari da solo:
  fa da **proxy verso le GitHub Release** (`/api/agent-builds/<ver>/<file>`), e
  risolve la "latest" via GitHub `releases/latest` (salvo override env
  `AGENT_LATEST_VERSION` o override DB `system_settings/agent_latest_version_override`).
- L'update remoto dell'agent scarica lo **script** `install-noc-agent.ps1` da
  `raw.githubusercontent.com/.../main/noc-agent/build/install-noc-agent.ps1` (branch
  `main`) e i **binari** dalla release della versione target.

## Automazione già presente
- `.github/workflows/auto-release-agent.yml`: parte al **push su `main` quando cambia
  `noc-agent/VERSION`** → calcola tag `v<VERSION>` → se non esiste, dispatcha
  `release-agent.yml`.
- `.github/workflows/release-agent.yml` (trigger: tag `v*` OPPURE workflow_dispatch
  con input `tag`): build 5 binari Windows (`nocagent/nocwatchdog/nocagent-ui/
  argus-tray/nocinstall .exe`) + Wails `ArgusDesktop.exe` + allega
  `install-noc-agent.ps1` e `installer_gui.ps1.template` → crea la GitHub Release.

## PROCEDURA per pubblicare una nuova release (es. v4.30.1)
1. Fare le modifiche al codice agent/script in `/app`.
2. **Bump versione**: aggiornare `noc-agent/VERSION` (es. `4.30.1`) e
   `noc-agent/cmd/agent/main.go` `var Version = "4.30.1"`.
3. L'utente fa **Save to GitHub** (push su `main`) — l'agent NON può pushare il codice.
4. Se l'auto-release non produce la release (spesso perché la pipeline è bloccata da
   un errore di build), **dispatchare a mano** `release-agent.yml` via API GitHub
   (serve un token con scope `repo`, fornito dall'utente al bisogno — MAI hardcodarlo):
   ```
   curl -s -X POST -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/santiM86/86NOCConnectorCenter/actions/workflows/release-agent.yml/dispatches" \
     -d '{"ref":"main","inputs":{"tag":"v4.30.1"}}'
   ```
   (204 = accettato)
5. **Monitorare** la run e i job:
   ```
   curl -s -H "Authorization: Bearer $GH_TOKEN" ".../actions/workflows/release-agent.yml/runs?per_page=1"
   curl -s -H "Authorization: Bearer $GH_TOKEN" ".../actions/runs/<RUN_ID>/jobs"
   ```
   Se `Build Windows binaries` fallisce, scaricare il log e correggere:
   ```
   curl -s -L -H "Authorization: Bearer $GH_TOKEN" ".../actions/jobs/<JOB_ID>/logs" | grep -iE "\.go:[0-9]+:|error"
   ```
6. **Verificare** la release finale:
   ```
   curl -s -H "Authorization: Bearer $GH_TOKEN" ".../releases/tags/v4.30.1"   # deve avere 9 asset
   ```
   `nocagent.exe` deve dare HTTP 200 (Accept: application/octet-stream sull'asset url).

## Fix diretto su `main` via API (quando la copia `main` differisce da `/app`)
`/app` e la `main` su GitHub possono DIVERGERE su singoli file. Se la build fallisce
per un file che in `/app` è già corretto, correggere il file SU MAIN via Contents API
(GET per sha+content → PUT con `branch:"main"`). ⚠️ Un commit su `main` fa scattare
anche `Deploy to Ubuntu Server` (redeploy del Center): effetto collaterale normale.

## Blocker noti
- `cmd/installer/main.go`: errori Go tipo "declared and not used" / "no new variables
  on left side of :=" bloccano l'intera release (Go compila tutto insieme). Risolti
  2026-08-11: `n, err := io.Copy(...)` → `_, err = io.Copy(...)`.
- Il job Wails (`ArgusDesktop.exe`) è lento (diversi minuti) ma non deve bloccare la
  release; storicamente v4.30.0 aveva 8 asset (senza ArgusDesktop) e funzionava lo stesso.

## SICUREZZA token
- Il token GitHub lo fornisce l'utente SOLO al bisogno. **MAI** salvarlo in file/codice/
  commit. Usarlo solo in variabile d'ambiente transitoria. Dopo l'uso, ricordare
  all'utente di **revocarlo e rigenerarlo** (https://github.com/settings/tokens) se è
  stato incollato in chat.
- `AGENT_GITHUB_TOKEN` sul Center (env del backend di produzione) serve solo a rendere
  il proxy verso GitHub più affidabile / evitare rate-limit (504). NON risolve una
  release mancante.

## Diagnosi rapida 502/504 sul download binario dal Center
Quasi sempre = **la release target NON esiste su GitHub** (o non ha i binari). Verificare
`releases/tags/<ver>` PRIMA di cercare altrove. Se la release esiste con i binari (200) e
il Center dà ancora 504 → problema connettività/rate-limit Center↔GitHub (mettere
`AGENT_GITHUB_TOKEN`).
