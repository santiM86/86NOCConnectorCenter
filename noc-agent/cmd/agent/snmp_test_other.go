//go:build !windows

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"runtime"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

func registerSNMPTestCommand(client *transport.Client, _ *logging.Logger) {
	client.Register("snmp_test", func(_ context.Context, _ json.RawMessage) (any, error) {
		return nil, fmt.Errorf("snmp_test non supportato su %s (solo windows)", runtime.GOOS)
	})
}
