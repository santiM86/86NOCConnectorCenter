//go:build !windows

// upgrade_log_other.go — stub no-op per OS non-Windows. Il comando
// get_upgrade_log ritorna errore "not supported", lo stesso pattern
// usato da update_remote / uninstall_remote.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"runtime"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

func registerUpgradeLogCommand(client *transport.Client, _ *logging.Logger) {
	client.Register("get_upgrade_log", func(_ context.Context, _ json.RawMessage) (any, error) {
		return nil, fmt.Errorf("get_upgrade_log non supportato su %s (solo windows)", runtime.GOOS)
	})
}
