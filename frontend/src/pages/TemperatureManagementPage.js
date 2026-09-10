import { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Thermometer, RefreshCw, Eraser, Check } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
const SRC_LABEL = { device: "Override device", cliente: "Soglia cliente", profilo: "Profilo vendor", default: "Default tipo" };
const SRC_CLS = { device: "text-indigo-300 border-indigo-500/40 bg-indigo-500/10", cliente: "text-sky-300 border-sky-500/40 bg-sky-500/10", profilo: "text-amber-300 border-amber-500/40 bg-amber-500/10", default: "text-neutral-400 border-neutral-600 bg-neutral-800/40" };
const STATE_CLS = { crit: "text-red-400", warn: "text-orange-400", ok: "text-emerald-400" };

const Sel = ({ value, onChange, children, testid }) => (
  <select value={value} onChange={e => onChange(e.target.value)} data-testid={testid}
    className="h-8 px-2 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]">{children}</select>
);

export default function TemperatureManagementPage() {
  const [data, setData] = useState({ devices: [] });
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(() => new Set());
  const [fClient, setFClient] = useState("all");
  const [fType, setFType] = useState("all");
  const [fSource, setFSource] = useState("all");
  const [fState, setFState] = useState("all");
  const [warn, setWarn] = useState("");
  const [crit, setCrit] = useState("");
  const headers = { Authorization: `Bearer ${localStorage.getItem("noc_token")}` };

  const load = useCallback(() => {
    setLoading(true);
    axios.get(`${API}/api/temperature/overview`, { headers })
      .then(r => setData(r.data)).catch(() => toast.error("Errore caricamento temperature")).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load]);

  const key = d => `${d.client_id}|${d.ip}`;
  const clients = useMemo(() => [...new Map(data.devices.map(d => [d.client_id, d.client_name])).entries()].sort((a, b) => a[1].localeCompare(b[1])), [data]);
  const types = useMemo(() => [...new Set(data.devices.map(d => d.device_type))].sort(), [data]);
  const rows = useMemo(() => data.devices.filter(d =>
    (fClient === "all" || d.client_id === fClient) && (fType === "all" || d.device_type === fType) &&
    (fSource === "all" || d.source === fSource) && (fState === "all" || d.state === fState)), [data, fClient, fType, fSource, fState]);
  const allSel = rows.length > 0 && rows.every(d => sel.has(key(d)));

  const toggleAll = () => setSel(prev => { const n = new Set(prev); rows.forEach(d => allSel ? n.delete(key(d)) : n.add(key(d))); return n; });
  const toggle = d => setSel(prev => { const n = new Set(prev); const k = key(d); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const targets = () => data.devices.filter(d => sel.has(key(d))).map(d => ({ client_id: d.client_id, ip: d.ip }));

  const apply = (clear) => {
    if (!sel.size) return toast.error("Seleziona almeno un dispositivo");
    if (!clear && warn === "" && crit === "") return toast.error("Indica warn e/o crit");
    const body = clear ? { targets: targets(), clear: true } : { targets: targets(), warn: warn || null, crit: crit || null };
    axios.post(`${API}/api/temperature/bulk`, body, { headers })
      .then(r => { toast.success(clear ? `Override rimosso su ${r.data.updated} device` : `Soglie applicate a ${r.data.updated} device (${r.data.clients} clienti)`); setSel(new Set()); load(); })
      .catch(e => toast.error(e?.response?.data?.detail || "Errore"));
  };

  const counts = useMemo(() => ({ crit: rows.filter(d => d.state === "crit").length, warn: rows.filter(d => d.state === "warn").length, ovr: rows.filter(d => d.source === "device").length }), [rows]);

  return (
    <div className="space-y-4" data-testid="temperature-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] flex items-center gap-2"><Thermometer size={22} className="text-orange-400" /> Gestione Temperature</h1>
          <p className="text-sm text-[var(--text-secondary)]">Tutti i dispositivi di tutti i clienti: temperatura live, soglia effettiva e da dove arriva. Seleziona e applica in blocco.</p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-red-400 font-mono" data-testid="temp-count-crit">{counts.crit} critici</span>
          <span className="text-orange-400 font-mono" data-testid="temp-count-warn">{counts.warn} warning</span>
          <span className="text-indigo-300 font-mono">{counts.ovr} con override</span>
          <button onClick={load} className="h-8 px-3 rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] inline-flex items-center gap-1" data-testid="temp-refresh-btn"><RefreshCw size={12} /> Aggiorna</button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-3">
        <Sel value={fClient} onChange={setFClient} testid="temp-filter-client"><option value="all">Tutti i clienti</option>{clients.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</Sel>
        <Sel value={fType} onChange={setFType} testid="temp-filter-type"><option value="all">Tutti i tipi</option>{types.map(t => <option key={t} value={t}>{t}</option>)}</Sel>
        <Sel value={fSource} onChange={setFSource} testid="temp-filter-source"><option value="all">Ogni provenienza</option>{Object.entries(SRC_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Sel>
        <Sel value={fState} onChange={setFState} testid="temp-filter-state"><option value="all">Ogni stato</option><option value="crit">Sopra soglia critica</option><option value="warn">Sopra soglia warning</option><option value="ok">OK</option></Sel>
        <span className="text-xs text-[var(--text-muted)] ml-auto" data-testid="temp-selected-count">{sel.size} selezionati</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-orange-500/30 bg-orange-500/5 p-3" data-testid="temp-bulk-bar">
        <span className="text-xs font-semibold text-orange-300 mr-1">Applica ai selezionati:</span>
        <input type="number" min="0" max="150" placeholder="warn °C" value={warn} onChange={e => setWarn(e.target.value)} data-testid="temp-bulk-warn"
          className="h-8 w-24 px-2 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" />
        <input type="number" min="0" max="150" placeholder="crit °C" value={crit} onChange={e => setCrit(e.target.value)} data-testid="temp-bulk-crit"
          className="h-8 w-24 px-2 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" />
        <button onClick={() => apply(false)} disabled={!sel.size} className="h-8 px-3 text-xs font-semibold rounded-md bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-40 inline-flex items-center gap-1" data-testid="temp-bulk-apply-btn"><Check size={12} /> Imposta override</button>
        <button onClick={() => apply(true)} disabled={!sel.size} className="h-8 px-3 text-xs font-semibold rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-40 inline-flex items-center gap-1" data-testid="temp-bulk-clear-btn"><Eraser size={12} /> Rimuovi override</button>
        <span className="text-[11px] text-[var(--text-muted)]">Senza override vale: soglia cliente per tipo → profilo vendor → default tipo.</span>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-auto">
        <table className="w-full text-xs" data-testid="temp-table">
          <thead>
            <tr className="text-[9px] uppercase tracking-[0.15em] text-[var(--text-muted)] border-b border-[var(--bg-border)]">
              <th className="px-3 py-2 w-8"><input type="checkbox" checked={allSel} onChange={toggleAll} data-testid="temp-select-all" /></th>
              <th className="text-left px-3 py-2">Cliente</th><th className="text-left px-3 py-2">Dispositivo</th><th className="text-left px-3 py-2">Tipo</th>
              <th className="text-right px-3 py-2">Temp</th><th className="text-right px-3 py-2">Warn</th><th className="text-right px-3 py-2">Crit</th><th className="text-left px-3 py-2">Provenienza soglia</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="px-3 py-6 text-center text-[var(--text-muted)]">Caricamento…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-[var(--text-muted)]">Nessun dispositivo con dati temperatura</td></tr>}
            {rows.map(d => (
              <tr key={key(d)} className={`border-b border-[var(--bg-border)]/50 hover:bg-white/[0.02] ${sel.has(key(d)) ? "bg-orange-500/5" : ""}`} data-testid={`temp-row-${d.ip}`}>
                <td className="px-3 py-1.5"><input type="checkbox" checked={sel.has(key(d))} onChange={() => toggle(d)} data-testid={`temp-check-${d.ip}`} /></td>
                <td className="px-3 py-1.5 text-[var(--text-secondary)] whitespace-nowrap">{d.client_name}</td>
                <td className="px-3 py-1.5 whitespace-nowrap"><span className="text-[var(--text-primary)] font-medium">{d.name}</span> <span className="font-mono text-[var(--text-muted)]">{d.ip}</span></td>
                <td className="px-3 py-1.5 text-[var(--text-secondary)]">{d.device_type}{d.profile_key ? <span className="text-[var(--text-muted)]"> · {d.profile_key}</span> : null}</td>
                <td className={`px-3 py-1.5 text-right font-mono font-bold ${STATE_CLS[d.state]}`} data-testid="temp-value">{d.temp_c != null ? `${d.temp_c}°` : "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{d.warn_c ?? "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{d.crit_c ?? "—"}</td>
                <td className="px-3 py-1.5"><span className={`px-1.5 py-0.5 rounded border text-[10px] ${SRC_CLS[d.source]}`}>{SRC_LABEL[d.source]}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
