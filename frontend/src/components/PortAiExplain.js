import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Sparkle, CircleNotch } from "@phosphor-icons/react";
import AiFeedback from "@/components/AiFeedback";

const VERDICT = {
  spento_dal_cliente: { label: "SPENTO DAL CLIENTE", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40" },
  standby: { label: "STANDBY", cls: "text-sky-300 bg-sky-500/15 border-sky-500/40" },
  inutilizzata: { label: "INUTILIZZATA", cls: "text-neutral-300 bg-neutral-500/15 border-neutral-500/40" },
  guasto_probabile: { label: "GUASTO PROBABILE", cls: "text-red-300 bg-red-500/15 border-red-500/40" },
  incerto: { label: "INCERTO", cls: "text-amber-300 bg-amber-500/15 border-amber-500/40" },
  attiva: { label: "ATTIVA", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40" },
};
const WHEN_CLS = { subito: "text-red-300", "entro oggi": "text-amber-300", "prossima visita": "text-sky-300" };

export default function PortAiExplain({ deviceIp, idx, clientId }) {
  const [latest, setLatest] = useState(null);
  const [running, setRunning] = useState(false);
  const params = clientId ? { client_id: clientId } : {};
  const url = `${API}/devices/${encodeURIComponent(deviceIp)}/switch-ports/${idx}/ai-explain`;

  useEffect(() => {
    setLatest(null);
    axios.get(url, { params }).then(r => setLatest(r.data?.latest || null)).catch(() => {});
  }, [deviceIp, idx, clientId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setRunning(true);
    try {
      const r = await axios.post(url, null, { params, timeout: 180000 });
      setLatest(r.data);
      toast.success(`Spiegazione AI pronta in ${r.data.duration_s}s`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Analisi AI fallita");
    } finally { setRunning(false); }
  };

  const res = latest?.result;
  const v = VERDICT[res?.verdict] || VERDICT.incerto;
  return (
    <div className="rounded-md border border-indigo-500/30 bg-indigo-500/[0.04] p-2.5 space-y-2" data-testid={`port-ai-${idx}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-300">
          <Sparkle size={12} weight="fill" /> Spiegazione AI porta
          {res && <span className={`text-[9px] px-1.5 py-0.5 rounded border ${v.cls}`} data-testid={`port-ai-verdict-${idx}`}>{v.label}</span>}
          {latest && <span className="font-normal normal-case tracking-normal text-[9px] text-[var(--text-muted)]">{new Date(latest.created_at).toLocaleString("it-IT")}</span>}
        </span>
        <button onClick={run} disabled={running} data-testid={`port-ai-run-${idx}`}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-60 transition-colors">
          {running ? <><CircleNotch size={11} className="animate-spin" /> Analisi…</> : <><Sparkle size={11} weight="fill" /> {latest ? "Rispiega" : "Spiega con AI"}</>}
        </button>
      </div>
      {!latest && !running && <p className="text-[10px] text-[var(--text-muted)]">L'AI incrocia abitudini della porta, PoE, ultimo device collegato, Datto RMM, flap e festività per dirti se è un guasto o uno spegnimento voluto.</p>}
      {res && (
        <div className="space-y-1.5" data-testid={`port-ai-body-${idx}`}>
          <p className="text-[12px] font-semibold text-[var(--text-primary)] leading-snug">{res.headline}</p>
          <p className="text-[11px] text-[var(--text-secondary)] leading-snug">{res.explanation}</p>
          {(res.actions || []).length > 0 && (
            <ul className="space-y-0.5">
              {res.actions.map((a, i) => (
                <li key={i} className="text-[11px] flex items-start gap-1.5">
                  <span className="font-mono text-[10px] text-indigo-300 flex-shrink-0">{a.priority}.</span>
                  <span><span className="text-[var(--text-primary)]">{a.action}</span>
                    {a.when && <span className={`ml-1 text-[9px] uppercase font-bold ${WHEN_CLS[a.when] || "text-[var(--text-muted)]"}`}>{a.when}</span>}
                    {a.why && <span className="block text-[10px] text-[var(--text-muted)]">{a.why}</span>}</span>
                </li>
              ))}
            </ul>
          )}
          {res.suggest_reclassify && (
            <p className="text-[10px] text-amber-200 border border-amber-500/30 bg-amber-500/10 rounded px-2 py-1" data-testid={`port-ai-reclassify-${idx}`}>
              Suggerimento: la statistica dice diversamente — l'AI propone <b>{res.suggest_reclassify === "habitual" ? "Abituale" : "Anomalo"}</b>. {res.reclassify_reason}
            </p>
          )}
          {res.confidence != null && <p className="text-[9px] text-[var(--text-muted)]">Confidenza {res.confidence}% · {latest.model}</p>}
          <AiFeedback analysisKind="port_explain" analysisId={latest.id} clientId={latest.client_id || clientId} deviceIp={deviceIp} portName={latest.port_name} portIdx={idx} aiVerdict={res.verdict} kbRefs={res.kb_refs || []} />
        </div>
      )}
    </div>
  );
}
