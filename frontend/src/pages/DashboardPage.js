import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { 
  Warning, 
  ShieldWarning, 
  CheckCircle,
  HardDrives,
  Users,
  Lightning,
  ArrowRight,
  Clock,
  CaretRight
} from "@phosphor-icons/react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { SlaGaugeWidget, ChangeTimelineWidget, UptimeHeatmapWidget, LatencyChartWidget } from "@/components/DashboardWidgets";

export default function DashboardPage() {
  const [stats, setStats] = useState({
    critical: 0, high: 0, medium: 0, low: 0,
    total_active: 0, total_clients: 0, total_devices: 0
  });
  const [trends, setTrends] = useState([]);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [liveStream, setLiveStream] = useState([]);
  const [connectors, setConnectors] = useState([]);
  const [clientId, setClientId] = useState(null);
  const wsRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchData();
    connectWebSocket();
    // Fetch first client for widgets
    axios.get(`${API}/clients`).then(r => {
      const clients = r.data?.clients || r.data || [];
      if (clients.length > 0) setClientId(clients[0].id);
    }).catch(() => {});
    return () => { if (wsRef.current) wsRef.current.close(); };
  }, []);

  const fetchData = async () => {
    try {
      const [statsRes, trendsRes, alertsRes, connectorsRes] = await Promise.all([
        axios.get(`${API}/stats/summary`),
        axios.get(`${API}/stats/trends?hours=24`),
        axios.get(`${API}/alerts?limit=20&status=active`),
        axios.get(`${API}/connector/status`).catch(() => ({ data: [] }))
      ]);
      setStats(statsRes.data);
      setTrends(trendsRes.data);
      setRecentAlerts(alertsRes.data);
      setConnectors(connectorsRes.data);
      setLiveStream(alertsRes.data.slice(0, 30).map(a => ({
        id: a.id, time: new Date(a.created_at).toLocaleTimeString("it-IT", {hour:"2-digit",minute:"2-digit",second:"2-digit"}),
        ip: a.ip_address, msg: a.message?.substring(0, 60), severity: a.severity, device: a.device_name
      })));
    } catch (error) {
      console.error("Error fetching data:", error);
    }
  };

  const connectWebSocket = () => {
    const wsUrl = process.env.REACT_APP_BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://");
    const wsToken = localStorage.getItem("noc_token");
    const wsUrlWithAuth = wsToken ? `${wsUrl}/ws/alerts?token=${wsToken}` : `${wsUrl}/ws/alerts`;
    wsRef.current = new WebSocket(wsUrlWithAuth);
    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "new_alert") {
        setRecentAlerts(prev => [data.alert, ...prev.slice(0, 19)]);
        setStats(prev => ({
          ...prev,
          [data.alert.severity]: prev[data.alert.severity] + 1,
          total_active: prev.total_active + 1
        }));
        setLiveStream(prev => [{
          id: data.alert.id, time: new Date(data.alert.created_at).toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit",second:"2-digit"}),
          ip: data.alert.ip_address, msg: data.alert.message?.substring(0, 60), severity: data.alert.severity, device: data.alert.device_name
        }, ...prev.slice(0, 29)]);
        if (data.alert.severity === "critical") {
          toast.error(`CRITICO: ${data.alert.title}`, { description: `${data.alert.device_name} - ${data.alert.client_name}` });
        }
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
  const formatHour = (h) => h ? h.split("T")[1]?.substring(0, 5) || "" : "";

  const urgentCount = stats.critical + stats.high;

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="dashboard-page">
      {/* Top Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Panoramica
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Monitoraggio in tempo reale
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--low)]/10 border border-[var(--low)]/20">
          <span className="live-dot" style={{width:6,height:6}}></span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--ok)]">Live</span>
        </div>
      </div>

      {/* Urgent Banner - only if problems exist */}
      {urgentCount > 0 && (
        <div 
          className="flex items-center justify-between p-3 rounded-lg border cursor-pointer hover:opacity-90 transition-opacity"
          style={{ background: "var(--critical-bg)", borderColor: "var(--critical-border)" }}
          onClick={() => navigate("/alerts?severity=critical")}
          data-testid="urgent-banner"
        >
          <div className="flex items-center gap-3">
            <Lightning size={20} weight="fill" className="text-[var(--critical)]" />
            <div>
              <p className="text-[var(--critical)] font-heading font-bold text-sm">
                {urgentCount} alert urgenti richiedono attenzione
              </p>
              <p className="text-[var(--text-muted)] text-xs">
                {stats.critical} critici, {stats.high} alti
              </p>
            </div>
          </div>
          <ArrowRight size={18} className="text-[var(--critical)]" />
        </div>
      )}

      {/* Severity Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SeverityCard label="Critici" value={stats.critical} color="critical" testId="metric-critical" />
        <SeverityCard label="Alti" value={stats.high} color="high" testId="metric-high" />
        <SeverityCard label="Medi" value={stats.medium} color="medium" testId="metric-medium" />
        <SeverityCard label="Bassi" value={stats.low} color="low" testId="metric-low" />
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard icon={<Lightning size={18} />} label="Alert Attivi" value={stats.total_active} />
        <StatCard icon={<Users size={18} />} label="Clienti" value={stats.total_clients} />
        <StatCard icon={<HardDrives size={18} />} label="Dispositivi" value={stats.total_devices} />
      </div>

      {/* Chart + Live Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
        <div className="lg:col-span-3 noc-panel p-4">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">
            Trend 24h
          </h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trends}>
                <defs>
                  <linearGradient id="critGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--critical)" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="var(--critical)" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="highGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--high)" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="var(--high)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="hour" tickFormatter={formatHour} stroke="var(--text-muted)" fontSize={9} fontFamily="JetBrains Mono" tickLine={false} axisLine={false} />
                <YAxis stroke="var(--text-muted)" fontSize={9} fontFamily="JetBrains Mono" tickLine={false} axisLine={false} width={25} />
                <Tooltip contentStyle={{ backgroundColor: "var(--bg-panel)", border: "1px solid var(--bg-border)", borderRadius: "0.5rem", fontFamily: "JetBrains Mono", fontSize: "11px" }} />
                <Area type="monotone" dataKey="critical" stroke="var(--critical)" strokeWidth={2} fill="url(#critGrad)" dot={false} />
                <Area type="monotone" dataKey="high" stroke="var(--high)" strokeWidth={1.5} fill="url(#highGrad)" dot={false} />
                <Line type="monotone" dataKey="medium" stroke="var(--medium)" strokeWidth={1} dot={false} opacity={0.6} />
                <Line type="monotone" dataKey="low" stroke="var(--low)" strokeWidth={1} dot={false} opacity={0.4} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="lg:col-span-2 noc-panel p-4">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">
            Live Stream
          </h3>
          <ScrollArea className="h-48">
            <div className="syslog-stream h-full" style={{border:"none",background:"transparent"}}>
              {liveStream.length === 0 ? (
                <p className="text-[var(--text-muted)] text-center py-6 text-xs">In attesa...</p>
              ) : (
                liveStream.map((e, i) => (
                  <div key={e.id + i} className="syslog-line flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{backgroundColor: getSevColor(e.severity)}}></span>
                    <span className="syslog-timestamp">{e.time}</span>
                    <span className="text-[var(--text-secondary)] truncate">{e.device || e.ip}</span>
                    <span className="text-[var(--text-muted)] truncate">{e.msg}</span>
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Connector Status */}
      {connectors.length > 0 && (
        <div className="noc-panel p-4">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">
            Connettori Attivi
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {connectors.map((c, i) => {
              const lastSeen = c.last_seen ? new Date(c.last_seen) : null;
              const isOnline = lastSeen && (Date.now() - lastSeen.getTime()) < 120000;
              return (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)]">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${isOnline ? "bg-[var(--ok)]" : "bg-[var(--critical)]"}`}></span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-[var(--text-primary)] truncate">{c.client_name || c.hostname}</p>
                    <p className="text-[10px] text-[var(--text-muted)] font-mono">
                      {c.hostname} | v{c.connector_version} | {c.traps_received} trap, {c.syslogs_received} syslog
                    </p>
                  </div>
                  <span className={`text-[10px] ${isOnline ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>
                    {isOnline ? "Online" : "Offline"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* === NEW: Enterprise Widgets === */}
      {clientId && (
        <>
          {/* SLA + Change Timeline */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <SlaGaugeWidget clientId={clientId} />
            <ChangeTimelineWidget clientId={clientId} />
          </div>

          {/* Heatmap + Latency */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <UptimeHeatmapWidget clientId={clientId} />
            <LatencyChartWidget clientId={clientId} />
          </div>
        </>
      )}

      {/* Recent Alerts Table */}
      <div className="noc-panel">
        <div className="p-3 border-b border-[var(--bg-border)] flex items-center justify-between">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest">
            Alert Attivi
          </h3>
          <Button 
            variant="ghost" size="sm" 
            onClick={() => navigate("/alerts")}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-md text-xs h-7 gap-1"
            data-testid="view-all-alerts-btn"
          >
            Tutti <CaretRight size={12} />
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="alert-table" data-testid="recent-alerts-table">
            <thead>
              <tr>
                <th>Sev.</th>
                <th>Titolo</th>
                <th>Dispositivo</th>
                <th>Cliente</th>
                <th>Ora</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {recentAlerts.length === 0 ? (
                <tr><td colSpan={6} className="text-center text-[var(--text-muted)] py-6 text-xs">Nessun alert attivo</td></tr>
              ) : (
                recentAlerts.slice(0, 8).map((alert) => (
                  <tr key={alert.id} className={alert.severity === "critical" ? "pulse-critical" : ""} data-testid={`alert-row-${alert.severity}`}>
                    <td>
                      <span className={`severity-badge severity-${alert.severity}`}>
                        {alert.severity === "critical" ? "CRIT" : alert.severity === "high" ? "HIGH" : alert.severity === "medium" ? "MED" : "LOW"}
                      </span>
                    </td>
                    <td className="cursor-pointer hover:text-[var(--text-primary)] transition-colors text-[var(--text-secondary)]" onClick={() => navigate(`/alerts/${alert.id}`)}>
                      {alert.title}
                    </td>
                    <td className="font-mono text-[var(--text-muted)] text-xs">{alert.device_name}</td>
                    <td className="text-[var(--text-secondary)] text-xs">{alert.client_name}</td>
                    <td className="font-mono text-[var(--text-muted)] text-[11px]">
                      {new Date(alert.created_at).toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"})}
                    </td>
                    <td>
                      <Button size="sm" variant="outline" onClick={() => handleAck(alert.id)}
                        className="rounded-md text-[10px] h-6 px-2 border-[var(--bg-border)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                        data-testid={`ack-btn-${alert.id}`}>
                        ACK
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SeverityCard({ label, value, color, testId }) {
  const colorMap = {
    critical: { text: "var(--critical)", bg: "var(--critical-bg)", border: "var(--critical-border)" },
    high: { text: "var(--high)", bg: "var(--high-bg)", border: "var(--high-border)" },
    medium: { text: "var(--medium)", bg: "var(--medium-bg)", border: "var(--medium-border)" },
    low: { text: "var(--low)", bg: "var(--low-bg)", border: "var(--low-border)" }
  };
  const c = colorMap[color];
  return (
    <div className="rounded-lg p-3 border transition-all duration-150 hover:scale-[1.01]"
      style={{ background: c.bg, borderColor: c.border }}
      data-testid={testId}>
      <div className="flex items-center justify-between mb-1">
        {value > 0 && color === "critical" && <span className="live-dot" style={{width:5,height:5,backgroundColor:c.text}}></span>}
        {!(value > 0 && color === "critical") && <span></span>}
      </div>
      <p className="font-heading text-3xl font-bold leading-none" style={{color:c.text}}>{value}</p>
      <p className="text-[10px] uppercase tracking-widest mt-1" style={{color:c.text,opacity:0.7}}>{label}</p>
    </div>
  );
}

function StatCard({ icon, label, value }) {
  return (
    <div className="noc-panel p-3 flex items-center gap-3">
      <div className="text-[var(--text-muted)]">{icon}</div>
      <div>
        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
        <p className="font-heading text-lg font-bold text-[var(--text-primary)]">{value}</p>
      </div>
    </div>
  );
}
