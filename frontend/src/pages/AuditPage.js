import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { Eye, ShieldWarning, ArrowsClockwise, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { useSortableTable, SortableTh } from "@/utils/tableSort";

export default function AuditPage() {
  const navigate = useNavigate();
  const [data, setData] = useState({ items: [], totals: {} });
  const [blockedIps, setBlockedIps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [onlySecurity, setOnlySecurity] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        axios.get(`${API}/admin/audit/recent?days=${days}&only_security=${onlySecurity}`),
        axios.get(`${API}/admin/audit/blocked-ips`).catch(() => ({ data: { blocked_ips: [] } })),
      ]);
      setData(r1.data);
      setBlockedIps(r2.data.blocked_ips || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento audit");
    } finally {
      setLoading(false);
    }
  }, [days, onlySecurity]);

  useEffect(() => { reload(); }, [reload]);

  const unblockIp = async (ip) => {
    if (!window.confirm(`Sbloccare l'IP ${ip}?`)) return;
    try {
      await axios.post(`${API}/admin/audit/unblock-ip`, { ip_address: ip });
      toast.success(`IP ${ip} sbloccato`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore");
    }
  };

  // v3.8.31: hook ordinamento audit log — DEVE stare prima dell'early-return
  // per rispettare le rules-of-hooks. items sara' [] al primo render (loading),
  // ma la hook si ricalcola correttamente quando data si popola.
  const SEV_RANK = { critical: 3, warning: 2, info: 1 };
  const _items = data.items || [];
  const { sorted: sortedAudit, sortKey, sortDir, requestSort } = useSortableTable(
    _items, "timestamp", "desc",
    {
      persistKey: "audit-page",
      accessors: {
        timestamp: (it) => it?.timestamp ? Date.parse(it.timestamp) : 0,
        action: (it) => (it?.action || "").toLowerCase(),
        severity: (it) => SEV_RANK[it?.severity] || 0,
        user: (it) => (it?.user_email || it?.user_id || "").toLowerCase(),
        ip: (it) => {
          const ip = it?.ip_address || "";
          const p = ip.split(".").map(n => parseInt(n, 10));
          if (p.length === 4 && p.every(n => !isNaN(n))) return p[0]*16777216+p[1]*65536+p[2]*256+p[3];
          return ip.toLowerCase();
        },
        resource: (it) => `${it?.resource_type || ""}/${it?.resource_id || ""}`.toLowerCase(),
        success: (it) => (it?.success === false ? 0 : 1),
      },
    }
  );

  if (loading) return <div className="p-6 text-[var(--text-muted)] text-sm">Caricamento…</div>;

  const totals = data.totals || {};
  const items = _items;

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="audit-page">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm">←</button>
        <Eye size={20} className="text-cyan-400" />
        <h1 className="text-xl font-bold">Audit & Security Events</h1>
      </div>

      {/* Filtri */}
      <div className="flex items-center gap-3 flex-wrap text-[11px]">
        <span className="text-[var(--text-muted)]">Periodo:</span>
        {[1, 7, 30, 90].map(d => (
          <button key={d} onClick={() => setDays(d)}
            className={`px-2 py-0.5 rounded border text-[10px] ${days === d ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
            data-testid={`days-${d}`}>{d}gg</button>
        ))}
        <label className="flex items-center gap-1 cursor-pointer ml-3">
          <input type="checkbox" checked={onlySecurity} onChange={e => setOnlySecurity(e.target.checked)} data-testid="only-security" />
          <span className="text-[10px]">Solo eventi security</span>
        </label>
        <Button size="sm" onClick={reload} variant="outline" className="ml-auto h-7 text-[11px] gap-1">
          <ArrowsClockwise size={11} /> Aggiorna
        </Button>
      </div>

      {/* Stat boxes */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Stat label="Eventi totali" value={totals.total || 0} />
        <Stat label="Login falliti" value={totals.failed_logins || 0} color={(totals.failed_logins || 0) > 10 ? "#FF3B30" : "#34C759"} />
        <Stat label="IP unique" value={totals.unique_ips || 0} />
        <Stat label="Critical" value={totals.by_severity?.critical || 0} color="#FF3B30" />
        <Stat label="Warning" value={totals.by_severity?.warning || 0} color="#FFB400" />
      </div>

      {/* IP bloccati */}
      {blockedIps.length > 0 && (
        <div className="noc-panel p-3" data-testid="blocked-ips-section">
          <div className="flex items-center gap-2 mb-2">
            <ShieldWarning size={14} className="text-red-400" />
            <span className="text-xs font-bold">IP bloccati per brute-force ({blockedIps.length})</span>
          </div>
          <div className="space-y-1">
            {blockedIps.map(b => (
              <div key={b.ip_address} className="flex items-center gap-2 text-[11px] bg-[var(--bg-card)] rounded px-2 py-1">
                <span className="font-mono text-red-400">{b.ip_address}</span>
                <span className="text-[10px] text-[var(--text-muted)]">{b.reason}</span>
                <span className="text-[10px] text-[var(--text-muted)] ml-auto">unlock: {new Date(b.unlock_at).toLocaleString("it-IT")}</span>
                <Button size="sm" variant="outline" onClick={() => unblockIp(b.ip_address)} className="h-5 text-[9px] text-amber-400 border-amber-400/30" data-testid={`unblock-${b.ip_address}`}>
                  <Trash size={9} /> Sblocca
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top IPs */}
      {totals.top_ips?.length > 0 && (
        <div className="noc-panel p-3">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Top IP per accessi</p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {totals.top_ips.slice(0, 10).map((ip, i) => (
              <div key={i} className="rounded bg-[var(--bg-card)] border border-[var(--bg-border)] px-2 py-1.5">
                <p className="text-[10px] font-mono truncate" title={ip.ip}>{ip.ip}</p>
                <p className="text-sm font-bold font-mono">{ip.count}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <BreakdownCard title="Eventi per azione" data={totals.by_action} max={15} />
        <BreakdownCard title="Eventi per severity" data={totals.by_severity} colorMap={{ info: "#06B6D4", warning: "#FFB400", critical: "#FF3B30" }} />
      </div>

      {/* Lista eventi */}
      <div className="noc-panel overflow-x-auto">
        <table className="noc-table w-full text-[11px]" data-testid="audit-table">
          <thead><tr>
            <SortableTh field="timestamp" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Quando</SortableTh>
            <SortableTh field="action" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Azione</SortableTh>
            <SortableTh field="severity" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Severity</SortableTh>
            <SortableTh field="user" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Utente</SortableTh>
            <SortableTh field="ip" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>IP</SortableTh>
            <SortableTh field="resource" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Risorsa</SortableTh>
            <SortableTh field="success" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Esito</SortableTh>
          </tr></thead>
          <tbody>
            {sortedAudit.slice(0, 500).map((it, i) => {
              const sc = it.severity === "critical" ? "#FF3B30" : it.severity === "warning" ? "#FFB400" : "#06B6D4";
              const failed = it.success === false;
              return (
                <tr key={i} data-testid={`audit-row-${i}`}>
                  <td className="text-[10px] font-mono whitespace-nowrap">{it.timestamp ? new Date(it.timestamp).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}</td>
                  <td className="text-[10px] font-semibold">{it.action || "?"}</td>
                  <td><span className="text-[9px] font-bold" style={{ color: sc }}>{(it.severity || "info").toUpperCase()}</span></td>
                  <td className="text-[10px] text-[var(--text-muted)]">{it.user_email || it.user_id || "—"}</td>
                  <td className="text-[10px] font-mono">{it.ip_address || "—"}</td>
                  <td className="text-[10px] truncate max-w-[200px]" title={`${it.resource_type || ""}/${it.resource_id || ""}`}>{it.resource_type ? `${it.resource_type}/${(it.resource_id || "").slice(0, 30)}` : "—"}</td>
                  <td><span className="text-[10px] font-bold" style={{ color: failed ? "#FF3B30" : "#34C759" }}>{failed ? "FAIL" : "OK"}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {items.length === 0 && <p className="text-center py-4 text-[var(--text-muted)] text-[11px]">Nessun evento</p>}
        {items.length > 500 && <p className="text-[9px] text-[var(--text-muted)] text-center py-1">…limitato a 500 eventi visualizzati</p>}
      </div>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded bg-[var(--bg-card)] border border-[var(--bg-border)] px-2 py-1.5">
      <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
      <p className="text-base font-bold font-mono leading-none mt-0.5" style={{ color: color || "var(--text-primary)" }}>{value}</p>
    </div>
  );
}

function BreakdownCard({ title, data, max = 8, colorMap }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1]).slice(0, max);
  const total = entries.reduce((s, [, c]) => s + c, 0);
  if (total === 0) return null;
  return (
    <div className="noc-panel p-3">
      <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">{title}</p>
      <div className="space-y-1">
        {entries.map(([k, v]) => {
          const pct = (v / total) * 100;
          const col = colorMap?.[k] || "#06B6D4";
          return (
            <div key={k} className="text-[10px]">
              <div className="flex justify-between">
                <span className="font-mono truncate max-w-[200px]" title={k}>{k}</span>
                <span className="font-bold">{v}</span>
              </div>
              <div className="h-1 bg-[var(--bg-card)] rounded overflow-hidden">
                <div className="h-full" style={{ width: `${pct}%`, background: col }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
