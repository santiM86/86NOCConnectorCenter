//go:build !windows

package main

import (
	"context"
	"os/signal"
	"syscall"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

// On non-Windows platforms there is no SCM. We rely on systemd / launchd
// (Restart=always + companion watchdog) for supervision. The --service
// flag is treated as "run in foreground but expect a supervisor".
func shouldRunAsService(_ bool) bool { return false }

func runAsService(cfg config.Config, log *logging.Logger) error {
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	runAgent(ctx, cfg, log)
	return nil
}
