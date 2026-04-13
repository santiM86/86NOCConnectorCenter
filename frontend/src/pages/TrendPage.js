import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

export default function TrendPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [days, setDays] = useState(7);
  const [trends, setTrends] = useState(null);
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

  const fetchTrends = useCallback(() => {
    if (!selectedClient) return;
    setLoading(true);
    axios.get(`${API}/api/trends/${selectedClient}?days=${days}`, { headers })
      .then(r => setTrends(r.data))
      .catch(() => toast.error("Errore nel caricamento trend"))
      .finally(() => setLoading(false));
  }, [selectedClient, days]);

  useEffect(() => { fetchTrends(); }, [fetchTrends]);

  const fmtTime = (ts) => {
    if (!ts) return "";
    try { return new Date(ts).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
    catch { return ts.slice(0, 16); }
  };

  const fmtDate = (ts) => {
    if (!ts) return "";
    try { return new Date(ts).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }); }
    catch { return ts.slice(0, 10); }
  };

  return (
    <div className="space-y-6" data-testid="trend-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Grafici Trend</h1>
          <p className="text-sm text-[var(--text-secondary)]">Andamento storico delle metriche di rete</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="trend-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="trend-days-select">
            <option value={1}>24 ore</option>
            <option value={3}>3 giorni</option>
            <option value={7}>7 giorni</option>
            <option value={30}>30 giorni</option>
          </select>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Caricamento...</div>}

      {trends && !loading && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Availability Trend */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="availability-chart">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Disponibilita Rete</h3>
            {trends.availability_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={trends.availability_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtTime} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} unit="%" />
                  <Tooltip labelFormatter={fmtTime} contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 12 }} />
                  <Area type="monotone" dataKey="availability_pct" name="Disponibilita %" stroke="#10b981" fill="#10b981" fillOpacity={0.2} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <p className="text-xs text-[var(--text-secondary)] py-8 text-center">Nessun dato disponibile per il periodo selezionato</p>}
          </div>

          {/* Latency Trend */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="latency-chart">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Latenza Media (ms)</h3>
            {trends.availability_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={trends.availability_trend.filter(d => d.avg_ping_ms != null)}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtTime} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} unit="ms" />
                  <Tooltip labelFormatter={fmtTime} contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 12 }} />
                  <Line type="monotone" dataKey="avg_ping_ms" name="Latenza ms" stroke="#f59e0b" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="text-xs text-[var(--text-secondary)] py-8 text-center">Nessun dato disponibile</p>}
          </div>

          {/* VA Score Trend */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="va-score-chart">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Score Vulnerability Assessment</h3>
            {trends.va_score_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={trends.va_score_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <Tooltip labelFormatter={fmtDate} contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 12 }} />
                  <Area type="monotone" dataKey="overall_score" name="Score VA" stroke="#6366f1" fill="#6366f1" fillOpacity={0.15} strokeWidth={2} />
                  <Area type="monotone" dataKey="total_vulnerabilities" name="Vulnerabilita" stroke="#ef4444" fill="#ef4444" fillOpacity={0.1} strokeWidth={1} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <p className="text-xs text-[var(--text-secondary)] py-8 text-center">Esegui almeno 2 scansioni VA per visualizzare il trend</p>}
          </div>

          {/* Alert Trend */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="alert-trend-chart">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Alert per Giorno</h3>
            {trends.alert_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={trends.alert_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                  <XAxis dataKey="_id" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <Tooltip labelFormatter={fmtDate} contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="critical" name="Critici" fill="#ef4444" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="high" name="Alti" fill="#f97316" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="total" name="Totali" fill="#6366f1" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="text-xs text-[var(--text-secondary)] py-8 text-center">Nessun alert nel periodo selezionato</p>}
          </div>
        </div>
      )}
    </div>
  );
}
