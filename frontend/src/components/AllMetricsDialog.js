/**
 * AllMetricsDialog — modale "Tutte le metriche" usata sia da DeviceInfoCard
 * (modal Scheda Dispositivo nella pagina cliente) sia da DeviceDetailPanel
 * (clic della lente nella pagina globale Dispositivi).
 *
 * Carica `/api/devices/by-ip/{ip}/info-card` e mostra:
 *   - vendor_metrics_full (raw SNMP key:value)
 *   - raw_data (snapshot poll)
 * con search/JSON view/copy.
 */
import { useState, useEffect } from "react";
import axios from "axios";
import { ChartLineUp, MagnifyingGlass, X as XIcon, Copy as CopyIcon, CircleNotch } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function AllMetricsDialog({ deviceIp, deviceLabel = null, onClose }) {
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [view, setView] = useState("table");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!deviceIp) return;
    setLoading(true);
    setError(null);
    axios.get(`${API}/api/devices/by-ip/${encodeURIComponent(deviceIp)}/info-card`)
      .then(r => setCard(r.data))
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, [deviceIp]);

  const vm = card?.vendor_metrics_full || {};
  const raw = card?.raw_data || {};

  const flatten = (obj, prefix = "") => {
    const entries = [];
    Object.entries(obj || {}).forEach(([k, v]) => {
      const fullKey = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        const subEntries = flatten(v, fullKey);
        if (subEntries.length === 0) entries.push([fullKey, "{}"]);
        else entries.push(...subEntries);
      } else {
        entries.push([fullKey, v]);
      }
    });
    return entries;
  };

  const allFlat = [
    ...flatten(vm).map(([k, v]) => [`vendor_metrics.${k}`, v]),
    ...flatten(raw).map(([k, v]) => [`poll.${k}`, v]),
  ];
  const filtered = search
    ? allFlat.filter(([k, v]) => {
        const s = search.toLowerCase();
        return k.toLowerCase().includes(s) || String(v).toLowerCase().includes(s);
      })
    : allFlat;

  const fmtValue = (v) => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (Array.isArray(v) || typeof v === "object") return JSON.stringify(v);
    return String(v);
  };

  const copyJson = () => {
    const blob = JSON.stringify({ vendor_metrics: vm, raw_data: raw }, null, 2);
    navigator.clipboard?.writeText(blob).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm p-2 md:p-6"
      onClick={onClose} data-testid="all-metrics-dialog">
      <div className="w-full max-w-5xl max-h-[90vh] flex flex-col bg-[var(--bg-card)] border border-[var(--bg-border)] rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--bg-border)] gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <ChartLineUp size={18} className="text-cyan-400" weight="duotone" />
            <h3 className="text-sm font-bold text-[var(--text-primary)] truncate">
              Tutte le metriche — {deviceLabel || deviceIp}
            </h3>
            {!loading && !error && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-mono flex-shrink-0">
                {filtered.length}/{allFlat.length}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {!loading && !error && (
              <>
                <button onClick={() => setView(view === "table" ? "json" : "table")}
                  className="px-2 py-1 text-[10px] rounded border border-[var(--bg-border)] hover:bg-white/5">
                  {view === "table" ? "JSON" : "Tabella"}
                </button>
                <button onClick={copyJson} className="px-2 py-1 text-[10px] rounded border border-[var(--bg-border)] hover:bg-white/5 flex items-center gap-1">
                  <CopyIcon size={11} /> {copied ? "Copiato" : "Copia"}
                </button>
              </>
            )}
            <button onClick={onClose} className="p-1.5 rounded hover:bg-white/5 text-[var(--text-secondary)]"
              data-testid="all-metrics-close-btn">
              <XIcon size={16} />
            </button>
          </div>
        </div>

        {loading && (
          <div className="flex flex-1 items-center justify-center py-16">
            <CircleNotch size={28} className="animate-spin text-cyan-400" />
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center py-16 px-8 text-center gap-3">
            <span className="text-rose-400 text-sm">Impossibile caricare le metriche</span>
            <code className="text-[10px] text-rose-300 font-mono bg-rose-500/10 border border-rose-500/30 px-3 py-1.5 rounded">
              {error}
            </code>
            <p className="text-[11px] text-[var(--text-muted)] max-w-md">
              Probabilmente il device non e` ancora stato pollato o non e` in <code>device_poll_status</code>.
              Verifica che il connector sia attivo e che il device sia nella lista managed_devices.
            </p>
          </div>
        )}

        {!loading && !error && (
          <>
            <div className="px-4 py-2 border-b border-[var(--bg-border)] bg-black/20 flex items-center gap-2">
              <MagnifyingGlass size={14} className="text-[var(--text-secondary)] flex-shrink-0" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Cerca chiave o valore (es: cpu, temp, disk)..."
                className="flex-1 bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-secondary)] focus:outline-none"
                data-testid="all-metrics-search"
                autoFocus
              />
              {search && (
                <button onClick={() => setSearch("")} className="text-[var(--text-secondary)] hover:text-white">
                  <XIcon size={12} />
                </button>
              )}
            </div>

            <div className="flex-1 overflow-auto">
              {view === "json" ? (
                <pre className="text-[11px] font-mono text-cyan-100/90 p-4 whitespace-pre-wrap break-all">
                  {JSON.stringify({ vendor_metrics: vm, raw_data: raw }, null, 2)}
                </pre>
              ) : (
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-[var(--bg-card)] border-b border-[var(--bg-border)] z-10">
                    <tr>
                      <th className="text-left px-4 py-2 text-[10px] uppercase text-[var(--text-secondary)] font-semibold">Chiave</th>
                      <th className="text-left px-4 py-2 text-[10px] uppercase text-[var(--text-secondary)] font-semibold">Valore</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="px-4 py-8 text-center text-[var(--text-secondary)]">
                          {search ? `Nessun risultato per "${search}"` : "Nessuna metrica disponibile per questo device"}
                        </td>
                      </tr>
                    ) : (
                      filtered.map(([k, v], i) => {
                        const isVendor = k.startsWith("vendor_metrics.");
                        const formatted = fmtValue(v);
                        const isLong = formatted.length > 60;
                        return (
                          <tr key={i} className="border-b border-[var(--bg-border)]/30 hover:bg-white/5">
                            <td className="px-4 py-1.5 align-top">
                              <code className={`text-[10px] font-mono ${isVendor ? "text-cyan-300" : "text-amber-200"}`}>
                                {k}
                              </code>
                            </td>
                            <td className={`px-4 py-1.5 font-mono text-[10px] text-[var(--text-primary)] align-top ${isLong ? "break-all" : ""}`}>
                              {formatted}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              )}
            </div>

            <div className="px-4 py-2 border-t border-[var(--bg-border)] text-[10px] text-[var(--text-secondary)]">
              <span className="text-cyan-300">vendor_metrics.*</span> = SNMP vendor-specific |{" "}
              <span className="text-amber-200">poll.*</span> = ultimo snapshot raw del polling
            </div>
          </>
        )}
      </div>
    </div>
  );
}
