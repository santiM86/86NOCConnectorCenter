// Package poller — switch-ports collector.
//
// This module fills the gap that previously required the legacy PowerShell
// connector: it walks the SNMP interface table (ifTable / ifXTable) of every
// configured target whose profile is switch-like, and emits a
// proto.SwitchPortsReport upstream so the backend can populate the
// "Porte Switch" page (and the storm-based loop detection via pps).
//
// Scope v1 (solo porte): ifIndex, ifName/ifDescr/ifAlias, oper/admin status,
// speed, last-change, HC octet + unicast-packet counters (for rx/tx bps+pps
// computed from deltas between cycles). LLDP / bridge-FDB / PoE are out of
// scope for this first version.
package poller

import (
	"context"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gosnmp/gosnmp"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

// ifTable / ifXTable OIDs (roots for BulkWalk).
const (
	oidIfDescr          = "1.3.6.1.2.1.2.2.1.2"
	oidIfSpeed          = "1.3.6.1.2.1.2.2.1.5"
	oidIfAdminStatus    = "1.3.6.1.2.1.2.2.1.7"
	oidIfOperStatus     = "1.3.6.1.2.1.2.2.1.8"
	oidIfLastChange     = "1.3.6.1.2.1.2.2.1.9"
	oidIfInOctets       = "1.3.6.1.2.1.2.2.1.10"
	oidIfOutOctets      = "1.3.6.1.2.1.2.2.1.16"
	oidIfName           = "1.3.6.1.2.1.31.1.1.1.1"
	oidIfHCInOctets     = "1.3.6.1.2.1.31.1.1.1.6"
	oidIfHCInUcastPkts  = "1.3.6.1.2.1.31.1.1.1.7"
	oidIfHCOutOctets    = "1.3.6.1.2.1.31.1.1.1.10"
	oidIfHCOutUcastPkts = "1.3.6.1.2.1.31.1.1.1.11"
	oidIfHighSpeed      = "1.3.6.1.2.1.31.1.1.1.15"
	oidIfAlias          = "1.3.6.1.2.1.31.1.1.1.18"
)

// switchProfiles are the device profiles for which we collect the port table.
var switchProfiles = map[string]bool{
	"switch": true, "router": true, "firewall": true, "gateway": true,
}

// portCounters holds the previous cycle's raw counters for rate computation.
type portCounters struct {
	inOctets  uint64
	outOctets uint64
	inPkts    uint64
	outPkts   uint64
	at        time.Time
}

// PortsPoller walks the ifTable of switch-profile targets on an interval.
type PortsPoller struct {
	log  *logging.Logger
	on   func(proto.SwitchPortsReport)
	tick func()

	mu       sync.Mutex
	cfg      config.SNMPConfig
	interval time.Duration
	prev     map[string]map[int]portCounters // switchIP -> ifIndex -> counters
}

// NewPorts builds the switch-ports poller. It reuses the SNMP target list.
// `tick` is called once per cycle (even when no switch is present) to keep the
// health reporter from flagging the module as stuck on switch-less clients.
func NewPorts(cfg config.SNMPConfig, log *logging.Logger, on func(proto.SwitchPortsReport), tick func()) *PortsPoller {
	return &PortsPoller{
		log:      log.With("snmpports"),
		on:       on,
		tick:     tick,
		cfg:      cfg,
		interval: clampPortsInterval(cfg.Interval),
		prev:     map[string]map[int]portCounters{},
	}
}

// ApplyConfig hot-swaps the target list (shares the SNMP config).
func (p *PortsPoller) ApplyConfig(cfg config.SNMPConfig) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cfg = cfg
	p.interval = clampPortsInterval(cfg.Interval)
}

func clampPortsInterval(d time.Duration) time.Duration {
	// Slower than the basic SNMP poll: the ifTable walk is heavier. Floor 60s,
	// ceiling 10m, default 120s.
	if d <= 0 {
		return 120 * time.Second
	}
	if d < 60*time.Second {
		return 60 * time.Second
	}
	if d > 10*time.Minute {
		return 10 * time.Minute
	}
	return d
}

