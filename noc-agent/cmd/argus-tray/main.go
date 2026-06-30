//go:build windows

// Package main — argus-tray
//
// Binario sytstray-only stile Datto/CentraStage. Mostra l'icona "Argus"
// in System Tray (lato destro della taskbar Windows, accanto all'orologio)
// senza aprire alcuna finestra. Click sull'icona / menu:
//
//   - Apri NOC Center      → apre https://argus.86bit.it nel browser
//   - Stato Agent          → apre ArgusDesktop.exe (mini-finestra status)
//   - Apri agent.yaml      → Notepad sulla config locale
//   - Riavvia servizio     → sc.exe stop/start 86NocAgent (richiede admin)
//   - Esci                 → killa solo la tray, NON il servizio
//
// L'icona viene letta da `argus-tray.ico` se presente accanto
// all'eseguibile, altrimenti dall'icona embed (fallback compile-time).
//
// Vita del processo: avviato dal Scheduled Task At Logon dell'utente
// loggato (vedi installer_gui.ps1.template). Niente console window
// (subsystem GUI grazie a -H=windowsgui in -ldflags).
//
// Tooltip dinamico: hostname + versione agent + cliente (letti da
// C:\Program Files\86NocAgent\agent-ui.json che lo script PS scrive
// durante l'install).
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	_ "embed"

	"github.com/getlantern/systray"
)

//go:embed argus.ico
var iconBytes []byte

//go:embed update_gui.ps1
var updateGUITemplate string

// agentUIConfig riflette il JSON scritto dall'installer.
// Vedi installer_gui.ps1.template step [9/11].
type agentUIConfig struct {
	BackendURL string `json:"backend_url"`
	ClientID   string `json:"client_id"`
	Token      string `json:"token"`
	Role       string `json:"role"`
	InstallDir string `json:"install_dir"`
	ConfigPath string `json:"config_path"`
	Version    string `json:"version"`
	ClientName string `json:"client_name,omitempty"`
}

// loadConfig prova a leggere agent-ui.json. Best-effort: se manca
// usiamo default. NON facciamo crash.
//
// Ordine di lookup (primo che ha InstallDir valorizzato vince):
//   1. %ProgramData%\86NocAgent\agent-ui.json
//      (path "ufficiale" scritto da install-noc-agent.ps1 step 6,
//      preservato tra update; contiene client_name + agent_id reale)
//   2. accanto all'eseguibile (quando argus-tray.exe sta in InstallDir)
//   3. %ProgramFiles%\86NocAgent\agent-ui.json (legacy install, rimosso
//      dalle versioni recenti ma compat con installazioni pre-v4.5)
func loadConfig() agentUIConfig {
	var c agentUIConfig
	candidates := []string{
		filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent-ui.json"),
		`C:\ProgramData\86NocAgent\agent-ui.json`,
	}
	if exe, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Join(filepath.Dir(exe), "agent-ui.json"))
	}
	candidates = append(candidates,
		filepath.Join(os.Getenv("ProgramFiles"), "86NocAgent", "agent-ui.json"),
		`C:\Program Files\86NocAgent\agent-ui.json`,
	)
	for _, p := range candidates {
		if b, err := os.ReadFile(p); err == nil {
			// Strip UTF-8 BOM (EF BB BF). PowerShell scrive
			// [System.IO.File]::WriteAllText(..., UTF8) che emette
			// BOM; Go json.Unmarshal fallisce silente sul BOM lasciando
			// la struct a zero-value. Diagnosticato in v4.14.x: popup
			// "Argus Connector" mostrava Versione/Cliente vuoti anche se
			// agent-ui.json era popolato correttamente.
			if len(b) >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF {
				b = b[3:]
			}
			_ = json.Unmarshal(b, &c)
			if c.InstallDir != "" {
				return c
			}
		}
	}
	// Default sensible se agent-ui.json manca
	if c.InstallDir == "" {
		c.InstallDir = filepath.Join(os.Getenv("ProgramFiles"), "86NocAgent")
	}
	if c.ConfigPath == "" {
		c.ConfigPath = filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.yaml")
	}
	return c
}

