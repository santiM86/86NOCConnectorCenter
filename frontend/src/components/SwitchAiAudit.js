import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Sparkle, CircleNotch, X } from "@phosphor-icons/react";

const SEV = {
  high: "text-red-300 bg-red-500/15 border-red-500/40", medium: "text-amber-300 bg-amber-500/15 border-amber-500/40",
  low: "text-sky-300 bg-sky-500/15 border-sky-500/40", info: "text-neutral-300 bg-neutral-500/15 border-neutral-500/40",
};
const TYPE = { security: "Sicurezza", hygiene: "Igiene", reliability: "Affidabilità", capacity: "Capacità", anomaly: "Anomalia" };
const scoreCls = s => s >= 80 ? "text-emerald-300" : s >= 60 ? "text-amber-300" : "text-red-300";

export default function SwitchAiAudit({ deviceIp, clientId, onSelectPort, onClose }) {
  const [latest, setLatest] = useState(null);
  const [running, setRunning] = useState(false);
  const params = clientId ? { client_id: clientId } : {};
  const url = `${API}/devices/${encodeURIComponent(deviceIp)}/switch-ports/ai-audit`;

  useEffect(() => {
    axios.get(url, { params }).then(r => setLatest(r.data?.latest || null)).catch(() => {});
  }, [deviceIp, clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setRunning(true);
    try {
      const r = await axios.post(url, null, { params, timeout: 240000 });
      setLatest(r.data);
      toast.success(`Audit AI completato in ${r.data.duration_s}s (${r.data.ports_analyzed} porte)`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Audit AI fallito");
    } finally { setRunning(false); }
  };

  const res = latest?.result;
  const Ports = ({ list, testid }) => (list || []).length ? (
    <span className="inline-flex flex-wrap gap-1" data-testid={testid}>
      {list.map(p => <button key={p} onClick={() => onSelectPort?.(p)} className="font-mono text-[9px] px-1 rounded bg-cyan-500/15 text-cyan-200 border border-cyan-500/30 hover:bg-cyan-500/30">{p}</button>)}
    </span>
  ) : null;

  return (
    <div className="noc-panel p-3 md:p-4 space-y-3 border-indigo-500/30" data-testid="switch-ai-audit">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-wider text-indigo-300">
          <Sparkle size={13} weight="fill" /> Audit AI switch
          {res?.score != null && <span className={`font-mono text-sm ${scoreCls(res.score)}`} data-testid="switch-ai-audit-score">{res.score}/100</span>}
          {latest && <span className="font-normal normal-case tracking-normal text-[9px] text-[var(--text-muted)]">{new Date(latest.created_at).toLocaleString("it-IT")} · {latest.ports_analyzed} porte</span>}
        </h3>
        <div className="flex items-center gap-2">
          <button onClick={run} disabled={running} data-testid="switch-ai-audit-run"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-60 transition-colors">
            {running ? <><CircleNotch size={12} className="animate-spin" /> L'AI analizza tutte le porte…</> : <><Sparkle size={12} weight="fill" /> {latest ? "Riesegui audit" : "Esegui audit"}</>}
          </button>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]" data-testid="switch-ai-audit-close"><X size={14} /></button>
        </div>
      </div>
      {!latest && !running && <p className="text-[11px] text-[var(--text-muted)]">L'AI legge abitudini, device collegati, PoE, velocità, flap ed etichette di tutte le porte e propone: porte da disabilitare (sicurezza), attività fuori orario sospette, cavi/negoziazioni da sistemare, etichette mancanti.</p>}
      {res && (
        <div className="space-y-3" data-testid="switch-ai-audit-body">
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)] leading-snug" data-testid="switch-ai-audit-headline">{res.headline}</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1 leading-snug">{res.summary}</p>
          </div>
          {(res.findings || []).length > 0 && (
            <ul className="space-y-1.5" data-testid="switch-ai-audit-findings">
              {res.findings.map((f, i) => (
                <li key={i} className="rounded border border-[var(--bg-border)] bg-[var(--bg-card)] p-2 text-[11px]">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-[8px] font-bold px-1 py-0.5 rounded border uppercase ${SEV[f.severity] || SEV.info}`}>{f.severity}</span>
                    <span className="text-[9px] text-indigo-300 uppercase tracking-wider">{TYPE[f.type] || f.type}</span>
                    <span className="font-semibold text-[var(--text-primary)]">{f.title}</span>
                    <Ports list={f.ports} />
                  </div>
                  <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{f.detail}</p>
                  {f.action && <p className="text-[10px] text-cyan-200 mt-0.5"><b>Azione:</b> {f.action}</p>}
                </li>
              ))}
            </ul>
          )}
          <div className="grid sm:grid-cols-2 gap-2 text-[10px]">
            {(res.disable_candidates || []).length > 0 && <div><span className="text-[var(--text-muted)] uppercase tracking-wider text-[9px]">Porte da disabilitare (mai usate)</span><br /><Ports list={res.disable_candidates} testid="switch-ai-audit-disable" /></div>}
            {(res.label_missing || []).length > 0 && <div><span className="text-[var(--text-muted)] uppercase tracking-wider text-[9px]">Porte attive senza etichetta</span><br /><Ports list={res.label_missing} testid="switch-ai-audit-labels" /></div>}
          </div>
          {res.confidence != null && <p className="text-[9px] text-[var(--text-muted)]">Confidenza {res.confidence}% · {latest.model}</p>}
        </div>
      )}
    </div>
  );
}
