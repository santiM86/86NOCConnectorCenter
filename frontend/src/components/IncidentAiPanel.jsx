import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Brain, ShieldWarning, ListNumbers, Clock, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const VERDICT = {
  vero_positivo: ["Vero positivo", "text-red-300 bg-red-500/15 border-red-500/30"],
  probabile: ["Probabile minaccia", "text-orange-300 bg-orange-500/15 border-orange-500/30"],
  da_verificare: ["Da verificare", "text-amber-300 bg-amber-500/15 border-amber-500/30"],
  falso_positivo: ["Falso positivo", "text-emerald-300 bg-emerald-500/15 border-emerald-500/30"],
};

const Block = ({ icon: Icon, title, children, tid }) => (
  <div data-testid={tid}>
    <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1"><Icon size={11} /> {title}</div>
    {children}
  </div>
);

export default function IncidentAiPanel({ incident, onUpdated }) {
  const [busy, setBusy] = useState(false);
  const inv = incident.ai_investigation;
  const r = inv?.result || {};
  const run = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/incidents/${incident.id}/investigate`);
      toast.success("Indagine AI completata");
      onUpdated && onUpdated();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Indagine AI non riuscita");
    } finally {
      setBusy(false);
    }
  };
  const [vLabel, vCls] = VERDICT[r.verdict] || ["", ""];
  return (
    <div className="rounded-lg border border-violet-500/30 bg-violet-500/[0.04] p-3 space-y-3" data-testid="incident-ai-panel">
      <div className="flex items-center gap-2">
        <Brain size={15} className="text-violet-300" weight="fill" />
        <span className="text-[11px] font-bold uppercase tracking-wider text-violet-200">Indagine SOC con AI</span>
        {(incident.alert_ids || []).length > 0 && <span className="text-[10px] text-[var(--text-muted)]">{incident.alert_ids.length} alert correlati</span>}
        <Button size="sm" onClick={run} disabled={busy} className="ml-auto h-7 text-[11px] gap-1 bg-violet-600 hover:bg-violet-500" data-testid="incident-ai-run-btn">
          <MagnifyingGlass size={12} /> {busy ? "Indagine in corso…" : inv ? "Rifai indagine" : "Indaga con AI"}
        </Button>
      </div>
      {!inv ? (
        <p className="text-[11px] text-[var(--text-muted)]" data-testid="incident-ai-empty">L'AI ricostruisce la cronologia dagli alert, individua la causa probabile e propone le azioni in ordine di priorità.</p>
      ) : (
        <>
          <div className="flex items-start gap-2 flex-wrap">
            <h3 className="text-[13px] font-semibold text-white flex-1 min-w-0" data-testid="incident-ai-headline">{r.headline}</h3>
            {vLabel && <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${vCls}`} data-testid="incident-ai-verdict">{vLabel}</span>}
            {r.confidence != null && <span className="text-[10px] text-[var(--text-muted)]">confidenza {r.confidence}%</span>}
          </div>
          {r.summary && <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed" data-testid="incident-ai-summary">{r.summary}</p>}
          {r.root_cause && <Block icon={ShieldWarning} title="Causa probabile" tid="incident-ai-root"><p className="text-[11px] text-neutral-200">{r.root_cause}</p></Block>}
          {(r.actions || []).length > 0 && (
            <Block icon={ListNumbers} title="Azioni consigliate" tid="incident-ai-actions">
              <ol className="space-y-1">
                {[...r.actions].sort((a, b) => (a.priority || 9) - (b.priority || 9)).map((a, i) => (
                  <li key={i} className="text-[11px] text-neutral-100 flex gap-2" data-testid={`incident-ai-action-${i}`}>
                    <span className="shrink-0 w-4 h-4 rounded-full bg-violet-500/25 text-violet-200 text-[9px] font-bold flex items-center justify-center">{i + 1}</span>
                    <span>{a.action}{a.why && <span className="block text-[10px] text-[var(--text-muted)]">{a.why}</span>}</span>
                  </li>
                ))}
              </ol>
            </Block>
          )}
          {(r.evidence || []).length > 0 && (
            <Block icon={ShieldWarning} title="Prove" tid="incident-ai-evidence">
              <ul className="list-disc pl-4 space-y-0.5">{r.evidence.map((e, i) => <li key={i} className="text-[10px] text-[var(--text-secondary)]">{e}</li>)}</ul>
            </Block>
          )}
          {(r.timeline || []).length > 0 && (
            <Block icon={Clock} title="Cronologia ricostruita" tid="incident-ai-timeline">
              <ul className="space-y-0.5">{r.timeline.map((t, i) => <li key={i} className="text-[10px] text-[var(--text-secondary)]"><span className="font-mono text-violet-200">{t.at}</span> — {t.event}</li>)}</ul>
            </Block>
          )}
          <p className="text-[9px] text-[var(--text-muted)]">Indagine del {new Date(inv.at).toLocaleString("it-IT")} · {inv.by} · {inv.alerts_analyzed} alert analizzati</p>
        </>
      )}
    </div>
  );
}
