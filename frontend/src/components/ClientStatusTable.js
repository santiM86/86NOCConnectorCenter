import React, { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Wifi, Server, HardDrive, Bell, Radio } from "lucide-react";

const HEALTH = {
  critical: { color: "#FF3B30", label: "CRITICO" },
  warning: { color: "#FF9500", label: "ATTENZIONE" },
  attention: { color: "#FFCC00", label: "INFO" },
  ok: { color: "#34C759", label: "OK" },
};
const WAN_LABELS = {
  ok: "OK", isp_down: "ISP DOWN", firewall_down: "FW DOWN", router_down: "ROUTER DOWN",
  firewall_degraded: "DEGRADATA", router_degraded: "DEGRADATA", degraded: "PARZIALE",
  offline: "OFFLINE", pending: "…", not_configured: "N/C", unknown: "—",
};
const wanColor = (s) => (s === "ok" ? "#34C759" : ["pending", "not_configured", "unknown"].includes(s) ? "#6b7280" : s?.includes("degr") || s === "degraded" ? "#FF9500" : "#FF3B30");
const SEV = { critical: "#FF3B30", high: "#FF9500", medium: "#FFCC00", low: "#8b9bb0" };

function Cell({ children, className = "", testid }) {
  return <td className={`px-3 py-2 text-xs whitespace-nowrap ${className}`} data-testid={testid}>{children}</td>;
}

function Pill({ color, children, testid }) {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-bold"
      style={{ color, background: `${color}18`, border: `1px solid ${color}40` }} data-testid={testid}>{children}</span>
  );
}

