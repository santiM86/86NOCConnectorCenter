import { useEffect, useState } from "react";
import axios from "axios";
import { Power, Warning, PlugsConnected, Question, CircleNotch, ArrowClockwise, ShieldCheck } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

const VERDICT_UI = {
  intentional: { cls: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10", Icon: Power },
  crash: { cls: "text-red-300 border-red-500/40 bg-red-500/10", Icon: Warning },
  disconnected: { cls: "text-amber-300 border-amber-500/40 bg-amber-500/10", Icon: PlugsConnected },
  reachable_elsewhere: { cls: "text-sky-300 border-sky-500/40 bg-sky-500/10", Icon: ShieldCheck },
  unknown: { cls: "text-slate-300 border-slate-500/40 bg-slate-500/10", Icon: Question },
};
const LEVEL_DOT = { ok: "bg-emerald-400", warn: "bg-amber-400", crit: "bg-red-400", info: "bg-sky-400", na: "bg-slate-600" };

export default function ShutdownDiagnosis({ deviceIp, clientId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const token = localStorage.getItem("noc_token");
      const res = await axios.get(`${API}/api/devices/shutdown-diagnosis/${deviceIp}`, {
        params: clientId ? { client_id: clientId } : {}, headers: { Authorization: `Bearer ${token}` },
      });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Diagnosi non disponibile");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [deviceIp, clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="mt-2 text-[11px] text-[var(--text-muted)]" data-testid="shutdown-diag-loading"><CircleNotch size={12} className="animate-spin inline mr-1" />Analisi spegnimento…</div>;
  if (error) return <div className="mt-2 text-[11px] text-amber-300" data-testid="shutdown-diag-error">{error}</div>;
  if (!data || data.verdict === "online") return null;

  const ui = VERDICT_UI[data.verdict] || VERDICT_UI.unknown;
  return (
    <div className="mt-2 rounded-md border border-[var(--bg-border)] overflow-hidden" data-testid="shutdown-diagnosis">
      <div className={`flex items-center justify-between gap-2 px-3 py-2 border-b ${ui.cls}`} data-testid="shutdown-diag-verdict">
        <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide">
          <ui.Icon size={14} weight="bold" /> {data.label}
          {data.confidence > 0 && <span className="text-[10px] font-mono font-normal opacity-80" data-testid="shutdown-diag-confidence">{data.confidence}%</span>}
        </span>
        <button onClick={load} className="text-[10px] opacity-70 hover:opacity-100 flex items-center gap-1" data-testid="shutdown-diag-refresh"><ArrowClockwise size={11} /> Ricalcola</button>
      </div>
      <p className="px-3 pt-2 text-[11px] text-[var(--text-secondary)] leading-snug" data-testid="shutdown-diag-summary">{data.summary}</p>
      <div className="px-3 py-2 space-y-1.5">
        {(data.evidence || []).map((ev, i) => (
          <div key={ev.kind || i} className="flex items-start gap-2" data-testid={`shutdown-diag-evidence-${ev.kind}`}>
            <span className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${LEVEL_DOT[ev.level] || LEVEL_DOT.na}`} />
            <div className="min-w-0">
              <p className="text-[11px] text-[var(--text-primary)] leading-snug">{ev.title}{ev.where && <span className="text-[var(--text-muted)] font-mono"> · {ev.where}</span>}</p>
              <p className="text-[10px] text-[var(--text-muted)] leading-snug">{ev.text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
