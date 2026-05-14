// Stub non-Windows: il comando lan_scan ritorna errore "unsupported".
//
//go:build !windows

package main

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

func registerLanScanCommand(client *transport.Client, _ *logging.Logger) {
	client.Register("lan_scan", func(_ context.Context, _ json.RawMessage) (any, error) {
		return nil, errors.New("lan_scan: supportato solo su agent Windows")
	})
	client.Register("lan_scan_cancel", func(_ context.Context, _ json.RawMessage) (any, error) {
		return map[string]any{"cancelled": false, "reason": "non supportato"}, nil
	})
}
