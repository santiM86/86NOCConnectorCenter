//go:build !windows

// update_remote_other.go — stub no-op per non-Windows. Il command WS
// handler "update" rifiuta gia' su non-windows, ma questa funzione
// dev'essere definita per compilare il pacchetto su Linux/macOS
// (necessario per CI cross-build).
package main

import (
	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

func triggerRemoteUpdate(version string, cfg *config.Config, log *logging.Logger) {
	log.Warn("triggerRemoteUpdate stub: not supported on this OS")
}
