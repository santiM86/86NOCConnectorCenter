// Package poller runs the SNMP polling loop. It supports a list of
// configured targets, each with its own community/profile, and emits
// SNMPPollResult events upstream.
//
// The implementation is intentionally minimal — sysName / sysDescr /
// sysObjectID / sysUpTime — because the backend already owns the rich
// device-profile catalogue (Zyxel/MikroTik/Printer MIB...). Once the
// agent ships a poll result with sys_object_id, the backend can decide
// which extra OIDs to request via a follow-up server.command.
package poller

import (
	"context"
	"fmt"
	"net"
	"sync"
	"time"

	"github.com/gosnmp/gosnmp"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

const (
	oidSysDescr    = "1.3.6.1.2.1.1.1.0"
	oidSysObjectID = "1.3.6.1.2.1.1.2.0"
	oidSysUpTime   = "1.3.6.1.2.1.1.3.0"
	oidSysName     = "1.3.6.1.2.1.1.5.0"
)

type Poller struct {
	cfg config.SNMPConfig
	log *logging.Logger
	on  func(proto.SNMPPollResult)

	mu         sync.Mutex
	lastPollAt time.Time
}

func New(cfg config.SNMPConfig, log *logging.Logger, on func(proto.SNMPPollResult)) *Poller {
	return &Poller{cfg: cfg, log: log.With("snmp"), on: on}
}

// LastPollAt returns the timestamp of the last completed cycle.
func (p *Poller) LastPollAt() time.Time {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.lastPollAt
}

// Run blocks until ctx done, polling every cfg.Interval.
func (p *Poller) Run(ctx context.Context) {
	if !p.cfg.Enabled {
		return
	}
	interval := p.cfg.Interval
	if interval <= 0 {
		interval = 60 * time.Second
	}
	t := time.NewTicker(interval)
	defer t.Stop()
	p.runOnce(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			p.runOnce(ctx)
		}
	}
}

// PollOne runs a single ad-hoc SNMP query against ip with the optional
// community override. Result is returned regardless of reachability.
func (p *Poller) PollOne(ctx context.Context, ip, community string) proto.SNMPPollResult {
	res := p.poll(ctx, ip, community)
	if p.on != nil {
		p.on(res)
	}
	return res
}

// PollAll polls every configured target once and emits results.
func (p *Poller) PollAll(ctx context.Context) []proto.SNMPPollResult {
	return p.runOnce(ctx)
}

func (p *Poller) runOnce(ctx context.Context) []proto.SNMPPollResult {
	if len(p.cfg.Targets) == 0 {
		return nil
	}
	results := make([]proto.SNMPPollResult, 0, len(p.cfg.Targets))
	var wg sync.WaitGroup
	mu := sync.Mutex{}
	sem := make(chan struct{}, 16)
	for _, t := range p.cfg.Targets {
		t := t
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			res := p.poll(ctx, t.IP, t.Community)
			mu.Lock()
			results = append(results, res)
			mu.Unlock()
			if p.on != nil {
				p.on(res)
			}
		}()
	}
	wg.Wait()
	p.mu.Lock()
	p.lastPollAt = time.Now().UTC()
	p.mu.Unlock()
	return results
}

func (p *Poller) poll(ctx context.Context, ip, community string) proto.SNMPPollResult {
	res := proto.SNMPPollResult{Target: ip, OIDs: map[string]string{}}
	communities := p.cfg.Communities
	if community != "" {
		communities = append([]string{community}, communities...)
	}
	if len(communities) == 0 {
		communities = []string{"public"}
	}

	host, port, err := net.SplitHostPort(ip)
	if err != nil {
		host = ip
		port = "161"
	}

	timeout := p.cfg.Timeout
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	if dl, ok := ctx.Deadline(); ok {
		if d := time.Until(dl); d > 0 && d < timeout {
			timeout = d
		}
	}

	start := time.Now()
	var lastErr error
	for _, c := range communities {
		g := &gosnmp.GoSNMP{
			Target:    host,
			Port:      portU16(port),
			Community: c,
			Version:   gosnmp.Version2c,
			Timeout:   timeout,
			Retries:   p.cfg.Retries,
		}
		if err := g.Connect(); err != nil {
			lastErr = err
			continue
		}
		oids := []string{oidSysDescr, oidSysObjectID, oidSysUpTime, oidSysName}
		pkt, err := g.Get(oids)
		_ = g.Conn.Close()
		if err != nil {
			lastErr = err
			continue
		}
		// success
		for _, v := range pkt.Variables {
			switch v.Name {
			case "." + oidSysDescr:
				res.SysDescr = asString(v)
			case "." + oidSysObjectID:
				res.SysObjectID = asString(v)
			case "." + oidSysUpTime:
				if t, ok := v.Value.(uint32); ok {
					res.Uptime = time.Duration(t) * 10 * time.Millisecond
				}
			case "." + oidSysName:
				res.SysName = asString(v)
			}
		}
		res.Reachable = true
		res.Latency = time.Since(start)
		return res
	}
	res.Reachable = false
	res.Latency = time.Since(start)
	if lastErr != nil {
		res.Error = lastErr.Error()
	} else {
		res.Error = "no community matched"
	}
	return res
}

func asString(v gosnmp.SnmpPDU) string {
	switch x := v.Value.(type) {
	case string:
		return x
	case []byte:
		return string(x)
	default:
		return fmt.Sprintf("%v", v.Value)
	}
}

func portU16(s string) uint16 {
	var n int
	for _, c := range s {
		if c < '0' || c > '9' {
			return 161
		}
		n = n*10 + int(c-'0')
	}
	if n <= 0 || n > 65535 {
		return 161
	}
	return uint16(n)
}
