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

func registerAgentLogCommand(client *transport.Client, _ *logging.Logger) {
	client.Register("get_agent_logs", func(_ context.Context, _ json.RawMessage) (any, error) {
		return nil, fmt.Errorf("get_agent_logs non supportato su %s (solo windows)", runtime.GOOS)
	})
}
