package main

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/nettrace"
	"github.com/86bit/noc-agent/internal/transport"
)

// registerNetTraceCommand espone il comando WS "net_trace": esegue una
// diagnosi di percorso (mtr/traceroute/tracert) verso un target e ritorna
// gli hop con loss%/latenza. Pensato per l'agent-SONDA del NOC.
func registerNetTraceCommand(client *transport.Client, log *logging.Logger) {
	client.Register("net_trace", func(ctx context.Context, args json.RawMessage) (any, error) {
		var a nettrace.Args
		if err := json.Unmarshal(args, &a); err != nil {
			return nil, fmt.Errorf("net_trace payload invalido: %w", err)
		}
		if a.Target == "" {
			return nil, fmt.Errorf("net_trace: target mancante")
		}
		log.Info("net_trace request", "target", a.Target, "mode", a.Mode, "port", fmt.Sprintf("%d", a.Port))
		res := nettrace.Run(ctx, a)
		log.Info("net_trace done", "target", a.Target, "tool", res.Tool, "hops", fmt.Sprintf("%d", len(res.Hops)), "reached", fmt.Sprintf("%t", res.Reached))
		return res, nil
	})
}
