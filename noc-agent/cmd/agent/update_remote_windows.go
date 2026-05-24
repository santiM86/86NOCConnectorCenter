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
	"os"
	"os/exec"
	"strconv"
	"strings"

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

	// ===================================================================
	// EXEC VIA TASK SCHEDULER (NOT subprocess)
	// ===================================================================
	// Diagnosticato in v4.14.x: subprocess detached (anche con
	// CREATE_BREAKAWAY_FROM_JOB) muore PRIMA di scrivere il transcript.
	// La cartella SYSTEM TEMP \86noc-upgrade-logs resta vuota.
	// Cause possibili: Windows ASR blocca PowerShell lanciato da
	// servizio non firmato; oppure le pipe ereditate da nocagent.exe
	// chiudono al Stop-Service e powershell.exe esce con broken-pipe.
	//
	// SOLUZIONE: scriviamo lo script su disco e lo lanciamo tramite
	// schtasks.exe come task one-shot. Task Scheduler crea il processo
	// nella SUA sessione di servizio, completamente disaccoppiato dal
	// 86NocAgent service. Stop-Service 86NocAgent NON intacca il task.
	scriptPath := `C:\ProgramData\86NocAgent\update_oneshot.ps1`
	if err := os.MkdirAll(`C:\ProgramData\86NocAgent`, 0o755); err != nil {
		log.Error("mkdir ProgramData fallita", "err", err.Error())
		return
	}
	if err := os.WriteFile(scriptPath, []byte(psScript), 0o644); err != nil {
		log.Error("scrittura script oneshot fallita", "err", err.Error())
		return
	}
	taskName := "86NocAgent_OneshotUpdate"
	// Cleanup task precedente (idempotente, ignora errori).
	_ = exec.Command("schtasks.exe", "/Delete", "/TN", taskName, "/F").Run()
	// Crea task SYSTEM HIGHEST. /SC ONCE + /ST 23:59 = trigger placeholder
	// (lo lanciamo subito a mano con /Run, il trigger non si attiva mai).
	taskCmd := fmt.Sprintf(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%s"`, scriptPath)
	createCmd := exec.Command("schtasks.exe", "/Create",
		"/TN", taskName,
		"/TR", taskCmd,
		"/SC", "ONCE",
		"/ST", "23:59",
		"/RU", "NT AUTHORITY\\SYSTEM",
		"/RL", "HIGHEST",
		"/F",
	)
	if out, err := createCmd.CombinedOutput(); err != nil {
		log.Error("schtasks /Create fallita", "err", err.Error(), "output", string(out))
		return
	}
	// Esegui subito il task: Task Scheduler crea il processo in sessione
	// 0 indipendente. Sopravvive al Stop-Service 86NocAgent perche' NON
	// e' child del servizio.
	runCmd := exec.Command("schtasks.exe", "/Run", "/TN", taskName)
	if out, err := runCmd.CombinedOutput(); err != nil {
		log.Error("schtasks /Run fallita", "err", err.Error(), "output", string(out))
		return
	}
	log.Info("installer schedulato via Task Scheduler",
		"task", taskName,
		"script", scriptPath,
		"target_version", version,
	)
	_ = strconv.Itoa // mantieni import strconv compat (potrebbe non servire piu')
}

