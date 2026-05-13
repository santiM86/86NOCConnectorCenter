//go:build windows

package main

// update_actions_windows.go
//
// UI side-effects dell'auto-updater:
//  - refreshUpdateMenuItem aggiorna l'etichetta + abilita/disabilita il menu
//    "Aggiorna ora" in base a quello che il watcher ha trovato su GitHub.
//  - runUpdateNow scarica install-noc-agent.ps1 e lo lancia elevato (UAC).
//    L'installer si occupa di fermare i servizi, sovrascrivere i .exe e
//    rifare lo start.
//  - showVersionDialog popola una piccola dialog con tutte le info di
//    runtime (versione, build, agent_id, log path, backend) — utile per il
//    supporto remoto quando un cliente chiama dicendo "non funziona".

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"unsafe"

	"github.com/lxn/walk"
)

// uiSync esegue fn sul thread UI Win32. La NotifyIcon e i message box devono
// essere chiamati dal thread che ha creato la finestra associata; usiamo
// hiddenMw che e' la sentinel sempre presente quando la UI e' su.
func uiSync(app *App, fn func()) {
	switch {
	case app == nil:
		return
	case app.mw != nil:
		app.mw.Synchronize(fn)
	case app.hiddenMw != nil:
		app.hiddenMw.Synchronize(fn)
	default:
		// Fallback: invoca direttamente (best effort; potrebbe crashare se
		// chiamato off-thread, ma e' meglio che non eseguire affatto).
		fn()
	}
}

// refreshUpdateMenuItem riconfigura il menu "Aggiorna ora..." in base al
// risultato piu' recente del watcher. Chiamato ogni 30s dal main loop.
func refreshUpdateMenuItem(app *App) {
	if app == nil || app.updateItem == nil || app.update == nil {
		return
	}
	snap := app.update.Snapshot()
	uiSync(app, func() {
		if snap.available && snap.latestVer != "" {
			app.updateItem.SetText(fmt.Sprintf("Aggiorna ora a v%s...", snap.latestVer))
			app.updateItem.SetEnabled(true)
		} else {
			app.updateItem.SetText("Aggiorna ora... (gia' aggiornato)")
			app.updateItem.SetEnabled(false)
		}
	})
}

// runUpdateNow scarica install-noc-agent.ps1 da raw GitHub e lo esegue con
// privilegi elevati (UAC), passando token / client_id / backend del cliente
// corrente cosi' la reinstallazione e' transparent per l'utente.
//
// Eseguito in goroutine perche' fa download + Start-Process che potrebbero
// bloccare il main thread UI.
func runUpdateNow(app *App) {
	if app == nil {
		return
	}
	logf("update: avvio aggiornamento alla latest release")

	// Validazione minima: serviranno questi campi per ricostruire l'install
	if app.agent.Token == "" || app.agent.ClientID == "" || app.agent.BackendURL == "" {
		showUpdateError(app, "Mancano informazioni di provisioning (token / client_id / backend) in agent-ui.json. "+
			"Esegui prima un'installazione manuale.")
		return
	}

	// Scarica lo script in %TEMP%\install-noc-agent.ps1
	tmpScript := filepath.Join(os.TempDir(), "install-noc-agent.ps1")
	rawURL := "https://raw.githubusercontent.com/santiM86/86NOCConnectorCenter/main/noc-agent/build/install-noc-agent.ps1"
	if err := downloadFile(rawURL, tmpScript); err != nil {
		showUpdateError(app, fmt.Sprintf("Download installer fallito: %v", err))
		return
	}

	// Ricostruisci la URL WS (potrebbe essere stata convertita a https in agent-ui.json)
	wsURL := app.agent.BackendURL
	wsURL = strings.Replace(wsURL, "https://", "wss://", 1)
	wsURL = strings.Replace(wsURL, "http://", "ws://", 1)
	if !strings.HasSuffix(wsURL, "/api/agent/ws") {
		wsURL = strings.TrimRight(wsURL, "/") + "/api/agent/ws"
	}

	args := []string{
		"-NoProfile", "-ExecutionPolicy", "Bypass",
		"-File", tmpScript,
		"-Token", app.agent.Token,
		"-ClientId", app.agent.ClientID,
		"-BackendUrl", wsURL,
		"-Role", app.agent.Role,
	}

	// ShellExecuteW con verb "runas" → UAC prompt.
	if err := runElevated("powershell.exe", args); err != nil {
		showUpdateError(app, fmt.Sprintf("Avvio installer elevato fallito: %v", err))
		return
	}

	// Messaggio di conferma. L'installer girera' in finestra propria, NON
	// blocca questa UI.
	uiSync(app, func() {
		if app.mw != nil {
			walk.MsgBox(app.mw, "Aggiornamento avviato",
				"L'installer e' partito in una finestra separata. Al termine la tray UI verra' chiusa "+
					"e ripartira' automaticamente dopo qualche secondo. Non chiudere la finestra installer "+
					"prima che mostri 'COMPLETATA'.",
				walk.MsgBoxIconInformation)
		}
	})
}

