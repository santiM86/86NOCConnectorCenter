import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function TrapsPage() {
  const [traps, setTraps] = useState([]);
  const [loading, setLoading] = useState(false);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selected, setSelected] = useState(null);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const fetchTraps = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (deviceFilter) params.set("device_ip", deviceFilter);
    params.set("limit", "200");
    axios.get(`${API}/api/connector/snmp-traps?${params.toString()}`, { headers })
      .then(r => setTraps(r.data?.items || []))
      .catch(() => toast.error("Errore caricamento SNMP traps"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceFilter]);

  useEffect(() => { fetchTraps(); }, [fetchTraps]);
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(fetchTraps, 15000);
    return () => clearInterval(t);
  }, [autoRefresh, fetchTraps]);

  const fmtTs = (ts) => {
    if (!ts) return "—";
    try { return new Date(ts).toLocaleString("it-IT"); } catch { return ts; }
  };

  return (
    <div className="space-y-4" data-testid="traps-page">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">SNMP Traps</h1>
        <p className="text-sm text-[var(--text-secondary)]">Trap SNMP ricevuti dai dispositivi (UDP 162 via connector)</p>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
        <div className="flex items-center gap-2 flex-wrap">
          <input placeholder="IP dispositivo" value={deviceFilter} onChange={e => setDeviceFilter(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="traps-device-filter" />
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
              data-testid="traps-autorefresh" />
            Auto-refresh 15s
          </label>
          <button onClick={fetchTraps}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            data-testid="traps-refresh-btn">Aggiorna</button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden">
          {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Caricamento...</div>}
          {!loading && traps.length === 0 && (
            <div className="text-center py-12 text-[var(--text-secondary)]">
              Nessun trap SNMP ricevuto.<br />
              <span className="text-xs">
                Configura i dispositivi per inviare trap all'IP del connector (UDP 162) con la community giusta.
              </span>
            </div>
          )}
          {!loading && traps.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-[var(--bg-input,rgba(0,0,0,0.15))] border-b border-[var(--bg-border)]">
                  <tr className="text-left text-[var(--text-secondary)]">
                    <th className="px-3 py-2 w-40">Timestamp</th>
                    <th className="px-3 py-2 w-32">Device</th>
                    <th className="px-3 py-2 w-28">Community</th>
                    <th className="px-3 py-2">Trap OID</th>
                  </tr>
                </thead>
                <tbody>
                  {traps.map((t, i) => (
                    <tr key={t.id || i}
                      onClick={() => setSelected(t)}
                      className={`border-b border-[var(--bg-border)] cursor-pointer hover:bg-[var(--bg-hover,rgba(255,255,255,0.03))] ${selected?.id === t.id ? "bg-cyan-500/10" : ""}`}
                      data-testid={`trap-row-${i}`}>
                      <td className="px-3 py-1.5 text-[var(--text-secondary)] whitespace-nowrap">{fmtTs(t.ts)}</td>
                      <td className="px-3 py-1.5 font-mono text-[var(--text-primary)]">{t.device_ip}</td>
                      <td className="px-3 py-1.5 text-[var(--text-secondary)]">{t.community || "—"}</td>
                      <td className="px-3 py-1.5 font-mono text-[var(--text-primary)] truncate max-w-[300px]">{t.trap_oid || "(unparsed)"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="trap-detail">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Dettaglio Trap</h3>
          {!selected && <p className="text-xs text-[var(--text-secondary)]">Seleziona un trap per visualizzare i varbinds.</p>}
          {selected && (
            <div className="space-y-3 text-xs">
              <div>
                <div className="text-[10px] uppercase text-[var(--text-secondary)]">Timestamp</div>
                <div className="text-[var(--text-primary)] font-mono">{fmtTs(selected.ts)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-[var(--text-secondary)]">Device</div>
                <div className="text-[var(--text-primary)] font-mono">{selected.device_ip}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-[var(--text-secondary)]">Trap OID</div>
                <div className="text-[var(--text-primary)] font-mono break-all">{selected.trap_oid || "—"}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-[var(--text-secondary)]">Varbinds</div>
                {selected.varbinds && Object.keys(selected.varbinds || {}).length > 0 ? (
                  <pre className="bg-black/30 p-2 rounded border border-[var(--bg-border)] text-[10px] overflow-x-auto text-emerald-300">
                    {JSON.stringify(selected.varbinds, null, 2)}
                  </pre>
                ) : <div className="text-[var(--text-secondary)]">Nessun varbind parsato</div>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
