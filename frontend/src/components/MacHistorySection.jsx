import { useEffect, useState } from "react";
import axios from "axios";
import { ClockCounterClockwise, ArrowRight } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmt = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "medium" }); } catch { return iso; }
};

export const MacHistorySection = ({ deviceIp, clientId }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!deviceIp) return;
    axios.get(`${API}/devices/by-ip/${encodeURIComponent(deviceIp)}/mac-history`, { params: clientId ? { client_id: clientId } : {} })
      .then(({ data: d }) => setData(d)).catch(() => setData({ current_mac: null, history: [] }));
  }, [deviceIp, clientId]);

  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid="mac-history-section">
      <div className="flex items-center gap-1.5 mb-2">
        <ClockCounterClockwise size={13} weight="bold" className="text-amber-300" />
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">Storico schede di rete (MAC)</h4>
      </div>
      {!data ? (
        <p className="text-[10px] text-[var(--text-muted)]">Caricamento…</p>
      ) : (
        <>
          <div className="flex items-center justify-between text-[11px] py-1 border-b border-white/5">
            <span className="text-[var(--text-muted)]">MAC attuale</span>
            <span className="font-mono text-white" data-testid="mac-history-current">{data.current_mac ? data.current_mac.toUpperCase() : "—"}</span>
          </div>
          {data.pending && (
            <p className="text-[10px] text-amber-300/90 mt-1.5" data-testid="mac-history-pending">
              In verifica: nuovo MAC {String(data.pending.mac || "").toUpperCase()} visto {data.pending.count}× (conferma a 2 rilevazioni)
            </p>
          )}
          {data.history.length === 0 ? (
            <p className="text-[10px] text-[var(--text-muted)] mt-2" data-testid="mac-history-empty">Nessun cambio di scheda di rete registrato.</p>
          ) : (
            <ul className="mt-2 space-y-1" data-testid="mac-history-list">
              {data.history.map((h, i) => (
                <li key={`${h.at}-${i}`} className="flex items-center gap-2 text-[10px] font-mono" data-testid={`mac-history-row-${i}`}>
                  <span className="text-[var(--text-muted)] shrink-0 w-32">{fmt(h.at)}</span>
                  <span className="text-red-300/80">{String(h.from || "—").toUpperCase()}</span>
                  <ArrowRight size={10} className="text-[var(--text-muted)]" />
                  <span className="text-emerald-300">{String(h.to || "—").toUpperCase()}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
};