// dashboardURL converte il backend WS URL nel URL https del Center.
// "wss://argus.86bit.it/api/agent/ws" → "https://argus.86bit.it".
func dashboardURL(cfg agentUIConfig) string {
	u := strings.TrimSpace(cfg.BackendURL)
	if u == "" {
		return "https://argus.86bit.it"
	}
	u = strings.Replace(u, "wss://", "https://", 1)
	u = strings.Replace(u, "ws://", "http://", 1)
	if i := strings.Index(u, "/api/"); i > 0 {
		u = u[:i]
	}
	return strings.TrimRight(u, "/")
}

// openBrowser apre l'URL nel browser di default (senza console window).
func openBrowser(url string) {
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Start()
}

// openFile apre un file con l'app di default associata.
func openFile(path string) {
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", path)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Start()
}

// startProcess lancia un binario in background, no console.
func startProcess(path string, args ...string) {
	cmd := exec.Command(path, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
	_ = cmd.Start()
}

// startProcessVisible lancia un binario MOSTRANDO la sua finestra.
// Usato per powershell con GUI script che vogliamo l'utente veda.
func startProcessVisible(path string, args ...string) {
	cmd := exec.Command(path, args...)
	_ = cmd.Start()
}

// messageBoxW chiama l'API Win32 MessageBoxW per mostrare una popup nativa
// (stile Datto/Windows). Niente Notepad, niente file temp.
// Flag MB_ICONINFORMATION (0x40) + MB_OK (0x00).
func messageBoxW(title, text string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	mbox := user32.NewProc("MessageBoxW")
	titlePtr, _ := syscall.UTF16PtrFromString(title)
	textPtr, _ := syscall.UTF16PtrFromString(text)
	_, _, _ = mbox.Call(0, uintptr(unsafe.Pointer(textPtr)), uintptr(unsafe.Pointer(titlePtr)), 0x40)
}

// runUpdateGUI lancia un PowerShell con uno script che mostra una
// finestra WinForms (titolo, label di stato, progress bar) e in
// background esegue install-noc-agent.ps1 catturandone l'output.
// Datto/CentraStage style: GUI nativa Windows, niente console blu.
func runUpdateGUI(cfg agentUIConfig) {
	if cfg.Token == "" || cfg.ClientID == "" {
		messageBoxW("Argus - Aggiorna Connector",
			"Configurazione incompleta: manca token o client_id in agent-ui.json.\n"+
				"Apri il NOC Center e usa il pulsante Aggiorna da li.")
		return
	}
	// Lo script GUI vive embedded come stringa Go. Vedi argus-update-gui.ps1
	// per un file leggibile (e' una copia identica).
	ps := buildUpdateGUIScript(cfg)
	tmp := filepath.Join(os.TempDir(), fmt.Sprintf("argus-update-%d.ps1", time.Now().Unix()))
	if err := os.WriteFile(tmp, []byte(ps), 0644); err != nil {
		messageBoxW("Argus - Errore", "Impossibile scrivere lo script di update:\n"+err.Error())
		return
	}
	// `-WindowStyle Hidden` nasconde la console di PowerShell.
	// Lo script poi mostra la sua WinForms.
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-ExecutionPolicy", "Bypass",
		"-WindowStyle", "Hidden", "-File", tmp)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	_ = cmd.Start()
}

