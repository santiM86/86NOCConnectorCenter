import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Trash, Plus, TreeStructure, Lightbulb } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { useClientsAndDevices } from "@/components/AlertRulesPanel";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const inputCls = "bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white outline-none focus:border-cyan-500";

const DependencyForm = ({ clientId, devices, onCreated }) => {
  const [parent, setParent] = useState("");
  const [kids, setKids] = useState(new Set());
  const toggleKid = (ip) => setKids((p) => { const n = new Set(p); n.has(ip) ? n.delete(ip) : n.add(ip); return n; });
  const submit = async () => {
    try {
      await axios.post(`${API}/alert-dependencies`, { client_id: clientId, parent_ip: parent, child_ips: [...kids] });
      toast.success("Dipendenza salvata");
      setParent(""); setKids(new Set());
      onCreated();
    } catch (e) {
      toast.error(e.response?.data?.detail?.toString?.() || "Errore salvataggio");
    }
  };
  return (
    <div className="space-y-2" data-testid="dependency-form">
      <select className={`${inputCls} w-full`} value={parent} onChange={(e) => setParent(e.target.value)} data-testid="dep-parent-select">
        <option value="">— dispositivo padre (es. server host, firewall, switch) —</option>
        {devices.map((d) => <option key={d.ip_address} value={d.ip_address}>{d.name || d.ip_address} · {d.ip_address}</option>)}
      </select>
      {parent && (
        <div className="max-h-44 overflow-y-auto grid grid-cols-1 md:grid-cols-2 gap-1 p-2 rounded border border-[var(--bg-border)]" data-testid="dep-children-list">
          {devices.filter((d) => d.ip_address !== parent).map((d) => (
            <label key={d.ip_address} className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)] cursor-pointer">
              <input type="checkbox" checked={kids.has(d.ip_address)} onChange={() => toggleKid(d.ip_address)} data-testid={`dep-child-${d.ip_address}`} />
              {d.name || d.ip_address} <span className="font-mono text-[var(--text-muted)]">{d.ip_address}</span>
            </label>
          ))}
        </div>
      )}
      <Button size="sm" onClick={submit} disabled={!parent || kids.size === 0} className="h-8 gap-1 text-xs bg-cyan-600 hover:bg-cyan-500" data-testid="dep-create-btn">
        <Plus size={12} /> Salva dipendenza ({kids.size} figli)
      </Button>
    </div>
  );
};

const Suggestions = ({ items, onApply }) => (
  items.length === 0 ? null : (
    <div className="space-y-1.5" data-testid="dep-suggestions">
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-amber-300"><Lightbulb size={11} /> Proposte automatiche (host → sue VM, stesso MAC)</p>
      {items.map((s) => (
        <div key={s.mac} className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-amber-500/20 bg-amber-500/[0.04] text-[11px]" data-testid={`dep-suggestion-${s.mac}`}>
          <span className="font-semibold text-white">{s.host_name}</span>
          <span className="font-mono text-[var(--text-muted)]">{s.host_ip}</span>
          <span className="text-[var(--text-muted)]">→ {s.child_ips.length} VM</span>
          <Button size="sm" variant="outline" onClick={() => onApply(s)} className="ml-auto h-6 text-[10px] border-amber-500/30 text-amber-200" data-testid={`dep-suggestion-apply-${s.mac}`}>
            Applica
          </Button>
        </div>
      ))}
    </div>
  )
);

export const AlertDependenciesPanel = () => {
  const [clientId, setClientId] = useState("");
  const { clients, devices } = useClientsAndDevices(clientId);
  const [deps, setDeps] = useState([]);
  const [sugg, setSugg] = useState([]);
  const nameOf = (ip) => devices.find((d) => d.ip_address === ip)?.name || ip;
  const load = useCallback(() => {
    if (!clientId) { setDeps([]); setSugg([]); return; }
    axios.get(`${API}/alert-dependencies`, { params: { client_id: clientId } }).then(({ data }) => setDeps(data || [])).catch(() => {});
    axios.get(`${API}/alert-dependencies/suggestions`, { params: { client_id: clientId } }).then(({ data }) => setSugg(data || [])).catch(() => {});
  }, [clientId]);
  useEffect(() => { load(); }, [load]);
  const apply = async (s) => {
    try {
      await axios.post(`${API}/alert-dependencies`, { client_id: clientId, parent_ip: s.host_ip, child_ips: s.child_ips, source: "suggested" });
      toast.success("Dipendenza host → VM applicata");
      load();
    } catch { toast.error("Errore applicazione proposta"); }
  };
  const remove = async (d) => {
    try { await axios.delete(`${API}/alert-dependencies/${d.id}`); toast.success("Dipendenza rimossa"); load(); } catch { toast.error("Errore rimozione"); }
  };
  return (
    <div className="space-y-3" data-testid="alert-dependencies-panel">
      <select className={`${inputCls} w-full`} value={clientId} onChange={(e) => setClientId(e.target.value)} data-testid="dep-client-select">
        <option value="">— seleziona cliente —</option>
        {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      {clientId && (
        <>
          <Suggestions items={sugg} onApply={apply} />
          <DependencyForm clientId={clientId} devices={devices} onCreated={load} />
          {deps.length === 0 ? (
            <p className="text-[10px] text-[var(--text-muted)]" data-testid="deps-empty">Nessuna dipendenza per questo cliente.</p>
          ) : (
            <ul className="space-y-1.5" data-testid="deps-list">
              {deps.map((d) => (
                <li key={d.id} className="flex items-start gap-2 px-2.5 py-2 rounded border border-[var(--bg-border)] text-[11px]" data-testid={`dep-row-${d.id}`}>
                  <TreeStructure size={13} className="text-cyan-300 mt-0.5" />
                  <div className="min-w-0">
                    <span className="font-semibold text-white">{nameOf(d.parent_ip)}</span> <span className="font-mono text-[var(--text-muted)]">{d.parent_ip}</span>
                    {d.source === "suggested" && <span className="ml-1.5 text-[9px] text-amber-300">auto</span>}
                    <p className="text-[10px] text-[var(--text-muted)] truncate">→ {d.child_ips.map(nameOf).join(", ")}</p>
                  </div>
                  <button onClick={() => remove(d)} className="ml-auto p-1 rounded hover:bg-red-500/10 text-red-400 transition-colors" data-testid={`dep-delete-${d.id}`}>
                    <Trash size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
};
