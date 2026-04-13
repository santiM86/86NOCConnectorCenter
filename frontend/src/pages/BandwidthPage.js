import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

export default function BandwidthPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [summary, setSummary] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [history, setHistory] = useState(null);
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(false);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, []);

  const fetchSummary = useCallback(() => {
    if (!selectedClient) return;
    setLoading(true);
    axios.get(`${API}/api/bandwidth/summary/${selectedClient}`, { headers })
      .then(r => setSummary(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedClient]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  const fetchHistory = (deviceIp) => {
    setSelectedDevice(deviceIp);
    axios.get(`${API}/api/bandwidth/${selectedClient}/${deviceIp}?hours=${hours}`, { headers })
      .then(r => setHistory(r.data))
      .catch(() => toast.error("Errore caricamento storico bandwidth"));
  };

  const formatBps = (bps) => {
    if (!bps || bps === 0) return "0 bps";
    if (bps >= 1e9) return `${(bps / 1e9).toFixed(1)} Gbps`;
    if (bps >= 1e6) return `${(bps / 1e6).toFixed(1)} Mbps`;
    if (bps >= 1e3) return `${(bps / 1e3).toFixed(1)} Kbps`;
    return `${bps} bps`;
  };

  const fmtTime = (ts) => {
    if (!ts) return "";
    try { return new Date(ts).toLocaleString("it-IT", { hour: "2-digit", minute: "2-digit" }); }
    catch { return ts.slice(11, 16); }
  };

  const utilizationColor = (pct) => {
    if (pct >= 90) return "text-red-400";
    if (pct >= 70) return "text-amber-400";
    return "text-emerald-400";
  };

  // Group summary by device
  const deviceGroups = {};
  summary.forEach(s => {
    const key = s.device_ip;
    if (!deviceGroups[key]) deviceGroups[key] = { device_ip: key, device_name: s.device_name, interfaces: [] };
    deviceGroups[key].interfaces.push(s);
  });

  return (
    <div className="space-y-6" data-testid="bandwidth-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Monitoraggio Bandwidth</h1>
          <p className="text-sm text-[var(--text-secondary)]">Traffico di rete e utilizzo delle interfacce</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="bw-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={hours} onChange={e => setHours(Number(e.target.value))}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]">
            <option value={6}>6 ore</option>
            <option value={24}>24 ore</option>
            <option value={72}>3 giorni</option>
            <option value={168}>7 giorni</option>
          </select>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Caricamento...</div>}

      {/* Device list */}
      {Object.keys(deviceGroups).length > 0 ? (
        <div className="space-y-3">
          {Object.values(deviceGroups).map((dg) => (
            <div key={dg.device_ip} className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden" data-testid={`bw-device-${dg.device_ip}`}>
              <div className="p-3 border-b border-[var(--bg-border)] flex items-center justify-between cursor-pointer hover:bg-[var(--bg-surface)]"
                onClick={() => fetchHistory(dg.device_ip)}>
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5-4.5L16.5 16.5m0 0L12 12m4.5 4.5V3" />
                  </svg>
                  <span className="text-sm font-semibold text-[var(--text-primary)]">{dg.device_name || dg.device_ip}</span>
                  <span className="text-xs text-[var(--text-secondary)]">({dg.device_ip})</span>
                </div>
                <span className="text-xs text-[var(--text-secondary)]">{dg.interfaces.length} interfacce</span>
              </div>
              <div className="divide-y divide-[var(--bg-border)]">
                {dg.interfaces.map((iface, j) => (
                  <div key={j} className="flex items-center justify-between px-4 py-2 text-xs">
                    <span className="font-medium text-[var(--text-primary)] w-24">{iface.if_name}</span>
                    <span className="text-[var(--text-secondary)] w-20">{iface.if_speed ? formatBps(iface.if_speed) : "-"}</span>
                    <span className="text-emerald-400 w-24">IN: {formatBps(iface.last_in_bps)}</span>
                    <span className="text-blue-400 w-24">OUT: {formatBps(iface.last_out_bps)}</span>
                    <span className={`font-bold w-16 text-right ${utilizationColor(iface.last_utilization)}`}>
                      {iface.last_utilization?.toFixed(1) || "0"}%
                    </span>
                    <span className="text-[var(--text-secondary)] w-16 text-right">avg: {iface.avg_utilization}%</span>
                    <span className="text-[var(--text-secondary)] w-16 text-right">max: {iface.max_utilization}%</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : !loading && (
        <div className="text-center py-16">
          <svg className="w-12 h-12 mx-auto mb-3 text-[var(--text-secondary)] opacity-50" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5-4.5L16.5 16.5m0 0L12 12m4.5 4.5V3" />
          </svg>
          <p className="text-sm text-[var(--text-secondary)]">Nessun dato bandwidth disponibile.</p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">Il connettore iniziera a raccogliere dati ifInOctets/ifOutOctets al prossimo ciclo di polling.</p>
        </div>
      )}

      {/* History chart */}
      {history && selectedDevice && (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="bw-history-chart">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Storico Bandwidth — {selectedDevice} (ultime {hours}h)
          </h3>
          {history.interfaces?.length > 0 ? (
            <div className="space-y-4">
              {history.interfaces.map((iface, k) => (
                <div key={k}>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">{iface.if_name} ({formatBps(iface.if_speed)})</p>
                  <ResponsiveContainer width="100%" height={180}>
                    <AreaChart data={iface.data}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                      <XAxis dataKey="timestamp" tickFormatter={fmtTime} tick={{ fontSize: 9, fill: "var(--text-secondary)" }} />
                      <YAxis tickFormatter={(v) => formatBps(v)} tick={{ fontSize: 9, fill: "var(--text-secondary)" }} />
                      <Tooltip labelFormatter={fmtTime} formatter={(v) => formatBps(v)}
                        contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 11 }} />
                      <Area type="monotone" dataKey="in_bps" name="IN" stroke="#10b981" fill="#10b981" fillOpacity={0.15} strokeWidth={1.5} />
                      <Area type="monotone" dataKey="out_bps" name="OUT" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.15} strokeWidth={1.5} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-[var(--text-secondary)] text-center py-4">Nessun dato storico per questo dispositivo</p>}
        </div>
      )}
    </div>
  );
}
