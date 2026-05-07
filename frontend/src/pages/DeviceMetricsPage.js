import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

const METRICS = [
  { key: "cpu", label: "CPU %", unit: "%", color: "#6366f1", max: 100 },
  { key: "memory", label: "Memoria %", unit: "%", color: "#10b981", max: 100 },
  { key: "temperature", label: "Temperatura °C", unit: "°C", color: "#ef4444", max: null },
  { key: "response_ms", label: "Ping Latency (ms)", unit: "ms", color: "#f59e0b", max: null },
  { key: "ping_avg", label: "Ping medio (ms)", unit: "ms", color: "#f59e0b", max: null },
  { key: "ping_jitter", label: "Ping Jitter (ms)", unit: "ms", color: "#fb923c", max: null },
  { key: "packet_loss", label: "Packet Loss %", unit: "%", color: "#ef4444", max: 100 },
  { key: "sessions", label: "Sessioni firewall", unit: "", color: "#f97316", max: null },
  { key: "vpn_throughput", label: "VPN Throughput", unit: "Mbps", color: "#06b6d4", max: null },
  { key: "ups_charge_pct", label: "UPS Carica %", unit: "%", color: "#22c55e", max: 100 },
  { key: "ups_runtime_min", label: "UPS Autonomia (min)", unit: "min", color: "#06b6d4", max: null },
  { key: "ups_load_pct", label: "UPS Carico %", unit: "%", color: "#a855f7", max: 100 },
];

const PERIODS = [
  { key: "1h", label: "1 ora" },
  { key: "6h", label: "6 ore" },
  { key: "24h", label: "24 ore" },
  { key: "7d", label: "7 giorni" },
  { key: "30d", label: "30 giorni" },
];