// showUpdateError mostra un message box rosso con il messaggio dato.
func showUpdateError(app *App, msg string) {
	uiSync(app, func() {
		var parent walk.Form
		if app != nil && app.mw != nil {
			parent = app.mw
		}
		walk.MsgBox(parent, "Errore aggiornamento", msg, walk.MsgBoxIconError)
	})
}

// showVersionDialog popola una dialog con tutte le info di build/runtime per
// facilitare il supporto remoto. Accessibile dal menu tray "Info versione".
func showVersionDialog(app *App) {
	uiSync(app, func() {
		ver := app.agent.Version
		if ver == "" {
			ver = "?"
		}
		latest := ""
		if app != nil && app.update != nil {
			s := app.update.Snapshot()
			if s.latestVer != "" {
				latest = fmt.Sprintf("\n  Latest su GitHub: v%s%s",
					s.latestVer,
					ternary(s.available, " (aggiornamento disponibile)", " (gia' installata)"))
			}
		}
		buildDate := app.agent.BuildDate
		if buildDate == "" {
			buildDate = "?"
		}
		logPath := ""
		if b, err := os.ReadFile(filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "log_path.txt")); err == nil {
			logPath = strings.TrimSpace(string(b))
		}
		msg := fmt.Sprintf(
			"86bit NOC Agent\n\n"+
				"  Versione installata: v%s\n"+
				"  Build date: %s\n"+
				"  Piattaforma: %s/%s\n"+
				"  Agent ID: %s\n"+
				"  Cliente ID: %s\n"+
				"  Backend: %s\n"+
				"  Log path: %s%s",
			ver, buildDate, runtime.GOOS, runtime.GOARCH,
			app.agent.AgentID, app.agent.ClientID, app.agent.BackendURL,
			logPath, latest,
		)
		var parent walk.Form
		if app != nil && app.mw != nil {
			parent = app.mw
		}
		walk.MsgBox(parent, "Info versione 86bit NOC Agent", msg, walk.MsgBoxIconInformation)
	})
}

func ternary(cond bool, a, b string) string {
	if cond {
		return a
	}
	return b
}

// runElevated invoca un programma con ShellExecuteW verb=runas (UAC).
// La UI gira come utente normale; per sovrascrivere C:\Program Files\
// serve elevazione.
func runElevated(exe string, args []string) error {
	verb := "runas"
	cwd := ""
	exePtr, err := syscall.UTF16PtrFromString(exe)
	if err != nil {
		return err
	}
	verbPtr, err := syscall.UTF16PtrFromString(verb)
	if err != nil {
		return err
	}
	argLine := joinArgs(args)
	var argsPtr *uint16
	if argLine != "" {
		argsPtr, err = syscall.UTF16PtrFromString(argLine)
		if err != nil {
			return err
		}
	}
	var cwdPtr *uint16
	if cwd != "" {
		cwdPtr, _ = syscall.UTF16PtrFromString(cwd)
	}
	// SW_SHOWNORMAL = 1
	return shellExecuteW(0, verbPtr, exePtr, argsPtr, cwdPtr, 1)
}

func joinArgs(args []string) string {
	parts := make([]string, 0, len(args))
	for _, a := range args {
		if strings.ContainsAny(a, " \t\"") {
			parts = append(parts, `"`+strings.ReplaceAll(a, `"`, `""`)+`"`)
		} else {
			parts = append(parts, a)
		}
	}
	return strings.Join(parts, " ")
}

var (
	modShell32           = syscall.NewLazyDLL("shell32.dll")
	procShellExecuteW    = modShell32.NewProc("ShellExecuteW")
)

// unsafePtr ritorna l'uintptr di un *uint16 oppure 0 se nil.
// Necessario perche' syscall.Proc.Call accetta uintptr e non *uint16 nullable.
func unsafePtr(p *uint16) uintptr {
	if p == nil {
		return 0
	}
	return uintptr(unsafe.Pointer(p))
}

func shellExecuteW(hwnd uintptr, verb, file, args, cwd *uint16, show int32) error {
	ret, _, _ := procShellExecuteW.Call(
		hwnd,
		unsafePtr(verb),
		unsafePtr(file),
		unsafePtr(args),
		unsafePtr(cwd),
		uintptr(show),
	)
	// ShellExecuteW returns >32 on success
	if ret <= 32 {
		return fmt.Errorf("ShellExecuteW: code %d", ret)
	}
	return nil
}

// downloadFile salva il body di url in dst. Timeout 60s, max 1MB (lo script ps1
// e' tipicamente ~15 KB).
func downloadFile(url, dst string) error {
	cmd := exec.Command("powershell.exe", "-NoProfile", "-Command",
		fmt.Sprintf(
			"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri %q -OutFile %q -UseBasicParsing -TimeoutSec 60",
			url, dst,
		))
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Run()
}
