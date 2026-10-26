import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { CaretDown, CaretRight, Desktop, Crown } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const useNicGroups = (clientId) => {
  const [groups, setGroups] = useState([]);
  const load = useCallback(() => {
    if (!clientId) return;
    axios.get(`${API}/clients/${clientId}/nic-groups`).then(({ data }) => setGroups(Array.isArray(data) ? data : [])).catch(() => setGroups([]));
  }, [clientId]);
  useEffect(() => { load(); }, [load]);
  return { groups, reload: load };
};

const NicHostGroup = ({ g, clientId, devicesByIp, renderChildren, onChanged }) => {
  const [open, setOpen] = useState(true);
  const children = g.child_ips.map((ip) => devicesByIp[ip]).filter(Boolean);
  const setHost = async (hostIp) => {
    try {
      await axios.post(`${API}/clients/${clientId}/nic-groups/host`, { mac: g.mac, host_ip: hostIp });
      toast.success("Server host aggiornato");
      onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore impostazione host");
    }
  };
  return (
    <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/[0.03]" data-testid={`nic-group-${g.mac}`}>
      <div className="flex items-center gap-2 px-3 py-2 flex-wrap">
        <button onClick={() => setOpen((o) => !o)} className="text-cyan-300 hover:text-white transition-colors" data-testid={`nic-group-toggle-${g.mac}`}>
          {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </button>
        <Desktop size={14} className="text-cyan-300" />
        <span className="text-[12px] font-semibold text-white" data-testid={`nic-group-host-name-${g.mac}`}>{g.host_name}</span>
        <span className="text-[10px] font-mono text-[var(--text-muted)]">{g.host_ip}</span>
        <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-200 border border-cyan-500/30" data-testid={`nic-group-badge-${g.mac}`}>
          {g.child_ips.length} VM sulla stessa NIC
        </span>
        <span className="text-[9px] font-mono text-[var(--text-muted)]">MAC {g.mac.toUpperCase()}</span>
        <label className="ml-auto flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
          <Crown size={11} className={g.host_manual ? "text-amber-300" : "text-[var(--text-muted)]"} />
          Server host{g.host_manual ? "" : " (proposto)"}:
          <select value={g.host_ip} onChange={(e) => setHost(e.target.value)}
            className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-1.5 py-0.5 text-[10px] text-white outline-none focus:border-cyan-500"
            data-testid={`nic-group-host-select-${g.mac}`}>
            {g.members.map((m) => <option key={m.ip} value={m.ip}>{m.name} · {m.ip}</option>)}
          </select>
        </label>
      </div>
      {open && children.length > 0 && <div className="px-2 pb-2 pl-6">{renderChildren(children)}</div>}
    </div>
  );
};

export const NicHostGroups = ({ groups, clientId, devices, renderChildren, onChanged }) => {
  if (!groups.length) return null;
  const devicesByIp = Object.fromEntries(devices.map((d) => [d.ip_address, d]));
  const visible = groups.filter((g) => g.child_ips.some((ip) => devicesByIp[ip]));
  if (!visible.length) return null;
  return (
    <div className="space-y-2" data-testid="nic-host-groups">
      <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-cyan-400">Server e sue VM · stessa scheda di rete</p>
      {visible.map((g) => (
        <NicHostGroup key={g.mac} g={g} clientId={clientId} devicesByIp={devicesByIp} renderChildren={renderChildren} onChanged={onChanged} />
      ))}
    </div>
  );
};
