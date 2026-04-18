import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  Warning,
  CheckCircle,
  HardDrives,
  Lightning,
  ArrowRight,
  CaretRight,
  CaretDown,
  Globe,
  WifiHigh,
  WifiSlash,
  ShieldCheck,
  Database,
  Printer,
  PlugsConnected,
  MagnifyingGlass,
  ArrowClockwise,
  Funnel,
  Clock,
  XCircle,
  CircleNotch,
} from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import MobileDashboard from "@/components/MobileDashboard";

const HEALTH_CONFIG = {
  critical: { color: "#FF3B30", bg: "#FF3B3012", border: "#FF3B3030", label: "CRITICO" },
  warning:  { color: "#FF9500", bg: "#FF950012", border: "#FF950030", label: "ATTENZIONE" },
  attention:{ color: "#FFCC00", bg: "#FFCC0012", border: "#FFCC0030", label: "INFO" },
  ok:       { color: "#34C759", bg: "#34C75912", border: "#34C75930", label: "OK" },
};

const WAN_LABELS = {
  ok: "OK", isp_down: "ISP DOWN", firewall_down: "FW DOWN", router_down: "RT DOWN",
  firewall_degraded: "FW DEGR.", router_degraded: "RT DEGR.", degraded: "PARZIALE",
  offline: "OFFLINE", pending: "...", not_configured: "N/C", unknown: "---",
};

const WAN_COLORS = {
  ok: "#34C759", isp_down: "#FF3B30", firewall_down: "#FF3B30", router_down: "#FF3B30",
  firewall_degraded: "#FF9500", router_degraded: "#FF9500", degraded: "#FF9500",
  offline: "#FF3B30", pending: "#555", not_configured: "#555", unknown: "#555",
};

