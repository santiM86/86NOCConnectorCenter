import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Heartbeat, Shield, WifiHigh, WifiSlash, CheckCircle, XCircle, Warning, Cloud, HardDrives, ArrowClockwise } from "@phosphor-icons/react";

const STATUS_COLORS = {
  ok: { bg: "bg-emerald-500/15", border: "border-emerald-500/40", text: "text-emerald-400", label: "OK" },
  degraded: { bg: "bg-amber-500/15", border: "border-amber-500/40", text: "text-amber-400", label: "DEGRADED" },
  stale: { bg: "bg-amber-500/15", border: "border-amber-500/40", text: "text-amber-400", label: "STALE" },
  down: { bg: "bg-rose-500/15", border: "border-rose-500/40", text: "text-rose-400", label: "DOWN" },
  disabled: { bg: "bg-white/5", border: "border-white/10", text: "text-white/40", label: "N/A" },
  unknown: { bg: "bg-white/5", border: "border-white/10", text: "text-white/50", label: "?" },
  n_a: { bg: "bg-white/5", border: "border-white/10", text: "text-white/40", label: "N/A" },
};

const OVERALL_COLORS = {
  both_ok: { bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-400", label: "ENTRAMBI OK" },
  direct_only: { bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-400", label: "SOLO DIRETTO" },
  connector_only: { bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-400", label: "SOLO CONNECTOR" },
  both_down: { bg: "bg-rose-500/10", border: "border-rose-500/40", text: "text-rose-400", label: "BOTH DOWN" },
  n_a: { bg: "bg-white/5", border: "border-white/10", text: "text-white/50", label: "N/D" },
};

export default function ChannelHealthPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = async () => {
    try {
      const res = await axios.get(`${API}/redfish/channel-health-matrix`);
      setData(res.data);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!autoRefresh) return;
    const i = setInterval(load, 30000);
    return () => clearInterval(i);
  }, [autoRefresh]);

  if (loading) return <div className="p-6 text-white/50">Caricamento…</div>;
  if (!data) return <div className="p-6 text-rose-400">Errore caricamento</div>;

  const stats = data.stats || {};

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="channel-health-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Heartbeat size={24} className="text-cyan-400" /> Channel Health Matrix
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Stato dual-path iLO: Direct (cloud → WAN) + Connector (LAN). Refresh 30s.</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-[12px] text-white/70">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <button onClick={load} className="h-8 px-3 rounded bg-white/5 border border-white/10 hover:bg-white/10 text-[12px] flex items-center gap-1" data-testid="refresh-btn">
            <ArrowClockwise size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <SummaryCard label="Totali" value={stats.total || 0} icon={HardDrives} color="text-white" />
        <SummaryCard label="Entrambi OK" value={stats.both_ok || 0} icon={CheckCircle} color="text-emerald-400" />
        <SummaryCard label="Solo Direct" value={stats.direct_only || 0} icon={Cloud} color="text-amber-400" />
        <SummaryCard label="Solo Connector" value={stats.connector_only || 0} icon={WifiHigh} color="text-amber-400" />
        <SummaryCard label="BOTH DOWN" value={stats.both_down || 0} icon={XCircle} color="text-rose-400" pulse={(stats.both_down || 0) > 0} />
      </div>

      {/* Matrix */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="text-white/50 text-xs uppercase border-b border-white/10">
            <tr>
              <th className="text-left py-2 px-2">Device</th>
              <th className="text-left py-2 px-2">Cliente</th>
              <th className="text-center py-2 px-2"><Cloud size={14} className="inline mr-1" /> Direct (WAN)</th>
              <th className="text-center py-2 px-2"><WifiHigh size={14} className="inline mr-1" /> Connector (LAN)</th>
              <th className="text-center py-2 px-2">Overall</th>
              <th className="text-left py-2 px-2">Dettagli</th>
            </tr>
          </thead>
          <tbody>
            {(data.items || []).map(it => {
              const dc = STATUS_COLORS[it.direct.status] || STATUS_COLORS.unknown;
              const cc = STATUS_COLORS[it.connector.status] || STATUS_COLORS.unknown;
              const oc = OVERALL_COLORS[it.overall] || OVERALL_COLORS.n_a;
              const critical = it.overall === "both_down";
              return (
                <tr key={it.device_ip} className={`border-b border-white/5 hover:bg-white/[0.02] ${critical ? "bg-rose-500/5" : ""}`} data-testid={`row-${it.device_ip}`}>
                  <td className="py-2 px-2">
                    <div className="text-white/90 font-medium text-[13px]">{it.device_name}</div>
                    <div className="text-white/40 text-[10px] font-mono">{it.device_ip}</div>
                  </td>
                  <td className="py-2 px-2 text-white/70 text-[12px]">{it.client_name || <span className="text-white/30">—</span>}</td>
                  <td className="py-2 px-2 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide ${dc.bg} ${dc.border} ${dc.text}`}>
                      {dc.label}
                    </span>
                    {it.direct.consecutive_failures > 0 && (
                      <div className="text-[9px] text-rose-400 mt-0.5">{it.direct.consecutive_failures} fail consec.</div>
                    )}
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide ${cc.bg} ${cc.border} ${cc.text}`}>
                      {cc.label}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide ${oc.bg} ${oc.border} ${oc.text} ${critical ? "animate-pulse" : ""}`}>
                      {critical && <Warning size={10} className="inline mr-1" />}
                      {oc.label}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-[11px] text-white/60">
                    {it.direct.last_error && (
                      <div className="truncate max-w-xs" title={it.direct.last_error}>
                        <span className="text-rose-400/70">err:</span> {it.direct.last_error.slice(0, 60)}...
                      </div>
                    )}
                    {it.connector.connector_host && (
                      <div className="text-white/40 text-[10px]">
                        host: <span className="font-mono">{it.connector.connector_host}</span>
                      </div>
                    )}
                    {it.direct.last_success && (
                      <div className="text-white/40 text-[10px]">
                        last OK: {new Date(it.direct.last_success).toLocaleString("it-IT")}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {(data.items || []).length === 0 && (
              <tr><td colSpan={6} className="py-8 text-center text-white/40">Nessun iLO configurato nel Vault.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-[11px] text-white/40">
        Generato: {new Date(data.generated_at).toLocaleString("it-IT")} · Soglie: Direct OK se success &lt;3 min; Connector OK se heartbeat &lt;5 min.
      </div>
    </div>
  );
}

function SummaryCard({ label, value, icon: Icon, color, pulse }) {
  return (
    <div className={`bg-white/[0.03] border border-white/10 rounded-lg p-3 ${pulse ? "animate-pulse border-rose-500/50" : ""}`}>
      <div className="flex items-center gap-2 text-[11px] text-white/50 uppercase tracking-wide">
        <Icon size={14} /> {label}
      </div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
    </div>
  );
}
