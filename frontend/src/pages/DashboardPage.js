import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Lightning, ArrowRight, CaretRight, Globe, MagnifyingGlass, ArrowClockwise, WarningCircle } from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import MobileDashboard from "@/components/MobileDashboard";
import { ClientStatusTable } from "@/components/ClientStatusTable";

export default function DashboardPage() {
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches);
  const [overview, setOverview] = useState({ clients: [], global: {} });
  const [overviewError, setOverviewError] = useState(null);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [liveStream, setLiveStream] = useState([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all, problems, ok
  const [loading, setLoading] = useState(true);
  const wsRef = useRef(null);
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    try {
      const overviewRes = await axios.get(`${API}/overview/clients`, { timeout: 60000 });
      setOverview(overviewRes.data);
      setOverviewError(null);
    } catch (e) {
      console.error("overview error:", e);
      const det = typeof e?.response?.data?.detail === "string" ? ` — ${e.response.data.detail.slice(0, 160)}` : "";
      setOverviewError(e?.response ? `HTTP ${e.response.status}${det}` : (e?.code === "ECONNABORTED" ? "timeout" : "rete"));
    }
    try {
      const alertsRes = await axios.get(`${API}/alerts?limit=20&status=active&vital_only=true`);
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
      const _a = data.alert || {};
      const _isRecovery = /recovery/i.test(_a.source_type || "") || /^(ONLINE|RIENTRATO|RIPRISTINATO|Zyxel RIPRISTINATO)/i.test(_a.title || "");
      if (data.type === "new_alert" && !_isRecovery) {
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
  const unmappedBackup = clients.filter(c => !c.backup || !c.backup.total).length;

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
          {unmappedBackup > 0 && (
            <button
              onClick={() => navigate("/settings/hornetsecurity?automap=1")}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-500/15 border border-amber-500/40 text-amber-400 hover:bg-amber-500/25 transition-all"
              title="Alcuni clienti non hanno un backup mappato — apri l'auto-mappatore"
              data-testid="unmapped-backup-badge"
            >
              <WarningCircle size={13} weight="fill" />
              {unmappedBackup} clienti senza backup · Auto-mappa
            </button>
          )}
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
        <KpiCard label="Dispositivi Vitali" value={g.total_devices || 0} sub={`${g.devices_online || 0} online`} color="#6366F1" testId="kpi-devices" />
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

      {/* Tabella compatta: una riga per cliente, solo stato ATTUALE */}
      {filtered.length > 0 && <ClientStatusTable clients={filtered} navigate={navigate} />}

      {filtered.length === 0 && !loading && (
        <div className="text-center py-12 text-[var(--text-muted)]">
          <Globe size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm" data-testid="dashboard-empty-msg">
            {overviewError ? `Panoramica non disponibile (${overviewError}) — nuovo tentativo tra 30s` : search ? "Nessun cliente trovato" : "Nessun cliente configurato"}
          </p>
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
            <table className="alert-table min-w-[640px]" data-testid="recent-alerts-table">
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
function KpiCard({ label, value, sub, color, testId }) {
  return (
    <div className="noc-panel p-3" data-testid={testId}>
      <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
      <p className="font-heading text-2xl font-bold leading-none mt-1" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-1">{sub}</p>}
    </div>
  );
}