// restartService — sc.exe stop + start 86NocAgent. Richiede admin.
// Lanciato via ShellExecute "runas" per UAC prompt.
func restartService() {
	ps := `Stop-Service -Name '86NocAgent' -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2; Start-Service -Name '86NocAgent' -ErrorAction SilentlyContinue`
	cmd := exec.Command("powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	_ = cmd.Start()
}

// hostname best-effort, no fatal.
func hostname() string {
	if h, err := os.Hostname(); err == nil {
		return h
	}
	return "unknown"
}

var (
	cfg     agentUIConfig
	cfgLock sync.RWMutex
)

func currentCfg() agentUIConfig {
	cfgLock.RLock()
	defer cfgLock.RUnlock()
	return cfg
}

func main() {
	cfg = loadConfig()
	systray.Run(onReady, onExit)
}

func onReady() {
	systray.SetIcon(iconBytes)
	systray.SetTitle("") // Windows ignora il title in tray, ma evita placeholder ASCII

	updateTooltip := func() {
		c := currentCfg()
		client := c.ClientName
		if client == "" && c.ClientID != "" {
			client = c.ClientID[:min(8, len(c.ClientID))]
		}
		tt := fmt.Sprintf("Argus Agent v%s — %s — %s",
			c.Version, hostname(), client)
		systray.SetTooltip(tt)
	}
	updateTooltip()

	mOpenCenter := systray.AddMenuItem("Apri NOC Center", "Apre il NOC Center nel browser")
	systray.AddSeparator()
	mUpdate := systray.AddMenuItem("Aggiorna Connector", "Avvia procedura di aggiornamento con GUI")
	mRestart := systray.AddMenuItem("Riavvia servizio", "Riavvia 86NocAgent (richiede admin)")
	systray.AddSeparator()
	mAbout := systray.AddMenuItem("Informazioni", "Versione e info agent")
	mQuit := systray.AddMenuItem("Esci dal tray", "Chiude solo l'icona, il servizio resta attivo")

	// Periodic refresh del tooltip + reload config (ogni 60s, low cost)
	go func() {
		t := time.NewTicker(60 * time.Second)
		defer t.Stop()
		for range t.C {
			cfgLock.Lock()
			cfg = loadConfig()
			cfgLock.Unlock()
			updateTooltip()
		}
	}()

	// Event loop
	for {
		select {
		case <-mOpenCenter.ClickedCh:
			openBrowser(dashboardURL(currentCfg()))
		case <-mUpdate.ClickedCh:
			runUpdateGUI(currentCfg())
		case <-mRestart.ClickedCh:
			restartService()
		case <-mAbout.ClickedCh:
			c := currentCfg()
			info := fmt.Sprintf(
				"Argus Connector\n\n"+
					"Versione:   v%s\n"+
					"Host:       %s\n"+
					"Cliente:    %s\n"+
					"Backend:    %s\n"+
					"Install:    %s",
				c.Version, hostname(), c.ClientName,
				dashboardURL(c), c.InstallDir,
			)
			messageBoxW("Argus Connector - Informazioni", info)
		case <-mQuit.ClickedCh:
			systray.Quit()
			return
		}
	}
}

func onExit() {
	// Cleanup placeholder: nessuna risorsa da liberare.
}

// buildUpdateGUIScript ritorna lo script PowerShell embedded (update_gui.ps1)
// con i placeholder sostituiti dai valori di agent-ui.json.
func buildUpdateGUIScript(cfg agentUIConfig) string {
	scriptURL := "https://raw.githubusercontent.com/santiM86/86NOCConnectorCenter/main/noc-agent/build/install-noc-agent.ps1"
	esc := func(s string) string {
		// Escape single-quote per PowerShell single-quoted string literal.
		return strings.ReplaceAll(s, "'", "''")
	}
	s := updateGUITemplate
	s = strings.ReplaceAll(s, "__TOKEN__", esc(cfg.Token))
	s = strings.ReplaceAll(s, "__CLIENT_ID__", esc(cfg.ClientID))
	s = strings.ReplaceAll(s, "__BACKEND_URL__", esc(cfg.BackendURL))
	s = strings.ReplaceAll(s, "__CLIENT_NAME__", esc(cfg.ClientName))
	s = strings.ReplaceAll(s, "__SCRIPT_URL__", esc(scriptURL))
	return s
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
