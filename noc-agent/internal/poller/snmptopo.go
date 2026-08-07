// Package poller — switch topology collector (LLDP neighbors + bridge FDB).
//
// Companion to snmpports.go. Walks, for every switch-profile target:
//   - LLDP-MIB (lldpRemTable + lldpLocPortTable + lldpRemManAddrTable) to
//     discover neighbor switches/APs/phones and the local/remote port ids.
//   - Bridge-MIB / Q-Bridge FDB (dot1q/dot1d) to build the MAC address table,
//     resolving each bridge port to its ifIndex so the backend can map a MAC
//     to a physical port ("Connesso a").
//
// Emits proto.SwitchTopoReport upstream. Heavier and slower than the ports
// walk, so it runs on a longer interval.
package poller

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gosnmp/gosnmp"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

const (
	// LLDP-MIB local port table (index: lldpLocPortNum)
	oidLldpLocPortID   = "1.0.8802.1.1.2.1.3.7.1.3"
	oidLldpLocPortDesc = "1.0.8802.1.1.2.1.3.7.1.4"
	// LLDP-MIB remote systems table (index: timeMark.localPortNum.remIndex)
	oidLldpRemChassisID = "1.0.8802.1.1.2.1.4.1.1.5"
	oidLldpRemPortID    = "1.0.8802.1.1.2.1.4.1.1.7"
	oidLldpRemPortDesc  = "1.0.8802.1.1.2.1.4.1.1.8"
	oidLldpRemSysName   = "1.0.8802.1.1.2.1.4.1.1.9"
	oidLldpRemSysDesc   = "1.0.8802.1.1.2.1.4.1.1.10"
	// LLDP remote management address (index encodes the remote mgmt IP)
	oidLldpRemManAddr = "1.0.8802.1.1.2.1.4.2.1.3"
	// Bridge-MIB
	oidDot1dBasePortIfIndex = "1.3.6.1.2.1.17.1.4.1.2" // bridgePort -> ifIndex
	oidDot1dTpFdbPort       = "1.3.6.1.2.1.17.4.3.1.2" // mac(6) -> bridgePort
	// Q-Bridge (VLAN aware)
	oidDot1qTpFdbPort = "1.3.6.1.2.1.17.7.1.2.2.1.2" // vlan.mac(6) -> bridgePort
)

// TopoPoller walks LLDP + FDB of switch-profile targets on an interval.
type TopoPoller struct {
	log  *logging.Logger
	on   func(proto.SwitchTopoReport)
	tick func()

	mu       sync.Mutex
	cfg      config.SNMPConfig
	interval time.Duration
}

// NewTopo builds the switch-topology poller (LLDP + FDB). Reuses the SNMP
// target list. `tick` keeps the health reporter happy on switch-less clients.
func NewTopo(cfg config.SNMPConfig, log *logging.Logger, on func(proto.SwitchTopoReport), tick func()) *TopoPoller {
	return &TopoPoller{
		log:      log.With("snmptopo"),
		on:       on,
		tick:     tick,
		cfg:      cfg,
		interval: clampTopoInterval(cfg.Interval),
	}
}

// ApplyConfig hot-swaps the target list.
func (p *TopoPoller) ApplyConfig(cfg config.SNMPConfig) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cfg = cfg
	p.interval = clampTopoInterval(cfg.Interval)
}

func clampTopoInterval(d time.Duration) time.Duration {
	// LLDP+FDB is the heaviest SNMP walk: floor 120s, default 300s, ceiling 15m.
	if d <= 0 {
		return 300 * time.Second
	}
	scaled := d * 2
	if scaled < 120*time.Second {
		return 120 * time.Second
	}
	if scaled > 15*time.Minute {
		return 15 * time.Minute
	}
	return scaled
}

func (p *TopoPoller) snapshot() (config.SNMPConfig, time.Duration) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.cfg, p.interval
}

