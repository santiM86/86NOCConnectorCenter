# Setup pulito Connector ARGUS v4.25.1 (layout uniforme)

Risultato finale: macchina con **v4.25.1**, **un'unica tray** (`argus-tray.exe`,
senza voce "Stato Agent"), nessuna GUI legacy (ArgusDesktop/nocagent-ui rimosse).

---

## FASE 1 — Pubblicare la release v4.25.1 (una volta sola)

1. **Save to GitHub** (pulsante in chat) → porta su `main` le modifiche
   (installer uniforme + tray senza "Stato Agent" + versione 4.25.1).

2. Crea e pusha il tag → la GitHub Action `release-agent.yml` compila e pubblica
   automaticamente tutti i binari Windows + l'installer:
   ```bash
   git tag v4.25.1
   git push origin v4.25.1
   ```
   In alternativa: tab **Actions → Release Argus Agent → Run workflow** e nel
   campo `tag` scrivi `v4.25.1`.

3. Attendi che l'Action finisca (verde). A quel punto esiste la release
   `v4.25.1` con `argus-tray.exe`, `nocagent.exe`, `nocwatchdog.exe`,
   `install-noc-agent.ps1`, ecc.

---

## FASE 2 — Installazione pulita su una macchina (PowerShell come Admin)

Sostituisci `TOKEN`, `CLIENT_ID` (li trovi nel NOC Center → cliente → Aggiungi/
Installa connector) e, se serve, `BackendUrl`.

```powershell
# 1) scarica l'installer della release v4.25.1
iwr "https://github.com/santiM86/86NOCConnectorCenter/releases/download/v4.25.1/install-noc-agent.ps1" -OutFile "$env:TEMP\install.ps1"

# 2) esegui (versione fissata a v4.25.1)
& "$env:TEMP\install.ps1" `
    -Token       "noc_xxxxxxxxxxxx" `
    -ClientId    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -BackendUrl  "wss://argus.86bit.it/api/agent/ws" `
    -Role        "master" `
    -Version     "v4.25.1"
```

> Per lo scanner secondario usa `-Role "scanner"`.
> Per installare sempre l'ultima pubblicata usa `-Version "latest"` (dopo la
> FASE 1, `latest` = v4.25.1).

L'installer ora:
- installa SOLO `nocagent.exe` + `nocwatchdog.exe` + `argus-tray.exe`;
- **rimuove** `ArgusDesktop.exe` e `nocagent-ui.exe` se presenti (layout uniforme);
- registra l'autostart della tray (At Logon) sempre su `argus-tray.exe`;
- avvia i servizi e verifica heartbeat.

---

## FASE 3 — Allineare i connector GIA' installati

Dal NOC Center → **Server con Agent**:
- pulsante **"Forza re-deploy su N connector"** (banner azzurro in alto): allinea
  TUTTA la flotta live alla v4.25.1 in un click; oppure
- per singolo connector, il pulsante **"Forza re-deploy"** sulla riga.

---

## Verifica
- Tray: icona Argus → menu = Apri NOC Center · Aggiorna Connector · Riavvia
  servizio · Informazioni · Esci (NIENTE "Stato Agent").
- "Informazioni" → Versione **v4.25.1**.
- NOC Center → il connector mostra **4.25.1** e ✓ aggiornato.
- In `C:\Program Files\86NocAgent\` NON ci sono più `ArgusDesktop.exe` né
  `nocagent-ui.exe`.
