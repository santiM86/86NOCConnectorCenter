import { Link } from "react-router-dom";
import { Cube, Desktop, Devices } from "@phosphor-icons/react";
import DattoInfoPanel from "@/components/DattoInfoPanel";
import { PortUserLine, fmtSeen } from "@/components/PortUser";
import { vmKindOf } from "@/components/portMulti";

const DeviceRow = ({ a, p, clientId, role }) => {
  const since = (p.port_devices || []).find((d) => String(d.mac || "").toUpperCase() === a.mac)?.first_seen || a.first_seen_at;
  const kind = vmKindOf(a.mac);
  const Icon = role === "host" ? Desktop : kind ? Cube : Desktop;
  return (
    <li className={`py-1.5 ${role === "vm" ? "pl-5 border-l border-indigo-500/30 ml-1.5" : ""}`} data-testid={`port-multi-row-${p.idx}-${a.mac}`}>
      <div className="flex items-center gap-1.5 flex-wrap">
        <Icon size={12} className={role === "host" ? "text-cyan-300" : kind ? "text-indigo-300" : "text-neutral-300"} />
        {role === "host" && <span className="text-[8px] font-bold uppercase px-1 rounded bg-cyan-500/15 text-cyan-200">Server host</span>}
        {kind && role !== "host" && <span className="text-[8px] font-bold uppercase px-1 rounded bg-indigo-500/15 text-indigo-200">VM {kind}</span>}
        {a.source === "datto_rmm" && <span className="text-[8px] font-bold px-1 rounded bg-fuchsia-500/20 text-fuchsia-300">DATTO</span>}
        {a.ip
          ? <Link to={`/devices/${encodeURIComponent(a.ip)}`} className="text-[11px] font-semibold text-neutral-100 hover:underline">{a.name || a.ip}</Link>
          : <span className="text-[11px] font-semibold text-neutral-100">{a.name || a.mac}</span>}
        {a.ip && <span className="font-mono text-[9px] text-[var(--text-secondary)]">{a.ip}</span>}
        <span className="font-mono text-[9px] text-[var(--text-muted)]">{a.mac}</span>
        {since && <span className="ml-auto text-[9px] text-emerald-300/90" data-testid={`port-multi-since-${p.idx}-${a.mac}`}>agganciato dal {fmtSeen(since)}</span>}
      </div>
      {a.datto_user && <PortUserLine u={{ user: a.datto_user }} idx={`multi-${p.idx}-${a.mac}`} size="xs" />}
      {a.source === "datto_rmm" && <DattoInfoPanel clientId={clientId} ip={a.ip} mac={a.mac} name={a.name} testIdSuffix={`multi-${p.idx}-${a.mac}`} />}
    </li>
  );
};

export default function PortMultiDevices({ p, clientId }) {
  const list = p.attached || [];
  const h = p.vm_host;
  const host = h?.host_mac ? list.find((a) => a.mac === h.host_mac) || { mac: h.host_mac, name: h.host_name, ip: h.host_ip } : null;
  const others = host ? list.filter((a) => a.mac !== host.mac) : list;
  const total = p.attached_count || list.length;
  const vmCount = list.filter((a) => vmKindOf(a.mac)).length;
  return (
    <div className="rounded-md border border-indigo-500/40 bg-indigo-500/[0.06] p-2.5" data-testid={`port-multi-${p.idx}`}>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-200 mb-1">
        <Devices size={14} weight="bold" />
        Connesso a {total} dispositivi
        {vmCount > 0 && <span className="text-indigo-300 normal-case font-semibold">· {vmCount} VM {h?.kind || ""}</span>}
      </div>
      {h && !host && (
        <p className="text-[9px] text-[var(--text-muted)] mb-1" data-testid={`port-multi-nohost-${p.idx}`}>
          Server host non identificato: impostalo da "Server e sue VM" nella lista dispositivi del cliente.
        </p>
      )}
      <ul className="divide-y divide-white/5">
        {host && <DeviceRow a={host} p={p} clientId={clientId} role="host" />}
        {others.map((a) => <DeviceRow key={a.mac} a={a} p={p} clientId={clientId} role={host ? "vm" : "dev"} />)}
      </ul>
      {total > list.length && <p className="text-[9px] text-[var(--text-muted)] mt-1">… e altri {total - list.length}</p>}
      <p className="text-[9px] text-[var(--text-muted)] mt-1.5">
        Più dispositivi sulla stessa porta: "Dispositivo cambiato" solo se spariscono tutti e compare un dispositivo nuovo{vmCount > 0 ? "; una VM nuova = avviso informativo" : ""}.
      </p>
    </div>
  );
}
