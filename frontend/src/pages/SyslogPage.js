import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

const SEVERITY_COLORS = {
  0: "bg-red-600/20 text-red-300 border-red-600/40",       // emerg
  1: "bg-red-600/20 text-red-300 border-red-600/40",       // alert
  2: "bg-orange-600/20 text-orange-300 border-orange-600/40", // crit
  3: "bg-orange-500/20 text-orange-300 border-orange-500/40", // err
  4: "bg-amber-500/20 text-amber-300 border-amber-500/40", // warning
  5: "bg-sky-500/20 text-sky-300 border-sky-500/40",       // notice
  6: "bg-slate-500/20 text-slate-300 border-slate-500/40", // info
  7: "bg-slate-500/10 text-slate-400 border-slate-500/20", // debug
};

export default function SyslogPage() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [severityMax, setSeverityMax] = useState(7);
  const [textFilter, setTextFilter] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const fetchEvents = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (deviceFilter) params.set("device_ip", deviceFilter);
    params.set("severity_max", String(severityMax));
    params.set("limit", "200");
    axios.get(`${API}/api/connector/syslog?${params.toString()}`, { headers })
      .then(r => setEvents(r.data?.items || []))
      .catch(() => toast.error("Errore caricamento syslog"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceFilter, severityMax]);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(fetchEvents, 15000);
    return () => clearInterval(t);
  }, [autoRefresh, fetchEvents]);

  const filtered = textFilter
    ? events.filter(e => (e.message || "").toLowerCase().includes(textFilter.toLowerCase())
        || (e.host || "").toLowerCase().includes(textFilter.toLowerCase())
        || (e.device_ip || "").includes(textFilter))
    : events;

  const fmtTs = (ts) => {
    if (!ts) return "—";
    try { return new Date(ts).toLocaleString("it-IT"); } catch { return ts; }
  };

  return (
    <div className="space-y-4" data-testid="syslog-page">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Syslog Viewer</h1>
          <p className="text-sm text-[var(--text-secondary)]">Eventi Syslog ricevuti dai dispositivi di rete (UDP 514 via connector)</p>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
        <div className="flex items-center gap-2 flex-wrap">
          <input placeholder="IP dispositivo" value={deviceFilter} onChange={e => setDeviceFilter(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="syslog-device-filter" />
          <select value={severityMax} onChange={e => setSeverityMax(Number(e.target.value))}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="syslog-severity-filter">
            <option value={0}>Solo emergency</option>
            <option value={2}>Critical+</option>
            <option value={3}>Error+</option>
            <option value={4}>Warning+</option>
            <option value={6}>Info+</option>
            <option value={7}>Tutto (debug incl.)</option>
          </select>
          <input placeholder="Cerca nel messaggio..." value={textFilter} onChange={e => setTextFilter(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] flex-1 min-w-[200px]"
            data-testid="syslog-text-filter" />
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
              data-testid="syslog-autorefresh" />
            Auto-refresh 15s
          </label>
          <button onClick={fetchEvents}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            data-testid="syslog-refresh-btn">Aggiorna</button>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden">
        {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Caricamento...</div>}
        {!loading && filtered.length === 0 && (
          <div className="text-center py-12 text-[var(--text-secondary)]">
            Nessun evento syslog ricevuto.<br />
            <span className="text-xs">
              Assicurati che sui dispositivi sia attivo il forwarding syslog verso l'IP del connector sulla porta UDP 514.
            </span>
          </div>
        )}
        {!loading && filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-[var(--bg-input,rgba(0,0,0,0.15))] border-b border-[var(--bg-border)]">
                <tr className="text-left text-[var(--text-secondary)]">
                  <th className="px-3 py-2 w-40">Timestamp</th>
                  <th className="px-3 py-2 w-28">Severity</th>
                  <th className="px-3 py-2 w-32">Device</th>
                  <th className="px-3 py-2 w-28">Host</th>
                  <th className="px-3 py-2 w-24">Facility</th>
                  <th className="px-3 py-2">Messaggio</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e, i) => (
                  <tr key={e.id || i} className="border-b border-[var(--bg-border)] hover:bg-[var(--bg-hover,rgba(255,255,255,0.03))]"
                    data-testid={`syslog-row-${i}`}>
                    <td className="px-3 py-1.5 text-[var(--text-secondary)] whitespace-nowrap">{fmtTs(e.ts)}</td>
                    <td className="px-3 py-1.5">
                      <span className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase font-mono ${SEVERITY_COLORS[e.severity] || SEVERITY_COLORS[6]}`}>
                        {e.severity_label || e.severity}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[var(--text-primary)]">{e.device_ip}</td>
                    <td className="px-3 py-1.5 text-[var(--text-secondary)]">{e.host || "—"}</td>
                    <td className="px-3 py-1.5 text-[var(--text-secondary)]">{e.facility_label}</td>
                    <td className="px-3 py-1.5 text-[var(--text-primary)] font-mono whitespace-pre-wrap break-all">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
