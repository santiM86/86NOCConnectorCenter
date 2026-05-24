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
	//
	// Source=center: l'installer scarica i binari attraverso il Center
	// (reverse-proxy verso GitHub) usando lo stesso $Token agent. Evita
	// il rate-limit GitHub unauth sui PC dei clienti — il PAT GitHub
	// resta solo sul Center (env AGENT_GITHUB_TOKEN).
	//
	// LOGGING PERSISTENTE: redirigiamo TUTTO l'output del wrapper su
	// %TEMP%\86noc-upgrade-logs\wrapper_<ts>.log (Start-Transcript)
	// PRIMA di provare il download dello script. Cosi' anche se la
	// raw GitHub URL fallisce (rete bloccata, DNS, certificati) non
	// perdiamo la diagnosi. Lo script vero scrive su un suo log a
	// parte ma con la stessa cartella (vedi install-noc-agent.ps1
	// step 0.PRE). Tutta la storia di un upgrade vive in un posto
	// solo: %TEMP%\86noc-upgrade-logs\ .
	psScript := fmt.Sprintf(`
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$wrapperLogDir = Join-Path $env:TEMP '86noc-upgrade-logs'
try { New-Item -ItemType Directory -Force -Path $wrapperLogDir -ErrorAction SilentlyContinue | Out-Null } catch {}
$ts = (Get-Date).ToString('yyyyMMdd-HHmmss')
$wrapperLog = Join-Path $wrapperLogDir "wrapper_${ts}_pid$PID.log"
try { Start-Transcript -Path $wrapperLog -Force -ErrorAction Stop | Out-Null } catch {}
Write-Host "=== 86NocAgent Remote Update wrapper (target=%s, Source=center) ===" -ForegroundColor Cyan
Write-Host "Wrapper log: $wrapperLog"
Write-Host "Started:     $((Get-Date).ToString('o'))"
$installerPath = "$env:TEMP\install-noc-agent.ps1"
try {
    Invoke-WebRequest -Uri "%s" -OutFile $installerPath -UseBasicParsing -ErrorAction Stop -TimeoutSec 60
    Write-Host "Installer scaricato in $installerPath ($([math]::Round((Get-Item $installerPath).Length/1KB,1)) KB)"
} catch {
    Write-Host "Download installer fallito: $($_.Exception.Message)" -ForegroundColor Red
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
    exit 1
}
try {
    & $installerPath -Token "%s" -ClientId "%s" -BackendUrl "%s" -Role "%s" -Version "%s" -Source center -Quiet
    $rc = $LASTEXITCODE
    Write-Host "Installer exit code: $rc"
} catch {
    Write-Host "Esecuzione installer fallita: $($_.Exception.Message)" -ForegroundColor Red
    $rc = 98
}
try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
exit $rc
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
		// CREATE_NEW_PROCESS_GROUP  = 0x00000200
		// DETACHED_PROCESS          = 0x00000008
		// CREATE_BREAKAWAY_FROM_JOB = 0x01000000
		//
		// CREATE_BREAKAWAY_FROM_JOB e' CRITICO: i servizi Windows
		// girano dentro un Job Object e i child di default vengono
		// killati col job. Senza questo flag, quando Stop-Service
		// 86NocAgent viene chiamato dallo script PowerShell, lo
		// SCM termina sia nocagent.exe SIA il subprocess powershell
		// -> l'upgrade muore al 95% PRIMA di aver scritto i binari.
		// Diagnosticato in v4.14.x: cartella TEMP log SYSTEM vuota
		// = script morto prima del transcript.
		CreationFlags: 0x00000200 | 0x00000008 | 0x01000000,
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