func (p *PortsPoller) snapshot() (config.SNMPConfig, time.Duration) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.cfg, p.interval
}

// Run blocks until ctx done, collecting every interval.
func (p *PortsPoller) Run(ctx context.Context) {
	for {
		cfg, interval := p.snapshot()
		if cfg.Enabled {
			p.runOnce(ctx, cfg)
		}
		if p.tick != nil {
			p.tick()
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}
	}
}

func (p *PortsPoller) runOnce(ctx context.Context, cfg config.SNMPConfig) {
	switches := make([]proto.SwitchInfo, 0)
	for _, t := range cfg.Targets {
		if t.IP == "" || !switchProfiles[strings.ToLower(t.Profile)] {
			continue
		}
		ports := p.walkOne(ctx, cfg, t)
		if len(ports) == 0 {
			continue
		}
		switches = append(switches, proto.SwitchInfo{LocalIP: hostOnly(t.IP), Ports: ports})
	}
	if len(switches) == 0 {
		return
	}
	if p.on != nil {
		p.on(proto.SwitchPortsReport{Switches: switches})
	}
	p.log.Info("switch ports collected", "switches", strconv.Itoa(len(switches)))
}

// walkOne walks the ifTable/ifXTable of a single switch and returns its ports.
func (p *PortsPoller) walkOne(ctx context.Context, cfg config.SNMPConfig, t config.SNMPTarget) []proto.SwitchPortInfo {
	communities := cfg.Communities
	if t.Community != "" {
		communities = append([]string{t.Community}, communities...)
	}
	if len(communities) == 0 {
		communities = []string{"public"}
	}
	host, port := splitHostPort(t.IP)
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = 3 * time.Second
	}

	for _, c := range communities {
		g := &gosnmp.GoSNMP{
			Target:    host,
			Port:      portU16(port),
			Community: c,
			Version:   gosnmp.Version2c,
			Timeout:   timeout,
			Retries:   cfg.Retries,
			MaxOids:   gosnmp.MaxOids,
		}
		if err := g.Connect(); err != nil {
			continue
		}
		// ifName is the first mandatory walk; if it fails, the community is
		// wrong or the device has no ifXTable → try next community.
		names, err := walkStr(g, oidIfName)
		if err != nil || len(names) == 0 {
			// Fallback to ifDescr as the primary presence signal.
			names, err = walkStr(g, oidIfDescr)
			if err != nil || len(names) == 0 {
				_ = g.Conn.Close()
				continue
			}
		}
		descrs, _ := walkStr(g, oidIfDescr)
		aliases, _ := walkStr(g, oidIfAlias)
		opers, _ := walkInt(g, oidIfOperStatus)
		admins, _ := walkInt(g, oidIfAdminStatus)
		speeds, _ := walkUint(g, oidIfSpeed)
		hiSpeeds, _ := walkUint(g, oidIfHighSpeed)
		lastCh, _ := walkUint(g, oidIfLastChange)
		inOct, _ := walkUint(g, oidIfHCInOctets)
		if len(inOct) == 0 {
			inOct, _ = walkUint(g, oidIfInOctets)
		}
		outOct, _ := walkUint(g, oidIfHCOutOctets)
		if len(outOct) == 0 {
			outOct, _ = walkUint(g, oidIfOutOctets)
		}
		inPkts, _ := walkUint(g, oidIfHCInUcastPkts)
		outPkts, _ := walkUint(g, oidIfHCOutUcastPkts)
		_ = g.Conn.Close()

		swIP := hostOnly(t.IP)
		now := time.Now().UTC()
		p.mu.Lock()
		prevPorts := p.prev[swIP]
		if prevPorts == nil {
			prevPorts = map[int]portCounters{}
		}
		newPorts := map[int]portCounters{}
		p.mu.Unlock()

		ports := make([]proto.SwitchPortInfo, 0, len(names))
		for idx, nm := range names {
			name := strings.TrimSpace(nm)
			if name == "" {
				name = strings.TrimSpace(descrs[idx])
			}
			speed := 0
			if hs := hiSpeeds[idx]; hs > 0 {
				speed = int(hs) // ifHighSpeed already in Mbps
			} else if s := speeds[idx]; s > 0 {
				speed = int(s / 1000000) // ifSpeed in bps
			}
			pi := proto.SwitchPortInfo{
				Idx:         idx,
				Name:        name,
				Descr:       strings.TrimSpace(descrs[idx]),
				Alias:       strings.TrimSpace(aliases[idx]),
				Oper:        opers[idx],
				Admin:       admins[idx],
				SpeedMbps:   speed,
				LastChangeS: int64(lastCh[idx] / 100), // TimeTicks (1/100s) → seconds
				InOctets:    strconv.FormatUint(inOct[idx], 10),
				OutOctets:   strconv.FormatUint(outOct[idx], 10),
			}
			// Rate computation from previous cycle.
			cur := portCounters{
				inOctets: inOct[idx], outOctets: outOct[idx],
				inPkts: inPkts[idx], outPkts: outPkts[idx], at: now,
			}
			if pc, ok := prevPorts[idx]; ok {
				dt := now.Sub(pc.at).Seconds()
				if dt >= 1 {
					pi.RxBps = rate(cur.inOctets, pc.inOctets, dt) * 8
					pi.TxBps = rate(cur.outOctets, pc.outOctets, dt) * 8
					pi.RxPps = rate(cur.inPkts, pc.inPkts, dt)
					pi.TxPps = rate(cur.outPkts, pc.outPkts, dt)
				}
			}
			newPorts[idx] = cur
			ports = append(ports, pi)
		}

		p.mu.Lock()
		p.prev[swIP] = newPorts
		p.mu.Unlock()
		return ports
	}
	return nil
}

