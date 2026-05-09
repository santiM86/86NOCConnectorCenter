// Package health collects per-process telemetry (uptime, goroutines,
// memory, CPU) used to populate proto.AgentHeartbeat. It also implements
// a simple module liveness map: every long-running worker calls Tick()
// periodically; the reporter flags a module "stuck" if it has not ticked
// within its declared deadline.
package health

import (
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"

	"github.com/86bit/noc-agent/pkg/proto"
)

type module struct {
	last     time.Time
	deadline time.Duration
}

// Reporter is the agent-wide health tracker.
type Reporter struct {
	bootedAt time.Time

	mu      sync.Mutex
	modules map[string]*module

	errors atomic.Uint64
	last5  []errStamp

	lastScanAt time.Time
	lastPollAt time.Time
}

type errStamp struct{ at time.Time }

// New creates a Reporter and pre-warms the CPU stats channel so the first
// snapshot returns a sensible value.
func New() *Reporter {
	_, _ = cpu.Percent(0, false) // prime
	return &Reporter{
		bootedAt: time.Now().UTC(),
		modules:  map[string]*module{},
	}
}

// Register declares a module that will tick periodically with the given
// deadline (e.g. 2x the worker's tick interval).
func (r *Reporter) Register(name string, deadline time.Duration) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.modules[name] = &module{last: time.Now().UTC(), deadline: deadline}
}

// Tick marks a module as alive right now.
func (r *Reporter) Tick(name string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if m, ok := r.modules[name]; ok {
		m.last = time.Now().UTC()
	}
}

// RecordError increments the error counter and records its timestamp.
func (r *Reporter) RecordError() {
	r.errors.Add(1)
	r.mu.Lock()
	r.last5 = append(r.last5, errStamp{at: time.Now().UTC()})
	cutoff := time.Now().UTC().Add(-5 * time.Minute)
	for len(r.last5) > 0 && r.last5[0].at.Before(cutoff) {
		r.last5 = r.last5[1:]
	}
	r.mu.Unlock()
}

// SetLastScan / SetLastPoll record cycle completion timestamps.
func (r *Reporter) SetLastScan(t time.Time) {
	r.mu.Lock()
	r.lastScanAt = t
	r.mu.Unlock()
}
func (r *Reporter) SetLastPoll(t time.Time) {
	r.mu.Lock()
	r.lastPollAt = t
	r.mu.Unlock()
}

// Snapshot returns a populated AgentHeartbeat ready to ship.
func (r *Reporter) Snapshot() proto.AgentHeartbeat {
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	cpuPct := 0.0
	if v, err := cpu.Percent(0, false); err == nil && len(v) > 0 {
		cpuPct = v[0]
	}

	r.mu.Lock()
	alive := []string{}
	stuck := []string{}
	now := time.Now().UTC()
	for name, m := range r.modules {
		if now.Sub(m.last) > m.deadline {
			stuck = append(stuck, name)
		} else {
			alive = append(alive, name)
		}
	}
	cutoff := now.Add(-5 * time.Minute)
	errs := uint64(0)
	for _, e := range r.last5 {
		if e.at.After(cutoff) {
			errs++
		}
	}
	var lastScan, lastPoll *time.Time
	if !r.lastScanAt.IsZero() {
		ls := r.lastScanAt
		lastScan = &ls
	}
	if !r.lastPollAt.IsZero() {
		lp := r.lastPollAt
		lastPoll = &lp
	}
	r.mu.Unlock()

	return proto.AgentHeartbeat{
		Uptime:         time.Since(r.bootedAt),
		Goroutines:     runtime.NumGoroutine(),
		MemAllocBytes:  ms.Alloc,
		CPUPercent:     cpuPct,
		ErrorsLast5min: errs,
		ModulesAlive:   alive,
		ModulesStuck:   stuck,
		LastScanAt:     lastScan,
		LastPollAt:     lastPoll,
	}
}
