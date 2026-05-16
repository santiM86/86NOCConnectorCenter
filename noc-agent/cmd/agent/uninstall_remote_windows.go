//go:build windows

// uninstall_remote_windows.go — esegue la disinstallazione completa
// dell'agent triggerata da un comando WebSocket dal NOC Center.
//
// Strategia:
//   1. Il Center invia comando "uninstall" via WebSocket
//   2. L'agent risponde ACK immediato (status="uninstall_started")
//   3. In goroutine separata avvia uno script PowerShell detached che:
//      - Stop & remove dei servizi 86NocAgent + 86NocWatchdog
//      - Kill nocagent-ui.exe (se presente)
//      - Remove dei file in C:\Program Files\86NocAgent\
//      - Cancellazione registry entry Programmi e Funzionalita'
//      - Cancellazione shortcut start menu / desktop
//      - Cancellazione cartella ProgramData\86NocAgent (config, log, agent.yaml)
//      - Cancellazione scheduled tasks watchdog
//
// Lo script di base e' "uninstall.ps1" che e' gia' installato dentro
// InstallDir dall'installer di setup (vedi installer_gui.ps1.template
// linee ~1874-1923). Se per qualche motivo non e' presente, fallback
// inline al body completo (lasciamo per future hardening — per ora se
// uninstall.ps1 manca, fallisce e l'admin lo deve rimuovere a mano).
package main

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

// triggerRemoteUninstall lancia powershell.exe in background per
// disinstallare l'agent corrente. Ritorna subito (il subprocess gira
// detached: PowerShell sopravvive al Stop-Service del nostro processo).
//
// purgeData=true => cancella anche ProgramData (logs, config, agent.yaml)
//                   in modo che un eventuale re-install riparta da zero
//                   (nuovo UUID, nuova registrazione).
func triggerRemoteUninstall(purgeData bool, _ *config.Config, log *logging.Logger) {
	log = log.With("uninstall.remote")
	log.Info("avvio uninstall remoto", "purge_data", fmt.Sprintf("%t", purgeData))

	installDir := `C:\Program Files\86NocAgent`
	uninstScript := filepath.Join(installDir, "uninstall.ps1")
	// uninstall.ps1 attualmente cancella sempre ProgramData (data dir):
	// quindi `purgeData=false` non e' supportato a livello di script. Se
	// in futuro vorremo conservare i log/agent.yaml, il template
	// installer_gui.ps1.template va modificato per accettare -KeepData.
	_ = purgeData

	// Wrapper esterno: lancia uninstall.ps1 + (se purgeData) rimuove
	// brutalmente la directory di config residua. Il -ExecutionPolicy
	// Bypass e' necessario perche' il file PS1 non e' firmato.
	psScript := fmt.Sprintf(`
$ErrorActionPreference = 'Continue'
Write-Host "=== 86NocAgent Remote Uninstall ===" -ForegroundColor Cyan
if (Test-Path '%s') {
    & '%s'
    Write-Host "uninstall.ps1 terminato (exit=$LASTEXITCODE)"
} else {
    Write-Host "uninstall.ps1 NON trovato in %s -- fallback manuale" -ForegroundColor Yellow
    try { Stop-Service '86NocAgent'    -Force -ErrorAction SilentlyContinue } catch {}
    try { Stop-Service '86NocWatchdog' -Force -ErrorAction SilentlyContinue } catch {}
    try { sc.exe delete '86NocAgent'    | Out-Null } catch {}
    try { sc.exe delete '86NocWatchdog' | Out-Null } catch {}
    try { Get-Process 'nocagent-ui' -ErrorAction SilentlyContinue | Stop-Process -Force } catch {}
    try { Remove-Item -Path '%s' -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path "$env:ProgramData\86NocAgent" -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -Path "$env:ProgramData\86NocConnector" -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}
exit 0
`,
		uninstScript,
		uninstScript,
		installDir,
		installDir,
	)

	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-ExecutionPolicy", "Bypass",
		"-Command", psScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		// Detached: sopravvive al Stop-Service di noi stessi
		CreationFlags: 0x00000200 | 0x00000008,
	}
	if err := cmd.Start(); err != nil {
		log.Error("avvio uninstall powershell fallito", "err", err.Error())
		return
	}
	log.Info("uninstaller powershell avviato in background", "pid", strconv.Itoa(cmd.Process.Pid))
}
