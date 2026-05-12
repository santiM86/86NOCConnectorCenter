// Package poller — ICMP live-polling loop.
//
// PingPoller probes every configured target with the native OS `ping`
// command (cross-platform, zero raw-socket privileges required because
// the agent runs as LocalSystem/root on its host). Results are emitted
// upstream via the callback as proto.PingPollResult and the backend
// derives the UP/DOWN status of each managed_device from them.
//
// We intentionally invoke the system `ping` instead of pulling in a Go
// ICMP library because:
//   - Zero added dependency / supply-chain surface.
//   - Behaves identically to what a tech would do by hand on the box
//     (same OS resolver, same routing table, same firewall rules).
//   - Already battle-tested on Windows by the legacy PowerShell
//     connector, so we keep the operational footprint familiar.
package poller

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

// PingPoller fans out ICMP probes against a hot-swappable target list.
type PingPoller struct {
	log *logging.Logger
	on  func(proto.PingPollResult)

	mu         sync.Mutex
	cfg        config.PingConfig
	lastPollAt time.Time
}

func NewPing(cfg config.PingConfig, log *logging.Logger, on func(proto.PingPollResult)) *PingPoller {
	return &PingPoller{cfg: cfg, log: log.With("ping"), on: on}
}

// ApplyConfig hot-swaps the ping target list / interval at runtime.
// Called by the OnWelcome handler when the backend pushes a refreshed
// device assignment for this tenant.
func (p *PingPoller) ApplyConfig(cfg config.PingConfig) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cfg = cfg
	p.log.Info("ping config hot-swapped",
		"enabled", fmt.Sprintf("%t", cfg.Enabled),
		"targets", fmt.Sprintf("%d", len(cfg.Targets)),
		"interval", cfg.Interval.String(),
	)
}

// Snapshot returns the currently active config (exported for the
// command handlers that only need to see counters).
func (p *PingPoller) Snapshot() config.PingConfig {
	return p.snapshot()
}

func (p *PingPoller) snapshot() config.PingConfig {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.cfg
}

func (p *PingPoller) LastPollAt() time.Time {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.lastPollAt
}

// Run blocks until ctx is done. Each cycle probes every target in
// parallel (capped fan-out to avoid swamping the host network stack
// on big networks).
func (p *PingPoller) Run(ctx context.Context) {
	for {
		cfg := p.snapshot()
		interval := cfg.Interval
		if interval <= 0 {
			interval = 60 * time.Second
		}
		if cfg.Enabled && len(cfg.Targets) > 0 {
			p.runOnce(ctx, cfg)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}
	}
}

func (p *PingPoller) runOnce(ctx context.Context, cfg config.PingConfig) {
	var wg sync.WaitGroup
	sem := make(chan struct{}, 32) // cap concurrency
	for _, t := range cfg.Targets {
		t := t
		if t.IP == "" {
			continue
		}
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			res := p.probe(ctx, t.IP, cfg)
			if p.on != nil {
				p.on(res)
			}
		}()
	}
	wg.Wait()
	p.mu.Lock()
	p.lastPollAt = time.Now().UTC()
	p.mu.Unlock()
}

// ProbeOne is a manual single-shot probe used by the force_ping_poll
// command (handy for the “Test” button in the device UI).
func (p *PingPoller) ProbeOne(ctx context.Context, ip string) proto.PingPollResult {
	cfg := p.snapshot()
	res := p.probe(ctx, ip, cfg)
	if p.on != nil {
		p.on(res)
	}
	return res
}

