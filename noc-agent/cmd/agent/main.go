// 86NocAgent — single-binary NOC agent for the 86bit platform.
//
// Architecture: one persistent WebSocket to the backend; discovery,
// SNMP polling and self-telemetry run as supervised goroutines; a
// separate watchdog binary (cmd/watchdog) restarts us on hang or crash.
//
// Run: nocagent --config /etc/86nocagent/agent.yaml
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/discovery"
	"github.com/86bit/noc-agent/internal/health"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/internal/poller"
	"github.com/86bit/noc-agent/internal/transport"
	"github.com/86bit/noc-agent/internal/update"
	"github.com/86bit/noc-agent/pkg/proto"
)

// Version is injected at build time via -ldflags.
var Version = "4.0.0-dev"

func main() {
	var (
		cfgPath     = flag.String("config", "", "path to agent.yaml (overrides default lookup)")
		printID     = flag.Bool("print-id", false, "generate a fresh agent_id and exit")
		showVersion = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()

	if *showVersion {
		fmt.Printf("86NocAgent %s (%s/%s, go %s)\n", Version, runtime.GOOS, runtime.GOARCH, runtime.Version())
		return
	}
	if *printID {
		fmt.Println(transport.NewAgentID())
		return
	}

	log := logging.New()
	rootLog := log.With("agent")

	cfg, err := config.Load(*cfgPath)
	if err != nil {
		rootLog.Error("config load", "err", err.Error())
		os.Exit(2)
	}
	if cfg.AgentID == "" {
		cfg.AgentID = transport.NewAgentID()
		rootLog.Warn("agent_id missing in config — generated ephemeral", "agent_id", cfg.AgentID)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// Health reporter + module registration
	hr := health.New()
	hr.Register("transport", 60*time.Second)
	hr.Register("discovery", 2*cfg.Discovery.Interval)
	hr.Register("poller", 2*cfg.SNMP.Interval)
	hr.Register("watchdog", 3*cfg.Heartbeat)

	// Hello message
	hostname, _ := os.Hostname()
	hello := proto.AgentHello{
		AgentID:      cfg.AgentID,
		ClientID:     cfg.ClientID,
		Token:        cfg.Token,
		Hostname:     hostname,
		OS:           runtime.GOOS,
		Arch:         runtime.GOARCH,
		AgentVersion: Version,
		BootTime:     time.Now().UTC(),
		IPs:          localIPs(),
		Capabilities: capabilities(cfg),
		Labels:       cfg.Labels,
	}

	client := transport.New(cfg, log, hello)

	// Wire SNMP poller — emits results upstream as they happen.
	snmp := poller.New(cfg.SNMP, log, func(r proto.SNMPPollResult) {
		client.PushEvent(proto.EventSNMPPoll, r)
		hr.SetLastPoll(time.Now().UTC())
		hr.Tick("poller")
	})

	// Wire discovery — emits batch on each completed sweep.
	sources := []discovery.Source{}
	if cfg.Discovery.ARP {
		sources = append(sources, discovery.NewARP())
	}
	if cfg.Discovery.MDNS {
		sources = append(sources, discovery.NewMDNS())
	}
	disc := discovery.NewManager(log, cfg.Discovery.Interval, sources, func(batch []proto.DiscoveredEndpoint) {
		client.PushEvent(proto.EventDiscoveryBatch, batch)
		hr.SetLastScan(time.Now().UTC())
		hr.Tick("discovery")
	})

	// Server-initiated commands.
	client.Register(proto.CmdPing, func(ctx context.Context, _ json.RawMessage) (any, error) {
		return map[string]any{"pong": time.Now().UTC()}, nil
	})
	client.Register(proto.CmdGetMetrics, func(ctx context.Context, _ json.RawMessage) (any, error) {
		return hr.Snapshot(), nil
	})
	client.Register(proto.CmdForceLanScan, func(ctx context.Context, _ json.RawMessage) (any, error) {
		batch := disc.ForceScan(ctx)
		return map[string]any{"endpoints": len(batch)}, nil
	})
	client.Register(proto.CmdForceSNMPPoll, func(ctx context.Context, args json.RawMessage) (any, error) {
		var a struct {
			IP        string `json:"ip"`
			Community string `json:"community"`
		}
		_ = json.Unmarshal(args, &a)
		if a.IP == "" {
			results := snmp.PollAll(ctx)
			return map[string]any{"polled": len(results)}, nil
		}
		return snmp.PollOne(ctx, a.IP, a.Community), nil
	})
	client.Register(proto.CmdRunDiagnostics, func(ctx context.Context, _ json.RawMessage) (any, error) {
		return runDiagnostics(cfg), nil
	})
	client.Register(proto.CmdShutdown, func(ctx context.Context, _ json.RawMessage) (any, error) {
		go func() { time.Sleep(200 * time.Millisecond); cancel() }()
		return map[string]any{"shutting_down": true}, nil
	})

	// Updater (no-op until cfg.Update.ManifestURL is set).
	upd := update.New(cfg.Update, Version, log)

	// Self-telemetry pump
	go heartbeatLoop(ctx, client, hr, cfg.Heartbeat)
	// Watchdog file pump (read by cmd/watchdog)
	go watchdogTick(ctx, cfg.Watchdog.HeartbeatFile, hr)
	// Log shipping pump
	go logShipper(ctx, client, log)

	// Run workers
	go disc.Run(ctx)
	go snmp.Run(ctx)
	go upd.Run(ctx)

	rootLog.Info("agent started",
		"version", Version,
		"client_id", cfg.ClientID,
		"agent_id", cfg.AgentID,
		"backend", cfg.Backend.URL,
	)

	client.Run(ctx) // blocks until ctx cancelled
	rootLog.Info("agent stopped")
}

func capabilities(c config.Config) []string {
	caps := []string{}
	if c.Discovery.ARP {
		caps = append(caps, "discovery.arp")
	}
	if c.Discovery.MDNS {
		caps = append(caps, "discovery.mdns")
	}
	if c.SNMP.Enabled {
		caps = append(caps, "poll.snmp")
	}
	caps = append(caps, "cmd.force_lan_scan", "cmd.force_snmp_poll", "cmd.get_metrics", "cmd.run_diagnostics")
	return caps
}

func localIPs() []string {
	out := []string{}
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return out
	}
	for _, a := range addrs {
		if ipNet, ok := a.(*net.IPNet); ok && !ipNet.IP.IsLoopback() {
			if ip4 := ipNet.IP.To4(); ip4 != nil {
				out = append(out, ip4.String())
			}
		}
	}
	return out
}

func heartbeatLoop(ctx context.Context, c *transport.Client, hr *health.Reporter, every time.Duration) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			c.PushHeartbeat(hr.Snapshot())
			hr.Tick("transport")
		}
	}
}

