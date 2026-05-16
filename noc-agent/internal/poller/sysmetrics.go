// Package poller — SysMetrics polling loop.
//
// SysMetricsPoller samples the agent host's own resources (CPU, RAM,
// Disks, network, uptime) on a timer and emits a SysMetricsResult event
// upstream. This is the NATIVE replacement for SNMP-based Windows
// server monitoring: dove l'agent gira direttamente sul server, non c'e'
// motivo di interrogarlo via SNMP — gopsutil legge i WMI counters
// localmente (windows) o /proc (linux), zero rete, latenza < 100ms.
//
// Architettura: identico pattern di SNMP/Ping poller — config hot-swap
// via ApplyConfig, run loop con ticker, callback on(proto.SysMetricsResult).
package poller

import (
	"context"
	"fmt"
	"os"
	"runtime"
	"sync"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/load"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"

	"github.com/86bit/noc-agent/internal/config"
	"github.com/86bit/noc-agent/internal/logging"
	"github.com/86bit/noc-agent/pkg/proto"
)

// SysMetricsPoller samples host resources periodically.
type SysMetricsPoller struct {
	log *logging.Logger
	on  func(proto.SysMetricsResult)

	mu       sync.Mutex
	cfg      config.SysMetricsConfig
	lastTick time.Time
}

// NewSysMetrics creates a poller with the given cfg.
func NewSysMetrics(cfg config.SysMetricsConfig, log *logging.Logger, on func(proto.SysMetricsResult)) *SysMetricsPoller {
	return &SysMetricsPoller{cfg: cfg, log: log.With("sysmetrics"), on: on}
}

// ApplyConfig hot-swaps the cfg (enabled / interval) at runtime.
func (p *SysMetricsPoller) ApplyConfig(cfg config.SysMetricsConfig) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cfg = cfg
	p.log.Info("sysmetrics config hot-swapped",
		"enabled", fmt.Sprintf("%t", cfg.Enabled),
		"interval", cfg.Interval.String(),
	)
}

// LastTick returns the last sample timestamp.
func (p *SysMetricsPoller) LastTick() time.Time {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.lastTick
}

// Run blocks until ctx is cancelled. Emits a SysMetricsResult every cfg.Interval.
func (p *SysMetricsPoller) Run(ctx context.Context) {
	p.mu.Lock()
	cfg := p.cfg
	p.mu.Unlock()
	if !cfg.Enabled {
		p.log.Info("sysmetrics disabled — not starting")
		return
	}
	interval := cfg.Interval
	if interval <= 0 {
		interval = 60 * time.Second
	}
	// Primo sample subito (no warm-up wait di 60s)
	p.tick(ctx)
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			// re-read cfg ogni tick (hot-swap)
			p.mu.Lock()
			cfg = p.cfg
			p.mu.Unlock()
			if !cfg.Enabled {
				continue
			}
			p.tick(ctx)
		}
	}
}

func (p *SysMetricsPoller) tick(ctx context.Context) {
	res := sampleSysMetrics(ctx, p.log)
	p.mu.Lock()
	p.lastTick = time.Now()
	p.mu.Unlock()
	if p.on != nil {
		p.on(res)
	}
}

// sampleSysMetrics collects one snapshot. Errors on individual collectors
// are logged but never abort the whole sample — gopsutil sometimes fails
// transiently on Windows (WMI provider restart) and we prefer partial data
// over no data.
func sampleSysMetrics(ctx context.Context, log *logging.Logger) proto.SysMetricsResult {
	now := time.Now().UTC()
	res := proto.SysMetricsResult{
		SampledAt: now,
		OS:        runtime.GOOS,
	}

	hostname, _ := os.Hostname()
	res.Hostname = hostname

	// Host info (uptime, boot time, platform string)
	if info, err := host.InfoWithContext(ctx); err == nil {
		res.Platform = info.Platform + " " + info.PlatformVersion
		res.UptimeSec = info.Uptime
		res.BootTime = time.Unix(int64(info.BootTime), 0).UTC()
		if info.Hostname != "" && res.Hostname == "" {
			res.Hostname = info.Hostname
		}
	} else {
		log.Warn("host.Info failed", "err", err.Error())
	}

	// CPU — 1 sec sample so we get a real average instantaneo
	if cpuPct, err := cpu.PercentWithContext(ctx, time.Second, false); err == nil && len(cpuPct) > 0 {
		res.CPUPercent = cpuPct[0]
	} else if err != nil {
		log.Warn("cpu.Percent failed", "err", err.Error())
	}
	res.CPUCores = runtime.NumCPU()
	if avg, err := load.AvgWithContext(ctx); err == nil && avg != nil {
		res.LoadAvg1 = avg.Load1
	}

	// Memoria
	if vm, err := mem.VirtualMemoryWithContext(ctx); err == nil && vm != nil {
		res.MemTotalMB = vm.Total / 1024 / 1024
		res.MemUsedMB = vm.Used / 1024 / 1024
		res.MemUsedPct = vm.UsedPercent
	} else if err != nil {
		log.Warn("mem.VirtualMemory failed", "err", err.Error())
	}
	if sw, err := mem.SwapMemoryWithContext(ctx); err == nil && sw != nil {
		res.SwapUsedMB = sw.Used / 1024 / 1024
		res.SwapUsedPct = sw.UsedPercent
	}

	// Disks — solo partizioni reali (skip loop devices, /proc bind mounts).
	if parts, err := disk.PartitionsWithContext(ctx, false); err == nil {
		for _, p := range parts {
			if usage, err := disk.UsageWithContext(ctx, p.Mountpoint); err == nil && usage != nil {
				// gopsutil su windows ritorna a volte total=0 per drive non pronti
				if usage.Total == 0 {
					continue
				}
				res.Disks = append(res.Disks, proto.SysMetricsDisk{
					Mount:   p.Mountpoint,
					FSType:  p.Fstype,
					TotalGB: float64(usage.Total) / (1 << 30),
					UsedGB:  float64(usage.Used) / (1 << 30),
					UsedPct: usage.UsedPercent,
				})
			}
		}
	}

	// Network (totale aggregato — il Center puo' calcolare il delta lato server)
	if ios, err := net.IOCountersWithContext(ctx, false); err == nil && len(ios) > 0 {
		res.NetTotalRX = ios[0].BytesRecv
		res.NetTotalTX = ios[0].BytesSent
	}

	// Process count (cheap, ottimo signal su Windows servers)
	if procs, err := process.PidsWithContext(ctx); err == nil {
		res.ProcCount = len(procs)
	}

	return res
}