export default function DeviceMetricsPage({ embeddedIp = null, embeddedClientId = null }) {
  const [searchParams] = useSearchParams();
  const urlIp = searchParams.get("ip") || "";
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState(embeddedClientId || "");
  const [devices, setDevices] = useState([]);
  const [selectedIp, setSelectedIp] = useState(embeddedIp || urlIp || "");
  const [metric, setMetric] = useState("cpu");
  const [period, setPeriod] = useState("24h");
  const [data, setData] = useState({ points: [], count: 0 });
  const [loading, setLoading] = useState(false);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (embeddedIp) return;
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (!selectedClient && cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (embeddedIp) return;
    if (!selectedClient) return;
    axios.get(`${API}/api/devices?client_id=${selectedClient}`, { headers })
      .then(r => {
        const list = Array.isArray(r.data) ? r.data : (r.data?.devices || r.data?.items || []);
        // normalize to {ip, name} so existing UI keeps working
        const ds = list.map(d => ({
          ip: d.ip || d.ip_address || d.device_ip,
          name: d.name || d.hostname || d.ip_address || d.ip,
          ...d,
        })).filter(d => d.ip);
        setDevices(ds);
        if (ds.length > 0 && !selectedIp) setSelectedIp(ds[0].ip);
      }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClient]);

  const fetchData = useCallback(() => {
    if (!selectedIp) return;
    setLoading(true);
    axios.get(`${API}/api/devices/by-ip/${selectedIp}/metrics?metric=${metric}&period=${period}`, { headers })
      .then(r => setData(r.data))
      .catch(() => toast.error("Errore caricamento metriche"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIp, metric, period]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    const t = setInterval(fetchData, 60000); // refresh 60s
    return () => clearInterval(t);
  }, [fetchData]);

  const metricDef = METRICS.find(m => m.key === metric) || METRICS[0];

  const fmtTime = (ts) => {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      if (period === "7d" || period === "30d") {
        return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("it-IT", { hour: "2-digit" }) + "h";
      }
      return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    } catch { return ts.slice(0, 16); }
  };

  const last = data.points?.length ? data.points[data.points.length - 1] : null;
  const avgAll = data.points?.length
    ? (data.points.reduce((s, p) => s + (p.avg ?? 0), 0) / data.points.length).toFixed(1)
    : "—";
  const peakAll = data.points?.length
    ? Math.max(...data.points.map(p => p.max ?? 0)).toFixed(1)
    : "—";

  return (
    <div className="space-y-4" data-testid="device-metrics-page">
      {!embeddedIp && (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Trend Metriche Device</h1>
            <p className="text-sm text-[var(--text-secondary)]">Storico 30 giorni per CPU, RAM, temperatura e metriche vendor-specifiche</p>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 flex-wrap">
          {!embeddedIp && (
            <>
              <select value={selectedClient} onChange={e => { setSelectedClient(e.target.value); setSelectedIp(""); }}
                className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-input,var(--bg-card))] text-[var(--text-primary)]"
                data-testid="metrics-client-select">
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <select value={selectedIp} onChange={e => setSelectedIp(e.target.value)}
                className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-input,var(--bg-card))] text-[var(--text-primary)] min-w-[200px]"
                data-testid="metrics-device-select">
                <option value="">— Seleziona dispositivo —</option>
                {devices.map(d => (
                  <option key={d.ip} value={d.ip}>{d.name || d.ip} ({d.ip})</option>
                ))}
              </select>
            </>
          )}
          <select value={metric} onChange={e => setMetric(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-input,var(--bg-card))] text-[var(--text-primary)]"
            data-testid="metrics-metric-select">
            {METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
          <div className="flex items-center gap-1">
            {PERIODS.map(p => (
              <button key={p.key} onClick={() => setPeriod(p.key)}
                className={`h-8 px-3 text-xs rounded-md border transition-colors ${period === p.key
                  ? "bg-cyan-500/20 border-cyan-500/60 text-cyan-300"
                  : "bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
                data-testid={`metrics-period-${p.key}`}>
                {p.label}
              </button>
            ))}
          </div>
          <button onClick={fetchData} className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            data-testid="metrics-refresh-btn">Aggiorna</button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
          <div className="text-[10px] uppercase text-[var(--text-secondary)]">Ultimo</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]" data-testid="metrics-last">
            {last?.avg != null ? `${last.avg}${metricDef.unit}` : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
          <div className="text-[10px] uppercase text-[var(--text-secondary)]">Media periodo</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]" data-testid="metrics-avg">
            {avgAll !== "—" ? `${avgAll}${metricDef.unit}` : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
          <div className="text-[10px] uppercase text-[var(--text-secondary)]">Picco</div>
          <div className="text-2xl font-bold text-[var(--text-primary)]" data-testid="metrics-peak">
            {peakAll !== "—" ? `${peakAll}${metricDef.unit}` : "—"}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="metrics-chart-box">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{metricDef.label}</h3>
          <span className="text-xs text-[var(--text-secondary)]">{data.count} punti · refresh 60s</span>
        </div>
        {loading && <div className="text-center py-12 text-[var(--text-secondary)]">Caricamento...</div>}
        {!loading && data.points.length === 0 && (
          <div className="text-center py-12 text-[var(--text-secondary)]">
            Nessun dato storico disponibile.<br />
            <span className="text-xs">I dati vengono raccolti automaticamente dal connector. Attendere almeno 2-3 cicli di polling.</span>
          </div>
        )}
        {!loading && data.points.length > 0 && (
          <ResponsiveContainer width="100%" height={360}>
            <AreaChart data={data.points}>
              <defs>
                <linearGradient id={`grad-${metric}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={metricDef.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={metricDef.color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
              <XAxis dataKey="ts" tickFormatter={fmtTime} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
              <YAxis domain={metricDef.max ? [0, metricDef.max] : ['auto', 'auto']}
                tick={{ fontSize: 10, fill: "var(--text-secondary)" }} unit={metricDef.unit} />
              <Tooltip labelFormatter={fmtTime}
                contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area type="monotone" dataKey="avg" name={`Media ${metricDef.unit}`}
                stroke={metricDef.color} fill={`url(#grad-${metric})`} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="max" name={`Max ${metricDef.unit}`}
                stroke="#ef4444" strokeWidth={1} dot={false} strokeDasharray="4 3" />
              <Line type="monotone" dataKey="min" name={`Min ${metricDef.unit}`}
                stroke="#10b981" strokeWidth={1} dot={false} strokeDasharray="4 3" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
