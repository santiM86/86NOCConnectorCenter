/**
 * BridgeHealthWidget — v2026-02-28
 *
 * Mostra in tempo reale lo stato dei bridge SNMP/ping/discovery di ogni
 * agent v4 di un cliente, leggendo dall'endpoint admin
 * `GET /api/agents/diagnostics?client_id=<id>`.
 *
 * Risponde alla domanda "perche' i device sono obsoleti?" con dati
 * deterministici invece di guesswork:
 *  - live + connected_db        → agent vivo in registry e in DB
 *  - last_heartbeat_at <2min    → connessione attiva
 *  - bridge_counters.snmp_poll  → SNMP davvero in funzione (cresce)
 *  - poller_config.snmp_targets → numero target che agent dovrebbe pollare
 *
 * Refresh automatico ogni 15s. UI compatta che si autonasconde se non ci
 * sono agent (cliente senza connector v4 attivo).
 */
import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { ArrowsClockwise, WifiSlash, PlugsConnected, Warning, CheckCircle, Pulse } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;
const REFRESH_INTERVAL_MS = 15000;

/** Formatta un timestamp ISO in "Xs/Xm/Xh fa". Null/missing → "—". */
function relativeTime(iso) {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (!ts || isNaN(ts)) return "—";
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return `${diffSec}s fa`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m fa`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h fa`;
  return `${Math.floor(diffSec / 86400)}g fa`;
}

/** Severita' agent. Restituisce {color, label, icon}. */
function severityOf(a) {
  if (!a.live) return { color: "#FF3B30", label: "OFFLINE", icon: WifiSlash };
  // live=true: controlla freshness dell'attivita' SNMP
  const lastBridge = a.bridge_last_event_at || a.last_snmp_poll_received_at
                  || a.last_ping_poll_received_at || a.last_heartbeat_at;
  const ageSec = lastBridge ? Math.floor((Date.now() - Date.parse(lastBridge)) / 1000) : Infinity;
  const hasSnmpTargets = (a.poller_config?.snmp_targets || 0) > 0;
  if (ageSec > 600) return { color: "#FF3B30", label: "STALE", icon: Warning };
  if (!hasSnmpTargets) return { color: "#FFCC00", label: "NO TARGETS", icon: Warning };
  if (ageSec > 180) return { color: "#FFCC00", label: "RALLENTATO", icon: Pulse };
  return { color: "#34C759", label: "LIVE", icon: CheckCircle };
}

