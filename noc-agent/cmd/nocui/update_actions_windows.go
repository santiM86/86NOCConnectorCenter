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
	wd "github.com/lxn/walk/declarative"
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

// showVersionDialog apre una dialog moderna con tutte le info di
// build/runtime — usata dal menu tray "Info versione" e dal supporto
// remoto. Layout enterprise: header brandizzato 86bit / ARGUS,
// sezioni Sistema + Identita' + Collegamento, footer con link al
// portale 86bit e pulsanti Apri Center / Chiudi.
//
// L'implementazione usa lxn/walk/declarative al posto di walk.MsgBox
// per avere controllo completo su font, colori, padding, e per
// supportare un layout multi-colonna con valori monospace selezionabili
// (utile per copiare l'AgentID e mandarlo al supporto).
func showVersionDialog(app *App) {
	uiSync(app, func() {
		ver := app.agent.Version
		if ver == "" {
			ver = "?"
		} else {
			// Normalizza il prefisso "v": app.agent.Version puo' arrivare
			// con o senza "v" iniziale (es. "v4.25.4" oppure "4.25.4"). Il
			// display la ri-antepone ("v"+ver): senza questa normalizzazione
			// si otteneva "vv4.25.4" (bug segnalato sullo scanner). Rimuove
			// UNA sola "v"/"V" iniziale.
			ver = strings.TrimPrefix(strings.TrimPrefix(ver, "v"), "V")
		}
		buildDate := app.agent.BuildDate
		if buildDate == "" {
			buildDate = "—"
		}
		platform := fmt.Sprintf("%s/%s", runtime.GOOS, runtime.GOARCH)

		latestStatus := "—"
		latestColor := walk.RGB(0x6B, 0x72, 0x80)
		if app != nil && app.update != nil {
			s := app.update.Snapshot()
			if s.latestVer != "" {
				if s.available {
					latestStatus = fmt.Sprintf("v%s — aggiornamento disponibile", s.latestVer)
					latestColor = walk.RGB(0xD9, 0x77, 0x06) // amber
				} else {
					latestStatus = fmt.Sprintf("v%s — gia' allineato", s.latestVer)
					latestColor = walk.RGB(0x05, 0x96, 0x69) // emerald
				}
			}
		}

		agentID := app.agent.AgentID
		clientID := app.agent.ClientID
		backend := app.agent.BackendURL
		if agentID == "" {
			agentID = "—"
		}
		if clientID == "" {
			clientID = "—"
		}
		if backend == "" {
			backend = "—"
		}

		var dlg *walk.Dialog
		var acceptBtn *walk.PushButton
		var parent walk.Form
		if app != nil && app.mw != nil {
			parent = app.mw
		}

		// Palette enterprise (coerente con il dark navy del Center web)
		darkNavy := walk.RGB(0x0C, 0x1A, 0x2E)
		mutedText := walk.RGB(0xB7, 0xC2, 0xD6)
		body := walk.RGB(0xF7, 0xF8, 0xFB)
		label := walk.RGB(0x6B, 0x72, 0x80)
		value := walk.RGB(0x11, 0x18, 0x27)

		mono := wd.Font{Family: "Consolas", PointSize: 9}
		labelFont := wd.Font{Family: "Segoe UI", PointSize: 9}
		valueFont := wd.Font{Family: "Segoe UI", PointSize: 9, Bold: true}

		fieldRow := func(name, val string, valFont wd.Font, valColor walk.Color) []wd.Widget {
			return []wd.Widget{
				wd.Label{Text: name, Font: labelFont, TextColor: label, MinSize: wd.Size{Width: 110}},
				wd.LineEdit{Text: val, Font: valFont, TextColor: valColor, ReadOnly: true, Background: wd.SolidColorBrush{Color: body}},
			}
		}

		copyToClipboard := func(s string) {
			_ = walk.Clipboard().SetText(s)
		}

		_ = valueFont
		_ = mono

		err := (wd.Dialog{
			AssignTo:      &dlg,
			Title:         "ARGUS Connector · Informazioni",
			DefaultButton: &acceptBtn,
			CancelButton:  &acceptBtn,
			MinSize:       wd.Size{Width: 540, Height: 480},
			Size:          wd.Size{Width: 560, Height: 500},
			Icon:          loadAppIcon(),
			Background:    wd.SolidColorBrush{Color: body},
			Layout:        wd.VBox{MarginsZero: true, SpacingZero: true},
			Children: []wd.Widget{
				// ===== HEADER (banda scura con logo + product name) =====
				wd.Composite{
					Background: wd.SolidColorBrush{Color: darkNavy},
					Layout:     wd.HBox{Margins: wd.Margins{Left: 20, Top: 16, Right: 20, Bottom: 16}, Spacing: 14},
					Children: []wd.Widget{
						wd.ImageView{
							Image:     loadAppIcon(),
							MinSize:   wd.Size{Width: 40, Height: 40},
							MaxSize:   wd.Size{Width: 40, Height: 40},
							Mode:      wd.ImageViewModeZoom,
							Alignment: wd.AlignHCenterVCenter,
						},
						wd.Composite{
							Background: wd.SolidColorBrush{Color: darkNavy},
							Layout:     wd.VBox{MarginsZero: true, Spacing: 2},
							Children: []wd.Widget{
								wd.Label{
									Text:      "ARGUS Connector",
									Font:      wd.Font{Family: "Segoe UI", PointSize: 14, Bold: true},
									TextColor: walk.RGB(0xFF, 0xFF, 0xFF),
								},
								wd.Label{
									Text:      "by 86bit · Endpoint Monitoring & Discovery",
									Font:      wd.Font{Family: "Segoe UI", PointSize: 8},
									TextColor: mutedText,
								},
							},
						},
					},
				},
				// ===== BODY: sezioni Sistema / Identita' / Collegamento =====
				wd.Composite{
					Background: wd.SolidColorBrush{Color: body},
					Layout:     wd.VBox{Margins: wd.Margins{Left: 20, Top: 18, Right: 20, Bottom: 8}, Spacing: 14},
					Children: []wd.Widget{
						// Sezione SISTEMA
						wd.Label{
							Text:      "SISTEMA",
							Font:      wd.Font{Family: "Segoe UI", PointSize: 8, Bold: true},
							TextColor: label,
						},
						wd.Composite{
							Layout: wd.Grid{Columns: 2, Margins: wd.Margins{Top: 2}, Spacing: 8},
							Children: append(append(append(
								fieldRow("Versione", "v"+ver, valueFont, value),
								fieldRow("Build date", buildDate, labelFont, value)...),
								fieldRow("Piattaforma", platform, labelFont, value)...),
								wd.Label{Text: "Aggiornamento", Font: labelFont, TextColor: label, MinSize: wd.Size{Width: 110}},
								wd.Label{Text: latestStatus, Font: valueFont, TextColor: latestColor},
							),
						},
						// Sezione IDENTITA' e COLLEGAMENTO
						wd.Label{
							Text:      "IDENTITA' E COLLEGAMENTO",
							Font:      wd.Font{Family: "Segoe UI", PointSize: 8, Bold: true},
							TextColor: label,
						},
						wd.Composite{
							Layout: wd.Grid{Columns: 2, Margins: wd.Margins{Top: 2}, Spacing: 8},
							Children: append(append(
								fieldRow("Agent ID", agentID, mono, value),
								fieldRow("Cliente ID", clientID, mono, value)...),
								fieldRow("Backend", backend, labelFont, value)...,
							),
						},
						// NOTA: sezione "LOG" rimossa intenzionalmente. I log
						// dell'agent ora si consultano ESCLUSIVAMENTE dal Center
						// (route /agents -> pulsante 📋 sulla riga del connector).
						// Mostrare il path qui era fuorviante: l'utente non puo'
						// aprirlo perche' sta sotto C:\Windows\System32\config\
						// systemprofile\AppData\ del profilo SYSTEM.
						wd.VSpacer{},
					},
				},
				// ===== FOOTER (separator + link + buttons) =====
				wd.Composite{
					Background: wd.SolidColorBrush{Color: walk.RGB(0xEE, 0xF1, 0xF6)},
					Layout:     wd.HBox{Margins: wd.Margins{Left: 20, Top: 12, Right: 20, Bottom: 12}, Spacing: 8},
					Children: []wd.Widget{
						wd.Label{
							Text:      "© 86bit S.r.l. · supporto: info@86bit.it",
							Font:      wd.Font{Family: "Segoe UI", PointSize: 8},
							TextColor: label,
						},
						wd.HSpacer{},
						wd.PushButton{
							Text: "Copia Agent ID",
							OnClicked: func() {
								copyToClipboard(agentID)
							},
						},
						wd.PushButton{
							Text: "Apri Center",
							OnClicked: func() {
								if backend != "" && backend != "—" {
									openInBrowser(backend)
								}
							},
						},
						wd.PushButton{
							AssignTo: &acceptBtn,
							Text:     "Chiudi",
							OnClicked: func() {
								if dlg != nil {
									dlg.Accept()
								}
							},
						},
					},
				},
			},
		}).Create(parent)
		if err != nil {
			// Fallback alla MsgBox legacy se per qualche ragione il
			// dialog declarative fallisce (es. assenza di font).
			walk.MsgBox(parent, "Info versione 86bit NOC Agent",
				fmt.Sprintf("v%s · %s · %s\nAgentID: %s\nBackend: %s",
					ver, buildDate, platform, agentID, backend),
				walk.MsgBoxIconInformation)
			return
		}
		dlg.Run()
	})
}

func ternary(cond bool, a, b string) string {
	if cond {
		return a
	}
	return b
}

// openInBrowser apre un URL nel browser di default usando ShellExecute.
// Best-effort: nessun errore propagato — se fallisce (es. sandbox), il
// dialog rimane comunque utilizzabile.
func openInBrowser(url string) {
	if url == "" {
		return
	}
	u16, _ := syscall.UTF16PtrFromString(url)
	verb, _ := syscall.UTF16PtrFromString("open")
	shell32 := syscall.NewLazyDLL("shell32.dll")
	shellExec := shell32.NewProc("ShellExecuteW")
	_, _, _ = shellExec.Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(u16)), 0, 0, 1)
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
