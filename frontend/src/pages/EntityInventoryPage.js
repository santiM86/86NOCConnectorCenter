import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { API } from "@/App";
import { Cube, CircleNotch, ArrowsClockwise, X, Fingerprint, Detective } from "@phosphor-icons/react";

const SOURCE_META = {
  monitoring: { label: "Monitoraggio", cls: "bg-sky-500/15 text-sky-400 border-sky-500/40" },
  snmp: { label: "SNMP", cls: "bg-indigo-500/15 text-indigo-400 border-indigo-500/40" },
  datto: { label: "Datto RMM", cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40" },
  agent: { label: "Agent", cls: "bg-violet-500/15 text-violet-400 border-violet-500/40" },
  ilo: { label: "iLO/Redfish", cls: "bg-amber-500/15 text-amber-400 border-amber-500/40" },
  cmdb_manual: { label: "Anagrafica", cls: "bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/40" },
  nebula: { label: "Zyxel Nebula", cls: "bg-cyan-500/15 text-cyan-400 border-cyan-500/40" },
};

const KEY_LABEL = { serial: "Serial", mac: "MAC", datto_uid: "Datto UID", agent_id: "Agent ID", hostname: "Hostname", ip: "IP" };

function SourceBadge({ s }) {
  const m = SOURCE_META[s] || { label: s, cls: "bg-slate-500/15 text-slate-300 border-slate-500/40" };
  return <span className={`px-1.5 py-0.5 rounded border text-[9px] font-semibold ${m.cls}`}>{m.label}</span>;
}

function EntityDetail({ id, onClose }) {
  const [ent, setEnt] = useState(null);
  const [impact, setImpact] = useState(null);
  useEffect(() => {
    axios.get(`${API}/cmdb/entities/${id}`).then(r => setEnt(r.data)).catch(() => setEnt(null));
    axios.get(`${API}/cmdb/entities/${id}/impact`).then(r => setImpact(r.data)).catch(() => setImpact(null));
  }, [id]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} data-testid="entity-detail-backdrop" />
      <div className="fixed inset-y-0 right-0 w-full sm:w-[460px] bg-[var(--bg-panel)] border-l border-[var(--border-subtle)] z-50 overflow-y-auto shadow-2xl" data-testid="entity-detail-panel">
      <div className="flex items-center justify-between p-4 border-b border-[var(--border-subtle)] sticky top-0 bg-[var(--bg-panel)]">
        <div className="flex items-center gap-2"><Cube size={18} className="text-indigo-400" weight="duotone" />
          <span className="font-semibold text-[var(--text-primary)]">{ent?.name || "…"}</span></div>
        <button onClick={onClose} data-testid="entity-detail-close" className="text-[var(--text-muted)] hover:text-white"><X size={18} /></button>
      </div>
      {!ent ? <div className="p-8 flex justify-center"><CircleNotch size={22} className="animate-spin text-indigo-400" /></div> : (
        <div className="p-4 space-y-4 text-sm">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Fonti che vedono questo asset</div>
            <div className="flex flex-wrap gap-1">{(ent.sources || []).map(s => <SourceBadge key={s} s={s} />)}</div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[["Organizzazione", ent.org_name], ["IP principale", ent.primary_ip], ["Tipo", ent.device_type], ["Vitale", ent.is_vital ? "Sì" : "No"],
              ["Modello", ent.attrs?.model], ["Vendor", ent.attrs?.vendor], ["OS (agent)", ent.attrs?.agent_os],
              ["Nome Datto", ent.attrs?.datto_name], ["VM Hyper-V", ent.attrs?.hyperv_vm_name]].filter(x => x[1]).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-[var(--bg-deep)] p-2">
                <div className="text-[10px] text-[var(--text-muted)]">{k}</div>
                <div className="text-[var(--text-primary)] truncate">{String(v)}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1"><Fingerprint size={12} /> Chiavi d'identità</div>
            <div className="space-y-1">{Object.entries(ent.identity || {}).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs border-b border-[var(--border-subtle)]/50 py-1">
                <span className="text-[var(--text-muted)]">{KEY_LABEL[k] || k}</span>
                <span className="font-mono text-[var(--text-primary)] truncate ml-2">{String(v).replace(ent.client_id + ":", "")}</span>
              </div>))}</div>
          </div>
          {ent.manual && Object.keys(ent.manual).length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Anagrafica manuale</div>
              <div className="grid grid-cols-2 gap-2">{Object.entries(ent.manual).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-[var(--bg-deep)] p-2">
                  <div className="text-[10px] text-[var(--text-muted)]">{k}</div>
                  <div className="text-[var(--text-primary)] truncate">{String(v)}</div>
                </div>))}</div>
            </div>
          )}
          <div className="text-[10px] text-[var(--text-muted)] font-mono">entity_id: {ent.entity_id}</div>

          {impact && impact.impacted_count > 0 && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-3" data-testid="entity-impact">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-bold uppercase tracking-wider text-red-400">⚠ Impatto se cade</span>
                <span className="text-[10px] font-mono bg-[var(--bg-deep)] px-1.5 py-0.5 rounded text-red-300" data-testid="entity-impact-count">
                  {impact.impacted_count} a valle{impact.impacted_vital ? ` · ${impact.impacted_vital} vitali` : ""}
                </span>
              </div>
              <div className="space-y-1 max-h-52 overflow-y-auto">
                {impact.impacted.map(d => (
                  <div key={d.entity_id} className="flex items-center gap-2 text-[11px]">
                    <span className="w-4 text-[var(--text-muted)] font-mono">{"›".repeat(Math.min(d.depth, 3))}</span>
                    <span className="text-[var(--text-primary)] flex-1 truncate">{d.name}{d.is_vital && <span className="text-amber-400 ml-1">★</span>}</span>
                    <span className="font-mono text-[var(--text-muted)]">{d.primary_ip}</span>
                    <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--bg-deep)] text-[var(--text-muted)]">{d.rel_type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {impact && impact.impacted_count === 0 && (
            <div className="text-[11px] text-[var(--text-muted)]" data-testid="entity-impact-none">
              Nessuna entità nota a valle (foglia della topologia o topologia non ancora mappata).
            </div>
          )}
        </div>
      )}
      </div>
    </>
  );
}

