/**
 * Switch Ports Detail Page
 * ========================
 * Vista porta-per-porta di uno switch con stato (up/down/admin-down), velocità
 * e neighbor LLDP agganciato. Usata come deep-link dalla scheda device.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { ArrowsClockwise, LinkSimple, WifiHigh, WifiSlash, Prohibit } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

function fmtSpeed(mbps) {
  if (!mbps || mbps <= 0) return "—";
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(mbps % 1000 ? 1 : 0)} Gb`;
  return `${mbps} Mb`;
}

function fmtDuration(s) {
  if (!s || s <= 0) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}g ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function PortStatusIcon({ oper, admin }) {
  if (admin === 2) return <Prohibit size={14} className="text-[var(--text-muted)]" title="Admin down" />;
  if (oper === 1) return <WifiHigh size={14} className="text-emerald-400" title="Up" />;
  return <WifiSlash size={14} className="text-red-400" title="Down" />;
}

function PortCard({ p, onClick, active }) {
  const admin = p.admin;
  const oper = p.oper;
  let bg = "bg-[var(--bg-card)] border-[var(--bg-border)]";
  let label = "—";
  if (admin === 2) { bg = "bg-neutral-700/30 border-neutral-500/40"; label = "OFF"; }
  else if (oper === 1) { bg = "bg-emerald-500/15 border-emerald-400/40"; label = fmtSpeed(p.speed_mbps); }
  else { bg = "bg-red-500/15 border-red-400/40"; label = "DOWN"; }
  const hasNeigh = !!p.neighbor;
  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-center justify-center aspect-square border rounded text-[10px] font-mono transition hover:scale-105 ${bg} ${active ? "ring-2 ring-cyan-400" : ""}`}
      data-testid={`switch-port-card-${p.idx}`}
      title={`Porta ${p.idx} · ${p.name}\n${p.oper_status}/${p.admin_status} · ${fmtSpeed(p.speed_mbps)}${hasNeigh ? "\n→ " + (p.neighbor.remote_sys_name || p.neighbor.remote_ip) : ""}`}
    >
      <span className="absolute top-0.5 left-1 text-[9px] text-[var(--text-muted)]">{p.idx}</span>
      {hasNeigh && <LinkSimple size={9} className="absolute top-0.5 right-0.5 text-cyan-300" />}
      <PortStatusIcon oper={oper} admin={admin} />
      <span className="text-[9px] mt-0.5">{label}</span>
    </button>
  );
}

export default function SwitchPortsPage() {
  const { deviceIp } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("all");  // all | up | down | admin_down | with_neighbor
  const [selected, setSelected] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/devices/${encodeURIComponent(deviceIp)}/switch-ports`);
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento");
    } finally {
      setLoading(false);
    }
  }, [deviceIp]);

  useEffect(() => { reload(); }, [reload]);

  if (loading) return <div className="p-6 text-[var(--text-muted)] text-sm">Caricamento…</div>;
  if (!data) return <div className="p-6 text-[var(--text-muted)] text-sm">Nessun dato</div>;

  const ports = (data.ports || []).filter(p => {
    if (filter === "up") return p.oper === 1 && p.admin === 1;
    if (filter === "down") return p.oper === 2 && p.admin === 1;
    if (filter === "admin_down") return p.admin === 2;
    if (filter === "with_neighbor") return !!p.neighbor;
    return true;
  });
  const t = data.totals || {};

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="switch-ports-page">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm">←</button>
        <div>
          <h1 className="text-lg font-bold">Porte Switch · <span className="font-mono text-cyan-300">{data.device_ip}</span></h1>
          <p className="text-[10px] text-[var(--text-muted)]">
            {t.total} porte · <span className="text-emerald-300">{t.up} up</span> ·{" "}
            <span className="text-red-300">{t.down} down</span> ·{" "}
            <span className="text-[var(--text-muted)]">{t.admin_down} admin-down</span> ·{" "}
            <span className="text-cyan-300">{t.with_neighbor} con neighbor LLDP</span>
            {data.updated_at && ` · aggiornato ${new Date(data.updated_at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`}
          </p>
        </div>
        <div className="ml-auto">
          <Button size="sm" variant="outline" onClick={reload} className="h-7 gap-1 text-[11px]"><ArrowsClockwise size={12} /> Refresh</Button>
        </div>
      </div>

      {/* Filtri */}
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        {[
          { id: "all", label: `Tutte (${t.total || 0})`, color: "cyan" },
          { id: "up", label: `Up (${t.up || 0})`, color: "emerald" },
          { id: "down", label: `Down (${t.down || 0})`, color: "red" },
          { id: "admin_down", label: `Admin-down (${t.admin_down || 0})`, color: "neutral" },
          { id: "with_neighbor", label: `Con neighbor (${t.with_neighbor || 0})`, color: "cyan" },
        ].map(f => {
          const active = filter === f.id;
          const cls = f.color === "emerald" ? (active ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-emerald-500/30 text-emerald-300/70")
            : f.color === "red" ? (active ? "bg-red-500/20 border-red-400 text-red-300" : "border-red-500/30 text-red-300/70")
            : f.color === "neutral" ? (active ? "bg-neutral-500/30 border-neutral-400 text-neutral-200" : "border-neutral-500/30 text-[var(--text-muted)]")
            : (active ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-cyan-500/30 text-cyan-300/70");
          return (
            <button key={f.id} onClick={() => setFilter(f.id)} className={`px-3 py-1 rounded-md border text-[11px] font-semibold ${cls}`} data-testid={`port-filter-${f.id}`}>
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Matrice porte */}
      <div className="noc-panel p-3">
        <div className="grid grid-cols-8 md:grid-cols-12 gap-1.5">
          {ports.map(p => (
            <PortCard key={p.idx} p={p} active={selected?.idx === p.idx} onClick={() => setSelected(p)} />
          ))}
        </div>
        {ports.length === 0 && <div className="text-center text-[11px] text-[var(--text-muted)] py-3">Nessuna porta con questo filtro</div>}
      </div>

      {/* Tabella dettagliata */}
      <div className="noc-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="noc-table w-full text-[11px]" data-testid="switch-ports-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Nome</th>
                <th>Stato</th>
                <th>Admin</th>
                <th>Speed</th>
                <th>Ultimo change</th>
                <th>Collegato a</th>
              </tr>
            </thead>
            <tbody>
              {ports.map(p => (
                <tr key={p.idx} data-testid={`switch-port-row-${p.idx}`} className={selected?.idx === p.idx ? "bg-cyan-500/10" : ""}>
                  <td className="font-mono font-semibold">{p.idx}</td>
                  <td className="font-mono">{p.name}</td>
                  <td>
                    {p.admin === 2 ? (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-600/30 text-neutral-200 border border-neutral-400/30">ADMIN-DOWN</span>
                    ) : p.oper === 1 ? (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">UP</span>
                    ) : (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30">DOWN</span>
                    )}
                  </td>
                  <td className="text-[10px] text-[var(--text-muted)]">{p.admin_status}</td>
                  <td className="font-mono text-[10px]">{fmtSpeed(p.speed_mbps)}</td>
                  <td className="text-[10px] text-[var(--text-muted)]">{fmtDuration(p.last_change_s)}</td>
                  <td>
                    {p.neighbor ? (
                      <div className="flex items-center gap-1.5 text-[10px]">
                        <LinkSimple size={10} className="text-cyan-300" />
                        <div>
                          <span className="font-semibold text-cyan-300">{p.neighbor.remote_sys_name || "(senza nome)"}</span>
                          {p.neighbor.remote_port_desc && <span className="text-[var(--text-muted)] ml-1">· porta {p.neighbor.remote_port_desc}</span>}
                          {p.neighbor.remote_ip && <span className="text-[var(--text-muted)] ml-1 font-mono">({p.neighbor.remote_ip})</span>}
                        </div>
                      </div>
                    ) : (
                      <span className="text-[10px] text-[var(--text-muted)] italic">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
