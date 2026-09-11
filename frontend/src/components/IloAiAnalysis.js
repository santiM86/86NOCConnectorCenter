import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Sparkle, CircleNotch, CaretDown, CaretUp, Clock } from "@phosphor-icons/react";

const RISK = {
  ok: { label: "OK", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40" },
  low: { label: "BASSO", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40" },
  medium: { label: "MEDIO", cls: "text-amber-300 bg-amber-500/15 border-amber-500/40" },
  high: { label: "ALTO", cls: "text-orange-300 bg-orange-500/15 border-orange-500/40" },
  critical: { label: "CRITICO", cls: "text-red-300 bg-red-500/15 border-red-500/40" },
  unknown: { label: "N/D", cls: "text-slate-300 bg-slate-500/15 border-slate-500/40" },
};
const WHEN_CLS = { subito: "text-red-300", "entro 7 giorni": "text-amber-300", "prossima manutenzione": "text-sky-300" };

function List({ title, items, render, testid }) {
  if (!items || items.length === 0) return null;
  return (
    <div data-testid={testid}>
      <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{title}</p>
      <ul className="space-y-1">{items.map((it, i) => <li key={i} className="text-[11px] leading-snug">{render(it)}</li>)}</ul>
    </div>
  );
}

export default function IloAiAnalysis({ ip, clientId }) {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState(true);
  const [showHist, setShowHist] = useState(false);

  const load = async () => {
    try {
      const r = await axios.get(`${API}/servers/ilo-ai-analysis/${ip}`, { params: { client_id: clientId } });
      setLatest(r.data?.latest || null); setHistory(r.data?.history || []);
    } catch { /* silenzioso */ }
  };
  useEffect(() => { load(); }, [ip, clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setRunning(true);
    try {
      const r = await axios.post(`${API}/servers/ilo-ai-analysis/${ip}`, null, { params: { client_id: clientId }, timeout: 180000 });
      setLatest(r.data); setHistory(h => [r.data, ...h].slice(0, 10)); setOpen(true);
      toast.success(`Analisi AI completata in ${r.data.duration_s}s`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Analisi AI fallita");
    } finally { setRunning(false); }
  };

  const res = latest?.result;
  const risk = RISK[latest?.risk_level] || RISK.unknown;

  return (
    <div className="rounded-md border border-indigo-500/30 bg-indigo-500/[0.04]" data-testid={`ilo-ai-${ip}`}>
      <div className="flex items-center justify-between px-3 py-2 gap-2">
        <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-indigo-300" data-testid={`ilo-ai-toggle-${ip}`}>
          <Sparkle size={13} weight="fill" /> Analisi AI log hardware
          {latest && <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${risk.cls}`} data-testid={`ilo-ai-risk-${ip}`}>RISCHIO {risk.label}</span>}
          {latest && <span className="text-[9px] font-normal normal-case tracking-normal text-[var(--text-muted)] flex items-center gap-1"><Clock size={10} /> {new Date(latest.created_at).toLocaleString("it-IT")} · {latest.trigger === "auto" ? "automatica" : "manuale"}</span>}
          {open ? <CaretUp size={11} /> : <CaretDown size={11} />}
        </button>
        <button onClick={run} disabled={running}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-60 transition-colors"
          data-testid={`ilo-ai-run-${ip}`}>
          {running ? <><CircleNotch size={12} className="animate-spin" /> L'AI sta analizzando…</> : <><Sparkle size={12} weight="fill" /> {latest ? "Rianalizza" : "Analisi AI"}</>}
        </button>
      </div>
      {open && (
        <div className="border-t border-indigo-500/20 px-3 py-2 space-y-3" data-testid={`ilo-ai-body-${ip}`}>
          {!latest && !running && (
            <p className="text-[11px] text-[var(--text-muted)]">Nessuna analisi ancora. Premi "Analisi AI": il modello legge gli eventi IML/SEL, i sensori live, dischi, PSU e gli alert attivi e restituisce diagnosi, pattern e azioni prioritarie in italiano.</p>
          )}
          {running && !latest && <p className="text-[11px] text-indigo-200 flex items-center gap-2"><CircleNotch size={13} className="animate-spin" /> Lettura eventi e correlazione con lo stato hardware…</p>}
          {res && (
            <>
              <div>
                <p className="text-sm font-semibold text-[var(--text-primary)] leading-snug" data-testid={`ilo-ai-headline-${ip}`}>{res.headline}</p>
                <p className="text-[11px] text-[var(--text-secondary)] mt-1 leading-snug" data-testid={`ilo-ai-diagnosis-${ip}`}>{res.diagnosis}</p>
                {res.confidence != null && <p className="text-[9px] text-[var(--text-muted)] mt-0.5">Confidenza {res.confidence}% · {latest.events_count} eventi analizzati · {latest.unrepaired} da riparare · {latest.model}</p>}
              </div>
              <List title="Azioni consigliate" items={res.actions} testid={`ilo-ai-actions-${ip}`} render={a => (
                <div className="flex items-start gap-2">
                  <span className="font-mono text-[10px] w-4 text-indigo-300 flex-shrink-0">{a.priority}.</span>
                  <div>
                    <span className="text-[var(--text-primary)]">{a.action}</span>
                    {a.component && <span className="text-[var(--text-muted)]"> · {a.component}</span>}
                    {a.when && <span className={`ml-1 text-[9px] uppercase font-bold ${WHEN_CLS[a.when] || "text-[var(--text-muted)]"}`}>{a.when}</span>}
                    {a.why && <p className="text-[10px] text-[var(--text-muted)]">{a.why}</p>}
                  </div>
                </div>
              )} />
              <List title="Pattern rilevati" items={res.patterns} testid={`ilo-ai-patterns-${ip}`} render={p => (
                <div><span className="text-[var(--text-primary)]">{p.title}</span>{p.occurrences ? <span className="text-[var(--text-muted)]"> ×{p.occurrences}</span> : null}<p className="text-[10px] text-[var(--text-muted)]">{p.detail}</p></div>
              )} />
              <div className="grid md:grid-cols-2 gap-3">
                <List title="Da monitorare" items={res.watch} testid={`ilo-ai-watch-${ip}`} render={w => <span className="text-[var(--text-secondary)]">• {w}</span>} />
                <List title="Rumore da ignorare" items={res.ignore} testid={`ilo-ai-ignore-${ip}`} render={w => <span className="text-[var(--text-muted)] line-through decoration-slate-500/60">{w}</span>} />
              </div>
              {history.length > 1 && (
                <div>
                  <button onClick={() => setShowHist(s => !s)} className="text-[10px] text-indigo-300 hover:underline" data-testid={`ilo-ai-history-toggle-${ip}`}>
                    {showHist ? "Nascondi" : "Mostra"} storico analisi ({history.length})
                  </button>
                  {showHist && (
                    <ul className="mt-1 space-y-0.5" data-testid={`ilo-ai-history-${ip}`}>
                      {history.map(h => (
                        <li key={h.id} className="text-[10px] text-[var(--text-muted)] flex items-center gap-2 cursor-pointer hover:text-[var(--text-primary)]" onClick={() => setLatest(h)}>
                          <span className={`px-1 rounded border text-[8px] font-bold ${(RISK[h.risk_level] || RISK.unknown).cls}`}>{(RISK[h.risk_level] || RISK.unknown).label}</span>
                          {new Date(h.created_at).toLocaleString("it-IT")} · {h.trigger === "auto" ? "auto" : "manuale"} · {h.result?.headline}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
