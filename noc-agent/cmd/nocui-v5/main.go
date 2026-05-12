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

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

// Version è iniettato a build time via -ldflags.
var Version = "5.0.0-dev"

func main() {
	app := NewApp()

	err := wails.Run(&options.App{
		Title:             "Argus Desktop",
		Width:             1240,
		Height:            780,
		MinWidth:          1024,
		MinHeight:         640,
		DisableResize:     false,
		Fullscreen:        false,
		Frameless:         false,
		StartHidden:       false, // mostra subito (default)
		HideWindowOnClose: true,  // close → tray (no kill)
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
