//go:build windows

// Package main — ARGUS Desktop v5 (nocui-v5)
//
// Riscrittura completa della GUI desktop dell'Agent Go basata su Wails v2.
// Sostituisce la vecchia `nocagent-ui.exe` scritta in lxn/walk (Win32) che
// soffriva di freeze totale ad ogni chiamata di rete e di un look anni '90.
//
// Architettura:
//   - Main: bootstrap Wails (icona, finestra principale, system tray).
//   - App  : oggetto bindato al frontend (tutti i metodi sono async lato JS).
//   - tray : icona system-tray con menu dinamico (status, start/stop, open).
//
// Build (cross-compile Linux → Windows):
//   wails build --platform windows/amd64 -ldflags "-s -w -X main.Version=5.0.0"
package main

import (
	"context"
	"embed"
	"log"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

// Version è iniettato a build time via -ldflags.
var Version = "5.0.0-dev"

// hasFlag ritorna true se il flag passato e' presente in os.Args.
// Usato per gestire --minimized (autostart Datto-style: parte
// in taskbar, niente popup di finestra al login) e --tray (alias).
func hasFlag(name string) bool {
	for _, a := range os.Args[1:] {
		if a == name || a == "-"+name[2:] {
			return true
		}
	}
	return false
}

func main() {
	app := NewApp()

	// Datto-style: se lanciato dal Scheduled Task At Logon con
	// --minimized (o --tray), parte minimizzato in taskbar invece di
	// aprire la finestra. L'utente vede solo l'icona Argus nella taskbar
	// (come Datto Agent Monitor) — finestra accessibile via click.
	startHidden := false
	winStartState := options.Normal
	if hasFlag("--minimized") || hasFlag("--tray") {
		// StartHidden=true → la finestra non appare. L'utente vede solo
		// l'eseguibile come processo. NB: per avere icona in taskbar
		// servirebbe systray vera, qui usiamo Minimised come compromesso.
		startHidden = false
		winStartState = options.Minimised
	}

	err := wails.Run(&options.App{
		Title:             "Argus Desktop",
		Width:             1240,
		Height:            780,
		MinWidth:          1024,
		MinHeight:         640,
		DisableResize:     false,
		Fullscreen:        false,
		Frameless:         false,
		StartHidden:       startHidden,
		HideWindowOnClose: true, // close → tray (no kill)
		WindowStartState:  winStartState,
		BackgroundColour:  &options.RGBA{R: 11, G: 13, B: 20, A: 1},
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		OnStartup:     app.startup,
		OnDomReady:    app.domReady,
		OnBeforeClose: app.beforeClose,
		OnShutdown:    app.shutdown,
		Bind: []any{
			app,
		},
		Windows: &windows.Options{
			WebviewIsTransparent:              false,
			WindowIsTranslucent:               false,
			DisableWindowIcon:                 false,
			DisableFramelessWindowDecorations: false,
			WebviewUserDataPath:               "",
			// Edge WebView2 user agent custom: utile per filtri lato backend.
			WebviewBrowserPath: "",
		},
	})
	if err != nil {
		log.Fatalf("argus-desktop: wails run: %v", err)
	}
	_ = context.Background()
}
