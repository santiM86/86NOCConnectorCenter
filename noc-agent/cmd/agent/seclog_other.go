//go:build !windows

// Stub Linux/macOS: il registro accessi AdS (Windows Event Log) e' solo Windows.
package main

import (
	"context"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

func runSecLogCollector(ctx context.Context, client *transport.Client, log *logging.Logger) {
	log.With("seclog").Info("seclog collector: non supportato su questa piattaforma (solo Windows)")
}
