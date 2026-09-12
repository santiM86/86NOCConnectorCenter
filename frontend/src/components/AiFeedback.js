import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { ThumbsUp, ThumbsDown } from "@phosphor-icons/react";

/** Feedback del tecnico su un'analisi AI → memoria casi (db.ai_feedback) usata nei prompt successivi. */
export default function AiFeedback({ analysisKind, analysisId, clientId, deviceIp, portName, portIdx, aiVerdict, kbRefs = [] }) {
  const [sent, setSent] = useState(null);
  const [mode, setMode] = useState(null);
  const [note, setNote] = useState("");
  const tid = portIdx != null ? `${analysisKind}-${portIdx}` : `${analysisKind}-${deviceIp}`;

  const send = async (correct) => {
    try {
      await axios.post(`${API}/ai/feedback`, { analysis_kind: analysisKind, analysis_id: analysisId, client_id: clientId, device_ip: deviceIp,
        port_name: portName || null, port_idx: portIdx ?? null, ai_verdict: aiVerdict || null, correct, note: note || null });
      setSent(correct); setMode(null);
      toast.success(correct ? "Grazie: l'AI terrà conto della conferma" : "Registrato: l'AI userà la correzione nelle prossime analisi");
    } catch (e) { toast.error(e.response?.data?.detail || "Feedback non salvato"); }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-[9px] text-[var(--text-muted)]" data-testid={`ai-feedback-${tid}`}>
      {kbRefs.length > 0 && <span data-testid={`ai-kb-refs-${tid}`}>Fonti KB: {kbRefs.map(r => <code key={r} className="ml-1 px-1 rounded bg-indigo-500/15 text-indigo-200">{r}</code>)}</span>}
      {sent === null && mode === null && (
        <span className="ml-auto flex items-center gap-1">
          Verdetto corretto?
          <button onClick={() => send(true)} className="px-1.5 py-0.5 rounded border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15 flex items-center gap-0.5" data-testid={`ai-feedback-ok-${tid}`}><ThumbsUp size={10} /> Sì</button>
          <button onClick={() => setMode("wrong")} className="px-1.5 py-0.5 rounded border border-red-500/40 text-red-300 hover:bg-red-500/15 flex items-center gap-0.5" data-testid={`ai-feedback-ko-${tid}`}><ThumbsDown size={10} /> No</button>
        </span>
      )}
      {mode === "wrong" && (
        <span className="ml-auto flex items-center gap-1 w-full sm:w-auto">
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Cosa era davvero? (es. cavo sostituito, PC spento dall'utente)" data-testid={`ai-feedback-note-${tid}`}
            className="flex-1 min-w-[220px] h-6 px-2 text-[10px] rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" />
          <button onClick={() => send(false)} disabled={note.trim().length < 3} className="px-2 h-6 rounded bg-red-500/20 border border-red-500/40 text-red-200 disabled:opacity-50" data-testid={`ai-feedback-send-${tid}`}>Invia</button>
          <button onClick={() => setMode(null)} className="px-1 h-6 text-[var(--text-muted)]">✕</button>
        </span>
      )}
      {sent !== null && <span className={`ml-auto ${sent ? "text-emerald-300" : "text-amber-300"}`} data-testid={`ai-feedback-done-${tid}`}>{sent ? "✓ Confermato" : "✓ Correzione salvata in memoria casi"}</span>}
    </div>
  );
}