// rate returns per-second delta, guarding counter wraps/resets (returns 0).
func rate(cur, prev uint64, dt float64) int64 {
	if cur < prev || dt <= 0 {
		return 0
	}
	return int64(float64(cur-prev) / dt)
}

// ---- SNMP walk helpers (index = last OID sub-identifier) ----

func lastIndex(name string) (int, bool) {
	dot := strings.LastIndex(name, ".")
	if dot < 0 || dot == len(name)-1 {
		return 0, false
	}
	n, err := strconv.Atoi(name[dot+1:])
	if err != nil {
		return 0, false
	}
	return n, true
}

func walkStr(g *gosnmp.GoSNMP, root string) (map[int]string, error) {
	out := map[int]string{}
	pdus, err := g.BulkWalkAll(root)
	if err != nil {
		return out, err
	}
	for _, v := range pdus {
		idx, ok := lastIndex(v.Name)
		if !ok {
			continue
		}
		switch x := v.Value.(type) {
		case string:
			out[idx] = x
		case []byte:
			out[idx] = string(x)
		}
	}
	return out, nil
}

func walkInt(g *gosnmp.GoSNMP, root string) (map[int]int, error) {
	out := map[int]int{}
	pdus, err := g.BulkWalkAll(root)
	if err != nil {
		return out, err
	}
	for _, v := range pdus {
		idx, ok := lastIndex(v.Name)
		if !ok {
			continue
		}
		out[idx] = int(gosnmp.ToBigInt(v.Value).Int64())
	}
	return out, nil
}

func walkUint(g *gosnmp.GoSNMP, root string) (map[int]uint64, error) {
	out := map[int]uint64{}
	pdus, err := g.BulkWalkAll(root)
	if err != nil {
		return out, err
	}
	for _, v := range pdus {
		idx, ok := lastIndex(v.Name)
		if !ok {
			continue
		}
		out[idx] = gosnmp.ToBigInt(v.Value).Uint64()
	}
	return out, nil
}

func splitHostPort(ip string) (string, string) {
	if h, p, err := net.SplitHostPort(ip); err == nil {
		return h, p
	}
	return ip, "161"
}

func hostOnly(ip string) string {
	h, _ := splitHostPort(ip)
	return h
}
