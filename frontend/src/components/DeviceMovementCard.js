import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { ArrowsLeftRight, Warning, Eye } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * DeviceMovementCard — mostra spostamenti recenti di MAC tra porte/switch.
 * Anomalia rilevata server-side quando un MAC visto sulla "home port" (>=50 hits)
 * ricompare su una porta differente. Utile come widget security/forensics.
 *
 * Props:
 *   clientId: string | undefined  → se passato filtra al cliente
 *   days: number = 7              → finestra temporale
 *   compact: bool = false         → versione mini per dashboard
 */
export default function DeviceMovementCard({ clientId, days = 7, compact = false }) {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({ count: 0, active: 0 });
  const [loading, setLoading] = useState(true);
  const token = localStorage.getItem("noc_token");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (clientId) params.set("client_id", clientId);
      const r = await axios.get(`${API}/api/security/device-movements?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setItems(r.data.items || []);
      setStats({ count: r.data.count, active: r.data.active });
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [clientId, days, token]);

  useEffect(() => { reload(); const i = setInterval(reload, 30000); return () => clearInterval(i); }, [reload]);

  const fmtTime = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
    catch { return iso; }
  };

  if (loading && items.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 text-[11px] text-[var(--text-muted)]">
        Caricamento spostamenti…
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden" data-testid="device-movement-card">
      <div className="flex items-center justify-between p-3 border-b border-[var(--bg-border)]">
        <div className="flex items-center gap-2">
          <ArrowsLeftRight size={16} className="text-amber-400" />
          <h3 className="text-sm font-bold">Spostamenti dispositivi</h3>
          <span className="text-[10px] text-[var(--text-muted)]">ultimi {days}gg</span>
        </div>
        {stats.active > 0 && (
          <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold">
            {stats.active} attivi
          </span>
        )}
      </div>
      {items.length === 0 ? (
        <div className="p-6 text-center text-[11px] text-[var(--text-muted)] italic">
          Nessuno spostamento rilevato. I dispositivi sono nelle loro posizioni abituali. ✓
        </div>
      ) : (
        <ul className="divide-y divide-[var(--bg-border)]/50">
          {items.slice(0, compact ? 5 : 50).map((a) => (
            <li key={a.id} className="p-3 hover:bg-[var(--bg-hover)]/30 transition-colors" data-testid={`movement-item-${a.id}`}>
              <div className="flex items-start gap-3">
                <Warning size={14} weight="fill" className="text-amber-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-[var(--text-primary)] truncate">
                    {a.device_name || a.mac}
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-0.5">
                    {a.from_switch} porta {a.from_port}
                    {" → "}
                    <span className="text-amber-300">{a.to_switch} porta {a.to_port}</span>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] mt-1">
                    MAC {a.mac} · {fmtTime(a.created_at)}
                  </div>
                </div>
                <button
                  className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-0.5 flex-shrink-0"
                  title="Visualizza storia spostamenti"
                  onClick={async () => {
                    try {
                      const r = await axios.get(
                        `${API}/api/security/device-history/${a.client_id}/${a.mac}`,
                        { headers: { Authorization: `Bearer ${token}` } },
                      );
                      const lines = r.data.locations.map((l, i) =>
                        `${i + 1}. ${l.switch_ip} porta ${l.port} · visto ${l.count} volte`,
                      ).join("\n");
                      alert(`Storia ${r.data.device_name}\nMAC: ${r.data.mac}\nTotale osservazioni: ${r.data.total_observations}\n\nLocations:\n${lines}`);
                    } catch (e) { /* ignore */ }
                  }}
                  data-testid={`movement-history-${a.id}`}
                >
                  <Eye size={11} /> storia
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
