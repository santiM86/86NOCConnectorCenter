import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";

const confCls = c => c >= 90 ? "text-emerald-300" : c >= 80 ? "text-amber-300" : "text-red-300";

export default function FusionEvidence({ ip, clientId }) {
  const [v, setV] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    setV(null);
    axios.get(`${API}/fusion/device/${encodeURIComponent(ip)}`, { params: clientId ? { client_id: clientId } : {} })
      .then(r => setV(r.data)).catch(e => setErr(e.response?.data?.detail || "Errore"));
  }, [ip, clientId]);
  if (err) return <p className="text-[10px] text-red-300">{err}</p>;
  if (!v) return <p className="text-[10px] text-[var(--text-muted)]">Raccolta prove…</p>;
  return (
    <div className="space-y-2" data-testid={`fusion-evidence-${ip}`}>
      <p className="text-[12px]"><b className="text-[var(--text-primary)]">{v.label}</b> <span className={`font-mono font-bold ${confCls(v.confidence)}`} data-testid={`fusion-confidence-${ip}`}>{v.confidence}%</span>
        <span className="text-[10px] text-[var(--text-muted)]"> · {v.reasoning}</span></p>
      <ul className="space-y-1">
        {(v.evidence || []).map((e, i) => {
          const best = Object.entries(e.votes || {}).sort((a, b) => b[1] - a[1])[0];
          return (
            <li key={i} className="text-[10px] flex items-start gap-2 border-l-2 border-cyan-500/40 pl-2">
              <span className="font-mono text-[9px] px-1 rounded bg-cyan-500/15 text-cyan-200 flex-shrink-0 mt-0.5">{e.source_label}</span>
              <span><span className="text-[var(--text-primary)] font-semibold">{e.title}</span>
                {e.age_min != null && <span className="text-[var(--text-muted)]"> · {Math.round(e.age_min)} min</span>}
                <span className="block text-[var(--text-secondary)]">{e.text}</span>
                {best && <span className="text-[9px] text-[var(--text-muted)]">vota: {best[0]} +{best[1]}</span>}</span>
            </li>
          );
        })}
      </ul>
      {(v.scores) && <p className="text-[9px] text-[var(--text-muted)] font-mono">{Object.entries(v.scores).sort((a, b) => b[1] - a[1]).map(([k, s]) => `${k}=${s}`).join(" · ")}</p>}
    </div>
  );
}
