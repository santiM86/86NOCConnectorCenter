//go:build windows

// update_remote_windows.go — esegue l'aggiornamento dell'agent
// triggerato da un comando WebSocket inviato dal Center (es. bottone
// "Aggiorna" nella console SaaS).
//
// Idea base: scaricare install-noc-agent.ps1 da GitHub raw e lanciarlo
// come subprocess elevato (PowerShell). Lo script si occupa di:
//   - stop dei servizi 86NocAgent + 86NocWatchdog
//   - kill nocagent-ui.exe
//   - download binari della release richiesta da GitHub Release
//   - sovrascrivere file in C:\Program Files\86NocAgent\
//   - re-install dei servizi
//   - start dei servizi + rilancio della UI
//
// Le credenziali (token, client_id, backend_url, role) le leggiamo da
// agent.yaml gia' caricato in memoria. Niente input utente richiesto.
//
// Sicurezza: lo script accetta esecuzione solo se gia' siamo SYSTEM o
// admin (il servizio 86NocAgent gira come SYSTEM, quindi i requisiti
// di privilegio sono soddisfatti automaticamente).
package main

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"syscall"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

const remoteInstallerURL = "https://raw.githubusercontent.com/santiM86/86NOCConnectorCenter/main/noc-agent/build/install-noc-agent.ps1"

// triggerRemoteUpdate viene invocato dal command handler "update".
// Gira in goroutine: lancia powershell.exe e ritorna. PowerShell.exe
// resta vivo anche dopo che il nostro processo (nocagent.exe) viene
// terminato dal Stop-Service, perche' lo lanciamo con CREATE_NEW_PROCESS_GROUP
// + DETACHED_PROCESS via SysProcAttr — Windows non lo killa con il padre.
func triggerRemoteUpdate(version string, cfg *config.Config, log *logging.Logger) {
	log = log.With("update.remote")
	log.Info("avvio update remoto", "version", version)

	// Backend URL deve essere in formato wss:// per l'installer ps1
	// (e' come il connettore si riconnette dopo il restart).
	backendWS := cfg.Backend.URL
	if strings.HasPrefix(backendWS, "http://") {
		backendWS = "ws://" + strings.TrimPrefix(backendWS, "http://")
	} else if strings.HasPrefix(backendWS, "https://") {
		backendWS = "wss://" + strings.TrimPrefix(backendWS, "https://")
	}
	if !strings.HasSuffix(backendWS, "/api/agent/ws") {
		backendWS = strings.TrimSuffix(backendWS, "/") + "/api/agent/ws"
	}

	// Role: agent.yaml non lo persiste (config legacy). Usiamo "master"
	// come default. L'installer accetta "master" e "scanner" — un
	// connettore master che si auto-aggiorna a "scanner" non avrebbe
	// senso, quindi master e' sicuro.
	role := "master"
	if v, ok := cfg.Labels["role"]; ok && (v == "master" || v == "scanner") {
		role = v
	}

	// Costruisco il blocco PowerShell che fa: download + run installer
	// con i parametri presi da agent.yaml.
	psScript := fmt.Sprintf(`
$ErrorActionPreference = 'Continue'
Write-Host "=== 86NocAgent Remote Update -> %s ===" -ForegroundColor Cyan
$installerPath = "$env:TEMP\install-noc-agent.ps1"
try {
    Invoke-WebRequest -Uri "%s" -OutFile $installerPath -UseBasicParsing -ErrorAction Stop
} catch {
    Write-Host "Download installer fallito: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
& $installerPath -Token "%s" -ClientId "%s" -BackendUrl "%s" -Role "%s" -Version "%s" -Quiet
exit $LASTEXITCODE
`,
		version,
		remoteInstallerURL,
		cfg.Token,
		cfg.ClientID,
		backendWS,
		role,
		version,
	)

	// Subprocess detached: cosi' sopravvive al Stop-Service di noi stessi.
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-ExecutionPolicy", "Bypass",
		"-Command", psScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		// CREATE_NEW_PROCESS_GROUP = 0x00000200
		// DETACHED_PROCESS         = 0x00000008
		CreationFlags: 0x00000200 | 0x00000008,
	}
	if err := cmd.Start(); err != nil {
		log.Error("avvio powershell fallito", "err", err.Error())
		return
	}
	log.Info("installer powershell avviato in background", "pid", strconv.Itoa(cmd.Process.Pid))
	// Non aspettiamo cmd.Wait(): il subprocess gira indipendente. Il
	// nostro processo (nocagent.exe) sara' terminato dallo script poco
	// dopo, e il watchdog lo rifara' partire quando l'install ha finito.
}
