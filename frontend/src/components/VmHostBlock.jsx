import { Link } from "react-router-dom";
import { Cube, Desktop } from "@phosphor-icons/react";

export const VmHostBadge = ({ p }) => (
  p.vm_host ? (
    <div className="mt-1 text-[9px] text-indigo-300 flex items-center gap-1" data-testid={`port-vmhost-badge-${p.idx}`}>
      <Cube size={10} weight="bold" /> Host {p.vm_host.kind} · {p.vm_host.vms.length} VM
    </div>
  ) : null
);

export default function VmHostBlock({ p }) {
  const h = p.vm_host;
  if (!h) return null;
  return (
    <div className="rounded-md border border-indigo-500/40 bg-indigo-500/[0.07] p-2.5 text-[11px]" data-testid={`port-vmhost-${p.idx}`}>
      <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-indigo-300 mb-1.5">
        <Cube size={12} weight="fill" /> Porta host di virtualizzazione · {h.kind} · {h.vms.length} VM
      </div>
      <div className="flex items-center gap-1.5 mb-1.5" data-testid={`port-vmhost-host-${p.idx}`}>
        <Desktop size={14} className="text-cyan-300" />
        <span className="text-[9px] uppercase text-[var(--text-muted)]">Connesso a</span>
        {h.host_name ? (
          <>
            {h.host_ip
              ? <Link to={`/devices/${encodeURIComponent(h.host_ip)}`} className="font-semibold text-cyan-300 hover:underline">{h.host_name}</Link>
              : <span className="font-semibold text-cyan-300">{h.host_name}</span>}
            {h.host_ip && <span className="font-mono text-[10px] text-[var(--text-muted)]">{h.host_ip}</span>}
            {h.host_mac && <span className="font-mono text-[9px] text-[var(--text-muted)]">{h.host_mac}</span>}
          </>
        ) : (
          <span className="text-[var(--text-secondary)]">server host non identificato (impostalo in "Server e sue VM")</span>
        )}
      </div>
      <ul className="pl-5 space-y-0.5 border-l border-indigo-500/30 ml-1.5" data-testid={`port-vmhost-vms-${p.idx}`}>
        {h.vms.map((v) => (
          <li key={v.mac} className="flex items-baseline gap-1.5 text-[10px]" data-testid={`port-vmhost-vm-${p.idx}-${v.mac}`}>
            <span className="text-indigo-300">↳</span>
            {v.ip
              ? <Link to={`/devices/${encodeURIComponent(v.ip)}`} className="font-semibold text-neutral-100 hover:underline">{v.name}</Link>
              : <span className="font-semibold text-neutral-100">{v.name}</span>}
            {v.ip && <span className="font-mono text-[9px] text-[var(--text-secondary)]">{v.ip}</span>}
            <span className="font-mono text-[9px] text-[var(--text-muted)]">{v.mac}</span>
          </li>
        ))}
      </ul>
      <p className="text-[9px] text-[var(--text-muted)] mt-1.5">
        Più VM sulla stessa porta: "Dispositivo cambiato" solo se spariscono tutte e compare un dispositivo nuovo; una VM nuova = avviso informativo.
      </p>
    </div>
  );
}
