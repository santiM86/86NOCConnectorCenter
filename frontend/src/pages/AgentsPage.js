import { useState, useEffect, useMemo, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  PlugsConnected, ArrowClockwise, ArrowCircleUp, MagnifyingGlass, Buildings,
  Cpu, Clock, WifiHigh, WifiSlash, Warning, Stethoscope, Trash, X,
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
  // v4.15.x: vista albero raggruppata per cliente (default ON). Persistita
  // in localStorage cosi' la preferenza resta sui reload.
  const [groupByClient, setGroupByClient] = useState(() => {
    try { return localStorage.getItem("agents.groupByClient") !== "0"; }
    catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem("agents.groupByClient", groupByClient ? "1" : "0"); }
    catch {}
  }, [groupByClient]);
  // Toggle apertura/chiusura per singolo cliente nella vista albero.
  const [collapsedClients, setCollapsedClients] = useState(new Set());
  const toggleClientCollapse = (cid) => {
    setCollapsedClients((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid); else next.add(cid);
      return next;
    });
  };

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
  }, []);

  // Adaptive polling: 3s se c'è un update/uninstall in corso, altrimenti 15s
  useEffect(() => {
    const anyBusy = agents.some(
      (a) => a.update_status === "in_progress" || a.uninstall_status === "in_progress"
    );
    const id = setInterval(fetchAll, anyBusy ? 3000 : 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents.some((a) => a.update_status === "in_progress" || a.uninstall_status === "in_progress")]);

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

  // Deduplicazione "ghost agents": per ciascuna coppia (client_id, hostname)
  // tieni SOLO il record più recente (live > last_hello_at desc). I duplicati
  // sono UUID generati prima del fix v4.4.0 di persistenza agent_id.txt.
  // Toggle "Mostra tutti" per vedere comunque l'intera cronologia.
  const [showAllGhosts, setShowAllGhosts] = useState(false);
  const dedupedAgents = useMemo(() => {
    if (showAllGhosts) return agents;
    const byKey = new Map();
    const tsOf = (a) => {
      const v = a.last_heartbeat_at || a.last_hello_at || a.first_seen_at || "";
      return v ? new Date(v).getTime() : 0;
    };
    for (const a of agents) {
      const key = `${a.client_id || ""}::${(a.hostname || a.agent_id || "").toLowerCase()}`;
      const prev = byKey.get(key);
      if (!prev) { byKey.set(key, a); continue; }
      // priorità: live, poi ts più recente
      if (a.live && !prev.live) { byKey.set(key, a); continue; }
      if (!a.live && prev.live) continue;
      if (tsOf(a) > tsOf(prev)) byKey.set(key, a);
    }
    return Array.from(byKey.values());
  }, [agents, showAllGhosts]);

  const filtered = useMemo(() => {
    const s = search.toLowerCase().trim();
    return dedupedAgents.filter((a) => {
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
  }, [dedupedAgents, search, clientFilter, clients]);

  const hiddenGhostsCount = agents.length - dedupedAgents.length;

  const liveCount = dedupedAgents.filter((a) => a.live).length;
  const outdated = dedupedAgents.filter((a) => {
    const an = normVer(a.agent_version);
    return latestN && an && an !== latestN;
  });
  const outdatedLive = outdated.filter((a) => a.live);

  const updateOne = async (a) => {
    if (!a.live) {
      toast.error("L'agent non è connesso (LIVE). Aspetta che torni online e ritenta.");
      return;
    }
    if (!latest || latest === "latest") {
      toast.error("Versione target non risolvibile: il Center non riesce a leggere l'ultima release da GitHub. Imposta AGENT_GITHUB_TOKEN nel .env del backend o forza con AGENT_LATEST_VERSION.");
      return;
    }
    if (!confirm(`Aggiornare ${a.hostname || a.agent_id.slice(0, 8)} a ${latest}?`)) return;
    setBusyIds((s) => new Set([...s, a.agent_id]));
    try {
      const r = await axios.post(`${API}/agents/bulk-update`, {
        agent_ids: [a.agent_id],
        version: latest,
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
    if (!latest || latest === "latest") {
      toast.error("Versione target non risolvibile dal Center (GitHub API). Imposta AGENT_GITHUB_TOKEN nel backend.");
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

  // ---- Vedi log agent (nocagent.log live dal PC client) ----
  const [agentLogTarget, setAgentLogTarget] = useState(null);
  const [agentLogBusy, setAgentLogBusy] = useState(false);
  const [agentLogData, setAgentLogData] = useState(null);

  const fetchAgentLog = async (a) => {
    setAgentLogTarget(a);
    setAgentLogBusy(true);
    setAgentLogData(null);
    try {
      const r = await axios.get(`${API}/agents/${a.agent_id}/agent-logs`);
      setAgentLogData(r.data);
    } catch (err) {
      setAgentLogData({ error: err.response?.data?.detail || err.message || "Errore" });
    } finally {
      setAgentLogBusy(false);
    }
  };

  // ---- Vedi log upgrade (recupera transcript installer dal PC client) ----
  const [logTarget, setLogTarget] = useState(null);    // l'agent per cui mostriamo il log
  const [logBusy, setLogBusy] = useState(false);
  const [logData, setLogData] = useState(null);        // reply dal backend

  const fetchUpgradeLog = async (a) => {
    setLogTarget(a);
    setLogBusy(true);
    setLogData(null);
    try {
      const r = await axios.get(`${API}/agents/${a.agent_id}/upgrade-log`);
      setLogData(r.data);
    } catch (err) {
      setLogData({ error: err.response?.data?.detail || err.message || "Errore" });
    } finally {
      setLogBusy(false);
    }
  };

  // Stato modale rimozione
  const [removeTarget, setRemoveTarget] = useState(null); // l'agent corrente
  const [removeMode, setRemoveMode] = useState("center"); // "center" | "full"
  const [removing, setRemoving] = useState(false);

  const openRemove = (a) => {
    setRemoveTarget(a);
    setRemoveMode(a.live ? "full" : "center");
  };

  const confirmRemove = async () => {
    if (!removeTarget) return;
    const a = removeTarget;
    const isFull = removeMode === "full";
    setRemoving(true);
    try {
      const r = await axios.delete(`${API}/agents/${a.agent_id}`, {
        params: { uninstall_remote: isFull, purge_data: true },
      });
      const purged = Object.entries(r.data.collections_purged || {})
        .map(([c, n]) => `${c}=${n}`).join(", ") || "-";
      if (isFull) {
        if (r.data.tracking_uninstall) {
          // Uninstall avviato — progress bar la traccia, NON rimuovere ottimisticamente
          toast.success(`${a.hostname || a.agent_id}: comando uninstall inviato (${r.data.uninstall_status}). Attendi 30-60s per la conferma.`);
        } else if (r.data.uninstall_status === "command_sent") {
          toast.success(`${a.hostname || a.agent_id}: comando uninstall inviato + DB pulito (${purged})`);
        } else if (r.data.uninstall_status === "agent_offline") {
          toast.warning(`${a.hostname}: agent offline, rimosso solo dal Center (${purged}). Esegui uninstall.ps1 manualmente sul PC.`);
        } else {
          toast.error(`${a.hostname}: ${r.data.uninstall_error || "errore uninstall"}`);
        }
      } else {
        toast.success(`${a.hostname || a.agent_id}: rimosso dal Center (${purged})`);
      }
      // Optimistic UI SOLO se non c'è tracking_uninstall (altrimenti voglio vedere progress)
      if (!r.data.tracking_uninstall) {
        setAgents((prev) => prev.filter((x) => x.agent_id !== a.agent_id));
      }
      setRemoveTarget(null);
      setTimeout(fetchAll, 1500);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore rimozione");
    } finally {
      setRemoving(false);
    }
  };

  // Sblocca stato bloccato: reset campi update_* / uninstall_* in DB.
  // Usato quando un agent resta in "in_progress" per più tempo del
  // timeout (es. wrapper PS crashato senza heartbeat, agent crashato
  // post-update, rete instabile). Endpoint admin-only su backend.
  const forceCleanup = async (a, purge = false) => {
    if (!a) return;
    const label = a.hostname || a.agent_id;
    const msg = purge
      ? `Eliminare COMPLETAMENTE l'agent ${label} dal Center (DB + storico)?\n\nQuesto NON disinstalla il software dal PC client. Usalo solo se sei sicuro che il record è uno zombie.`
      : `Sbloccare lo stato dell'agent ${label}?\n\nVerranno azzerati i campi update_* e uninstall_* (record mantenuto, l'agent può riconnettersi normalmente).`;
    if (!window.confirm(msg)) return;
    setBusyIds((s) => new Set(s).add(a.agent_id));
    try {
      const r = await axios.post(
        `${API}/agents/${a.agent_id}/force-cleanup`,
        null,
        { params: { purge_db: purge } },
      );
      if (r.data.purged) {
        toast.success(`${label}: rimosso dal Center (purge_db=true)`);
        setAgents((prev) => prev.filter((x) => x.agent_id !== a.agent_id));
      } else {
        toast.success(`${label}: stato sbloccato (campi update_*/uninstall_* azzerati)`);
      }
      setTimeout(fetchAll, 1000);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore sblocco stato");
    } finally {
      setBusyIds((s) => { const x = new Set(s); x.delete(a.agent_id); return x; });
    }
  };

  const uniqueClients = Object.entries(
    dedupedAgents.reduce((acc, a) => { acc[a.client_id] = (acc[a.client_id] || 0) + 1; return acc; }, {})
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
        <KPI label="Totale" value={dedupedAgents.length} icon={Cpu} color="indigo" testId="kpi-total"
             sub={hiddenGhostsCount > 0 ? `${hiddenGhostsCount} ghost nascosti` : ""} />
        <KPI label="Live" value={liveCount} icon={WifiHigh} color="emerald" testId="kpi-live" />
        <KPI label="Versione corrente" value={latest || "—"} icon={ArrowCircleUp} color="sky" testId="kpi-latest" mono />
        <KPI label="Obsoleti" value={outdated.length}
             sub={outdatedLive.length > 0 ? `${outdatedLive.length} aggiornabili ora` : ""}
             icon={Warning} color={outdated.length > 0 ? "amber" : "zinc"} testId="kpi-outdated" />
      </div>

      {/* Warning banner: latest version non risolta → updates impossibili */}
      {(!latest || latest === "latest") && agents.length > 0 && (
        <div className="noc-panel p-3 border-red-500/40 bg-red-500/5 flex items-start gap-2.5"
          data-testid="latest-version-warning">
          <Warning size={18} weight="fill" className="text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 text-xs">
            <p className="font-bold text-red-300">Versione target non risolvibile</p>
            <p className="text-red-200/70 text-[11px] mt-0.5">
              Il Center non riesce a leggere l'ultima release da GitHub
              (rate-limit unauth = 60/h). Senza una versione concreta, gli
              update remoti falliranno con "timeout". Imposta uno dei due
              env nel <span className="font-mono">.env</span> del backend:
            </p>
            <ul className="text-[10px] mt-1.5 font-mono text-red-200/80 space-y-0.5">
              <li>• <span className="text-amber-400">AGENT_GITHUB_TOKEN</span>=ghp_xxx  (Personal Access Token, scope: <span className="font-bold">public_repo</span> sufficiente)</li>
              <li>• <span className="text-amber-400">AGENT_LATEST_VERSION</span>=v4.11.0  (override manuale - sconsigliato se hai CI/CD)</li>
            </ul>
          </div>
        </div>
      )}

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
        <label className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] cursor-pointer ml-2"
          title="Mostra anche record obsoleti con UUID vecchi (pre-fix persistenza agent_id v4.4.0)"
          data-testid="agents-show-ghosts-label">
          <input type="checkbox" checked={showAllGhosts}
            onChange={(e) => setShowAllGhosts(e.target.checked)}
            data-testid="agents-show-ghosts-toggle" />
          Mostra ghost ({hiddenGhostsCount})
        </label>
        <label className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] cursor-pointer ml-2"
          title="Raggruppa gli agent per cliente in una vista ad albero (utile per clienti multi-VLAN con piu' connector)"
          data-testid="agents-group-by-client-label">
          <input type="checkbox" checked={groupByClient}
            onChange={(e) => setGroupByClient(e.target.checked)}
            data-testid="agents-group-by-client-toggle" />
          🌲 Vista albero per cliente
        </label>
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
                {(() => {
                  // v4.15.x: vista ad albero — ordina per cliente e poi
                  // per role (master prima), insert header row al cambio
                  // di client_id. Sintesi: ricalcolo qui per non creare
                  // un'altra useMemo che cambia gli hook in render.
                  const sorted = groupByClient
                    ? [...filtered].sort((x, y) => {
                        const cx = (clients[x.client_id] || x.client_id || "").toLowerCase();
                        const cy = (clients[y.client_id] || y.client_id || "").toLowerCase();
                        if (cx !== cy) return cx.localeCompare(cy);
                        // master prima dello scanner all'interno del cliente
                        const rx = (x.labels?.role || "master").toLowerCase();
                        const ry = (y.labels?.role || "master").toLowerCase();
                        if (rx !== ry) return rx === "master" ? -1 : 1;
                        // poi hostname stabile
                        return (x.hostname || "").localeCompare(y.hostname || "");
                      })
                    : filtered;
                  const nodes = [];
                  let lastCid = null;
                  // Conta gli agent per client_id sui filtered (per la pillola)
                  const counts = sorted.reduce((acc, a) => {
                    acc[a.client_id] = (acc[a.client_id] || 0) + 1; return acc;
                  }, {});
                  sorted.forEach((a) => {
                    if (groupByClient && a.client_id !== lastCid) {
                      lastCid = a.client_id;
                      const cName = clients[a.client_id] || a.client_id?.slice(0, 8) || "—";
                      const isCollapsed = collapsedClients.has(a.client_id);
                      const cnt = counts[a.client_id] || 0;
                      nodes.push(
                        <tr key={`group-${a.client_id || "none"}`}
                          className="bg-[var(--bg-card)]/40 border-t border-[var(--bg-border)]"
                          data-testid={`agents-group-header-${a.client_id || "none"}`}>
                          <td colSpan={9} className="p-1.5 px-2.5">
                            <button
                              type="button"
                              onClick={() => toggleClientCollapse(a.client_id)}
                              className="flex items-center gap-2 text-[11px] font-bold text-sky-300 hover:text-sky-200 transition-colors"
                              data-testid={`agents-group-toggle-${a.client_id || "none"}`}
                            >
                              <span className="text-[var(--text-muted)] font-mono w-3 text-center">
                                {isCollapsed ? "▶" : "▼"}
                              </span>
                              <Buildings size={13} />
                              <Link to={`/client/${a.client_id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                                {cName}
                              </Link>
                              <span className="text-[9px] font-normal text-[var(--text-muted)] ml-1">
                                {cnt} {cnt === 1 ? "connector" : "connector"}
                              </span>
                            </button>
                          </td>
                        </tr>
                      );
                    }
                    if (groupByClient && collapsedClients.has(a.client_id)) return;
                  const verN = normVer(a.agent_version);
                  const isOutdated = latestN && verN && verN !== latestN;
                  const stuck = (a.modules_stuck || []).length;
                  const alive = (a.modules_alive || []).length;
                  nodes.push(
                    <tr key={a.agent_id} className={`border-t border-[var(--bg-border)] hover:bg-[var(--bg-card)]/30 transition-colors ${groupByClient ? "bg-transparent" : ""}`}
                      data-testid={`agent-row-${a.agent_id}`}>
                      <td className={`p-2.5 ${groupByClient ? "pl-7" : ""}`}>
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
                        {/* v4.23 — Store-and-forward visibility badge.
                            Si accende solo se il connector ha buffer locale
                            non vuoto (link WS instabile o queue satura).
                            Aiuta a capire se i ritardi nelle metriche sono
                            "in transito" o "persi". */}
                        {a.spool_depth > 0 && (
                          <span
                            className="ml-1 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-mono bg-amber-900/40 text-amber-300 border border-amber-700/40"
                            title={`Buffer locale (Zabbix-style): ${a.spool_depth} frame in coda${a.spool_oldest_at ? `, piu' vecchio: ${a.spool_oldest_at}` : ""}${a.spool_dropped_total ? `, droppati totali: ${a.spool_dropped_total}` : ""}`}
                            data-testid={`agent-spool-badge-${a.agent_id}`}
                          >
                            ⇪ {a.spool_depth}
                          </span>
                        )}
                        {a.spool_dropped_total > 0 && a.spool_depth === 0 && (
                          <span
                            className="ml-1 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-mono bg-red-900/30 text-red-300 border border-red-700/40"
                            title={`Frame droppati totali per saturazione: ${a.spool_dropped_total}. Considera di aumentare Spool.MaxFrames o ridurre il polling interval.`}
                            data-testid={`agent-spool-dropped-${a.agent_id}`}
                          >
                            ✕ {a.spool_dropped_total}
                          </span>
                        )}
                      </td>
                      <td className="p-2.5 text-right whitespace-nowrap">
                        {a.uninstall_status === "in_progress" ? (
                          <div className="inline-flex flex-col items-end gap-0.5 min-w-[120px]" data-testid={`agent-uninstall-progress-${a.agent_id}`}>
                            <span className="text-[9px] text-red-400 font-mono animate-pulse">
                              disinstallando… {a.uninstall_progress || 0}%
                            </span>
                            <div className="w-full h-1 bg-[var(--bg-input)] rounded-full overflow-hidden">
                              <div className="h-full bg-red-500 transition-all duration-500"
                                style={{ width: `${a.uninstall_progress || 0}%` }} />
                            </div>
                            <span className="text-[8px] text-[var(--text-muted)]">
                              {a.uninstall_method === "legacy_update" ? "via magic update" : "via WS"} · {Math.floor(a.uninstall_elapsed_sec || 0)}s
                            </span>
                            {a.uninstall_elapsed_sec > 180 && (
                              <button onClick={() => forceCleanup(a, false)}
                                className="text-[9px] text-amber-400 hover:underline"
                                data-testid={`agent-force-unblock-uninstall-${a.agent_id}`}
                                title="Stato bloccato da > 3 min — azzera campi uninstall_*">
                                ⚠ sblocca stato
                              </button>
                            )}
                          </div>
                        ) : a.uninstall_status === "completed" ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[9px] border border-emerald-500/20"
                            data-testid={`agent-uninstall-done-${a.agent_id}`}>
                            ✓ disinstallato
                          </span>
                        ) : a.uninstall_status === "failed" || a.uninstall_status === "timeout" ? (
                          <div className="inline-flex flex-col items-end gap-0.5 min-w-[120px]">
                            <span className="text-[9px] text-red-400 px-2 py-0.5 rounded bg-red-500/10 border border-red-500/20 cursor-help"
                              title={a.uninstall_error || ""}>
                              ✕ uninstall {a.uninstall_status}
                            </span>
                            {a.uninstall_error && (
                              <span className="text-[8px] text-[var(--text-muted)] truncate max-w-[200px]" title={a.uninstall_error}>
                                {a.uninstall_error.slice(0, 50)}…
                              </span>
                            )}
                            <button onClick={() => openRemove(a)}
                              className="text-[9px] text-amber-400 hover:underline">
                              ↻ ritenta
                            </button>
                          </div>
                        ) : a.update_status === "in_progress" ? (
                          <div className="inline-flex flex-col items-end gap-0.5 min-w-[100px]" data-testid={`agent-progress-${a.agent_id}`}>
                            <div className="flex items-center gap-1.5">
                              <span className="text-[9px] text-amber-400 font-mono animate-pulse">
                                aggiornando… {a.update_progress || 0}%
                              </span>
                            </div>
                            <div className="w-full h-1 bg-[var(--bg-input)] rounded-full overflow-hidden">
                              <div className="h-full bg-amber-500 transition-all duration-500"
                                style={{ width: `${a.update_progress || 0}%` }} />
                            </div>
                            <span className="text-[8px] text-[var(--text-muted)]">
                              → {a.update_target_version} · {Math.floor(a.update_elapsed_sec || 0)}s
                            </span>
                            {a.update_elapsed_sec > 300 && (
                              <button onClick={() => forceCleanup(a, false)}
                                className="text-[9px] text-amber-400 hover:underline"
                                data-testid={`agent-force-unblock-update-${a.agent_id}`}
                                title="Stato bloccato da > 5 min — azzera campi update_*">
                                ⚠ sblocca stato
                              </button>
                            )}
                          </div>
                        ) : a.update_status === "completed" ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[9px] border border-emerald-500/20"
                            data-testid={`agent-update-done-${a.agent_id}`}>
                            ✓ aggiornato
                          </span>
                        ) : a.update_status === "failed" || a.update_status === "timeout" ? (
                          <div className="inline-flex flex-col items-end gap-0.5 min-w-[120px]">
                            <span className="text-[9px] text-red-400 px-2 py-0.5 rounded bg-red-500/10 border border-red-500/20 cursor-help"
                              title={a.update_error || "Errore sconosciuto"}>
                              ✕ {a.update_status === "timeout" ? "timeout" : "fallito"}
                            </span>
                            {a.update_error && (
                              <span className="text-[8px] text-[var(--text-muted)] truncate max-w-[200px]"
                                title={a.update_error}>
                                {a.update_error.length > 40 ? a.update_error.slice(0, 40) + "…" : a.update_error}
                              </span>
                            )}
                            <button onClick={() => updateOne(a)}
                              className="text-[9px] text-amber-400 hover:underline"
                              data-testid={`agent-retry-${a.agent_id}`}>
                              ↻ ritenta
                            </button>
                            <button onClick={() => fetchUpgradeLog(a)}
                              className="text-[9px] text-sky-400 hover:underline"
                              data-testid={`agent-viewlog-${a.agent_id}`}>
                              📜 vedi log
                            </button>
                            <button onClick={() => openRemove(a)}
                              className="text-[9px] text-red-400 hover:underline"
                              data-testid={`agent-remove-failed-${a.agent_id}`}>
                              🗑 rimuovi
                            </button>
                          </div>
                        ) : (
                          <>
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
                            <button
                              onClick={() => fetchUpgradeLog(a)}
                              disabled={!a.live}
                              className="ml-1 text-[10px] px-2 py-0.5 rounded bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                              title="Vedi log ultimo tentativo di upgrade"
                              data-testid={`agent-viewlog-btn-${a.agent_id}`}>
                              📜
                            </button>
                            <button
                              onClick={() => fetchAgentLog(a)}
                              disabled={!a.live}
                              className="ml-1 text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                              title="Vedi nocagent.log (log live del servizio)"
                              data-testid={`agent-runtime-log-btn-${a.agent_id}`}>
                              📋
                            </button>
                            <button
                              onClick={() => openRemove(a)}
                              className="ml-1 text-[10px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20 transition-colors"
                              title="Rimuovi agent (Center + opzionale uninstall remoto)"
                              data-testid={`agent-remove-${a.agent_id}`}>
                              <Trash size={10} />
                            </button>
                            {(a.update_status || a.uninstall_status) && (
                              <button
                                onClick={() => forceCleanup(a, false)}
                                className="ml-1 text-[10px] px-2 py-0.5 rounded bg-zinc-500/10 text-zinc-400 hover:bg-amber-500/10 hover:text-amber-400 border border-zinc-500/20 transition-colors"
                                title={`Sblocca stato (update=${a.update_status || '—'} uninstall=${a.uninstall_status || '—'})`}
                                data-testid={`agent-force-cleanup-${a.agent_id}`}>
                                ⚠
                              </button>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                  });
                  return nodes;
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {/* Modale rimozione agent */}
      {removeTarget && (
        <RemoveAgentModal
          agent={removeTarget}
          clientName={clients[removeTarget.client_id]}
          mode={removeMode}
          setMode={setRemoveMode}
          removing={removing}
          onConfirm={confirmRemove}
          onClose={() => setRemoveTarget(null)}
        />
      )}

      {logTarget && (
        <UpgradeLogModal
          agent={logTarget}
          clientName={clients[logTarget.client_id]}
          loading={logBusy}
          data={logData}
          onRefresh={() => fetchUpgradeLog(logTarget)}
          onClose={() => { setLogTarget(null); setLogData(null); }}
        />
      )}

      {agentLogTarget && (
        <AgentLogsModal
          agent={agentLogTarget}
          clientName={clients[agentLogTarget.client_id]}
          loading={agentLogBusy}
          data={agentLogData}
          onRefresh={() => fetchAgentLog(agentLogTarget)}
          onClose={() => { setAgentLogTarget(null); setAgentLogData(null); }}
        />
      )}
    </div>
  );
}

function RemoveAgentModal({ agent, clientName, mode, setMode, removing, onConfirm, onClose }) {
  const canFull = agent.live;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="remove-agent-modal">
      <div className="bg-[var(--bg-panel)] border border-red-500/30 rounded-lg max-w-lg w-full p-5 shadow-2xl">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-heading font-bold text-red-400 flex items-center gap-2">
            <Trash size={18} /> Rimozione Connector
          </h2>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            data-testid="remove-modal-close">
            <X size={18} />
          </button>
        </div>

        <div className="mb-4 p-3 bg-[var(--bg-card)] rounded border border-[var(--bg-border)]">
          <p className="text-xs text-[var(--text-muted)]">Stai per rimuovere:</p>
          <p className="font-heading font-bold text-[var(--text-primary)] mt-1">
            {agent.hostname || agent.agent_id.slice(0, 12)}
            {agent.labels?.role && <span className="text-[10px] text-[var(--text-muted)] ml-2">[{agent.labels.role}]</span>}
          </p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
            cliente: <span className="text-sky-400">{clientName || agent.client_id?.slice(0, 8)}</span> ·
            versione: <span className="font-mono">{agent.agent_version}</span> ·
            stato: {agent.live ? <span className="text-emerald-400">LIVE</span> : <span className="text-zinc-400">offline</span>}
          </p>
        </div>

        <div className="space-y-2 mb-4">
          <label className={`flex items-start gap-2.5 p-3 rounded border cursor-pointer transition-colors ${
            mode === "center" ? "border-sky-500/40 bg-sky-500/5" : "border-[var(--bg-border)] hover:border-[var(--text-muted)]"
          }`} data-testid="remove-mode-center">
            <input type="radio" name="remove-mode" value="center" checked={mode === "center"}
              onChange={() => setMode("center")} className="mt-0.5" />
            <div className="flex-1">
              <p className="text-xs font-bold text-[var(--text-primary)]">Solo dal Center</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                Cancella TUTTE le tracce dal database NOC: <span className="font-mono">managed_agents,
                sys_metrics_latest/history, device_poll_status, agent_log_buffer</span>. L'agent sul PC
                resta installato — se è ancora attivo e si riconnette, ricreerà un record. Utile per
                pulire ghost agents senza toccare la macchina.
              </p>
            </div>
          </label>

          <label className={`flex items-start gap-2.5 p-3 rounded border transition-colors ${
            canFull ? "cursor-pointer" : "opacity-50 cursor-not-allowed"
          } ${
            mode === "full" ? "border-red-500/40 bg-red-500/5" : "border-[var(--bg-border)] hover:border-[var(--text-muted)]"
          }`} data-testid="remove-mode-full">
            <input type="radio" name="remove-mode" value="full" checked={mode === "full"}
              disabled={!canFull}
              onChange={() => setMode("full")} className="mt-0.5" />
            <div className="flex-1">
              <p className="text-xs font-bold text-[var(--text-primary)] flex items-center gap-1.5">
                Rimozione completa (uninstall remoto)
                {!canFull && <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-500/20 text-zinc-400">solo agent LIVE</span>}
              </p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                Invia comando WS <span className="font-mono">uninstall</span> all'agent:
                stop service <span className="font-mono">86NocAgent/86NocWatchdog</span>, rimozione
                binari <span className="font-mono">C:\Program Files\86NocAgent</span>, rimozione config
                <span className="font-mono">ProgramData\86NocAgent</span>, rimozione voce
                "Programmi e funzionalità", rimozione shortcut. Poi pulizia DB.
                <span className="block text-amber-400 mt-1">⚠ Operazione irreversibile sul PC del cliente.</span>
              </p>
            </div>
          </label>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-[var(--bg-border)]">
          <Button variant="outline" size="sm" onClick={onClose} disabled={removing}
            data-testid="remove-cancel-btn" className="h-8 text-xs">
            Annulla
          </Button>
          <Button size="sm" onClick={onConfirm} disabled={removing}
            className="h-8 text-xs bg-red-600 hover:bg-red-500 text-white font-bold"
            data-testid="remove-confirm-btn">
            <Trash size={12} className="mr-1.5" />
            {removing ? "Rimozione…" : (mode === "full" ? "Rimuovi tutto" : "Rimuovi dal Center")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function UpgradeLogModal({ agent, clientName, loading, data, onRefresh, onClose }) {
  // Estrae il body utile dalla reply nidificata del backend
  const reply = data?.reply || null;
  const marker = reply?.marker || null;
  const latestLog = reply?.latest_log || "";
  const latestPath = reply?.latest_path || "";
  const latestSize = reply?.latest_size || 0;
  const latestMtime = reply?.latest_mtime || "";
  const files = reply?.files || [];
  const baseDir = reply?.base_dir || "";
  const supported = data?.supported !== false;
  const source = data?.source || ""; // db_upload | ws_command | ws_unsupported

  const sourceLabel =
    source === "db_upload" ? "📤 dall'installer (POST al Center)"
    : source === "ws_command" ? "📡 dall'agent (live via WebSocket)"
    : "";

  const copyLog = () => {
    if (!latestLog) return;
    try {
      navigator.clipboard.writeText(latestLog);
      toast.success("Log copiato negli appunti");
    } catch {
      toast.error("Clipboard non disponibile");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="upgrade-log-modal">
      <div className="bg-[var(--bg-panel)] border border-violet-500/30 rounded-lg max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--bg-border)]">
          <div>
            <h2 className="text-base font-heading font-bold text-violet-400 flex items-center gap-2">
              📜 Log Upgrade Connector
            </h2>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono">
              {agent.hostname || agent.agent_id?.slice(0, 12)} · {clientName || agent.client_id?.slice(0, 8)} · v{agent.agent_version}
            </p>
            {sourceLabel && (
              <p className="text-[10px] text-violet-400 mt-1" data-testid="upgrade-log-source">
                Sorgente log: {sourceLabel}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={onRefresh} disabled={loading}
              className="text-[10px] px-2 py-1 rounded bg-sky-500/10 text-sky-400 hover:bg-sky-500/20 border border-sky-500/20 disabled:opacity-30"
              data-testid="upgrade-log-refresh">
              <ArrowClockwise size={11} className="inline mr-1" />
              {loading ? "Carico…" : "Ricarica"}
            </button>
            <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] p-1"
              data-testid="upgrade-log-close">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && (
            <div className="text-center py-8 text-[var(--text-muted)] text-xs">
              Recupero log dal PC client (timeout 15s)…
            </div>
          )}

          {!loading && data?.error && (
            <div className="p-3 rounded bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
              <p className="font-bold mb-1">Errore</p>
              <p className="whitespace-pre-wrap">{data.error}</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-2">
                Suggerimento: se l&apos;agent &egrave; offline, recupera il log manualmente sul PC:
                <span className="font-mono ml-1">C:\Windows\Temp\86noc-upgrade-logs\noc_upgrade_latest.log</span>
              </p>
            </div>
          )}

          {!loading && !supported && (
            <div className="p-3 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
              <p className="font-bold mb-1">Comando non supportato</p>
              <p>L&apos;agent &egrave; troppo vecchio (richiede v4.13+). Aggiorna il connector e riprova.</p>
            </div>
          )}

          {!loading && supported && reply && (
            <>
              {/* Status marker */}
              {marker && (
                <div className={`p-3 rounded border text-xs ${
                  marker.status === "completed" ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" :
                  marker.status === "failed" ? "bg-red-500/10 border-red-500/30 text-red-400" :
                  marker.status === "started" ? "bg-amber-500/10 border-amber-500/30 text-amber-400" :
                  "bg-zinc-500/10 border-zinc-500/30 text-zinc-400"
                }`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-bold uppercase text-[11px] tracking-wider">
                      Stato ultimo upgrade: {marker.status || "sconosciuto"}
                    </span>
                    {marker.started && (
                      <span className="text-[10px] font-mono opacity-70">avviato {marker.started}</span>
                    )}
                  </div>
                  {marker.extra && (
                    <p className="text-[10px] font-mono mt-1 opacity-80 break-all">{marker.extra}</p>
                  )}
                  {marker.log_file && (
                    <p className="text-[10px] font-mono mt-1 opacity-70 break-all">file: {marker.log_file}</p>
                  )}
                </div>
              )}

              {/* Info */}
              <div className="text-[10px] text-[var(--text-muted)] font-mono flex flex-wrap gap-x-4 gap-y-1">
                <span>BaseDir: <span className="text-[var(--text-primary)]">{baseDir}</span></span>
                {latestPath && <span>Latest: <span className="text-[var(--text-primary)]">{latestPath}</span></span>}
                {latestSize > 0 && <span>Size: <span className="text-[var(--text-primary)]">{(latestSize / 1024).toFixed(1)} KB</span></span>}
                {latestMtime && <span>MTime: <span className="text-[var(--text-primary)]">{latestMtime}</span></span>}
              </div>

              {!reply.exists && (
                <div className="p-3 rounded bg-zinc-500/10 border border-zinc-500/30 text-zinc-400 text-xs">
                  <p>Nessuna cartella <span className="font-mono">{baseDir}</span> sul PC client.</p>
                  <p className="mt-1 text-[10px]">
                    Probabile: questo agent non ha mai eseguito un upgrade dopo l&apos;introduzione dello script con logging persistente (v4.13). Esegui un update e riprova.
                  </p>
                </div>
              )}

              {/* Content log */}
              {latestLog ? (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">noc_upgrade_latest.log</span>
                    <button onClick={copyLog}
                      className="text-[10px] text-sky-400 hover:underline"
                      data-testid="upgrade-log-copy">
                      📋 copia tutto
                    </button>
                  </div>
                  <pre className="text-[10px] leading-tight font-mono bg-black/40 p-3 rounded border border-[var(--bg-border)] overflow-x-auto max-h-[50vh] whitespace-pre-wrap break-words"
                    data-testid="upgrade-log-content">
                    {latestLog}
                  </pre>
                </div>
              ) : source === "db_upload" ? (
                (() => {
                  // Se l'upgrade è completed/success, mostriamo solo una piccola
                  // nota informativa (non un warning allarmante).
                  // Il warning grosso resta solo per upgrade failed/partial.
                  const status = String(reply?.marker?.status || "").toLowerCase();
                  const isSuccess = status === "success" || status === "completed";
                  if (isSuccess) {
                    return (
                      <div className="p-2.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[10px]">
                        <span className="font-semibold">Upgrade riuscito</span> — il transcript di
                        questo run risulta vuoto (probabilmente un upgrade vecchio prima del fix
                        encoding). Nessuna azione richiesta. I prossimi upgrade mostreranno il log
                        completo.
                      </div>
                    );
                  }
                  return (
                    <div className="p-3 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
                      <p className="font-bold mb-1">Upload ricevuto ma transcript vuoto</p>
                      <p>
                        L&apos;installer ha confermato lo stato dell&apos;upgrade ma il body del transcript &egrave; vuoto.
                        Cause possibili:
                      </p>
                      <ul className="list-disc list-inside mt-1 text-[10px] text-amber-300/80">
                        <li>File del transcript non flushato prima di <span className="font-mono">Stop-Transcript</span></li>
                        <li>Encoding UTF-16 (default <span className="font-mono">Start-Transcript</span>) non letto correttamente</li>
                        <li>Script eseguito senza <span className="font-mono">-Version</span> (vedi target=None)</li>
                      </ul>
                      <p className="mt-2 text-[10px]">
                        Fix: prossima release dello script forzer&agrave; encoding UTF-8 e flush esplicito. Nel frattempo riprova l&apos;upgrade.
                      </p>
                    </div>
                  );
                })()
              ) : reply.exists ? (
                <div className="p-3 rounded bg-zinc-500/10 border border-zinc-500/30 text-zinc-400 text-xs">
                  Cartella presente ma <span className="font-mono">noc_upgrade_latest.log</span> assente. Esegui un nuovo update e riprova.
                </div>
              ) : null}

              {/* File list */}
              {files.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1.5">
                    Ultimi {files.length} file in {baseDir}
                  </p>
                  <div className="space-y-0.5 text-[10px] font-mono">
                    {files.map((f) => (
                      <div key={f.name} className="flex items-center gap-3 px-2 py-0.5 hover:bg-[var(--bg-card)]/50 rounded">
                        <span className="text-[var(--text-muted)] w-32 truncate">{f.mtime?.slice(0, 19).replace("T", " ")}</span>
                        <span className="text-amber-400 w-16 text-right">{(f.size / 1024).toFixed(1)} KB</span>
                        <span className="text-[var(--text-primary)] flex-1 truncate">{f.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2.5 border-t border-[var(--bg-border)] text-[10px] text-[var(--text-muted)]">
          Suggerimento: in caso di crash dell&apos;installer su Windows controlla anche
          <span className="font-mono text-[var(--text-primary)] mx-1">Event Viewer → Application → Source=86NocAgent</span>
          (Event ID 1001/1099/1100).
        </div>
      </div>
    </div>
  );
}

function AgentLogsModal({ agent, clientName, loading, data, onRefresh, onClose }) {
  const reply = data?.reply || null;
  const latestLog = reply?.latest_log || "";
  const latestSize = reply?.latest_size || 0;
  const latestMtime = reply?.latest_mtime || "";
  const files = reply?.files || [];
  const baseDir = reply?.base_dir || "";
  const logPath = reply?.log_path || "";
  const supported = data?.supported !== false;
  const exists = reply?.exists;

  const copyLog = () => {
    if (!latestLog) return;
    try {
      navigator.clipboard.writeText(latestLog);
      toast.success("Log copiato negli appunti");
    } catch {
      toast.error("Clipboard non disponibile");
    }
  };

  // Auto-scroll to bottom on first load (live tail UX)
  const logRef = useRef(null);
  useEffect(() => {
    if (logRef.current && latestLog) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [latestLog]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="agent-logs-modal">
      <div className="bg-[var(--bg-panel)] border border-emerald-500/30 rounded-lg max-w-5xl w-full max-h-[90vh] flex flex-col shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-[var(--bg-border)]">
          <div>
            <h2 className="text-base font-heading font-bold text-emerald-400 flex items-center gap-2">
              📋 Log Connector (nocagent.log)
            </h2>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono">
              {agent.hostname || agent.agent_id?.slice(0, 12)} · {clientName || agent.client_id?.slice(0, 8)} · v{agent.agent_version}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={onRefresh} disabled={loading}
              className="text-[10px] px-2 py-1 rounded bg-sky-500/10 text-sky-400 hover:bg-sky-500/20 border border-sky-500/20 disabled:opacity-30"
              data-testid="agent-logs-refresh">
              <ArrowClockwise size={11} className="inline mr-1" />
              {loading ? "Carico…" : "Ricarica"}
            </button>
            <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] p-1"
              data-testid="agent-logs-close">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden p-4 space-y-3 flex flex-col">
          {loading && (
            <div className="text-center py-8 text-[var(--text-muted)] text-xs">
              Recupero log dal PC client (timeout 20s)…
            </div>
          )}

          {!loading && data?.error && (
            <div className="p-3 rounded bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
              <p className="font-bold mb-1">Errore</p>
              <p className="whitespace-pre-wrap">{data.error}</p>
            </div>
          )}

          {!loading && !supported && (
            <div className="p-3 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
              <p className="font-bold mb-1">Comando non supportato</p>
              <p>L&apos;agent è troppo vecchio (richiede v4.13+). Aggiorna il connector e riprova.</p>
            </div>
          )}

          {!loading && supported && reply && (
            <>
              <div className="text-[10px] text-[var(--text-muted)] font-mono flex flex-wrap gap-x-4 gap-y-1 shrink-0">
                {logPath && <span>File: <span className="text-[var(--text-primary)] break-all">{logPath}</span></span>}
                {latestSize > 0 && <span>Size: <span className="text-[var(--text-primary)]">{(latestSize / 1024).toFixed(1)} KB</span></span>}
                {latestMtime && <span>Updated: <span className="text-[var(--text-primary)]">{latestMtime}</span></span>}
              </div>

              {!exists && (
                <div className="p-3 rounded bg-zinc-500/10 border border-zinc-500/30 text-zinc-400 text-xs">
                  File <span className="font-mono">{logPath || "nocagent.log"}</span> non trovato sul PC client.
                  Verifica che il servizio sia attivo e abbia scritto almeno una riga.
                </div>
              )}

              {latestLog && (
                <>
                  <div className="flex items-center justify-between shrink-0">
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      Ultime righe (tail di {(latestSize / 1024).toFixed(1)} KB)
                    </span>
                    <button onClick={copyLog}
                      className="text-[10px] text-sky-400 hover:underline"
                      data-testid="agent-logs-copy">
                      📋 copia tutto
                    </button>
                  </div>
                  <pre ref={logRef}
                    className="text-[10px] leading-snug font-mono bg-black/40 p-3 rounded border border-[var(--bg-border)] overflow-y-auto flex-1 whitespace-pre break-normal"
                    data-testid="agent-logs-content">
                    {latestLog}
                  </pre>
                </>
              )}

              {files.length > 1 && (
                <div className="shrink-0">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">
                    File ruotati ({files.length})
                  </p>
                  <div className="space-y-0.5 text-[10px] font-mono max-h-24 overflow-y-auto">
                    {files.map((f) => (
                      <div key={f.name} className="flex items-center gap-3 px-2 py-0.5 hover:bg-[var(--bg-card)]/50 rounded">
                        <span className="text-[var(--text-muted)] w-32 truncate">{f.mtime?.slice(0, 19).replace("T", " ")}</span>
                        <span className="text-amber-400 w-16 text-right">{(f.size / 1024).toFixed(1)} KB</span>
                        <span className="text-[var(--text-primary)] flex-1 truncate">{f.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-4 py-2.5 border-t border-[var(--bg-border)] text-[10px] text-[var(--text-muted)]">
          Path log: <span className="font-mono text-[var(--text-primary)]">{baseDir || "—"}</span>
          {" · "}I log sono leggibili SOLO dal Center: l&apos;accesso diretto dal PC è bloccato (profilo SYSTEM).
        </div>
      </div>
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
