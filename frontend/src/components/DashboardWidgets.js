import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  ChartLine, Shield, Clock, Warning, ArrowUp, ArrowDown,
  CheckCircle, XCircle, Pulse, Eye
} from "@phosphor-icons/react";

/* ── SLA Gauge Widget ── */
export function SlaGaugeWidget({ clientId }) {
  const [sla, setSla] = useState(null);
  const [period, setPeriod] = useState(30);

  useEffect(() => {
    if (!clientId) return;
    axios.get(`${API}/metrics/sla/${clientId}?days=${period}`)
      .then(r => setSla(r.data)).catch(() => {});
  }, [clientId, period]);

  if (!sla) return <WidgetSkeleton title="SLA" />;

  const overall = sla.overall_sla_pct;
  const color = overall >= 99.9 ? "emerald" : overall >= 99 ? "green" : overall >= 95 ? "amber" : "red";

  return (
    <div className="noc-panel p-4 space-y-3" data-testid="sla-widget">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={16} className="text-indigo-400" weight="fill" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">SLA Monitoring</h3>
        </div>
        <div className="flex gap-1">
          {[7, 30, 90].map(d => (
            <button key={d} onClick={() => setPeriod(d)}
              className={`px-2 py-0.5 rounded text-[9px] font-medium ${period === d ? "bg-indigo-600/20 text-indigo-400" : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"}`}
            >{d}gg</button>
          ))}
        </div>
      </div>

      {/* Overall SLA Gauge */}
      <div className="flex items-center gap-4">
        <div className="relative w-20 h-20">
          <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--bg-deep)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.5" fill="none"
              stroke={`var(--${color === "emerald" ? "emerald" : color}-500, #22c55e)`}
              strokeWidth="3" strokeDasharray={`${overall} ${100 - overall}`} strokeLinecap="round"
              className="transition-all duration-1000"
              style={{ stroke: color === "emerald" ? "#10b981" : color === "green" ? "#22c55e" : color === "amber" ? "#f59e0b" : "#ef4444" }}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className={`text-lg font-black text-${color}-400`} style={{ color: color === "emerald" ? "#10b981" : color === "green" ? "#22c55e" : color === "amber" ? "#f59e0b" : "#ef4444" }}>
              {overall.toFixed(1)}%
            </span>
          </div>
        </div>
        <div className="flex-1 text-xs text-[var(--text-muted)]">
          <p>Periodo: {period} giorni</p>
          <p>Check totali: {sla.total_checks.toLocaleString()}</p>
          <p>Target: 99.9%</p>
        </div>
      </div>

      {/* Per-device SLA */}
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {sla.devices.map((d, i) => (
          <div key={i} className="flex items-center gap-2 text-xs px-2 py-1.5 rounded hover:bg-[var(--bg-hover)] transition-colors">
            {d.meets_sla ? <CheckCircle size={14} className="text-emerald-400" weight="fill" /> : <XCircle size={14} className="text-red-400" weight="fill" />}
            <span className="flex-1 text-[var(--text-primary)] truncate">{d.device_name}</span>
            <span className="text-[10px] font-mono text-[var(--text-muted)]">{d.device_ip}</span>
            <span className={`font-mono font-bold ${d.uptime_pct >= 99.9 ? "text-emerald-400" : d.uptime_pct >= 99 ? "text-green-400" : d.uptime_pct >= 95 ? "text-amber-400" : "text-red-400"}`}>
              {d.uptime_pct.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Change Timeline Widget ── */
export function ChangeTimelineWidget({ clientId }) {
  const [changes, setChanges] = useState(null);
  const [days, setDays] = useState(7);

  useEffect(() => {
    if (!clientId) return;
    axios.get(`${API}/metrics/changes/${clientId}?days=${days}`)
      .then(r => setChanges(r.data)).catch(() => {});
  }, [clientId, days]);

  if (!changes) return <WidgetSkeleton title="Modifiche Rete" />;

  const sevColor = {
    critical: "text-red-400 bg-red-500/15 border-red-500/30",
    high: "text-orange-400 bg-orange-500/15 border-orange-500/30",
    medium: "text-yellow-400 bg-yellow-500/15 border-yellow-500/30",
    info: "text-blue-400 bg-blue-500/15 border-blue-500/30",
  };

  const typeIcon = {
    device_added: <ArrowUp size={12} className="text-emerald-400" />,
    device_removed: <ArrowDown size={12} className="text-red-400" />,
    status_changed: <Pulse size={12} className="text-amber-400" />,
    name_changed: <Eye size={12} className="text-indigo-400" />,
    ports_changed: <Warning size={12} className="text-yellow-400" />,
  };

  return (
    <div className="noc-panel p-4 space-y-3" data-testid="changes-widget">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock size={16} className="text-amber-400" weight="fill" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Modifiche Rete</h3>
          <span className="text-[10px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded-full">{changes.total_changes}</span>
        </div>
        <div className="flex gap-1">
          {[1, 7, 30].map(d => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-2 py-0.5 rounded text-[9px] font-medium ${days === d ? "bg-indigo-600/20 text-indigo-400" : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"}`}
            >{d === 1 ? "Oggi" : `${d}gg`}</button>
          ))}
        </div>
      </div>

      {changes.total_changes === 0 ? (
        <p className="text-xs text-[var(--text-muted)] text-center py-4">Nessuna modifica rilevata</p>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-y-auto">
          {changes.changes.map((c, i) => {
            const sevCls = sevColor[c.severity] || sevColor.info;
            return (
              <div key={i} className={`border rounded-lg px-3 py-2 ${sevCls}`}>
                <div className="flex items-center gap-2 text-[10px]">
                  {typeIcon[c.type] || <Warning size={12} />}
                  <span className="font-bold uppercase">{c.type.replace("_", " ")}</span>
                  <span className="ml-auto text-[var(--text-muted)]">{formatTimeAgo(c.timestamp)}</span>
                </div>
                <p className="text-[11px] mt-0.5 text-[var(--text-primary)]">{c.message}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Uptime Heatmap Widget ── */
export function UptimeHeatmapWidget({ clientId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!clientId) return;
    axios.get(`${API}/metrics/heatmap/${clientId}?days=7`)
      .then(r => setData(r.data)).catch(() => {});
  }, [clientId]);

  if (!data) return <WidgetSkeleton title="Heatmap Disponibilita'" />;

  const devices = Object.entries(data.devices || {});
  if (devices.length === 0) return null;

  // Get last 24 hours
  const now = new Date();
  const hours = [];
  for (let i = 23; i >= 0; i--) {
    const h = new Date(now.getTime() - i * 3600000);
    h.setMinutes(0, 0, 0);
    hours.push(h.toISOString().replace(/\.\d+Z$/, "+00:00"));
  }

  const getColor = (pct) => {
    if (pct === undefined || pct === null) return "bg-[var(--bg-deep)]";
    if (pct >= 99) return "bg-emerald-500";
    if (pct >= 90) return "bg-green-500";
    if (pct >= 75) return "bg-amber-500";
    if (pct >= 50) return "bg-orange-500";
    return "bg-red-500";
  };

  return (
    <div className="noc-panel p-4 space-y-3" data-testid="heatmap-widget">
      <div className="flex items-center gap-2">
        <ChartLine size={16} className="text-emerald-400" weight="fill" />
        <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Disponibilita' 24h</h3>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[9px]">
          <thead>
            <tr>
              <th className="text-left text-[var(--text-muted)] font-medium pb-1 pr-2 min-w-[120px]">Dispositivo</th>
              {hours.map((h, i) => (
                <th key={i} className="text-center text-[var(--text-muted)] font-normal pb-1 px-0" style={{ width: 12 }}>
                  {i % 4 === 0 ? new Date(h).getHours().toString().padStart(2, "0") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {devices.map(([ip, info]) => (
              <tr key={ip}>
                <td className="text-[var(--text-primary)] pr-2 py-0.5 truncate max-w-[120px]" title={`${info.device_name} (${ip})`}>
                  {info.device_name || ip}
                </td>
                {hours.map((h, i) => {
                  const cell = info.hours?.[h];
                  return (
                    <td key={i} className="p-0">
                      <div
                        className={`w-2.5 h-2.5 rounded-sm mx-auto ${getColor(cell?.uptime_pct)}`}
                        title={cell ? `${cell.uptime_pct}% | ${cell.avg_ping ?? "-"}ms` : "N/D"}
                        style={{ opacity: cell ? (cell.uptime_pct / 100 * 0.5 + 0.5) : 0.2 }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-[8px] text-[var(--text-muted)]">
        <span>Legenda:</span>
        {[
          { label: "100%", cls: "bg-emerald-500" },
          { label: "90-99%", cls: "bg-green-500" },
          { label: "75-90%", cls: "bg-amber-500" },
          { label: "50-75%", cls: "bg-orange-500" },
          { label: "<50%", cls: "bg-red-500" },
          { label: "N/D", cls: "bg-[var(--bg-deep)]" },
        ].map(l => (
          <div key={l.label} className="flex items-center gap-1">
            <div className={`w-2 h-2 rounded-sm ${l.cls}`} />
            <span>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Latency Chart Widget ── */
export function LatencyChartWidget({ clientId }) {
  const [data, setData] = useState(null);
  const [selectedIp, setSelectedIp] = useState(null);

  useEffect(() => {
    if (!clientId) return;
    axios.get(`${API}/metrics/heatmap/${clientId}?days=1`)
      .then(r => {
        setData(r.data);
        const ips = Object.keys(r.data?.devices || {});
        if (ips.length > 0 && !selectedIp) setSelectedIp(ips[0]);
      }).catch(() => {});
  }, [clientId]);

  if (!data) return <WidgetSkeleton title="Latenza" />;

  const devices = Object.entries(data.devices || {});
  const selectedDevice = selectedIp ? data.devices?.[selectedIp] : null;
  const hours = selectedDevice ? Object.entries(selectedDevice.hours || {}).sort(([a], [b]) => a.localeCompare(b)) : [];
  const maxPing = Math.max(...hours.map(([, v]) => v.avg_ping || 0), 1);

  return (
    <div className="noc-panel p-4 space-y-3" data-testid="latency-widget">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Pulse size={16} className="text-cyan-400" weight="fill" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Latenza 24h</h3>
        </div>
        <select
          value={selectedIp || ""}
          onChange={e => setSelectedIp(e.target.value)}
          className="h-6 px-2 rounded bg-[var(--bg-deep)] border border-[var(--border-subtle)] text-[10px] text-[var(--text-primary)]"
          data-testid="latency-device-select"
        >
          {devices.map(([ip, info]) => (
            <option key={ip} value={ip}>{info.device_name || ip}</option>
          ))}
        </select>
      </div>

      {hours.length > 0 ? (
        <div className="h-32 flex items-end gap-0.5">
          {hours.map(([h, v], i) => {
            const ping = v.avg_ping || 0;
            const pct = (ping / maxPing) * 100;
            const color = ping < 5 ? "bg-emerald-500" : ping < 20 ? "bg-green-500" : ping < 50 ? "bg-amber-500" : "bg-red-500";
            return (
              <div key={i} className="flex-1 flex flex-col items-center group relative" title={`${new Date(h).getHours()}:00 - ${ping.toFixed(1)}ms`}>
                <div className={`w-full ${color} rounded-t transition-all duration-300`} style={{ height: `${Math.max(pct, 3)}%`, opacity: v.uptime_pct === 0 ? 0.3 : 1 }} />
                {i % 4 === 0 && (
                  <span className="text-[7px] text-[var(--text-muted)] mt-0.5">{new Date(h).getHours()}h</span>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-[var(--text-muted)] text-center py-6">Nessun dato disponibile</p>
      )}
    </div>
  );
}

/* ── Skeleton ── */
function WidgetSkeleton({ title }) {
  return (
    <div className="noc-panel p-4 space-y-3 animate-pulse">
      <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">{title}</h3>
      <div className="h-24 bg-[var(--bg-deep)] rounded" />
    </div>
  );
}

/* ── Helpers ── */
function formatTimeAgo(iso) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m fa`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h fa`;
  const days = Math.floor(hours / 24);
  return `${days}gg fa`;
}
