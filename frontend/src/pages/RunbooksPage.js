import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Book, Plus, Trash, Pencil, CheckCircle } from "@phosphor-icons/react";

export default function RunbooksPage() {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { const r = await axios.get(`${API}/runbooks`); setItems(r.data?.items || []); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async (d) => {
    if (d.id) await axios.put(`${API}/runbooks/${d.id}`, d);
    else await axios.post(`${API}/runbooks`, d);
    setEditing(null); load();
  };
  const remove = async (id) => {
    if (!window.confirm("Eliminare runbook?")) return;
    await axios.delete(`${API}/runbooks/${id}`); load();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="runbooks-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Book size={24} className="text-emerald-400" /> Runbooks — Procedure operative NOC
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Procedure standardizzate per riduzione MTTR. Matching automatico su alert.</p>
        </div>
        <button onClick={() => setEditing({ steps: [], device_types: [], alert_keywords: [], severity_match: [] })}
          className="px-3 py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 text-sm font-bold flex items-center gap-1"
          data-testid="runbook-add-btn">
          <Plus size={14} /> Nuovo runbook
        </button>
      </div>

      {loading ? <div className="text-center py-12 text-white/40">Caricamento...</div> : items.length === 0 ? (
        <div className="text-center py-16 text-white/40">
          <Book size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Nessun runbook. Crea il primo per guidare i tecnici in turno.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {items.map((r, i) => (
            <div key={i} className="bg-[#12121a] border border-[#2a2a3e] rounded-lg p-4 hover:border-emerald-500/30 transition-colors" data-testid={`runbook-row-${r.id}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-[14px] font-bold text-white">{r.title}</h3>
                  {r.description && <p className="text-[11px] text-white/60 mt-1">{r.description}</p>}
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    {(r.device_types || []).map(t => (<span key={t} className="text-[9px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 font-mono uppercase">{t}</span>))}
                    {(r.alert_keywords || []).map(k => (<span key={k} className="text-[9px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 font-mono">#{k}</span>))}
                    <span className="text-[9px] text-white/30 font-mono ml-auto"><CheckCircle size={9} className="inline" /> {(r.steps || []).length} step</span>
                  </div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => setEditing(r)} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-400"><Pencil size={12} /></button>
                  <button onClick={() => remove(r.id)} className="p-1.5 rounded hover:bg-red-500/10 text-red-400"><Trash size={12} /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && <RunbookEditor initial={editing} onClose={() => setEditing(null)} onSave={save} />}
    </div>
  );
}

function RunbookEditor({ initial, onClose, onSave }) {
  const [f, setF] = useState({
    title: "", description: "", device_types: [], alert_keywords: [], severity_match: [],
    steps: [], ...initial,
  });
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  const addStep = () => set("steps", [...(f.steps || []), { order: (f.steps?.length || 0) + 1, title: "", description: "" }]);
  const setStep = (i, k, v) => set("steps", f.steps.map((s, j) => j === i ? { ...s, [k]: v } : s));
  const removeStep = (i) => set("steps", f.steps.filter((_, j) => j !== i));
  const setArr = (k, str) => set(k, str.split(",").map(s => s.trim()).filter(Boolean));

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl max-w-3xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-4">{initial.id ? "Modifica runbook" : "Nuovo runbook"}</h3>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] text-white/60 uppercase">Titolo *</label>
            <input value={f.title} onChange={e => set("title", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" data-testid="runbook-title" />
          </div>
          <div>
            <label className="text-[10px] text-white/60 uppercase">Descrizione</label>
            <textarea value={f.description || ""} onChange={e => set("description", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" rows={2} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-white/60 uppercase">Device types (csv: switch,router,ilo)</label>
              <input value={(f.device_types || []).join(",")} onChange={e => setArr("device_types", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" />
            </div>
            <div>
              <label className="text-[10px] text-white/60 uppercase">Alert keywords (csv)</label>
              <input value={(f.alert_keywords || []).join(",")} onChange={e => setArr("alert_keywords", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" placeholder="cpu,high,memory" />
            </div>
          </div>
          <div>
            <label className="text-[10px] text-white/60 uppercase">Severity match (csv: critical,warning)</label>
            <input value={(f.severity_match || []).join(",")} onChange={e => setArr("severity_match", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" />
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] text-white/60 uppercase">Step procedura</label>
              <button onClick={addStep} className="text-[11px] text-emerald-400 hover:text-emerald-300">+ Aggiungi step</button>
            </div>
            {(f.steps || []).map((s, i) => (
              <div key={i} className="mb-2 p-2 bg-[#0f0f17] rounded border border-[#1e1e2e]">
                <div className="flex items-start gap-2">
                  <span className="text-[10px] font-bold text-indigo-400 font-mono">#{i + 1}</span>
                  <div className="flex-1 space-y-1">
                    <input value={s.title} onChange={e => setStep(i, "title", e.target.value)} placeholder="Titolo step" className="w-full bg-transparent border-b border-[#2a2a3e] text-white text-sm py-1" />
                    <textarea value={s.description || ""} onChange={e => setStep(i, "description", e.target.value)} placeholder="Descrizione / comando" className="w-full bg-transparent text-white/70 text-[11px] py-1" rows={2} />
                  </div>
                  <button onClick={() => removeStep(i)} className="p-1 text-red-400 hover:bg-red-500/10 rounded"><Trash size={11} /></button>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded bg-white/5 text-white/60 text-sm">Annulla</button>
          <button onClick={() => onSave(f)} disabled={!f.title} className="px-4 py-2 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 text-sm font-bold disabled:opacity-50" data-testid="runbook-save-btn">Salva</button>
        </div>
      </div>
    </div>
  );
}