// probe runs the native `ping` once against ip. Cross-platform.
func (p *PingPoller) probe(ctx context.Context, ip string, cfg config.PingConfig) proto.PingPollResult {
	res := proto.PingPollResult{Target: ip, Method: "icmp"}
	count := cfg.Count
	if count <= 0 {
		count = 1
	}
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = 2 * time.Second
	}

	var args []string
	switch runtime.GOOS {
	case "windows":
		// -n count, -w timeout_ms
		args = []string{"-n", strconv.Itoa(count), "-w", strconv.Itoa(int(timeout.Milliseconds())), ip}
	case "darwin":
		// macOS: -c count, -W timeout_ms (per-packet), -t total_timeout_s
		args = []string{"-c", strconv.Itoa(count), "-W", strconv.Itoa(int(timeout.Milliseconds())), ip}
	default:
		// Linux/BSD: -c count, -W timeout_s, -n numeric
		secs := int(timeout.Seconds())
		if secs < 1 {
			secs = 1
		}
		args = []string{"-c", strconv.Itoa(count), "-W", strconv.Itoa(secs), "-n", ip}
	}

	// Total deadline: count * timeout + 1s slack
	total := time.Duration(count)*timeout + time.Second
	cctx, cancel := context.WithTimeout(ctx, total)
	defer cancel()

	start := time.Now()
	cmd := exec.CommandContext(cctx, "ping", args...)
	hideWindow(cmd)
	out, err := cmd.CombinedOutput()
	res.Latency = time.Since(start)

	if err != nil {
		// Non-zero exit on Windows means 100% loss; on Unix same.
		// Still parse output to extract loss / rtt if present.
		res.Reachable = false
		res.LossPct = 100.0
		// Provide a short error excerpt for debugging in the UI.
		msg := strings.TrimSpace(strings.SplitN(string(out), "\n", 2)[0])
		if msg == "" {
			msg = err.Error()
		}
		if len(msg) > 200 {
			msg = msg[:200]
		}
		res.Error = msg
		// Try to refine RTT/loss anyway (e.g. partial loss).
		applyParsed(&res, string(out), count)
		return res
	}

	applyParsed(&res, string(out), count)
	if res.LossPct < 100.0 {
		res.Reachable = true
	}
	return res
}

// applyParsed extracts loss % and best RTT from the OS ping output.
// We do not require these — Reachable is the source of truth — but
// they make the device card in the UI much more informative.
var (
	reLossUnix = regexp.MustCompile(`(\d+)% (?:packet )?loss`)
	reRTTUnix  = regexp.MustCompile(`(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/`)
	reLossWin  = regexp.MustCompile(`\((\d+)% (?:loss|persi)\)`)
	reRTTWin   = regexp.MustCompile(`(?:Average|Media)\s*=\s*(\d+)ms`)
)

func applyParsed(res *proto.PingPollResult, out string, count int) {
	scan := bufio.NewScanner(strings.NewReader(out))
	scan.Buffer(make([]byte, 0, 64*1024), 256*1024)
	for scan.Scan() {
		line := scan.Text()
		// Loss
		if m := reLossUnix.FindStringSubmatch(line); m != nil {
			if v, err := strconv.ParseFloat(m[1], 64); err == nil {
				res.LossPct = v
			}
		} else if m := reLossWin.FindStringSubmatch(line); m != nil {
			if v, err := strconv.ParseFloat(m[1], 64); err == nil {
				res.LossPct = v
			}
		}
		// RTT (use avg as a stable proxy for "best")
		if m := reRTTUnix.FindStringSubmatch(line); m != nil {
			if v, err := strconv.ParseFloat(m[1], 64); err == nil {
				res.Latency = time.Duration(v * float64(time.Millisecond))
			}
		} else if m := reRTTWin.FindStringSubmatch(line); m != nil {
			if v, err := strconv.ParseFloat(m[1], 64); err == nil {
				res.Latency = time.Duration(v * float64(time.Millisecond))
			}
		}
	}
	// Defensive: if we got no loss line at all but the exit code was 0
	// (success) we keep LossPct=0; if it was != 0 the caller already
	// set 100. Nothing to do here.
	_ = count
	_ = fmt.Sprintf // keep import slot reserved for future use
}
