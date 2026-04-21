import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Robot, Play, CheckCircle, XCircle, Clock, Gear, Plus, Trash, Pencil, Warning, ShieldCheck } from "@phosphor-icons/react";

const SEV_COLORS = {
  critical: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  high: "text-orange-400 bg-orange-500/10 border-orange-500/30",
  medium: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  low: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

const STATUS_COLORS = {
  pending_approval: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  approved: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  dispatched: "text-sky-400 bg-sky-500/10 border-sky-500/30",
  success: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  failed: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  rejected: "text-white/40 bg-white/5 border-white/10",
};

export default function RemediationPage() {
  const [tab, setTab] = useState("executions");
  const [stats, setStats] = useState(null);
  const [executions, setExecutions] = useState([]);
  const [rules, setRules] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingRule, setEditingRule] = useState(null);
  const [editingScript, setEditingScript] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [s, e, r, sc, cl] = await Promise.all([
        axios.get(`${API}/remediation/stats`),
        axios.get(`${API}/remediation/executions?limit=100`),
        axios.get(`${API}/remediation/rules`),
        axios.get(`${API}/remediation/scripts`),
        axios.get(`${API}/clients`),
      ]);
      setStats(s.data);
      setExecutions(e.data?.items || []);
      setRules(r.data?.items || []);
      setScripts(sc.data?.items || []);
      setClients(cl.data?.items || cl.data || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); const i = setInterval(load, 30000); return () => clearInterval(i); }, []);

  const approve = async (id) => { await axios.post(`${API}/remediation/executions/${id}/approve`); load(); };
  const reject = async (id) => {
    const reason = window.prompt("Motivo rifiuto (opzionale):") || "";
    await axios.post(`${API}/remediation/executions/${id}/reject`, null, { params: { reason } });
    load();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="remediation-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Robot size={24} className="text-violet-400" /> Automated Remediation Engine
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Regole alert→azione con approvazione manuale, audit trail e cooldown automatico.</p>
        </div>
      </div>

      {/* STATS CARDS */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="In attesa approvazione" value={stats.pending_approvals} color="text-amber-400" icon={Clock} />
          <StatCard label="Eseguiti OK (24h)" value={stats.day_success} color="text-emerald-400" icon={CheckCircle} />
          <StatCard label="Falliti (24h)" value={stats.day_failures} color="text-rose-400" icon={XCircle} />
          <StatCard label={`Regole attive / totale`} value={`${stats.active_rules} / ${stats.total_rules}`} color="text-violet-400" icon={ShieldCheck} />
        </div>
      )}

      {/* TABS */}
      <div className="flex gap-2 border-b border-white/10 mb-4">
        {[
          { id: "executions", label: "Esecuzioni" },
          { id: "rules", label: `Regole (${rules.length})` },
          { id: "scripts", label: `Script (${scripts.length})` },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${tab === t.id ? "text-violet-400 border-violet-400" : "text-white/60 border-transparent hover:text-white"}`}
            data-testid={`tab-${t.id}`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div className="text-white/50 text-sm p-4">Caricamento…</div>}

      {/* EXECUTIONS */}
      {tab === "executions" && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="text-white/50 text-xs uppercase border-b border-white/10">
              <tr>
                <th className="text-left py-2 px-2">Quando</th>
                <th className="text-left py-2 px-2">Alert / Regola</th>
                <th className="text-left py-2 px-2">Script</th>
                <th className="text-left py-2 px-2">Device</th>
                <th className="text-left py-2 px-2">Stato</th>
                <th className="text-left py-2 px-2">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {executions.map(e => (
                <tr key={e.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-2 px-2 text-white/60 text-xs">{(e.created_at || "").replace("T", " ").slice(0, 19)}</td>
                  <td className="py-2 px-2">
                    <div className="text-white/90 font-medium text-[12px]">{e.alert_title || e.rule_name || "—"}</div>
                    <div className="text-white/40 text-[11px]">{e.rule_name}</div>
                  </td>
                  <td className="py-2 px-2 text-white/80 text-[12px]">{e.script_name}<div className="text-[10px] text-white/40">{e.script_type}</div></td>
                  <td className="py-2 px-2 text-white/80 text-[12px]">{e.device_name || e.device_ip}<div className="text-[10px] text-white/40">{e.device_ip}</div></td>
                  <td className="py-2 px-2">
                    <span className={`px-2 py-0.5 rounded border text-[11px] font-bold uppercase ${STATUS_COLORS[e.status] || "text-white/50 border-white/10"}`}>{e.status}</span>
                  </td>
                  <td className="py-2 px-2">
                    {e.status === "pending_approval" && (
                      <div className="flex gap-1">
                        <button onClick={() => approve(e.id)} data-testid={`approve-${e.id}`}
                          className="px-2 py-1 rounded text-[11px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30">Approva</button>
                        <button onClick={() => reject(e.id)} data-testid={`reject-${e.id}`}
                          className="px-2 py-1 rounded text-[11px] bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500/30">Rifiuta</button>
                      </div>
                    )}
                    {(e.output || e.error) && (
                      <details className="text-[11px] text-white/60 mt-1">
                        <summary className="cursor-pointer text-violet-400">Output</summary>
                        <pre className="bg-black/40 p-2 mt-1 rounded max-w-xl overflow-auto text-[10px]">{e.error || e.output}</pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
              {executions.length === 0 && !loading && (
                <tr><td colSpan={6} className="py-6 text-center text-white/40">Nessuna esecuzione ancora.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* RULES */}
      {tab === "rules" && (
        <div>
          <div className="flex justify-end mb-3">
            <button onClick={() => setEditingRule({ enabled: true, requires_approval: true, cooldown_minutes: 10, max_per_day: 20 })} data-testid="new-rule-btn"
              className="px-3 py-2 rounded bg-violet-500/20 text-violet-400 border border-violet-500/30 hover:bg-violet-500/30 text-sm font-bold flex items-center gap-1">
              <Plus size={14} /> Nuova regola
            </button>
          </div>
          <div className="grid gap-3">
            {rules.map(r => (
              <div key={r.id} className="bg-white/[0.03] border border-white/10 rounded-lg p-3 flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${r.enabled ? "bg-emerald-400" : "bg-white/30"}`}></span>
                    <div className="text-white font-semibold">{r.name}</div>
                    {r.requires_approval && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 uppercase">Approval</span>}
                  </div>
                  <div className="text-[12px] text-white/60 mt-1">{r.description}</div>
                  <div className="text-[11px] text-white/40 mt-1">
                    Trigger: {(r.alert_types || []).join(", ") || "any"} · Severity: {(r.severity_match || []).join("/") || "any"} ·
                    Keywords: {(r.keyword_match || []).join(", ") || "any"} · Cooldown: {r.cooldown_minutes}min
                  </div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => setEditingRule(r)} className="p-2 text-white/50 hover:text-white"><Pencil size={14} /></button>
                  <button onClick={async () => { if (window.confirm("Eliminare regola?")) { await axios.delete(`${API}/remediation/rules/${r.id}`); load(); } }}
                    className="p-2 text-rose-400 hover:text-rose-300"><Trash size={14} /></button>
                </div>
              </div>
            ))}
            {rules.length === 0 && <div className="text-white/40 text-sm py-4 text-center">Nessuna regola configurata.</div>}
          </div>
        </div>
      )}

      {/* SCRIPTS */}
      {tab === "scripts" && (
        <div>
          <div className="flex justify-end mb-3">
            <button onClick={() => setEditingScript({ script_type: "powershell", requires_approval: true, timeout_seconds: 60 })} data-testid="new-script-btn"
              className="px-3 py-2 rounded bg-violet-500/20 text-violet-400 border border-violet-500/30 hover:bg-violet-500/30 text-sm font-bold flex items-center gap-1">
              <Plus size={14} /> Nuovo script
            </button>
          </div>
          <div className="grid gap-3">
            {scripts.map(s => (
              <div key={s.id} className="bg-white/[0.03] border border-white/10 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <div className="text-white font-semibold">{s.name}</div>
                      {s.is_builtin && <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/30 uppercase">Builtin</span>}
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-white/60 border border-white/10">{s.script_type}</span>
                    </div>
                    <div className="text-[12px] text-white/60 mt-1">{s.description}</div>
                  </div>
                  {!s.is_builtin && (
                    <div className="flex gap-1">
                      <button onClick={() => setEditingScript(s)} className="p-2 text-white/50 hover:text-white"><Pencil size={14} /></button>
                      <button onClick={async () => { if (window.confirm("Eliminare script?")) { await axios.delete(`${API}/remediation/scripts/${s.id}`); load(); } }}
                        className="p-2 text-rose-400 hover:text-rose-300"><Trash size={14} /></button>
                    </div>
                  )}
                </div>
                <details className="mt-2">
                  <summary className="text-[11px] text-violet-400 cursor-pointer">Mostra body</summary>
                  <pre className="bg-black/40 p-2 mt-1 rounded text-[10px] text-white/70 overflow-auto max-h-40">{s.body}</pre>
                </details>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* RULE EDITOR MODAL */}
      {editingRule && (
        <RuleEditor rule={editingRule} scripts={scripts} clients={clients}
          onClose={() => setEditingRule(null)}
          onSave={async (data) => {
            if (editingRule.id) await axios.put(`${API}/remediation/rules/${editingRule.id}`, data);
            else await axios.post(`${API}/remediation/rules`, data);
            setEditingRule(null); load();
          }} />
      )}

      {/* SCRIPT EDITOR MODAL */}
      {editingScript && (
        <ScriptEditor script={editingScript}
          onClose={() => setEditingScript(null)}
          onSave={async (data) => {
            if (editingScript.id) await axios.put(`${API}/remediation/scripts/${editingScript.id}`, data);
            else await axios.post(`${API}/remediation/scripts`, data);
            setEditingScript(null); load();
          }} />
      )}
    </div>
  );
}

function StatCard({ label, value, color, icon: Icon }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-lg p-3">
      <div className="flex items-center gap-2 text-[11px] text-white/50 uppercase tracking-wide">
        <Icon size={14} /> {label}
      </div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
    </div>
  );
}

function RuleEditor({ rule, scripts, clients, onClose, onSave }) {
  const [form, setForm] = useState({
    name: rule.name || "",
    description: rule.description || "",
    enabled: rule.enabled !== false,
    alert_types: (rule.alert_types || []).join(", "),
    severity_match: (rule.severity_match || []).join(", "),
    device_type_match: (rule.device_type_match || []).join(", "),
    keyword_match: (rule.keyword_match || []).join(", "),
    client_ids: rule.client_ids || [],
    script_id: rule.script_id || "",
    requires_approval: rule.requires_approval !== false,
    cooldown_minutes: rule.cooldown_minutes || 10,
    max_per_day: rule.max_per_day || 20,
  });

  const submit = () => {
    if (!form.name || !form.script_id) { alert("Nome e Script sono obbligatori"); return; }
    const payload = {
      ...form,
      alert_types: form.alert_types.split(",").map(s => s.trim()).filter(Boolean),
      severity_match: form.severity_match.split(",").map(s => s.trim()).filter(Boolean),
      device_type_match: form.device_type_match.split(",").map(s => s.trim()).filter(Boolean),
      keyword_match: form.keyword_match.split(",").map(s => s.trim()).filter(Boolean),
    };
    onSave(payload);
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#0d1117] border border-white/20 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="p-5">
          <h2 className="text-lg font-bold text-white mb-4">{rule.id ? "Modifica regola" : "Nuova regola"}</h2>
          <div className="space-y-3">
            <Field label="Nome"><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="input" data-testid="rule-name" /></Field>
            <Field label="Descrizione"><textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="input" rows="2" /></Field>
            <Field label="Script da eseguire *">
              <select value={form.script_id} onChange={e => setForm({ ...form, script_id: e.target.value })} className="input" data-testid="rule-script">
                <option value="">— seleziona —</option>
                {scripts.map(s => <option key={s.id} value={s.id}>{s.name} ({s.script_type})</option>)}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Alert types (csv)"><input value={form.alert_types} onChange={e => setForm({ ...form, alert_types: e.target.value })} placeholder="cpu_high,service_down" className="input" /></Field>
              <Field label="Severity (csv)"><input value={form.severity_match} onChange={e => setForm({ ...form, severity_match: e.target.value })} placeholder="critical,high" className="input" /></Field>
              <Field label="Device types (csv)"><input value={form.device_type_match} onChange={e => setForm({ ...form, device_type_match: e.target.value })} placeholder="switch,server" className="input" /></Field>
              <Field label="Keywords (csv)"><input value={form.keyword_match} onChange={e => setForm({ ...form, keyword_match: e.target.value })} placeholder="cpu,memory" className="input" /></Field>
              <Field label="Cooldown (minuti)"><input type="number" value={form.cooldown_minutes} onChange={e => setForm({ ...form, cooldown_minutes: Number(e.target.value) })} className="input" /></Field>
              <Field label="Max per giorno"><input type="number" value={form.max_per_day} onChange={e => setForm({ ...form, max_per_day: Number(e.target.value) })} className="input" /></Field>
            </div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-white/80 text-sm"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> Abilitata</label>
              <label className="flex items-center gap-2 text-white/80 text-sm"><input type="checkbox" checked={form.requires_approval} onChange={e => setForm({ ...form, requires_approval: e.target.checked })} /> Richiede approvazione</label>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded text-white/60 hover:text-white text-sm">Annulla</button>
            <button onClick={submit} data-testid="save-rule-btn" className="px-4 py-2 rounded bg-violet-500/30 text-violet-200 border border-violet-500/40 hover:bg-violet-500/40 text-sm font-bold">Salva</button>
          </div>
        </div>
      </div>
      <style>{`.input{width:100%;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:8px 10px;color:white;font-size:13px}.input:focus{outline:none;border-color:rgba(139,92,246,0.5)}`}</style>
    </div>
  );
}

function ScriptEditor({ script, onClose, onSave }) {
  const [form, setForm] = useState({
    name: script.name || "",
    description: script.description || "",
    script_type: script.script_type || "powershell",
    body: script.body || "",
    timeout_seconds: script.timeout_seconds || 60,
    requires_approval: script.requires_approval !== false,
    target_device_types: (script.target_device_types || []).join(", "),
    tags: (script.tags || []).join(", "),
  });
  const submit = () => {
    if (!form.name || !form.body) { alert("Nome e body sono obbligatori"); return; }
    onSave({
      ...form,
      target_device_types: form.target_device_types.split(",").map(s => s.trim()).filter(Boolean),
      tags: form.tags.split(",").map(s => s.trim()).filter(Boolean),
    });
  };
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#0d1117] border border-white/20 rounded-lg max-w-3xl w-full max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="p-5">
          <h2 className="text-lg font-bold text-white mb-4">{script.id ? "Modifica script" : "Nuovo script"}</h2>
          <div className="space-y-3">
            <Field label="Nome"><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="input" /></Field>
            <Field label="Descrizione"><input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="input" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tipo">
                <select value={form.script_type} onChange={e => setForm({ ...form, script_type: e.target.value })} className="input">
                  <option>powershell</option><option>shell</option><option>snmp-set</option>
                  <option>http-get</option><option>http-post</option><option>reboot</option><option>service-restart</option>
                </select>
              </Field>
              <Field label="Timeout (s)"><input type="number" value={form.timeout_seconds} onChange={e => setForm({ ...form, timeout_seconds: Number(e.target.value) })} className="input" /></Field>
              <Field label="Device types (csv)"><input value={form.target_device_types} onChange={e => setForm({ ...form, target_device_types: e.target.value })} className="input" /></Field>
              <Field label="Tags (csv)"><input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} className="input" /></Field>
            </div>
            <Field label="Body (script / JSON payload)">
              <textarea value={form.body} onChange={e => setForm({ ...form, body: e.target.value })} rows={10} className="input font-mono text-[12px]" />
            </Field>
            <label className="flex items-center gap-2 text-white/80 text-sm"><input type="checkbox" checked={form.requires_approval} onChange={e => setForm({ ...form, requires_approval: e.target.checked })} /> Richiede approvazione di default</label>
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded text-white/60 hover:text-white text-sm">Annulla</button>
            <button onClick={submit} className="px-4 py-2 rounded bg-violet-500/30 text-violet-200 border border-violet-500/40 hover:bg-violet-500/40 text-sm font-bold">Salva</button>
          </div>
        </div>
      </div>
      <style>{`.input{width:100%;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:8px 10px;color:white;font-size:13px}.input:focus{outline:none;border-color:rgba(139,92,246,0.5)}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <label className="block"><div className="text-[11px] text-white/50 mb-1 uppercase tracking-wide">{label}</div>{children}</label>;
}
