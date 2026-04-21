import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Target, CheckCircle, Warning } from "@phosphor-icons/react";

export default function SLAPage() {
  const [clients, setClients] = useState([]);
  const [targets, setTargets] = useState([]);
  const [selectedClient, setSelectedClient] = useState(null);
  const [compliance, setCompliance] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    const [c, t] = await Promise.all([
      axios.get(`${API}/clients`),
      axios.get(`${API}/sla/targets`),
    ]);
    setClients(c.data || []);
    setTargets(t.data?.items || []);
  };
  useEffect(() => { load(); }, []);

  const viewCompliance = async (clientId) => {
    setSelectedClient(clientId);
    try {
      const r = await axios.get(`${API}/sla/compliance/${clientId}`);
      setCompliance(r.data);
    } catch (e) {
      setCompliance({ error: e.response?.data?.detail || e.message });
    }
  };

  const saveTarget = async (t) => {
    await axios.post(`${API}/sla/targets`, t);
    setEditing(null); load();
  };

  const targetFor = (cid) => targets.find(t => t.client_id === cid);

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="sla-page">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Target size={24} className="text-purple-400" /> SLA Management
        </h1>
        <p className="text-[12px] text-white/50 mt-1">Target per cliente · Compliance mensile · Report breach / credit</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <h2 className="text-sm font-bold text-white mb-2">Clienti + SLA</h2>
          <div className="space-y-2">
            {clients.map(c => {
              const t = targetFor(c.id);
              return (
                <div key={c.id} className="bg-[#12121a] border border-[#2a2a3e] rounded-lg p-3 hover:border-purple-500/30" data-testid={`sla-client-${c.id}`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-[13px] font-bold text-white">{c.name}</div>
                      <div className="text-[10px] text-white/40 font-mono mt-0.5">
                        {t ? `Uptime ≥${t.uptime_target_percent}% · MTTA ≤${t.mtta_minutes}min · MTTR ≤${t.mttr_hours}h` : "Nessun SLA"}
                      </div>
                    </div>
                    <div className="flex gap-1">
                      <button onClick={() => viewCompliance(c.id)} className="text-[10px] px-2 py-1 rounded bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20">Report</button>
                      <button onClick={() => setEditing(t || { client_id: c.id, name: "Default SLA", uptime_target_percent: 99.9, mtta_minutes: 15, mttr_hours: 4, hours_coverage: "24x7", credit_percent_per_breach: 5, active: true })} className="text-[10px] px-2 py-1 rounded bg-purple-500/10 text-purple-400 hover:bg-purple-500/20" data-testid={`sla-edit-${c.id}`}>{t ? "Modifica" : "Nuovo SLA"}</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-bold text-white mb-2">Compliance report</h2>
          {compliance ? (
            compliance.error ? <div className="text-red-400 text-xs p-3 bg-red-500/5 rounded">{compliance.error}</div> : (
              <div className="bg-[#12121a] border border-[#2a2a3e] rounded-lg p-4 space-y-3" data-testid="sla-compliance-report">
                <div className={`flex items-center gap-2 text-sm font-bold ${compliance.compliance === "compliant" ? "text-emerald-400" : "text-red-400"}`}>
                  {compliance.compliance === "compliant" ? <CheckCircle size={16} /> : <Warning size={16} />}
                  {compliance.compliance === "compliant" ? "COMPLIANT" : `BREACH × ${compliance.breaches?.length}`}
                </div>
                <div className="text-[10px] text-white/40 font-mono">
                  {compliance.period?.start?.slice(0, 10)} → {compliance.period?.end?.slice(0, 10)}
                </div>
                <table className="w-full text-[11px]">
                  <tbody>
                    <tr><td className="py-1 text-white/60">Alert totali</td><td className="text-white font-mono">{compliance.metrics?.total_alerts}</td></tr>
                    <tr><td className="py-1 text-white/60">Alert critici</td><td className="text-white font-mono">{compliance.metrics?.critical_alerts}</td></tr>
                    <tr><td className="py-1 text-white/60">MTTA medio</td><td className="text-white font-mono">{compliance.metrics?.mtta_avg_minutes ?? "—"} min</td></tr>
                    <tr><td className="py-1 text-white/60">MTTR medio</td><td className="text-white font-mono">{compliance.metrics?.mttr_avg_hours ?? "—"} h</td></tr>
                    <tr><td className="py-1 text-white/60">Uptime stimato</td><td className="text-white font-mono">{compliance.metrics?.uptime_percent ?? "—"}%</td></tr>
                  </tbody>
                </table>
                {compliance.breaches?.length > 0 && (
                  <div>
                    <div className="text-[10px] text-red-400 uppercase font-bold mb-1">Breach</div>
                    {compliance.breaches.map((b, i) => (
                      <div key={i} className="text-[11px] text-red-400 font-mono">
                        {b.metric}: target {b.target}{b.unit} · actual {b.actual}{b.unit}
                      </div>
                    ))}
                    <div className="mt-2 text-[11px] text-amber-400">Credito dovuto: <b>{compliance.credit_due_percent}%</b> sul fatturato</div>
                  </div>
                )}
              </div>
            )
          ) : <div className="text-white/40 text-xs">Seleziona un cliente per il report mensile</div>}
        </div>
      </div>

      {editing && <SLAEditor initial={editing} onClose={() => setEditing(null)} onSave={saveTarget} />}
    </div>
  );
}

function SLAEditor({ initial, onClose, onSave }) {
  const [f, setF] = useState(initial);
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  const n = (k, v) => set(k, v === "" ? null : Number(v));
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-4">SLA Target</h3>
        <div className="space-y-3">
          <Field label="Nome SLA" v={f.name} set={v => set("name", v)} />
          <Field label="Uptime target (%)" v={f.uptime_target_percent} set={v => n("uptime_target_percent", v)} type="number" />
          <Field label="MTTA target (min)" v={f.mtta_minutes} set={v => n("mtta_minutes", v)} type="number" />
          <Field label="MTTR target (h)" v={f.mttr_hours} set={v => n("mttr_hours", v)} type="number" />
          <Field label="Copertura" v={f.hours_coverage} set={v => set("hours_coverage", v)} placeholder="24x7 | business_hours" />
          <Field label="Credito per breach (%)" v={f.credit_percent_per_breach} set={v => n("credit_percent_per_breach", v)} type="number" />
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded bg-white/5 text-white/60 text-sm">Annulla</button>
          <button onClick={() => onSave(f)} className="px-4 py-2 rounded bg-purple-500/20 text-purple-400 border border-purple-500/30 hover:bg-purple-500/30 text-sm font-bold" data-testid="sla-save-btn">Salva</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, v, set, type = "text", placeholder }) {
  return (
    <div>
      <label className="text-[10px] text-white/60 uppercase">{label}</label>
      <input type={type} value={v ?? ""} onChange={e => set(e.target.value)} placeholder={placeholder}
        className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-sm" />
    </div>
  );
}
