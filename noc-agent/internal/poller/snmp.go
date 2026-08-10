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
	"strings"
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

// ApplyConfig hot-swaps the SNMP configuration at runtime. Used when the
// backend pushes an updated target list via the server.welcome frame.
// Safe to call concurrently with Run(); the next poll cycle picks up the
// new targets/interval automatically.
func (p *Poller) ApplyConfig(cfg config.SNMPConfig) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cfg = cfg
	p.log.Info("snmp config hot-swapped",
		"enabled", fmt.Sprintf("%t", cfg.Enabled),
		"targets", fmt.Sprintf("%d", len(cfg.Targets)),
		"interval", cfg.Interval.String(),
	)
}

// snapshot returns a copy of the current config under the mutex.
func (p *Poller) snapshot() config.SNMPConfig {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.cfg
}

// LastPollAt returns the timestamp of the last completed cycle.
func (p *Poller) LastPollAt() time.Time {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.lastPollAt
}

// Run blocks until ctx done, polling every cfg.Interval.
// The configuration is re-read at the start of each cycle so that
// ApplyConfig() takes effect on the next iteration without restart.
// If the config is disabled the loop keeps spinning and waits for a hot-
// swap to enable it (interval falls back to 60 s for the wait tick).
func (p *Poller) Run(ctx context.Context) {
	for {
		cfg := p.snapshot()
		interval := cfg.Interval
		if interval <= 0 {
			interval = 60 * time.Second
		}
		if cfg.Enabled && len(cfg.Targets) > 0 {
			p.runOnce(ctx)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
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
	cfg := p.snapshot()
	if len(cfg.Targets) == 0 {
		return nil
	}
	results := make([]proto.SNMPPollResult, 0, len(cfg.Targets))
	var wg sync.WaitGroup
	mu := sync.Mutex{}
	// v4.23 Zabbix-Proxy-style worker pool: poller count is now
	// configurable (cfg.Pollers). 0/negative falls back to 16 (legacy
	// default) — never go above 128 to avoid socket exhaustion on
	// small Windows hosts.
	pollers := cfg.Pollers
	if pollers <= 0 {
		pollers = 16
	}
	if pollers > 128 {
		pollers = 128
	}
	sem := make(chan struct{}, pollers)
	for _, t := range cfg.Targets {
		t := t
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			// v2026-06-02: pollTarget riceve l'intero SNMPTarget
			// (con ExtraOIDs del profilo). Senza ExtraOIDs ricade
			// nei 4 OID base (compat con PollOne/force_snmp_poll).
			res := p.pollTarget(ctx, t)
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
	return p.pollTarget(ctx, config.SNMPTarget{IP: ip, Community: community})
}

func (p *Poller) pollTarget(ctx context.Context, t config.SNMPTarget) proto.SNMPPollResult {
	ip := t.IP
	community := t.Community
	res := proto.SNMPPollResult{Target: ip, OIDs: map[string]string{}}
	cfg := p.snapshot()
	communities := cfg.Communities
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

	timeout := cfg.Timeout
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
			Retries:   cfg.Retries,
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
		// v2026-06-02 fix critico: polla anche gli ExtraOIDs del profilo
		// (CPU, memoria, temperatura, supplies stampante, ecc.). Senza
		// questi il backend non ha metriche da mostrare e la UI rimane
		// con valori 0 anche se il device e' SNMP-attivo. Eseguiti in
		// batch da 20 OID per non sforare il packet size SNMP.
		if len(t.ExtraOIDs) > 0 {
			// Ricrea connessione (la precedente e' stata chiusa)
			gExtra := &gosnmp.GoSNMP{
				Target:    host,
				Port:      portU16(port),
				Community: c,
				Version:   gosnmp.Version2c,
				Timeout:   timeout,
				Retries:   cfg.Retries,
			}
			if errC := gExtra.Connect(); errC == nil {
				oidList := make([]string, 0, len(t.ExtraOIDs))
				nameByOID := make(map[string]string, len(t.ExtraOIDs))
				for name, oid := range t.ExtraOIDs {
					if oid == "" {
						continue
					}
					oidList = append(oidList, oid)
					nameByOID["."+oid] = name
				}
				// Batch da 20 OID per stare sotto la MTU SNMP standard
				const batchSize = 20
				for i := 0; i < len(oidList); i += batchSize {
					end := i + batchSize
					if end > len(oidList) {
						end = len(oidList)
					}
					ePkt, errE := gExtra.Get(oidList[i:end])
					if errE != nil {
						p.log.Warn("snmp extra oids batch failed",
							"ip", ip, "batch_start", fmt.Sprintf("%d", i),
							"err", errE.Error())
						continue
					}
					for _, v := range ePkt.Variables {
						if v.Type == gosnmp.NoSuchObject ||
							v.Type == gosnmp.NoSuchInstance ||
							v.Type == gosnmp.EndOfMibView {
							continue
						}
						label := nameByOID[v.Name]
						if label == "" {
							label = v.Name
						}
						res.OIDs[label] = asString(v)
					}
				}
				// v4.30: WALK fallback per OID a TABELLA (es. H3C hh3cEntityExt*:
				// CPU/mem/temperatura/ventole/PSU). Il GET sulla base-colonna
				// risponde NoSuchInstance; per ogni OID non risolto dal GET
				// proviamo un BulkWalk ed emettiamo i valori per-indice come
				// "name.<index>". Il backend li raggruppa in vendor_metrics.
				for wName, wOID := range t.ExtraOIDs {
					if wOID == "" {
						continue
					}
					if _, ok := res.OIDs[wName]; ok {
						continue // gia' risolto via GET (scalare)
					}
					pdus, werr := gExtra.BulkWalkAll(wOID)
					if werr != nil || len(pdus) == 0 {
						continue
					}
					base := strings.TrimPrefix(wOID, ".")
					for _, v := range pdus {
						if v.Type == gosnmp.NoSuchObject || v.Type == gosnmp.NoSuchInstance || v.Type == gosnmp.EndOfMibView {
							continue
						}
						vn := strings.TrimPrefix(v.Name, ".")
						idx := strings.TrimPrefix(strings.TrimPrefix(vn, base), ".")
						if idx == "" || idx == "0" {
							res.OIDs[wName] = asString(v)
						} else {
							res.OIDs[wName+"."+idx] = asString(v)
						}
					}
				}
				_ = gExtra.Conn.Close()
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
