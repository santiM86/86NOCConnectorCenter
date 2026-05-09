//go:build windows

package main

import (
	"context"
	"fmt"

	"golang.org/x/sys/windows/svc"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
)

// shouldRunAsService returns true when the agent must hand off to the
// Windows Service Control Manager. We auto-detect non-interactive sessions
// (i.e. processes started by SCM) and also honour an explicit --service
// flag for testing.
func shouldRunAsService(forceFlag bool) bool {
	if forceFlag {
		return true
	}
	inService, err := svc.IsWindowsService()
	if err != nil {
		return false
	}
	return inService
}

type winAgent struct {
	cfg config.Config
	log *logging.Logger
}

// Execute is the SCM service handler. It must respond to control messages
// quickly: any blocking work runs in a goroutine while we keep draining
// the request channel.
func (w *winAgent) Execute(_ []string, r <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	const acceptedCmds = svc.AcceptStop | svc.AcceptShutdown
	status <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		runAgent(ctx, w.cfg, w.log)
		close(done)
	}()

	status <- svc.Status{State: svc.Running, Accepts: acceptedCmds}

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

func runAsService(cfg config.Config, log *logging.Logger) error {
	if err := svc.Run(ServiceName, &winAgent{cfg: cfg, log: log}); err != nil {
		return fmt.Errorf("svc.Run: %w", err)
	}
	return nil
}
