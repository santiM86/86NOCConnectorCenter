// Package discovery coordinates LAN endpoint discovery via multiple
// backends (ARP, mDNS, future LLDP/SNMP-CAM). Each backend implements
// the Source interface; the manager runs them in parallel on a tick and
// merges results into a deduped batch keyed by IP.
package discovery

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
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

	// cachePath is the disk location where the discovery snapshot is
	// persisted after every successful sweep. The Wails desktop UI reads
	// this file directly to render the "Dispositivi rilevati" tab even
	// when the Center is unreachable. Empty = persistence disabled.
	cachePath string
	// forceTriggerPath is the optional file path watched on each tick:
	// if it exists, the manager treats it as an external "re-scan now"
	// trigger (used by the Wails UI to request an immediate sweep
	// without exposing a loopback socket). The file is deleted right
	// after being honored so the trigger is one-shot.
	forceTriggerPath string

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

// Run blocks until ctx is done, sweeping every tick. A secondary 3s
// poll watches forceTriggerPath: if the Wails UI drops the trigger
// file the next sweep is fired immediately (one-shot, file removed).
func (m *Manager) Run(ctx context.Context) {
	if m.tick <= 0 {
		m.tick = 5 * time.Minute
	}
	t := time.NewTicker(m.tick)
	defer t.Stop()
	trig := time.NewTicker(3 * time.Second)
	defer trig.Stop()
	m.runOnce(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			m.runOnce(ctx)
		case <-trig.C:
			if m.consumeForceTrigger() {
				m.log.Info("force-trigger consumed: running discovery sweep")
				m.runOnce(ctx)
			}
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
	// Persist on disk so the Wails UI can read the snapshot directly.
	// Best-effort: log the error but never fail the sweep — the in-memory
	// state is still authoritative for the next tick.
	if err := m.WriteCache(); err != nil {
		m.log.Warn("discovery cache write failed", "err", err.Error())
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

// SetCachePath configures the on-disk snapshot location. Call ONCE at
// startup before Run(). Empty string disables persistence.
func (m *Manager) SetCachePath(p string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.cachePath = p
}

// SetForceTriggerPath configures the path watched on each tick for an
// external "re-scan now" file flag. Empty disables.
func (m *Manager) SetForceTriggerPath(p string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.forceTriggerPath = p
}

// Snapshot returns a copy of all endpoints currently tracked in memory,
// sorted by IPv4 ascending. Safe for concurrent use.
func (m *Manager) Snapshot() []proto.DiscoveredEndpoint {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]proto.DiscoveredEndpoint, 0, len(m.endpoints))
	for _, ep := range m.endpoints {
		out = append(out, ep)
	}
	sort.Slice(out, func(i, j int) bool { return ipLess(out[i].IP, out[j].IP) })
	return out
}

// snapshotPayload is the on-disk format of discovery_cache.json. We
// keep it explicit (vs. dumping the internal struct) so the file is
// self-describing for downstream tools and we can evolve the in-memory
// representation without breaking readers.
type snapshotPayload struct {
	Version    int                          `json:"version"`
	WrittenAt  string                       `json:"written_at"`
	LastScanAt string                       `json:"last_scan_at,omitempty"`
	Count      int                          `json:"count"`
	Endpoints  []proto.DiscoveredEndpoint   `json:"endpoints"`
}

// WriteCache atomically writes the current snapshot to m.cachePath.
// No-op if cachePath is empty. Returns nil on success or wraps the
// first I/O error encountered. Atomicity: writes to a temp file in
// the same directory and renames over the target.
func (m *Manager) WriteCache() error {
	m.mu.Lock()
	path := m.cachePath
	lastScan := m.lastScanAt
	eps := make([]proto.DiscoveredEndpoint, 0, len(m.endpoints))
	for _, ep := range m.endpoints {
		eps = append(eps, ep)
	}
	m.mu.Unlock()
	if path == "" {
		return nil
	}
	sort.Slice(eps, func(i, j int) bool { return ipLess(eps[i].IP, eps[j].IP) })
	payload := snapshotPayload{
		Version:   1,
		WrittenAt: time.Now().UTC().Format(time.RFC3339),
		Count:     len(eps),
		Endpoints: eps,
	}
	if !lastScan.IsZero() {
		payload.LastScanAt = lastScan.UTC().Format(time.RFC3339)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(&payload, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadCache repopulates the in-memory endpoint map from a snapshot file
// written by a previous run. Used at agent startup so the Wails UI is
// not empty for the first 5 minutes of a fresh process. Stale entries
// (older than retainAfter) are dropped at load time.
func (m *Manager) LoadCache() error {
	m.mu.Lock()
	path := m.cachePath
	retain := m.retainAfter
	m.mu.Unlock()
	if path == "" {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	var payload snapshotPayload
	if err := json.Unmarshal(data, &payload); err != nil {
		return err
	}
	now := time.Now().UTC()
	cutoff := now.Add(-retain)
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, ep := range payload.Endpoints {
		if ep.IP == "" {
			continue
		}
		if retain > 0 && !ep.LastSeenAt.IsZero() && ep.LastSeenAt.Before(cutoff) {
			continue
		}
		m.endpoints[ep.IP] = ep
	}
	return nil
}

// consumeForceTrigger returns true once if the trigger file exists; in
// that case the file is removed so the trigger is one-shot. Safe to
// call from runOnce without locking m.mu (the file is the lock).
func (m *Manager) consumeForceTrigger() bool {
	m.mu.Lock()
	path := m.forceTriggerPath
	m.mu.Unlock()
	if path == "" {
		return false
	}
	if _, err := os.Stat(path); err != nil {
		return false
	}
	_ = os.Remove(path)
	return true
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
