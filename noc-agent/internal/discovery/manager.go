// Package discovery coordinates LAN endpoint discovery via multiple
// backends (ARP, mDNS, future LLDP/SNMP-CAM). Each backend implements
// the Source interface; the manager runs them in parallel on a tick and
// merges results into a deduped batch keyed by IP.
package discovery

import (
	"context"
	"net"
	"sort"
	"sync"
	"time"

	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

// Source is one discovery backend (ARP, mDNS, ...).
type Source interface {
	Name() string
	Scan(ctx context.Context) ([]proto.DiscoveredEndpoint, error)
}

// Manager runs registered Sources on a tick and exposes the merged batch.
type Manager struct {
	log     *logging.Logger
	sources []Source

	mu        sync.Mutex
	endpoints map[string]proto.DiscoveredEndpoint // keyed by IP

	lastScanAt time.Time
	tick       time.Duration
	// retainAfter is how long an IP that we have not seen in any source
	// scan is kept in the merge cache. Beyond this it is pruned to keep
	// memory bounded on long-running agents.
	retainAfter time.Duration

	onBatch func([]proto.DiscoveredEndpoint)
}

// NewManager wires sources and registers a callback fired at the end of
// every successful sweep.
func NewManager(log *logging.Logger, tick time.Duration, sources []Source, onBatch func([]proto.DiscoveredEndpoint)) *Manager {
	return &Manager{
		log:         log.With("discovery"),
		sources:     sources,
		endpoints:   make(map[string]proto.DiscoveredEndpoint),
		tick:        tick,
		retainAfter: 60 * time.Minute,
		onBatch:     onBatch,
	}
}

// LastScanAt returns the wall-clock of the last completed sweep.
func (m *Manager) LastScanAt() time.Time {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.lastScanAt
}

// ForceScan triggers a sweep immediately and returns the produced batch.
func (m *Manager) ForceScan(ctx context.Context) []proto.DiscoveredEndpoint {
	return m.runOnce(ctx)
}

// Run blocks until ctx is done, sweeping every tick.
func (m *Manager) Run(ctx context.Context) {
	if m.tick <= 0 {
		m.tick = 5 * time.Minute
	}
	t := time.NewTicker(m.tick)
	defer t.Stop()
	m.runOnce(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			m.runOnce(ctx)
		}
	}
}

func (m *Manager) runOnce(ctx context.Context) []proto.DiscoveredEndpoint {
	if len(m.sources) == 0 {
		return nil
	}
	scanCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	var wg sync.WaitGroup
	results := make([][]proto.DiscoveredEndpoint, len(m.sources))
	for i, s := range m.sources {
		i, s := i, s
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					m.log.Errorf("source %s panicked: %v", s.Name(), r)
				}
			}()
			eps, err := s.Scan(scanCtx)
			if err != nil {
				m.log.Warn("source error", "source", s.Name(), "err", err.Error())
				return
			}
			results[i] = eps
		}()
	}
	wg.Wait()

	merged := m.merge(results)
	// Reverse DNS (PTR) enrichment: fills Hostname for endpoints that
	// neither ARP nor mDNS could name. Bounded in time/concurrency by
	// ptrLookupTimeout and ptrWorkers — see ptr.go.
	merged = enrichPTR(scanCtx, merged)
	// NetBIOS NBNS enrichment: per gli host Windows risolve hostname
	// (es. "PC-MARCO") quando il DNS aziendale non ha PTR. Per molti PC
	// Windows e' l'UNICA via di risoluzione, quindi senza questo step
	// la lista dispositivi mostra "10.10.1.55" invece di "PC-MARCO" — vedi
	// internal/nbns/. Operazione cheap: UDP/137 con 200ms timeout per host.
	merged = enrichNBNS(scanCtx, merged)
	m.mu.Lock()
	m.lastScanAt = time.Now().UTC()
	m.mu.Unlock()

	if m.onBatch != nil && len(merged) > 0 {
		m.onBatch(merged)
	}
	m.log.Info("scan completed", "endpoints", itoa(len(merged)))
	return merged
}

func (m *Manager) merge(batches [][]proto.DiscoveredEndpoint) []proto.DiscoveredEndpoint {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now().UTC()
	for _, b := range batches {
		for _, ep := range b {
			if ep.IP == "" {
				continue
			}
			if existing, ok := m.endpoints[ep.IP]; ok {
				if ep.MAC == "" && existing.MAC != "" {
					ep.MAC = existing.MAC
				}
				if ep.Hostname == "" && existing.Hostname != "" {
					ep.Hostname = existing.Hostname
				}
				if ep.Vendor == "" && existing.Vendor != "" {
					ep.Vendor = existing.Vendor
				}
				ep.FirstSeenAt = existing.FirstSeenAt
			} else {
				ep.FirstSeenAt = now
			}
			ep.LastSeenAt = now
			m.endpoints[ep.IP] = ep
		}
	}
	// Prune endpoints not seen for longer than retainAfter so the merge
	// cache cannot grow without bound on a long-running agent.
	if m.retainAfter > 0 {
		cutoff := now.Add(-m.retainAfter)
		for ip, ep := range m.endpoints {
			if ep.LastSeenAt.Before(cutoff) {
				delete(m.endpoints, ip)
			}
		}
	}
	out := make([]proto.DiscoveredEndpoint, 0, len(m.endpoints))
	for _, ep := range m.endpoints {
		out = append(out, ep)
	}
	sort.Slice(out, func(i, j int) bool { return ipLess(out[i].IP, out[j].IP) })
	return out
}

func ipLess(a, b string) bool {
	ipA := net.ParseIP(a).To4()
	ipB := net.ParseIP(b).To4()
	if ipA == nil || ipB == nil {
		return a < b
	}
	for i := 0; i < 4; i++ {
		if ipA[i] != ipB[i] {
			return ipA[i] < ipB[i]
		}
	}
	return false
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}