func watchdogTick(ctx context.Context, path string, hr *health.Reporter) {
	if path == "" {
		return
	}
	_ = os.MkdirAll(parentDir(path), 0o755)
	t := time.NewTicker(15 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			now := time.Now().UTC().Format(time.RFC3339Nano)
			_ = os.WriteFile(path, []byte(now), 0o644)
			hr.Tick("watchdog")
		}
	}
}

func parentDir(p string) string {
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] == '/' || p[i] == '\\' {
			return p[:i]
		}
	}
	return "."
}

func logShipper(ctx context.Context, c *transport.Client, log *logging.Logger) {
	stream := log.Stream()
	for {
		select {
		case <-ctx.Done():
			return
		case e := <-stream:
			// Ship only warn/error to the backend; info/debug stay on stderr.
			// Shipping every info-level line would create a feedback loop
			// (any log emitted by the transport layer would itself be shipped).
			if e.Level != "warn" && e.Level != "error" {
				continue
			}
			c.PushLog(e)
		}
	}
}

func runDiagnostics(cfg config.Config) map[string]any {
	out := map[string]any{
		"go_version":   runtime.Version(),
		"goroutines":   runtime.NumGoroutine(),
		"os":           runtime.GOOS,
		"arch":         runtime.GOARCH,
		"backend":      cfg.Backend.URL,
		"discovery":    cfg.Discovery,
		"snmp_targets": len(cfg.SNMP.Targets),
	}
	return out
}
