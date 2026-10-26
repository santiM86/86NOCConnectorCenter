import { Link } from "react-router-dom";
import { Cube, Desktop, TreeStructure } from "@phosphor-icons/react";

const fmt = (iso) => {
  if (!iso) return null;
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

const Row = ({ d, since, idx, icon: Icon, host }) => (
  <li className={`flex items-center gap-2 py-1 ${host ? "" : "pl-5"}`} data-testid={`cable-attached-${idx}-${d.mac}`}>
    {!host && <span className="text-indigo-300 text-[10px]">↳</span>}
    <Icon size={12} className={host ? "text-cyan-300" : "text-indigo-300"} />
    <div className="min-w-0 flex-1">
      {d.ip
        ? <Link to={`/devices/${encodeURIComponent(d.ip)}`} className={`text-[11px] font-semibold hover:underline ${host ? "text-cyan-300" : "text-neutral-100"}`}>{d.name || d.ip}</Link>
        : <span className="text-[11px] font-semibold text-neutral-100">{d.name || d.mac}</span>}
      <div className="text-[9px] font-mono text-[var(--text-muted)]">{d.ip && `${d.ip} · `}{d.mac}</div>
    </div>
    <span className="text-[9px] text-emerald-300/90 whitespace-nowrap" title="Prima volta visto su questa porta" data-testid={`cable-attached-since-${idx}-${d.mac}`}>
      {fmt(since) ? `agganciato dal ${fmt(since)}` : "data di aggancio non disponibile"}
    </span>
  </li>
);

export default function PortAttachedTree({ p }) {
  const seen = Object.fromEntries((p.port_devices || []).map((d) => [String(d.mac || "").toUpperCase(), d.first_seen]));
  const since = (d) => seen[d.mac] || (p.attached || []).find((a) => a.mac === d.mac)?.first_seen_at;
  const h = p.vm_host;
  const host = h && h.host_mac ? { name: h.host_name, ip: h.host_ip, mac: h.host_mac } : null;
  const children = h ? h.vms : (p.attached || []);
  if (!host && children.length === 1) {
    const s = fmt(since(children[0]));
    return s ? <p className="mt-1 text-[9px] text-emerald-300/90" data-testid={`cable-attached-since-${p.idx}-${children[0].mac}`}>Agganciato a questa porta dal {s}</p> : null;
  }
  if (!host && children.length === 0) return null;
  return (
    <div className="mt-2 rounded-lg border border-indigo-500/30 bg-indigo-500/[0.05] p-2.5" data-testid={`cable-attached-tree-${p.idx}`}>
      <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-indigo-300 mb-1">
        <TreeStructure size={11} weight="bold" />
        {h ? `Collegati sotto · host ${h.kind} · ${h.vms.length} VM` : `Collegati sotto · ${children.length} dispositivi sulla stessa porta`}
      </div>
      <ul className="divide-y divide-white/5">
        {host && <Row d={host} since={since(host)} idx={p.idx} icon={Desktop} host />}
        {children.map((d) => <Row key={d.mac} d={d} since={since(d)} idx={p.idx} icon={h ? Cube : Desktop} host={!h} />)}
      </ul>
    </div>
  );
}