// Run blocks until ctx done, collecting every interval.
func (p *TopoPoller) Run(ctx context.Context) {
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

func (p *TopoPoller) runOnce(ctx context.Context, cfg config.SNMPConfig) {
	switches := make([]proto.SwitchTopoInfo, 0)
	for _, t := range cfg.Targets {
		if t.IP == "" || !switchProfiles[strings.ToLower(t.Profile)] {
			continue
		}
		info := p.walkOne(ctx, cfg, t)
		if info == nil || (len(info.Neighbors) == 0 && len(info.FDB) == 0) {
			continue
		}
		switches = append(switches, *info)
	}
	if len(switches) == 0 {
		return
	}
	if p.on != nil {
		p.on(proto.SwitchTopoReport{Switches: switches})
	}
	p.log.Info("switch topology collected", "switches", strconv.Itoa(len(switches)))
}

func (p *TopoPoller) walkOne(ctx context.Context, cfg config.SNMPConfig, t config.SNMPTarget) *proto.SwitchTopoInfo {
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
		neighbors := p.walkLLDP(g)
		fdb := p.walkFDB(g)
		_ = g.Conn.Close()

		// If neither table returned anything, the community may be wrong or the
		// switch exposes nothing: try the next community before giving up.
		if len(neighbors) == 0 && len(fdb) == 0 {
			continue
		}
		return &proto.SwitchTopoInfo{
			LocalIP:   hostOnly(t.IP),
			Neighbors: neighbors,
			FDB:       fdb,
		}
	}
	return nil
}

// ---- LLDP ----

func (p *TopoPoller) walkLLDP(g *gosnmp.GoSNMP) []proto.LLDPNeighbor {
	// local port table: lldpLocPortNum -> id/desc
	locID, _ := walkStr(g, oidLldpLocPortID)
	locDesc, _ := walkStr(g, oidLldpLocPortDesc)

	chassis := walkSuffix(g, oidLldpRemChassisID)
	if len(chassis) == 0 {
		return nil
	}
	remPortID := walkSuffix(g, oidLldpRemPortID)
	remPortDesc := walkSuffix(g, oidLldpRemPortDesc)
	remSysName := walkSuffix(g, oidLldpRemSysName)
	remSysDesc := walkSuffix(g, oidLldpRemSysDesc)
	manAddr := walkManAddr(g, oidLldpRemManAddr) // key: timeMark.localPortNum.remIndex -> ip

	out := make([]proto.LLDPNeighbor, 0, len(chassis))
	for key := range chassis {
		parts := strings.Split(key, ".")
		localPortNum := 0
		if len(parts) >= 2 {
			localPortNum, _ = strconv.Atoi(parts[1])
		}
		n := proto.LLDPNeighbor{
			LocalPortID:     strings.TrimSpace(locID[localPortNum]),
			LocalPortDesc:   strings.TrimSpace(locDesc[localPortNum]),
			RemoteChassisID: fmtVal(chassis[key]),
			RemotePortID:    fmtVal(remPortID[key]),
			RemotePortDesc:  strings.TrimSpace(fmtVal(remPortDesc[key])),
			RemoteSysName:   strings.TrimSpace(fmtVal(remSysName[key])),
			RemoteSysDesc:   strings.TrimSpace(fmtVal(remSysDesc[key])),
			RemoteIP:        manAddr[manKeyPrefix(key)],
		}
		if n.RemoteSysName == "" && n.RemoteChassisID == "" {
			continue
		}
		out = append(out, n)
	}
	return out
}

// manKeyPrefix reduces a rem-table index (timeMark.localPortNum.remIndex) to
// the same 3-tuple prefix used to key the management-address map.
func manKeyPrefix(key string) string {
	parts := strings.Split(key, ".")
	if len(parts) >= 3 {
		return strings.Join(parts[:3], ".")
	}
	return key
}

// walkManAddr parses lldpRemManAddrTable. Its OID suffix is
// timeMark.localPortNum.remIndex.addrSubtype.addrLen.<addr bytes>. For IPv4
// (subtype 1, len 4) we extract the last 4 octets as the remote mgmt IP.
func walkManAddr(g *gosnmp.GoSNMP, root string) map[string]string {
	out := map[string]string{}
	pdus, err := g.BulkWalkAll(root)
	if err != nil {
		return out
	}
	for _, v := range pdus {
		suf := suffixAfter(v.Name, root)
		if suf == "" {
			continue
		}
		parts := strings.Split(suf, ".")
		// need at least: t.lp.ri.subtype.len.b1.b2.b3.b4  (>=9), subtype==1 ipv4
		if len(parts) < 9 || parts[3] != "1" {
			continue
		}
		key := strings.Join(parts[:3], ".")
		ip := strings.Join(parts[len(parts)-4:], ".")
		if _, ok := out[key]; !ok {
			out[key] = ip
		}
	}
	return out
}

