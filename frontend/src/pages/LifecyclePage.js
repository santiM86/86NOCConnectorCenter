import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { HardDrives, Warning, CheckCircle, ChartBar, Upload, Pencil, Trash, Plus } from "@phosphor-icons/react";

const RISK_COLORS = {
  high: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

export default function LifecyclePage() {
  const [tab, setTab] = useState("dashboard");
  const [records, setRecords] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [expiring, setExpiring] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const fileRef = useRef(null);

  const load = async () => {
    setLoading(true);
    try {
      const [r, d, e] = await Promise.all([
        axios.get(`${API}/lifecycle/records`),
        axios.get(`${API}/lifecycle/dashboard`),
        axios.get(`${API}/lifecycle/expiring?days_ahead=90`),
      ]);
      setRecords(r.data?.items || []);
      setDashboard(d.data);
      setExpiring(e.data?.items || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const save = async (data) => {
    await axios.post(`${API}/lifecycle/records`, data);
    setEditing(null); load();
  };
  const remove = async (ip) => {
    if (!window.confirm(`Eliminare record ${ip}?`)) return;
    await axios.delete(`${API}/lifecycle/records/${ip}`);
    load();
  };

  const importCsv = async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const res = await axios.post(`${API}/lifecycle/import-csv`, fd);
    alert(`Importati: ${res.data.imported}\nSaltati: ${res.data.skipped}`);
    ev.target.value = "";
    load();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="lifecycle-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <HardDrives size={24} className="text-teal-400" /> Hardware Lifecycle & Warranty
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Scadenze garanzia OEM, EOL/EOSL, contratti manutenzione, risk scoring — stile Park Place ParkView.</p>
        </div>
        <div className="flex gap-2">
          <input type="file" accept=".csv" ref={fileRef} onChange={importCsv} className="hidden" data-testid="csv-input" />
          <button onClick={() => fileRef.current?.click()} className="px-3 py-2 rounded bg-sky-500/20 text-sky-400 border border-sky-500/30 hover:bg-sky-500/30 text-sm font-bold flex items-center gap-1" data-testid="import-csv-btn">
            <Upload size={14} /> Importa CSV
          </button>
          <button onClick={() => setEditing({ criticality: "medium" })} className="px-3 py-2 rounded bg-teal-500/20 text-teal-400 border border-teal-500/30 hover:bg-teal-500/30 text-sm font-bold flex items-center gap-1" data-testid="new-record-btn">
            <Plus size={14} /> Nuovo asset
          </button>
        </div>
      </div>

      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <StatCard label="Asset totali" value={dashboard.total} color="text-white" icon={HardDrives} />
          <StatCard label="High risk" value={dashboard.high_risk} color="text-rose-400" icon={Warning} />
          <StatCard label="Garanzia scaduta" value={dashboard.expired_warranty} color="text-rose-400" icon={Warning} />
          <StatCard label="In scadenza 30gg" value={dashboard.expiring_30_days} color="text-amber-400" icon={Warning} />
          <StatCard label="EOSL raggiunto" value={dashboard.eosl_reached} color="text-rose-500" icon={Warning} />
        </div>
      )}

      <div className="flex gap-2 border-b border-white/10 mb-4">
        {[
          { id: "dashboard", label: "Dashboard" },
          { id: "expiring", label: `In scadenza (${expiring.length})` },
          { id: "all", label: `Tutti gli asset (${records.length})` },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${tab === t.id ? "text-teal-400 border-teal-400" : "text-white/60 border-transparent hover:text-white"}`}
            data-testid={`tab-${t.id}`}>{t.label}</button>
        ))}
      </div>

      {loading && <div className="text-white/50 text-sm p-4">Caricamento…</div>}

      {tab === "dashboard" && dashboard && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-white/[0.03] border border-white/10 rounded-lg p-4">
            <h3 className="text-white/90 font-bold mb-3 flex items-center gap-2"><ChartBar size={16} className="text-teal-400" /> Distribuzione per vendor</h3>
            {(dashboard.by_vendor || []).map(v => (
              <div key={v.vendor} className="flex items-center gap-2 mb-2">
                <div className="text-[12px] text-white/80 w-32 truncate">{v.vendor}</div>
                <div className="flex-1 bg-white/5 rounded h-2 overflow-hidden">
                  <div className="bg-teal-400 h-full" style={{ width: `${Math.min(100, (v.count / (dashboard.total || 1)) * 100)}%` }}></div>
                </div>
                <div className="text-[12px] text-white/60 w-10 text-right">{v.count}</div>
              </div>
            ))}
            {(dashboard.by_vendor || []).length === 0 && <div className="text-white/40 text-sm py-2">Nessun dato</div>}
          </div>

          <div className="bg-white/[0.03] border border-white/10 rounded-lg p-4">
            <h3 className="text-white/90 font-bold mb-3 flex items-center gap-2"><Warning size={16} className="text-amber-400" /> Distribuzione rischio</h3>
            <div className="space-y-2">
              {[
                { label: "High risk", count: dashboard.high_risk, total: dashboard.total, color: "bg-rose-400" },
                { label: "Medium risk", count: dashboard.medium_risk, total: dashboard.total, color: "bg-amber-400" },
                { label: "Low risk", count: dashboard.low_risk, total: dashboard.total, color: "bg-emerald-400" },
              ].map(r => (
                <div key={r.label} className="flex items-center gap-2">
                  <div className="text-[12px] text-white/80 w-32">{r.label}</div>
                  <div className="flex-1 bg-white/5 rounded h-2 overflow-hidden">
                    <div className={`${r.color} h-full`} style={{ width: `${Math.min(100, (r.count / (r.total || 1)) * 100)}%` }}></div>
                  </div>
                  <div className="text-[12px] text-white/60 w-10 text-right">{r.count}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {(tab === "expiring" || tab === "all") && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1000px]">
            <thead className="text-white/50 text-xs uppercase border-b border-white/10">
              <tr>
                <th className="text-left py-2 px-2">Device</th>
                <th className="text-left py-2 px-2">Vendor / Model</th>
                <th className="text-left py-2 px-2">S/N</th>
                <th className="text-left py-2 px-2">Garanzia</th>
                <th className="text-left py-2 px-2">EOSL</th>
                <th className="text-left py-2 px-2">Risk</th>
                <th className="text-left py-2 px-2"></th>
              </tr>
            </thead>
            <tbody>
              {(tab === "expiring" ? expiring : records).map(r => (
                <tr key={r.device_ip} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-2 px-2 text-white/90 text-[12px] font-mono">{r.device_ip}</td>
                  <td className="py-2 px-2 text-white/80 text-[12px]">{r.vendor || "—"}<div className="text-[10px] text-white/40">{r.model}</div></td>
                  <td className="py-2 px-2 text-white/60 text-[11px] font-mono">{r.serial_number || "—"}</td>
                  <td className="py-2 px-2 text-[12px]">
                    <div className={r.warranty_days_left != null && r.warranty_days_left < 0 ? "text-rose-400 font-bold" : r.warranty_days_left != null && r.warranty_days_left < 30 ? "text-amber-400" : "text-white/70"}>
                      {r.warranty_end || "—"}
                    </div>
                    {r.warranty_days_left != null && <div className="text-[10px] text-white/40">{r.warranty_days_left < 0 ? `scaduta da ${-r.warranty_days_left}gg` : `tra ${r.warranty_days_left}gg`}</div>}
                  </td>
                  <td className="py-2 px-2 text-[12px] text-white/70">{r.eosl_date || "—"}</td>
                  <td className="py-2 px-2">
                    <span className={`px-2 py-0.5 rounded border text-[11px] font-bold uppercase ${RISK_COLORS[r.risk_band] || "text-white/40"}`}>
                      {r.risk_band} · {r.risk_score}
                    </span>
                  </td>
                  <td className="py-2 px-2">
                    <button onClick={() => setEditing(r)} className="p-1 text-white/50 hover:text-white"><Pencil size={13} /></button>
                    <button onClick={() => remove(r.device_ip)} className="p-1 text-rose-400 hover:text-rose-300"><Trash size={13} /></button>
                  </td>
                </tr>
              ))}
              {((tab === "expiring" ? expiring : records).length === 0 && !loading) && (
                <tr><td colSpan={7} className="py-6 text-center text-white/40">Nessun asset.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {editing && <LifecycleEditor record={editing} onClose={() => setEditing(null)} onSave={save} />}
    </div>
  );
}

function StatCard({ label, value, color, icon: Icon }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-lg p-3">
      <div className="flex items-center gap-2 text-[11px] text-white/50 uppercase tracking-wide">
        <Icon size={14} /> {label}
      </div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value ?? 0}</div>
    </div>
  );
}

function LifecycleEditor({ record, onClose, onSave }) {
  const [form, setForm] = useState(record);
  const f = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = () => {
    if (!form.device_ip) { alert("device_ip richiesto"); return; }
    onSave(form);
  };
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#0d1117] border border-white/20 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="p-5">
          <h2 className="text-lg font-bold text-white mb-4">Lifecycle asset — {record.device_ip || "nuovo"}</h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Device IP *"><input value={form.device_ip || ""} onChange={f("device_ip")} className="input" data-testid="lc-ip" /></Field>
            <Field label="Criticality">
              <select value={form.criticality || "medium"} onChange={f("criticality")} className="input">
                <option>low</option><option>medium</option><option>high</option><option>critical</option>
              </select>
            </Field>
            <Field label="Vendor"><input value={form.vendor || ""} onChange={f("vendor")} className="input" /></Field>
            <Field label="Model"><input value={form.model || ""} onChange={f("model")} className="input" /></Field>
            <Field label="Serial Number"><input value={form.serial_number || ""} onChange={f("serial_number")} className="input" /></Field>
            <Field label="Install date"><input type="date" value={form.install_date || ""} onChange={f("install_date")} className="input" /></Field>
            <Field label="Warranty start"><input type="date" value={form.warranty_start || ""} onChange={f("warranty_start")} className="input" /></Field>
            <Field label="Warranty end"><input type="date" value={form.warranty_end || ""} onChange={f("warranty_end")} className="input" /></Field>
            <Field label="Warranty level"><input value={form.warranty_level || ""} onChange={f("warranty_level")} placeholder="Foundation Care 24x7" className="input" /></Field>
            <Field label="OEM contract #"><input value={form.oem_contract_number || ""} onChange={f("oem_contract_number")} className="input" /></Field>
            <Field label="EOL (End of Life)"><input type="date" value={form.eol_date || ""} onChange={f("eol_date")} className="input" /></Field>
            <Field label="EOSL (End of Support Life)"><input type="date" value={form.eosl_date || ""} onChange={f("eosl_date")} className="input" /></Field>
            <Field label="3rd-party maintenance"><input value={form.third_party_maintenance || ""} onChange={f("third_party_maintenance")} placeholder="Park Place, Curvature..." className="input" /></Field>
            <Field label="Maintenance end"><input type="date" value={form.maintenance_end || ""} onChange={f("maintenance_end")} className="input" /></Field>
            <Field label="Replacement cost (€)"><input type="number" value={form.replacement_cost_eur || ""} onChange={e => setForm({ ...form, replacement_cost_eur: Number(e.target.value) || null })} className="input" /></Field>
            <div className="col-span-2"><Field label="Note"><textarea value={form.notes || ""} onChange={f("notes")} rows={2} className="input" /></Field></div>
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={onClose} className="px-4 py-2 rounded text-white/60 hover:text-white text-sm">Annulla</button>
            <button onClick={submit} data-testid="save-lc-btn" className="px-4 py-2 rounded bg-teal-500/30 text-teal-200 border border-teal-500/40 hover:bg-teal-500/40 text-sm font-bold">Salva</button>
          </div>
        </div>
      </div>
      <style>{`.input{width:100%;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:8px 10px;color:white;font-size:13px}.input:focus{outline:none;border-color:rgba(20,184,166,0.5)}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <label className="block"><div className="text-[11px] text-white/50 mb-1 uppercase tracking-wide">{label}</div>{children}</label>;
}
