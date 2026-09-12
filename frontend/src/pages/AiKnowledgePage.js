import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { BookOpen, Plus, Trash2, Search, Brain } from "lucide-react";
import { API } from "@/App";

const VENDORS = ["HPE", "HPE Aruba/Comware", "Cisco", "Zyxel", "Microsoft", "Datto RMM", "Networking", "OS", "Generico"];

function AddForm({ onAdded }) {
  const [f, setF] = useState({ title: "", vendor: "HPE", tags: "", content: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/ai/knowledge`, { ...f, tags: f.tags.split(",").map(t => t.trim()).filter(Boolean) });
      toast.success("Voce aggiunta: l'AI la userà da subito quando pertinente");
      setF({ title: "", vendor: "HPE", tags: "", content: "" }); onAdded();
    } catch (e) { toast.error(e.response?.data?.detail?.[0]?.msg || e.response?.data?.detail || "Errore"); }
    finally { setBusy(false); }
  };
  const inp = "w-full h-8 px-2 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]";
  return (
    <div className="noc-panel p-3 space-y-2" data-testid="kb-add-form">
      <h3 className="text-[11px] font-bold uppercase tracking-wider text-indigo-300 flex items-center gap-1"><Plus size={13} /> Nuova voce (procedura interna, codice evento, fix noto)</h3>
      <div className="grid sm:grid-cols-3 gap-2">
        <input className={inp} placeholder="Titolo (es. IML 'Drive Array Controller Failure' su DL380 Gen10)" value={f.title} onChange={e => setF({ ...f, title: e.target.value })} data-testid="kb-title" />
        <select className={inp} value={f.vendor} onChange={e => setF({ ...f, vendor: e.target.value })} data-testid="kb-vendor">{VENDORS.map(v => <option key={v}>{v}</option>)}</select>
        <input className={inp} placeholder="Tag separati da virgola (es. iml, controller, p408i, gen10)" value={f.tags} onChange={e => setF({ ...f, tags: e.target.value })} data-testid="kb-tags" />
      </div>
      <textarea className={`${inp} h-24 py-1`} placeholder="Contenuto: cosa significa, causa probabile, azione consigliata, comandi, riferimenti advisory HPE…" value={f.content} onChange={e => setF({ ...f, content: e.target.value })} data-testid="kb-content" />
      <div className="flex justify-end"><button onClick={submit} disabled={busy || f.title.length < 3 || f.content.length < 10} className="h-8 px-3 rounded-md text-xs font-semibold bg-indigo-500/20 border border-indigo-500/40 text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-50" data-testid="kb-submit">Aggiungi alla base di conoscenza</button></div>
    </div>
  );
}

export default function AiKnowledgePage() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [fb, setFb] = useState(null);
  const [tab, setTab] = useState("kb");

  const load = useCallback(() => {
    axios.get(`${API}/ai/knowledge`, { params: q ? { q } : {} }).then(r => setData(r.data)).catch(() => toast.error("Errore caricamento KB"));
    axios.get(`${API}/ai/feedback`, { params: { limit: 100 } }).then(r => setFb(r.data)).catch(() => {});
  }, [q]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

  const del = async (id) => {
    if (!window.confirm("Eliminare questa voce?")) return;
    try { await axios.delete(`${API}/ai/knowledge/${id}`); toast.success("Voce eliminata"); load(); } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  return (
    <div className="space-y-4 p-3 md:p-5" data-testid="ai-knowledge-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-base md:text-lg font-bold flex items-center gap-2"><Brain size={18} className="text-indigo-300" /> Base conoscenza AI</h1>
        {data && <span className="text-[11px] text-[var(--text-muted)]" data-testid="kb-counts">{data.builtin_count} voci vendor integrate · <b className="text-indigo-300">{data.user_count}</b> vostre</span>}
        {fb?.stats && <span className="text-[11px] text-[var(--text-muted)]" data-testid="kb-feedback-stats">· Memoria casi: <b className="text-[var(--text-primary)]">{fb.stats.total}</b> feedback{fb.stats.accuracy_pct != null && <>, AI corretta nel <b className={fb.stats.accuracy_pct >= 80 ? "text-emerald-300" : "text-amber-300"}>{fb.stats.accuracy_pct}%</b></>}</span>}
        <div className="ml-auto flex gap-1 text-[11px]">
          <button onClick={() => setTab("kb")} className={`px-2 h-7 rounded ${tab === "kb" ? "bg-indigo-500/20 text-indigo-200" : "text-[var(--text-muted)]"}`} data-testid="kb-tab-kb">Conoscenza</button>
          <button onClick={() => setTab("fb")} className={`px-2 h-7 rounded ${tab === "fb" ? "bg-indigo-500/20 text-indigo-200" : "text-[var(--text-muted)]"}`} data-testid="kb-tab-fb">Memoria casi</button>
        </div>
      </div>
      <p className="text-[11px] text-[var(--text-secondary)] max-w-3xl">Ogni analisi AI (porte, audit switch, log iLO) riceve automaticamente le voci pertinenti di questa base (codici IML/SEL HPE, eventi iLO, problemi porta/PoE, comandi Aruba/Comware/Cisco) e i casi passati sullo stesso device: come li avete chiusi e i vostri feedback sulle analisi precedenti. Aggiungete qui le vostre procedure interne e fix noti.</p>

      {tab === "kb" && (
        <>
          <AddForm onAdded={load} />
          <div className="noc-panel">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--bg-border)]">
              <Search size={13} className="text-[var(--text-muted)]" />
              <input value={q} onChange={e => setQ(e.target.value)} placeholder="Cerca (es. DIMM, PoE, flap, ASR, err-disabled)…" className="flex-1 h-7 bg-transparent text-xs text-[var(--text-primary)] outline-none" data-testid="kb-search" />
              <span className="text-[10px] text-[var(--text-muted)]">{data?.items?.length ?? 0} voci</span>
            </div>
            <ul className="divide-y divide-[var(--bg-border)]" data-testid="kb-list">
              {(data?.items || []).map(e => (
                <li key={e.id} className="p-3 text-[11px]" data-testid={`kb-item-${e.id}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <BookOpen size={12} className={e.source === "user" ? "text-indigo-300" : "text-[var(--text-muted)]"} />
                    <b className="text-[var(--text-primary)]">{e.title}</b>
                    <span className="text-[9px] px-1 rounded bg-cyan-500/15 text-cyan-200">{e.vendor}</span>
                    <span className={`text-[8px] px-1 rounded uppercase ${e.source === "user" ? "bg-indigo-500/20 text-indigo-200" : "bg-neutral-500/20 text-neutral-300"}`}>{e.source === "user" ? "vostra" : "integrata"}</span>
                    <code className="text-[9px] text-[var(--text-muted)]">{e.id}</code>
                    {e.source === "user" && <button onClick={() => del(e.id)} className="ml-auto text-red-300 hover:text-red-200" data-testid={`kb-delete-${e.id}`}><Trash2 size={12} /></button>}
                  </div>
                  <p className="text-[var(--text-secondary)] mt-1 leading-snug">{e.content}</p>
                  {(e.tags || []).length > 0 && <p className="text-[9px] text-[var(--text-muted)] mt-0.5">{e.tags.map(t => `#${t}`).join(" ")}</p>}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      {tab === "fb" && (
        <div className="noc-panel">
          <table className="noc-table w-full text-[11px]" data-testid="kb-feedback-table">
            <thead><tr><th>Quando</th><th>Device</th><th>Analisi</th><th>Verdetto AI</th><th>Esito</th><th>Nota tecnico</th><th>Da</th></tr></thead>
            <tbody>
              {(fb?.items || []).map(f => (
                <tr key={f.id}>
                  <td className="text-[var(--text-muted)]">{new Date(f.created_at).toLocaleString("it-IT")}</td>
                  <td className="font-mono">{f.device_ip}{f.port_name ? ` · ${f.port_name}` : ""}</td>
                  <td>{f.analysis_kind}</td>
                  <td>{f.ai_verdict || "—"}</td>
                  <td>{f.correct ? <span className="text-emerald-300">corretto</span> : <span className="text-red-300">errato</span>}</td>
                  <td className="text-[var(--text-secondary)]">{f.note || "—"}</td>
                  <td className="text-[var(--text-muted)]">{f.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {fb && fb.items.length === 0 && <p className="text-center text-[11px] text-[var(--text-muted)] py-4">Nessun feedback ancora: usa "Verdetto corretto? Sì/No" sotto ogni analisi AI.</p>}
        </div>
      )}
    </div>
  );
}
