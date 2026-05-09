//go:build !windows

package main

import (
	"context"
	"os/signal"
	"syscall"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

func runIfService() bool { return false }

func runAsWindowsService(cfg config.Config, pidFile string, _ *logging.Logger) error {
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	runWatchdog(ctx, cfg, pidFile)
	return nil
}