export default function EntityInventoryPage() {
  const [ents, setEnts] = useState([]);
  const [clients, setClients] = useState([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [sel, setSel] = useState(null);

  const clientName = (cid) => (clients.find(c => c.id === cid) || {}).name || cid?.slice(0, 8) || "—";

  const load = () => {
    setLoading(true);
    axios.get(`${API}/cmdb/entities`, { params: filter ? { client_id: filter } : {} })
      .then(r => setEnts(r.data.entities || [])).catch(() => setEnts([])).finally(() => setLoading(false));
  };
  useEffect(() => { axios.get(`${API}/clients`).then(r => setClients(r.data || [])).catch(() => {}); }, []);
  useEffect(load, [filter]);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      await axios.post(`${API}/cmdb/entities/rebuild`, null, { params: filter ? { client_id: filter } : {} });
      load();
      toast.success("Inventario ricostruito: fonti fuse e identità aggiornate.");
    } catch {
      toast.error("Ricostruzione fallita.");
    } finally { setRebuilding(false); }
  };

  return (
    <div className="p-4 sm:p-6 space-y-5" data-testid="entity-inventory-page">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-indigo-500/15 border border-indigo-500/30"><Cube size={22} className="text-indigo-400" weight="duotone" /></div>
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Inventario Unificato (CMDB)</h1>
            <p className="text-sm text-[var(--text-muted)] mt-1 max-w-2xl">Ogni asset è UNA entità che fonde tutte le fonti (Monitoraggio, SNMP, Datto, Agent, iLO, Anagrafica), con identità stabile anche al cambio IP.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="entity-client-filter"
            className="px-3 py-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)]">
            <option value="">Tutti i clienti</option>
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={rebuild} disabled={rebuilding} data-testid="entity-rebuild-btn"
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-500/15 border border-indigo-500/40 text-indigo-300 text-sm hover:bg-indigo-500/25 disabled:opacity-50">
            <ArrowsClockwise size={15} className={rebuilding ? "animate-spin" : ""} /> {rebuilding ? "Ricostruzione…" : "Ricostruisci"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><CircleNotch size={26} className="animate-spin text-indigo-400" /></div>
      ) : ents.length === 0 ? (
        <div className="text-center py-16 text-[var(--text-muted)]" data-testid="entity-empty">
          <Detective size={40} className="mx-auto mb-2 opacity-50" />
          Nessuna entità. Premi “Ricostruisci” per fondere le fonti.
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--border-subtle)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--bg-deep)] text-[var(--text-muted)] text-left text-xs">
              <tr><th className="px-3 py-2">Asset</th><th className="px-3 py-2">Cliente</th><th className="px-3 py-2">IP</th><th className="px-3 py-2">Tipo</th><th className="px-3 py-2">Fonti fuse</th></tr>
            </thead>
            <tbody>
              {ents.map(e => (
                <tr key={e.entity_id} onClick={() => setSel(e.entity_id)} data-testid={`entity-row-${e.primary_ip}`}
                  className="border-t border-[var(--border-subtle)] hover:bg-[var(--bg-deep)] cursor-pointer">
                  <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{e.name}{e.is_vital && <span className="ml-1 text-[9px] text-amber-400">★</span>}</td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">{clientName(e.client_id)}</td>
                  <td className="px-3 py-2 font-mono text-[var(--text-muted)]">{e.primary_ip}</td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">{e.device_type || "—"}</td>
                  <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{(e.sources || []).map(s => <SourceBadge key={s} s={s} />)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sel && <EntityDetail id={sel} onClose={() => setSel(null)} />}
    </div>
  );
}
