// LAN scan command handler — Windows only.
//
// Espone il comando WS `lan_scan` con args { cidr, scan_id }.
// L'handler ritorna immediatamente (ACK con scan_id) e lancia lo scan
// in goroutine: ogni risultato viene streamato al Center via agent.event
// `lan_scan_result`, lo stato avanzamento via `lan_scan_progress`,
// e a fine scan emette `lan_scan_done`.
//
//go:build windows

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/86bit/noc-agent/internal/lanscan"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/transport"
)

// activeLanScans traccia gli scan in corso per cancellazione (one-per-agent).
var (
	lanScanMu     sync.Mutex
	lanScanCancel context.CancelFunc
)

// registerLanScanCommand installa l'handler del comando server "lan_scan"
// sul client WS. Il Center invia args:
//
//	{ "scan_id": "<uuid>", "cidr": "192.168.1.0/24" }
//
// Risposta sincrona: { "scan_id": "<uuid>", "accepted": true }.
// Streaming: agent.event { kind: "lan_scan_result|progress|done", data: ... }.
func registerLanScanCommand(client *transport.Client, log *logging.Logger) {
	client.Register("lan_scan", func(ctx context.Context, args json.RawMessage) (any, error) {
		var a struct {
			ScanID string `json:"scan_id"`
			CIDR   string `json:"cidr"`
		}
		_ = json.Unmarshal(args, &a)
		if a.ScanID == "" {
			return nil, fmt.Errorf("scan_id mancante")
		}
		if strings.TrimSpace(a.CIDR) == "" {
			a.CIDR = lanscan.DetectLocalCIDR()
		}

		// One-at-a-time: cancella scan precedente se ancora attivo.
		lanScanMu.Lock()
		if lanScanCancel != nil {
			lanScanCancel()
		}
		scanCtx, cancel := context.WithCancel(context.Background())
		lanScanCancel = cancel
		lanScanMu.Unlock()

		log.Info(fmt.Sprintf("lan_scan start scan_id=%s cidr=%s", a.ScanID, a.CIDR))
		go func() {
			defer func() {
				if rv := recover(); rv != nil {
					log.Errorf("lan_scan panic scan_id=%s: %v", a.ScanID, rv)
				}
				lanScanMu.Lock()
				lanScanCancel = nil
				lanScanMu.Unlock()
			}()

			started := time.Now().UTC()
			res, err := lanscan.Run(scanCtx, a.CIDR,
				func(p lanscan.Progress) {
					client.PushEvent("lan_scan_progress", map[string]any{
						"scan_id": a.ScanID,
						"done":    p.Done,
						"total":   p.Total,
						"found":   p.Found,
					})
				},
				func(r lanscan.Result) {
					client.PushEvent("lan_scan_result", map[string]any{
						"scan_id": a.ScanID,
						"result":  r,
					})
				},
			)
			payload := map[string]any{
				"scan_id":    a.ScanID,
				"cidr":       a.CIDR,
				"total":      len(res),
				"started_at": started.Format(time.RFC3339),
				"ended_at":   time.Now().UTC().Format(time.RFC3339),
			}
			if err != nil {
				payload["error"] = err.Error()
			}
			client.PushEvent("lan_scan_done", payload)
			log.Info(fmt.Sprintf("lan_scan end scan_id=%s found=%d err=%v", a.ScanID, len(res), err))
		}()
		return map[string]any{"scan_id": a.ScanID, "accepted": true, "cidr": a.CIDR}, nil
	})

	client.Register("lan_scan_cancel", func(_ context.Context, _ json.RawMessage) (any, error) {
		lanScanMu.Lock()
		c := lanScanCancel
		lanScanCancel = nil
		lanScanMu.Unlock()
		if c != nil {
			c()
			return map[string]any{"cancelled": true}, nil
		}
		return map[string]any{"cancelled": false, "reason": "nessuno scan in corso"}, nil
	})
}