/* Riga cliente: SOLO stato attuale (vitali offline, WAN, backup, alert attivi). */
function ClientRow({ c, navigate }) {
  const [open, setOpen] = useState(false);
  const h = HEALTH[c.health] || HEALTH.ok;
  const d = c.devices || {};
  const vOff = d.vital_offline || 0;
  const vTot = d.vital_total || 0;
  const bk = c.backup || {};
  const bkBad = (bk.error || 0) + (bk.failed || 0);
  const al = c.alerts || {};
  const critHigh = (al.critical || 0) + (al.high || 0);
  const det = c.detail || {};
  const vitalsDown = (det.vital_list || []).filter(v => v.status === "offline");
  const wanBad = (det.wan_targets || []).filter(w => !["online", "filtered"].includes(w.status));
  const activeAlerts = (det.recent_alerts || []).filter(a => !a.status || a.status === "active");
  const hasDetail = vitalsDown.length + wanBad.length + activeAlerts.length > 0;

  return (
    <>
      <tr className={`border-b border-[var(--bg-border)]/60 hover:bg-white/[0.02] transition-colors ${hasDetail ? "cursor-pointer" : ""}`}
        onClick={() => hasDetail && setOpen(o => !o)} data-testid={`client-row-${c.id}`}>
        <Cell className="w-6 pl-3">
          {hasDetail ? (open ? <ChevronDown size={13} className="text-[var(--text-muted)]" /> : <ChevronRight size={13} className="text-[var(--text-muted)]" />) : <span className="inline-block w-[13px]" />}
        </Cell>
        <Cell>
          <span className="inline-flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: h.color, boxShadow: c.health === "critical" ? `0 0 8px ${h.color}` : "none" }} />
            <span className="font-semibold text-[var(--text-primary)] text-sm" data-testid="client-name">{c.name}</span>
            {c.connector_online === false && <Pill color="#FF3B30">NO SONDA</Pill>}
          </span>
        </Cell>
        <Cell testid="client-vitals">
          <span className="inline-flex items-center gap-1.5"><Server size={12} className="text-[var(--text-muted)]" />
            {vTot === 0 ? <span className="text-[var(--text-muted)]">—</span>
              : vOff > 0 ? <Pill color="#FF3B30">{vOff} OFFLINE / {vTot}</Pill>
              : (d.vital_stale || 0) > 0 ? <Pill color="#FF9500">{d.vital_stale} STALE / {vTot}</Pill>
              : <span className="text-emerald-400 font-mono">{d.vital_online ?? vTot}/{vTot} online</span>}
          </span>
        </Cell>
        <Cell testid="client-wan">
          <span className="inline-flex items-center gap-1.5"><Wifi size={12} className="text-[var(--text-muted)]" />
            <Pill color={wanColor(c.wan?.status)}>{WAN_LABELS[c.wan?.status] || c.wan?.status}</Pill>
            {c.wan?.latency_ms != null && c.wan.status === "ok" && <span className="text-[10px] text-[var(--text-muted)] font-mono">{Math.round(c.wan.latency_ms)}ms</span>}
          </span>
        </Cell>
        <Cell testid="client-backup">
          <span className="inline-flex items-center gap-1.5"><HardDrive size={12} className="text-[var(--text-muted)]" />
            {!bk.total ? <span className="text-[var(--text-muted)]">—</span>
              : bkBad > 0 ? <Pill color="#FF3B30">{bkBad} KO / {bk.total}</Pill>
              : (bk.warning || 0) + (bk.stale || 0) > 0 ? <Pill color="#FF9500">{(bk.warning || 0) + (bk.stale || 0)} WARN / {bk.total}</Pill>
              : <span className="text-emerald-400 font-mono">{bk.ok}/{bk.total} ok</span>}
          </span>
        </Cell>
        <Cell testid="client-alerts">
          <span className="inline-flex items-center gap-1.5"><Bell size={12} className="text-[var(--text-muted)]" />
            {critHigh > 0 ? <Pill color={al.critical > 0 ? "#FF3B30" : "#FF9500"}>{critHigh} ATTIVI</Pill>
              : (al.total || 0) > 0 ? <span className="text-[var(--text-muted)] font-mono">{al.total} minori</span>
              : <span className="text-emerald-400 font-mono">0</span>}
          </span>
        </Cell>
        <Cell className="text-right pr-3">
          <button onClick={(e) => { e.stopPropagation(); navigate(`/client/${c.id}`); }}
            className="inline-flex items-center gap-1 text-[10px] font-semibold text-indigo-400 hover:text-indigo-300"
            data-testid={`open-client-${c.id}`}>Apri <ExternalLink size={11} /></button>
        </Cell>
      </tr>
      {open && hasDetail && (
        <tr className="border-b border-[var(--bg-border)]/60 bg-black/20" data-testid={`client-detail-${c.id}`}>
          <td />
          <td colSpan={6} className="px-3 py-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              {vitalsDown.length > 0 && (
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-red-400 mb-1.5">Vitali offline ({vitalsDown.length})</p>
                  {vitalsDown.map((v, i) => (
                    <div key={i} className="flex justify-between gap-2 py-0.5" data-testid="detail-vital-offline">
                      <span className="text-[var(--text-primary)] truncate">{v.name || v.ip}</span>
                      <span className="font-mono text-[var(--text-muted)]">{v.ip}</span>
                    </div>
                  ))}
                </div>
              )}
              {wanBad.length > 0 && (
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-orange-400 mb-1.5">WAN con problemi</p>
                  {wanBad.map((w, i) => (
                    <div key={i} className="flex justify-between gap-2 py-0.5" data-testid="detail-wan-bad">
                      <span className="truncate">{w.label}</span>
                      <Pill color={wanColor(w.status === "offline" ? "offline" : "degraded")}>{(w.status || "").toUpperCase()}</Pill>
                    </div>
                  ))}
                </div>
              )}
              {activeAlerts.length > 0 && (
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-[var(--text-muted)] mb-1.5">Allarmi attivi</p>
                  {activeAlerts.slice(0, 6).map((a, i) => (
                    <div key={i} className="flex items-center gap-2 py-0.5" data-testid="detail-alert">
                      <span className="w-1.5 h-1.5 rounded-full flex-none" style={{ background: SEV[a.severity] || SEV.low }} />
                      <span className="truncate text-[var(--text-primary)]">{a.title}</span>
                    </div>
                  ))}
                  {activeAlerts.length > 6 && <p className="text-[10px] text-[var(--text-muted)] mt-1">+{activeAlerts.length - 6} altri</p>}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export const ClientStatusTable = ({ clients, navigate }) => (
  <div className="noc-panel overflow-hidden" data-testid="client-status-table">
    <table className="w-full">
      <thead>
        <tr className="text-[9px] font-bold uppercase tracking-[0.15em] text-[var(--text-muted)] border-b border-[var(--bg-border)]">
          <th className="w-6" />
          <th className="text-left px-3 py-2">Cliente</th>
          <th className="text-left px-3 py-2">Vitali</th>
          <th className="text-left px-3 py-2">WAN</th>
          <th className="text-left px-3 py-2">Backup</th>
          <th className="text-left px-3 py-2">Alert</th>
          <th className="text-right px-3 py-2"><Radio size={11} className="inline" /></th>
        </tr>
      </thead>
      <tbody>
        {clients.map(c => <ClientRow key={c.id} c={c} navigate={navigate} />)}
      </tbody>
    </table>
  </div>
);
