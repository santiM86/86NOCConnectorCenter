/**
 * AllMetricsDialog - modale "Tutte le metriche" usata sia da DeviceInfoCard
 * (modal Scheda Dispositivo nella pagina cliente) sia da DeviceDetailPanel
 * (clic della lente nella pagina globale Dispositivi).
 *
 * Carica `/api/devices/by-ip/{ip}/info-card` e mostra:
 *   - vendor_metrics_full (raw SNMP key:value)
 *   - raw_data (snapshot poll)
 * con search / JSON view / copy.
 *
 * FIX v2 (2026-02-13): su switch grossi (HP 5130 52G = 52 porte x 30+ OID)
 * il render di > 3000 righe in un solo tick sincrono bloccava il main thread,
 * gli overlay scuri della Dialog rimanevano sullo schermo e l'utente vedeva
 * "schermata nera" (render freeze percepito come crash).
 * Interventi:
 *   1. flatten() ora ha un Set `seen` anti-riferimento-ciclico + maxDepth=20
 *      per evitare stack overflow su strutture SNMP auto-referenzianti.
 *   2. Cap di rendering: massimo `visibleCap` righe (default 500), con toggle
 *      "Mostra tutte" se l'utente vuole davvero la lista intera.
 *   3. try/catch su JSON.stringify (vendor_metrics potrebbe avere circular).
 *   4. Ricerca ora forza il rendering di TUTTE le righe filtrate (l'utente sta
 *      cercando qualcosa di specifico, il cap non serve).
 */
import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { ChartLineUp, MagnifyingGlass, X as XIcon, Copy as CopyIcon, CircleNotch, Warning } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

// Soglia oltre cui il rendering diventa lento. Tipico switch enterprise (52G)
// genera 2000-4000 entry; desktop veloce regge bene fino a 800 righe senza lag.
const DEFAULT_VISIBLE_CAP = 500;
const MAX_FLATTEN_DEPTH = 20;

function safeFlatten(obj, prefix = "", depth = 0, seen = new WeakSet()) {
  const entries = [];
  if (depth > MAX_FLATTEN_DEPTH) {
    entries.push([prefix || "<root>", "[truncated: max depth]"]);
    return entries;
  }
  if (obj && typeof obj === "object") {
    if (seen.has(obj)) {
      entries.push([prefix || "<root>", "[circular]"]);
      return entries;
    }
    seen.add(obj);
  }
  try {
    Object.entries(obj || {}).forEach(([k, v]) => {
      const fullKey = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        const subEntries = safeFlatten(v, fullKey, depth + 1, seen);
        if (subEntries.length === 0) entries.push([fullKey, "{}"]);
        else entries.push(...subEntries);
      } else {
        entries.push([fullKey, v]);
      }
    });
  } catch (e) {
    entries.push([prefix || "<root>", `[flatten error: ${e.message}]`]);
  }
  return entries;
}

function safeStringify(obj) {
  try {
    const seen = new WeakSet();
    return JSON.stringify(obj, (_k, v) => {
      if (v && typeof v === "object") {
        if (seen.has(v)) return "[circular]";
        seen.add(v);
      }
      return v;
    }, 2);
  } catch (e) {
    return `/* Errore serializzazione JSON: ${e.message} */`;
  }
}

export default function AllMetricsDialog({ deviceIp, deviceLabel = null, onClose }) {
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [view, setView] = useState("table");
  const [copied, setCopied] = useState(false);
  const [showAll, setShowAll] = useState(false);

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

  // Flatten eseguito in useMemo per non rifarlo ad ogni render (ricerca cambia
  // spesso, flatten e' costoso su oggetti grossi).
  const allFlat = useMemo(() => {
    if (!card) return [];
    try {
      return [
        ...safeFlatten(vm).map(([k, v]) => [`vendor_metrics.${k}`, v]),
        ...safeFlatten(raw).map(([k, v]) => [`poll.${k}`, v]),
      ];
    } catch (e) {
      // Safety net: se qualcosa esplode durante il flatten, meglio un array
      // vuoto + messaggio d'errore che un white/black screen.
      return [["__error__", `flatten failed: ${e.message}`]];
    }
  }, [card]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    if (!search) return allFlat;
    const s = search.toLowerCase();
    return allFlat.filter(([k, v]) =>
      k.toLowerCase().includes(s) || String(v).toLowerCase().includes(s)
    );
  }, [allFlat, search]);

  // Cap di rendering: se la lista e' grossa e non stiamo cercando nulla,
  // mostra solo le prime N per non bloccare il main thread.
  const shouldCap = !search && !showAll && filtered.length > DEFAULT_VISIBLE_CAP;
  const visible = shouldCap ? filtered.slice(0, DEFAULT_VISIBLE_CAP) : filtered;

  const fmtValue = (v) => {
    if (v === null || v === undefined) return "-";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (Array.isArray(v) || typeof v === "object") {
      try { return JSON.stringify(v); } catch { return "[unserializable]"; }
    }
    return String(v);
  };

  const copyJson = () => {
    const blob = safeStringify({ vendor_metrics: vm, raw_data: raw });
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
              Tutte le metriche - {deviceLabel || deviceIp}
            </h3>
            {!loading && !error && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-mono flex-shrink-0">
                {visible.length}/{allFlat.length}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {!loading && !error && (
              <>
                <button onClick={() => setView(view === "table" ? "json" : "table")}
                  className="px-2 py-1 text-[10px] rounded border border-[var(--bg-border)] hover:bg-white/5"
                  data-testid="all-metrics-toggle-view">
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
              Probabilmente il device non e' ancora stato pollato o non e' in <code>device_poll_status</code>.
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

            {/* Warning cap */}
            {shouldCap && (
              <div className="px-4 py-2 border-b border-[var(--bg-border)] bg-amber-500/10 flex items-center gap-2 text-[11px]">
                <Warning size={14} className="text-amber-400 flex-shrink-0" weight="fill" />
                <span className="text-amber-200 flex-1">
                  Mostro le prime {DEFAULT_VISIBLE_CAP} di {allFlat.length} metriche per non bloccare il browser.
                  Usa la ricerca per trovare chiavi specifiche.
                </span>
                <button
                  onClick={() => setShowAll(true)}
                  className="px-2 py-1 text-[10px] rounded border border-amber-400/50 text-amber-200 hover:bg-amber-400/10 font-semibold"
                  data-testid="all-metrics-show-all"
                >
                  Mostra tutte ({allFlat.length})
                </button>
              </div>
            )}

            <div className="flex-1 overflow-auto">
              {view === "json" ? (
                <pre className="text-[11px] font-mono text-cyan-100/90 p-4 whitespace-pre-wrap break-all">
                  {safeStringify({ vendor_metrics: vm, raw_data: raw })}
                </pre>
              ) : (
                <table className="w-full text-[11px]" data-testid="all-metrics-table">
                  <thead className="sticky top-0 bg-[var(--bg-card)] border-b border-[var(--bg-border)] z-10">
                    <tr>
                      <th className="text-left px-4 py-2 text-[10px] uppercase text-[var(--text-secondary)] font-semibold">Chiave</th>
                      <th className="text-left px-4 py-2 text-[10px] uppercase text-[var(--text-secondary)] font-semibold">Valore</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="px-4 py-8 text-center text-[var(--text-secondary)]">
                          {search ? `Nessun risultato per "${search}"` : "Nessuna metrica disponibile per questo device"}
                        </td>
                      </tr>
                    ) : (
                      visible.map(([k, v], i) => {
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
