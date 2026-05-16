import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  PlugsConnected, ArrowClockwise, ArrowCircleUp, MagnifyingGlass, Buildings,
  Cpu, Clock, WifiHigh, WifiSlash, Warning, Stethoscope,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

/**
 * AgentsPage — admin view di TUTTI gli agent Go v4 installati sui clienti.
 *
 * Sostituisce la vecchia pagina /connectors (PowerShell v3 deprecato).
 * Mostra: hostname, cliente, versione (badge outdated vs latest),
 * stato live, OS, IP, ultimo heartbeat, moduli alive/stuck.
 *
 * Azioni:
 *  - Aggiorna singolo agent → POST /api/agents/bulk-update {agent_ids:[id]}
 *  - Aggiorna tutti obsoleti → POST /api/agents/bulk-update {only_outdated:true}
 *  - Diagnostica → POST /api/agents/{id}/command "run_diagnostics"
 *  - Vai al cliente → /client/{client_id}
 */
export default function AgentsPage() {
  const [agents, setAgents] = useState([]);
  const [clients, setClients] = useState({});
  const [latest, setLatest] = useState(null);
  const [search, setSearch] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyIds, setBusyIds] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const fetchAll = async () => {
    try {
      const [agRes, cliRes, latRes] = await Promise.all([
        axios.get(`${API}/agents`),
        axios.get(`${API}/clients`),
        axios.get(`${API}/agent/latest-version`),
      ]);
      setAgents(agRes.data?.agents || []);
      const cmap = {};
      (cliRes.data || []).forEach((c) => { cmap[c.id] = c.name; });
      setClients(cmap);
      setLatest(latRes.data?.version || null);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore caricamento agent");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 15000);
    return () => clearInterval(id);
  }, []);

  // Versione normalizzata per confronto (rimuove 'v', +metadata, -dev)
  const normVer = (v) => {
    if (!v) return "";
    let s = String(v).trim().replace(/^v/i, "");
    for (const sep of ["+", "-"]) {
      const i = s.indexOf(sep);
      if (i >= 0) s = s.slice(0, i);
    }
    return s;
  };
  const latestN = normVer(latest);

  const filtered = useMemo(() => {
    const s = search.toLowerCase().trim();
    return agents.filter((a) => {
      if (clientFilter && a.client_id !== clientFilter) return false;
      if (!s) return true;
      return (
        (a.hostname || "").toLowerCase().includes(s) ||
        (a.agent_id || "").toLowerCase().includes(s) ||
        (a.os || "").toLowerCase().includes(s) ||
        (clients[a.client_id] || "").toLowerCase().includes(s) ||
        (a.ips || []).join(" ").toLowerCase().includes(s)
      );
    });
  }, [agents, search, clientFilter, clients]);

  const liveCount = agents.filter((a) => a.live).length;
  const outdated = agents.filter((a) => {
    const an = normVer(a.agent_version);
    return latestN && an && an !== latestN;
  });
  const outdatedLive = outdated.filter((a) => a.live);

  const updateOne = async (a) => {
    if (!a.live) {
      toast.error("L'agent non è connesso (LIVE). Aspetta che torni online e ritenta.");
      return;
    }
    if (!confirm(`Aggiornare ${a.hostname || a.agent_id.slice(0, 8)} a ${latest || "latest"}?`)) return;
    setBusyIds((s) => new Set([...s, a.agent_id]));
    try {
      const r = await axios.post(`${API}/agents/bulk-update`, {
        agent_ids: [a.agent_id],
        version: latest || undefined,
      });
      if (r.data.sent_count > 0) {
        toast.success(`Comando inviato a ${a.hostname || a.agent_id.slice(0, 8)}`);
      } else {
        toast.error(`Failed: ${(r.data.failed?.[0]?.reason) || "agent non risponde"}`);
      }
      // re-fetch dopo 5s
      setTimeout(fetchAll, 5000);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore update");
    } finally {
      setBusyIds((s) => { const x = new Set(s); x.delete(a.agent_id); return x; });
    }
  };

  const updateAllOutdated = async () => {
    if (outdatedLive.length === 0) {
      toast.error("Nessun agent obsoleto è attualmente connesso.");
      return;
    }
    if (!confirm(`Aggiornare ${outdatedLive.length} connector LIVE a ${latest}?\n\nGli agent si riavvieranno autonomamente.`)) return;
    setBulkBusy(true);
    try {
      const r = await axios.post(`${API}/agents/bulk-update`, { only_outdated: true, version: latest });
      toast.success(`Inviato a ${r.data.sent_count} agent. Failed: ${r.data.failed_count}`);
      setTimeout(fetchAll, 5000);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore bulk-update");
    } finally {
      setBulkBusy(false);
    }
  };

  const runDiagnostics = async (a) => {
    if (!a.live) { toast.error("Agent non LIVE"); return; }
    setBusyIds((s) => new Set([...s, a.agent_id]));
    try {
      const r = await axios.post(`${API}/agents/${a.agent_id}/command`, {
        name: "run_diagnostics", timeout: 30,
      });
      // mostra in toast un summary leggibile
      const reply = r.data?.reply;
      toast.success(`Diagnostica ${a.hostname}: ${JSON.stringify(reply).slice(0, 200)}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore diagnostica");
    } finally {
      setBusyIds((s) => { const x = new Set(s); x.delete(a.agent_id); return x; });
    }
  };

  const uniqueClients = Object.entries(
    agents.reduce((acc, a) => { acc[a.client_id] = (acc[a.client_id] || 0) + 1; return acc; }, {})
  );

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="agents-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <PlugsConnected size={22} /> Agent v4 (Connector Go)
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Gestione centralizzata: aggiornamenti remoti, stato live, diagnostica
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchAll}
          className="rounded-md text-xs h-8" data-testid="agents-refresh">
          <ArrowClockwise size={14} className="mr-1.5" /> Aggiorna
        </Button>
      </div>

      {/* KPI Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Totale" value={agents.length} icon={Cpu} color="indigo" testId="kpi-total" />
        <KPI label="Live" value={liveCount} icon={WifiHigh} color="emerald" testId="kpi-live" />
        <KPI label="Versione corrente" value={latest || "—"} icon={ArrowCircleUp} color="sky" testId="kpi-latest" mono />
        <KPI label="Obsoleti" value={outdated.length}
             sub={outdatedLive.length > 0 ? `${outdatedLive.length} aggiornabili ora` : ""}
             icon={Warning} color={outdated.length > 0 ? "amber" : "zinc"} testId="kpi-outdated" />
      </div>

      {/* Bulk action banner */}
      {outdated.length > 0 && (
        <div className="noc-panel p-3 border-amber-500/40 bg-amber-500/5 flex items-center justify-between"
          data-testid="bulk-update-banner">
          <div className="flex items-center gap-2.5">
            <ArrowCircleUp size={18} weight="fill" className="text-amber-400" />
            <div>
              <p className="text-xs text-amber-200 font-semibold">
                {outdated.length} connector su versione precedente
              </p>
              <p className="text-[10px] text-amber-300/70">
                {outdatedLive.length} attualmente live → aggiornabili ora · {outdated.length - outdatedLive.length} offline (rimandare)
              </p>
            </div>
          </div>
          <Button size="sm" onClick={updateAllOutdated} disabled={bulkBusy || outdatedLive.length === 0}
            className="rounded-md h-8 text-xs bg-amber-500/90 hover:bg-amber-500 text-amber-950 font-bold"
            data-testid="bulk-update-all-btn">
            <ArrowCircleUp size={13} className="mr-1.5" />
            {bulkBusy ? "Invio…" : `Aggiorna ${outdatedLive.length} ora`}
          </Button>
        </div>
      )}

      {/* Filters */}
      <div className="noc-panel p-3 flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[200px]">
          <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            placeholder="Cerca per hostname, IP, OS, cliente, agent_id..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 bg-[var(--bg-input)] border border-[var(--bg-border)] rounded px-3 py-1.5 text-xs text-[var(--text-primary)]"
            data-testid="agents-search"
          />
        </div>
        <select
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
          className="bg-[var(--bg-input)] border border-[var(--bg-border)] rounded px-2.5 py-1.5 text-xs text-[var(--text-primary)]"
          data-testid="agents-client-filter"
        >
          <option value="">Tutti i clienti ({agents.length})</option>
          {uniqueClients.map(([cid, n]) => (
            <option key={cid} value={cid}>
              {clients[cid] || cid.slice(0, 8)} ({n})
            </option>
          ))}
        </select>
        {(search || clientFilter) && (
          <button onClick={() => { setSearch(""); setClientFilter(""); }}
            className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] px-2"
            data-testid="agents-filter-clear">
            ✕ pulisci
          </button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-[var(--text-muted)] text-xs">Caricamento…</p>
      ) : filtered.length === 0 ? (
        <div className="noc-panel p-8 text-center">
          <PlugsConnected size={32} className="mx-auto text-[var(--text-muted)] mb-2" />
          <p className="text-[var(--text-muted)] text-xs">
            {agents.length === 0
              ? "Nessun agent v4 registrato. Installa l'agent sul cliente tramite la pagina Clienti → bottone Installer."
              : "Nessun agent corrisponde al filtro."}
          </p>
        </div>
      ) : (
        <div className="noc-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)] uppercase tracking-wider">
                <tr className="text-[9px]">
                  <th className="text-left p-2.5">Stato</th>
                  <th className="text-left p-2.5">Hostname</th>
                  <th className="text-left p-2.5">Cliente</th>
                  <th className="text-left p-2.5">Versione</th>
                  <th className="text-left p-2.5">OS</th>
                  <th className="text-left p-2.5">IP</th>
                  <th className="text-left p-2.5">Ultimo Heartbeat</th>
                  <th className="text-left p-2.5">Moduli</th>
                  <th className="p-2.5 text-right">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => {
                  const verN = normVer(a.agent_version);
                  const isOutdated = latestN && verN && verN !== latestN;
                  const stuck = (a.modules_stuck || []).length;
                  const alive = (a.modules_alive || []).length;
                  return (
                    <tr key={a.agent_id} className="border-t border-[var(--bg-border)] hover:bg-[var(--bg-card)]/30 transition-colors"
                      data-testid={`agent-row-${a.agent_id}`}>
                      <td className="p-2.5">
                        {a.live ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            <WifiHigh size={10} weight="fill" /> LIVE
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
                            <WifiSlash size={10} /> OFFLINE
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 font-medium text-[var(--text-primary)]">
                        {a.hostname || <span className="text-[var(--text-muted)] italic">{a.agent_id.slice(0, 12)}</span>}
                        {a.labels?.role && <span className="ml-1.5 text-[9px] text-[var(--text-muted)]">[{a.labels.role}]</span>}
                      </td>
                      <td className="p-2.5">
                        {clients[a.client_id] ? (
                          <Link to={`/client/${a.client_id}`} className="text-sky-400 hover:text-sky-300 hover:underline flex items-center gap-1"
                            data-testid={`agent-client-link-${a.agent_id}`}>
                            <Buildings size={11} /> {clients[a.client_id]}
                          </Link>
                        ) : (
                          <span className="text-[var(--text-muted)] font-mono text-[10px]">{a.client_id?.slice(0, 8) || "—"}</span>
                        )}
                      </td>
                      <td className="p-2.5">
                        <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                          isOutdated ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                     : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        }`}>
                          {a.agent_version || "—"}
                        </span>
                      </td>
                      <td className="p-2.5 text-[var(--text-muted)] text-[10px]">
                        {a.os} {a.arch && <span className="opacity-60">{a.arch}</span>}
                      </td>
                      <td className="p-2.5 font-mono text-[10px] text-[var(--text-muted)]" title={(a.ips || []).join(", ")}>
                        {(a.ips || []).filter(ip => !ip.startsWith("169.254"))[0] || "—"}
                      </td>
                      <td className="p-2.5 text-[10px] text-[var(--text-muted)]">
                        <Clock size={10} className="inline mr-1" />
                        {fmtRel(a.last_heartbeat_at || a.last_hello_at)}
                      </td>
                      <td className="p-2.5 text-[10px]">
                        <span className="text-emerald-400" title={(a.modules_alive || []).join(", ")}>{alive} ok</span>
                        {stuck > 0 && (
                          <span className="ml-1 text-red-400" title={(a.modules_stuck || []).join(", ")}>
                            · {stuck} stuck
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 text-right whitespace-nowrap">
                        <button
                          onClick={() => updateOne(a)}
                          disabled={!a.live || !isOutdated || busyIds.has(a.agent_id)}
                          className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border border-amber-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                          title={!a.live ? "Agent offline" : !isOutdated ? "Già aggiornato" : "Aggiorna"}
                          data-testid={`agent-update-${a.agent_id}`}>
                          <ArrowCircleUp size={10} className="inline mr-0.5" />
                          {busyIds.has(a.agent_id) ? "…" : "Update"}
                        </button>
                        <button
                          onClick={() => runDiagnostics(a)}
                          disabled={!a.live || busyIds.has(a.agent_id)}
                          className="ml-1 text-[10px] px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 hover:bg-sky-500/20 border border-sky-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                          title="Esegui diagnostica live"
                          data-testid={`agent-diag-${a.agent_id}`}>
                          <Stethoscope size={10} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function KPI({ label, value, sub, icon: Icon, color, testId, mono }) {
  const colorMap = {
    indigo: "text-indigo-400 border-indigo-500/20 bg-indigo-500/5",
    emerald: "text-emerald-400 border-emerald-500/20 bg-emerald-500/5",
    sky: "text-sky-400 border-sky-500/20 bg-sky-500/5",
    amber: "text-amber-400 border-amber-500/30 bg-amber-500/5",
    zinc: "text-zinc-400 border-zinc-500/20 bg-zinc-500/5",
  };
  return (
    <div className={`noc-panel p-3 border ${colorMap[color] || ""}`} data-testid={testId}>
      <div className="flex items-center gap-2">
        <Icon size={16} weight="fill" className={colorMap[color]?.split(" ")[0] || ""} />
        <p className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
      </div>
      <p className={`text-lg font-bold mt-1 ${colorMap[color]?.split(" ")[0] || "text-[var(--text-primary)]"} ${mono ? "font-mono text-sm" : "font-heading"}`}>
        {value}
      </p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </div>
  );
}

function fmtRel(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const ms = Date.now() - d.getTime();
    if (ms < 60000) return "ora";
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m fa`;
    if (ms < 86400000) return `${Math.floor(ms / 3600000)}h fa`;
    return `${Math.floor(ms / 86400000)}g fa`;
  } catch { return "—"; }
}
