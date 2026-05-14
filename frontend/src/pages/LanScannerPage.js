import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Scanner LAN — versione web (NOC Center).
 *
 * Avvia uno scan ICMP+ARP+NBNS sull'agent Connector selezionato e
 * mostra i risultati in tempo reale tramite polling REST (1s).
 * Risolve definitivamente i problemi della UI desktop Win32:
 * niente "Non risponde", visibile anche da cellulare/tablet.
 */
export default function LanScannerPage() {
  const token = localStorage.getItem("noc_token");
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [cidr, setCidr] = useState("");
  const [filter, setFilter] = useState("");

  const [scanId, setScanId] = useState(null);
  const [run, setRun] = useState(null);
  const [starting, setStarting] = useState(false);

  const pollRef = useRef(null);

  // Carica lista agent connessi.
  const refreshAgents = useCallback(() => {
    axios.get(`${API}/api/agents`, { headers })
      .then((r) => {
        const list = Array.isArray(r.data?.agents) ? r.data.agents : [];
        // Mostriamo solo quelli "live" (WS connesso) — gli offline non possono scansionare.
        const live = list.filter((a) => a.live);
        setAgents(live);
        if (!selectedAgent && live.length > 0) {
          setSelectedAgent(live[0].agent_id);
        }
      })
      .catch(() => {
        toast.error("Impossibile caricare la lista agent. Sei admin?");
      });
  }, [headers, selectedAgent]);

  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  // Polling stato scan ogni 1s finché running.
  useEffect(() => {
    if (!scanId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await axios.get(`${API}/api/lan-scans/${scanId}`, { headers });
        if (cancelled) return;
        setRun(r.data);
        if (r.data?.status && r.data.status !== "running") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      } catch (_e) {
        // ignore singoli fail di polling
      }
    };
    tick();
    pollRef.current = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [scanId, headers]);

  const startScan = async () => {
    if (!selectedAgent) {
      toast.error("Seleziona prima un agent");
      return;
    }
    setStarting(true);
    setRun(null);
    try {
      const r = await axios.post(
        `${API}/api/lan-scans`,
        { agent_id: selectedAgent, cidr: cidr.trim() },
        { headers },
      );
      setScanId(r.data.scan_id);
      setRun(r.data);
      toast.success(`Scan avviato su ${r.data.cidr || "subnet locale"}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore avvio scan");
    } finally {
      setStarting(false);
    }
  };

  const cancelScan = async () => {
    if (!scanId) return;
    try {
      await axios.delete(`${API}/api/lan-scans/${scanId}`, { headers });
      toast.info("Scan cancellato");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore cancellazione");
    }
  };

  const running = run?.status === "running";
  const results = useMemo(() => {
    const arr = Array.isArray(run?.results) ? run.results.slice() : [];
    arr.sort((a, b) => ipNum(a.ip) - ipNum(b.ip));
    if (!filter.trim()) return arr;
    const q = filter.toLowerCase();
    return arr.filter((r) =>
      [r.ip, r.hostname, r.mac, r.vendor]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    );
  }, [run, filter]);

  const aliveCount = results.filter((r) => r.status === "alive").length;
  const arpCount = results.filter((r) => r.status === "arp-only").length;
  const pct = run?.progress?.total
    ? Math.round((run.progress.done / run.progress.total) * 100)
    : 0;

  return (
    <div className="p-6 space-y-5 text-[var(--text-primary,#1a1a2a)]" data-testid="lan-scanner-page">
      <header>
        <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary,#64748b)]">
          Network discovery on-demand
        </div>
        <h1 className="text-2xl font-bold tracking-tight">Scanner LAN</h1>
        <p className="text-sm text-[var(--text-secondary,#64748b)] mt-1 max-w-2xl">
          Lancia uno scan attivo (ICMP nativo + ARP + NBNS + reverse DNS) tramite un Connector
          Windows. Risultati live, niente UI desktop bloccata.
        </p>
      </header>

      {/* Controlli */}
      <div className="rounded-xl border border-[var(--border,#e5e7eb)] bg-white p-5 shadow-sm space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-[2fr_2fr_auto_auto] gap-3 items-end">
          <div>
            <label className="text-xs text-[var(--text-secondary,#64748b)]">
              Agent Connector ({agents.length} live)
            </label>
            <select
              data-testid="lan-scan-agent"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              disabled={running}
              className="mt-1 w-full rounded-md border border-[var(--border,#e5e7eb)] px-3 py-2 text-sm bg-white"
            >
              {agents.length === 0 && <option value="">(nessun agent connesso)</option>}
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.hostname || a.agent_id.slice(0, 8)} · {a.client_id?.slice(0, 8) || "no-client"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-[var(--text-secondary,#64748b)]">
              CIDR target (vuoto = auto-detect)
            </label>
            <input
              data-testid="lan-scan-cidr"
              value={cidr}
              onChange={(e) => setCidr(e.target.value)}
              placeholder="es. 192.168.1.0/24"
              disabled={running}
              className="mt-1 w-full rounded-md border border-[var(--border,#e5e7eb)] px-3 py-2 text-sm font-mono"
            />
          </div>
          {!running ? (
            <button
              data-testid="lan-scan-start"
              onClick={startScan}
              disabled={starting || !selectedAgent}
              className="px-5 py-2 rounded-md bg-[#1040e0] text-white text-sm font-medium hover:bg-[#0d34b8] disabled:opacity-50 transition-colors"
            >
              {starting ? "Avvio…" : "▶ Avvia scan"}
            </button>
          ) : (
            <button
              data-testid="lan-scan-cancel"
              onClick={cancelScan}
              className="px-5 py-2 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              ■ Annulla
            </button>
          )}
          <button
            onClick={refreshAgents}
            disabled={running}
            title="Ricarica lista agent"
            className="px-3 py-2 rounded-md border border-[var(--border,#e5e7eb)] text-sm hover:bg-slate-50"
          >
            ↻
          </button>
        </div>

        {/* Progress + stats */}
        {(running || run?.status === "done" || run?.status === "error") && (
          <div className="space-y-2" data-testid="lan-scan-progress">
            <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${run?.status === "error" ? "bg-red-500" : "bg-emerald-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="text-xs font-mono flex flex-wrap gap-4 text-[var(--text-secondary,#64748b)]">
              <span>
                {running ? "● in corso" : run?.status === "error" ? "✗ errore" : "✓ completato"}
              </span>
              <span>
                {run?.progress?.done ?? 0}/{run?.progress?.total ?? 0} probe
              </span>
              <span className="text-emerald-600">● {aliveCount} alive</span>
              {arpCount > 0 && <span className="text-amber-600">◐ {arpCount} arp-only</span>}
              <span>cidr: {run?.cidr || "—"}</span>
              {run?.error && <span className="text-red-600">errore: {run.error}</span>}
            </div>
          </div>
        )}
      </div>

      {/* Tabella risultati */}
      <div className="rounded-xl border border-[var(--border,#e5e7eb)] bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border,#e5e7eb)]">
          <h2 className="font-semibold">Risultati ({results.length})</h2>
          <input
            data-testid="lan-scan-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="filtra: ip, hostname, mac…"
            className="px-3 py-1.5 rounded-md border border-[var(--border,#e5e7eb)] text-xs w-64"
          />
        </div>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-sm" data-testid="lan-scan-table">
            <thead className="bg-slate-50 sticky top-0 text-xs uppercase tracking-wider text-[var(--text-secondary,#64748b)]">
              <tr>
                <th className="text-left px-4 py-2 w-24">Stato</th>
                <th className="text-left px-4 py-2 font-mono w-36">IP</th>
                <th className="text-left px-4 py-2 w-20">RTT</th>
                <th className="text-left px-4 py-2">Hostname</th>
                <th className="text-left px-4 py-2 font-mono">MAC</th>
                <th className="text-left px-4 py-2">Vendor</th>
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-[var(--text-secondary,#64748b)]">
                    {running
                      ? "Scan in corso, primi risultati in arrivo…"
                      : run
                      ? "Nessun host trovato."
                      : "Avvia uno scan per iniziare."}
                  </td>
                </tr>
              ) : (
                results.map((r) => (
                  <tr
                    key={r.ip}
                    className="border-t border-[var(--border,#e5e7eb)] hover:bg-slate-50"
                    data-testid={`lan-scan-row-${r.ip}`}
                  >
                    <td className="px-4 py-1.5">
                      {r.status === "alive" ? (
                        <span className="text-emerald-600 font-medium">● alive</span>
                      ) : r.status === "arp-only" ? (
                        <span className="text-amber-600 font-medium">◐ arp</span>
                      ) : (
                        <span className="text-slate-400">○ {r.status}</span>
                      )}
                    </td>
                    <td className="px-4 py-1.5 font-mono">{r.ip}</td>
                    <td className="px-4 py-1.5 font-mono text-xs text-[var(--text-secondary,#64748b)]">
                      {r.rtt_ms >= 0 ? `${r.rtt_ms} ms` : ""}
                    </td>
                    <td className="px-4 py-1.5">{r.hostname || ""}</td>
                    <td className="px-4 py-1.5 font-mono text-xs">{r.mac || ""}</td>
                    <td className="px-4 py-1.5 text-xs">{r.vendor || ""}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// Confronto numerico IPv4 per ordinamento stabile.
function ipNum(s) {
  if (!s) return 0;
  const m = String(s).split(".").map(Number);
  if (m.length !== 4 || m.some((n) => Number.isNaN(n))) return 0;
  return ((m[0] << 24) >>> 0) + ((m[1] << 16) >>> 0) + ((m[2] << 8) >>> 0) + m[3];
}