export default function DashboardPage() {
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches);
  const [overview, setOverview] = useState({ clients: [], global: {} });
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [liveStream, setLiveStream] = useState([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all, problems, ok
  const [loading, setLoading] = useState(true);
  const wsRef = useRef(null);
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    try {
      const overviewRes = await axios.get(`${API}/overview/clients`);
      setOverview(overviewRes.data);
    } catch (e) { console.error("overview error:", e); }
    try {
      const alertsRes = await axios.get(`${API}/alerts?limit=20&status=active`);
      const alerts = alertsRes.data || [];
      setRecentAlerts(alerts);
      setLiveStream(alerts.slice(0, 30).map(a => ({
        id: a.id, time: new Date(a.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        ip: a.ip_address, msg: a.message?.substring(0, 60), severity: a.severity, device: a.device_name
      })));
    } catch (e) { console.error("alerts error:", e); }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    connectWebSocket();
    const onResize = () => setIsMobile(window.matchMedia("(max-width: 767px)").matches);
    window.addEventListener("resize", onResize);
    return () => { clearInterval(interval); if (wsRef.current) wsRef.current.close(); window.removeEventListener("resize", onResize); };
  }, [fetchData]);

  const connectWebSocket = () => {
    const wsUrl = process.env.REACT_APP_BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://");
    const wsToken = localStorage.getItem("noc_token");
    wsRef.current = new WebSocket(wsToken ? `${wsUrl}/ws/alerts?token=${wsToken}` : `${wsUrl}/ws/alerts`);
    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "new_alert") {
        setRecentAlerts(prev => [data.alert, ...prev.slice(0, 19)]);
        setLiveStream(prev => [{
          id: data.alert.id, time: new Date(data.alert.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
          ip: data.alert.ip_address, msg: data.alert.message?.substring(0, 60), severity: data.alert.severity, device: data.alert.device_name
        }, ...prev.slice(0, 29)]);
        if (data.alert.severity === "critical") toast.error(`CRITICO: ${data.alert.title}`, { description: `${data.alert.device_name} - ${data.alert.client_name}` });
        fetchData();
      }
    };
    wsRef.current.onclose = () => { setTimeout(connectWebSocket, 5000); };
  };

  const handleAck = async (alertId) => {
    try {
      await axios.patch(`${API}/alerts/${alertId}`, { status: "acknowledged" });
      setRecentAlerts(prev => prev.filter(a => a.id !== alertId));
      fetchData();
      toast.success("Alert confermato");
    } catch { toast.error("Errore"); }
  };

  const getSevColor = (s) => ({ critical: "var(--critical)", high: "var(--high)", medium: "var(--medium)", low: "var(--low)" }[s] || "var(--text-muted)");

  if (isMobile) return <MobileDashboard />;

  const g = overview.global || {};
  const clients = overview.clients || [];

  // Filter & search
  const filtered = clients.filter(c => {
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "problems" && c.health === "ok") return false;
    if (filter === "ok" && c.health !== "ok") return false;
    return true;
  });

  const urgentCount = g.critical_alerts || 0;

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="dashboard-page">
      {/* Top Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Panoramica</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio in tempo reale — {clients.length} clienti</p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={fetchData} className="p-1.5 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all" title="Aggiorna">
            <ArrowClockwise size={16} />
          </button>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--low)]/10 border border-[var(--low)]/20">
            <span className="live-dot" style={{ width: 6, height: 6 }}></span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ok)]">Live</span>
          </div>
        </div>
      </div>

      {/* Urgent Banner */}
      {urgentCount > 0 && (
        <div className="flex items-center justify-between p-3 rounded-lg border cursor-pointer hover:opacity-90 transition-opacity"
          style={{ background: "var(--critical-bg)", borderColor: "var(--critical-border)" }}
          onClick={() => navigate("/alerts?severity=critical")} data-testid="urgent-banner">
          <div className="flex items-center gap-3">
            <Lightning size={20} weight="fill" className="text-[var(--critical)]" />
            <div>
              <p className="text-[var(--critical)] font-heading font-bold text-sm">{urgentCount} alert critici richiedono attenzione</p>
            </div>
          </div>
          <ArrowRight size={18} className="text-[var(--critical)]" />
        </div>
      )}

      {/* Global KPI Bar */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <KpiCard label="Clienti" value={g.total_clients || 0} sub={`${g.clients_ok || 0} OK`} color="#34C759" testId="kpi-clients" />
        <KpiCard label="Problemi" value={(g.clients_warning || 0) + (g.clients_critical || 0)} sub={`${g.clients_critical || 0} critici`} color={g.clients_critical > 0 ? "#FF3B30" : "#FF9500"} testId="kpi-problems" />
        <KpiCard label="Alert Attivi" value={g.total_alerts || 0} sub={`${g.critical_alerts || 0} critici`} color={g.critical_alerts > 0 ? "#FF3B30" : "#34C759"} testId="kpi-alerts" />
        <KpiCard label="Dispositivi" value={g.total_devices || 0} sub={`${g.devices_online || 0} online`} color="#6366F1" testId="kpi-devices" />
        <div className="noc-panel p-3 lg:col-span-2">
          <div className="flex items-center gap-2">
            <MagnifyingGlass size={14} className="text-[var(--text-muted)]" />
            <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cerca cliente..."
              className="h-6 text-xs bg-transparent border-none shadow-none focus-visible:ring-0 text-[var(--text-primary)] placeholder:text-[var(--text-muted)]" data-testid="search-client" />
          </div>
          <div className="flex gap-1 mt-2">
            {[["all", "Tutti"], ["problems", "Problemi"], ["ok", "OK"]].map(([v, l]) => (
              <button key={v} onClick={() => setFilter(v)}
                className={`text-[9px] px-2 py-0.5 rounded-md font-semibold transition-all ${filter === v ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
                data-testid={`filter-${v}`}>{l}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Client Grid */}
      <div className={`grid gap-3 ${filtered.length > 20 ? "grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5" : filtered.length > 8 ? "grid-cols-2 md:grid-cols-3 lg:grid-cols-4" : "grid-cols-1 md:grid-cols-2 lg:grid-cols-3"}`}>
        {filtered.map(c => <ClientCard key={c.id} client={c} navigate={navigate} />)}
      </div>

      {filtered.length === 0 && !loading && (
        <div className="text-center py-12 text-[var(--text-muted)]">
          <Globe size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">{search ? "Nessun cliente trovato" : "Nessun cliente configurato"}</p>
        </div>
      )}

      {/* Live Stream + Recent Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
        <div className="lg:col-span-2 noc-panel p-4">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">Live Stream</h3>
          <ScrollArea className="h-48">
            <div className="syslog-stream h-full" style={{ border: "none", background: "transparent" }}>
              {liveStream.length === 0 ? (
                <p className="text-[var(--text-muted)] text-center py-6 text-xs">In attesa di eventi...</p>
              ) : liveStream.map((e, i) => (
                <div key={e.id + i} className="syslog-line flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: getSevColor(e.severity) }}></span>
                  <span className="syslog-timestamp">{e.time}</span>
                  <span className="text-[var(--text-secondary)] truncate">{e.device || e.ip}</span>
                  <span className="text-[var(--text-muted)] truncate">{e.msg}</span>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>

        <div className="lg:col-span-3 noc-panel">
          <div className="p-3 border-b border-[var(--bg-border)] flex items-center justify-between">
            <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest">Alert Attivi</h3>
            <Button variant="ghost" size="sm" onClick={() => navigate("/alerts")}
              className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-md text-xs h-7 gap-1" data-testid="view-all-alerts-btn">
              Tutti <CaretRight size={12} />
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="alert-table" data-testid="recent-alerts-table">
              <thead>
                <tr><th>Sev.</th><th>Titolo</th><th>Dispositivo</th><th>Cliente</th><th>Ora</th><th></th></tr>
              </thead>
              <tbody>
                {recentAlerts.length === 0 ? (
                  <tr><td colSpan={6} className="text-center text-[var(--text-muted)] py-6 text-xs">Nessun alert attivo</td></tr>
                ) : recentAlerts.slice(0, 6).map(alert => (
                  <tr key={alert.id} className={alert.severity === "critical" ? "pulse-critical" : ""} data-testid={`alert-row-${alert.severity}`}>
                    <td><span className={`severity-badge severity-${alert.severity}`}>{alert.severity === "critical" ? "CRIT" : alert.severity === "high" ? "HIGH" : alert.severity === "medium" ? "MED" : "LOW"}</span></td>
                    <td className="cursor-pointer hover:text-[var(--text-primary)] transition-colors text-[var(--text-secondary)]" onClick={() => navigate(`/alerts/${alert.id}`)}>{alert.title}</td>
                    <td className="font-mono text-[var(--text-muted)] text-xs">{alert.device_name}</td>
                    <td className="text-[var(--text-secondary)] text-xs">{alert.client_name}</td>
                    <td className="font-mono text-[var(--text-muted)] text-[11px]">{new Date(alert.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</td>
                    <td><Button size="sm" variant="outline" onClick={() => handleAck(alert.id)}
                      className="rounded-md text-[10px] h-6 px-2 border-[var(--bg-border)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]" data-testid={`ack-btn-${alert.id}`}>ACK</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ==================== CLIENT CARD ==================== */
function ClientCard({ client: c, navigate }) {
  const [expanded, setExpanded] = useState(false);
  const h = HEALTH_CONFIG[c.health] || HEALTH_CONFIG.ok;
  const wanColor = WAN_COLORS[c.wan?.status] || "#555";
  const wanLabel = WAN_LABELS[c.wan?.status] || "---";
  const hasAlerts = c.alerts?.total > 0;
  const hasCritical = c.alerts?.critical > 0;
  const detail = c.detail || {};

  return (
    <div className="rounded-xl overflow-hidden border transition-all duration-200"
      style={{ borderColor: h.border, background: "var(--bg-panel)" }}
      data-testid={`client-card-${c.id}`}>

      {/* Header — always visible, clickable */}
      <div className="px-3.5 py-2.5 flex items-center justify-between cursor-pointer hover:bg-[var(--bg-hover)]/30 transition-colors"
        style={{ borderBottom: `2px solid ${h.color}20` }}
        onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: h.color, boxShadow: `0 0 8px ${h.color}50` }}></div>
          <h3 className="text-sm font-bold text-[var(--text-primary)] truncate">{c.name}</h3>
          {hasAlerts && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-md font-bold flex-shrink-0" style={{ color: hasCritical ? "#FF3B30" : "#FF9500", background: hasCritical ? "#FF3B3012" : "#FF950012" }}>
              {c.alerts.total}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={(e) => { e.stopPropagation(); navigate(`/client/${c.id}`); }} className="text-[9px] px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors font-bold" data-testid={`open-client-${c.id}`}>
            Apri
          </button>
          <CaretDown size={14} weight="bold" className={`text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`} />
        </div>
      </div>

      {/* Summary row — always visible with real data */}
      <div className="px-3.5 py-2 grid grid-cols-3 gap-x-3 gap-y-1.5">
        <SvcLine icon={Globe} label="WAN" value={wanLabel} color={wanColor} sub={c.wan?.latency_ms ? `${c.wan.latency_ms}ms` : null} />
        <SvcLine
          icon={HardDrives}
          label="Dispositivi"
          value={c.devices?.total > 0 ? `${c.devices.online}/${c.devices.total}` : "—"}
          color={
            c.devices?.offline > 0 ? "#FF3B30"
            : c.devices?.stale > 0 ? "#FF9500"
            : c.devices?.unknown > 0 ? "#FFCC00"
            : "#34C759"
          }
          sub={
            c.devices?.offline > 0 ? `${c.devices.offline} off`
            : c.devices?.stale > 0 ? `${c.devices.stale} stale`
            : c.devices?.unknown > 0 ? `${c.devices.unknown} non classif.`
            : null
          }
        />
        <SvcLine icon={PlugsConnected} label="Connettore" value={c.connector_online === true ? "ON" : c.connector_online === false ? "OFF" : "—"} color={c.connector_online ? "#34C759" : c.connector_online === false ? "#FF3B30" : "#555"} />
        <SvcLine icon={Database} label="Backup" value={c.backup?.total > 0 ? (c.backup.error > 0 ? `${c.backup.error} ERR` : "OK") : "—"} color={c.backup?.error > 0 ? "#FF3B30" : c.backup?.total > 0 ? "#34C759" : "#555"} />
        <SvcLine icon={Printer} label="Stampanti" value={c.printers?.total > 0 ? (c.printers.low_toner > 0 ? `${c.printers.low_toner} LOW` : "OK") : "—"} color={c.printers?.low_toner > 0 ? "#FF9500" : c.printers?.total > 0 ? "#34C759" : "#555"} />
        <SvcLine icon={WifiHigh} label="ISP" value={c.wan?.gateway === "online" ? "OK" : c.wan?.gateway === "offline" ? "DOWN" : "—"} color={c.wan?.gateway === "online" ? "#34C759" : c.wan?.gateway === "offline" ? "#FF3B30" : "#555"} />
      </div>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="border-t border-[var(--bg-border)]/50 px-3.5 py-3 space-y-3 bg-[var(--bg-card)]/30">

          {/* WAN Targets */}
          {detail.wan_targets?.length > 0 && (
            <div>
              <p className="text-[8px] font-bold uppercase tracking-[0.15em] text-indigo-400 mb-1.5">Monitoraggio WAN</p>
              <div className="space-y-1.5">
                {detail.wan_targets.map((w, i) => {
                  const wc = w.status === "online" ? "#34C759" : w.status === "offline" ? "#FF3B30" : w.status === "degraded" ? "#FF9500" : "#555";
                  return (
                    <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[10px]" style={{ borderColor: `${wc}25`, background: `${wc}06` }}>
                      {w.device_type === "firewall" ? <ShieldCheck size={13} weight="bold" style={{ color: wc }} /> : <HardDrives size={13} weight="bold" style={{ color: wc }} />}
                      <span className="font-bold text-[var(--text-primary)]">{w.label}</span>
                      <span className="text-[8px] px-1 py-0.5 rounded font-bold uppercase" style={{ color: wc, background: `${wc}15` }}>{w.status === "online" ? "ONLINE" : w.status === "offline" ? "OFFLINE" : w.status?.toUpperCase() || "?"}</span>
                      <span className="font-mono text-[var(--text-muted)]">{w.ip}</span>
                      {w.check_ping && <span className="text-[8px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-400 font-bold">ICMP</span>}
                      <span className="ml-auto font-mono font-bold" style={{ color: wc }}>{w.latency_ms != null ? `${w.latency_ms}ms` : "—"}</span>
                      {w.loss_pct != null && w.loss_pct > 0 && <span className="font-mono text-red-400">{w.loss_pct}%</span>}
                      {w.gateway_ok != null && (
                        <span className="text-[8px] px-1 py-0.5 rounded font-bold" style={{ color: w.gateway_ok ? "#34C759" : "#FF3B30", background: w.gateway_ok ? "#34C75910" : "#FF3B3010" }}>
                          GW {w.gateway_ok ? "OK" : "DOWN"} {w.gateway_latency != null && `${w.gateway_latency}ms`}
                        </span>
                      )}
                      {w.ports?.length > 0 && w.ports.map((p, j) => (
                        <span key={j} className="font-mono" style={{ color: p.open ? "#34C759" : "#FF3B30" }}>:{p.port} {p.open ? "OPEN" : "CLOSED"}</span>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Devices List */}
          {detail.devices_list?.length > 0 && (
            <div>
              <p className="text-[8px] font-bold uppercase tracking-[0.15em] text-cyan-400 mb-1.5">Dispositivi ({detail.devices_list.length})</p>
              <div className="grid grid-cols-1 gap-1">
                {detail.devices_list.map((d, i) => (
                  <div key={i} className="flex items-center gap-2 px-2 py-1 rounded text-[10px]">
                    <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: d.status === "online" ? "#34C759" : "#FF3B30" }}></div>
                    <span className="font-medium text-[var(--text-primary)]">{d.name}</span>
                    <span className="font-mono text-[var(--text-muted)]">{d.ip}</span>
                    {d.type && <span className="text-[8px] text-[var(--text-muted)] uppercase opacity-50">{d.type}</span>}
                    <span className="ml-auto text-[8px] font-bold uppercase" style={{ color: d.status === "online" ? "#34C759" : "#FF3B30" }}>{d.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recent Alerts */}
          {detail.recent_alerts?.length > 0 && (
            <div>
              <p className="text-[8px] font-bold uppercase tracking-[0.15em] text-amber-400 mb-1.5">Alert Attivi ({c.alerts?.total || 0})</p>
              <div className="space-y-1">
                {detail.recent_alerts.map((a, i) => {
                  const sc = a.severity === "critical" ? "#FF3B30" : a.severity === "high" ? "#FF9500" : a.severity === "medium" ? "#FFCC00" : "#888";
                  return (
                    <div key={i} className="flex items-center gap-2 px-2 py-1 rounded text-[10px]" style={{ background: `${sc}06` }}>
                      <span className="text-[8px] px-1 py-0.5 rounded font-bold uppercase" style={{ color: sc, background: `${sc}15` }}>{a.severity?.substring(0, 4)}</span>
                      <span className="text-[var(--text-primary)] truncate">{a.title}</span>
                      <span className="text-[var(--text-muted)] ml-auto flex-shrink-0">{a.device_name}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Quick actions */}
          <div className="flex gap-2 pt-1">
            <button onClick={() => navigate("/wan-monitor")} className="text-[9px] px-2 py-1 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors">Monitor WAN</button>
            <button onClick={() => navigate("/devices")} className="text-[9px] px-2 py-1 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 transition-colors">Dispositivi</button>
            <button onClick={() => navigate("/alerts")} className="text-[9px] px-2 py-1 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors">Alert</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ==================== SERVICE LINE ==================== */
function SvcLine({ icon: Icon, label, value, color, sub }) {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <Icon size={11} weight="bold" style={{ color, opacity: 0.7 }} className="flex-shrink-0" />
      <div className="min-w-0">
        <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest leading-none">{label}</p>
        <p className="text-[10px] font-bold font-mono leading-tight" style={{ color }}>
          {value}
          {sub && <span className="text-[8px] font-normal opacity-60 ml-0.5">{sub}</span>}
        </p>
      </div>
    </div>
  );
}

/* ==================== KPI CARD ==================== */
function KpiCard({ label, value, sub, color, testId }) {
  return (
    <div className="noc-panel p-3" data-testid={testId}>
      <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
      <p className="font-heading text-2xl font-bold leading-none mt-1" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-1">{sub}</p>}
    </div>
  );
}
