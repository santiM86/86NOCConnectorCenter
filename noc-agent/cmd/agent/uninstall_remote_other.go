//go:build !windows

package main

import (
	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

// triggerRemoteUninstall noop su non-windows (l'agent gira ufficialmente
// solo su windows in produzione, ma teniamo il file per cross-build clean).
func triggerRemoteUninstall(_ bool, _ *config.Config, log *logging.Logger) {
	log.With("uninstall.remote").Warn("uninstall remoto non supportato su questa piattaforma")
}
