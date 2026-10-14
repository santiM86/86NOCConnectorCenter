import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Trash, Plus, Play } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SEV = { low: "Bassa", medium: "Media", high: "Alta", critical: "Critica" };
const SEV_COLOR = { low: "text-slate-300", medium: "text-amber-300", high: "text-orange-400", critical: "text-red-400" };
const EMPTY = { name: "", metric: "packet_loss", operator: ">", threshold: 5, duration_min: 15, severity: "high", scope: "all", client_id: "", device_ip: "", enabled: true };
const inputCls = "bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white outline-none focus:border-cyan-500";

export const useClientsAndDevices = (clientId) => {
  const [clients, setClients] = useState([]);
  const [devices, setDevices] = useState([]);
  useEffect(() => { axios.get(`${API}/clients`).then(({ data }) => setClients(data || [])).catch(() => {}); }, []);
  useEffect(() => {
    if (!clientId) { setDevices([]); return; }
    axios.get(`${API}/devices`, { params: { client_id: clientId } })
      .then(({ data }) => setDevices((Array.isArray(data) ? data : data?.devices || []).filter((d) => d.ip_address)))
      .catch(() => setDevices([]));
  }, [clientId]);
  return { clients, devices };
};

const RuleForm = ({ metrics, onCreated }) => {
  const [f, setF] = useState(EMPTY);
  const { clients, devices } = useClientsAndDevices(f.client_id);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const submit = async () => {
    try {
      await axios.post(`${API}/alert-rules`, { ...f, threshold: Number(f.threshold), duration_min: Number(f.duration_min), client_id: f.client_id || null, device_ip: f.device_ip || null });
      toast.success("Regola creata");
      setF(EMPTY);
      onCreated();
    } catch (e) {
      toast.error(e.response?.data?.detail?.toString?.() || "Errore creazione regola");
    }
  };
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 items-end" data-testid="metric-rule-form">
      <input className={`${inputCls} col-span-2`} placeholder="Nome regola (es. Perdita pacchetti WAN)" value={f.name} onChange={(e) => set("name", e.target.value)} data-testid="rule-name-input" />
      <select className={inputCls} value={f.metric} onChange={(e) => set("metric", e.target.value)} data-testid="rule-metric-select">
        {metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
      </select>
      <div className="flex gap-1">
        <select className={`${inputCls} w-14`} value={f.operator} onChange={(e) => set("operator", e.target.value)} data-testid="rule-operator-select">
          <option value=">">&gt;</option><option value="<">&lt;</option>
        </select>
        <input type="number" className={`${inputCls} w-full`} value={f.threshold} onChange={(e) => set("threshold", e.target.value)} data-testid="rule-threshold-input" />
      </div>
      <label className="text-[10px] text-[var(--text-muted)]">Per almeno (minuti)
        <input type="number" min={0} className={`${inputCls} w-full mt-0.5`} value={f.duration_min} onChange={(e) => set("duration_min", e.target.value)} data-testid="rule-duration-input" />
      </label>
      <label className="text-[10px] text-[var(--text-muted)]">Gravità
        <select className={`${inputCls} w-full mt-0.5`} value={f.severity} onChange={(e) => set("severity", e.target.value)} data-testid="rule-severity-select">
          {Object.entries(SEV).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-[var(--text-muted)]">Si applica a
        <select className={`${inputCls} w-full mt-0.5`} value={f.scope} onChange={(e) => set("scope", e.target.value)} data-testid="rule-scope-select">
          <option value="all">Tutti i clienti</option><option value="client">Un cliente</option><option value="device">Un dispositivo</option>
        </select>
      </label>
      {f.scope !== "all" && (
        <select className={inputCls} value={f.client_id} onChange={(e) => setF((p) => ({ ...p, client_id: e.target.value, device_ip: "" }))} data-testid="rule-client-select">
          <option value="">— cliente —</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      )}
      {f.scope === "device" && (
        <select className={inputCls} value={f.device_ip} onChange={(e) => set("device_ip", e.target.value)} data-testid="rule-device-select">
          <option value="">— dispositivo —</option>
          {devices.map((d) => <option key={d.ip_address} value={d.ip_address}>{d.name || d.ip_address} · {d.ip_address}</option>)}
        </select>
      )}
      <Button size="sm" onClick={submit} disabled={!f.name.trim()} className="h-8 gap-1 text-xs bg-cyan-600 hover:bg-cyan-500" data-testid="rule-create-btn">
        <Plus size={12} /> Aggiungi regola
      </Button>
    </div>
  );
};

export const AlertRulesPanel = () => {
  const [metrics, setMetrics] = useState([]);
  const [rules, setRules] = useState([]);
  const load = useCallback(() => {
    axios.get(`${API}/alert-rules`).then(({ data }) => setRules(data || [])).catch(() => {});
  }, []);
  useEffect(() => {
    axios.get(`${API}/alert-rules/metrics`).then(({ data }) => setMetrics(data || [])).catch(() => {});
    load();
  }, [load]);
  const label = (k) => metrics.find((m) => m.key === k)?.label || k;
  const toggle = async (r) => {
    try { await axios.put(`${API}/alert-rules/${r.id}`, { ...r, enabled: !r.enabled }); load(); } catch { toast.error("Errore aggiornamento"); }
  };
  const remove = async (r) => {
    try { await axios.delete(`${API}/alert-rules/${r.id}`); toast.success("Regola eliminata"); load(); } catch { toast.error("Errore eliminazione"); }
  };
  const runNow = async () => {
    try { const { data } = await axios.post(`${API}/alert-rules/run`); toast.success(`Regole valutate: ${data.emitted} nuovi alert`); } catch { toast.error("Errore valutazione"); }
  };
  return (
    <div className="space-y-3" data-testid="alert-rules-panel">
      <RuleForm metrics={metrics} onCreated={load} />
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={runNow} className="h-7 gap-1 text-[11px] border-[var(--bg-border)]" data-testid="rules-run-now-btn">
          <Play size={11} /> Valuta ora
        </Button>
      </div>
      {rules.length === 0 ? (
        <p className="text-[10px] text-[var(--text-muted)]" data-testid="rules-empty">Nessuna regola configurata.</p>
      ) : (
        <ul className="space-y-1.5" data-testid="rules-list">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center gap-2 px-2.5 py-2 rounded border border-[var(--bg-border)] text-[11px]" data-testid={`rule-row-${r.id}`}>
              <Switch checked={r.enabled !== false} onCheckedChange={() => toggle(r)} data-testid={`rule-toggle-${r.id}`} />
              <span className="font-semibold text-white">{r.name}</span>
              <span className="font-mono text-[var(--text-muted)]">{label(r.metric)} {r.operator} {r.threshold} · {r.duration_min} min</span>
              <span className={`font-semibold ${SEV_COLOR[r.severity]}`}>{SEV[r.severity]}</span>
              <span className="text-[10px] text-[var(--text-muted)]">{r.scope === "all" ? "Tutti i clienti" : r.scope === "client" ? "Cliente" : `Dispositivo ${r.device_ip}`}</span>
              <button onClick={() => remove(r)} className="ml-auto p-1 rounded hover:bg-red-500/10 text-red-400 transition-colors" data-testid={`rule-delete-${r.id}`}>
                <Trash size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
