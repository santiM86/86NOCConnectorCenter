import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  ArrowUp, ArrowDown, Warning, CheckCircle, Lightning, Thermometer,
  Cpu, HardDrive, Fan, BatteryFull, WifiHigh, WifiSlash,
  ShieldCheck, Globe, ArrowsClockwise, FloppyDisk
} from "@phosphor-icons/react";

const formatBps = (bps) => {
  if (!bps && bps !== 0) return "N/A";
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(1)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(1)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(0)} Kbps`;
  return `${bps} bps`;
};

const formatSpeed = (bps) => {
  if (!bps) return "";
  if (bps >= 1e9) return `${bps / 1e9}G`;
  if (bps >= 1e8) return `${bps / 1e6}M`;
  if (bps >= 1e6) return `${bps / 1e6}M`;
  return `${bps / 1e3}K`;
};

const GaugeWidget = ({ label, value, max = 100, unit = "%", icon, thresholds = { warn: 70, crit: 90 } }) => {
  if (value == null) return null;
  const pct = Math.min((value / max) * 100, 100);
  const color = value >= thresholds.crit ? "var(--critical)" : value >= thresholds.warn ? "var(--medium)" : "var(--ok)";
  const bgColor = value >= thresholds.crit ? "var(--critical-bg)" : value >= thresholds.warn ? "rgba(234,179,8,0.1)" : "var(--low-bg)";
  return (
    <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid={`gauge-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          {icon}
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">{label}</p>
        </div>
        <p className="text-sm font-mono font-bold" style={{ color }}>{value}{unit}</p>
      </div>
      <div className="w-full h-2 rounded-full bg-[var(--bg-hover)] overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
};

const HwStatusBadge = ({ condition, label }) => {
  const map = {
    ok: { color: "text-[var(--ok)]", bg: "bg-[var(--low-bg)] border-[var(--low-border)]", text: "OK" },
    degraded: { color: "text-[var(--medium)]", bg: "bg-yellow-500/10 border-yellow-500/20", text: "DEGRADATO" },
    failed: { color: "text-[var(--critical)]", bg: "bg-[var(--critical-bg)] border-[var(--critical-border)]", text: "GUASTO" },
    other: { color: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)] border-[var(--bg-border)]", text: "N/D" },
    unknown: { color: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)] border-[var(--bg-border)]", text: "N/D" },
    predictiveFailure: { color: "text-[var(--medium)]", bg: "bg-yellow-500/10 border-yellow-500/20", text: "PRE-GUASTO" },
  };
  const s = map[condition] || map.unknown;
  return (
    <div className={`px-2 py-1.5 rounded-md border ${s.bg} flex items-center justify-between gap-2`}>
      <span className="text-[10px] text-[var(--text-muted)] truncate">{label}</span>
      <span className={`text-[10px] font-bold ${s.color}`}>{s.text}</span>
    </div>
  );
};

const PortTrafficRow = ({ port }) => {
  const hasTraffic = port.in_bps != null || port.out_bps != null;
  const hasErrors = (port.in_errors || 0) > 0 || (port.out_errors || 0) > 0;
  return (
    <div className={`grid grid-cols-12 gap-1 items-center px-2 py-1 text-[10px] font-mono rounded ${
      port.status === "up" ? "bg-[var(--low-bg)]/30" : port.status === "down" ? "bg-[var(--critical-bg)]/30" : "bg-[var(--bg-hover)]/30"
    }`}>
      <div className="col-span-1 flex items-center">
        <div className={`w-2 h-2 rounded-full ${port.status === "up" ? "bg-[var(--ok)]" : port.status === "down" ? "bg-[var(--critical)]" : "bg-[var(--text-muted)]"}`} />
      </div>
      <div className="col-span-2 text-[var(--text-primary)] truncate">{port.index}</div>
      <div className="col-span-2 text-[var(--text-muted)]">
        {port.speed_bps ? formatSpeed(port.speed_bps) : ""}
      </div>
      <div className="col-span-2 text-emerald-400 flex items-center gap-0.5">
        {hasTraffic && <><ArrowDown size={8} className="inline" />{formatBps(port.in_bps)}</>}
      </div>
      <div className="col-span-2 text-blue-400 flex items-center gap-0.5">
        {hasTraffic && <><ArrowUp size={8} className="inline" />{formatBps(port.out_bps)}</>}
      </div>
      <div className={`col-span-3 text-right ${hasErrors ? "text-[var(--medium)]" : "text-[var(--text-muted)]"}`}>
        {hasErrors ? `Err: ${port.in_errors || 0}/${port.out_errors || 0}` : ""}
      </div>
    </div>
  );
};

