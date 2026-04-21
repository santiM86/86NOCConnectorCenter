import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Database, Pencil, Trash, Plus, Warning } from "@phosphor-icons/react";

export default function CMDBPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [warnings, setWarnings] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        axios.get(`${API}/cmdb/assets`),
        axios.get(`${API}/cmdb/warranty-alerts?days_ahead=60`),
      ]);
      setItems(r1.data?.items || []);
      setWarnings(r2.data?.items || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const save = async (data) => {
    await axios.post(`${API}/cmdb/assets`, data);
    setEditing(null);
    load();
  };

  const remove = async (ip) => {
    if (!window.confirm(`Eliminare asset ${ip}?`)) return;
    await axios.delete(`${API}/cmdb/assets/${ip}`);
    load();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="cmdb-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Database size={24} className="text-indigo-400" /> CMDB — Configuration Management Database
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Asset inventory: vendor, contratto, garanzia, ciclo vita, responsabile.</p>
        </div>
        <button onClick={() => setEditing({})} className="px-3 py-2 rounded-lg bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-sm font-bold flex items-center gap-1" data-testid="cmdb-add-btn">
          <Plus size={14} /> Nuovo asset
        </button>
      </div>

      {warnings.length > 0 && (
        <div className="mb-6 bg-amber-500/5 border border-amber-500/30 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Warning size={16} className="text-amber-400" />
            <span className="text-sm font-bold text-amber-400">Garanzia/Contratto in scadenza (60gg)</span>
          </div>
          <div className="grid gap-1">
            {warnings.slice(0, 5).map((w, i) => (
              <div key={i} className="text-xs text-white/70 font-mono">
                {w.device_ip} · {w.vendor || "?"} {w.model || ""} · warranty: <span className="text-amber-300">{w.warranty_end || "—"}</span> · support: <span className="text-amber-300">{w.support_expires || "—"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading ? <div className="text-center py-12 text-white/40">Caricamento...</div> : (
        <table className="w-full bg-[#12121a] border border-[#2a2a3e] rounded-lg overflow-hidden">
          <thead className="bg-[#0f0f17] text-[10px] text-white/40 uppercase">
            <tr>
              <th className="p-2 text-left">IP</th><th className="p-2 text-left">Vendor</th><th className="p-2 text-left">Modello</th>
              <th className="p-2 text-left">S/N</th><th className="p-2 text-left">Garanzia</th>
              <th className="p-2 text-left">Supporto</th><th className="p-2 text-left">Responsabile</th><th className="p-2 text-left">Stato</th><th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={9} className="text-center py-12 text-white/40 text-xs">Nessun asset in CMDB. Clicca "Nuovo asset".</td></tr>
            ) : items.map((a, i) => (
              <tr key={i} className="border-t border-[#1e1e2e] hover:bg-white/5 text-[11px]" data-testid={`cmdb-row-${a.device_ip}`}>
                <td className="p-2 font-mono text-white">{a.device_ip}</td>
                <td className="p-2 text-white/70">{a.vendor || "—"}</td>
                <td className="p-2 text-white/70">{a.model || "—"}</td>
                <td className="p-2 text-white/60 font-mono">{a.serial_number || "—"}</td>
                <td className="p-2 text-white/60">{a.warranty_end || "—"}</td>
                <td className="p-2 text-white/60">{a.support_expires || "—"}</td>
                <td className="p-2 text-white/70">{a.responsible_user || "—"}</td>
                <td className="p-2"><span className="text-[9px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">{a.lifecycle_state || "production"}</span></td>
                <td className="p-2 flex gap-1">
                  <button onClick={() => setEditing(a)} className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400"><Pencil size={12} /></button>
                  <button onClick={() => remove(a.device_ip)} className="p-1 rounded hover:bg-red-500/10 text-red-400"><Trash size={12} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && <AssetEditor initial={editing} onClose={() => setEditing(null)} onSave={save} />}
    </div>
  );
}

function AssetEditor({ initial, onClose, onSave }) {
  const [f, setF] = useState({
    device_ip: "", vendor: "", model: "", serial_number: "", firmware: "",
    warranty_end: "", support_expires: "", location: "", rack: "",
    responsible_user: "", lifecycle_state: "production", notes: "",
    ...initial,
  });
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl max-w-xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-4">{initial.device_ip ? `Modifica ${initial.device_ip}` : "Nuovo Asset CMDB"}</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="IP device *" v={f.device_ip} set={v => set("device_ip", v)} disabled={!!initial.device_ip} testid="cmdb-ip" />
          <Field label="Vendor" v={f.vendor} set={v => set("vendor", v)} />
          <Field label="Modello" v={f.model} set={v => set("model", v)} />
          <Field label="Serial Number" v={f.serial_number} set={v => set("serial_number", v)} />
          <Field label="Firmware" v={f.firmware} set={v => set("firmware", v)} />
          <Field label="Garanzia fino (YYYY-MM-DD)" v={f.warranty_end} set={v => set("warranty_end", v)} />
          <Field label="Supporto scade (YYYY-MM-DD)" v={f.support_expires} set={v => set("support_expires", v)} />
          <Field label="Supporto (contratto #)" v={f.support_contract} set={v => set("support_contract", v)} />
          <Field label="Posizione" v={f.location} set={v => set("location", v)} />
          <Field label="Rack" v={f.rack} set={v => set("rack", v)} />
          <Field label="Responsabile interno" v={f.responsible_user} set={v => set("responsible_user", v)} />
          <div>
            <label className="text-[10px] text-white/60 uppercase">Lifecycle</label>
            <select value={f.lifecycle_state} onChange={e => set("lifecycle_state", e.target.value)} className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-[12px]">
              <option value="production">Production</option><option value="staging">Staging</option>
              <option value="retired">Retired</option><option value="spare">Spare</option>
            </select>
          </div>
        </div>
        <textarea value={f.notes || ""} onChange={e => set("notes", e.target.value)} placeholder="Note" className="w-full mt-3 bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-[12px]" rows={3} />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded bg-white/5 text-white/60 text-sm">Annulla</button>
          <button onClick={() => onSave(f)} disabled={!f.device_ip} className="px-4 py-2 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-sm font-bold disabled:opacity-50" data-testid="cmdb-save-btn">Salva</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, v, set, disabled, testid }) {
  return (
    <div>
      <label className="text-[10px] text-white/60 uppercase">{label}</label>
      <input value={v || ""} onChange={e => set(e.target.value)} disabled={disabled}
        className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-[12px] disabled:opacity-50"
        data-testid={testid} />
    </div>
  );
}
