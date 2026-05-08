//go:build windows

package main

import (
	"context"
	"fmt"

	"golang.org/x/sys/windows/svc"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

// Watchdog runs as a Windows service when launched by SCM. Without this
// handler Windows would terminate it within seconds because the binary
// would not respond to SCM control messages.

func runIfService() bool {
	in, err := svc.IsWindowsService()
	if err != nil {
		return false
	}
	return in
}

type winWatchdog struct {
	cfg     config.Config
	pidFile string
}

func (w *winWatchdog) Execute(_ []string, r <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	status <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		runWatchdog(ctx, w.cfg, w.pidFile)
		close(done)
	}()

	status <- svc.Status{State: svc.Running, Accepts: accepted}

loop:
	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				status <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				break loop
			}
		case <-done:
			break loop
		}
	}

	status <- svc.Status{State: svc.StopPending}
	cancel()
	<-done
	status <- svc.Status{State: svc.Stopped}
	return false, 0
}

func runAsWindowsService(cfg config.Config, pidFile string, _ *logging.Logger) error {
	if err := svc.Run("86NocWatchdog", &winWatchdog{cfg: cfg, pidFile: pidFile}); err != nil {
		return fmt.Errorf("svc.Run: %w", err)
	}
	return nil
}
