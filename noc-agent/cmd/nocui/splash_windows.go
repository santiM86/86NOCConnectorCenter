// Splash screen all'avvio del Connector (boot UX).
//
// Mostra per ~3s una piccola finestra centrata con il logo Argus, il
// nome del cliente e una progress bar marquee. In parallelo verifica
// via HTTP `/api/agent/self/health` lo stato del canale WS dell'agent
// e aggiorna la riga status con l'esito.
//
// Implementazione volutamente leggera: usa walk.MainWindow con
// FixedSingleDialog frame (no resize) e si auto-chiude dopo il timeout.
// Niente SetWindowLong manipolation per evitare bug walk.
//
//go:build windows

package main

import (
	"os"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"

	"github.com/lxn/walk"
	wd "github.com/lxn/walk/declarative"
)

// showSplash blocca per al massimo `maxWait`. Ritorna quando il timer
// scade o quando il backend health check ha riportato un esito (con
// 1.2s di "leggi il messaggio" prima della chiusura).
func showSplash(app *App, maxWait time.Duration) {
	defer func() {
		if r := recover(); r != nil {
			logf("PANIC in showSplash: %v", r)
		}
	}()

	logoPath := ensureSplashLogo(app)

	var (
		dlg    *walk.MainWindow
		statLb *walk.Label
	)

	wd.MainWindow{
		AssignTo:   &dlg,
		Title:      "Argus",
		Icon:       app.icon,
		Background: wd.SolidColorBrush{Color: walk.RGB(255, 255, 255)},
		Size:       wd.Size{Width: 460, Height: 280},
		MinSize:    wd.Size{Width: 460, Height: 280},
		Layout:     wd.VBox{Margins: wd.Margins{Left: 24, Top: 24, Right: 24, Bottom: 16}, Spacing: 8},
		Children: []wd.Widget{
			wd.Composite{
				Layout: wd.HBox{Alignment: wd.AlignHCenterVCenter},
				Children: []wd.Widget{
					wd.HSpacer{},
					wd.ImageView{
						Image:   logoPath,
						Mode:    wd.ImageViewModeZoom,
						MinSize: wd.Size{Width: 96, Height: 96},
						MaxSize: wd.Size{Width: 96, Height: 96},
					},
					wd.HSpacer{},
				},
			},
			wd.Label{
				Text:          "ARGUS Connector",
				TextAlignment: wd.AlignCenter,
				TextColor:     walk.RGB(20, 20, 30),
				Font:          wd.Font{Family: "Segoe UI", PointSize: 16, Bold: true},
			},
			wd.Label{
				Text:          clientLine(app),
				TextAlignment: wd.AlignCenter,
				TextColor:     walk.RGB(110, 110, 125),
				Font:          wd.Font{Family: "Segoe UI", PointSize: 9},
			},
			wd.VSpacer{Size: 6},
			wd.ProgressBar{MarqueeMode: true, MinSize: wd.Size{Height: 8}},
			wd.Label{
				AssignTo:      &statLb,
				Text:          "Verifica connessione al NOC Center...",
				TextAlignment: wd.AlignCenter,
				TextColor:     walk.RGB(16, 64, 224),
				Font:          wd.Font{Family: "Segoe UI", PointSize: 9},
			},
		},
	}.Create()

	// Centra sullo schermo principale via GetSystemMetrics.
	sw, sh := getPrimaryScreenSize()
	b := dlg.Bounds()
	b.X = (sw - b.Width) / 2
	if b.X < 0 {
		b.X = 0
	}
	b.Y = (sh - b.Height) / 3
	if b.Y < 0 {
		b.Y = 0
	}
	dlg.SetBounds(b)

	dlg.Show()

	// Background WS health check (best-effort).
	done := make(chan struct{}, 1)
	go func() {
		var hr healthReply
		err := backendGet("/api/agent/self/health", app.agent, &hr)
		dlg.Synchronize(func() {
			if err != nil {
				statLb.SetText("NOC Center non raggiungibile - controlla rete o token")
				statLb.SetTextColor(walk.RGB(200, 60, 50))
			} else if hr.Connected {
				statLb.SetText("Connesso al NOC Center - canale WS OK")
				statLb.SetTextColor(walk.RGB(40, 150, 70))
			} else {
				statLb.SetText("Agent NON connesso al canale WS")
				statLb.SetTextColor(walk.RGB(200, 130, 30))
			}
		})
		select {
		case done <- struct{}{}:
		default:
		}
	}()

	// Resta visibile finche' health check completa (poi 1.2s di lettura)
	// oppure finche' scade maxWait, qualunque venga prima.
	timer := time.NewTimer(maxWait)
	select {
	case <-done:
		<-time.After(1200 * time.Millisecond)
	case <-timer.C:
	}
	timer.Stop()
	dlg.Synchronize(func() { _ = dlg.Close() })
	// Lascia un attimo al message loop per processare WM_CLOSE.
	deadline := time.Now().Add(600 * time.Millisecond)
	for time.Now().Before(deadline) && dlg.Visible() {
		time.Sleep(30 * time.Millisecond)
	}
}

// ensureSplashLogo prepara una path al file argus.ico utilizzabile da
// walk.ImageView. Se l'installer ha messo argus.ico in InstallDir lo
// usiamo; altrimenti scriviamo l'icona embedded in %LOCALAPPDATA%.
func ensureSplashLogo(app *App) string {
	if app.agent.InstallDir != "" {
		p := filepath.Join(app.agent.InstallDir, "argus.ico")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	tmp := filepath.Join(localAppDir(), "argus.ico")
	if _, err := os.Stat(tmp); err == nil {
		return tmp
	}
	if len(argusIcoBytes) > 0 {
		_ = os.MkdirAll(filepath.Dir(tmp), 0o755)
		_ = os.WriteFile(tmp, argusIcoBytes, 0o644)
	}
	return tmp
}

func localAppDir() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "86NocAgent")
}

func clientLine(app *App) string {
	cid := app.agent.ClientID
	if cid == "" {
		cid = "non configurato"
	}
	role := app.agent.Role
	if role == "" {
		role = "master"
	}
	v := app.agent.Version
	if v == "" {
		v = "4.0"
	}
	return "Cliente: " + cid + "  -  Ruolo: " + role + "  -  v" + v
}

// --- GetSystemMetrics wrappers ---------------------------------------------

var (
	modUser32          = syscall.NewLazyDLL("user32.dll")
	procGetSystemMetricsSW = modUser32.NewProc("GetSystemMetrics")
)

func getPrimaryScreenSize() (int, int) {
	const SM_CXSCREEN = 0
	const SM_CYSCREEN = 1
	w, _, _ := procGetSystemMetricsSW.Call(uintptr(SM_CXSCREEN))
	h, _, _ := procGetSystemMetricsSW.Call(uintptr(SM_CYSCREEN))
	if w == 0 {
		w = 1920
	}
	if h == 0 {
		h = 1080
	}
	return int(w), int(h)
}

// keep `unsafe` import used (small no-op) so future Win32 hooks compile
// without re-adding the import.
var _ = unsafe.Sizeof(int32(0))