// ---- FDB (bridge MAC table) ----

func (p *TopoPoller) walkFDB(g *gosnmp.GoSNMP) []proto.FDBEntry {
	// bridge port -> ifIndex
	basePort, _ := walkInt(g, oidDot1dBasePortIfIndex)

	out := make([]proto.FDBEntry, 0)
	seen := map[string]bool{}

	// Prefer Q-Bridge (VLAN aware): suffix = vlan.b1..b6
	q := walkSuffix(g, oidDot1qTpFdbPort)
	for suf, v := range q {
		parts := strings.Split(suf, ".")
		if len(parts) < 7 {
			continue
		}
		vlan, _ := strconv.Atoi(parts[0])
		mac := macFromOctets(parts[len(parts)-6:])
		if mac == "" {
			continue
		}
		bp := int(gosnmp.ToBigInt(v.Value).Int64())
		if bp <= 0 {
			continue
		}
		ifidx := bp
		if ix, ok := basePort[bp]; ok && ix > 0 {
			ifidx = ix
		}
		k := mac + "@" + strconv.Itoa(ifidx)
		if seen[k] {
			continue
		}
		seen[k] = true
		out = append(out, proto.FDBEntry{MAC: mac, Port: ifidx, VLAN: vlan})
	}

	// Fallback to classic dot1d if Q-Bridge is empty: suffix = b1..b6
	if len(out) == 0 {
		d := walkSuffix(g, oidDot1dTpFdbPort)
		for suf, v := range d {
			parts := strings.Split(suf, ".")
			if len(parts) < 6 {
				continue
			}
			mac := macFromOctets(parts[len(parts)-6:])
			if mac == "" {
				continue
			}
			bp := int(gosnmp.ToBigInt(v.Value).Int64())
			if bp <= 0 {
				continue
			}
			ifidx := bp
			if ix, ok := basePort[bp]; ok && ix > 0 {
				ifidx = ix
			}
			k := mac + "@" + strconv.Itoa(ifidx)
			if seen[k] {
				continue
			}
			seen[k] = true
			out = append(out, proto.FDBEntry{MAC: mac, Port: ifidx})
		}
	}
	return out
}

// ---- helpers (multi-component OID indices) ----

// suffixAfter returns the part of an OID name after `root.` (both may or may
// not carry a leading dot).
func suffixAfter(name, root string) string {
	name = strings.TrimPrefix(name, ".")
	r := strings.TrimPrefix(root, ".")
	if strings.HasPrefix(name, r+".") {
		return name[len(r)+1:]
	}
	return ""
}

// walkSuffix walks a subtree and keys every varbind by its full index suffix
// (everything after the root), preserving multi-component table indices.
func walkSuffix(g *gosnmp.GoSNMP, root string) map[string]gosnmp.SnmpPDU {
	out := map[string]gosnmp.SnmpPDU{}
	pdus, err := g.BulkWalkAll(root)
	if err != nil {
		return out
	}
	for _, v := range pdus {
		if s := suffixAfter(v.Name, root); s != "" {
			out[s] = v
		}
	}
	return out
}

// fmtVal renders an SNMP value: printable octet strings as-is, binary octet
// strings (e.g. a MAC chassis-id) as colon hex.
func fmtVal(v gosnmp.SnmpPDU) string {
	switch x := v.Value.(type) {
	case string:
		return x
	case []byte:
		printable := len(x) > 0
		for _, b := range x {
			if (b < 32 || b > 126) && b != 0 {
				printable = false
				break
			}
		}
		if printable {
			return strings.TrimRight(string(x), "\x00")
		}
		parts := make([]string, len(x))
		for i, b := range x {
			parts[i] = fmt.Sprintf("%02x", b)
		}
		return strings.Join(parts, ":")
	}
	return ""
}

// macFromOctets turns 6 decimal OID sub-identifiers into AA:BB:CC:DD:EE:FF.
func macFromOctets(parts []string) string {
	if len(parts) != 6 {
		return ""
	}
	b := make([]string, 6)
	for i, ptxt := range parts {
		n, err := strconv.Atoi(ptxt)
		if err != nil || n < 0 || n > 255 {
			return ""
		}
		b[i] = fmt.Sprintf("%02X", n)
	}
	mac := strings.Join(b, ":")
	if mac == "00:00:00:00:00:00" {
		return ""
	}
	return mac
}