export default function BridgeHealthWidget({ clientId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0); // forza re-render per "Xs fa"

  const fetchData = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.get(
        `${API}/api/agents/diagnostics?client_id=${encodeURIComponent(clientId)}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setData(res.data);
      setErr(null);
    } catch (e) {
      setErr(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Refresh periodico
  useEffect(() => {
    const id = setInterval(() => fetchData(), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchData]);

  // Re-render ogni 5s per aggiornare i "Xs fa" senza rifare la fetch
  useEffect(() => {
    const id = setInterval(() => setRefreshTick(t => t + 1), 5000);
    return () => clearInterval(id);
  }, []);

  // Hide se cliente non ha agent
  if (!data || (!loading && (data.agents || []).length === 0)) return null;

  const agents = data.agents || [];
  const totalLive = data.live_count || 0;
  const totalCount = data.total_count || 0;
  // Sintesi globale: peggior severita' dei live agent
  const liveAgents = agents.filter(a => a.live);
  const worstSeverity = liveAgents.length === 0
    ? { color: "#FF3B30", label: "NESSUN AGENT" }
    : liveAgents.map(severityOf)
        .reduce((acc, s) => {
          const order = { "#FF3B30": 3, "#FFCC00": 2, "#34C759": 1 };
          return (order[s.color] || 0) > (order[acc.color] || 0) ? s : acc;
        }, { color: "#34C759", label: "LIVE" });

  return (
    <div className="noc-panel p-4" data-testid="bridge-health-widget" data-tick={refreshTick}>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <PlugsConnected size={14} weight="bold" style={{ color: worstSeverity.color }} />
          <h3 className="text-[10px] font-bold uppercase tracking-[0.15em]"
              style={{ color: worstSeverity.color }}>
            Bridge Health — {totalLive}/{totalCount} agent live · {worstSeverity.label}
          </h3>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-[9px] px-1.5 py-1 rounded border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-cyan-300 hover:border-cyan-500/30 transition-colors disabled:opacity-50"
          title="Aggiorna manualmente (auto-refresh 15s)"
          data-testid="bridge-health-refresh-btn"
        >
          <ArrowsClockwise size={11} weight="bold" className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {err && (
        <div className="text-[10px] text-red-400 mb-2">Errore: {err}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {agents.map(a => {
          const sev = severityOf(a);
          const SevIcon = sev.icon;
          const snmpTargets = a.poller_config?.snmp_targets || 0;
          const pingTargets = a.poller_config?.ping_targets || 0;
          const snmpCount = a.bridge_counters?.snmp_poll || 0;
          const pingCount = a.bridge_counters?.ping_poll || 0;
          const discoveryCount = a.bridge_counters?.discovery_batch || 0;
          return (
            <div
              key={a.agent_id}
              className="rounded border p-2"
              style={{ borderColor: `${sev.color}33`, background: `${sev.color}08` }}
              data-testid={`bridge-agent-${a.agent_id}`}
            >
              <div className="flex items-center gap-1.5 mb-1.5">
                <SevIcon size={11} weight="bold" style={{ color: sev.color }} />
                <span className="text-[10px] font-bold text-[var(--text-primary)] truncate flex-1">
                  {a.hostname || a.agent_id.slice(0, 8)}
                </span>
                <span className="text-[8px] px-1 py-0.5 rounded font-bold uppercase"
                      style={{ color: sev.color, background: `${sev.color}18` }}>
                  {a.role || "?"} · {sev.label}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1 text-[9px]">
                <div className="text-center">
                  <p className="text-[var(--text-muted)] uppercase tracking-wider text-[7px]">SNMP</p>
                  <p className="font-mono font-bold" style={{ color: snmpCount > 0 ? "#34C759" : "#64748B" }}>
                    {snmpCount}
                  </p>
                  <p className="text-[7px] text-[var(--text-muted)]">{relativeTime(a.last_snmp_poll_received_at)}</p>
                  <p className="text-[7px] text-[var(--text-muted)]">tgt: {snmpTargets}</p>
                </div>
                <div className="text-center border-x border-[var(--bg-border)]">
                  <p className="text-[var(--text-muted)] uppercase tracking-wider text-[7px]">PING</p>
                  <p className="font-mono font-bold" style={{ color: pingCount > 0 ? "#34C759" : "#64748B" }}>
                    {pingCount}
                  </p>
                  <p className="text-[7px] text-[var(--text-muted)]">{relativeTime(a.last_ping_poll_received_at)}</p>
                  <p className="text-[7px] text-[var(--text-muted)]">tgt: {pingTargets}</p>
                </div>
                <div className="text-center">
                  <p className="text-[var(--text-muted)] uppercase tracking-wider text-[7px]">DISCOVERY</p>
                  <p className="font-mono font-bold" style={{ color: discoveryCount > 0 ? "#34C759" : "#64748B" }}>
                    {discoveryCount}
                  </p>
                  <p className="text-[7px] text-[var(--text-muted)]">{relativeTime(a.last_discovery_received_at)}</p>
                  <p className="text-[7px] text-[var(--text-muted)]">batch:{a.last_discovery_batch_size || 0}</p>
                </div>
              </div>
              <div className="flex items-center justify-between mt-1.5 pt-1.5 border-t border-[var(--bg-border)] text-[8px] text-[var(--text-muted)]">
                <span title="IP rilevato dall'agent (subnet-aware dispatch)">
                  IP: <span className="font-mono">{a.last_ip || "—"}</span>
                </span>
                <span>HB: {relativeTime(a.last_heartbeat_at)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
