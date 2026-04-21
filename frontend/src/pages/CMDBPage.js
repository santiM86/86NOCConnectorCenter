import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Database, Pencil, Trash, Plus, Warning } from "@phosphor-icons/react";

export default function CMDBPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [clients, setClients] = useState([]);
  const [candidates, setCandidates] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const [r1, r2, r3, r4] = await Promise.all([
        axios.get(`${API}/cmdb/assets`),
        axios.get(`${API}/cmdb/warranty-alerts?days_ahead=60`),
        axios.get(`${API}/clients`),
        axios.get(`${API}/cmdb/candidates`),
      ]);
      setItems(r1.data?.items || []);
      setWarnings(r2.data?.items || []);
      setClients(r3.data?.items || r3.data || []);
      setCandidates(r4.data?.items || []);
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

      {editing && <AssetEditor initial={editing} onClose={() => setEditing(null)} onSave={save} clients={clients} candidates={candidates} />}
    </div>
  );
}

function AssetEditor({ initial, onClose, onSave, clients = [], candidates = [] }) {
  const [f, setF] = useState({
    device_ip: "", device_name: "", client_id: "", vendor: "", model: "", serial_number: "", firmware: "",
    warranty_end: "", support_expires: "", location: "", rack: "",
    responsible_user: "", lifecycle_state: "production", notes: "",
    ...initial,
  });
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState(null);
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));

  const autofillFromILO = async () => {
    if (!f.device_ip) { setImportMsg({ type: "error", text: "Inserisci prima un IP o seleziona un device dalla lista" }); return; }
    setImporting(true); setImportMsg(null);
    try {
      const res = await axios.get(`${API}/cmdb/autofill/${f.device_ip}`);
      const d = res.data || {};
      if (!d.has_data) {
        setImportMsg({ type: "warn", text: `Nessun dato telemetria disponibile per ${f.device_ip}. Compila manualmente.` });
        // Still import client_id if present
        if (d.client_id) set("client_id", d.client_id);
      } else {
        setF(p => ({
          ...p,
          vendor: d.vendor || p.vendor,
          model: d.model || p.model,
          serial_number: d.serial_number || p.serial_number,
          firmware: d.firmware || p.firmware,
          device_name: d.device_name || p.device_name,
          client_id: d.client_id || p.client_id,
        }));
        setImportMsg({ type: "ok", text: `Dati importati da ${d.source}${d.client_name ? ` · Cliente: ${d.client_name}` : ""}` });
      }
    } catch (e) {
      setImportMsg({ type: "error", text: `Errore: ${e.response?.data?.detail || e.message}` });
    } finally { setImporting(false); }
  };

  const pickCandidate = async (ip) => {
    set("device_ip", ip);
    // Trigger autofill immediately
    setTimeout(() => {
      const orig = f.device_ip;
      setF(p => ({ ...p, device_ip: ip }));
      // Call autofill against the new ip after state settles
      setTimeout(async () => {
        setImporting(true);
        try {
          const res = await axios.get(`${API}/cmdb/autofill/${ip}`);
          const d = res.data || {};
          setF(p => ({
            ...p,
            device_ip: ip,
            vendor: d.vendor || "",
            model: d.model || "",
            serial_number: d.serial_number || "",
            firmware: d.firmware || "",
            device_name: d.device_name || "",
            client_id: d.client_id || "",
          }));
          setImportMsg({ type: d.has_data ? "ok" : "warn", text: d.has_data ? `Dati importati da ${d.source}${d.client_name ? ` · Cliente: ${d.client_name}` : ""}` : "Device trovato ma senza telemetria — compila manualmente" });
        } catch (e) {
          setImportMsg({ type: "error", text: "Errore import: " + (e.message || "unknown") });
        } finally { setImporting(false); }
      }, 50);
    }, 0);
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl max-w-2xl w-full p-5 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-4">{initial.device_ip ? `Modifica ${initial.device_ip}` : "Nuovo Asset CMDB"}</h3>

        {/* Quick-pick da device monitorati */}
        {!initial.device_ip && candidates.length > 0 && (
          <div className="mb-4 p-3 bg-indigo-500/5 border border-indigo-500/20 rounded">
            <div className="text-[10px] uppercase tracking-wider text-indigo-400 mb-2">⚡ Import rapido da device già monitorati</div>
            <select
              onChange={e => { if (e.target.value) pickCandidate(e.target.value); }}
              className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-2 text-white text-[12px]"
              data-testid="cmdb-quick-pick"
              defaultValue="">
              <option value="">— Seleziona device monitorato ({candidates.length} disponibili) —</option>
              {candidates.map(c => (
                <option key={c.device_ip} value={c.device_ip}>
                  {c.device_ip} · {c.device_name || "—"}
                </option>
              ))}
            </select>
            <div className="text-[10px] text-white/40 mt-1">I dati hardware (vendor/modello/serial/firmware) verranno importati automaticamente.</div>
          </div>
        )}

        {/* Cliente selector — PRIMARIO */}
        <div className="mb-3 p-3 bg-white/[0.03] border border-white/10 rounded">
          <label className="text-[10px] uppercase tracking-wider text-white/60">Cliente *</label>
          <select value={f.client_id || ""} onChange={e => set("client_id", e.target.value)}
            className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-2 text-white text-[13px] mt-1"
            data-testid="cmdb-client-select">
            <option value="">— Seleziona cliente —</option>
            {clients.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="IP device *" v={f.device_ip} set={v => set("device_ip", v)} disabled={!!initial.device_ip} testid="cmdb-ip" />
          <div>
            <label className="text-[10px] text-white/60 uppercase">Nome device</label>
            <div className="flex gap-1">
              <input value={f.device_name || ""} onChange={e => set("device_name", e.target.value)}
                className="flex-1 bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-[12px]" />
              <button onClick={autofillFromILO} disabled={importing || !f.device_ip}
                className="px-3 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30 text-[11px] font-bold disabled:opacity-40"
                data-testid="cmdb-autofill-btn" title="Importa dati dalla iLO/telemetria attuale">
                {importing ? "…" : "⚡ iLO"}
              </button>
            </div>
          </div>
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

        {importMsg && (
          <div className={`mt-3 p-2 rounded text-[11px] ${importMsg.type === "ok" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30" : importMsg.type === "warn" ? "bg-amber-500/10 text-amber-400 border border-amber-500/30" : "bg-rose-500/10 text-rose-400 border border-rose-500/30"}`}>
            {importMsg.text}
          </div>
        )}

        <textarea value={f.notes || ""} onChange={e => set("notes", e.target.value)} placeholder="Note" className="w-full mt-3 bg-[#0f0f17] border border-[#2a2a3e] rounded px-2 py-1.5 text-white text-[12px]" rows={3} />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded bg-white/5 text-white/60 text-sm">Annulla</button>
          <button onClick={() => onSave(f)} disabled={!f.device_ip || !f.client_id} className="px-4 py-2 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-sm font-bold disabled:opacity-50" data-testid="cmdb-save-btn">Salva</button>
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
