import { useEffect, useState } from "react";
import axios from "axios";
import { Plugs } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmt = (iso) => {
  if (!iso) return "mai visto";
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

const PortRow = ({ p, i }) => (
  <li className="flex items-center gap-2 text-[11px] py-1 border-b border-white/5 last:border-0" data-testid={`nic-port-row-${i}`}>
    <span className={`h-2 w-2 rounded-full shrink-0 ${p.active ? "bg-emerald-400 animate-pulse" : "bg-zinc-600"}`} />
    <span className="font-mono text-white w-36 shrink-0" data-testid={`nic-port-mac-${i}`}>{p.mac.toUpperCase()}</span>
    <span className={`text-[10px] font-semibold uppercase ${p.active ? "text-emerald-300" : "text-[var(--text-muted)]"}`} data-testid={`nic-port-state-${i}`}>
      {p.active ? "Risponde ora" : "In attesa"}
    </span>
    <span className="ml-auto text-[10px] text-[var(--text-muted)] text-right" data-testid={`nic-port-where-${i}`}>
      {p.switch_ip ? `${p.switch_name} · porta ${p.port_name || p.port}` : "posizione switch non nota"}
      <span className="block">{fmt(p.last_seen)}</span>
    </span>
  </li>
);

export const NicPortsSection = ({ deviceIp, clientId }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!deviceIp) return;
    axios.get(`${API}/devices/by-ip/${encodeURIComponent(deviceIp)}/nic-ports`, { params: clientId ? { client_id: clientId } : {} })
      .then(({ data: d }) => setData(d)).catch(() => setData({ ports: [] }));
  }, [deviceIp, clientId]);

  if (!data) return null;
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid="nic-ports-section">
      <div className="flex items-center gap-1.5 mb-2">
        <Plugs size={13} weight="bold" className="text-sky-300" />
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-sky-300">
          Porte di rete dell'apparato ({data.ports.length})
        </h4>
      </div>
      {data.ports.length === 0 && (
        <p className="text-[10px] text-[var(--text-muted)]" data-testid="nic-ports-empty">Nessuna porta di rete (MAC) ancora rilevata su questo IP.</p>
      )}
      <ul data-testid="nic-ports-list">
        {data.ports.map((p, i) => <PortRow key={p.mac} p={p} i={i} />)}
      </ul>
      {data.ports.length > 1 && (
        <p className="text-[10px] text-[var(--text-muted)] mt-1.5">
          Porte dello stesso apparato (bond/failover): il passaggio da una all'altra non genera allarmi.
        </p>
      )}
    </div>
  );
};