export function DeviceDetailPanel({ dev, isPing }) {
  const [metricsHistory, setMetricsHistory] = useState(null);
  const [showAllPorts, setShowAllPorts] = useState(false);

  useEffect(() => {
    if (dev.cpu_usage != null || dev.temperature != null) {
      axios.get(`${API}/connector/device-metrics/${dev.device_ip}`)
        .then(r => setMetricsHistory(r.data))
        .catch(() => {});
    }
  }, [dev.device_ip, dev.cpu_usage, dev.temperature]);

  const hw = dev.hardware || {};
  const fw = dev.firewall || {};
  const hasExtended = dev.cpu_usage != null || dev.memory_usage != null || dev.temperature != null;
  const hasHardware = (hw.fans?.length > 0) || (hw.power_supplies?.length > 0) || (hw.temperatures?.length > 0) || (hw.disks?.length > 0) || hw.health_status;
  const hasFirewall = dev.device_class === "zyxel-usg" || fw.active_sessions != null || fw.vpn_throughput != null;
  const ports = (dev.ports || []).sort((a, b) => parseInt(a.index) - parseInt(b.index));
  const hasTrafficData = ports.some(p => p.in_bps != null || p.speed_bps != null);
  const classLabel = dev.device_class === "hpe-comware" ? "HPE Comware Switch" 
    : dev.device_class === "hpe-ilo" ? "HPE iLO Server" 
    : dev.device_class === "zyxel-usg" ? "Zyxel USG Firewall" 
    : null;

  return (
    <div className="border-t border-[var(--bg-border)] p-3 pl-8 bg-[var(--bg-card)]/50 animate-fade-in space-y-3" data-testid={`device-detail-${dev.device_ip}`}>
      {/* Header info */}
      <div className="flex flex-wrap items-center gap-2">
        {dev.sys_descr && <p className="text-[11px] text-[var(--text-muted)] truncate flex-1">{dev.sys_descr}</p>}
        {classLabel && <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
          dev.device_class === "zyxel-usg" ? "bg-amber-500/10 border border-amber-500/20 text-amber-400" : "bg-indigo-500/10 border border-indigo-500/20 text-indigo-400"
        }`}>{classLabel}</span>}
      </div>
      {dev.sys_uptime && <p className="text-[11px] text-[var(--text-muted)]">Uptime: {dev.sys_uptime}</p>}

      {isPing ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-2 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Ping</p>
            <p className={`text-sm font-mono font-bold ${dev.reachable ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>
              {dev.ping_ms != null ? `${dev.ping_ms}ms` : "N/A"}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">HTTP</p>
            <p className={`text-sm font-mono font-bold ${dev.http_status && dev.http_status >= 200 && dev.http_status < 400 ? "text-[var(--ok)]" : dev.http_status ? "text-[var(--medium)]" : "text-[var(--text-muted)]"}`}>
              {dev.http_status ? `${dev.http_status}` : "N/A"}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Stato</p>
            <p className={`text-sm font-bold ${dev.reachable ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>
              {dev.reachable ? "Raggiungibile" : "Offline"}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Monitoraggio</p>
            <p className="text-sm font-mono font-bold text-indigo-400">Ping + HTTP</p>
          </div>
        </div>
      ) : (
        <>
          {/* Extended Metrics Gauges */}
          {hasExtended && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" data-testid="extended-metrics">
              <GaugeWidget
                label="CPU" value={dev.cpu_usage} unit="%" 
                icon={<Cpu size={12} className="text-blue-400" />}
                thresholds={{ warn: 70, crit: 90 }}
              />
              <GaugeWidget
                label="RAM" value={dev.memory_usage} unit="%"
                icon={<HardDrive size={12} className="text-purple-400" />}
                thresholds={{ warn: 80, crit: 95 }}
              />
              <GaugeWidget
                label="Temp" value={dev.temperature} max={100} unit="C"
                icon={<Thermometer size={12} className="text-orange-400" />}
                thresholds={{ warn: 60, crit: 75 }}
              />
            </div>
          )}

          {/* Hardware Health (ILO) */}
          {hasHardware && (
            <div className="space-y-2" data-testid="hardware-health">
              {hw.health_status && (
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">Salute Server:</span>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                    hw.health_status === "ok" ? "text-[var(--ok)] bg-[var(--low-bg)]" :
                    hw.health_status === "degraded" ? "text-[var(--medium)] bg-yellow-500/10" :
                    "text-[var(--critical)] bg-[var(--critical-bg)]"
                  }`}>
                    {hw.health_status === "ok" ? "OK" : hw.health_status === "degraded" ? "DEGRADATO" : hw.health_status === "failed" ? "GUASTO" : hw.health_status?.toUpperCase()}
                  </span>
                </div>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {/* Temperature Sensors */}
                {hw.temperatures?.length > 0 && (
                  <div className="space-y-1" data-testid="hw-temperatures">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium flex items-center gap-1"><Thermometer size={10} /> Temperature</p>
                    {hw.temperatures.map((t, i) => (
                      <div key={i} className={`px-2 py-1 rounded-md border ${
                        t.condition === "ok" ? "bg-[var(--low-bg)] border-[var(--low-border)]" : "bg-[var(--critical-bg)] border-[var(--critical-border)]"
                      } flex items-center justify-between`}>
                        <span className="text-[10px] text-[var(--text-muted)] truncate">{t.locale}</span>
                        <span className={`text-[10px] font-mono font-bold ${
                          t.value > 75 ? "text-[var(--critical)]" : t.value > 60 ? "text-[var(--medium)]" : "text-[var(--ok)]"
                        }`}>{t.value}C</span>
                      </div>
                    ))}
                  </div>
                )}
                {/* Fans */}
                {hw.fans?.length > 0 && (
                  <div className="space-y-1" data-testid="hw-fans">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium flex items-center gap-1"><Fan size={10} /> Ventole</p>
                    {hw.fans.map((f, i) => (
                      <HwStatusBadge key={i} condition={f.condition} label={`${f.locale}${f.speed ? ` (${f.speed}%)` : ""}`} />
                    ))}
                  </div>
                )}
                {/* Power Supplies */}
                {hw.power_supplies?.length > 0 && (
                  <div className="space-y-1" data-testid="hw-psu">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium flex items-center gap-1"><BatteryFull size={10} /> Alimentatori</p>
                    {hw.power_supplies.map((p, i) => (
                      <HwStatusBadge key={i} condition={p.condition} label={p.name} />
                    ))}
                  </div>
                )}
                {/* Disks */}
                {hw.disks?.length > 0 && (
                  <div className="space-y-1" data-testid="hw-disks">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium flex items-center gap-1"><HardDrive size={10} /> Dischi</p>
                    {hw.disks.map((d, i) => (
                      <HwStatusBadge key={i} condition={d.status} label={d.name} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Zyxel Firewall Metrics */}
          {hasFirewall && (
            <div className="space-y-2" data-testid="firewall-metrics">
              <div className="flex items-center gap-2">
                <ShieldCheck size={14} className="text-amber-400" />
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">Firewall Status</span>
                {fw.product_name && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 font-mono">{fw.product_name}</span>}
                {fw.firmware && <span className="text-[9px] text-[var(--text-muted)] font-mono">FW: {fw.firmware}</span>}
                {fw.serial_number && <span className="text-[9px] text-[var(--text-muted)] font-mono">S/N: {fw.serial_number}</span>}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {/* Active Sessions */}
                {fw.active_sessions != null && (
                  <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="fw-sessions">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <Globe size={12} className="text-cyan-400" />
                        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">Sessioni</p>
                      </div>
                      <p className={`text-sm font-mono font-bold ${
                        fw.active_sessions > 50000 ? "text-[var(--critical)]" : fw.active_sessions > 30000 ? "text-[var(--medium)]" : "text-[var(--ok)]"
                      }`}>{fw.active_sessions.toLocaleString()}</p>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-[var(--bg-hover)] overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ 
                        width: `${Math.min((fw.active_sessions / 100000) * 100, 100)}%`,
                        backgroundColor: fw.active_sessions > 50000 ? "var(--critical)" : fw.active_sessions > 30000 ? "var(--medium)" : "var(--ok)"
                      }} />
                    </div>
                  </div>
                )}
                {/* VPN Throughput */}
                {fw.vpn_throughput != null && (
                  <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="fw-vpn">
                    <div className="flex items-center gap-1.5 mb-1">
                      <ArrowsClockwise size={12} className="text-emerald-400" />
                      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">VPN IPSec</p>
                    </div>
                    <p className="text-sm font-mono font-bold text-emerald-400">{formatBps(fw.vpn_throughput)}</p>
                  </div>
                )}
                {/* Flash Usage */}
                {fw.flash_usage != null && (
                  <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="fw-flash">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <FloppyDisk size={12} className="text-purple-400" />
                        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">Flash</p>
                      </div>
                      <p className={`text-sm font-mono font-bold ${
                        fw.flash_usage > 90 ? "text-[var(--critical)]" : fw.flash_usage > 70 ? "text-[var(--medium)]" : "text-[var(--ok)]"
                      }`}>{fw.flash_usage}%</p>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-[var(--bg-hover)] overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-700" style={{ 
                        width: `${fw.flash_usage}%`,
                        backgroundColor: fw.flash_usage > 90 ? "var(--critical)" : fw.flash_usage > 70 ? "var(--medium)" : "var(--ok)"
                      }} />
                    </div>
                  </div>
                )}
                {/* CPU Detail */}
                {fw.cpu_detail && (
                  <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="fw-cpu-detail">
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <Cpu size={12} className="text-blue-400" />
                      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">CPU Detail</p>
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-[9px] font-mono">
                      {fw.cpu_detail.current != null && <div className="flex justify-between"><span className="text-[var(--text-muted)]">Now</span><span className="text-[var(--text-primary)]">{fw.cpu_detail.current}%</span></div>}
                      {fw.cpu_detail.avg_5sec != null && <div className="flex justify-between"><span className="text-[var(--text-muted)]">5s</span><span className="text-[var(--text-primary)]">{fw.cpu_detail.avg_5sec}%</span></div>}
                      {fw.cpu_detail.avg_1min != null && <div className="flex justify-between"><span className="text-[var(--text-muted)]">1m</span><span className="text-[var(--text-primary)]">{fw.cpu_detail.avg_1min}%</span></div>}
                      {fw.cpu_detail.avg_5min != null && <div className="flex justify-between"><span className="text-[var(--text-muted)]">5m</span><span className="text-[var(--text-primary)]">{fw.cpu_detail.avg_5min}%</span></div>}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Metrics History Mini-Chart */}
          {metricsHistory && metricsHistory.length > 1 && (
            <div className="space-y-1" data-testid="metrics-history">
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">Trend ultime 24h</p>
              <div className="h-16 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-1 flex items-end gap-px overflow-hidden">
                {metricsHistory.slice(-60).map((m, i) => {
                  const val = m.cpu_usage ?? m.temperature ?? 0;
                  const h = Math.max(2, (val / 100) * 100);
                  const color = val > 90 ? "var(--critical)" : val > 70 ? "var(--medium)" : "var(--ok)";
                  return <div key={i} className="flex-1 rounded-t-sm transition-all" style={{ height: `${h}%`, backgroundColor: color, minWidth: 2, opacity: 0.8 }} title={`${m.timestamp?.split("T")[1]?.substring(0,5) || ""}: CPU ${m.cpu_usage ?? "-"}% | Temp ${m.temperature ?? "-"}C`} />;
                })}
              </div>
              <div className="flex justify-between text-[9px] text-[var(--text-muted)]">
                <span>24h fa</span>
                <span className="flex items-center gap-2">
                  <span className="flex items-center gap-0.5"><div className="w-2 h-2 rounded-sm" style={{ backgroundColor: "var(--ok)" }} />CPU</span>
                </span>
                <span>ora</span>
              </div>
            </div>
          )}

          {/* Port Status Grid + Traffic Table */}
          {ports.length > 0 ? (
            <div className="space-y-2">
              {/* Visual port grid */}
              <div className="grid grid-cols-6 sm:grid-cols-8 md:grid-cols-12 gap-1.5">
                {ports.map((port, pi) => (
                  <div key={pi} 
                    title={`Porta ${port.index}: ${port.status}${port.speed_bps ? ` | ${formatSpeed(port.speed_bps)}` : ""}${port.in_bps != null ? ` | IN:${formatBps(port.in_bps)} OUT:${formatBps(port.out_bps)}` : ""}${(port.in_errors||0)+(port.out_errors||0) > 0 ? ` | Errori: ${port.in_errors||0}/${port.out_errors||0}` : ""}`}
                    className={`h-6 rounded flex items-center justify-center text-[9px] font-mono border cursor-default ${
                      port.status === "up" ? "bg-[var(--low-bg)] border-[var(--low-border)] text-[var(--ok)]"
                      : port.status === "down" ? "bg-[var(--critical-bg)] border-[var(--critical-border)] text-[var(--critical)]"
                      : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]"
                    }`}>{port.index}</div>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]"><div className="w-3 h-3 rounded bg-[var(--low-bg)] border border-[var(--low-border)]"></div>UP</span>
                <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]"><div className="w-3 h-3 rounded bg-[var(--critical-bg)] border border-[var(--critical-border)]"></div>DOWN</span>
                {hasTrafficData && (
                  <button onClick={() => setShowAllPorts(!showAllPorts)} className="ml-auto text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors" data-testid="toggle-traffic-table">
                    {showAllPorts ? "Nascondi traffico" : "Mostra traffico"}
                  </button>
                )}
              </div>

              {/* Traffic detail table */}
              {showAllPorts && hasTrafficData && (
                <div className="space-y-0.5 mt-1" data-testid="traffic-table">
                  <div className="grid grid-cols-12 gap-1 items-center px-2 py-1 text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
                    <div className="col-span-1"></div>
                    <div className="col-span-2">Porta</div>
                    <div className="col-span-2">Speed</div>
                    <div className="col-span-2">IN</div>
                    <div className="col-span-2">OUT</div>
                    <div className="col-span-3 text-right">Errori I/O</div>
                  </div>
                  {ports.filter(p => p.status === "up").map((port, pi) => (
                    <PortTrafficRow key={pi} port={port} />
                  ))}
                </div>
              )}
            </div>
          ) : <p className="text-xs text-[var(--text-muted)]">Nessun dato porte</p>}
        </>
      )}
    </div>
  );
}
